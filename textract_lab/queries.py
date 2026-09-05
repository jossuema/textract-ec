"""Queries fijas del taller (inglés, ASCII puro) y su validación.

Textract Queries está documentado solo para inglés y el patrón de Query.Text
y Alias solo admite ASCII (https://docs.aws.amazon.com/textract/latest/APIReference/API_Query.html):
nada de tildes, ñ ni signos ¿¡. Máximo 15 queries por página en llamadas síncronas.
"""
from __future__ import annotations

import hashlib
import json
import re

MAX_LARGO = 200
MAX_QUERIES_SYNC = 15
# Patrón oficial de Query.Text / Query.Alias (ASCII imprimible + espacios en blanco).
# re.ASCII: sin él, \s acepta espacios Unicode (NBSP \xa0, em-space) que el servicio rechaza
# con InvalidParameterException; se valida con fullmatch para no aceptar un '\n' final.
PATRON_ASCII = re.compile(r'^[a-zA-Z0-9\s!"#$%\'&()*+,\-./:;=?@\[\\\]^_`{|}~><]+$', re.ASCII)

QUERIES_FACTURA: list[dict] = [
    {'Text': 'What is the RUC of the issuer?', 'Alias': 'RUC_EMISOR'},
    {'Text': 'What is the FACTURA No.?', 'Alias': 'NUM_FACTURA'},
    {'Text': 'What is the CLAVE DE ACCESO?', 'Alias': 'CLAVE_ACCESO'},
    {'Text': 'What is the FECHA EMISION date?', 'Alias': 'FECHA_EMISION'},
    {'Text': 'What is the SUBTOTAL 15% amount?', 'Alias': 'SUBTOTAL_15'},
    {'Text': 'What is the IVA 15% amount?', 'Alias': 'IVA_15'},
    {'Text': 'What is the VALOR TOTAL?', 'Alias': 'VALOR_TOTAL'},
]

QUERIES_ORDEN_COMPRA: list[dict] = [
    {'Text': 'Who is the supplier?', 'Alias': 'PROVEEDOR'},
    {'Text': 'What is the total amount of the purchase?', 'Alias': 'TOTAL_COMPRA'},
    {'Text': 'How many monitors were purchased?', 'Alias': 'CANT_MONITORES'},
]

SETS_DEL_TALLER: dict[str, list[dict]] = {
    'factura': QUERIES_FACTURA,
    'orden_compra': QUERIES_ORDEN_COMPRA,
}


def validar_query(q: dict) -> None:
    """Lanza ValueError si Text/Alias no cumplen el patrón ASCII o superan 200 caracteres."""
    if not isinstance(q, dict) or 'Text' not in q:
        raise ValueError(f'query inválida (se espera dict con Text y Alias): {q!r}')
    for campo in ('Text', 'Alias'):
        valor = q.get(campo)
        if campo == 'Alias' and valor is None:
            continue
        if not isinstance(valor, str) or not valor.strip():
            raise ValueError(f'{campo} de la query debe ser un texto no vacío: {q!r}')
        if len(valor) > MAX_LARGO:
            raise ValueError(f'{campo} supera {MAX_LARGO} caracteres: {valor[:40]!r}...')
        if not valor.isascii() or not PATRON_ASCII.fullmatch(valor):
            malos = sorted({c for c in valor if not (c.isascii() and PATRON_ASCII.fullmatch(c))})
            raise ValueError(
                f'{campo} contiene caracteres no ASCII {malos}: Textract solo acepta '
                f'queries en ASCII (sin tildes, ñ ni ¿¡). Query: {valor!r}'
            )


def validar_queries(queries: list[dict]) -> None:
    """Valida una lista completa (patrón, largo, máximo 15 en llamadas síncronas, alias únicos)."""
    if len(queries) > MAX_QUERIES_SYNC:
        raise ValueError(f'máximo {MAX_QUERIES_SYNC} queries por página en llamadas síncronas '
                         f'(recibidas {len(queries)})')
    alias_vistos: set[str] = set()
    for q in queries:
        validar_query(q)
        alias = q.get('Alias')
        if alias in alias_vistos:
            raise ValueError(f'alias repetido: {alias}')
        if alias is not None:
            alias_vistos.add(alias)


def hash_queries(queries: list[dict]) -> str:
    """hash8 de la clave de cache/fixture (§7 del contrato): sha256 del JSON canónico."""
    canon = json.dumps(queries, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:8]


def alias_de(queries: list[dict]) -> list[str]:
    """Lista de alias (o Text si no hay alias) en el orden dado."""
    return [q.get('Alias') or q['Text'] for q in queries]


def set_para_tipo(tipo_documento: str) -> list[dict] | None:
    """Set de queries del taller según el tipo: factura → QUERIES_FACTURA; desconocido → orden de compra."""
    if tipo_documento == 'factura':
        return QUERIES_FACTURA
    if tipo_documento in ('desconocido', 'orden_compra'):
        return QUERIES_ORDEN_COMPRA
    return None  # formulario: no hay queries en el taller
