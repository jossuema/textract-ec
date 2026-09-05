#!/usr/bin/env python3
"""Lab 2 (checkpoint: TODO resuelto) — formularios, checkboxes y tablas con AnalyzeDocument FORMS + TABLES + LAYOUT.

Idéntico a 02_formulario_tabla.py pero con mi_pares_clave_valor ya escrito (8 líneas). Para
recuperarte: cp checkpoints/lab2/02_formulario_tabla.py . y ejecuta igual; verás '✔ tu implementación coincide'.

Qué hace:
- Una llamada `analyze_document` con FeatureTypes=['FORMS', 'TABLES', 'LAYOUT'] (US$ 0.065/página
  aprox.: FORMS 0.05 + TABLES 0.015; LAYOUT sin costo extra cuando va con TABLES/FORMS) o el
  fixture equivalente en OFFLINE.
- Imprime los pares clave → valor (KEY_VALUE_SET), los checkboxes como [X] / [ ] (SELECTION_ELEMENT),
  cada tabla (TABLE → CELL con RowIndex/ColumnIndex) como CSV y un resumen de los bloques LAYOUT_*.
- --csv guarda cada tabla en salida/<doc>.tabla<N>.csv (la primera también como salida/<doc>.detalle.csv).
- --json guarda la respuesta cruda en salida/<doc>.analyze.json y muestra un KEY con su VALUE.

EL ÚNICO TODO DEL TALLER está en `mi_pares_clave_valor(resp)`: devuelve un dict clave → valor a
partir de la respuesta cruda. El script se autoverifica contra textract_lab.bloques.pares_clave_valor:
si lanzas NotImplementedError o devuelves vacío, usa la versión de la librería y te avisa; si devuelves
algo, lo compara e imprime '✔ tu implementación coincide' o las diferencias.

Ejemplos:
    python3 02_formulario_tabla.py docs/factura_limpia.png --csv
    python3 02_formulario_tabla.py docs/formulario_inscripcion.png
    python3 02_formulario_tabla.py docs/factura_foto.jpg --offline --json
"""
from __future__ import annotations

import argparse
import json
import sys
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

from textract_lab import bloques, cliente, consola, costos  # noqa: E402

DOC_DEFAULT = 'docs/factura_limpia.png'
FEATURES = ['FORMS', 'TABLES', 'LAYOUT']
DIR_SALIDA = RAIZ / 'salida'


# =============================================================================
#  SOLUCIÓN del único TODO del taller (8 líneas)
# =============================================================================
def mi_pares_clave_valor(resp: dict) -> dict[str, str]:
    """Devuelve {texto_clave: texto_valor} a partir de la respuesta cruda de AnalyzeDocument FORMS.

    Pista (8 líneas):
      1. by_id = bloques.indice(resp)                      # Id → Block: los hijos no conocen a su padre
      2. recorre resp['Blocks'] y quédate con los bloques KEY_VALUE_SET
      3. ... cuyo EntityTypes contenga 'KEY' (los VALUE también son KEY_VALUE_SET)
      4. el VALUE de cada KEY está en bloques.hijos(key, by_id, 'VALUE') (relación tipo VALUE; toma el [0])
      5. el texto de cualquier bloque sale de bloques.texto(bloque, by_id) (une los WORD; checkbox → [X]/[ ])
      6. limpia la clave: .strip() y quítale el ':' final para que coincida con la librería
      7. kv[clave] = texto_valor  ('' si el KEY no tiene VALUE, como 'Firma:')
      8. return kv
    Referencia: https://docs.aws.amazon.com/textract/latest/dg/how-it-works-kvp.html
    """
    by_id = bloques.indice(resp)                                       # 1. Id → Block
    kv: dict[str, str] = {}
    for key in resp['Blocks']:
        if key['BlockType'] != 'KEY_VALUE_SET' or 'KEY' not in key.get('EntityTypes', []):
            continue                                                   # 2-3. solo los KEY
        valores = bloques.hijos(key, by_id, 'VALUE')                   # 4. relación KEY —VALUE→ VALUE
        clave = bloques.texto(key, by_id).strip().rstrip(':').strip()  # 5-6. texto limpio de la clave
        kv[clave] = bloques.texto(valores[0], by_id) if valores else ''  # 7. WORDs unidos; checkbox → [X]/[ ]
    return kv                                                          # 8.
# =============================================================================


def _normalizar(k: str) -> str:
    return bloques.normalizar_clave(k)


