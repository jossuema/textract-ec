"""Pipeline ETAPAS / procesar_documento sobre los fixtures (offline)."""
from __future__ import annotations

import json

import pytest

from textract_lab import bedrock, cliente, etapas
from textract_lab.modelo import Campo, Resultado, Tabla

CLAVE_OK = '0109202601179045612900120010010000012341234567813'


def test_etapas_es_la_lista_del_contrato():
    assert [f.__name__ for f in etapas.ETAPAS] == ['texto', 'estructura', 'consultas', 'clasificar_etapa', 'validar',
                                                   'salida']


def test_factura_limpia_ok(documentos):
    r = etapas.procesar_documento(documentos['factura_limpia'], modo='offline')
    assert isinstance(r, Resultado)
    assert r.tipo_documento == 'factura'
    assert r.estado == 'OK'
    assert r.alertas == []
    assert r.modo == 'offline'
    assert r.paginas == 1
    assert r.costo_usd == 0.0
    assert r.campos['VALOR_TOTAL'].valor == '944.84'
    assert r.campos['RUC_EMISOR'].valor == '1790456129001'
    assert r.campos['CLAVE_ACCESO'].valor == CLAVE_OK
    assert r.campos['FECHA_EMISION'].valor == '2026-09-01'  # normalizada a ISO
    assert {c.origen for c in r.campos.values()} <= {'FORMS', 'QUERIES', 'TABLES', 'NORMALIZADO'}
    assert len(r.tablas) >= 1 and len(r.tablas[0].datos) == 3


def test_factura_limpia_pdf_comparte_fixture(documentos):
    r = etapas.procesar_documento('docs/factura_limpia.pdf', modo='offline')
    assert r.estado == 'OK' and r.tipo_documento == 'factura'


def test_factura_trampa_revisar_dos_alertas(documentos):
    r = etapas.procesar_documento(documentos['factura_trampa'], modo='offline')
    assert r.tipo_documento == 'factura'
    assert r.estado == 'REVISAR'
    assert len(r.alertas) == 2, r.alertas
    texto = '\n'.join(r.alertas)
    assert 'ítems no suman el subtotal' in texto
    assert 'clave de acceso con dígito verificador inválido' in texto
    assert r.campos['CLAVE_ACCESO'].valor.endswith('814')


def test_factura_foto_ok_textract_leyo_bien_la_foto(documentos):
    """Dato real: la foto del celular se lee casi tan bien como el original → OK, 0 alertas.

    El momento de las alertas del taller lo da factura_trampa (OCR perfecto y documento mal),
    no la foto. La corrección O→0 sigue existiendo y se prueba abajo con campos hechos a mano.
    """
    r = etapas.procesar_documento(documentos['factura_foto'], modo='offline')
    assert r.tipo_documento == 'factura'
    assert r.estado == 'OK'
    assert r.alertas == []
    assert r.campos['CLAVE_ACCESO'].valor == CLAVE_OK
    assert r.campos['CLAVE_ACCESO'].origen != 'NORMALIZADO'  # no hizo falta corregir nada
    assert r.campos['VALOR_TOTAL'].valor == '944.84'
    assert r.campos['FECHA_EMISION'].valor == '2026-09-01'


def test_validar_corrige_o_por_cero_y_pasa_a_revisar():
    """Cubre la etapa `validar` con normalizar_sin_llm: campos a mano, sin depender de un fixture.

    Es lo que pasaría si la foto del sábado saliera peor que la grabada: el OCR confunde O con 0,
    la corrección se aplica, se anuncia como alerta y el documento queda en REVISAR (nunca en
    silencio: corregir sin avisar sería peor que no corregir).
    """
    clave_con_letra_o = CLAVE_OK[:24] + 'O' + CLAVE_OK[25:]
    assert clave_con_letra_o != CLAVE_OK
    campos = {
        'RUC_EMISOR': Campo('1790456129001', 99.0, 'QUERIES'),
        'NUM_FACTURA': Campo('001-001-000001234', 97.0, 'QUERIES'),
        'CLAVE_ACCESO': Campo(clave_con_letra_o, 73.0, 'QUERIES'),
        'FECHA_EMISION': Campo('01/09/2026', 98.0, 'QUERIES'),
        'SUBTOTAL_15': Campo('821.60', 96.0, 'QUERIES'),
        'IVA_15': Campo('123.24', 99.0, 'QUERIES'),
        'VALOR_TOTAL': Campo('944.84', 98.0, 'QUERIES'),
    }
    ctx = etapas.validar({'tipo': 'factura', 'campos': dict(campos), 'campos_canonicos': dict(campos),
                          'tablas': [], 'selecciones': []})
    assert ctx['estado'] == 'REVISAR'
    assert any(a.startswith('corregido automáticamente') for a in ctx['alertas'])
    assert ctx['campos_canonicos']['CLAVE_ACCESO'].valor == CLAVE_OK
    assert ctx['campos_canonicos']['CLAVE_ACCESO'].origen == 'NORMALIZADO'
    assert ctx['campos_canonicos']['CLAVE_ACCESO'].confianza == 73.0  # la confianza no se inventa


def test_formulario_tipo_formulario(documentos):
    r = etapas.procesar_documento(documentos['formulario_inscripcion'], modo='offline')
    assert r.tipo_documento == 'formulario'
    assert r.estado == 'OK', r.alertas
    assert r.campos['Nombre'].valor == 'Ana Lucía'
    assert r.campos['Cédula'].valor == '0103456786'
    marcados = [k for k, c in r.campos.items() if k.startswith('[') and c.valor == '[X]']
    assert len(marcados) == 3


