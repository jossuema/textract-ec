"""Validadores deterministas: vectores del contrato (§6), parseo, reglas de factura y normalización."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from textract_lab.modelo import Campo, Tabla
from textract_lab.validadores import (dv_cedula, dv_clave_acceso, dv_clave_acceso_esperado, dv_ruc,
                                      estado_final, normalizar_sin_llm, parse_fecha, parse_monto,
                                      validar_factura, validar_formulario)

CLAVE_OK = '0109202601179045612900120010010000012341234567813'
CLAVE_MAL = '0109202601179045612900120010010000012341234567814'


# ------------------------------------------------------------- módulo 10/11

@pytest.mark.parametrize('cedula, esperado', [
    ('0103456786', True),    # vector del contrato
    ('0103456785', False),   # dv incorrecto
    ('0103456786001', False),  # 13 dígitos no es cédula
    ('010345678', False),    # 9 dígitos
    ('O103456786', False),   # letra O en vez de 0
    ('2503456786', False),   # provincia 25 no existe
    ('0163456786', False),   # tercer dígito >= 6
    ('', False),
    (None, False),
])
def test_dv_cedula(cedula, esperado):
    assert dv_cedula(cedula) is esperado


@pytest.mark.parametrize('ruc, esperado', [
    ('1790456129001', True),   # sociedad privada, Pichincha (contrato)
    ('0103456786001', True),   # persona natural (contrato)
    ('0990123454001', True),   # sociedad privada Guayas (docs/extra/recibo_restaurante)
    ('1790456129002', False),  # sufijo distinto de 001
    ('1790456128001', False),  # dv incorrecto
    ('0103456785001', False),  # cédula base inválida
    ('179045612900', False),   # 12 dígitos
    ('179O456129001', False),  # letra O
])
def test_dv_ruc(ruc, esperado):
    assert dv_ruc(ruc) is esperado


def test_dv_ruc_publico_calculado():
    """RUC público (tercer dígito 6): módulo 11 con 3,2,7,6,5,4,3,2 sobre 8 dígitos, dv en el 9º, sufijo 0001."""
    base = '17600012'
    suma = sum(int(d) * c for d, c in zip(base, [3, 2, 7, 6, 5, 4, 3, 2]))
    residuo = suma % 11
    dv = 0 if residuo == 0 else 11 - residuo
    assert dv != 10
    assert dv_ruc(f'{base}{dv}0001') is True
    assert dv_ruc(f'{base}{(dv + 1) % 10}0001') is False
    assert dv_ruc(f'{base}{dv}001') is False  # sufijo de sociedad privada no vale


@pytest.mark.parametrize('clave, esperado', [
    (CLAVE_OK, True),
    (CLAVE_MAL, False),
    (CLAVE_OK[:-1], False),          # 48 dígitos
    (CLAVE_OK + '3', False),         # 50 dígitos
    ('010920260117904561290012O010010000012341234567813', False),  # letra O
])
def test_dv_clave_acceso(clave, esperado):
    assert dv_clave_acceso(clave) is esperado


def test_dv_clave_acceso_esperado():
    assert dv_clave_acceso_esperado(CLAVE_MAL) == 3
    assert dv_clave_acceso_esperado(CLAVE_OK) == 3
    assert dv_clave_acceso_esperado('123') is None


# ------------------------------------------------------------------- parseo

@pytest.mark.parametrize('texto, esperado', [
    ('944.84', Decimal('944.84')),
    ('$ 944.84', Decimal('944.84')),
    ('1,234.56', Decimal('1234.56')),
    ('USD 12', Decimal('12.00')),
    ('0.00', Decimal('0.00')),
    ('1.234,56', Decimal('1234.56')),
    ('821,60', Decimal('821.60')),
    (944.84, Decimal('944.84')),
    ('', None),
    ('sin monto', None),
    (None, None),
])
def test_parse_monto(texto, esperado):
    assert parse_monto(texto) == esperado


@pytest.mark.parametrize('texto, esperado', [
    ('01/09/2026', date(2026, 9, 1)),
    ('01-09-2026', date(2026, 9, 1)),
    ('2026-09-01', date(2026, 9, 1)),
    ('01/09/2026 09:15:00', date(2026, 9, 1)),
    ('31/02/2026', None),
    ('hoy', None),
    ('', None),
])
def test_parse_fecha(texto, esperado):
    assert parse_fecha(texto) == esperado


# ------------------------------------------------------------ factura

def _campos_factura(clave: str = CLAVE_OK, conf: float = 99.0, origen: str = 'QUERIES') -> dict[str, Campo]:
    return {
        'RUC_EMISOR': Campo('1790456129001', conf, origen),
        'NUM_FACTURA': Campo('001-001-000001234', conf, origen),
        'CLAVE_ACCESO': Campo(clave, conf, origen),
        'FECHA_EMISION': Campo('01/09/2026', conf, origen),
        'SUBTOTAL_15': Campo('821.60', conf, origen),
        'SUBTOTAL_SIN_IMPUESTOS': Campo('821.60', conf, origen),
        'IVA_15': Campo('123.24', conf, origen),
        'PROPINA': Campo('0.00', conf, origen),
        'VALOR_TOTAL': Campo('944.84', conf, origen),
    }


def _tabla_items(precio_item2: str = '85.60') -> Tabla:
    return Tabla([
        ['Cant.', 'Descripción', 'Precio Unitario', 'Descuento', 'Precio Total'],
        ['2', 'Monitor 27" 4K Ejemplo', '350.00', '0.00', '700.00'],
        ['1', 'Teclado mecánico ES', '85.60', '0.00', precio_item2],
        ['3', 'Cable HDMI 2.1 2m', '12.00', '0.00', '36.00'],
    ], 99.0, '')


def test_validar_factura_limpia_sin_alertas():
    assert validar_factura(_campos_factura(), [_tabla_items()]) == []


def test_validar_factura_trampa_dos_alertas():
    alertas = validar_factura(_campos_factura(clave=CLAVE_MAL), [_tabla_items('95.60')])
    assert len(alertas) == 2, alertas
    texto = '\n'.join(alertas)
    assert 'ítems no suman el subtotal' in texto
    assert 'clave de acceso con dígito verificador inválido' in texto
    assert '831.60' in texto and '821.60' in texto


def test_validar_factura_con_claves_forms_sinonimos():
    """Acepta claves crudas de FORMS ('RUC', 'VALOR TOTAL', 'IVA 15%'...) además de los alias canónicos."""
    campos = {
        'RUC': Campo('1790456129001', 99, 'FORMS'),
        'No.': Campo('001-001-000001234', 99, 'FORMS'),
        'CLAVE DE ACCESO': Campo(CLAVE_OK, 99, 'FORMS'),
        'Fecha Emisión': Campo('01/09/2026', 99, 'FORMS'),
        'SUBTOTAL 15%': Campo('821.60', 99, 'FORMS'),
        'IVA 15%': Campo('123.24', 99, 'FORMS'),
        'VALOR TOTAL': Campo('944.84', 99, 'FORMS'),
    }
    assert validar_factura(campos, [_tabla_items()]) == []


def test_validar_factura_campos_faltantes():
    alertas = validar_factura({}, [])
    assert len(alertas) == 7
    assert all(a.startswith('no se encontró ') for a in alertas)


def test_validar_factura_iva_y_total_no_cuadran():
    campos = _campos_factura()
    campos['IVA_15'] = Campo('120.00', 99, 'QUERIES')
    alertas = validar_factura(campos, [_tabla_items()])
    assert any('IVA 15% no cuadra' in a for a in alertas)
    assert any('el total no cuadra' in a for a in alertas)


def test_validar_factura_fecha_futura_y_ruc_invalido():
    campos = _campos_factura()
    campos['FECHA_EMISION'] = Campo('01/01/2099', 99, 'QUERIES')
    campos['RUC_EMISOR'] = Campo('1790456128001', 99, 'QUERIES')
    alertas = validar_factura(campos, [_tabla_items()])
    assert any('posterior a hoy' in a for a in alertas)
    assert any('RUC_EMISOR con dígito verificador inválido' in a for a in alertas)


def test_validar_factura_confianza_baja():
    campos = _campos_factura()
    campos['VALOR_TOTAL'] = Campo('944.84', 71.0, 'QUERIES')
    alertas = validar_factura(campos, [_tabla_items()])
    assert alertas == ['confianza baja en VALOR_TOTAL: 71.0 < 90 (origen QUERIES)']


def test_validar_factura_propina_ausente_no_alerta():
    campos = _campos_factura()
    del campos['PROPINA']
    assert validar_factura(campos, [_tabla_items()]) == []


# -------------------------------------------------------------- formulario

def _selecciones(track_marcados=('Workshop OCR con Textract',)):
    grupos = {
        'Workshop OCR con Textract': 'track', 'Serverless': 'track', 'Datos y analítica': 'track',
        'Sí': 'cuenta', 'No': 'cuenta',
        'Principiante': 'nivel', 'Intermedio': 'nivel', 'Avanzado': 'nivel',
    }
    marcados = set(track_marcados) | {'Sí', 'Intermedio'}
    return [(k, 'SELECTED' if k in marcados else 'NOT_SELECTED', 98.0) for k in grupos]


def _campos_formulario(cedula='0103456786', correo='ana.sarmiento@ejemplo.ec'):
    return {'Nombre': Campo('Ana Lucía', 98, 'FORMS'), 'Cédula': Campo(cedula, 98, 'FORMS'),
            'Correo': Campo(correo, 98, 'FORMS')}


def test_validar_formulario_ok():
    assert validar_formulario(_campos_formulario(), _selecciones()) == []


def test_validar_formulario_cedula_y_correo_invalidos():
    alertas = validar_formulario(_campos_formulario(cedula='0103456785', correo='ana.sarmiento'), _selecciones())
    assert any('cédula con dígito verificador inválido' in a for a in alertas)
    assert any('correo sin formato válido' in a for a in alertas)


def test_validar_formulario_dos_tracks():
    alertas = validar_formulario(_campos_formulario(), _selecciones(('Workshop OCR con Textract', 'Serverless')))
    assert any(a.startswith('track:') and 'exactamente 1' in a for a in alertas)


# ------------------------------------------------------------ normalización

def test_normalizar_sin_llm_corrige_o_por_cero():
    campos = {'CLAVE_ACCESO': Campo('010920260117904561290012O010010000012341234567813', 80.0, 'QUERIES')}
    salida, alertas = normalizar_sin_llm(campos)
    assert salida['CLAVE_ACCESO'].valor == CLAVE_OK
    assert salida['CLAVE_ACCESO'].origen == 'NORMALIZADO'
    assert salida['CLAVE_ACCESO'].confianza == 80.0
    assert alertas == [f'corregido automáticamente: 010920260117904561290012O010010000012341234567813 → {CLAVE_OK}']


def test_normalizar_sin_llm_no_toca_lo_valido():
    campos = _campos_factura()
    salida, alertas = normalizar_sin_llm(campos)
    assert alertas == []
    assert salida['CLAVE_ACCESO'].origen == 'QUERIES'
    assert salida['RUC_EMISOR'].valor == '1790456129001'


def test_normalizar_sin_llm_fecha_iso_y_montos():
    campos = {'FECHA_EMISION': Campo('01/09/2026', 99, 'FORMS'), 'VALOR_TOTAL': Campo('$ 944.84', 99, 'FORMS'),
              'SUBTOTAL_15': Campo('821.6', 99, 'FORMS')}
    salida, alertas = normalizar_sin_llm(campos)
    assert alertas == []  # solo cambios de formato: sin alerta y origen conservado
    assert salida['FECHA_EMISION'].valor == '2026-09-01'
    assert salida['VALOR_TOTAL'].valor == '944.84'
    assert salida['SUBTOTAL_15'].valor == '821.60'
    assert salida['VALOR_TOTAL'].origen == 'FORMS'


def test_normalizar_sin_llm_ruc_con_l_por_uno():
    campos = {'RUC_EMISOR': Campo('l790456129001', 90, 'FORMS')}
    salida, alertas = normalizar_sin_llm(campos)
    assert salida['RUC_EMISOR'].valor == '1790456129001'
    assert len(alertas) == 1 and 'corregido automáticamente' in alertas[0]


def test_normalizar_sin_llm_no_corrige_si_sigue_invalido():
    campos = {'CLAVE_ACCESO': Campo('O' + CLAVE_MAL[1:], 90, 'FORMS')}
    salida, alertas = normalizar_sin_llm(campos)
    assert salida['CLAVE_ACCESO'].valor == 'O' + CLAVE_MAL[1:]
    assert alertas == []


# --------------------------------------------------------------- estado

def test_estado_final():
    assert estado_final([]) == 'OK'
    assert estado_final(['algo']) == 'REVISAR'
