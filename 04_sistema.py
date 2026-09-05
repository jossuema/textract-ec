#!/usr/bin/env python3
"""Lab 4 — esto es un sistema: la misma tubería sobre una carpeta entera.

El pipeline es una lista de funciones (ctx) -> ctx (textract_lab/etapas.py):
    ETAPAS = [texto, estructura, consultas, clasificar_etapa, validar, salida]
y `procesar_documento()` la recorre y devuelve un Resultado{tipo_documento, campos, tablas,
alertas, estado, paginas, costo_usd}. Aquí solo iteramos docs/*.png|jpg, mostramos una tabla y
guardamos salida/resumen.json + salida/<documento>.validado.json.

Sin `--online` NUNCA se llama a AWS: cada respuesta sale de cache/ (lo que grabaste en los Labs 1-3)
o de fixtures/ (lo que viene en el repo). Un documento sin ninguna de las dos aparece como SIN DATOS.

Uso:
  python3 04_sistema.py [directorio=docs/ ...] [--online|--offline] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def _raiz_repo() -> Path:
    """Sube directorios hasta encontrar textract_lab/ (funciona desde otro cwd)."""
    aqui = Path(__file__).resolve()
    for p in (aqui.parent, *aqui.parents):
        if (p / 'textract_lab' / '__init__.py').exists():
            return p
    return aqui.parent


RAIZ = _raiz_repo()
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import cliente, consola, costos, etapas  # noqa: E402
from textract_lab.clasificar import clasificar  # noqa: E402
from textract_lab.cliente import ErrorAWS, FixtureFaltante  # noqa: E402
from textract_lab.modelo import Resultado  # noqa: E402
from textract_lab.queries import QUERIES_FACTURA, set_para_tipo  # noqa: E402

DIRECTORIO_DEFAULT = 'docs'
EXTENSIONES = ('.png', '.jpg', '.jpeg')
DIR_SALIDA = RAIZ / 'salida'


# ------------------------------------------------------------------ CLI

def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Lab 4: corre el pipeline ETAPAS sobre una carpeta de documentos.')
    ap.add_argument('rutas', nargs='*', default=[DIRECTORIO_DEFAULT],
                    help=f'directorios (sin subcarpetas) o archivos png/jpg (default: {DIRECTORIO_DEFAULT}/)')
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument('--online', action='store_true',
                      help='permitir llamadas a Textract (con cache/); sin este flag solo cache/ y fixtures/')
    modo.add_argument('--offline', action='store_true', help='igual que el modo por defecto (sin AWS); por simetría')
    ap.add_argument('--json', action='store_true', help='imprimir además salida/resumen.json por pantalla')
    return ap.parse_args(argv)


# ------------------------------------------------------ modo local (sin AWS)

def llamar_local(operacion: str, documento, *, feature_types=None, queries=None, modo=None,
                 silencioso: bool = False) -> dict:
    """Sustituto de cliente.llamar que NUNCA llama a AWS: cache/ (tus grabaciones) → fixtures/ (del repo).

    Misma firma y misma clave que cliente.llamar, así el resto del pipeline no nota la diferencia:
    esto es "enchufar" otra fuente de datos sin tocar las etapas.
    """
    if operacion != 'analyze_document':
        feature_types, queries = None, None
    features = [f.upper() for f in (feature_types or [])]
    if queries and 'QUERIES' not in features:
        features.append('QUERIES')
    clave = cliente.clave_llamada(documento, operacion, features or None, queries)
    for origen, ruta in (('cache', cliente.ruta_cache(clave)), ('fixture', cliente.ruta_fixture(clave))):
        resp = cliente.leer_json(ruta)
        if resp is not None:
            cliente.ULTIMA_LLAMADA.update(
                clave=clave, origen=origen, costo_usd=0.0,
                paginas=int((resp.get('DocumentMetadata') or {}).get('Pages', 1) or 1))
            return resp
    raise FixtureFaltante(f'sin cache/ ni fixtures/ para {clave}.json '
                          f'(grábalo con los Labs 1-3 en online o ejecuta 04_sistema.py --online)')


# ---------------------------------------------------------------- lote

def listar_documentos(rutas: list[str]) -> list[Path]:
    """png/jpg de cada directorio (sin recursión) o los archivos sueltos indicados; ordenados por nombre."""
    docs: list[Path] = []
    for r in rutas:
        p = cliente.resolver_documento(r)
        if p.is_dir():
            docs += sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() in EXTENSIONES)
        elif p.is_file():
            docs.append(p)
        else:
            consola.aviso(f'no existe {r}: se omite')
    unicos: list[Path] = []
    for d in docs:
        if d not in unicos:
            unicos.append(d)
    return unicos


def ruta_corta(p: Path) -> str:
    """Ruta relativa a la raíz del repo o al cwd; si no, el nombre del archivo."""
    for base in (RAIZ, Path.cwd()):
        try:
            return str(p.relative_to(base))
        except ValueError:
            continue
    return p.name


def estimar_online(documentos: list[Path]) -> tuple[int, float, int]:
    """(llamadas reales, costo aproximado US$, llamadas desde cache/) que haría --online con el cache actual.

    La tubería pide DetectDocumentText + FORMS/TABLES/LAYOUT a todos los documentos y QUERIES según el tipo
    tentativo (factura → 7 queries; desconocido → orden de compra; formulario → ninguna). El tipo se estima
    con el texto ya conocido (cache/ o fixtures/); si no hay ninguno se asume factura (mismo costo por página).
    """
    reales, costo_total, desde_cache = 0, 0.0, 0
    for doc in documentos:
        plan: list[tuple] = [('detect_document_text', None, None), ('analyze_document', etapas.FEATURES_ESTRUCTURA, None)]
        clave_texto = cliente.clave_llamada(doc, 'detect_document_text')
        resp_texto = cliente.cache_vigente(doc, clave_texto)[0] or cliente.leer_json(cliente.ruta_fixture(clave_texto))
        queries = set_para_tipo(clasificar(resp_texto)[0]) if resp_texto is not None else QUERIES_FACTURA
        if queries:
            plan.append(('analyze_document', ['QUERIES'], queries))
        for operacion, features, qs in plan:
            if cliente.hay_cache(doc, operacion, features, qs):
                desde_cache += 1
            else:
                reales += 1
                costo_total += costos.costo(operacion, features)
    return reales, round(costo_total, 6), desde_cache


def procesar_lote(documentos: list[Path], modo: str) -> tuple[list[dict], list[Resultado]]:
    """Corre ETAPAS por documento; devuelve filas de resumen y los Resultados (None → SIN DATOS / ERROR)."""
    filas: list[dict] = []
    resultados: list[Resultado] = []
    for doc in documentos:
        nombre = ruta_corta(doc)
        fila = {'documento': nombre, 'stem': cliente.stem(doc), 'tipo': None, 'estado': None, 'alertas': [],
                'n_alertas': 0, 'paginas': 0, 'costo_usd': 0.0, 'origenes': [], 'salida': None, 'motivo': None}
        try:
            r = etapas.procesar_documento(doc, modo=modo)
            r.documento = nombre  # ruta corta (no la ruta absoluta de tu máquina) en salida/<doc>.validado.json
        except FixtureFaltante as e:
            fila.update(estado='SIN DATOS', motivo=str(e))
            filas.append(fila)
            continue
        except ErrorAWS as e:
            consola.error(f'{nombre}: {e}')
            fila.update(estado='ERROR', motivo=str(e))
            filas.append(fila)
            continue
        origenes = sorted({str(ll.get('origen')) for ll in r.extra.get('llamadas', []) if ll.get('origen')})
        r.modo = 'cache/fixtures' if modo == 'offline' and 'cache' in origenes else r.modo
        DIR_SALIDA.mkdir(parents=True, exist_ok=True)
        ruta = DIR_SALIDA / f'{fila["stem"]}.validado.json'
        ruta.write_text(r.to_json(), encoding='utf-8')
        fila.update(tipo=r.tipo_documento, estado=r.estado, alertas=list(r.alertas), n_alertas=len(r.alertas),
                    paginas=r.paginas, costo_usd=r.costo_usd, origenes=origenes, salida=ruta_corta(ruta))
        filas.append(fila)
        resultados.append(r)
    return filas, resultados


def imprimir_tabla(filas: list[dict]) -> None:
    colores = {'OK': 'verde', 'REVISAR': 'rojo', 'SIN DATOS': 'amarillo', 'ERROR': 'rojo'}
    cuerpo = []
    for f in filas:
        estado = consola.color(f['estado'], colores.get(f['estado'], 'blanco'))
        if f['tipo'] is None:
            cuerpo.append([f['documento'], '—', estado, '—', '—', '—'])
        else:
            cuerpo.append([f['documento'], f['tipo'], estado, str(f['n_alertas']), str(f['paginas']),
                           f'{f["costo_usd"]:.4f}'])
    print(consola.tabla(cuerpo, ['documento', 'tipo', 'estado', 'alertas', 'páginas', 'US$']))


def ejecutar(args: argparse.Namespace) -> int:
    if args.online:
        modo = cliente.resolver_modo('online')  # sin credenciales → cae a offline con aviso (no es error)
        etiqueta = cliente.banner_modo(modo)
    else:
        modo = 'offline'
        cliente.llamar = llamar_local  # inyectamos el lector local: cache/ → fixtures/, nunca AWS
        etiqueta = cliente.banner_modo('offline') + ' + cache/ · sin llamadas a AWS (usa --online para pedir lo que falte)'
    print(etiqueta, flush=True)

    documentos = listar_documentos(args.rutas)
    if not documentos:
        consola.error(f'no hay png/jpg en {", ".join(args.rutas)}')
        return 1
    print(f'{len(documentos)} documento(s) · ETAPAS = [{", ".join(e.__name__ for e in etapas.ETAPAS)}]')
    if args.online and modo == 'online' and cliente.info_credenciales().get('tiene_credenciales'):
        # Sin esto el flag gastaría sin avisar: la tubería pide FORMS+TABLES+LAYOUT a TODOS los documentos.
        # (sin credenciales no se estima: llamar() caerá a fixtures con su propio aviso)
        reales, costo_est, desde_cache = estimar_online(documentos)
        if reales:
            consola.aviso(f'--online: {reales} llamada(s) reales a Textract ≈ {costos.formatear(costo_est)} '
                          f'({costos.NOTA_TARIFAS}); {desde_cache} desde cache/. Ctrl+C ahora si no quieres gastar.')
        else:
            print(f'--online: las {desde_cache} respuestas están en cache/: no se llamará a Textract')
    consola.titulo('Resultado por documento')
    filas, resultados = procesar_lote(documentos, modo)
    imprimir_tabla(filas)

    for f in filas:
        if f['estado'] == 'REVISAR' and f['alertas']:
            print(f'  {f["documento"]}:')
            for a in f['alertas'][:4]:
                print('    - ' + a)
            if len(f['alertas']) > 4:
                print(f'    … y {len(f["alertas"]) - 4} más en {f["salida"]}')
        elif f['estado'] == 'SIN DATOS':
            print(f'  {f["documento"]}: {consola.color("SIN DATOS", "amarillo")} — {f["motivo"]}')

    totales = {
        'documentos': len(filas),
        'ok': sum(1 for f in filas if f['estado'] == 'OK'),
        'revisar': sum(1 for f in filas if f['estado'] == 'REVISAR'),
        'sin_datos': sum(1 for f in filas if f['estado'] == 'SIN DATOS'),
        'error': sum(1 for f in filas if f['estado'] == 'ERROR'),
        'paginas': sum(f['paginas'] for f in filas),
        'costo_usd': round(sum(f['costo_usd'] for f in filas), 6),
    }
    resumen = {
        'generado': datetime.now().isoformat(timespec='seconds'),
        'modo': 'online' if args.online and modo == 'online' else 'local (cache/fixtures)',
        'rutas': args.rutas,
        'etapas': [e.__name__ for e in etapas.ETAPAS],
        'documentos': filas,
        'totales': totales,
        'nota_costo': costos.NOTA_TARIFAS,
    }
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    ruta_resumen = DIR_SALIDA / 'resumen.json'
    ruta_resumen.write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.json:
        print(json.dumps(resumen, ensure_ascii=False, indent=2))

    consola.ok(f'{totales["ok"]} OK · {totales["revisar"]} REVISAR · {totales["sin_datos"]} SIN DATOS'
               + (f' · {totales["error"]} ERROR' if totales['error'] else '')
               + f' → {ruta_corta(ruta_resumen)} y salida/<documento>.validado.json')
    origen = ' (todo desde cache/fixtures)' if totales['costo_usd'] == 0 else f' ({costos.NOTA_TARIFAS})'
    print(f'Costo estimado de esta corrida: {costos.formatear(totales["costo_usd"])}{origen}')
    return 2 if totales['error'] else 0


def main(argv: list[str] | None = None) -> int:
    args = parsear_args(argv)
    try:
        return ejecutar(args)
    except ErrorAWS as e:
        consola.error(str(e))
        return 2
    except KeyboardInterrupt:
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