def test_orden_compra_prosa_desconocido_con_queries_equivocadas(documentos):
    """La carta en prosa no es factura ni formulario: REVISAR por tipo desconocido.

    Y las 3 queries del set de orden de compra son la evidencia para el bonus con LLM: dos
    responden con seguridad y se equivocan, una calla. Los valores correctos son
    'Tecnología Andina Ejemplo S.A.', 1221.20 y 3 monitores (ver docs/ground_truth/).
    """
    r = etapas.procesar_documento(documentos['orden_compra_prosa'], modo='offline')
    assert r.tipo_documento == 'desconocido'
    assert r.estado == 'REVISAR'
    assert r.alertas == ['tipo de documento no reconocido: revisar manualmente']
    for alias in ('PROVEEDOR', 'TOTAL_COMPRA', 'CANT_MONITORES'):
        assert r.campos[alias].origen == 'QUERIES'
    assert r.campos['PROVEEDOR'].valor == 'Gerente de Compras'      # el cargo del firmante, no el proveedor
    assert round(r.campos['PROVEEDOR'].confianza, 1) == 60.0
    assert r.campos['TOTAL_COMPRA'].vacio()                        # el total no está escrito: hay que sumarlo
    assert r.campos['CANT_MONITORES'].valor == '27'                # las pulgadas, no la cantidad (3)
    assert round(r.campos['CANT_MONITORES'].confianza, 1) == 99.0


def test_mini_desconocido_tolera_fixtures_ausentes(documentos):
    r = etapas.procesar_documento(documentos['mini'], modo='offline')
    assert r.tipo_documento == 'desconocido'
    assert r.estado == 'REVISAR'
    assert len(r.extra['avisos']) == 2  # sin FORMS/TABLES y sin QUERIES, pero no falla


def test_recibo_extra_es_factura_incompleta(documentos):
    r = etapas.procesar_documento(documentos['recibo_restaurante'], modo='offline')
    assert r.tipo_documento == 'factura'
    assert r.estado == 'REVISAR'
    assert r.campos['RUC_EMISOR'].valor == '0990123454001'


def test_documento_sin_fixture_lanza_fixture_faltante():
    with pytest.raises(cliente.FixtureFaltante):
        etapas.procesar_documento('docs/factura_foto_real.jpg', modo='offline')


def test_sin_queries(documentos):
    r = etapas.procesar_documento(documentos['factura_limpia'], modo='offline', con_queries=False)
    assert r.estado == 'OK'
    assert {c.origen for c in r.campos.values()} <= {'FORMS', 'TABLES'}
    assert r.campos['VALOR_TOTAL'].valor == '944.84'


def test_procesar_con_contexto_expone_respuestas(documentos):
    ctx = etapas.procesar_con_contexto(documentos['factura_limpia'], modo='offline')
    assert ctx['resp_texto']['Blocks'] and ctx['resp_estructura']['Blocks'] and ctx['resp_queries']['Blocks']
    assert ctx['tipo'] == 'factura' and ctx['estado'] == 'OK'
    assert len(ctx['llamadas']) == 3 and all(ll['origen'] == 'fixture' for ll in ctx['llamadas'])
    assert isinstance(ctx['resultado'], Resultado)


def test_combinar_fuentes_gana_mayor_confianza():
    forms = {'VALOR TOTAL': Campo('944.84', 98.0, 'FORMS'), 'RUC': Campo('1790456129001', 99.5, 'FORMS')}
    respuestas = {'VALOR_TOTAL': Campo('944.84', 99.0, 'QUERIES'), 'RUC_EMISOR': Campo('1790456129001', 99.5, 'QUERIES')}
    tablas = [Tabla([['Forma de Pago', 'Valor'], ['VALOR TOTAL', '944.84']], 60.0)]
    salida = etapas.combinar_fuentes(forms, respuestas, tablas)
    assert salida['VALOR_TOTAL'].origen == 'QUERIES'
    assert salida['RUC_EMISOR'].origen == 'QUERIES'  # a igual confianza, QUERIES > FORMS
    assert etapas.combinar_fuentes({}, {}, tablas)['VALOR_TOTAL'].origen == 'TABLES'


def test_resultado_to_json_y_desde_dict(documentos):
    r = etapas.procesar_documento(documentos['factura_trampa'], modo='offline')
    datos = json.loads(r.to_json())
    assert datos['estado'] == 'REVISAR' and datos['campos']['VALOR_TOTAL']['valor'] == '944.84'
    copia = Resultado.desde_dict(datos)
    assert copia.alertas == r.alertas and copia.campos['RUC_EMISOR'] == r.campos['RUC_EMISOR']
    assert copia.tablas[0].filas == r.tablas[0].filas


def test_json_del_llm_revalidado_por_el_modulo_11():
    """'El LLM propone, el módulo 11 dispone': el JSON del fixture de Bedrock vuelve a pasar por validar_factura."""
    from textract_lab.validadores import validar_factura

    r = bedrock.estructurar('', {}, [], modelo='haiku', modo='offline', documento='docs/factura_foto.jpg')
    campos = bedrock.json_a_campos(r['json'])
    assert campos['CLAVE_ACCESO'].valor == CLAVE_OK and campos['CLAVE_ACCESO'].origen == 'LLM'
    assert validar_factura(campos, []) == []
