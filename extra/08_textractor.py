#!/usr/bin/env python3
"""Extra 08 — amazon-textract-textractor (opcional): el "atajo" que hace lo que hicimos a mano.

La librería oficial de AWS (github.com/aws-samples/amazon-textract-textractor, v1.10.0, Python >= 3.10)
convierte la respuesta cruda en objetos Document / Page / Table / KeyValue con exportación a pandas,
CSV, Markdown y HTML. Es útil como nivel 2; en el taller parseamos los Blocks a mano porque es más
didáctico y no agrega dependencias.

Aquí seguimos usando textract_lab.cliente.llamar() (cache/fixtures, costo controlado) y le pasamos la
respuesta al parser de textractor: `textractor.parsers.response_parser.parse(resp)`.

Uso:
  python3 extra/08_textractor.py [documento=docs/factura_limpia.png] [--offline|--online] [--markdown]

Instalación (opcional, fuera del camino obligatorio):
  pip install "amazon-textract-textractor[pandas]"      # o: pip install -r requirements-extra.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _raiz_repo() -> Path:
    aqui = Path(__file__).resolve()
    for p in (aqui.parent, *aqui.parents):
        if (p / 'textract_lab' / '__init__.py').exists():
            return p
    return aqui.parent


RAIZ = _raiz_repo()
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import bloques, cliente, consola  # noqa: E402
from textract_lab.cliente import ErrorAWS, FixtureFaltante  # noqa: E402

try:  # import protegido: la librería es opcional
    from textractor.parsers import response_parser  # type: ignore
    TEXTRACTOR_DISPONIBLE = True
except ImportError:
    response_parser = None
    TEXTRACTOR_DISPONIBLE = False

DOCUMENTO_DEFAULT = 'docs/factura_limpia.png'
FEATURES = ['FORMS', 'TABLES', 'LAYOUT']  # misma clave de cache/fixture que el Lab 2
DIR_SALIDA = RAIZ / 'salida'


def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Extra 08: la misma respuesta de Textract con amazon-textract-textractor.')
    ap.add_argument('documento', nargs='?', default=DOCUMENTO_DEFAULT)
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument('--offline', action='store_true', help='usar solo fixtures/ (sin AWS)')
    modo.add_argument('--online', action='store_true', help='llamar a Textract (con cache/)')
    ap.add_argument('--markdown', action='store_true', help='imprimir document.to_markdown() (entrada típica para un LLM)')
    return ap.parse_args(argv)


def explicar_instalacion() -> None:
    consola.aviso('amazon-textract-textractor no está instalada: este extra es opcional')
    print("""
Para probarlo (no hace falta para ningún lab del taller):
  python3 -m pip install "amazon-textract-textractor[pandas]"     # ≈ 1.10.0, Python >= 3.10
  # trae pandas, Pillow, XlsxWriter, rapidfuzz, tabulate; en wifi lento puede tardar
Después:
  python3 extra/08_textractor.py docs/factura_limpia.png --offline
Lo que verías: Document → document.tables[0].to_pandas() (DataFrame de la tabla de ítems), document.key_values
(pares clave-valor), document.to_markdown() (texto para un LLM) y salida/<doc>.tabla<N>.csv.
Mientras tanto, lo mismo a mano con la librería del taller:
  from textract_lab import bloques; tablas = bloques.tablas(resp); print(bloques.tabla_a_csv(tablas[0]))""")


def ejecutar(args: argparse.Namespace) -> int:
    if not TEXTRACTOR_DISPONIBLE:
        explicar_instalacion()
        return 0
    modo_pedido = 'offline' if args.offline else 'online' if args.online else None
    modo = cliente.resolver_modo(modo_pedido)
    print(cliente.banner_modo(modo), flush=True)
    documento = args.documento
    stem = cliente.stem(documento)

    try:
        resp = cliente.llamar('analyze_document', documento, feature_types=FEATURES, modo=modo)
    except FixtureFaltante as e:
        consola.error(str(e))
        return 1
    print(f'origen: {cliente.ULTIMA_LLAMADA.get("origen")} · bloques: {bloques.resumen_bloques(resp)}')

    document = response_parser.parse(resp)  # Document de textractor a partir del dict crudo de boto3
    consola.titulo('Document de textractor')
    print(f'  páginas: {len(getattr(document, "pages", []) or [])} · tablas: {len(getattr(document, "tables", []) or [])} '
          f'· pares clave-valor: {len(getattr(document, "key_values", []) or [])}')

    consola.titulo('Pares clave-valor (document.key_values)')
    for kv in list(getattr(document, 'key_values', []) or [])[:12]:
        try:
            print(f'  {str(kv.key).strip():<32} → {str(kv.value).strip()}')
        except Exception:  # noqa: BLE001 — la API cambia entre versiones; no romper el extra
            print(f'  {kv}')

    consola.titulo('Tablas (to_pandas / to_csv)')
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    for i, tabla in enumerate(getattr(document, 'tables', []) or [], start=1):
        ruta = DIR_SALIDA / f'{stem}.tabla{i}.csv'
        try:
            df = tabla.to_pandas()
            print(df.to_string(index=False))
            df.to_csv(ruta, index=False)
        except Exception as e:  # noqa: BLE001 — sin pandas: to_csv() de la propia librería
            consola.aviso(f'to_pandas no disponible ({type(e).__name__}): usando to_csv()')
            csv = tabla.to_csv()
            print(csv)
            ruta.write_text(csv, encoding='utf-8')
        consola.ok(f'guardado {ruta.relative_to(RAIZ)}')

    if args.markdown:
        consola.titulo('document.to_markdown() — lo que le darías a un LLM')
        to_md = getattr(document, 'to_markdown', None)
        print(to_md() if callable(to_md) else getattr(document, 'text', '(sin linearización en esta versión)'))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parsear_args(argv)
    try:
        return ejecutar(args)
    except ErrorAWS as e:
        consola.error(str(e))
        return 2
    except FileNotFoundError as e:
        consola.error(str(e))
        return 1


if __name__ == '__main__':
    sys.exit(main())
