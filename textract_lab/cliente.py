"""Único punto de contacto con Textract: decide ONLINE (AWS + cache) u OFFLINE (fixtures).

Orden de resolución del modo: argumento `forzar` > variable LAB_MODO > credenciales
(sin credenciales → OFFLINE; el motivo se incorpora al banner de modo, que es la
primera línea de cada script; es el estado esperado de quien no tiene cuenta, no un
error). Cualquier otro error real de AWS se convierte en `ErrorAWS` con explicación
en español y la sugerencia de usar `--offline`.

Variables de entorno que entiende este módulo:
- LAB_MODO=online|offline   fuerza el modo (sin flag en la CLI).
- LAB_REGION                región (default us-east-1).
- LAB_BLOQUEAR_DEFAULT=1    guarda del ponente: si el perfil efectivo es `default` (de
                            ~/.aws) el modo online se niega con ErrorAWS. Los asistentes
                            no la definen: para ellos el perfil default es legítimo.
- AWS_EC2_METADATA_DISABLED se fija a 'true' si no existe (evita ~2 s de sondeo al
                            metadata service en laptops sin credenciales); en una EC2
                            con rol de instancia exporta AWS_EC2_METADATA_DISABLED=false.

boto3 se importa de forma perezosa: el modo offline funciona sin boto3 instalado.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

from . import consola, costos

REGION_DEFAULT = 'us-east-1'
RAIZ = Path(__file__).resolve().parent.parent  # raíz del repo (contiene textract_lab/)
DIR_FIXTURES = RAIZ / 'fixtures'
DIR_CACHE = RAIZ / 'cache'
OPERACIONES = ('detect_document_text', 'analyze_document', 'analyze_expense')
FEATURES_VALIDAS = ('FORMS', 'TABLES', 'QUERIES', 'SIGNATURES', 'LAYOUT')
MODOS = ('online', 'offline')
# Extensiones del set del taller: comparten la clave `<stem>/...`. Otras (.pdf, .tiff) llevan la
# extensión en la clave para que docs/factura_limpia.pdf no reutilice el cache del PNG.
EXTENSIONES_TALLER = ('.png', '.jpg', '.jpeg')
# Fuentes de credenciales de boto3 que dependen de un perfil de ~/.aws (ahí importa cuál es).
FUENTES_CON_PERFIL = ('shared-credentials-file', 'config-file', 'assume-role',
                      'assume-role-with-web-identity', 'sso', 'custom-process')
SUFIJO_SIDECAR = '.doc.sha256'  # cache/<clave>.doc.sha256: hash del documento con el que se grabó el cache

# Estado del proceso
_cliente_textract = None
_aviso_sin_credenciales_dado = False
_sin_credenciales = False  # se activa tras NoCredentialsError: todo lo demás va offline
MOTIVO_OFFLINE: str | None = None  # p. ej. 'sin credenciales de AWS'; lo muestra banner_modo('offline')
ULTIMA_LLAMADA: dict = {'clave': None, 'origen': None, 'costo_usd': 0.0, 'paginas': 0}


class FixtureFaltante(Exception):
    """No existe el fixture pedido en modo offline."""


class ErrorAWS(Exception):
    """Error real de AWS/boto3 envuelto con explicación en español y sugerencia --offline."""

    def __init__(self, mensaje: str, original: BaseException | None = None):
        super().__init__(mensaje)
        self.original = original


# ------------------------------------------------------------------ rutas

def stem(documento: str | Path) -> str:
    """'docs/factura_limpia.png' → 'factura_limpia'."""
    return Path(str(documento)).stem


def resolver_documento(documento: str | Path) -> Path:
    """Ruta absoluta: relativa al cwd si existe ahí, si no relativa a la raíz del repo."""
    p = Path(str(documento)).expanduser()
    if p.is_absolute() or p.exists():
        return p.resolve()
    alterna = RAIZ / p
    return alterna.resolve() if alterna.exists() else p.resolve()


def ruta_fixture(clave: str) -> Path:
    return DIR_FIXTURES / f'{clave}.json'


def ruta_cache(clave: str) -> Path:
    return DIR_CACHE / f'{clave}.json'


def ruta_sidecar_cache(clave: str) -> Path:
    """cache/<clave>.doc.sha256: hash del documento con el que se grabó cache/<clave>.json."""
    return DIR_CACHE / f'{clave}{SUFIJO_SIDECAR}'


def sha256_documento(documento: str | Path) -> str | None:
    """sha256 hex del archivo (None si no existe): detecta que la foto se repitió con el mismo nombre."""
    ruta = resolver_documento(documento)
    if not ruta.is_file():
        return None
    h = hashlib.sha256()
    with ruta.open('rb') as fh:
        for trozo in iter(lambda: fh.read(1 << 20), b''):
            h.update(trozo)
    return h.hexdigest()


def cache_vigente(documento: str | Path, clave: str) -> tuple[dict | None, str]:
    """(respuesta en cache, motivo). Respuesta None si no hay cache o si el documento cambió.

    El cache es válido si no hay sidecar (cache antiguo o documento ausente) o si el sidecar coincide
    con el sha256 actual del documento. Si difiere, el cache está obsoleto (misma ruta, otro contenido:
    p. ej. la foto del sábado repetida con el mismo nombre) y se vuelve a pedir a Textract.
    """
    en_cache = leer_json(ruta_cache(clave))
    if en_cache is None:
        return None, 'sin cache'
    sidecar = ruta_sidecar_cache(clave)
    if not sidecar.exists():
        return en_cache, 'cache sin sidecar'
    actual = sha256_documento(documento)
    if actual is None:
        return en_cache, 'documento ausente en disco'
    grabado = sidecar.read_text(encoding='utf-8').strip()
    if grabado and grabado != actual:
        return None, 'el documento cambió desde que se grabó el cache'
    return en_cache, 'cache vigente'


def hash_queries(queries: list[dict]) -> str:
    """hash8 de §7: sha256(json.dumps(queries, sort_keys=True, ensure_ascii=True))[:8]."""
    return hashlib.sha256(json.dumps(queries, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:8]


def _nombre_clave(documento: str | Path) -> str:
    """Primer segmento de la clave: 'factura_limpia' para .png/.jpg; 'factura_limpia.pdf' para otras extensiones."""
    p = Path(str(documento))
    sufijo = p.suffix.lower()
    if sufijo and sufijo not in EXTENSIONES_TALLER:
        return f'{p.stem}{sufijo}'
    return p.stem


def clave_llamada(documento: str | Path, operacion: str, feature_types: list[str] | None = None,
                  queries: list[dict] | None = None) -> str:
    """'<stem>/<operacion>[__<FEATURES ordenadas unidas por _>][__<hash8>]'.

    Para documentos que no son .png/.jpg del taller (por ejemplo .pdf) el primer segmento lleva la
    extensión ('factura_limpia.pdf/detect_document_text') para no compartir cache con el PNG.
    """
    clave = f'{_nombre_clave(documento)}/{operacion}'
    if feature_types:
        clave += '__' + '_'.join(sorted(f.upper() for f in feature_types))
    if queries:
        clave += '__' + hash_queries(queries)
    return clave


# --------------------------------------------------------------- lectura

def leer_json(ruta: str | Path) -> dict | None:
    """Lee <ruta>.json o <ruta>.json.gz (devuelve None si no existe ninguno)."""
    ruta = Path(ruta)
    candidatas = [ruta, Path(str(ruta) + '.gz')] if ruta.suffix == '.json' else [ruta]
    for r in candidatas:
        if r.exists():
            if r.suffix == '.gz':
                with gzip.open(r, 'rt', encoding='utf-8') as fh:
                    return json.load(fh)
            return json.loads(r.read_text(encoding='utf-8'))
    return None


def escribir_json(ruta: str | Path, datos: dict, comprimir: bool = False) -> Path:
    """Guarda JSON minificado (opcionalmente .gz). Devuelve la ruta escrita."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(datos, ensure_ascii=False, separators=(',', ':'), default=str)
    if comprimir:
        ruta = Path(str(ruta) + '.gz') if ruta.suffix != '.gz' else ruta
        with gzip.open(ruta, 'wt', encoding='utf-8') as fh:
            fh.write(texto)
    else:
        ruta.write_text(texto, encoding='utf-8')
    return ruta


