"""Regresiones de la revisión previa al taller (todo offline, sin AWS).

Cubre: cuadre de AnalyzeExpense sin TAX/GRATUITY, moneda en ExpenseField.Currency, formatear_monto con
int, queries con espacios Unicode, clave de cache por extensión (PDF vs PNG), QUERIES sin QueriesConfig,
sidecar del cache (documento cambiado), hay_cache vs hay_fixture, banner con motivo, guarda del perfil
default, META.json de grabar_fixtures en 00_check, ground truth de mini y extra 07 sin QUERIES.
"""
from __future__ import annotations

import importlib.util
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from textract_lab import cliente, queries
from textract_lab.validadores import formatear_monto

from conftest import RAIZ


def _cargar_modulo(nombre: str, ruta: str):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope='module')
def e06():
    return _cargar_modulo('extra_06_expense', 'extra/06_expense.py')


@pytest.fixture(scope='module')
def e07():
    return _cargar_modulo('extra_07_async', 'extra/07_async_s3.py')


# ------------------------------------------------------------ extra 06

def test_expense_validar_sin_tax_ni_propina_no_crashea(e06):
    alertas = e06.validar({'SUBTOTAL': ('100.00', 99.0), 'TOTAL': ('115.00', 99.0)})
    assert any('subtotal 100.00 + impuesto 0.00 + propina 0.00 = 100.00 pero TOTAL dice 115.00' in a for a in alertas)
    assert any('IVA/propina no reconocidos' in a for a in alertas)


def test_expense_validar_con_tax_cero_y_propina_cero(e06):
    alertas = e06.validar({'SUBTOTAL': ('100.00', 99.0), 'TAX': ('0.00', 99.0), 'GRATUITY': ('0.00', 99.0),
                           'TOTAL': ('100.00', 99.0)})
    assert not any('pero TOTAL dice' in a for a in alertas)


def test_expense_validar_cuadra_con_iva_y_propina(e06):
    alertas = e06.validar({'SUBTOTAL': ('100.00', 99.0), 'TAX': ('15.00', 99.0), 'GRATUITY': ('10.00', 99.0),
                           'TOTAL': ('125.00', 99.0), 'TAX_PAYER_ID': ('1790456129001', 99.0)})
    assert alertas == []


def test_expense_moneda_sale_de_expense_field_currency(e06):
    campo = {'Type': {'Text': 'TOTAL', 'Confidence': 99.0},
             'ValueDetection': {'Text': '10.00', 'Confidence': 98.5},
             'Currency': {'Code': 'USD', 'Confidence': 99.0}}
    assert e06.campo_texto(campo) == ('TOTAL', '', '10.00', 98.5, 'USD')


def test_formatear_monto_acepta_int_y_float():
    assert formatear_monto(0) == '0.00'
    assert formatear_monto(Decimal('944.845')) == '944.85'
    assert formatear_monto('85.6') == '85.60'


# ------------------------------------------------------------ queries

@pytest.mark.parametrize('texto', ['What is the\xa0total?', 'What is the\u2003total?', 'Qu\u00e9 total?'])
def test_validar_query_rechaza_espacios_unicode(texto):
    """NBSP y em-space pasan con \\s en modo Unicode pero el servicio los rechaza (un '\\n' final sí lo admite el patrón oficial)."""
    with pytest.raises(ValueError):
        queries.validar_query({'Text': texto, 'Alias': 'TOTAL'})


def test_validar_query_acepta_ascii():
    queries.validar_query({'Text': 'What is the total?', 'Alias': 'TOTAL_1'})


def test_parametros_queries_sin_queries_config_falla_antes_de_llamar():
    with pytest.raises(ValueError) as e:
        cliente._parametros(cliente.resolver_documento('docs/mini.png'), 'analyze_document', ['QUERIES'], None)
    assert 'QueriesConfig' in str(e.value)


def test_extra_07_rechaza_queries(e07):
    args = e07.parsear_args(['docs/factura_limpia.pdf', '--bucket', 'b', '--features', 'FORMS', 'QUERIES', '--dry-run'])
    with pytest.raises(ValueError) as e:
        e07.plan(args, RAIZ / 'docs' / 'factura_limpia.pdf', 'textract-ec/factura_limpia.pdf')
    assert 'QueriesConfig' in str(e.value)
    assert e07.main(['docs/factura_limpia.pdf', '--bucket', 'b', '--features', 'FORMS', 'QUERIES', '--dry-run']) == 1


# ------------------------------------------------------------ cache/clave

