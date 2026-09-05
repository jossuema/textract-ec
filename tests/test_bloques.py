"""Navegación del grafo de Blocks sobre los fixtures (misma forma que la respuesta cruda de boto3)."""
from __future__ import annotations

from textract_lab import bloques
from textract_lab.modelo import Campo, Tabla

CLAVE_OK = '0109202601179045612900120010010000012341234567813'


# ------------------------------------------------------------- texto

def test_lineas_no_vacio_y_con_confianza(resp_texto):
    lineas = bloques.lineas(resp_texto('factura_limpia'))
    assert lineas
    assert all(isinstance(t, str) and t for t, _ in lineas)
    assert all(0.0 <= c <= 100.0 for _, c in lineas)


def test_lineas_mini_conserva_espanol(resp_texto):
    textos = [t for t, _ in bloques.lineas(resp_texto('mini'))]
    assert len(textos) == 4
    assert any('¿Funciona el español?' in t for t in textos)
    assert any('ñ' in t for t in textos)


def test_texto_completo_y_confianza_media(resp_texto):
    resp = resp_texto('factura_limpia')
    completo = bloques.texto_completo(resp)
    assert 'FACTURA' in completo and '1790456129001' in completo
    assert completo.count('\n') == len(bloques.lineas(resp)) - 1
    assert 97.0 <= bloques.confianza_media(resp, 'LINE') <= 100.0
    assert bloques.confianza_media(resp_texto('factura_foto'), 'WORD') < bloques.confianza_media(resp, 'WORD')
    assert bloques.confianza_media({}, 'LINE') == 0.0


def test_indice_hijos_texto_recursivo(resp_texto):
    resp = resp_texto('factura_limpia')
    by_id = bloques.indice(resp)
    pagina = bloques.por_tipo(resp, 'PAGE')[0]
    lineas = [b for b in bloques.hijos(pagina, by_id) if b['BlockType'] == 'LINE']
    assert len(lineas) == len(bloques.lineas(resp))
    for ln in lineas[:10]:
        palabras = bloques.hijos(ln, by_id)
        assert palabras and all(w['BlockType'] == 'WORD' for w in palabras)
        assert bloques.texto(ln, by_id) == ln['Text']


def test_resumen_bloques(resp_estructura):
    resumen = bloques.resumen_bloques(resp_estructura('factura_limpia'))
    for tipo in ('PAGE', 'LINE', 'WORD', 'KEY_VALUE_SET', 'TABLE', 'CELL'):
        assert resumen.get(tipo, 0) > 0, tipo
    assert resumen['PAGE'] == 1


# ------------------------------------------------------------- FORMS

def test_pares_clave_valor_factura_limpia(resp_estructura):
    pares = bloques.pares_clave_valor(resp_estructura('factura_limpia'))
    assert 'RUC' in pares
    assert pares['RUC'].valor == '1790456129001'
    assert pares['RUC'].origen == 'FORMS'
    assert pares['VALOR TOTAL'].valor == '944.84'
    assert pares['CLAVE DE ACCESO'].valor == CLAVE_OK
    assert pares['Fecha Emisión'].valor == '01/09/2026'
    for campo in pares.values():
        assert isinstance(campo, Campo)
        assert 0.0 <= campo.confianza <= 100.0
    assert not any(k.endswith(':') for k in pares)


def test_pares_clave_valor_confianza_minima(resp_estructura):
    """La confianza del par es min(conf KEY, conf VALUE)."""
    resp = resp_estructura('factura_limpia')
    by_id = bloques.indice(resp)
    pares = bloques.pares_clave_valor(resp)
    for key in bloques.por_tipo(resp, 'KEY_VALUE_SET'):
        if 'KEY' not in key.get('EntityTypes', []):
            continue
        clave = bloques.texto(key, by_id).rstrip(':').strip()
        if clave != 'RUC':
            continue
        valor = bloques.hijos(key, by_id, 'VALUE')[0]
        assert pares['RUC'].confianza == min(key['Confidence'], valor['Confidence'])
        break
    else:
        raise AssertionError("no se encontró el KEY 'RUC' en el fixture")


def test_pares_clave_valor_trampa_lleva_clave_invalida(resp_estructura):
    pares = bloques.pares_clave_valor(resp_estructura('factura_trampa'))
    assert pares['CLAVE DE ACCESO'].valor.endswith('814')