def meta_fixtures() -> dict:
    """Contenido de fixtures/META.json (o un dict vacío si no existe)."""
    try:
        return json.loads((DIR_FIXTURES / 'META.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------- credenciales

def _region() -> str:
    return os.environ.get('LAB_REGION', REGION_DEFAULT)


def _sesion():
    """boto3.Session respetando AWS_PROFILE (import perezoso).

    Sin credenciales, la cadena de boto3 termina sondeando el metadata service de EC2
    (169.254.169.254) con ~2 s de espera antes de rendirse. En una laptop eso es pantalla en blanco;
    se desactiva por omisión salvo que el proceso corra con credenciales de contenedor (CloudShell,
    ECS) o que el usuario ya haya fijado la variable (en una EC2 con rol: AWS_EC2_METADATA_DISABLED=false).
    """
    import boto3  # noqa: WPS433 (perezoso a propósito)

    if not (os.environ.get('AWS_CONTAINER_CREDENTIALS_FULL_URI')
            or os.environ.get('AWS_CONTAINER_CREDENTIALS_RELATIVE_URI')):
        os.environ.setdefault('AWS_EC2_METADATA_DISABLED', 'true')
    perfil = os.environ.get('AWS_PROFILE')
    return boto3.Session(profile_name=perfil) if perfil else boto3.Session()


def info_credenciales() -> dict:
    """{'perfil', 'fuente', 'region', 'tiene_credenciales'} sin llamar a AWS."""
    info = {'perfil': os.environ.get('AWS_PROFILE'), 'fuente': None,
            'region': _region(), 'tiene_credenciales': False, 'error': None}
    try:
        sesion = _sesion()
        cred = sesion.get_credentials()
        if cred is not None:
            info['tiene_credenciales'] = True
            info['fuente'] = getattr(cred, 'method', None) or 'desconocida'
            info['perfil'] = info['perfil'] or getattr(sesion, 'profile_name', None)
    except ImportError:
        info['fuente'] = 'boto3 no instalado'
    except Exception as e:  # ProfileNotFound, PartialCredentialsError, etc.: error de configuración
        info['fuente'] = f'error: {type(e).__name__}'
        info['error'] = e
    return info


def _descripcion_fixtures() -> str:
    """'fixtures SINTÉTICOS generados 2026-09-03' o 'fixtures reales grabados <fecha>' según META.json."""
    meta = meta_fixtures()
    if meta.get('origen') == 'textract':
        return f'fixtures reales grabados {meta.get("generado", "?")}'
    return f'fixtures SINTÉTICOS generados {meta.get("generado", "?")}'


def _avisar_offline(motivo: str) -> None:
    """Aviso amarillo (una vez por proceso) cuando se cae a offline DESPUÉS de haber impreso el banner."""
    global _aviso_sin_credenciales_dado, MOTIVO_OFFLINE
    MOTIVO_OFFLINE = motivo
    if not _aviso_sin_credenciales_dado:
        _aviso_sin_credenciales_dado = True
        consola.aviso(f'[OFFLINE] {motivo}: usando fixtures/ ({_descripcion_fixtures()})')


def bloqueo_perfil_default() -> bool:
    """True si LAB_BLOQUEAR_DEFAULT está activa (guarda del ponente: nunca gastar en el perfil default)."""
    return os.environ.get('LAB_BLOQUEAR_DEFAULT', '').strip().lower() in ('1', 'true', 'si', 'sí', 'yes', 'on')


def usa_perfil_default(info: dict | None = None) -> bool:
    """True si las credenciales salen del perfil 'default' de ~/.aws (no de variables de entorno ni contenedor)."""
    info = info if info is not None else info_credenciales()
    return bool(info.get('tiene_credenciales')) and (info.get('perfil') or 'default') == 'default' \
        and (info.get('fuente') or '') in FUENTES_CON_PERFIL


def _verificar_bloqueo_default(info: dict | None = None) -> None:
    """Lanza ErrorAWS si LAB_BLOQUEAR_DEFAULT está activa y el perfil efectivo es 'default'."""
    if bloqueo_perfil_default() and usa_perfil_default(info):
        raise ErrorAWS("perfil 'default' bloqueado por LAB_BLOQUEAR_DEFAULT: exporta AWS_PROFILE=personal "
                       f"(o unset LAB_BLOQUEAR_DEFAULT)\npara continuar sin AWS: python3 {_nombre_script()} --offline")


def resolver_modo(forzar: str | None = None) -> str:
    """'online' | 'offline'. Orden: forzar > LAB_MODO > credenciales (None → offline; el motivo va al banner)."""
    global MOTIVO_OFFLINE
    if forzar:
        f = forzar.lower()
        if f not in MODOS:
            raise ValueError(f'modo inválido: {forzar!r} (usa online u offline)')
        if f == 'online' and _sin_credenciales:
            return 'offline'
        if f == 'online':
            _verificar_bloqueo_default()
        return f
    env = os.environ.get('LAB_MODO', '').strip().lower()
    if env in MODOS:
        if env == 'online':
            _verificar_bloqueo_default()
        return env
    if env:
        consola.aviso(f'LAB_MODO={env!r} no es online/offline; se ignora')
    if _sin_credenciales:
        return 'offline'
    info = info_credenciales()
    if info.get('error') is not None:
        # Perfil inexistente o credenciales a medias: error de configuración, se muestra (no se oculta).
        raise _envolver_error(info['error'], '')
    if not info['tiene_credenciales']:
        # No se imprime aquí: el banner (primera línea del script) incorpora el motivo.
        MOTIVO_OFFLINE = 'sin credenciales de AWS'
        return 'offline'
    _verificar_bloqueo_default(info)
    return 'online'


def banner_modo(modo: str) -> str:
    """'[ONLINE us-east-1 · perfil personal]' o '[OFFLINE · sin credenciales de AWS · fixtures SINTÉTICOS generados 2026-09-03]'.

    En offline incluye el motivo (MOTIVO_OFFLINE) cuando el modo no fue pedido explícitamente, para que
    la primera línea de cada script lo diga sin necesitar un aviso previo.
    """
    global _aviso_sin_credenciales_dado
    if modo == 'online':
        perfil = os.environ.get('AWS_PROFILE') or info_credenciales().get('perfil') or 'default'
        return f'[ONLINE {_region()} · perfil {perfil}]'
    motivo = f' · {MOTIVO_OFFLINE}' if MOTIVO_OFFLINE else ''
    if MOTIVO_OFFLINE:
        _aviso_sin_credenciales_dado = True  # el banner ya lo dijo: no repetir el aviso amarillo
    return f'[OFFLINE{motivo} · {_descripcion_fixtures()}]'


# ------------------------------------------------------------------ cliente

def textract_client():
    """Cliente boto3 de Textract en LAB_REGION con reintentos 'standard' (máx. 10 intentos)."""
    global _cliente_textract
    if _cliente_textract is None:
        import boto3
        from botocore.config import Config

        _cliente_textract = _sesion().client(
            'textract',
            region_name=_region(),
            config=Config(retries={'total_max_attempts': 10, 'mode': 'standard'}),
        )
    return _cliente_textract


def _nombre_script() -> str:
    try:
        nombre = Path(sys.argv[0]).name
    except Exception:
        nombre = ''
    return nombre if nombre and nombre not in ('-', '-c') else '<script>.py'


def explicar_error(e: BaseException, operacion: str = '') -> str:
    """Una línea en español que explica el error de AWS/boto3."""
    nombre = type(e).__name__
    codigo = ''
    try:
        codigo = e.response.get('Error', {}).get('Code', '')  # ClientError
    except AttributeError:
        pass
    api = {'detect_document_text': 'DetectDocumentText', 'analyze_document': 'AnalyzeDocument',
           'analyze_expense': 'AnalyzeExpense'}.get(operacion, operacion)
    region = _region()
    tabla = {
        'AccessDeniedException': f'tu política IAM no permite textract:{api}',
        'UnrecognizedClientException': 'credenciales inválidas (revisa AWS_PROFILE o las claves)',
        'InvalidSignatureException': 'firma inválida: credenciales incorrectas o reloj desajustado',
        'ExpiredTokenException': 'el token de sesión caducó: vuelve a iniciar sesión (SSO/STS)',
        'ExpiredToken': 'el token de sesión caducó: vuelve a iniciar sesión (SSO/STS)',
        'ThrottlingException': 'Textract está limitando las llamadas (TPS) incluso tras 10 reintentos: espera unos segundos',
        'ProvisionedThroughputExceededException': 'cuota de TPS excedida incluso tras reintentos: espera unos segundos',
        'LimitExceededException': 'límite de servicio excedido',
        'InvalidParameterException': 'parámetro inválido (¿query no ASCII, más de 15 queries o FeatureTypes vacío?)',
        'UnsupportedDocumentException': 'formato no soportado: usa PNG/JPEG o PDF/TIFF de UNA página',
        'BadDocumentException': 'Textract no pudo leer el documento (¿corrupto o vacío?)',
        'DocumentTooLargeException': 'el documento supera 10 MB (límite de las llamadas síncronas)',
        'InvalidS3ObjectException': 'objeto S3 inválido o inaccesible',
        'InternalServerError': 'error interno de Textract: reintenta',
        'EndpointConnectionError': f'sin conexión con Textract en {region} (¿wifi? ¿región válida? Textract no existe en sa-east-1)',
        'ConnectTimeoutError': f'tiempo de espera agotado conectando a {region}',
        'ReadTimeoutError': 'tiempo de espera agotado leyendo la respuesta',
        'SSLError': 'error SSL (¿proxy o red corporativa?)',
        'ParamValidationError': 'parámetros inválidos para boto3 (revisa FeatureTypes/QueriesConfig)',
        'ProfileNotFound': f'el perfil AWS_PROFILE={os.environ.get("AWS_PROFILE")!r} no existe en ~/.aws/config',
        'PartialCredentialsError': 'credenciales incompletas (falta access key o secret)',
        'NoRegionError': 'falta la región: exporta LAB_REGION=us-east-1',
        'InvalidRegionError': f'región inválida: {region!r}',
    }
    explicacion = tabla.get(codigo) or tabla.get(nombre) or 'error inesperado de AWS'
    detalle = str(e).strip().replace('\n', ' ')
    if len(detalle) > 220:
        detalle = detalle[:217] + '...'
    etiqueta = codigo or nombre
    return f'{etiqueta}: {explicacion}. Detalle: {detalle}'


def _envolver_error(e: BaseException, operacion: str) -> ErrorAWS:
    msg = explicar_error(e, operacion)
    return ErrorAWS(f'{msg}\npara continuar sin AWS: python3 {_nombre_script()} --offline', e)


# ------------------------------------------------------------------ llamar

def _fixture_alternativo(documento, operacion, feature_types, queries) -> tuple[Path | None, str]:
    """En offline con queries distintas al set del taller: fixture del set fijo si existe."""
    from . import queries as q_mod

    for nombre, set_fijo in q_mod.SETS_DEL_TALLER.items():
        if queries == set_fijo:
            continue
        clave = clave_llamada(documento, operacion, feature_types, set_fijo)
        if leer_json(ruta_fixture(clave)) is not None:
            return ruta_fixture(clave), nombre
    return None, ''


def _leer_offline(documento, operacion, feature_types, queries, silencioso) -> dict:
    clave = clave_llamada(documento, operacion, feature_types, queries)
    resp = leer_json(ruta_fixture(clave))
    if resp is None and _nombre_clave(documento) != stem(documento):
        # docs/factura_limpia.pdf no tiene fixture propio: se usa el del PNG del mismo nombre (mismo contenido).
        clave_png = clave.replace(f'{_nombre_clave(documento)}/', f'{stem(documento)}/', 1)
        resp = leer_json(ruta_fixture(clave_png))
        if resp is not None:
            if not silencioso:
                consola.aviso(f'{Path(str(documento)).name}: no hay fixture propio; usando el de '
                              f'{stem(documento)}.png (mismo documento en otra extensión)')
            clave = clave_png
    if resp is None and queries:
        ruta_alt, nombre = _fixture_alternativo(documento, operacion, feature_types, queries)
        if ruta_alt is not None:
            if not silencioso:
                consola.aviso(f'en modo offline solo existe el set de queries del taller ({nombre}); '
                              f'usando {ruta_alt.relative_to(RAIZ)}. Experimentar con queries propias requiere credenciales.')
            resp = leer_json(ruta_alt)
    if resp is None:
        esperada = ruta_fixture(clave).relative_to(RAIZ)
        raise FixtureFaltante(
            f'no existe el fixture {esperada} (ni .gz) para {stem(documento)}. '
            f'En modo offline solo están los documentos del taller; para este documento '
            f'necesitas credenciales (--online) o grabarlo con tools/grabar_fixtures.py.'
        )
    ULTIMA_LLAMADA.update(clave=clave, origen='fixture', costo_usd=0.0,
                          paginas=int((resp.get('DocumentMetadata') or {}).get('Pages', 1) or 1))
    return resp


def _parametros(documento: Path, operacion: str, feature_types, queries) -> dict:
    if not documento.exists():
        raise FileNotFoundError(f'no existe el documento {documento}')
    datos = documento.read_bytes()
    if len(datos) > 10 * 1024 * 1024:
        raise ErrorAWS(f'{documento.name} pesa {len(datos) / 1e6:.1f} MB: el límite síncrono es 10 MB')
    params: dict = {'Document': {'Bytes': datos}}
    if operacion == 'analyze_document':
        features = [f.upper() for f in (feature_types or [])]
        if queries and 'QUERIES' not in features:
            features.append('QUERIES')
        if not features:
            raise ValueError('analyze_document requiere feature_types (FORMS, TABLES, QUERIES, LAYOUT, SIGNATURES)')
        for f in features:
            if f not in FEATURES_VALIDAS:
                raise ValueError(f'FeatureType desconocido: {f}')
        if 'QUERIES' in features and not queries:
            # boto3 lo deja pasar (QueriesConfig es opcional en el modelo) pero Textract responde
            # InvalidParameterException: QUERIES exige QueriesConfig con al menos una query.
            raise ValueError('FeatureTypes incluye QUERIES pero no se pasaron queries: Textract exige '
                             'QueriesConfig (usa queries=[{"Text": ..., "Alias": ...}] o quita QUERIES)')
        params['FeatureTypes'] = features
        if queries:
            from . import queries as q_mod

            q_mod.validar_queries(queries)
            params['QueriesConfig'] = {'Queries': [{k: v for k, v in q.items() if k in ('Text', 'Alias', 'Pages')}
                                                   for q in queries]}
    return params


def llamar(operacion: str, documento: str | Path, *, feature_types: list[str] | None = None,
           queries: list[dict] | None = None, modo: str | None = None, silencioso: bool = False) -> dict:
    """Ejecuta una operación síncrona de Textract (o lee el fixture/cache equivalente).

    operacion ∈ {'detect_document_text', 'analyze_document', 'analyze_expense'}.
    - offline: fixtures/<clave>.json(.gz); si falta → FixtureFaltante.
    - online: cache/<clave>.json si existe (imprime '[CACHE]'); si no, llama a Textract con
      Document={'Bytes': ...}, guarda el cache minificado y registra el costo.
    - NoCredentialsError → cambia a offline con aviso amarillo (una sola vez por proceso).
    - Cualquier otro error de boto3/botocore → ErrorAWS con explicación y sugerencia '--offline'.
    """
    global _sin_credenciales
    if operacion not in OPERACIONES:
        raise ValueError(f'operación desconocida: {operacion!r} (usa {", ".join(OPERACIONES)})')
    if operacion != 'analyze_document' and (feature_types or queries):
        feature_types, queries = None, None  # solo AnalyzeDocument admite features/queries
    if feature_types:
        feature_types = [f.upper() for f in feature_types]
        if queries and 'QUERIES' not in feature_types:
            feature_types = feature_types + ['QUERIES']
    elif queries:
        feature_types = ['QUERIES']

    modo_real = resolver_modo(modo)
    if modo_real == 'offline':
        return _leer_offline(documento, operacion, feature_types, queries, silencioso)

    clave = clave_llamada(documento, operacion, feature_types, queries)
    en_cache, motivo_cache = cache_vigente(documento, clave)
    if en_cache is not None:
        if not silencioso:
            print(f'[CACHE] {clave}', flush=True)
        ULTIMA_LLAMADA.update(clave=clave, origen='cache', costo_usd=0.0,
                              paginas=int((en_cache.get('DocumentMetadata') or {}).get('Pages', 1) or 1))
        return en_cache
    if motivo_cache == 'el documento cambió desde que se grabó el cache' and not silencioso:
        consola.aviso(f'cache/{clave}.json es de otra versión de {Path(str(documento)).name} '
                      f'(el archivo cambió): se vuelve a pedir a Textract')

    ruta_doc = resolver_documento(documento)
    params = _parametros(ruta_doc, operacion, feature_types, queries)

    try:
        from botocore import exceptions as bexc
    except ImportError as e:
        raise ErrorAWS(f'boto3 no está instalado ({e}). Instala con: pip install -r requirements.txt\n'
                       f'para continuar sin AWS: python3 {_nombre_script()} --offline', e) from e
    try:
        cliente = textract_client()
        resp = getattr(cliente, operacion)(**params)
    except bexc.NoCredentialsError:
        # Estado esperado de quien no tiene cuenta: no es un error, se cae a fixtures (aviso una vez).
        _sin_credenciales = True
        _avisar_offline('sin credenciales de AWS')
        return _leer_offline(documento, operacion, feature_types, queries, silencioso)
    except (bexc.BotoCoreError, bexc.ClientError) as e:
        # Cualquier otro error real (AccessDenied, sin red, throttling, query no ASCII...) se muestra.
        raise _envolver_error(e, operacion) from e

    paginas = int((resp.get('DocumentMetadata') or {}).get('Pages', 1) or 1)
    try:
        escribir_json(ruta_cache(clave), resp)
        huella = sha256_documento(ruta_doc)
        if huella:
            ruta_sidecar_cache(clave).write_text(huella + '\n', encoding='utf-8')
    except OSError as e:
        if not silencioso:
            consola.aviso(f'no se pudo escribir el cache {ruta_cache(clave)}: {e}')
    costos.registrar(operacion, feature_types, paginas)
    ULTIMA_LLAMADA.update(clave=clave, origen='aws', paginas=paginas,
                          costo_usd=costos.costo(operacion, feature_types, paginas))
    if not silencioso:
        print(f'[AWS {_region()}] {operacion} {stem(documento)} → cache/{clave}.json '
              f'({costos.formatear(ULTIMA_LLAMADA["costo_usd"])})', flush=True)
    return resp


def hay_fixture(documento: str | Path, operacion: str, feature_types=None, queries=None) -> bool:
    """True si existe el fixture (o el cache) para esa clave; no llama a AWS.

    Ojo: en modo online llamar() solo consulta cache/; para saber si una llamada online costará
    dinero usa hay_cache().
    """
    clave = clave_llamada(documento, operacion, feature_types, queries)
    return leer_json(ruta_fixture(clave)) is not None or leer_json(ruta_cache(clave)) is not None


def hay_cache(documento: str | Path, operacion: str, feature_types=None, queries=None) -> bool:
    """True si existe cache/<clave>.json VIGENTE (lo único que evita una llamada real en modo online)."""
    if feature_types:
        feature_types = [f.upper() for f in feature_types]
        if queries and 'QUERIES' not in feature_types:
            feature_types = feature_types + ['QUERIES']
    elif queries:
        feature_types = ['QUERIES']
    clave = clave_llamada(documento, operacion, feature_types, queries)
    return cache_vigente(documento, clave)[0] is not None