def test_clave_pdf_no_colisiona_con_png():
    png = cliente.clave_llamada('docs/factura_limpia.png', 'analyze_document', ['tables', 'FORMS', 'layout'])
    pdf = cliente.clave_llamada('/x/y/factura_limpia.pdf', 'analyze_document', ['tables', 'FORMS', 'layout'])
    assert png == 'factura_limpia/analyze_document__FORMS_LAYOUT_TABLES'
    assert pdf == 'factura_limpia.pdf/analyze_document__FORMS_LAYOUT_TABLES'
    assert cliente.clave_llamada('docs/factura_foto.jpg', 'detect_document_text') == 'factura_foto/detect_document_text'


def test_pdf_offline_usa_fixture_del_png_con_aviso(capsys):
    resp = cliente.llamar('detect_document_text', 'docs/factura_limpia.pdf', modo='offline')
    assert resp['Blocks']
    assert 'usando el de factura_limpia.png' in capsys.readouterr().out


def test_cache_vigente_detecta_documento_cambiado(tmp_path, monkeypatch):
    monkeypatch.setattr(cliente, 'DIR_CACHE', tmp_path / 'cache')
    doc = tmp_path / 'foto.jpg'
    doc.write_bytes(b'version 1')
    clave = cliente.clave_llamada(doc, 'detect_document_text')
    cliente.escribir_json(cliente.ruta_cache(clave), {'Blocks': [], 'DocumentMetadata': {'Pages': 1}})
    assert cliente.cache_vigente(doc, clave)[1] == 'cache sin sidecar'  # cache antiguo: se acepta
    cliente.ruta_sidecar_cache(clave).write_text(cliente.sha256_documento(doc) + '\n')
    assert cliente.cache_vigente(doc, clave)[1] == 'cache vigente'
    assert cliente.hay_cache(doc, 'detect_document_text')
    doc.write_bytes(b'version 2: la foto se repitio con el mismo nombre')
    resp, motivo = cliente.cache_vigente(doc, clave)
    assert resp is None and 'cambió' in motivo
    assert not cliente.hay_cache(doc, 'detect_document_text')


def test_hay_cache_no_confunde_fixture_con_cache(tmp_path, monkeypatch):
    """hay_fixture mira fixtures/ y hay_cache mira cache/: son dos almacenes distintos.

    El cache/ real del repo existe (se llenó al grabar los fixtures contra AWS el 2026-09-04),
    así que la prueba usa un cache/ vacío en tmp_path para aislar las dos preguntas.
    """
    features = ['FORMS', 'TABLES', 'LAYOUT']
    monkeypatch.setattr(cliente, 'DIR_CACHE', tmp_path / 'cache_vacio')
    assert cliente.hay_fixture('docs/factura_limpia.png', 'analyze_document', features)
    assert not cliente.hay_cache('docs/factura_limpia.png', 'analyze_document', features)
    # Y al revés: con solo cache/ (sin fixture) hay_cache sí responde. hay_fixture mira los dos
    # almacenes a propósito ("¿hay respuesta guardada?"); hay_cache es el único que contesta
    # "¿esta llamada en online será gratis?".
    doc = tmp_path / 'documento_sin_fixture.png'
    doc.write_bytes(b'no es un documento del taller')
    clave = cliente.clave_llamada(doc, 'analyze_document', features)
    assert not cliente.ruta_fixture(clave).exists()
    assert not cliente.hay_cache(doc, 'analyze_document', features)
    cliente.escribir_json(cliente.ruta_cache(clave), {'Blocks': [], 'DocumentMetadata': {'Pages': 1}})
    assert cliente.hay_cache(doc, 'analyze_document', features)
    assert cliente.hay_fixture(doc, 'analyze_document', features)


# ----------------------------------------------------------- modo/banner

def test_banner_offline_incluye_motivo(monkeypatch):
    monkeypatch.setattr(cliente, 'MOTIVO_OFFLINE', 'sin credenciales de AWS')
    banner = cliente.banner_modo('offline')
    assert banner.startswith('[OFFLINE · sin credenciales de AWS · fixtures')
    monkeypatch.setattr(cliente, 'MOTIVO_OFFLINE', None)
    assert cliente.banner_modo('offline').startswith('[OFFLINE · fixtures')


