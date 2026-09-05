"""Navegación del grafo de Blocks de Textract (respuesta cruda de boto3).

Todo opera sobre el dict que devuelve boto3 (o un fixture con la misma forma):
PAGE → LINE → WORD; KEY_VALUE_SET (KEY —VALUE→ VALUE); TABLE → CELL → WORD;
QUERY —ANSWER→ QUERY_RESULT; SELECTION_ELEMENT dentro de un VALUE o CELL.
Referencia: https://docs.aws.amazon.com/textract/latest/APIReference/API_Block.html
"""
from __future__ import annotations

import csv
import io
import unicodedata
from collections import Counter

from .modelo import Campo, Tabla


# ---------------------------------------------------------------- utilidades

def normalizar_clave(s: str) -> str:
    """'  RUC: ' → 'ruc'; 'Descripción' → 'descripcion'. Sin tildes, minúsculas, sin ':' final."""
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.strip().lower()
    while s.endswith(':'):
        s = s[:-1].rstrip()
    return ' '.join(s.split())


def _clave_limpia(s: str) -> str:
    """Clave para dicts de FORMS: strip y sin ':' final, conservando mayúsculas y tildes."""
    s = ' '.join(str(s or '').split())
    while s.endswith(':'):
        s = s[:-1].rstrip()
    return s


def _blocks(resp: dict) -> list[dict]:
    return list((resp or {}).get('Blocks') or [])


