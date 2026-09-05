"""Integridad de fixtures/: MANIFEST.sha256, META.json, forma de cada fixture y claves de §7."""
from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from textract_lab import bedrock, cliente, queries

from conftest import DIR_FIXTURES, DOCUMENTOS, RAIZ

MANIFEST = DIR_FIXTURES / 'MANIFEST.sha256'
META = DIR_FIXTURES / 'META.json'

# Fixtures que DEBEN existir (contrato §7).
REQUERIDOS = {
    'mini': ['detect_document_text'],
    'factura_limpia': ['detect_document_text', 'analyze_document__FORMS_LAYOUT_TABLES', 'queries_factura'],
    'factura_trampa': ['detect_document_text', 'analyze_document__FORMS_LAYOUT_TABLES', 'queries_factura'],
    'factura_foto': ['detect_document_text', 'analyze_document__FORMS_LAYOUT_TABLES', 'queries_factura'],
    'formulario_inscripcion': ['detect_document_text', 'analyze_document__FORMS_LAYOUT_TABLES'],
    'orden_compra_prosa': ['detect_document_text', 'queries_orden_compra'],
}
BEDROCK_REQUERIDOS = ['orden_compra_prosa__haiku', 'orden_compra_prosa__nova', 'factura_foto__haiku',
                      'factura_foto__nova']


def _leer_manifest() -> dict[str, str]:
    entradas: dict[str, str] = {}
    for n, linea in enumerate(MANIFEST.read_text(encoding='utf-8').splitlines(), 1):
        if not linea.strip():
            continue
        partes = linea.split('  ', 1)
        assert len(partes) == 2 and len(partes[0]) == 64, f'línea {n} del MANIFEST mal formada: {linea!r}'
        entradas[partes[1].strip()] = partes[0]
    return entradas


def _archivos_fixture() -> list[str]:
    rutas = [p for p in DIR_FIXTURES.rglob('*') if p.is_file() and p.suffix in ('.json', '.gz')
             and p.name != 'META.json']
    return sorted(p.relative_to(RAIZ).as_posix() for p in rutas)


def _clave_queries(doc: str, nombre: str) -> str:
    set_q = queries.QUERIES_ORDEN_COMPRA if nombre == 'queries_orden_compra' else queries.QUERIES_FACTURA
    return cliente.clave_llamada(DOCUMENTOS[doc], 'analyze_document', ['QUERIES'], set_q).split('/', 1)[1]


# ------------------------------------------------------------- manifest

def test_manifest_existe_y_tiene_formato_sha256sum():
    assert MANIFEST.exists()
    entradas = _leer_manifest()
    assert entradas
    assert all(r.startswith('fixtures/') for r in entradas)


def test_manifest_coincide_con_los_archivos():
    entradas = _leer_manifest()
    en_disco = _archivos_fixture()
    faltan = sorted(set(entradas) - set(en_disco))
    sobran = sorted(set(en_disco) - set(entradas))
    assert not faltan, f'en el MANIFEST pero no en disco: {faltan}'
    assert not sobran, f'en disco pero no en el MANIFEST (regenera con tools/): {sobran}'
    for ruta, sha in entradas.items():
        real = hashlib.sha256((RAIZ / ruta).read_bytes()).hexdigest()
        assert real == sha, f'sha256 distinto en {ruta}: ¿fixture editado a mano? regenera el MANIFEST'