def autoverificar(resp: dict) -> dict[str, str]:
    """Compara mi_pares_clave_valor con la versión de la librería. Devuelve el dict clave → valor a usar."""
    consola.titulo('Autoverificación del TODO (mi_pares_clave_valor)')
    referencia = {k: c.valor for k, c in bloques.pares_clave_valor(resp).items()}
    try:
        mio = mi_pares_clave_valor(resp)
    except NotImplementedError as e:
        consola.aviso(f'TODO pendiente en mi_pares_clave_valor — {e}: usando textract_lab.bloques.pares_clave_valor')
        return referencia
    except Exception as e:  # un error en el código del asistente no debe tumbar el lab
        consola.error(f'tu función lanzó {type(e).__name__}: {e}')
        consola.aviso('usando textract_lab.bloques.pares_clave_valor mientras lo arreglas')
        return referencia
    if not mio:
        consola.aviso('tu función devolvió vacío: usando textract_lab.bloques.pares_clave_valor')
        return referencia

    mio_n = {_normalizar(k): str(v or '').strip() for k, v in mio.items()}
    ref_n = {_normalizar(k): str(v or '').strip() for k, v in referencia.items()}
    faltan = sorted(set(ref_n) - set(mio_n))
    sobran = sorted(set(mio_n) - set(ref_n))
    distintos = [(k, mio_n[k], ref_n[k]) for k in ref_n if k in mio_n and mio_n[k] != ref_n[k]]
    if not faltan and not sobran and not distintos:
        consola.ok(f'tu implementación coincide: {len(ref_n)} pares iguales a la librería')
        return {k: str(v or '') for k, v in mio.items()}
    consola.error(f'tu implementación difiere de la librería ({len(mio_n)} pares tuyos vs {len(ref_n)}):')
    for k in faltan[:10]:
        print(f'  falta la clave {k!r} (la librería da {ref_n[k]!r})')
    for k in sobran[:10]:
        print(f'  clave de más {k!r} → {mio_n[k]!r}')
    for k, a, b in distintos[:10]:
        print(f'  {k!r}: tú {a!r} · librería {b!r}')
    if len(faltan) + len(sobran) + len(distintos) > 30:
        print('  (solo se muestran las 10 primeras diferencias de cada tipo)')
    consola.aviso('usando la versión de la librería para el resto del lab')
    return referencia


def imprimir_pares(resp: dict, pares_usados: dict[str, str]) -> None:
    """Tabla clave | valor | confianza (la confianza sale de la librería: min(conf KEY, conf VALUE))."""
    campos = bloques.pares_clave_valor(resp)
    consola.titulo(f'Pares clave → valor (FORMS: {len(pares_usados)} pares)')
    filas = []
    for clave, campo in campos.items():
        valor = pares_usados.get(clave, campo.valor)
        filas.append([clave, valor if valor else consola.color('(sin valor)', 'gris'),
                      consola.confianza_coloreada(campo.confianza)])
    print(consola.tabla(filas, ['clave', 'valor', 'conf'], max_ancho_col=52))
    ruc = bloques.buscar_clave(campos, 'ruc')
    total = bloques.buscar_clave(campos, 'valor total')
    if ruc or total:
        print('buscar_clave normaliza (sin tildes, sin ":", minúsculas): '
              + (f'ruc → {ruc.valor!r}  ' if ruc else '') + (f'valor total → {total.valor!r}' if total else ''))


def imprimir_checkboxes(resp: dict) -> None:
    sel = bloques.selecciones(resp)
    if not sel:
        return
    consola.titulo(f'Checkboxes (SELECTION_ELEMENT: {len(sel)}, marcados {sum(1 for _, s, _ in sel if s == "SELECTED")})')
    for etiqueta, estado, conf in sel:
        marca = consola.color('[X]', 'verde') if estado == 'SELECTED' else '[ ]'
        print(f'  {marca} {etiqueta:<32} {estado:<13} {consola.confianza_coloreada(conf)}')
    print('SelectionStatus vive en el SELECTION_ELEMENT, hijo del VALUE; la etiqueta es el KEY.')


def imprimir_tablas(resp: dict, guardar_csv: bool, documento: str) -> None:
    lista = bloques.tablas(resp)
    consola.titulo(f'Tablas (TABLE → CELL): {len(lista)}')
    if not lista:
        print('(este documento no tiene tablas)')
        return
    stem = cliente.stem(documento)
    for n, t in enumerate(lista, 1):
        titulo = f' · título: {t.titulo}' if t.titulo else ''
        print(f'\nTabla {n}: {len(t.datos)} filas de datos × {len(t.cabecera)} columnas · '
              f'confianza media de celdas {consola.confianza_coloreada(t.confianza)}{titulo}')
        print(consola.tabla(t.datos, t.cabecera, max_ancho_col=30))
        csv_txt = bloques.tabla_a_csv(t)
        print('CSV:')
        print(csv_txt.rstrip('\n'))
        if guardar_csv:
            DIR_SALIDA.mkdir(parents=True, exist_ok=True)
            ruta = DIR_SALIDA / f'{stem}.tabla{n}.csv'
            ruta.write_text(csv_txt, encoding='utf-8')
            consola.ok(f'guardado {ruta.relative_to(RAIZ)}')
            if n == 1:
                alias = DIR_SALIDA / f'{stem}.detalle.csv'
                alias.write_text(csv_txt, encoding='utf-8')
                consola.ok(f'guardado {alias.relative_to(RAIZ)} (la primera tabla es el detalle de ítems)')
    if not guardar_csv:
        print('\n(--csv para guardarlas en salida/)')


