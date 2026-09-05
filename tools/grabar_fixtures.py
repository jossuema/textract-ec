#!/usr/bin/env python3
"""Graba fixtures REALES de Amazon Textract (y, con --bedrock, de Amazon Bedrock) desde la cuenta del ponente.

Es la ÚNICA herramienta del kit que llama a Textract en lote. Reemplaza los fixtures sintéticos
de fixtures/ por respuestas reales, escribe fixtures/META.json (origen "textract") y regenera
fixtures/MANIFEST.sha256. Cada llamada pasa por textract_lab.cliente.llamar() en modo online:
si ya existe cache/<clave>.json no se vuelve a pagar; luego se copia cache → fixtures.

Seguridad (no se puede saltar):
  - exige --confirmar y AWS_PROFILE definido y distinto de 'default';
  - imprime account id, ARN y región ANTES de gastar y pide confirmación interactiva (salvo --si);
  - --dry-run lista lo que haría (documentos, operaciones, costo aproximado) sin tocar AWS.

Uso típico (jueves T-2):
    AWS_PROFILE=personal python3 tools/grabar_fixtures.py --dry-run
    AWS_PROFILE=personal python3 tools/grabar_fixtures.py --confirmar --bedrock
Sábado T-2h, solo la foto real:
    AWS_PROFILE=personal python3 tools/grabar_fixtures.py --confirmar --solo factura_foto_real --bedrock

Costo aproximado del set completo (Textract, tarifa Oregón): ≈ US$ 0.45; Bedrock: centavos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import bedrock, bloques, cliente, consola, costos, etapas, queries  # noqa: E402

DIR_DOCS = RAIZ / 'docs'
DIR_FIXTURES = RAIZ / 'fixtures'
EXTENSIONES = ('.png', '.jpg', '.jpeg')  # el PDF de factura_limpia comparte stem con el PNG: no se graba aparte
FEATURES_ESTRUCTURA = ['FORMS', 'TABLES', 'LAYOUT']

DETECT = ('detect_document_text', None, None)
ESTRUCTURA = ('analyze_document', FEATURES_ESTRUCTURA, None)
QUERIES_FACT = ('analyze_document', ['QUERIES'], queries.QUERIES_FACTURA)
QUERIES_OC = ('analyze_document', ['QUERIES'], queries.QUERIES_ORDEN_COMPRA)

# Operaciones por documento (contrato §7). Documentos no listados (facturas nuevas, la foto real,
# cualquier PNG/JPG que se agregue a docs/) reciben el plan completo de factura.
PLANES: dict[str, list[tuple]] = {
    'mini': [DETECT],
    'formulario_inscripcion': [DETECT, ESTRUCTURA],
    'orden_compra_prosa': [DETECT, QUERIES_OC],
    'recibo_restaurante': [DETECT, ESTRUCTURA],
}
PLAN_FACTURA = [DETECT, ESTRUCTURA, QUERIES_FACT]

# Fixtures de Bedrock (05_bonus_bedrock.py --offline): documento → se graba con cada modelo de --modelos.
DOCS_BEDROCK = ['orden_compra_prosa', 'factura_foto', 'factura_foto_real']
MODELOS_BEDROCK = ['haiku', 'nova']


# ------------------------------------------------------------------ plan

def documentos_disponibles(con_extra: bool = True) -> list[Path]:
    rutas = [p for p in sorted(DIR_DOCS.iterdir()) if p.suffix.lower() in EXTENSIONES]
    if con_extra and (DIR_DOCS / 'extra').is_dir():
        rutas += [p for p in sorted((DIR_DOCS / 'extra').iterdir()) if p.suffix.lower() in EXTENSIONES]
    return rutas


def plan_para(documento: Path) -> list[tuple]:
    return PLANES.get(documento.stem, PLAN_FACTURA)


def construir_plan(documentos: list[Path]) -> list[dict]:
    plan = []
    for doc in documentos:
        for operacion, features, qs in plan_para(doc):
            clave = cliente.clave_llamada(doc, operacion, features, qs)
            plan.append({
                'documento': doc, 'stem': doc.stem, 'operacion': operacion, 'features': features, 'queries': qs,
                'clave': clave,
                'costo': costos.costo(operacion, features, 1),
                'en_cache': cliente.leer_json(cliente.ruta_cache(clave)) is not None,
                'fixture_previo': cliente.leer_json(cliente.ruta_fixture(clave)) is not None,
            })
    return plan


def mostrar_plan(plan: list[dict], docs_bedrock: list[Path], modelos: list[str], region: str) -> float:
    filas = []
    total = 0.0
    for item in plan:
        feat = '+'.join(item['features']) if item['features'] else '—'
        if item['queries']:
            feat += f' ({len(item["queries"])} queries)'
        origen = 'cache (sin costo)' if item['en_cache'] else f'AWS {costos.formatear(item["costo"])}'
        if not item['en_cache']:
            total += item['costo']
        filas.append([item['stem'], item['operacion'], feat, origen,
                      'reemplaza' if item['fixture_previo'] else 'nuevo'])
    print(consola.tabla(filas, ['documento', 'operación', 'features', 'origen previsto', 'fixture']))
    print(f'Textract en {region}: {len(plan)} llamadas, {sum(1 for i in plan if not i["en_cache"])} reales '
          f'(el resto desde cache/) ≈ {costos.formatear(total)} · {costos.NOTA_TARIFAS}')
    if docs_bedrock:
        print(f'Bedrock: {len(docs_bedrock)} documento(s) × {len(modelos)} modelo(s) = '
              f'{len(docs_bedrock) * len(modelos)} llamadas converse '
              f'({", ".join(bedrock.MODELOS[m] for m in modelos)}) ≈ centavos ({bedrock.NOTA_PRECIOS})')
    return total


# ------------------------------------------------------------- seguridad

def perfil_efectivo() -> str | None:
    return os.environ.get('AWS_PROFILE') or None


def verificar_perfil(abortar: bool = True) -> bool:
    perfil = perfil_efectivo()
    if not perfil:
        consola.error('AWS_PROFILE no está definido. Esta herramienta gasta dinero: exporta el perfil de la cuenta '
                      'del ponente (por ejemplo AWS_PROFILE=personal). Nunca usa el perfil default.')
        return _abortar(abortar)
    if perfil.strip().lower() == 'default':
        consola.error("AWS_PROFILE='default' no está permitido (contrato §0): usa AWS_PROFILE=personal.")
        return _abortar(abortar)
    if os.environ.get('LAB_MODO', '').strip().lower() == 'offline':
        consola.error('LAB_MODO=offline está definido: con él llamar() leería fixtures en vez de Textract. '
                      'Ejecuta con LAB_MODO=online (o sin la variable).')
        return _abortar(abortar)
    return True


def _abortar(abortar: bool) -> bool:
    if abortar:
        sys.exit(1)
    return False


def identidad(region: str) -> dict:
    """sts get-caller-identity con la sesión del perfil (única llamada que no es Textract/Bedrock)."""
    try:
        sesion = cliente._sesion()
        sts = sesion.client('sts', region_name=region)
        r = sts.get_caller_identity()
    except Exception as e:  # noqa: BLE001
        raise cliente.ErrorAWS(cliente.explicar_error(e, 'sts'), e) from e
    return {'cuenta': r.get('Account', '?'), 'arn': r.get('Arn', '?'), 'usuario': r.get('UserId', '?')}


def confirmar_interactivo(mensaje: str) -> bool:
    try:
        respuesta = input(f'{mensaje} Escribe "si" para continuar: ').strip().lower()
    except EOFError:
        return False
    return respuesta in ('si', 'sí', 's', 'yes', 'y')


# ------------------------------------------------------------- grabación

def grabar_textract(plan: list[dict], comprimir: bool) -> tuple[list[dict], list[str], dict]:
    """Ejecuta el plan en online (respeta cache/) y copia cache → fixtures. Devuelve (hechos, fallos, versiones)."""
    hechos: list[dict] = []
    fallos: list[str] = []
    versiones: dict[str, str] = {}
    for item in plan:
        etiqueta = f'{item["stem"]} · {item["operacion"]}' + (f' {"+".join(item["features"])}' if item['features'] else '')
        try:
            resp = cliente.llamar(item['operacion'], item['documento'], feature_types=item['features'],
                                  queries=item['queries'], modo='online')
        except (cliente.ErrorAWS, FileNotFoundError, ValueError) as e:
            consola.error(f'{etiqueta}: {e}')
            fallos.append(etiqueta)
            continue
        ultima = dict(cliente.ULTIMA_LLAMADA)
        if ultima.get('origen') == 'fixture':
            # No debería ocurrir con LAB_MODO≠offline; si pasa, no hay credenciales (NoCredentialsError).
            consola.error(f'{etiqueta}: la respuesta salió de fixtures/, no de AWS (¿sin credenciales?). No se graba.')
            fallos.append(etiqueta)
            continue
        destino = cliente.ruta_fixture(item['clave'])
        # Evita duplicados .json/.json.gz de la misma clave.
        for viejo in (destino, Path(str(destino) + '.gz')):
            if viejo.exists():
                viejo.unlink()
        escrito = cliente.escribir_json(destino, resp, comprimir=comprimir)
        for k in ('DetectDocumentTextModelVersion', 'AnalyzeDocumentModelVersion', 'AnalyzeExpenseModelVersion'):
            if k in resp:
                versiones[k] = str(resp[k])
        consola.ok(f'{etiqueta} → {escrito.relative_to(RAIZ)} ({escrito.stat().st_size / 1024:.0f} KB, '
                   f'origen {ultima.get("origen")}, {costos.formatear(float(ultima.get("costo_usd") or 0))})')
        hechos.append({**item, 'origen': ultima.get('origen'), 'costo_real': float(ultima.get('costo_usd') or 0),
                       'ruta': escrito})
    return hechos, fallos, versiones


def _guardar_fixture_bedrock(documento: Path, clave_modelo: str, resultado: dict, region: str) -> Path:
    ruta = bedrock.ruta_fixture_bedrock(str(documento), clave_modelo)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    datos = {
        'sintetico': False,
        'nota': f'Respuesta real de Amazon Bedrock ({region}) grabada por tools/grabar_fixtures.py',
        'grabado': date.today().isoformat(),
        'documento': documento.relative_to(RAIZ).as_posix() if documento.is_relative_to(RAIZ) else str(documento),
        'modelo': clave_modelo,
        'estrategia': resultado.get('estrategia'),
        'stopReason': resultado.get('stopReason'),
        'latencia_ms': resultado.get('latencia_ms'),
        'request': resultado.get('request'),
        'response': resultado.get('response'),
        'usage': resultado.get('usage'),
        'json': resultado.get('json'),
    }
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    return ruta


def grabar_bedrock(documentos: list[Path], modelos: list[str], region: str) -> tuple[list[dict], list[str], float]:
    """Para cada documento y modelo: texto + campos + alertas (desde los fixtures recién grabados) → converse."""
    hechos: list[dict] = []
    fallos: list[str] = []
    costo_total = 0.0
    for doc in documentos:
        try:
            ctx = etapas.procesar_con_contexto(doc, modo='offline')
        except cliente.FixtureFaltante as e:
            consola.error(f'{doc.stem}: faltan sus fixtures de Textract, no se puede armar el prompt ({e})')
            fallos.append(f'{doc.stem} · bedrock (sin fixtures de Textract)')
            continue
        texto = bloques.texto_completo(ctx['resp_texto'])
        campos = ctx.get('campos_canonicos') or ctx.get('campos') or {}
        alertas = list(ctx.get('alertas') or [])
        for modelo in modelos:
            etiqueta = f'{doc.stem} · bedrock {modelo}'
            try:
                resultado = bedrock.estructurar(texto, campos, alertas, modelo=modelo, modo='online', documento=str(doc))
            except cliente.ErrorAWS as e:
                consola.error(f'{etiqueta}: {e}')
                fallos.append(etiqueta)
                continue
            ruta = _guardar_fixture_bedrock(doc, modelo, resultado, region)
            costo_total += float(resultado.get('costo_usd_aprox') or 0.0)
            usage = resultado.get('usage') or {}
            consola.ok(f'{etiqueta} ({resultado["modelo_id"]}, {resultado["estrategia"]}) → {ruta.relative_to(RAIZ)} · '
                       f'{usage.get("inputTokens", "?")} in / {usage.get("outputTokens", "?")} out · '
                       f'{resultado.get("latencia_ms", "?")} ms · ${resultado.get("costo_usd_aprox", 0):.4f} aprox.')
            hechos.append({'stem': doc.stem, 'modelo': modelo, 'modelo_id': resultado['modelo_id'], 'ruta': ruta})
    return hechos, fallos, costo_total


# ------------------------------------------------------------ META/MANIFEST

def escribir_meta(region: str, cuenta: str, perfil: str, versiones: dict, grabados: list[str],
                  fallos: list[str], bedrock_hechos: list[dict], parcial: bool, no_regrabados: list[str]) -> Path:
    ruta = DIR_FIXTURES / 'META.json'
    previo = cliente.meta_fixtures()
    if parcial and previo:
        meta = dict(previo)
        origen = 'textract' if previo.get('origen') == 'textract' else 'mixto'
        documentos = sorted(set(previo.get('documentos') or []) | set(grabados))
        errores = dict(previo.get('errores_inyectados') or {})
        for stem in grabados:
            errores.pop(stem, None)  # los fixtures reales no llevan errores inyectados
        modelos_bedrock = dict(previo.get('bedrock') or {})
    else:
        meta = {}
        origen = 'textract'
        documentos = sorted(set(grabados))
        errores = {}
        modelos_bedrock = {}
    for h in bedrock_hechos:
        modelos_bedrock[h['modelo']] = h['modelo_id']
    meta.update({
        'origen': origen,
        'generado': date.today().isoformat(),
        'generador': 'tools/grabar_fixtures.py',
        'nota': ('Respuestas REALES de Amazon Textract grabadas desde la cuenta del ponente; '
                 'misma forma que devuelve boto3 (minificadas). Regenerar con tools/grabar_fixtures.py.'
                 + (' Origen mixto: algunos documentos siguen siendo sintéticos.' if origen == 'mixto' else '')),
        'region': region,
        'cuenta_ultimos4': str(cuenta)[-4:],
        'perfil': perfil,
        'modelo_textract': {**(previo.get('modelo_textract') or {} if parcial and isinstance(previo.get('modelo_textract'), dict) else {}), **versiones},
        'bedrock': modelos_bedrock,
        'documentos': documentos,
        'fallos': fallos,
        'no_regrabados': no_regrabados,
        'comprimidos': any(p.suffix == '.gz' for p in DIR_FIXTURES.rglob('*.gz')),
        'errores_inyectados': errores,
    })
    ruta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return ruta


def regenerar_manifest() -> tuple[Path, int]:
    rutas = sorted((p for p in DIR_FIXTURES.rglob('*') if p.is_file() and p.suffix in ('.json', '.gz')
                    and p.name != 'META.json'), key=lambda p: p.relative_to(RAIZ).as_posix())
    lineas = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(RAIZ).as_posix()}' for p in rutas]
    manifest = DIR_FIXTURES / 'MANIFEST.sha256'
    manifest.write_text('\n'.join(lineas) + '\n', encoding='utf-8')
    return manifest, len(lineas)


def fixtures_huerfanos(stems_plan: set[str]) -> list[Path]:
    """Carpetas fixtures/<stem>/ sin documento en el plan (sintéticos viejos o documentos borrados)."""
    return sorted(p for p in DIR_FIXTURES.iterdir() if p.is_dir() and p.name != 'bedrock' and p.name not in stems_plan)


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--confirmar', action='store_true', help='obligatorio para llamar a AWS (gasta dinero)')
    ap.add_argument('--si', action='store_true', help='no pedir confirmación interactiva tras mostrar la cuenta')
    ap.add_argument('--dry-run', action='store_true', help='listar lo que haría (documentos, operaciones, costo) sin tocar AWS')
    ap.add_argument('--solo', action='append', metavar='STEM', default=[],
                    help='grabar solo este documento (repetible): --solo factura_foto_real --solo mini')
    ap.add_argument('--sin-extra', action='store_true', help='no incluir docs/extra/')
    ap.add_argument('--bedrock', action='store_true',
                    help=f'grabar también fixtures/bedrock/ para {", ".join(DOCS_BEDROCK)} (los que existan)')
    ap.add_argument('--solo-bedrock', action='store_true', help='no llamar a Textract; solo grabar Bedrock (implica --bedrock)')
    ap.add_argument('--modelos', default=','.join(MODELOS_BEDROCK),
                    help=f'claves de textract_lab.bedrock.MODELOS separadas por coma (default {",".join(MODELOS_BEDROCK)})')
    ap.add_argument('--comprimir', action='store_true', help='guardar los fixtures como .json.gz')
    ap.add_argument('--limpiar', action='store_true',
                    help='borrar carpetas fixtures/<stem>/ que no correspondan a ningún documento del plan (solo sin --solo)')
    args = ap.parse_args(argv)

    region = os.environ.get('LAB_REGION', cliente.REGION_DEFAULT)
    perfil = perfil_efectivo()
    if args.solo_bedrock:
        args.bedrock = True
    modelos = [m.strip() for m in args.modelos.split(',') if m.strip()]
    desconocidos = [m for m in modelos if m not in bedrock.MODELOS]
    if desconocidos:
        consola.error(f'modelos desconocidos: {desconocidos}. Válidos: {", ".join(bedrock.MODELOS)}')
        return 1

    documentos = documentos_disponibles(con_extra=not args.sin_extra)
    if args.solo:
        stems = {d.stem for d in documentos}
        faltan = [s for s in args.solo if s not in stems]
        if faltan:
            consola.error(f'--solo: no existe docs/<stem>.png|jpg para {faltan}. Disponibles: {", ".join(sorted(stems))}')
            if 'factura_foto_real' in faltan:
                print('  (docs/factura_foto_real.jpg la toma el ponente el sábado; ver CHECKLIST T-2h)')
            return 1
        documentos = [d for d in documentos if d.stem in args.solo]
    plan = [] if args.solo_bedrock else construir_plan(documentos)
    docs_bedrock = [d for d in documentos if d.stem in DOCS_BEDROCK] if args.bedrock else []
    if args.bedrock and not docs_bedrock:
        consola.aviso(f'--bedrock: ninguno de {DOCS_BEDROCK} está en la selección; no se grabará Bedrock')

    consola.titulo(f'Plan de grabación · región {region} · perfil {perfil or "(sin AWS_PROFILE)"}')
    if not plan and not docs_bedrock:
        consola.error('nada que grabar')
        return 1
    mostrar_plan(plan, docs_bedrock, modelos, region)
    huerfanos = fixtures_huerfanos({i['stem'] for i in plan}) if plan and not args.solo else []
    if huerfanos:
        consola.aviso('carpetas de fixtures sin documento en el plan (quedan como están; --limpiar las borra): '
                      + ', '.join(p.name for p in huerfanos))

    if args.dry_run:
        verificar_perfil(abortar=False)
        consola.ok('DRY-RUN: no se llamó a AWS ni se escribió nada. Para grabar: añade --confirmar (y --si para no preguntar).')
        return 0
    if not args.confirmar:
        consola.error('falta --confirmar: esta herramienta gasta dinero en la cuenta del perfil. '
                      'Revisa el plan con --dry-run y vuelve a ejecutar con --confirmar.')
        return 1
    verificar_perfil(abortar=True)
    os.environ['LAB_MODO'] = 'online'

    try:
        quien = identidad(region)
    except cliente.ErrorAWS as e:
        consola.error(f'no se pudo verificar la identidad con el perfil {perfil!r}: {e}')
        return 2
    print(f'\nCuenta AWS : {quien["cuenta"]}\nARN        : {quien["arn"]}\nRegión     : {region}\nPerfil     : {perfil}')
    if not args.si and not confirmar_interactivo('\n¿Grabar con esta cuenta?'):
        consola.aviso('cancelado por el usuario; no se llamó a Textract')
        return 1

    fallos: list[str] = []
    versiones: dict[str, str] = {}
    hechos: list[dict] = []
    if plan:
        consola.titulo('Textract')
        hechos, fallos, versiones = grabar_textract(plan, args.comprimir)
    bedrock_hechos: list[dict] = []
    costo_bedrock = 0.0
    if docs_bedrock:
        consola.titulo('Bedrock')
        bedrock_hechos, fallos_b, costo_bedrock = grabar_bedrock(docs_bedrock, modelos, region)
        fallos += fallos_b

    if args.limpiar and huerfanos:
        import shutil
        for carpeta in huerfanos:
            shutil.rmtree(carpeta)
            consola.aviso(f'borrado {carpeta.relative_to(RAIZ)}')
        huerfanos = []

    grabados = sorted({h['stem'] for h in hechos})
    parcial = bool(args.solo) or args.solo_bedrock
    meta = escribir_meta(region, quien['cuenta'], perfil or '', versiones, grabados, fallos, bedrock_hechos, parcial,
                         [p.name for p in huerfanos])
    manifest, n = regenerar_manifest()

    consola.titulo('Resumen')
    reales = [h for h in hechos if h['origen'] == 'aws']
    print(f'Textract: {len(hechos)} fixtures escritos ({len(reales)} llamadas reales, '
          f'{len(hechos) - len(reales)} desde cache/) ≈ {costos.formatear(sum(h["costo_real"] for h in hechos))}')
    if docs_bedrock:
        print(f'Bedrock : {len(bedrock_hechos)} fixtures ≈ ${costo_bedrock:.4f} ({bedrock.NOTA_PRECIOS})')
    acumulado = costos.acumulado()
    print(f'Acumulado de la sesión (cache/.costos.json): {acumulado["llamadas"]} llamadas, '
          f'{costos.formatear(acumulado["usd"])}')
    print(f'{meta.relative_to(RAIZ)} → origen {json.loads(meta.read_text(encoding="utf-8"))["origen"]!r}; '
          f'{manifest.relative_to(RAIZ)} → {n} entradas')
    if fallos:
        consola.error(f'{len(fallos)} fallo(s): ' + '; '.join(fallos))
        print('Reintenta (lo ya grabado sale del cache sin costo) o revisa la política IAM / la región.')
        return 1
    consola.ok('listo. Verifica con: python3 00_check.py --offline && python3 -m pytest -q tests/')
    return 0


if __name__ == '__main__':
    sys.exit(main())