def test_buscar_clave_normalizada(resp_estructura):
    pares = bloques.pares_clave_valor(resp_estructura('factura_limpia'))
    assert bloques.buscar_clave(pares, 'ruc').valor == '1790456129001'
    assert bloques.buscar_clave(pares, 'Fecha emision').valor == '01/09/2026'
    assert bloques.buscar_clave(pares, 'no existe') is None


# ------------------------------------------------------------- TABLES

def test_tablas_factura_limpia_items(resp_estructura):
    tablas = bloques.tablas(resp_estructura('factura_limpia'))
    assert tablas and all(isinstance(t, Tabla) for t in tablas)
    items = tablas[0]
    assert items.cabecera == ['Cant.', 'Descripción', 'Precio Unitario', 'Descuento', 'Precio Total']
    assert len(items.datos) == 3
    assert [f[-1] for f in items.datos] == ['700.00', '85.60', '36.00']
    assert items.datos[1][1] == 'Teclado mecánico ES'
    assert 0.0 < items.confianza <= 100.0


def test_tablas_factura_trampa_item_2(resp_estructura):
    items = bloques.tablas(resp_estructura('factura_trampa'))[0]
    assert items.datos[1][-1] == '95.60'


def test_tabla_a_csv_y_columna(resp_estructura):
    items = bloques.tablas(resp_estructura('factura_limpia'))[0]
    csv_txt = bloques.tabla_a_csv(items)
    filas = csv_txt.strip().split('\n')
    assert len(filas) == 4
    assert filas[0].startswith('Cant.,')
    assert '"Monitor 27"" 4K Ejemplo"' in filas[1]  # comillas escapadas según CSV
    assert bloques.columna(items, 'precio total') == 4
    assert bloques.columna(items, 'no existe') is None


def test_tablas_tolera_respuesta_vacia():
    assert bloques.tablas({}) == []
    assert bloques.tablas({'Blocks': [{'Id': 't', 'BlockType': 'TABLE', 'Confidence': 90}]})[0].filas == []


# ------------------------------------------------------------- QUERIES

def test_respuestas_queries_factura_limpia(resp_queries):
    """Las 7 queries (escritas en inglés) responden sobre una factura en ESPAÑOL.

    Cifras reales de Textract (fixtures grabados el 2026-09-04, us-east-1). Queries está
    documentado como "solo inglés": aquí funcionó, pero fuera del soporte oficial, y por eso
    el Lab 3 no se queda con una sola fuente.
    """
    r = bloques.respuestas_queries(resp_queries('factura_limpia'))
    assert {alias: campo.valor for alias, campo in r.items()} == {
        'RUC_EMISOR': '1790456129001',
        'NUM_FACTURA': '001-001-000001234',
        'CLAVE_ACCESO': CLAVE_OK,
        'FECHA_EMISION': '01/09/2026',
        'SUBTOTAL_15': '821.60',
        'IVA_15': '123.24',
        'VALOR_TOTAL': '944.84',
    }
    assert {alias: round(campo.confianza, 1) for alias, campo in r.items()} == {
        'RUC_EMISOR': 99.0, 'NUM_FACTURA': 97.0, 'CLAVE_ACCESO': 83.0, 'FECHA_EMISION': 98.0,
        'SUBTOTAL_15': 96.0, 'IVA_15': 99.0, 'VALOR_TOTAL': 98.0,
    }
    assert all(campo.origen == 'QUERIES' for campo in r.values())
    # El campo más largo (49 dígitos) es el único que baja de 90: por eso FORMS le gana en el Lab 3.
    assert min(r, key=lambda a: r[a].confianza) == 'CLAVE_ACCESO'
    assert all(campo.confianza > 90 for alias, campo in r.items() if alias != 'CLAVE_ACCESO')