def test_manifest_valida_como_00_check(ejecutar):
    """La verificación que hace 00_check.py --offline se puede reproducir con sha256sum/shasum."""
    import shutil
    herramienta = shutil.which('shasum') or shutil.which('sha256sum')
    if not herramienta:
        pytest.skip('sin shasum/sha256sum en esta máquina')
    args = ['-a', '256', '-c', str(MANIFEST)] if herramienta.endswith('shasum') else ['-c', str(MANIFEST)]
    import subprocess
    r = subprocess.run([herramienta, *args], cwd=str(RAIZ), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ----------------------------------------------------------------- META

def test_meta_valido():
    meta = json.loads(META.read_text(encoding='utf-8'))
    assert meta['origen'] in ('sintetico', 'textract', 'mixto')
    assert date.fromisoformat(meta['generado'])
    assert meta.get('generador', '').startswith('tools/')
    assert isinstance(meta.get('nota', ''), str) and meta['nota']
    assert isinstance(meta.get('errores_inyectados', {}), dict)
    if meta['origen'] == 'sintetico':
        assert 'factura_foto' in meta['errores_inyectados']
    else:
        assert meta.get('region'), 'los fixtures reales deben indicar la región'
        assert 'cuenta' in json.dumps(meta), 'los fixtures reales deben indicar los últimos 4 dígitos de la cuenta'


def test_meta_no_esta_en_el_manifest():
    assert 'fixtures/META.json' not in _leer_manifest()


def test_banner_modo_offline_refleja_meta():
    meta = json.loads(META.read_text(encoding='utf-8'))
    banner = cliente.banner_modo('offline')
    assert banner.startswith('[OFFLINE')
    if meta['origen'] == 'textract':
        assert 'reales' in banner
    else:
        assert 'SINTÉTICOS' in banner
    assert meta['generado'] in banner


# ---------------------------------------------------------- fixtures Textract

@pytest.mark.parametrize('doc, nombre', [(d, n) for d, ns in REQUERIDOS.items() for n in ns])
def test_fixture_requerido_existe_y_tiene_blocks(doc, nombre, cargar_fixture):
    if nombre.startswith('queries_'):
        nombre = _clave_queries(doc, nombre)
    resp = cargar_fixture(f'{doc}/{nombre}')
    assert isinstance(resp.get('Blocks'), list) and resp['Blocks']
    assert resp['DocumentMetadata']['Pages'] == 1
    assert resp['ResponseMetadata']['HTTPStatusCode'] == 200
    tipos = {b['BlockType'] for b in resp['Blocks']}
    assert 'PAGE' in tipos and 'LINE' in tipos and 'WORD' in tipos
    if nombre == 'detect_document_text':
        assert 'DetectDocumentTextModelVersion' in resp
        assert tipos <= {'PAGE', 'LINE', 'WORD'}
    else:
        assert 'AnalyzeDocumentModelVersion' in resp
    if 'FORMS' in nombre:
        assert 'KEY_VALUE_SET' in tipos
    if 'QUERIES' in nombre:
        assert 'QUERY' in tipos


def test_todos_los_fixtures_cargan_y_tienen_blocks():
    for ruta in _archivos_fixture():
        if ruta.startswith('fixtures/bedrock/'):
            continue
        clave = ruta[len('fixtures/'):].replace('.json.gz', '').replace('.json', '')
        datos = cliente.leer_json(cliente.ruta_fixture(clave))
        assert datos is not None, ruta
        assert datos.get('Blocks'), f'{ruta} sin Blocks'
        ids = [b['Id'] for b in datos['Blocks']]
        assert len(ids) == len(set(ids)), f'{ruta}: Ids repetidos'
        by_id = set(ids)
        for b in datos['Blocks']:
            assert 0.0 <= float(b.get('Confidence', 100.0)) <= 100.0, f'{ruta}: Confidence fuera de rango'
            for rel in b.get('Relationships') or []:
                assert set(rel['Ids']) <= by_id, f'{ruta}: relación a un Id inexistente en {b["Id"]}'


def test_claves_de_queries_segun_hash8():
    """El nombre del fixture de QUERIES debe salir de clave_llamada() con el set del taller."""
    assert queries.hash_queries(queries.QUERIES_FACTURA) == cliente.hash_queries(queries.QUERIES_FACTURA)
    clave = cliente.clave_llamada('docs/factura_limpia.png', 'analyze_document', ['QUERIES'], queries.QUERIES_FACTURA)
    assert clave.startswith('factura_limpia/analyze_document__QUERIES__')
    assert cliente.ruta_fixture(clave).exists()
    clave_oc = cliente.clave_llamada('docs/orden_compra_prosa.png', 'analyze_document', ['QUERIES'],
                                     queries.QUERIES_ORDEN_COMPRA)
    assert cliente.ruta_fixture(clave_oc).exists()
    assert clave.split('__')[-1] != clave_oc.split('__')[-1]


def test_queries_del_taller_son_ascii_y_validas():
    queries.validar_queries(queries.QUERIES_FACTURA)
    queries.validar_queries(queries.QUERIES_ORDEN_COMPRA)
    assert [q['Alias'] for q in queries.QUERIES_FACTURA] == ['RUC_EMISOR', 'NUM_FACTURA', 'CLAVE_ACCESO',
                                                             'FECHA_EMISION', 'SUBTOTAL_15', 'IVA_15', 'VALOR_TOTAL']
    with pytest.raises(ValueError):
        queries.validar_query({'Text': '¿Cuál es el RUC?', 'Alias': 'RUC'})


def test_fixture_queries_lleva_las_queries_del_taller(resp_queries):
    resp = resp_queries('factura_limpia')
    pedidas = [b['Query'] for b in resp['Blocks'] if b['BlockType'] == 'QUERY']
    assert [(q['Text'], q['Alias']) for q in pedidas] == [(q['Text'], q['Alias']) for q in queries.QUERIES_FACTURA]


def test_llamar_offline_lee_fixture_y_fixture_faltante():
    resp = cliente.llamar('detect_document_text', 'docs/mini.png', modo='offline', silencioso=True)
    assert resp['Blocks']
    assert cliente.ULTIMA_LLAMADA['origen'] == 'fixture'
    assert cliente.ULTIMA_LLAMADA['costo_usd'] == 0.0
    with pytest.raises(cliente.FixtureFaltante) as e:
        cliente.llamar('detect_document_text', 'docs/no_existe.png', modo='offline', silencioso=True)
    assert 'fixtures/no_existe/detect_document_text.json' in str(e.value)


def test_hay_fixture():
    assert cliente.hay_fixture('docs/factura_limpia.png', 'analyze_document', ['FORMS', 'TABLES', 'LAYOUT'])
    assert not cliente.hay_fixture('docs/mini.png', 'analyze_document', ['FORMS', 'TABLES', 'LAYOUT'])


# ----------------------------------------------------------- fixtures Bedrock

@pytest.mark.parametrize('nombre', BEDROCK_REQUERIDOS)
def test_fixture_bedrock_forma(nombre):
    ruta = DIR_FIXTURES / 'bedrock' / f'{nombre}.json'
    assert ruta.exists(), f'falta {ruta.relative_to(RAIZ)}'
    datos = json.loads(ruta.read_text(encoding='utf-8'))
    for k in ('request', 'response', 'usage', 'json'):
        assert k in datos, f'{nombre}: falta {k}'
    req = datos['request']
    assert req['modelId'] in bedrock.MODELOS.values()
    assert req['inferenceConfig']['temperature'] == 0
    assert req['system'][0]['text'].strip()
    estrategia = bedrock.estrategia_para(req['modelId'])
    if estrategia == 'json_schema':
        esquema = json.loads(req['outputConfig']['textFormat']['structure']['jsonSchema']['schema'])
    else:
        esquema = req['toolConfig']['tools'][0]['toolSpec']['inputSchema']['json']
        assert req['toolConfig']['toolChoice'] == {'tool': {'name': bedrock.NOMBRE_HERRAMIENTA}}
    # Misma forma que SCHEMA_DOCUMENTO (los sintéticos replican el esquema localmente; los reales
    # grabados con tools/grabar_fixtures.py deben llevar el prompt y el esquema EXACTOS de la librería).
    assert set(esquema['required']) == set(bedrock.SCHEMA_DOCUMENTO['required'])
    assert set(esquema['properties']) == set(bedrock.SCHEMA_DOCUMENTO['properties'])
    if not datos.get('sintetico', False):
        assert req['system'][0]['text'] == bedrock.SYSTEM_PROMPT_ES
        assert esquema == bedrock.SCHEMA_DOCUMENTO
    assert bedrock.extraer_json(datos['response'], estrategia) == datos['json']
    assert datos['usage']['inputTokens'] > 0 and datos['usage']['outputTokens'] > 0
    assert set(bedrock.SCHEMA_DOCUMENTO['required']) <= set(datos['json'])


def test_fixture_bedrock_orden_compra_segun_ground_truth(ground_truth):
    gt = ground_truth('orden_compra_prosa')
    for modelo in ('haiku', 'nova'):
        datos = json.loads((DIR_FIXTURES / 'bedrock' / f'orden_compra_prosa__{modelo}.json').read_text(encoding='utf-8'))
        j = datos['json']
        assert abs(float(j['total']) - gt['total']) < 0.005
        assert j['emisor']['razon_social'].lower().startswith('tecnolog')
        monitores = [i for i in j['items'] if 'monitor' in i['descripcion'].lower()]
        assert monitores and int(monitores[0]['cantidad']) == gt['monitores']


def test_fixture_bedrock_factura_foto_corrige_la_o():
    for modelo in ('haiku', 'nova'):
        datos = json.loads((DIR_FIXTURES / 'bedrock' / f'factura_foto__{modelo}.json').read_text(encoding='utf-8'))
        j = datos['json']
        assert j['clave_acceso'] == '0109202601179045612900120010010000012341234567813'
        assert j['fecha_emision'] == '2026-09-01'
        assert j['alertas'] and j['explicacion']


def test_estructurar_offline_usa_fixture():
    r = bedrock.estructurar('', {}, [], modelo='haiku', modo='offline', documento='docs/orden_compra_prosa.png')
    assert r['modo'] == 'offline' and r['estrategia'] == 'json_schema'
    assert r['modelo_id'] == bedrock.MODELOS['haiku']
    assert r['costo_usd_aprox'] > 0
    with pytest.raises(cliente.FixtureFaltante):
        bedrock.estructurar('', {}, [], modelo='nova-micro', modo='offline', documento='docs/mini.png')
