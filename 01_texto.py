#!/usr/bin/env python3
"""Lab 1 — texto y confianza con DetectDocumentText (la operación barata: US$ 0.0015/página aprox.).

Qué hace:
- Una llamada `detect_document_text` (o el fixture equivalente en OFFLINE) sobre un PNG/JPEG
  de una página; imprime cada LINE con su Confidence en semáforo (verde >= 90, amarillo 70-90,
  rojo < 70), la confianza media, el conteo de bloques por tipo y las palabras por debajo de 90.
- --overlay dibuja las cajas de cada LINE sobre la imagen → salida/<doc>.overlay.png (necesita
  Pillow; si falta, avisa y sigue).
- --json guarda la respuesta cruda en salida/<doc>.texto.json y muestra un LINE con su primer WORD
  (el modelo mental: PAGE → LINE → WORD; los hijos no conocen a su padre, por eso el índice by_id).

Compara la factura limpia con la foto para ver caer la confianza:
    python3 01_texto.py docs/factura_limpia.png
    python3 01_texto.py docs/factura_foto.jpg --overlay
    python3 01_texto.py docs/factura_foto.jpg --offline --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def _raiz_repo() -> Path:
    """Sube desde este archivo hasta encontrar textract_lab/ (funciona desde checkpoints/ y otro cwd)."""
    aqui = Path(__file__).resolve()
    for p in (aqui.parent, *aqui.parents):
        if (p / 'textract_lab' / '__init__.py').exists():
            return p
    raise SystemExit('✘ no encuentro textract_lab/: ejecuta este script dentro del repo textract-ec')


RAIZ = _raiz_repo()
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import bloques, cliente, consola, costos, overlay  # noqa: E402

DOC_DEFAULT = 'docs/factura_limpia.png'
UMBRAL = consola.UMBRAL_ALTO  # 90: por debajo, AWS sugiere revisión humana en procesos financieros
DIR_SALIDA = RAIZ / 'salida'


def imprimir_lineas(resp: dict) -> list[tuple[str, float]]:
    """Cada LINE con su semáforo y su confianza."""
    lineas = bloques.lineas(resp)
    consola.titulo(f'Líneas detectadas ({len(lineas)})  ● >= 90  ● 70-90  ● < 70')
    for i, (txt, conf) in enumerate(lineas, 1):
        print(f'{i:>3}  {consola.confianza_coloreada(conf)}  {txt}')
    return lineas


def imprimir_resumen(resp: dict, documento: str) -> None:
    consola.titulo('Resumen')
    conteo = bloques.resumen_bloques(resp)
    print('bloques por tipo: ' + ', '.join(f'{k} {v}' for k, v in conteo.items()))
    paginas = (resp.get('DocumentMetadata') or {}).get('Pages', 1)
    tipos_texto = Counter(b.get('TextType', '?') for b in bloques.por_tipo(resp, 'WORD'))
    print(f'páginas: {paginas} · TextType de las palabras: '
          + ', '.join(f'{k} {v}' for k, v in tipos_texto.items()))
    media_linea = bloques.confianza_media(resp, 'LINE')
    media_palabra = bloques.confianza_media(resp, 'WORD')
    print(f'confianza media LINE: {consola.confianza_coloreada(media_linea)}   '
          f'WORD: {consola.confianza_coloreada(media_palabra)}   ({cliente.stem(documento)})')
    bajas = bloques.palabras_bajo_umbral(resp, UMBRAL)
    total_palabras = len(bloques.por_tipo(resp, 'WORD'))
    print(f'palabras < {UMBRAL:.0f}: {len(bajas)} de {total_palabras}')
    if bajas:
        peores = sorted(bajas, key=lambda p: p[1])[:10]
        print('  las peores: ' + '  '.join(f'{consola.semaforo(c)} {t} ({c:.1f})' for t, c in peores))
        print('  ¿son dígitos de montos o de la clave de acceso? En un proceso financiero, nada < 90 sin revisión humana.')
    else:
        consola.ok('ninguna palabra por debajo del umbral')
    modelo = resp.get('DetectDocumentTextModelVersion')
    if modelo:
        print(f'DetectDocumentTextModelVersion: {modelo}')


def imprimir_origen() -> None:
    ultima = cliente.ULTIMA_LLAMADA
    origen = {'aws': 'llamada real a Textract', 'cache': 'cache/ (ya pagada, US$ 0)', 'fixture': 'fixtures/ (US$ 0)'}
    costo_unitario = costos.costo('detect_document_text', None, ultima.get('paginas') or 1)
    print(f'origen de la respuesta: {origen.get(ultima.get("origen"), "?")} · '
          f'costo de esta llamada: {costos.formatear(ultima.get("costo_usd") or 0.0)} '
          f'(tarifa DetectDocumentText: {costos.formatear(costo_unitario)}/página)')


def guardar_json(resp: dict, documento: str) -> None:
    """Guarda la respuesta cruda y enseña un LINE con su primer WORD."""
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = DIR_SALIDA / f'{cliente.stem(documento)}.texto.json'
    ruta.write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding='utf-8')
    consola.ok(f'respuesta cruda guardada: {ruta.relative_to(RAIZ)} ({len(resp.get("Blocks") or [])} bloques)')
    by_id = bloques.indice(resp)
    lineas = bloques.por_tipo(resp, 'LINE')
    if not lineas:
        return
    linea = lineas[0]
    palabras = bloques.hijos(linea, by_id)
    consola.titulo('Un LINE y su primer WORD (Relationships CHILD → Ids → by_id)')
    muestra = {k: v for k, v in linea.items() if k != 'Geometry'}
    muestra['Geometry'] = {'BoundingBox': (linea.get('Geometry') or {}).get('BoundingBox')}
    print(json.dumps(muestra, ensure_ascii=False, indent=2))
    if palabras:
        w = {k: v for k, v in palabras[0].items() if k != 'Geometry'}
        w['Geometry'] = {'BoundingBox': (palabras[0].get('Geometry') or {}).get('BoundingBox')}
        print(json.dumps(w, ensure_ascii=False, indent=2))
    print('BoundingBox va de 0 a 1: multiplica por el ancho/alto en píxeles para dibujar (--overlay).')


def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('documento', nargs='?', default=DOC_DEFAULT,
                   help=f'PNG/JPEG de una página (default: {DOC_DEFAULT}). Prueba docs/factura_foto.jpg')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--offline', action='store_true', help='usar fixtures/ (sin AWS)')
    g.add_argument('--online', action='store_true', help='forzar Textract (con cache/)')
    p.add_argument('--overlay', action='store_true', help='dibujar cajas por confianza → salida/<doc>.overlay.png (Pillow)')
    p.add_argument('--json', action='store_true', help='guardar la respuesta cruda en salida/<doc>.texto.json y mostrar un LINE/WORD')
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parsear_args(argv)
    forzar = 'offline' if args.offline else 'online' if args.online else None
    modo = cliente.resolver_modo(forzar)
    print(consola.color(cliente.banner_modo(modo), 'negrita'), flush=True)

    ruta_doc = cliente.resolver_documento(args.documento)
    if not ruta_doc.exists():
        if modo == 'offline':
            consola.aviso(f'no existe {args.documento} en disco: en offline se busca el fixture por nombre ({cliente.stem(args.documento)})')
        else:
            consola.error(f'no existe el documento {args.documento}')
            return 1
    print(f'documento: {ruta_doc.relative_to(RAIZ) if ruta_doc.is_relative_to(RAIZ) else ruta_doc} · operación: detect_document_text')

    resp = cliente.llamar('detect_document_text', ruta_doc, modo=modo)
    imprimir_lineas(resp)
    imprimir_resumen(resp, str(ruta_doc))
    imprimir_origen()

    if args.overlay:
        consola.titulo('Overlay')
        salida = DIR_SALIDA / f'{cliente.stem(ruta_doc)}.overlay.png'
        try:
            salida = salida.relative_to(Path.cwd())  # ruta corta si estamos en la raíz del repo
        except ValueError:
            pass
        ruta = overlay.dibujar(ruta_doc, resp, salida)
        if ruta is not None:
            print('en CloudShell: Actions → Download file para verlo; en tu laptop ábrelo directamente.')
    if args.json:
        guardar_json(resp, str(ruta_doc))

    print()
    sufijo = ' --offline' if forzar == 'offline' else ''
    if cliente.stem(ruta_doc) == 'factura_foto':
        consola.ok('Lab 1 completo · siguiente: python3 02_formulario_tabla.py docs/factura_limpia.png --csv' + sufijo)
    else:
        consola.ok('Lab 1 completo · ahora compara: python3 01_texto.py docs/factura_foto.jpg --overlay' + sufijo)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (cliente.ErrorAWS, cliente.FixtureFaltante) as e:
        consola.error(str(e))
        sys.exit(2)
    except FileNotFoundError as e:
        consola.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        sys.exit(130)