def test_primera_linea_sin_credenciales_es_el_banner(ejecutar, tmp_path):
    """Sin --offline y sin credenciales: la primera línea es el banner (con el motivo), no un aviso."""
    home = tmp_path / 'home_vacio'
    home.mkdir()
    env_extra = {'HOME': str(home), 'AWS_SHARED_CREDENTIALS_FILE': str(home / 'no'), 'AWS_CONFIG_FILE': str(home / 'no')}
    import subprocess, sys
    env = dict(os.environ)
    env.update({'NO_COLOR': '1', 'PYTHONIOENCODING': 'utf-8', **env_extra})
    for var in ('LAB_MODO', 'AWS_PROFILE', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
                'AWS_CONTAINER_CREDENTIALS_FULL_URI', 'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI'):
        env.pop(var, None)
    r = subprocess.run([sys.executable, '01_texto.py', 'docs/mini.png'], cwd=str(RAIZ), env=env,
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    lineas = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert lineas[0].startswith('[OFFLINE · sin credenciales de AWS · fixtures'), lineas[:2]
    assert '! [OFFLINE]' not in r.stdout


def test_bloqueo_perfil_default(monkeypatch):
    monkeypatch.setenv('LAB_BLOQUEAR_DEFAULT', '1')
    monkeypatch.setattr(cliente, 'info_credenciales',
                        lambda: {'perfil': None, 'fuente': 'shared-credentials-file', 'region': 'us-east-1',
                                 'tiene_credenciales': True, 'error': None})
    monkeypatch.setenv('LAB_MODO', 'online')
    with pytest.raises(cliente.ErrorAWS) as e:
        cliente.resolver_modo()
    assert 'AWS_PROFILE=personal' in str(e.value)
    with pytest.raises(cliente.ErrorAWS):
        cliente.resolver_modo('online')
    monkeypatch.delenv('LAB_BLOQUEAR_DEFAULT')
    assert cliente.resolver_modo() == 'online'  # sin la guarda, el perfil default es legítimo (asistentes)
    monkeypatch.setattr(cliente, 'info_credenciales',
                        lambda: {'perfil': 'personal', 'fuente': 'shared-credentials-file', 'region': 'us-east-1',
                                 'tiene_credenciales': True, 'error': None})
    monkeypatch.setenv('LAB_BLOQUEAR_DEFAULT', '1')
    assert cliente.resolver_modo() == 'online'


def test_sesion_desactiva_imds_salvo_contenedor(monkeypatch):
    monkeypatch.delenv('AWS_EC2_METADATA_DISABLED', raising=False)
    monkeypatch.delenv('AWS_CONTAINER_CREDENTIALS_FULL_URI', raising=False)
    monkeypatch.setenv('AWS_PROFILE', 'taller-tests-sin-credenciales')
    try:
        cliente._sesion()
    except Exception:  # ProfileNotFound: solo interesa el efecto sobre el entorno
        pass
    assert os.environ.get('AWS_EC2_METADATA_DISABLED') == 'true'
    monkeypatch.setenv('AWS_EC2_METADATA_DISABLED', 'false')
    try:
        cliente._sesion()
    except Exception:
        pass
    assert os.environ.get('AWS_EC2_METADATA_DISABLED') == 'false'  # lo que fijó el usuario se respeta


# ------------------------------------------------------------- 00_check

def test_00_check_muestra_meta_de_grabar_fixtures(capsys, monkeypatch):
    check = _cargar_modulo('lab_00_check', '00_check.py')
    monkeypatch.setattr(cliente, 'meta_fixtures', lambda: {
        'origen': 'textract', 'generado': '2026-09-04', 'generador': 'tools/grabar_fixtures.py', 'region': 'us-east-1',
        'cuenta_ultimos4': '1234', 'modelo_textract': {'DetectDocumentTextModelVersion': '1.0', 'AnalyzeDocumentModelVersion': '1.0'}})
    check.mostrar_meta()
    salida = capsys.readouterr().out
    assert 'cuenta ...1234' in salida and '?' not in salida.split('cuenta')[1].split('\n')[0]
    assert 'DetectDocumentTextModelVersion=1.0' in salida


def test_00_check_python_39_en_offline_es_aviso(capsys, monkeypatch):
    check = _cargar_modulo('lab_00_check_py', '00_check.py')
    import sys
    monkeypatch.setattr(sys, 'version_info', (3, 9, 6, 'final', 0))
    check.imprimir_entorno('offline')
    salida = capsys.readouterr().out
    assert 'sirve para el modo OFFLINE' in salida and '✘' not in salida


# ---------------------------------------------------------- ground truth

def test_ground_truth_mini_es_revisar_como_el_pipeline():
    gt = json.loads((RAIZ / 'docs' / 'ground_truth' / 'mini.json').read_text(encoding='utf-8'))
    assert gt['estado_esperado'] == 'REVISAR'
    assert gt['alertas_esperadas'] == ['tipo de documento no reconocido']