def test_queries_sobre_prosa_responden_con_seguridad_y_se_equivocan(resp_queries):
    """Sobre prosa, Queries no dice "no sé": responde con seguridad y se equivoca (dato real).

    - PROVEEDOR → 'Gerente de Compras' (60.0): es el CARGO de quien firma por el comprador,
      no el proveedor ('Tecnología Andina Ejemplo S.A.').
    - TOTAL_COMPRA → sin respuesta: correcto, el total (1221.20) no está escrito, hay que sumarlo.
    - CANT_MONITORES → '27' (99.0): son las PULGADAS del monitor, no la cantidad (3).
    Una respuesta incorrecta con 99 % de confianza es el argumento del bonus: hace falta un LLM,
    y aun así el LLM tampoco decide solo (todo vuelve a pasar por los validadores).
    """
    r = bloques.respuestas_queries(resp_queries('orden_compra_prosa'))
    assert set(r) == {'PROVEEDOR', 'TOTAL_COMPRA', 'CANT_MONITORES'}
    assert all(campo.origen == 'QUERIES' for campo in r.values())

    assert r['PROVEEDOR'].valor == 'Gerente de Compras'
    assert round(r['PROVEEDOR'].confianza, 1) == 60.0
    assert r['PROVEEDOR'].valor != 'Tecnología Andina Ejemplo S.A.'  # la respuesta es segura y falsa

    assert r['TOTAL_COMPRA'].vacio()
    assert r['TOTAL_COMPRA'].confianza == 0.0

    assert r['CANT_MONITORES'].valor == '27'
    assert round(r['CANT_MONITORES'].confianza, 1) == 99.0
    assert r['CANT_MONITORES'].valor != '3'  # 27 son las pulgadas, no la cantidad


def test_respuestas_queries_factura_foto_solo_baja_en_clave_acceso(resp_queries, resp_estructura):
    """Textract es robusto: la foto responde los mismos valores que el original.

    Lo único que se degrada es la confianza del campo más largo: CLAVE_ACCESO baja de 83.0 a 73.0.
    """
    foto = bloques.respuestas_queries(resp_queries('factura_foto'))
    limpia = bloques.respuestas_queries(resp_queries('factura_limpia'))
    assert {a: c.valor for a, c in foto.items()} == {a: c.valor for a, c in limpia.items()}
    assert foto['VALOR_TOTAL'].valor == '944.84'
    assert foto['VALOR_TOTAL'].confianza == 98.0 == limpia['VALOR_TOTAL'].confianza
    assert round(foto['CLAVE_ACCESO'].confianza, 1) == 73.0
    assert foto['CLAVE_ACCESO'].confianza < limpia['CLAVE_ACCESO'].confianza
    # En la foto, FORMS gana el campo largo con holgura: es la competencia de fuentes del Lab 3.
    forms = bloques.pares_clave_valor(resp_estructura('factura_foto'))
    assert forms['CLAVE DE ACCESO'].confianza > foto['CLAVE_ACCESO'].confianza


# ------------------------------------------------------------- SELECCIONES

def test_selecciones_formulario_8_checkboxes_3_marcados(resp_estructura):
    sel = bloques.selecciones(resp_estructura('formulario_inscripcion'))
    assert len(sel) == 8
    marcados = [clave for clave, estado, _ in sel if estado == 'SELECTED']
    assert len(marcados) == 3
    assert set(marcados) == {'Workshop OCR con Textract', 'Sí', 'Intermedio'}
    assert all(estado in ('SELECTED', 'NOT_SELECTED') for _, estado, _ in sel)
    assert all(0 < conf <= 100 for _, _, conf in sel)


def test_texto_marca_seleccion():
    by_id = {}
    assert bloques.texto({'BlockType': 'SELECTION_ELEMENT', 'SelectionStatus': 'SELECTED'}, by_id) == '[X]'
    assert bloques.texto({'BlockType': 'SELECTION_ELEMENT', 'SelectionStatus': 'NOT_SELECTED'}, by_id) == '[ ]'


def test_pares_clave_valor_formulario(resp_estructura):
    pares = bloques.pares_clave_valor(resp_estructura('formulario_inscripcion'))
    assert pares['Nombre'].valor == 'Ana Lucía'
    assert pares['Cédula'].valor == '0103456786'
    assert pares['Correo'].valor == 'ana.sarmiento@ejemplo.ec'
    assert pares['Workshop OCR con Textract'].valor == '[X]'
    assert pares['Serverless'].valor == '[ ]'


# ------------------------------------------------------------- normalización

def test_normalizar_clave():
    assert bloques.normalizar_clave('  RUC: ') == 'ruc'
    assert bloques.normalizar_clave('Descripción') == 'descripcion'
    assert bloques.normalizar_clave('VALOR  TOTAL::') == 'valor total'
    assert bloques.normalizar_clave(None) == ''
