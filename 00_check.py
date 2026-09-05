#!/usr/bin/env python3
"""Checkpoint 0 — verifica tu cuenta, tu región y tu modo (ONLINE u OFFLINE).

Qué hace:
- Imprime la versión de Python y de boto3, el perfil y la fuente de credenciales
  que encontró boto3, la región del taller y el modo resuelto.
- ONLINE: `sts:GetCallerIdentity` (no requiere permisos IAM) para mostrar tu
  account id y ARN, y UNA llamada `DetectDocumentText` a docs/mini.png (~40 KB,
  US$ 0.0015 aprox.; la segunda vez sale de cache/).
- OFFLINE: no toca AWS. Valida fixtures/MANIFEST.sha256 (detecta clones corruptos)
  y muestra fixtures/META.json (fixtures sintéticos o reales).
- Termina con la palabra LISTO (código de salida 0). Error de AWS: línea roja y
  código 2. Otro error: código 1.

Ejemplos:
    python3 00_check.py                 # decide el modo según haya credenciales
    python3 00_check.py --offline       # sin AWS (ni siquiera hace falta boto3)
    python3 00_check.py --online        # fuerza AWS (AWS_PROFILE=personal recomendado)
    python3 00_check.py --costo         # páginas consumidas y costo aproximado de la sesión
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import sys
from pathlib import Path


def _raiz_repo() -> Path:
    """Sube desde este archivo hasta encontrar textract_lab/ (funciona desde cualquier cwd)."""
    aqui = Path(__file__).resolve()
    for p in (aqui.parent, *aqui.parents):
        if (p / 'textract_lab' / '__init__.py').exists():
            return p
    raise SystemExit('✘ no encuentro textract_lab/: ejecuta este script dentro del repo textract-ec')


RAIZ = _raiz_repo()
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import bloques, cliente, consola, costos  # noqa: E402

DOC_MINI = RAIZ / 'docs' / 'mini.png'
MANIFEST = RAIZ / 'fixtures' / 'MANIFEST.sha256'
META = RAIZ / 'fixtures' / 'META.json'
FUENTES_CON_PERFIL = cliente.FUENTES_CON_PERFIL  # fuentes de credenciales que dependen de un perfil de ~/.aws


# ------------------------------------------------------------------ utilidades

def version_boto3_sin_importar() -> str:
    """Versión de boto3 leyendo los metadatos del paquete (no lo importa: sirve en offline sin boto3)."""
    try:
        from importlib import metadata
        return metadata.version('boto3')
    except Exception:  # PackageNotFoundError o entorno raro
        return ''


def imprimir_entorno(modo: str) -> None:
    consola.titulo('Entorno')
    py = platform.python_version()
    if sys.version_info < (3, 10) and modo == 'offline':
        # En offline el kit funciona igual con 3.9 (solo stdlib): no es un error, solo un aviso para el modo online.
        consola.aviso(f'Python {py}: sirve para el modo OFFLINE; para el modo online necesitas 3.10 o superior '
                      '(boto3 dejó de soportar 3.9 en abril de 2026)')
    elif sys.version_info < (3, 10):
        consola.error(f'Python {py}: boto3 dejó de soportar 3.9 en abril de 2026; necesitas 3.10 o superior '
                      '(o sigue con --offline, que funciona con 3.9)')
    else:
        print(f'Python {py} ({platform.system()} {platform.machine()})')
    b3 = version_boto3_sin_importar()
    if b3:
        print(f'boto3 {b3}')
    elif modo == 'offline':
        consola.aviso('boto3 no instalado: no hace falta en modo offline (pip install boto3 para el modo online)')
    else:
        consola.error('boto3 no instalado: pip install -r requirements.txt (o sigue con --offline)')
    region = os.environ.get('LAB_REGION', cliente.REGION_DEFAULT)
    print(f'región: {region}  (Textract no existe en sa-east-1; cambia solo con LAB_REGION)')


def imprimir_credenciales(modo: str) -> dict:
    """Perfil y fuente de credenciales. En offline NO importa boto3."""
    consola.titulo('Credenciales')
    perfil_env = os.environ.get('AWS_PROFILE')
    if modo == 'offline':
        print(f'AWS_PROFILE: {perfil_env or "(no definido)"}')
        print('modo OFFLINE: no se usan credenciales ni se llama a AWS')
        return {'perfil': perfil_env, 'fuente': None, 'tiene_credenciales': False}
    info = cliente.info_credenciales()
    if info.get('error') is not None:
        raise cliente.ErrorAWS(cliente.explicar_error(info['error']) +
                               '\npara continuar sin AWS: python3 00_check.py --offline', info['error'])
    print(f'AWS_PROFILE: {perfil_env or "(no definido → boto3 usa el perfil default o el entorno)"}')
    print(f'perfil efectivo: {info.get("perfil") or "(ninguno)"}')
    print(f'fuente de credenciales (boto3.Session().get_credentials().method): {info.get("fuente") or "(ninguna)"}')
    if cliente.usa_perfil_default(info):
        # Para un asistente el perfil default de ~/.aws (lo que deja `aws configure`) es legítimo: amarillo, no rojo.
        # El ponente se protege con LAB_BLOQUEAR_DEFAULT=1 (cliente.resolver_modo ya habría lanzado ErrorAWS).
        consola.aviso("usando el perfil 'default' de ~/.aws: si tienes varios perfiles, elige uno con "
                      "export AWS_PROFILE=<nombre> (ver .env.example)")
    return info


# ------------------------------------------------------------------ online

def verificar_online() -> str:
    """sts:GetCallerIdentity + 1 DetectDocumentText a docs/mini.png. Devuelve el modo final."""
    consola.titulo('Identidad (sts:GetCallerIdentity, sin permisos IAM)')
    try:
        import boto3
        from botocore import exceptions as bexc
    except ImportError as e:
        raise cliente.ErrorAWS(f'boto3 no está instalado ({e}). pip install -r requirements.txt\n'
                               'para continuar sin AWS: python3 00_check.py --offline', e) from e
    region = os.environ.get('LAB_REGION', cliente.REGION_DEFAULT)
    perfil = os.environ.get('AWS_PROFILE')
    try:
        sesion = boto3.Session(profile_name=perfil) if perfil else boto3.Session()
        identidad = sesion.client('sts', region_name=region).get_caller_identity()
    except bexc.NoCredentialsError:
        consola.aviso('sin credenciales de AWS: no es un error, sigo en modo OFFLINE con fixtures/')
        return 'offline'
    except (bexc.BotoCoreError, bexc.ClientError) as e:
        raise cliente.ErrorAWS(cliente.explicar_error(e, 'sts') +
                               '\npara continuar sin AWS: python3 00_check.py --offline', e) from e
    print(f'cuenta:    {identidad.get("Account")}')
    print(f'identidad: {identidad.get("Arn")}')
    print(f'región:    {region}')

    consola.titulo(f'DetectDocumentText sobre {DOC_MINI.relative_to(RAIZ)} (1 página, US$ 0.0015 aprox.)')
    resp = cliente.llamar('detect_document_text', DOC_MINI, modo='online')
    if cliente.ULTIMA_LLAMADA.get('origen') == 'fixture':
        # llamar() cayó a offline por NoCredentialsError (aviso ya impreso).
        return 'offline'
    mostrar_mini(resp)
    return 'online'


def mostrar_mini(resp: dict) -> None:
    lineas = bloques.lineas(resp)
    for txt, conf in lineas:
        print(f'  {consola.confianza_coloreada(conf)}  {txt}')
    media = bloques.confianza_media(resp, 'LINE')
    print(f'{len(lineas)} líneas · confianza media LINE {consola.confianza_coloreada(media)}')
    texto = ' '.join(t for t, _ in lineas)
    if any(c in texto for c in 'ñáéíóú¿'):
        consola.ok('español con tildes y ñ leído correctamente')
    else:
        consola.aviso('no aparecen tildes/ñ en la respuesta: revisa que docs/mini.png sea el del taller')
    origen = {'aws': 'llamada real a Textract', 'cache': 'cache/ (sin costo)', 'fixture': 'fixtures/'}
    print(f'origen de la respuesta: {origen.get(cliente.ULTIMA_LLAMADA.get("origen"), "?")}')


# ----------------------------------------------------------------- offline

def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open('rb') as fh:
        for trozo in iter(lambda: fh.read(1 << 20), b''):
            h.update(trozo)
    return h.hexdigest()


def validar_manifest() -> bool:
    """Compara cada línea 'sha256  ruta' de MANIFEST.sha256 con el archivo real. True si todo coincide."""
    consola.titulo('Fixtures (fixtures/MANIFEST.sha256)')
    if not MANIFEST.exists():
        consola.error(f'no existe {MANIFEST.relative_to(RAIZ)}: clona de nuevo el repo o ejecuta tools/gen_fixtures_sinteticos.py')
        return False
    ok, malos, faltan = 0, [], []
    listados: set[Path] = set()
    for linea in MANIFEST.read_text(encoding='utf-8').splitlines():
        linea = linea.strip()
        if not linea or linea.startswith('#'):
            continue
        partes = linea.split(maxsplit=1)
        if len(partes) != 2:
            malos.append(f'línea ilegible: {linea[:60]}')
            continue
        esperado, rel = partes[0].lower(), partes[1].strip().lstrip('*')
        ruta = RAIZ / rel
        listados.add(ruta.resolve())
        if not ruta.exists():
            faltan.append(rel)
        elif sha256_de(ruta) != esperado:
            malos.append(rel)
        else:
            ok += 1
    for rel in faltan:
        consola.error(f'falta el fixture {rel}')
    for rel in malos:
        consola.error(f'hash distinto (archivo modificado o clone corrupto): {rel}')
    # Fixtures presentes que nadie lista: no es error, pero conviene saberlo.
    sin_listar = [p for p in (RAIZ / 'fixtures').rglob('*.json*')
                  if p.name != 'META.json' and p.resolve() not in listados]
    for p in sorted(sin_listar):
        consola.aviso(f'fixture no listado en el MANIFEST: {p.relative_to(RAIZ)}')
    documentos = sorted(d.name for d in (RAIZ / 'fixtures').iterdir() if d.is_dir() and d.name != 'bedrock')
    n_textract = sum(1 for d in documentos for _ in (RAIZ / 'fixtures' / d).glob('*.json*'))
    n_bedrock = len(list((RAIZ / 'fixtures' / 'bedrock').glob('*.json*'))) if (RAIZ / 'fixtures' / 'bedrock').exists() else 0
    print(f'fixtures: {len(documentos)} documentos ({", ".join(documentos)}) · '
          f'{n_textract} respuestas de Textract + {n_bedrock} de Bedrock')
    if malos or faltan:
        consola.error(f'MANIFEST con diferencias ({ok} OK, {len(malos)} distintos, {len(faltan)} faltan): '
                      f'git checkout -- fixtures/ o vuelve a clonar')
        return False
    consola.ok(f'MANIFEST OK: {ok} archivos con el hash esperado')
    return True


def mostrar_meta() -> None:
    meta = cliente.meta_fixtures()
    if not meta:
        consola.aviso(f'no se pudo leer {META.relative_to(RAIZ)}')
        return
    origen = meta.get('origen', '?')
    etiqueta = 'SINTÉTICOS (forma de Textract, NO salidas reales)' if origen == 'sintetico' else f'reales ({origen})'
    print(f'origen: {etiqueta}')
    print(f'generados: {meta.get("generado", "?")} por {meta.get("generador", "?")}')
    if meta.get('region'):
        # tools/grabar_fixtures.py escribe 'cuenta_ultimos4' y 'modelo_textract' como dict {Versión: valor}.
        cuenta = meta.get('cuenta_ultimos4') or meta.get('cuenta') or '?'
        modelo = meta.get('modelo_textract') or '?'
        if isinstance(modelo, dict):
            modelo = ', '.join(f'{k}={v}' for k, v in modelo.items()) or '?'
        print(f'región: {meta["region"]} · cuenta ...{cuenta} · modelo Textract {modelo}')
    if meta.get('nota'):
        print(f'nota: {meta["nota"]}')
    errores = meta.get('errores_inyectados') or {}
    for doc, lista in errores.items():
        print(f'errores inyectados en {doc}:')
        for e in lista:
            print(f'  - {e}')


def verificar_offline() -> bool:
    manifest_ok = validar_manifest()
    consola.titulo('fixtures/META.json')
    mostrar_meta()
    consola.titulo(f'DetectDocumentText sobre {DOC_MINI.relative_to(RAIZ)} (desde fixtures/, US$ 0)')
    resp = cliente.llamar('detect_document_text', DOC_MINI, modo='offline')
    mostrar_mini(resp)
    return manifest_ok


# --------------------------------------------------------------------- costo

def imprimir_costo() -> None:
    acumulado = costos.acumulado()
    consola.titulo('Costo de la sesión (llamadas reales; cache y fixtures no cuentan)')
    print(f'llamadas: {acumulado["llamadas"]} · páginas: {acumulado["paginas"]} · '
          f'{costos.formatear(acumulado["usd"])}  [{acumulado["nota"]}]')
    print(f'acumulado en {costos.ruta_acumulado().relative_to(RAIZ)}')


# ---------------------------------------------------------------------- main

def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument('--offline', action='store_true', help='no llamar a AWS: valida fixtures/ y META.json')
    g.add_argument('--online', action='store_true', help='forzar AWS (sts + 1 DetectDocumentText a docs/mini.png)')
    p.add_argument('--costo', action='store_true', help='solo mostrar el costo acumulado de la sesión y salir')
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parsear_args(argv)
    if args.costo:
        imprimir_costo()
        return 0
    forzar = 'offline' if args.offline else 'online' if args.online else None
    modo = cliente.resolver_modo(forzar)  # puede lanzar ErrorAWS (perfil inexistente, etc.)
    print(consola.color(cliente.banner_modo(modo), 'negrita'), flush=True)

    imprimir_entorno(modo)
    imprimir_credenciales(modo)
    todo_bien = True
    if modo == 'online':
        modo = verificar_online()
        if modo == 'offline':
            print(consola.color(cliente.banner_modo('offline'), 'negrita'))
    if modo == 'offline':
        todo_bien = verificar_offline()
    imprimir_costo()

    print()
    if not todo_bien:
        consola.error('revisa los errores de arriba antes de seguir (el resto del taller funciona igual)')
        return 1
    consola.ok(f'LISTO · modo {modo.upper()} · siguiente paso: python3 01_texto.py docs/factura_limpia.png'
               + (' --offline' if modo == 'offline' and forzar == 'offline' else ''))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (cliente.ErrorAWS, cliente.FixtureFaltante) as e:
        consola.error(str(e))
        sys.exit(2)
    except KeyboardInterrupt:
        print()
        sys.exit(130)
