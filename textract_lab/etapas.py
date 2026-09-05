"""Pipeline como lista de funciones (ctx) -> ctx.

ETAPAS = [texto, estructura, consultas, clasificar_etapa, validar, salida].
Cada etapa recibe y devuelve el mismo dict `ctx`; procesar_documento() lo recorre
y devuelve un Resultado. En modo offline nunca se llama a AWS: solo fixtures/cache.
Donde enchufar cosas: revisión humana (estado REVISAR), base de datos (salida),
LLM (una etapa más después de validar, ver bedrock.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import bloques, cliente, consola
from .clasificar import clasificar
from .modelo import Campo, Resultado, Tabla
from .validadores import (SINONIMOS, campos_canonicos, estado_final, normalizar_sin_llm,
                          parse_monto, validar_factura, validar_formulario)
from .queries import set_para_tipo

FEATURES_ESTRUCTURA = ['FORMS', 'TABLES', 'LAYOUT']
ORIGENES_PRIORIDAD = {'QUERIES': 0, 'FORMS': 1, 'TABLES': 2}  # desempate a igual confianza


def _nuevo_ctx(documento: str | Path, modo: str | None, con_queries: bool) -> dict:
    return {
        'documento': str(documento),
        'stem': cliente.stem(documento),
        'modo': cliente.resolver_modo(modo),
        'con_queries': con_queries,
        'resp_texto': None, 'resp_estructura': None, 'resp_queries': None,
        'lineas': [], 'campos': {}, 'campos_canonicos': {}, 'tablas': [], 'selecciones': [],
        'alertas': [], 'avisos': [], 'tipo': 'desconocido', 'evidencias': [],
        'paginas': 1, 'costo_usd': 0.0, 'llamadas': [], 'resultado': None,
    }


def _llamar(ctx: dict, operacion: str, **kw) -> dict:
    resp = cliente.llamar(operacion, ctx['documento'], modo=ctx['modo'], silencioso=True, **kw)
    ultima = dict(cliente.ULTIMA_LLAMADA)
    ctx['llamadas'].append(ultima)
    ctx['costo_usd'] = round(ctx['costo_usd'] + float(ultima.get('costo_usd') or 0.0), 6)
    ctx['paginas'] = max(ctx['paginas'], int(ultima.get('paginas') or 1))
    return resp


# ------------------------------------------------------------------ etapas

def texto(ctx: dict) -> dict:
    """DetectDocumentText → resp_texto y líneas. Obligatoria: sin fixture lanza FixtureFaltante."""
    ctx['resp_texto'] = _llamar(ctx, 'detect_document_text')
    ctx['lineas'] = bloques.lineas(ctx['resp_texto'])
    ctx['confianza_media'] = bloques.confianza_media(ctx['resp_texto'], 'WORD')
    return ctx


def estructura(ctx: dict) -> dict:
    """AnalyzeDocument FORMS+TABLES+LAYOUT → campos (FORMS), tablas y selecciones. Tolera fixture ausente."""
    try:
        resp = _llamar(ctx, 'analyze_document', feature_types=FEATURES_ESTRUCTURA)
    except cliente.FixtureFaltante as e:
        ctx['avisos'].append(f'sin FORMS/TABLES: {e}')
        return ctx
    ctx['resp_estructura'] = resp
    ctx['campos'] = bloques.pares_clave_valor(resp)
    ctx['tablas'] = bloques.tablas(resp)
    ctx['selecciones'] = bloques.selecciones(resp)
    return ctx


def consultas(ctx: dict) -> dict:
    """AnalyzeDocument QUERIES (set según el tipo tentativo) → resp_queries y combinación por confianza."""
    if not ctx.get('con_queries'):
        ctx['campos_canonicos'] = combinar_fuentes(ctx['campos'], {}, ctx['tablas'])
        ctx['campos'] = {**ctx['campos'], **ctx['campos_canonicos']}
        return ctx
    tipo_tentativo, _ = clasificar(ctx['resp_texto'], ctx.get('resp_estructura'))
    queries = set_para_tipo(tipo_tentativo)
    respuestas: dict[str, Campo] = {}
    if queries:
        try:
            ctx['resp_queries'] = _llamar(ctx, 'analyze_document', feature_types=['QUERIES'], queries=queries)
            respuestas = bloques.respuestas_queries(ctx['resp_queries'])
        except cliente.FixtureFaltante as e:
            ctx['avisos'].append(f'sin QUERIES: {e}')
    ctx['queries'] = queries or []
    ctx['respuestas_queries'] = respuestas
    ctx['campos_canonicos'] = combinar_fuentes(ctx['campos'], respuestas, ctx['tablas'])
    # El dict completo conserva FORMS crudo + alias de queries + ganadores canónicos.
    ctx['campos'] = {**ctx['campos'], **respuestas, **ctx['campos_canonicos']}
    return ctx


def clasificar_etapa(ctx: dict) -> dict:
    """Asigna tipo_documento por evidencia."""
    ctx['tipo'], ctx['evidencias'] = clasificar(ctx['resp_texto'], ctx.get('resp_estructura'))
    return ctx


def validar(ctx: dict) -> dict:
    """Reglas según el tipo; normalización sin LLM con re-validación para facturas."""
    tipo = ctx['tipo']
    if tipo == 'factura':
        canon = ctx['campos_canonicos'] or campos_canonicos(ctx['campos'])
        alertas = validar_factura(canon, ctx['tablas'])
        normalizados, alertas_norm = normalizar_sin_llm(canon)
        if alertas_norm:  # hubo correcciones O→0 / l→1: re-validar con los valores corregidos
            alertas = alertas_norm + validar_factura(normalizados, ctx['tablas'])
        ctx['campos_canonicos'] = normalizados
        ctx['campos'] = {**ctx['campos'], **normalizados}
        ctx['alertas'] = alertas
    elif tipo == 'formulario':
        ctx['alertas'] = validar_formulario(ctx['campos'], ctx['selecciones'])
    else:
        ctx['alertas'] = ['tipo de documento no reconocido: revisar manualmente']
    ctx['estado'] = estado_final(ctx['alertas'])
    return ctx


def salida(ctx: dict) -> dict:
    """Construye el Resultado final (aquí se enchufaría una base de datos o una cola de revisión)."""
    tipo = ctx['tipo']
    if tipo == 'factura':
        campos = dict(ctx['campos_canonicos'])
    else:
        campos = dict(ctx['campos'])
    if ctx.get('selecciones'):
        for clave, estado, conf in ctx['selecciones']:
            campos.setdefault(f'[{clave}]', Campo('[X]' if estado == 'SELECTED' else '[ ]', conf, 'FORMS'))
    ctx['resultado'] = Resultado(
        documento=ctx['documento'],
        tipo_documento=tipo,
        campos=campos,
        tablas=list(ctx['tablas']),
        alertas=list(ctx['alertas']),
        estado=ctx.get('estado') or estado_final(ctx['alertas']),
        paginas=int(ctx.get('paginas') or 1),
        costo_usd=float(ctx.get('costo_usd') or 0.0),
        modo=ctx['modo'],
        extra={'evidencias': ctx.get('evidencias', []), 'avisos': ctx.get('avisos', []),
               'confianza_media_palabras': ctx.get('confianza_media', 0.0),
               'llamadas': [{k: v for k, v in ll.items()} for ll in ctx.get('llamadas', [])]},
    )
    return ctx


ETAPAS: list[Callable[[dict], dict]] = [texto, estructura, consultas, clasificar_etapa, validar, salida]


# ------------------------------------------------------------ combinación

def _total_desde_tablas(tablas: list[Tabla], nombre: str) -> Campo | None:
    """Fila de totales de una tabla: 'VALOR TOTAL | 944.84' → Campo(origen='TABLES')."""
    sinonimos = set(SINONIMOS.get(nombre, ()))
    for t in tablas or []:
        for fila in t.filas:
            celdas = [c for c in fila if str(c).strip()]
            if len(celdas) < 2:
                continue
            etiqueta = bloques.normalizar_clave(celdas[-2])
            if etiqueta in sinonimos and parse_monto(celdas[-1]) is not None:
                return Campo(str(celdas[-1]).strip(), t.confianza, 'TABLES')
    return None


def combinar_fuentes(campos_forms: dict[str, Campo], respuestas: dict[str, Campo],
                     tablas: list[Tabla]) -> dict[str, Campo]:
    """Para cada campo canónico elige la fuente de mayor confianza (QUERIES vs FORMS vs TABLES).

    Devuelve alias → Campo ganador (con su 'origen'). Campos sin ninguna fuente no aparecen.
    """
    salida: dict[str, Campo] = {}
    for nombre in SINONIMOS:
        candidatos: list[Campo] = []
        q = respuestas.get(nombre)
        if q is not None and not q.vacio():
            candidatos.append(q)
        forms = campos_canonicos(campos_forms).get(nombre)
        if forms is not None and not forms.vacio():
            candidatos.append(forms)
        tab = _total_desde_tablas(tablas, nombre)
        if tab is not None:
            candidatos.append(tab)
        if candidatos:
            salida[nombre] = max(candidatos, key=lambda c: (c.confianza, -ORIGENES_PRIORIDAD.get(c.origen, 9)))
    return salida


# ---------------------------------------------------------------- pipeline

def procesar_documento(documento: str | Path, modo: str | None = None, con_queries: bool = True) -> Resultado:
    """Corre ETAPAS sobre un documento y devuelve el Resultado.

    En offline usa solo fixtures; si falta el fixture de texto lanza FixtureFaltante
    (04_sistema.py lo convierte en una fila 'SIN DATOS').
    """
    ctx = _nuevo_ctx(documento, modo, con_queries)
    for etapa in ETAPAS:
        ctx = etapa(ctx)
    return ctx['resultado']


def procesar_con_contexto(documento: str | Path, modo: str | None = None, con_queries: bool = True) -> dict:
    """Igual que procesar_documento pero devuelve el ctx completo (respuestas crudas incluidas)."""
    ctx = _nuevo_ctx(documento, modo, con_queries)
    for etapa in ETAPAS:
        ctx = etapa(ctx)
    return ctx


def tabla_campos(campos: dict[str, Campo]) -> str:
    """Tabla de consola campo | valor | confianza | origen (con semáforo)."""
    filas = []
    for k, c in campos.items():
        filas.append([k, c.valor, consola.confianza_coloreada(c.confianza), c.origen])
    return consola.tabla(filas, ['campo', 'valor', 'confianza', 'origen'])