def imprimir_layout(resp: dict) -> None:
    resumen = bloques.resumen_layout(resp)
    consola.titulo('LAYOUT (sin costo extra junto a TABLES/FORMS)')
    if not resumen:
        print('(sin bloques LAYOUT_* en esta respuesta)')
        return
    print('bloques LAYOUT_* por tipo: ' + ', '.join(f'{k} {v}' for k, v in resumen.items()))
    by_id = bloques.indice(resp)
    mostrados = 0
    for b in resp.get('Blocks') or []:
        tipo = str(b.get('BlockType', ''))
        if not tipo.startswith('LAYOUT_'):
            continue
        txt = bloques.texto(b, by_id).replace('\n', ' ')
        if len(txt) > 70:
            txt = txt[:67] + '…'
        n_hijos = len(bloques.hijos(b, by_id))
        print(f'  {tipo:<18} {consola.confianza_coloreada(b.get("Confidence", 0))}  {n_hijos:>2} LINE  {txt}')
        mostrados += 1
        if mostrados >= 12:
            print('  …')
            break
    print('cada LAYOUT_* agrupa LINEs (CHILD): útil para linealizar un documento antes de dárselo a un LLM.')


def imprimir_resumen(resp: dict) -> None:
    consola.titulo('Resumen')
    conteo = bloques.resumen_bloques(resp)
    print('bloques por tipo: ' + ', '.join(f'{k} {v}' for k, v in conteo.items()))
    ultima = cliente.ULTIMA_LLAMADA
    origen = {'aws': 'llamada real a Textract', 'cache': 'cache/ (ya pagada, US$ 0)', 'fixture': 'fixtures/ (US$ 0)'}
    tarifa = costos.costo('analyze_document', FEATURES, 1)
    print(f'origen de la respuesta: {origen.get(ultima.get("origen"), "?")} · '
          f'costo de esta llamada: {costos.formatear(ultima.get("costo_usd") or 0.0)} '
          f'(tarifa FORMS+TABLES+LAYOUT: {costos.formatear(tarifa)}/página)')
    modelo = resp.get('AnalyzeDocumentModelVersion')
    if modelo:
        print(f'AnalyzeDocumentModelVersion: {modelo}')


def guardar_json(resp: dict, documento: str) -> None:
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = DIR_SALIDA / f'{cliente.stem(documento)}.analyze.json'
    ruta.write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding='utf-8')
    consola.ok(f'respuesta cruda guardada: {ruta.relative_to(RAIZ)} ({len(resp.get("Blocks") or [])} bloques)')
    by_id = bloques.indice(resp)
    for b in resp.get('Blocks') or []:
        if b.get('BlockType') == 'KEY_VALUE_SET' and 'KEY' in (b.get('EntityTypes') or []):
            valores = bloques.hijos(b, by_id, 'VALUE')
            consola.titulo('Un KEY y su VALUE (Relationships VALUE → Id; CHILD → WORDs)')
            for blk in [b] + valores[:1]:
                muestra = {k: v for k, v in blk.items() if k != 'Geometry'}
                print(json.dumps(muestra, ensure_ascii=False, indent=2))
            print(f'KEY = {bloques.texto(b, by_id)!r} → VALUE = {bloques.texto(valores[0], by_id)!r}' if valores else '')
            break


def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('documento', nargs='?', default=DOC_DEFAULT,
                   help=f'PNG/JPEG de una página (default: {DOC_DEFAULT}). Prueba docs/formulario_inscripcion.png')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--offline', action='store_true', help='usar fixtures/ (sin AWS)')
    g.add_argument('--online', action='store_true', help='forzar Textract (con cache/; US$ 0.065/página aprox.)')
    p.add_argument('--csv', action='store_true', help='guardar cada tabla en salida/<doc>.tabla<N>.csv')
    p.add_argument('--json', action='store_true', help='guardar la respuesta cruda en salida/<doc>.analyze.json')
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
    print(f'documento: {ruta_doc.relative_to(RAIZ) if ruta_doc.is_relative_to(RAIZ) else ruta_doc} · '
          f'operación: analyze_document FeatureTypes={FEATURES}')

    resp = cliente.llamar('analyze_document', ruta_doc, feature_types=FEATURES, modo=modo)
    pares = autoverificar(resp)
    imprimir_pares(resp, pares)
    imprimir_checkboxes(resp)
    imprimir_tablas(resp, args.csv, str(ruta_doc))
    imprimir_layout(resp)
    imprimir_resumen(resp)
    if args.json:
        guardar_json(resp, str(ruta_doc))

    print()
    siguiente = ('python3 02_formulario_tabla.py docs/formulario_inscripcion.png'
                 if cliente.stem(ruta_doc) != 'formulario_inscripcion'
                 else 'python3 03_inteligente.py docs/factura_trampa.png')
    consola.ok(f'Lab 2 completo · siguiente: {siguiente}' + (' --offline' if forzar == 'offline' else ''))
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
