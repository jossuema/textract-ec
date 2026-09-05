#!/usr/bin/env python3
"""Genera fixtures SINTÉTICOS con la forma exacta de las respuestas de Amazon Textract y Bedrock.

Lee docs/ground_truth/<doc>.layout.json (geometría de cada palabra dibujada por
tools/gen_docs.py) y docs/ground_truth/<doc>.json (valores de negocio) y escribe:

  fixtures/<stem>/detect_document_text.json
  fixtures/<stem>/analyze_document__FORMS_LAYOUT_TABLES.json
  fixtures/<stem>/analyze_document__QUERIES__<hash8>.json
  fixtures/bedrock/<stem>__<modelo>.json
  fixtures/META.json
  fixtures/MANIFEST.sha256

Los fixtures NO son salidas reales de AWS: imitan la estructura (PAGE, LINE, WORD,
KEY_VALUE_SET, TABLE/CELL, SELECTION_ELEMENT, QUERY/QUERY_RESULT, LAYOUT_*)
para que todos los labs funcionen en modo offline hoy. El ponente los reemplaza
con tools/grabar_fixtures.py desde su cuenta (AWS_PROFILE=personal, us-east-1).

Uso:
    python3 tools/gen_fixtures_sinteticos.py

No requiere credenciales, red ni dependencias fuera de la stdlib.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import random
import sys
import uuid
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GROUND_TRUTH = RAIZ / 'docs' / 'ground_truth'
FIXTURES = RAIZ / 'fixtures'
FECHA_GENERACION = '2026-09-03'
LIMITE_TOTAL_BYTES = 4 * 1024 * 1024  # si se supera, se guardan .json.gz

if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# ---------------------------------------------------------------------------
# Queries y clave de fixture: se importan de textract_lab si ya existe; si no,
# se replica la fórmula EXACTA del contrato (§4 y §7) para que el nombre del
# archivo coincida cuando la librería esté lista. Verificar tras integrar:
#   python3 -c "from textract_lab import cliente, queries; print(cliente.clave_llamada('docs/factura_limpia.png','analyze_document',['QUERIES'],queries.QUERIES_FACTURA))"
# ---------------------------------------------------------------------------
_QUERIES_FACTURA_LOCAL = [
    {'Text': 'What is the RUC of the issuer?', 'Alias': 'RUC_EMISOR'},
    {'Text': 'What is the FACTURA No.?', 'Alias': 'NUM_FACTURA'},
    {'Text': 'What is the CLAVE DE ACCESO?', 'Alias': 'CLAVE_ACCESO'},
    {'Text': 'What is the FECHA EMISION date?', 'Alias': 'FECHA_EMISION'},
    {'Text': 'What is the SUBTOTAL 15% amount?', 'Alias': 'SUBTOTAL_15'},
    {'Text': 'What is the IVA 15% amount?', 'Alias': 'IVA_15'},
    {'Text': 'What is the VALOR TOTAL?', 'Alias': 'VALOR_TOTAL'},
]
_QUERIES_ORDEN_COMPRA_LOCAL = [
    {'Text': 'Who is the supplier?', 'Alias': 'PROVEEDOR'},
    {'Text': 'What is the total amount of the purchase?', 'Alias': 'TOTAL_COMPRA'},
    {'Text': 'How many monitors were purchased?', 'Alias': 'CANT_MONITORES'},
]


def _stem_local(documento: str | Path) -> str:
    return Path(documento).stem


def _clave_llamada_local(documento, operacion, feature_types=None, queries=None) -> str:
    """Réplica de textract_lab.cliente.clave_llamada (§4 del contrato)."""
    clave = f'{_stem_local(documento)}/{operacion}'
    if feature_types:
        clave += '__' + '_'.join(sorted(feature_types))
    if queries:
        hash8 = hashlib.sha256(json.dumps(queries, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:8]
        clave += f'__{hash8}'
    return clave


ORIGEN_CLAVES = []
try:
    from textract_lab.queries import QUERIES_FACTURA, QUERIES_ORDEN_COMPRA  # type: ignore
    ORIGEN_CLAVES.append('queries: textract_lab')
    if [dict(q) for q in QUERIES_FACTURA] != _QUERIES_FACTURA_LOCAL or [dict(q) for q in QUERIES_ORDEN_COMPRA] != _QUERIES_ORDEN_COMPRA_LOCAL:
        print('AVISO: las queries de textract_lab.queries difieren de las del contrato; se usan las de la librería.')
except Exception:  # la librería aún no existe o está a medio escribir
    QUERIES_FACTURA = _QUERIES_FACTURA_LOCAL
    QUERIES_ORDEN_COMPRA = _QUERIES_ORDEN_COMPRA_LOCAL
    ORIGEN_CLAVES.append('queries: réplica local (§4)')
try:
    from textract_lab.cliente import clave_llamada  # type: ignore
    ORIGEN_CLAVES.append('clave_llamada: textract_lab')
except Exception:
    clave_llamada = _clave_llamada_local
    ORIGEN_CLAVES.append('clave_llamada: réplica local (§7)')
ORIGEN_CLAVES = '; '.join(ORIGEN_CLAVES)

try:
    from textract_lab.bedrock import MODELOS, SCHEMA_DOCUMENTO, SYSTEM_PROMPT_ES  # type: ignore
    ORIGEN_BEDROCK = 'textract_lab'
except Exception:
    ORIGEN_BEDROCK = 'réplica local'
    MODELOS = {
        'haiku': 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
        'haiku-global': 'global.anthropic.claude-haiku-4-5-20251001-v1:0',
        'nova': 'amazon.nova-lite-v1:0',
        'nova-micro': 'amazon.nova-micro-v1:0',
    }
    SCHEMA_DOCUMENTO = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'tipo_documento': {'type': 'string'},
            'emisor': {'type': 'object', 'additionalProperties': False,
                       'properties': {'razon_social': {'type': 'string'}, 'ruc': {'type': 'string'}},
                       'required': ['razon_social', 'ruc']},
            'comprador': {'type': 'object', 'additionalProperties': False,
                          'properties': {'nombre': {'type': 'string'}, 'identificacion': {'type': 'string'}},
                          'required': ['nombre', 'identificacion']},
            'numero_factura': {'type': 'string'},
            'fecha_emision': {'type': 'string', 'description': 'YYYY-MM-DD'},
            'clave_acceso': {'type': 'string'},
            'items': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': {'descripcion': {'type': 'string'}, 'cantidad': {'type': 'number'},
                               'precio_unitario': {'type': 'number'}, 'total': {'type': 'number'}},
                'required': ['descripcion', 'cantidad', 'precio_unitario', 'total']}},
            'subtotal': {'type': 'number'},
            'iva': {'type': 'number'},
            'propina': {'type': 'number'},
            'total': {'type': 'number'},
            'moneda': {'type': 'string'},
            'alertas': {'type': 'array', 'items': {'type': 'string'}},
            'explicacion': {'type': 'string'},
        },
        'required': ['tipo_documento', 'emisor', 'comprador', 'numero_factura', 'fecha_emision', 'clave_acceso',
                     'items', 'subtotal', 'iva', 'propina', 'total', 'moneda', 'alertas', 'explicacion'],
    }
    SYSTEM_PROMPT_ES = (
        'Eres un asistente que estructura documentos comerciales ecuatorianos a partir del texto extraído por OCR. '
        'Reglas: no inventes datos; si un campo no aparece, deja cadena vacía o 0 y agrega una alerta; '
        'fechas en formato YYYY-MM-DD; moneda USD por defecto; valida que el RUC tenga 13 dígitos y que '
        'subtotal + IVA + propina cuadre con el total; explica cada alerta en una frase; responde siempre en español.'
    )


# ---------------------------------------------------------------------------
# Utilidades de geometría e identificadores
# ---------------------------------------------------------------------------

class Fabrica:
    """Fabrica bloques Textract con ids uuid4 deterministas y confianzas con semilla."""

    def __init__(self, ancho: int, alto: int, conf_min: float, conf_max: float, semilla: int = 42):
        self.ancho, self.alto = ancho, alto
        self.conf_min, self.conf_max = conf_min, conf_max
        self.rng = random.Random(semilla)
        self.bloques: list[dict] = []

    def id(self) -> str:
        # uuid4 válido (versión 4, variante RFC 4122) derivado del generador con semilla → reproducible.
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def conf(self, fija: float | None = None) -> float:
        if fija is not None:
            return float(fija)
        return round(self.rng.uniform(self.conf_min, self.conf_max), 6)

    def geometria(self, bbox: list[float], poligono: list[list[float]] | None = None) -> dict:
        x0, y0, x1, y1 = bbox
        w, h = self.ancho, self.alto
        if poligono is None:
            poligono = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        return {
            'BoundingBox': {'Width': round((x1 - x0) / w, 6), 'Height': round((y1 - y0) / h, 6),
                            'Left': round(x0 / w, 6), 'Top': round(y0 / h, 6)},
            'Polygon': [{'X': round(px / w, 6), 'Y': round(py / h, 6)} for px, py in poligono],
        }

    def bloque(self, tipo: str, bbox=None, poligono=None, conf: float | None = None, **campos) -> dict:
        b: dict = {'BlockType': tipo, 'Id': self.id(), 'Page': 1}
        if bbox is not None:
            b['Confidence'] = self.conf(conf)
            b['Geometry'] = self.geometria(bbox, poligono)
        b.update(campos)
        self.bloques.append(b)
        return b


def union_bbox(bboxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in bboxes), min(b[1] for b in bboxes), max(b[2] for b in bboxes), max(b[3] for b in bboxes)]


def union_poligono(elementos: list[dict]) -> list[list[float]] | None:
    """Polígono rotado que envuelve varios elementos con 'poligono' (esquinas extremas)."""
    pols = [e['poligono'] for e in elementos if e.get('poligono')]
    if not pols:
        return None
    return [pols[0][0], pols[-1][1], pols[-1][2], pols[0][3]]


def relacion(tipo: str, ids: list[str]) -> dict:
    return {'Type': tipo, 'Ids': list(ids)}


def ordenar_lectura(elementos: list[dict]) -> list[dict]:
    """Orden de lectura aproximado: por fila (y) y luego por x."""
    return sorted(elementos, key=lambda e: (round(e['bbox'][1] / 40), e['bbox'][0]))


# ---------------------------------------------------------------------------
# Construcción de la respuesta
# ---------------------------------------------------------------------------

def aplicar_errores_foto(layout: dict) -> list[str]:
    """Inyecta en el layout de factura_foto los errores de OCR de §7 y devuelve su descripción."""
    descripciones = []
    for e in layout['elementos']:
        if e['rol'] == 'valor' and len(e['texto']) == 49 and e['texto'].isdigit():
            # Un '0' de la clave de acceso leído como 'O' (el primer 0 tras el RUC, posición 24: ...129001|2|001001...)
            pos = 24
            nuevo = e['texto'][:pos] + 'O' + e['texto'][pos + 1:]
            if e['texto'] != nuevo:
                e['texto'] = nuevo
                e['palabras'][0]['texto'] = nuevo
                e['ocr_error'] = 'O_por_0'
                if not descripciones:
                    descripciones.append(f"clave de acceso: el dígito {pos + 1} ('0') se lee como letra 'O' en WORD, LINE, VALUE y QUERY_RESULT "
                                         "(tanto en NÚMERO DE AUTORIZACIÓN como en CLAVE DE ACCESO) → normalizar_sin_llm debe corregir O→0")
        if e['rol'] == 'valor' and e['texto'] == '944.84':
            e['confianza_fija'] = 71.0
    descripciones.append("VALOR TOTAL '944.84' leído correctamente pero con confianza 71 (WORD, LINE, VALUE y QUERY_RESULT) → alerta 'confianza baja' y estado REVISAR")
    return descripciones


def construir(layout: dict, operacion: str, feature_types: list[str] | None, queries: list[dict] | None,
              respuestas: dict[str, str] | None, conf_rango: tuple[float, float], semilla: int) -> dict:
    """Construye una respuesta con la forma de boto3 a partir del layout."""
    F = Fabrica(layout['ancho'], layout['alto'], conf_rango[0], conf_rango[1], semilla)
    feature_types = feature_types or []
    elementos = layout['elementos']
    con_texto = [e for e in elementos if e['rol'] in ('titulo', 'linea', 'clave', 'valor', 'celda') and e['palabras']]

    pagina = F.bloque('PAGE', [0, 0, layout['ancho'], layout['alto']], conf=None)
    del pagina['Confidence']  # PAGE no lleva Confidence en Textract

    # --- WORD y LINE ---
    palabras_por_elemento: dict[str, list[dict]] = {}
    grupos: dict[str, list[dict]] = {}
    for e in ordenar_lectura(con_texto):
        grupos.setdefault(e.get('linea') or e['id'], []).append(e)
    lineas: list[dict] = []
    linea_de_elemento: dict[str, dict] = {}
    for gid, miembros in grupos.items():
        miembros = sorted(miembros, key=lambda e: e['bbox'][0])
        conf_fija = next((e['confianza_fija'] for e in miembros if 'confianza_fija' in e), None)
        conf_linea = F.conf(conf_fija)
        palabras_ids: list[str] = []
        for e in miembros:
            wl = []
            for p in e['palabras']:
                w = F.bloque('WORD', p['bbox'], p.get('poligono'), conf=conf_fija if conf_fija else None,
                             Text=p['texto'], TextType='PRINTED')
                if 'RotationAngle' not in w and layout.get('rotacion_grados'):
                    w['Geometry']['RotationAngle'] = -float(layout['rotacion_grados'])
                wl.append(w)
            palabras_por_elemento[e['id']] = wl
            palabras_ids.extend(w['Id'] for w in wl)
        texto_linea = ' '.join(e['texto'] for e in miembros)
        bbox = union_bbox([e['bbox'] for e in miembros])
        linea = F.bloque('LINE', bbox, union_poligono(miembros), conf=conf_linea, Text=texto_linea,
                         Relationships=[relacion('CHILD', palabras_ids)])
        lineas.append(linea)
        for e in miembros:
            linea_de_elemento[e['id']] = linea
    hijos_pagina = [l['Id'] for l in lineas]

    # --- FORMS: KEY_VALUE_SET y SELECTION_ELEMENT ---
    claves_kv: list[dict] = []
    selecciones: dict[str, dict] = {}
    if 'FORMS' in feature_types:
        pares: dict[str, dict[str, dict]] = {}
        for e in elementos:
            if e.get('par'):
                pares.setdefault(e['par'], {})[e['rol']] = e
        for pid, partes in pares.items():
            clave = partes.get('clave')
            if not clave:
                continue
            valor = partes.get('valor')
            casilla = partes.get('checkbox')
            conf_par = F.conf(valor.get('confianza_fija') if valor else None)
            if casilla:
                sel = F.bloque('SELECTION_ELEMENT', casilla['bbox'], casilla.get('poligono'), conf=None,
                               SelectionStatus=casilla['estado'])
                selecciones[casilla['id']] = sel
                bloque_valor = F.bloque('KEY_VALUE_SET', casilla['bbox'], casilla.get('poligono'), conf=conf_par,
                                        EntityTypes=['VALUE'], Relationships=[relacion('CHILD', [sel['Id']])])
            elif valor and valor['palabras']:
                ids_valor = [w['Id'] for w in palabras_por_elemento.get(valor['id'], [])]
                bloque_valor = F.bloque('KEY_VALUE_SET', valor['bbox'], valor.get('poligono'), conf=conf_par,
                                        EntityTypes=['VALUE'], Relationships=[relacion('CHILD', ids_valor)])
            else:
                bbox_vacio = valor['bbox'] if valor else [clave['bbox'][2] + 10, clave['bbox'][1], clave['bbox'][2] + 400, clave['bbox'][3]]
                bloque_valor = F.bloque('KEY_VALUE_SET', bbox_vacio, (valor or {}).get('poligono'), conf=conf_par, EntityTypes=['VALUE'])
            ids_clave = [w['Id'] for w in palabras_por_elemento.get(clave['id'], [])]
            bloque_clave = F.bloque('KEY_VALUE_SET', clave['bbox'], clave.get('poligono'), conf=conf_par, EntityTypes=['KEY'],
                                    Relationships=[relacion('VALUE', [bloque_valor['Id']]), relacion('CHILD', ids_clave)])
            claves_kv.append(bloque_clave)
        hijos_pagina.extend(b['Id'] for b in claves_kv)
        hijos_pagina.extend(s['Id'] for s in selecciones.values())

    # --- TABLES: TABLE y CELL ---
    tablas: list[dict] = []
    if 'TABLES' in feature_types:
        por_tabla: dict[str, list[dict]] = {}
        for e in elementos:
            if e['rol'] == 'celda':
                por_tabla.setdefault(e['tabla'], []).append(e)
        titulos = {e['tabla']: e for e in elementos if e['rol'] == 'tabla_titulo'}
        for tid, celdas in por_tabla.items():
            celdas = sorted(celdas, key=lambda c: (c['fila'], c['col']))
            ids_celdas = []
            for c in celdas:
                campos = {'RowIndex': c['fila'], 'ColumnIndex': c['col'], 'RowSpan': 1, 'ColumnSpan': 1}
                ids_palabras = [w['Id'] for w in palabras_por_elemento.get(c['id'], [])]
                if ids_palabras:
                    campos['Relationships'] = [relacion('CHILD', ids_palabras)]
                if c.get('cabecera'):
                    campos['EntityTypes'] = ['COLUMN_HEADER']
                celda = F.bloque('CELL', c['celda_bbox'], c.get('celda_poligono'), conf=None, **campos)
                ids_celdas.append(celda['Id'])
            bbox = union_bbox([c['celda_bbox'] for c in celdas])
            tabla = F.bloque('TABLE', bbox, (titulos.get(tid) or {}).get('poligono'), conf=None,
                             EntityTypes=['STRUCTURED_TABLE'], Relationships=[relacion('CHILD', ids_celdas)])
            tablas.append(tabla)
        hijos_pagina.extend(t['Id'] for t in tablas)

    # --- LAYOUT ---
    if 'LAYOUT' in feature_types:
        ids_lineas_tabla = set()
        for e in elementos:
            if e['rol'] == 'celda' and e['id'] in linea_de_elemento:
                ids_lineas_tabla.add(linea_de_elemento[e['id']]['Id'])
        ids_lineas_kv = set()
        for e in elementos:
            if e['rol'] in ('clave', 'valor') and e['id'] in linea_de_elemento:
                ids_lineas_kv.add(linea_de_elemento[e['id']]['Id'])
        ids_lineas_titulo = set()
        for e in elementos:
            if e['rol'] == 'titulo' and e['id'] in linea_de_elemento:
                ids_lineas_titulo.add(linea_de_elemento[e['id']]['Id'])
        layouts = []
        for l in lineas:
            if l['Id'] in ids_lineas_titulo:
                layouts.append(F.bloque('LAYOUT_TITLE', _bbox_de(l, F), conf=None, Relationships=[relacion('CHILD', [l['Id']])]))
        # Un LAYOUT_TABLE por tabla y un LAYOUT_KEY_VALUE por bloque de pares; LAYOUT_TEXT con el resto.
        for t in tablas:
            ids = [l['Id'] for l in lineas if l['Id'] in ids_lineas_tabla and _dentro(l, t)]
            if ids:
                layouts.append(F.bloque('LAYOUT_TABLE', _bbox_de(t, F), conf=None, Relationships=[relacion('CHILD', ids)]))
        ids_kv = [l['Id'] for l in lineas if l['Id'] in ids_lineas_kv and l['Id'] not in ids_lineas_tabla]
        if ids_kv:
            bb = union_bbox([_bbox_de(l, F) for l in lineas if l['Id'] in ids_kv])
            layouts.append(F.bloque('LAYOUT_KEY_VALUE', bb, conf=None, Relationships=[relacion('CHILD', ids_kv)]))
        resto = [l for l in lineas if l['Id'] not in ids_lineas_titulo | ids_lineas_tabla | set(ids_kv)]
        if resto:
            bb = union_bbox([_bbox_de(l, F) for l in resto])
            layouts.append(F.bloque('LAYOUT_TEXT', bb, conf=None, Relationships=[relacion('CHILD', [l['Id'] for l in resto])]))
        hijos_pagina.extend(b['Id'] for b in layouts)

    # --- QUERIES ---
    if 'QUERIES' in feature_types and queries:
        for q in queries:
            bloque_q = F.bloque('QUERY', None, Query={'Text': q['Text'], 'Alias': q['Alias']})
            texto = (respuestas or {}).get(q['Alias'])
            if texto is None:
                continue  # sin respuesta: QUERY sin Relationships (como hace Textract)
            fuente = next((e for e in elementos if e['rol'] == 'valor' and e['texto'] == texto), None) or \
                next((e for e in elementos if e['texto'] == texto), None)
            if fuente is None:
                raise ValueError(f'no encuentro en el layout el texto {texto!r} para la query {q["Alias"]}')
            res = F.bloque('QUERY_RESULT', fuente['bbox'], fuente.get('poligono'),
                           conf=fuente.get('confianza_fija'), Text=texto)
            bloque_q['Relationships'] = [relacion('ANSWER', [res['Id']])]
            hijos_pagina.append(bloque_q['Id'])

    pagina['Relationships'] = [relacion('CHILD', hijos_pagina)]

    resp = {'DocumentMetadata': {'Pages': 1}, 'Blocks': F.bloques}
    if operacion == 'detect_document_text':
        resp['DetectDocumentTextModelVersion'] = '1.0'
    else:
        resp['AnalyzeDocumentModelVersion'] = '1.0'
    resp['ResponseMetadata'] = {
        'HTTPStatusCode': 200,
        'RequestId': f'sintetico-{layout["documento"]}-{operacion}' + (('-' + '-'.join(sorted(feature_types)).lower()) if feature_types else ''),
        'HTTPHeaders': {}, 'RetryAttempts': 0,
    }
    return resp


def _bbox_de(bloque: dict, F: Fabrica) -> list[float]:
    bb = bloque['Geometry']['BoundingBox']
    return [bb['Left'] * F.ancho, bb['Top'] * F.alto, (bb['Left'] + bb['Width']) * F.ancho, (bb['Top'] + bb['Height']) * F.alto]


def _dentro(linea: dict, tabla: dict) -> bool:
    a, b = linea['Geometry']['BoundingBox'], tabla['Geometry']['BoundingBox']
    cx, cy = a['Left'] + a['Width'] / 2, a['Top'] + a['Height'] / 2
    return b['Left'] - 0.01 <= cx <= b['Left'] + b['Width'] + 0.01 and b['Top'] - 0.01 <= cy <= b['Top'] + b['Height'] + 0.01


# ---------------------------------------------------------------------------
# Fixtures de Bedrock
# ---------------------------------------------------------------------------

def texto_linealizado(resp_texto: dict) -> str:
    return '\n'.join(b['Text'] for b in resp_texto['Blocks'] if b['BlockType'] == 'LINE')


def prompt_usuario(texto: str, campos: dict, alertas: list[str]) -> str:
    return (
        'Estructura el siguiente documento según el esquema.\n\n'
        f'TEXTO OCR (Amazon Textract):\n{texto}\n\n'
        f'CAMPOS YA EXTRAÍDOS (alias: valor · confianza):\n{json.dumps(campos, ensure_ascii=False, indent=1)}\n\n'
        f'ALERTAS DE LOS VALIDADORES:\n{json.dumps(alertas, ensure_ascii=False)}\n'
    )


def fixture_bedrock(stem: str, clave_modelo: str, texto: str, campos: dict, alertas: list[str], salida_json: dict,
                    usage: dict) -> dict:
    model_id = MODELOS[clave_modelo]
    request = {
        'modelId': model_id,
        'system': [{'text': SYSTEM_PROMPT_ES}],
        'messages': [{'role': 'user', 'content': [{'text': prompt_usuario(texto, campos, alertas)}]}],
        'inferenceConfig': {'temperature': 0, 'maxTokens': 1024},
    }
    if model_id.startswith(('us.anthropic', 'global.anthropic', 'anthropic.')):
        request['outputConfig'] = {'textFormat': {'type': 'json_schema', 'structure': {'jsonSchema': {
            'name': 'documento', 'description': 'Documento comercial estructurado (factura, orden de compra, formulario).',
            'schema': json.dumps(SCHEMA_DOCUMENTO, ensure_ascii=False)}}}}
        content = [{'text': json.dumps(salida_json, ensure_ascii=False)}]
        estrategia = 'json_schema'
    else:
        request['toolConfig'] = {
            'tools': [{'toolSpec': {'name': 'registrar_documento',
                                    'description': 'Registra el documento comercial estructurado.',
                                    'inputSchema': {'json': SCHEMA_DOCUMENTO}}}],
            'toolChoice': {'tool': {'name': 'registrar_documento'}},
        }
        content = [{'toolUse': {'toolUseId': f'tooluse_sintetico_{stem}', 'name': 'registrar_documento', 'input': salida_json}}]
        estrategia = 'tool_use'
    return {
        'sintetico': True,
        'nota': 'Respuesta SINTÉTICA con la forma de bedrock-runtime converse(); no proviene de un modelo real.',
        'documento': stem, 'modelo': clave_modelo, 'estrategia': estrategia,
        'request': request,
        'response': {
            'output': {'message': {'role': 'assistant', 'content': content}},
            'stopReason': 'end_turn' if estrategia == 'json_schema' else 'tool_use',
            'usage': usage,
            'metrics': {'latencyMs': 1840},
            'ResponseMetadata': {'HTTPStatusCode': 200, 'RequestId': f'sintetico-bedrock-{stem}-{clave_modelo}', 'HTTPHeaders': {}, 'RetryAttempts': 0},
        },
        'usage': usage,
        'json': salida_json,
    }


def json_orden_compra(gt: dict) -> dict:
    return {
        'tipo_documento': 'orden_compra',
        'emisor': {'razon_social': gt['proveedor'], 'ruc': ''},
        'comprador': {'nombre': gt['comprador'], 'identificacion': ''},
        'numero_factura': '',
        'fecha_emision': gt['fecha_carta'],
        'clave_acceso': '',
        'items': [
            {'descripcion': 'Monitor de 27 pulgadas', 'cantidad': 3, 'precio_unitario': 350.00, 'total': 1050.00},
            {'descripcion': 'Teclado mecánico', 'cantidad': 2, 'precio_unitario': 85.60, 'total': 171.20},
        ],
        'subtotal': 1221.20, 'iva': 0.0, 'propina': 0.0, 'total': 1221.20, 'moneda': 'USD',
        'alertas': [
            'El documento es una carta de confirmación de compra, no una factura: no tiene número, clave de acceso ni RUC.',
            'No se indica IVA; el total 1221.20 es la suma de los ítems (3 × 350.00 + 2 × 85.60) sin impuestos.',
        ],
        'explicacion': (
            'Carta fechada en Cuenca el 28 de agosto de 2026 en la que Andina Datos Ejemplo confirma a '
            'Tecnología Andina Ejemplo S.A. la compra de tres monitores de 27 pulgadas a 350 dólares y dos teclados '
            'mecánicos a 85.60 dólares, con entrega en Calle Larga 4-56 antes del 10 de septiembre y pago por transferencia. '
            'Las cantidades y precios están en prosa, por eso las consultas de Textract fallaron: una no respondió '
            'y las otras dos respondieron mal.'
        ),
    }


def json_factura_foto(gt: dict) -> dict:
    return {
        'tipo_documento': 'factura',
        'emisor': {'razon_social': gt['emisor']['razon_social'], 'ruc': gt['emisor']['ruc']},
        'comprador': {'nombre': gt['comprador']['nombre'], 'identificacion': gt['comprador']['identificacion']},
        'numero_factura': gt['numero_factura'],
        'fecha_emision': gt['fecha_emision_iso'],
        'clave_acceso': gt['clave_acceso'],
        'items': [{'descripcion': i['descripcion'], 'cantidad': int(i['cantidad']), 'precio_unitario': float(i['precio_unitario']),
                   'total': float(i['precio_total'])} for i in gt['items']],
        'subtotal': 821.60, 'iva': 123.24, 'propina': 0.0, 'total': 944.84, 'moneda': 'USD',
        'alertas': [
            "Clave de acceso: el OCR leyó una letra 'O' en la posición 25; se corrigió a '0' porque la clave del SRI solo admite dígitos y así el dígito verificador (módulo 11) cuadra.",
            'VALOR TOTAL leído con confianza 71 %: se mantiene 944.84 porque coincide con SUBTOTAL 15% (821.60) + IVA 15% (123.24).',
        ],
        'explicacion': (
            'Factura electrónica de Tecnología Andina Ejemplo S.A. (RUC 1790456129001) a Comunidad AWS Ecuador Ejemplo, '
            'No. 001-001-000001234 del 1 de septiembre de 2026, con tres ítems por 821.60 más IVA 15 % de 123.24; total 944.84 USD. '
            'La foto está inclinada y con poca luz, por eso hay confianzas bajas, pero la aritmética cuadra.'
        ),
    }


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def cargar(nombre: str) -> tuple[dict, dict]:
    layout = json.loads((GROUND_TRUTH / f'{nombre}.layout.json').read_text(encoding='utf-8'))
    gt = json.loads((GROUND_TRUTH / f'{nombre}.json').read_text(encoding='utf-8'))
    return layout, gt


def escribir(clave: str, datos: dict, comprimir: bool) -> Path:
    ruta = FIXTURES / (clave + ('.json.gz' if comprimir else '.json'))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cuerpo = json.dumps(datos, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if comprimir:
        with gzip.open(ruta, 'wb') as f:
            f.write(cuerpo)
    else:
        ruta.write_bytes(cuerpo)
    return ruta


def generar_todo(comprimir: bool) -> tuple[list[Path], dict]:
    escritos: list[Path] = []
    errores_inyectados: dict[str, list[str]] = {}
    LIMPIO, FOTO = (97.0, 99.9), (62.0, 96.0)
    FEATURES = ['FORMS', 'TABLES', 'LAYOUT']

    def emitir(clave: str, datos: dict) -> None:
        ruta = escribir(clave, datos, comprimir)
        escritos.append(ruta)
        print(f'  {ruta.relative_to(RAIZ).as_posix():70s} {ruta.stat().st_size / 1024:7.1f} KB  bloques={len(datos.get("Blocks", []))}')

    # mini: solo detect_document_text
    layout, _ = cargar('mini')
    emitir(clave_llamada('docs/mini.png', 'detect_document_text'), construir(layout, 'detect_document_text', None, None, None, LIMPIO, 1))

    # facturas limpia y trampa: 3 fixtures cada una
    respuestas_cache: dict[str, dict] = {}
    for nombre, semilla in (('factura_limpia', 10), ('factura_trampa', 20)):
        layout, gt = cargar(nombre)
        doc = f'docs/{nombre}.png'
        respuestas = dict(gt['campos_esperados'])
        emitir(clave_llamada(doc, 'detect_document_text'), construir(layout, 'detect_document_text', None, None, None, LIMPIO, semilla))
        emitir(clave_llamada(doc, 'analyze_document', FEATURES), construir(layout, 'analyze_document', FEATURES, None, None, LIMPIO, semilla + 1))
        emitir(clave_llamada(doc, 'analyze_document', ['QUERIES'], QUERIES_FACTURA),
               construir(layout, 'analyze_document', ['QUERIES'], QUERIES_FACTURA, respuestas, LIMPIO, semilla + 2))

    # factura_foto: confianzas bajas, geometría rotada y errores inyectados
    layout, gt = cargar('factura_foto')
    errores_inyectados['factura_foto'] = aplicar_errores_foto(layout)
    respuestas = dict(gt['campos_esperados'])
    clave_con_o = next(e['texto'] for e in layout['elementos'] if e.get('ocr_error') == 'O_por_0')
    respuestas['CLAVE_ACCESO'] = clave_con_o
    doc = 'docs/factura_foto.jpg'
    detect_foto = construir(layout, 'detect_document_text', None, None, None, FOTO, 30)
    emitir(clave_llamada(doc, 'detect_document_text'), detect_foto)
    emitir(clave_llamada(doc, 'analyze_document', FEATURES), construir(layout, 'analyze_document', FEATURES, None, None, FOTO, 31))
    emitir(clave_llamada(doc, 'analyze_document', ['QUERIES'], QUERIES_FACTURA),
           construir(layout, 'analyze_document', ['QUERIES'], QUERIES_FACTURA, respuestas, FOTO, 32))

    # formulario: detect + FORMS_LAYOUT_TABLES
    layout, _ = cargar('formulario_inscripcion')
    doc = 'docs/formulario_inscripcion.png'
    emitir(clave_llamada(doc, 'detect_document_text'), construir(layout, 'detect_document_text', None, None, None, LIMPIO, 40))
    emitir(clave_llamada(doc, 'analyze_document', FEATURES), construir(layout, 'analyze_document', FEATURES, None, None, LIMPIO, 41))

    # orden de compra en prosa: detect + QUERIES sin respuesta
    layout, gt_orden = cargar('orden_compra_prosa')
    doc = 'docs/orden_compra_prosa.png'
    detect_orden = construir(layout, 'detect_document_text', None, None, None, LIMPIO, 50)
    emitir(clave_llamada(doc, 'detect_document_text'), detect_orden)
    emitir(clave_llamada(doc, 'analyze_document', ['QUERIES'], QUERIES_ORDEN_COMPRA),
           construir(layout, 'analyze_document', ['QUERIES'], QUERIES_ORDEN_COMPRA, {}, LIMPIO, 51))

    # recibo extra: detect + FORMS_LAYOUT_TABLES (para 04_sistema.py si se pasa docs/extra)
    layout, _ = cargar('recibo_restaurante')
    doc = 'docs/extra/recibo_restaurante.png'
    emitir(clave_llamada(doc, 'detect_document_text'), construir(layout, 'detect_document_text', None, None, None, LIMPIO, 60))
    emitir(clave_llamada(doc, 'analyze_document', FEATURES), construir(layout, 'analyze_document', FEATURES, None, None, LIMPIO, 61))

    # --- Bedrock ---
    campos_orden = {q['Alias']: {'valor': '', 'confianza': 0.0, 'origen': 'QUERIES'} for q in QUERIES_ORDEN_COMPRA}
    alertas_orden = ['las 3 consultas de Textract fallaron sobre prosa: una sin respuesta y dos con valor incorrecto']
    salida_orden = json_orden_compra(gt_orden)
    gt_foto = json.loads((GROUND_TRUTH / 'factura_foto.json').read_text(encoding='utf-8'))
    campos_foto = {
        'RUC_EMISOR': {'valor': '1790456129001', 'confianza': 88.4, 'origen': 'QUERIES'},
        'NUM_FACTURA': {'valor': '001-001-000001234', 'confianza': 90.1, 'origen': 'QUERIES'},
        'CLAVE_ACCESO': {'valor': clave_con_o, 'confianza': 79.6, 'origen': 'QUERIES'},
        'FECHA_EMISION': {'valor': '01/09/2026', 'confianza': 85.3, 'origen': 'QUERIES'},
        'SUBTOTAL_15': {'valor': '821.60', 'confianza': 86.9, 'origen': 'QUERIES'},
        'IVA_15': {'valor': '123.24', 'confianza': 84.2, 'origen': 'QUERIES'},
        'VALOR_TOTAL': {'valor': '944.84', 'confianza': 71.0, 'origen': 'QUERIES'},
    }
    alertas_foto = ['clave de acceso contiene caracteres no numéricos (O)', 'confianza baja en VALOR_TOTAL (71.0)']
    salida_foto = json_factura_foto(gt_foto)
    bedrock = [
        ('orden_compra_prosa', 'haiku', texto_linealizado(detect_orden), campos_orden, alertas_orden, salida_orden, {'inputTokens': 812, 'outputTokens': 260, 'totalTokens': 1072}),
        ('orden_compra_prosa', 'nova', texto_linealizado(detect_orden), campos_orden, alertas_orden, salida_orden, {'inputTokens': 905, 'outputTokens': 248, 'totalTokens': 1153}),
        ('factura_foto', 'haiku', texto_linealizado(detect_foto), campos_foto, alertas_foto, salida_foto, {'inputTokens': 1418, 'outputTokens': 402, 'totalTokens': 1820}),
        ('factura_foto', 'nova', texto_linealizado(detect_foto), campos_foto, alertas_foto, salida_foto, {'inputTokens': 1533, 'outputTokens': 388, 'totalTokens': 1921}),
    ]
    for stem, modelo, texto, campos, alertas, salida, usage in bedrock:
        ruta = escribir(f'bedrock/{stem}__{modelo}', fixture_bedrock(stem, modelo, texto, campos, alertas, salida, usage), comprimir)
        escritos.append(ruta)
        print(f'  {ruta.relative_to(RAIZ).as_posix():70s} {ruta.stat().st_size / 1024:7.1f} KB')

    meta = {
        'origen': 'sintetico',
        'generado': FECHA_GENERACION,
        'generador': 'tools/gen_fixtures_sinteticos.py',
        'nota': 'Fixtures sintéticos con la forma de la respuesta de Textract; NO son salidas reales. '
                'Reemplázalos con tools/grabar_fixtures.py desde tu cuenta (AWS_PROFILE=personal, us-east-1).',
        'region': None,
        'modelo_textract': None,
        'comprimidos': comprimir,
        'claves_segun': ORIGEN_CLAVES,
        'bedrock_segun': ORIGEN_BEDROCK,
        'confianzas': {'limpios': '97-99.9 con random.Random(42 + semilla por documento)', 'factura_foto': '62-96'},
        'errores_inyectados': errores_inyectados,
    }
    return escritos, meta


def escribir_manifest(rutas: list[Path]) -> Path:
    lineas = []
    for ruta in sorted(rutas, key=lambda r: r.relative_to(RAIZ).as_posix()):
        h = hashlib.sha256(ruta.read_bytes()).hexdigest()
        lineas.append(f'{h}  {ruta.relative_to(RAIZ).as_posix()}')
    manifest = FIXTURES / 'MANIFEST.sha256'
    manifest.write_text('\n'.join(lineas) + '\n', encoding='utf-8')
    return manifest


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description='Regenera fixtures/ SINTÉTICOS (Textract + Bedrock), fixtures/META.json y '
                    'fixtures/MANIFEST.sha256 a partir de docs/ground_truth/*.layout.json. No llama a AWS.',
        epilog='Borra y reescribe todos los fixtures/<doc>/*.json y fixtures/bedrock/*.json (determinista: '
               'con la misma librería produce los mismos bytes).')
    parser.parse_args(argv)
    print(f'Claves de fixture según: {ORIGEN_CLAVES}; esquema Bedrock según: {ORIGEN_BEDROCK}')
    FIXTURES.mkdir(parents=True, exist_ok=True)
    # Limpia fixtures previos (json y json.gz) para no dejar huérfanos en el manifest.
    for viejo in list(FIXTURES.rglob('*.json')) + list(FIXTURES.rglob('*.json.gz')):
        if viejo.name != 'META.json':
            viejo.unlink()
    print('Generando fixtures sintéticos...')
    escritos, meta = generar_todo(comprimir=False)
    total = sum(r.stat().st_size for r in escritos)
    if total > LIMITE_TOTAL_BYTES:
        print(f'Total {total / 1024 / 1024:.2f} MB > 4 MB: se regeneran comprimidos (.json.gz)')
        for r in escritos:
            r.unlink()
        escritos, meta = generar_todo(comprimir=True)
        total = sum(r.stat().st_size for r in escritos)
    (FIXTURES / 'META.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = escribir_manifest(escritos)
    print(f'  {manifest.relative_to(RAIZ).as_posix():70s} {len(escritos)} entradas')
    print(f'Total fixtures: {total / 1024:.0f} KB en {len(escritos)} archivos (META.json aparte, fuera del manifest).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