def _conf(block: dict) -> float:
    try:
        return float(block.get('Confidence', 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------- grafo básico

def indice(resp: dict) -> dict[str, dict]:
    """Id → Block."""
    return {b['Id']: b for b in _blocks(resp) if 'Id' in b}


def hijos(block: dict, by_id: dict[str, dict], tipo: str = 'CHILD') -> list[dict]:
    """Sigue Relationships[Type == tipo].Ids y devuelve los bloques (ignora ids desconocidos)."""
    salida: list[dict] = []
    for rel in (block or {}).get('Relationships') or []:
        if rel.get('Type') == tipo:
            for id_ in rel.get('Ids') or []:
                b = by_id.get(id_)
                if b is not None:
                    salida.append(b)
    return salida


def por_tipo(resp: dict, tipo: str) -> list[dict]:
    """Bloques de un BlockType, en el orden de la respuesta."""
    return [b for b in _blocks(resp) if b.get('BlockType') == tipo]


def marca_seleccion(block: dict) -> str:
    """SELECTION_ELEMENT → '[X]' si SELECTED, '[ ]' si no."""
    return '[X]' if block.get('SelectionStatus') == 'SELECTED' else '[ ]'


def texto(block: dict, by_id: dict[str, dict]) -> str:
    """Texto de un bloque: WORD.Text unidos por espacio; SELECTION_ELEMENT → '[X]' / '[ ]'.

    Funciona para LINE, KEY, VALUE, CELL (y recursivamente para cualquier bloque con CHILD).
    """
    tipo = block.get('BlockType')
    if tipo == 'WORD':
        return str(block.get('Text', ''))
    if tipo == 'SELECTION_ELEMENT':
        return marca_seleccion(block)
    partes = [texto(h, by_id) for h in hijos(block, by_id, 'CHILD')]
    return ' '.join(p for p in partes if p)


def lineas(resp: dict) -> list[tuple[str, float]]:
    """[(Text, Confidence)] de los bloques LINE en orden de lectura."""
    return [(str(b.get('Text', '')), _conf(b)) for b in por_tipo(resp, 'LINE')]


def texto_completo(resp: dict) -> str:
    """Texto linealizado (una LINE por renglón): entrada típica para un LLM."""
    return '\n'.join(t for t, _ in lineas(resp))


def confianza_media(resp: dict, tipo: str = 'LINE') -> float:
    """Promedio de Confidence de los bloques de `tipo` (0.0 si no hay)."""
    valores = [_conf(b) for b in por_tipo(resp, tipo)]
    return round(sum(valores) / len(valores), 2) if valores else 0.0


def palabras_bajo_umbral(resp: dict, umbral: float = 90.0) -> list[tuple[str, float]]:
    """Palabras con confianza menor al umbral."""
    return [(str(b.get('Text', '')), _conf(b)) for b in por_tipo(resp, 'WORD') if _conf(b) < umbral]


def resumen_bloques(resp: dict) -> dict[str, int]:
    """Conteo por BlockType (ordenado por frecuencia)."""
    c = Counter(b.get('BlockType', '?') for b in _blocks(resp))
    return dict(c.most_common())


# ------------------------------------------------------------------- FORMS

def _es_key(block: dict) -> bool:
    return block.get('BlockType') == 'KEY_VALUE_SET' and 'KEY' in (block.get('EntityTypes') or [])


def _valor_de(key: dict, by_id: dict[str, dict]) -> dict | None:
    valores = hijos(key, by_id, 'VALUE')
    return valores[0] if valores else None


def pares_clave_valor(resp: dict) -> dict[str, Campo]:
    """KEY_VALUE_SET KEY→VALUE. Clave normalizada (strip, sin ':' final).

    Campo(valor, confianza=min(conf KEY, conf VALUE), origen='FORMS').
    Si una clave se repite, se conserva la primera con valor no vacío.
    """
    by_id = indice(resp)
    pares: dict[str, Campo] = {}
    for key in _blocks(resp):
        if not _es_key(key):
            continue
        clave = _clave_limpia(texto(key, by_id))
        if not clave:
            continue
        valor_b = _valor_de(key, by_id)
        if valor_b is None:
            campo = Campo('', _conf(key), 'FORMS')
        else:
            campo = Campo(texto(valor_b, by_id), min(_conf(key), _conf(valor_b)), 'FORMS')
        if clave in pares and not pares[clave].vacio():
            continue
        pares[clave] = campo
    return pares


def buscar_clave(pares: dict[str, Campo], *candidatas: str) -> Campo | None:
    """Busca en un dict de FORMS por clave normalizada ('ruc', 'valor total', ...)."""
    objetivo = {normalizar_clave(c) for c in candidatas}
    for clave, campo in pares.items():
        if normalizar_clave(clave) in objetivo:
            return campo
    return None


# ------------------------------------------------------------ SELECCIONES

def _centro(block: dict) -> tuple[float, float]:
    bb = ((block.get('Geometry') or {}).get('BoundingBox') or {})
    return (float(bb.get('Left', 0)) + float(bb.get('Width', 0)) / 2,
            float(bb.get('Top', 0)) + float(bb.get('Height', 0)) / 2)


def _linea_mas_cercana(sel: dict, resp: dict) -> str:
    """Para un checkbox sin KEY: texto de la LINE más cercana en la misma fila (preferir a la derecha)."""
    cx, cy = _centro(sel)
    alto = float(((sel.get('Geometry') or {}).get('BoundingBox') or {}).get('Height', 0.01)) or 0.01
    mejor, mejor_d = '', 9e9
    for ln in por_tipo(resp, 'LINE'):
        lx, ly = _centro(ln)
        if abs(ly - cy) > alto * 1.5:
            continue
        bb = ((ln.get('Geometry') or {}).get('BoundingBox') or {})
        izquierda = float(bb.get('Left', 0))
        d = abs(izquierda - cx) if izquierda >= cx else abs(lx - cx) + 0.05
        d += abs(ly - cy) * 2  # penaliza el desalineado vertical (misma fila primero)
        if d < mejor_d:
            mejor, mejor_d = str(ln.get('Text', '')).replace('[X]', '').replace('[ ]', '').strip(), d
    return mejor


def selecciones(resp: dict) -> list[tuple[str, str, float]]:
    """[(clave, 'SELECTED'|'NOT_SELECTED', confianza)] por cada SELECTION_ELEMENT.

    La clave es el texto del KEY asociado (más las palabras que acompañen al checkbox
    en el VALUE). Si el checkbox no cuelga de un KEY, se usa la LINE más cercana.
    """
    by_id = indice(resp)
    salida: list[tuple[str, str, float]] = []
    vistos: set[str] = set()
    for key in _blocks(resp):
        if not _es_key(key):
            continue
        valor_b = _valor_de(key, by_id)
        if valor_b is None:
            continue
        etiqueta = _clave_limpia(texto(key, by_id))
        palabras = [texto(h, by_id) for h in hijos(valor_b, by_id) if h.get('BlockType') == 'WORD']
        if palabras:
            etiqueta = f'{etiqueta} {" ".join(palabras)}'.strip()
        for h in hijos(valor_b, by_id):
            if h.get('BlockType') == 'SELECTION_ELEMENT':
                salida.append((etiqueta, h.get('SelectionStatus', 'NOT_SELECTED'), _conf(h)))
                vistos.add(h.get('Id', ''))
    for sel in por_tipo(resp, 'SELECTION_ELEMENT'):
        if sel.get('Id') in vistos:
            continue
        salida.append((_linea_mas_cercana(sel, resp), sel.get('SelectionStatus', 'NOT_SELECTED'), _conf(sel)))
    return salida


# ------------------------------------------------------------------ TABLES

def tablas(resp: dict) -> list[Tabla]:
    """Una Tabla por bloque TABLE: filas × columnas por RowIndex/ColumnIndex (1-based).

    Las celdas ausentes se rellenan con ''. MERGED_CELL se tolera (las CELL
    subyacentes siguen existiendo). El título sale de TABLE_TITLE si existe.
    """
    by_id = indice(resp)
    salida: list[Tabla] = []
    for t in por_tipo(resp, 'TABLE'):
        celdas = [c for c in hijos(t, by_id) if c.get('BlockType') == 'CELL']
        if not celdas:
            salida.append(Tabla([], _conf(t), ''))
            continue
        n_filas = max(int(c.get('RowIndex', 1)) for c in celdas)
        n_cols = max(int(c.get('ColumnIndex', 1)) for c in celdas)
        filas = [[''] * n_cols for _ in range(n_filas)]
        confs = []
        for c in celdas:
            r, k = int(c.get('RowIndex', 1)) - 1, int(c.get('ColumnIndex', 1)) - 1
            if 0 <= r < n_filas and 0 <= k < n_cols:
                filas[r][k] = texto(c, by_id)
            confs.append(_conf(c))
        titulos = hijos(t, by_id, 'TABLE_TITLE')
        titulo = texto(titulos[0], by_id) if titulos else ''
        conf = round(sum(confs) / len(confs), 2) if confs else _conf(t)
        salida.append(Tabla(filas, conf, titulo))
    return salida


def tabla_a_csv(tabla: Tabla) -> str:
    """CSV (stdlib) con una fila por fila de la tabla."""
    buf = io.StringIO()
    escritor = csv.writer(buf, lineterminator='\n')
    for fila in tabla.filas:
        escritor.writerow(fila)
    return buf.getvalue()


def columna(tabla: Tabla, nombre: str) -> int | None:
    """Índice de la columna cuya cabecera (normalizada) contiene `nombre`; None si no está."""
    objetivo = normalizar_clave(nombre)
    for i, celda in enumerate(tabla.cabecera):
        if objetivo and objetivo in normalizar_clave(celda):
            return i
    return None


# ----------------------------------------------------------------- QUERIES

def respuestas_queries(resp: dict) -> dict[str, Campo]:
    """alias → Campo(valor=QUERY_RESULT.Text, confianza, origen='QUERIES').

    Devuelve TODOS los alias pedidos: los que no tuvieron respuesta salen con
    valor '' y confianza 0.0 (bloque QUERY sin relación ANSWER).
    """
    by_id = indice(resp)
    salida: dict[str, Campo] = {}
    for q in por_tipo(resp, 'QUERY'):
        info = q.get('Query') or {}
        alias = info.get('Alias') or info.get('Text') or q.get('Id', '?')
        respuestas = [r for r in hijos(q, by_id, 'ANSWER') if r.get('BlockType') == 'QUERY_RESULT']
        if respuestas:
            mejor = max(respuestas, key=_conf)
            campo = Campo(str(mejor.get('Text', '')), _conf(mejor), 'QUERIES')
        else:
            campo = Campo('', 0.0, 'QUERIES')
        if alias in salida and salida[alias].vacio() is False and campo.vacio():
            continue
        salida[alias] = campo
    return salida


# ------------------------------------------------------------------ LAYOUT

def resumen_layout(resp: dict) -> dict[str, int]:
    """Conteo de bloques LAYOUT_* (LAYOUT_TITLE, LAYOUT_TABLE, LAYOUT_TEXT, ...)."""
    c = Counter(b.get('BlockType') for b in _blocks(resp) if str(b.get('BlockType', '')).startswith('LAYOUT_'))
    return dict(c.most_common())
