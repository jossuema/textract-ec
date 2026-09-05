"""Capa opcional de razonamiento con Amazon Bedrock (Converse API).

Regla del taller: "el LLM propone, el módulo 11 dispone". El JSON que devuelve
el modelo vuelve a pasar por validadores.py y toda corrección se etiqueta como alerta.

Estrategia por prefijo del modelId:
- 'us.anthropic' / 'global.anthropic' / 'anthropic.' → structured outputs (outputConfig json_schema;
  el campo `schema` es un STRING json.dumps).
- 'amazon.nova' / 'us.amazon.nova' → tool use forzado (toolConfig + toolChoice tool) y se lee toolUse.input.
- cualquier otro → prompt "responde solo JSON" + limpieza de fences + json.loads.
El cliente bedrock-runtime se crea SOLO en modo online.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import consola
from .cliente import (RAIZ, REGION_DEFAULT, ErrorAWS, FixtureFaltante, resolver_modo, stem)
from .modelo import Campo, como_campo

MODELOS: dict[str, str] = {
    'haiku': 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
    'haiku-global': 'global.anthropic.claude-haiku-4-5-20251001-v1:0',
    'nova': 'amazon.nova-lite-v1:0',
    'nova-micro': 'amazon.nova-micro-v1:0',
}
MODELO_DEFAULT = 'haiku'
DIR_FIXTURES_BEDROCK = RAIZ / 'fixtures' / 'bedrock'
MAX_TOKENS = 1024
TEMPERATURA = 0

# Precios aproximados US$ por 1M tokens (entrada, salida); NO verificados en la página oficial de AWS.
PRECIOS_1M: dict[str, tuple[float, float]] = {
    'haiku': (1.00, 5.00),
    'haiku-global': (1.00, 5.00),
    'nova': (0.06, 0.24),
    'nova-micro': (0.035, 0.14),
}
NOTA_PRECIOS = 'precios de Bedrock aproximados, no verificados en la página oficial'

_ITEM = {
    'type': 'object',
    'properties': {
        'descripcion': {'type': 'string'},
        'cantidad': {'type': 'number'},
        'precio_unitario': {'type': 'number'},
        'total': {'type': 'number'},
    },
    'required': ['descripcion', 'cantidad', 'precio_unitario', 'total'],
    'additionalProperties': False,
}

SCHEMA_DOCUMENTO: dict = {
    'type': 'object',
    'properties': {
        'tipo_documento': {'type': 'string',
                           'enum': ['factura', 'orden_compra', 'formulario', 'recibo', 'otro']},
        'emisor': {
            'type': 'object',
            'properties': {'razon_social': {'type': 'string'}, 'ruc': {'type': 'string'}},
            'required': ['razon_social', 'ruc'],
            'additionalProperties': False,
        },
        'comprador': {
            'type': 'object',
            'properties': {'nombre': {'type': 'string'}, 'identificacion': {'type': 'string'}},
            'required': ['nombre', 'identificacion'],
            'additionalProperties': False,
        },
        'numero_factura': {'type': 'string'},
        'fecha_emision': {'type': 'string', 'description': 'YYYY-MM-DD o cadena vacía'},
        'clave_acceso': {'type': 'string', 'description': '49 dígitos o cadena vacía'},
        'items': {'type': 'array', 'items': _ITEM},
        'subtotal': {'type': 'number'},
        'iva': {'type': 'number'},
        'propina': {'type': 'number'},
        'total': {'type': 'number'},
        'moneda': {'type': 'string'},
        'alertas': {'type': 'array', 'items': {'type': 'string'}},
        'explicacion': {'type': 'string', 'description': 'Explicación breve en español'},
    },
    'required': ['tipo_documento', 'emisor', 'comprador', 'numero_factura', 'fecha_emision',
                 'clave_acceso', 'items', 'subtotal', 'iva', 'propina', 'total', 'moneda',
                 'alertas', 'explicacion'],
    'additionalProperties': False,
}

SYSTEM_PROMPT_ES: str = (
    'Eres un asistente que estructura y valida texto OCR de documentos comerciales ecuatorianos '
    '(facturas electrónicas del SRI, órdenes de compra, recibos). Recibes el texto linealizado que '
    'extrajo Amazon Textract, los campos que ya se extrajeron con su confianza y las alertas de los '
    'validadores deterministas. Reglas:\n'
    '1. No inventes datos. Si un dato no aparece en el texto, deja cadena vacía o 0 y agrega una alerta.\n'
    '2. Fechas en formato YYYY-MM-DD. Montos como números con punto decimal, sin símbolos.\n'
    '3. Moneda USD por defecto (Ecuador) salvo que el documento diga otra cosa.\n'
    '4. Valida que el RUC tenga 13 dígitos y que subtotal + IVA + propina cuadre con el total; '
    'si no cuadra, agrega una alerta. Si un identificador parece tener letras donde van dígitos '
    '(O por 0, l por 1) corrígelo y agrega una alerta que lo diga.\n'
    '5. Explica cada alerta en una sola frase, en español.\n'
    '6. Responde únicamente con el JSON pedido (sin texto adicional ni bloques de código).\n'
    '7. Responde en español.'
)

DESCRIPCION_ESQUEMA = 'Datos estructurados y validados de un documento comercial ecuatoriano'
NOMBRE_HERRAMIENTA = 'registrar_documento'


class ErrorBedrock(ErrorAWS):
    """Error de Bedrock traducido (hereda de ErrorAWS para que los scripts lo capturen igual)."""


# ----------------------------------------------------------------- modelos

def resolver_modelo(modelo: str | None) -> tuple[str, str]:
    """('haiku', 'us.anthropic...') a partir de una clave de MODELOS o de un modelId completo."""
    modelo = modelo or MODELO_DEFAULT
    if modelo in MODELOS:
        return modelo, MODELOS[modelo]
    for clave, mid in MODELOS.items():
        if mid == modelo:
            return clave, mid
    clave = re.sub(r'[^a-z0-9]+', '-', modelo.lower()).strip('-')
    return clave, modelo


def estrategia_para(model_id: str) -> str:
    """'json_schema' (Anthropic), 'tool_use' (Nova) o 'prompt' (otros)."""
    mid = model_id.lower()
    if mid.startswith(('us.anthropic', 'global.anthropic', 'anthropic.', 'eu.anthropic', 'apac.anthropic')):
        return 'json_schema'
    if 'amazon.nova' in mid:
        return 'tool_use'
    return 'prompt'


# ----------------------------------------------------------------- request

def _campos_como_texto(campos: dict) -> str:
    lineas = []
    for k, v in (campos or {}).items():
        c = como_campo(v) if not isinstance(v, Campo) else v
        if c.vacio():
            continue
        lineas.append(f'- {k}: {c.valor} (confianza {c.confianza:.1f}, origen {c.origen})')
    return '\n'.join(lineas) if lineas else '- (ninguno)'


def mensaje_usuario(texto: str, campos: dict, alertas: list[str], estrategia: str) -> str:
    """Contenido del turno de usuario (texto OCR + campos + alertas)."""
    partes = [
        'Texto extraído por Amazon Textract (una línea por renglón):',
        '<<<', texto.strip() or '(vacío)', '>>>',
        '',
        'Campos ya extraídos (valor, confianza 0-100, origen):',
        _campos_como_texto(campos),
        '',
        'Alertas de los validadores deterministas:',
        '\n'.join(f'- {a}' for a in (alertas or [])) or '- (ninguna)',
    ]
    if estrategia == 'prompt':
        partes += ['', 'Responde SOLO con un objeto JSON que cumpla exactamente este esquema, sin texto extra:',
                   json.dumps(SCHEMA_DOCUMENTO, ensure_ascii=False)]
    return '\n'.join(partes)


def construir_request(texto: str, campos: dict, alertas: list[str], modelo: str = MODELO_DEFAULT) -> dict:
    """Los kwargs exactos de bedrock-runtime.converse(...) para el modelo dado (sin llamar a AWS)."""
    _, model_id = resolver_modelo(modelo)
    estrategia = estrategia_para(model_id)
    req: dict = {
        'modelId': model_id,
        'system': [{'text': SYSTEM_PROMPT_ES}],
        'messages': [{'role': 'user', 'content': [{'text': mensaje_usuario(texto, campos, alertas, estrategia)}]}],
        'inferenceConfig': {'temperature': TEMPERATURA, 'maxTokens': MAX_TOKENS},
    }
    if estrategia == 'json_schema':
        req['outputConfig'] = {'textFormat': {'type': 'json_schema', 'structure': {'jsonSchema': {
            'name': 'documento', 'description': DESCRIPCION_ESQUEMA,
            'schema': json.dumps(SCHEMA_DOCUMENTO)}}}}
    elif estrategia == 'tool_use':
        req['toolConfig'] = {
            'tools': [{'toolSpec': {'name': NOMBRE_HERRAMIENTA, 'description': DESCRIPCION_ESQUEMA,
                                    'inputSchema': {'json': SCHEMA_DOCUMENTO}}}],
            'toolChoice': {'tool': {'name': NOMBRE_HERRAMIENTA}},
        }
    return req


# ---------------------------------------------------------------- response

_FENCE_RE = re.compile(r'^```[a-zA-Z]*\s*|\s*```$', re.MULTILINE)


def limpiar_fences(texto: str) -> str:
    """Quita ```json ... ``` y texto antes/después del primer { ... último }."""
    t = _FENCE_RE.sub('', texto or '').strip()
    ini, fin = t.find('{'), t.rfind('}')
    return t[ini:fin + 1] if ini != -1 and fin != -1 else t


def extraer_json(response: dict, estrategia: str) -> dict:
    """Saca el dict JSON de la respuesta de converse según la estrategia."""
    contenido = (((response or {}).get('output') or {}).get('message') or {}).get('content') or []
    if estrategia == 'tool_use':
        for bloque in contenido:
            if 'toolUse' in bloque:
                entrada = bloque['toolUse'].get('input')
                if isinstance(entrada, dict):
                    return entrada
                if isinstance(entrada, str):
                    return json.loads(limpiar_fences(entrada))
        # Algunos modelos devuelven texto aunque se fuerce la herramienta.
    textos = [b['text'] for b in contenido if 'text' in b]
    if not textos:
        raise ErrorBedrock('el modelo no devolvió contenido JSON (stopReason=%s)' % response.get('stopReason'))
    try:
        return json.loads(limpiar_fences('\n'.join(textos)))
    except json.JSONDecodeError as e:
        raise ErrorBedrock(f'el modelo no devolvió JSON válido: {e}. Texto: {textos[0][:200]!r}') from e


def traducir_error(e: BaseException) -> str:
    """Traduce los errores típicos de acceso a Bedrock a una línea en español."""
    nombre = type(e).__name__
    codigo, mensaje = '', str(e)
    try:
        codigo = e.response.get('Error', {}).get('Code', '')
        mensaje = e.response.get('Error', {}).get('Message', mensaje)
    except AttributeError:
        pass
    m = mensaje.lower()
    if 'ftuformnotfilled' in m or 'use case' in m or 'use-case' in m:
        return ('falta el formulario de caso de uso de Anthropic en la consola de Bedrock '
                '(us-east-1 → Model catalog → Claude Haiku 4.5 → Submit use case details)')
    if 'mpagreementbeingcreated' in m or 'marketplace' in m:
        return 'suscripción de Marketplace en curso (puede tardar hasta 15 min): reintenta o usa --modelo nova'
    if codigo == 'AccessDeniedException' or nombre == 'AccessDeniedException':
        return 'IAM no permite bedrock:InvokeModel sobre este modelo/perfil (ver iam/bedrock-workshop-policy.json)'
    if codigo == 'ValidationException' and 'on-demand' in m:
        return 'usa el perfil de inferencia us. o global. (no el ID base anthropic.…): on-demand no soportado'
    if codigo == 'ValidationException' and ('outputconfig' in m or 'structured' in m or 'json_schema' in m):
        return 'este modelo no soporta structured outputs: usa --modelo nova (tool use) o un Claude 4.5+'
    if codigo == 'ValidationException':
        return f'petición inválida para Bedrock: {mensaje[:160]}'
    if codigo == 'ResourceNotFoundException':
        return 'modelo o perfil de inferencia no encontrado en esta región (¿us-east-1?)'
    if codigo in ('ThrottlingException', 'ServiceUnavailableException', 'ModelNotReadyException'):
        return 'Bedrock está limitando o no está listo: reintenta en unos segundos o usa --modelo nova'
    if codigo == 'ModelTimeoutException' or nombre in ('ReadTimeoutError', 'ConnectTimeoutError'):
        return 'el modelo tardó demasiado: reintenta o usa --modelo nova'
    if nombre == 'EndpointConnectionError':
        return 'sin conexión con bedrock-runtime (¿wifi? ¿región?)'
    if nombre == 'NoCredentialsError':
        return 'sin credenciales de AWS: usa --offline'
    return f'{codigo or nombre}: {mensaje[:160]}'


# --------------------------------------------------------------- fixtures

def ruta_fixture_bedrock(documento: str, clave_modelo: str) -> Path:
    return DIR_FIXTURES_BEDROCK / f'{stem(documento)}__{clave_modelo}.json'


def _leer_fixture(documento: str, clave_modelo: str, model_id: str) -> dict:
    if not documento:
        raise FixtureFaltante('en modo offline hace falta indicar el documento para ubicar fixtures/bedrock/<doc>__<modelo>.json')
    ruta = ruta_fixture_bedrock(documento, clave_modelo)
    if not ruta.exists():
        raise FixtureFaltante(f'no existe el fixture {ruta.relative_to(RAIZ)}; '
                              f'grábalo con tools/bedrock_check.py o usa --modelo con otro modelo')
    datos = json.loads(ruta.read_text(encoding='utf-8'))
    response = datos.get('response') or {}
    usage = datos.get('usage') or response.get('usage') or {}
    estrategia = estrategia_para((datos.get('request') or {}).get('modelId') or model_id)
    salida_json = datos.get('json')
    if salida_json is None:
        salida_json = extraer_json(response, estrategia)
    return {
        'json': salida_json,
        'usage': usage,
        'modelo_id': (datos.get('request') or {}).get('modelId') or model_id,
        'estrategia': estrategia,
        'costo_usd_aprox': costo_aprox(usage, clave_modelo),
        'modo': 'offline',
        'sintetico': bool(datos.get('sintetico', False)),
        'request': datos.get('request'),
        'response': response,
        'fixture': str(ruta.relative_to(RAIZ)),
    }


# ----------------------------------------------------------------- cliente

_cliente_bedrock = None
_config_cliente_bedrock: tuple | None = None
READ_TIMEOUT_DEFAULT = 60  # s; en el bonus en vivo, más de esto ya es 'cambia a nova'
INTENTOS_DEFAULT = 3


def cliente_bedrock(read_timeout: int | None = None, intentos: int | None = None):
    """boto3.client('bedrock-runtime') en LAB_REGION (solo se crea en modo online).

    read_timeout: segundos de espera de la respuesta (default LAB_BEDROCK_TIMEOUT o 60). Un ReadTimeoutError
    se reintenta (es HTTPClientError), por eso `intentos` importa: tools/precalentar_esquema.py usa
    read_timeout=300 e intentos=1 para medir UNA sola llamada mientras Bedrock compila el esquema.
    """
    global _cliente_bedrock, _config_cliente_bedrock
    if read_timeout is None:
        try:
            read_timeout = int(os.environ.get('LAB_BEDROCK_TIMEOUT', READ_TIMEOUT_DEFAULT))
        except ValueError:
            read_timeout = READ_TIMEOUT_DEFAULT
    intentos = max(int(intentos or INTENTOS_DEFAULT), 1)
    config = (read_timeout, intentos, os.environ.get('LAB_REGION', REGION_DEFAULT), os.environ.get('AWS_PROFILE'))
    if _cliente_bedrock is None or _config_cliente_bedrock != config:
        import boto3
        from botocore.config import Config

        perfil = os.environ.get('AWS_PROFILE')
        sesion = boto3.Session(profile_name=perfil) if perfil else boto3.Session()
        _cliente_bedrock = sesion.client(
            'bedrock-runtime',
            region_name=os.environ.get('LAB_REGION', REGION_DEFAULT),
            config=Config(read_timeout=read_timeout, connect_timeout=10,
                          retries={'total_max_attempts': intentos, 'mode': 'standard'}),
        )
        _config_cliente_bedrock = config
    return _cliente_bedrock


def estructurar(texto: str, campos: dict, alertas: list[str], *, modelo: str = MODELO_DEFAULT,
                modo: str | None = None, documento: str = '') -> dict:
    """Pide al LLM el JSON normalizado del documento.

    Devuelve {'json': dict, 'usage': {...}, 'modelo_id': str, 'estrategia': str, 'costo_usd_aprox': float,
    'modo': 'online'|'offline', 'request': {...}, 'response': {...}}.
    Offline: lee fixtures/bedrock/<stem>__<clave_modelo>.json (FixtureFaltante si no existe).
    Online: converse(...) y traduce los errores de acceso a español (ErrorBedrock).
    """
    clave_modelo, model_id = resolver_modelo(modelo)
    modo_real = resolver_modo(modo)
    if modo_real == 'offline':
        return _leer_fixture(documento, clave_modelo, model_id)

    req = construir_request(texto, campos, alertas, modelo)
    estrategia = estrategia_para(model_id)
    try:
        response = cliente_bedrock().converse(**req)
    except ImportError as e:
        raise ErrorBedrock(f'boto3 no está instalado ({e}); para continuar sin AWS: --offline', e) from e
    except Exception as e:  # noqa: BLE001 — se traduce abajo
        raise ErrorBedrock(f'{traducir_error(e)}\npara continuar sin AWS: --offline', e) from e

    usage = response.get('usage') or {}
    salida_json = extraer_json(response, estrategia)
    return {
        'json': salida_json,
        'usage': usage,
        'modelo_id': model_id,
        'estrategia': estrategia,
        'costo_usd_aprox': costo_aprox(usage, clave_modelo),
        'modo': 'online',
        'stopReason': response.get('stopReason'),
        'latencia_ms': (response.get('metrics') or {}).get('latencyMs'),
        'request': req,
        'response': {k: v for k, v in response.items() if k != 'ResponseMetadata'},
    }


def costo_aprox(usage: dict, clave_modelo: str) -> float:
    """US$ aproximados de una llamada según usage {'inputTokens', 'outputTokens'} (ver NOTA_PRECIOS)."""
    entrada, salida = PRECIOS_1M.get(clave_modelo, PRECIOS_1M['haiku'])
    tin = float((usage or {}).get('inputTokens', 0) or 0)
    tout = float((usage or {}).get('outputTokens', 0) or 0)
    return round(tin / 1e6 * entrada + tout / 1e6 * salida, 6)


# ------------------------------------------------ re-validación del JSON

def json_a_campos(datos: dict) -> dict[str, Campo]:
    """Convierte el JSON del LLM en Campos canónicos (origen 'LLM') para pasarlos por validar_factura."""
    d = datos or {}
    emisor = d.get('emisor') or {}

    def c(valor) -> Campo:
        if isinstance(valor, float) and valor.is_integer() and False:
            valor = int(valor)
        if isinstance(valor, (int, float)):
            valor = f'{valor:.2f}'
        return Campo('' if valor is None else str(valor), 100.0, 'LLM')

    campos = {
        'RUC_EMISOR': c(emisor.get('ruc', '')),
        'NUM_FACTURA': c(d.get('numero_factura', '')),
        'CLAVE_ACCESO': c(d.get('clave_acceso', '')),
        'FECHA_EMISION': c(d.get('fecha_emision', '')),
        'SUBTOTAL_15': c(d.get('subtotal', '')),
        'IVA_15': c(d.get('iva', '')),
        'PROPINA': c(d.get('propina', '')),
        'VALOR_TOTAL': c(d.get('total', '')),
    }
    return {k: v for k, v in campos.items() if not v.vacio()}


def guardar_fixture(documento: str, clave_modelo: str, resultado: dict) -> Path:
    """Guarda request/response/usage/json de una llamada online como fixture (para tools/)."""
    ruta = ruta_fixture_bedrock(documento, clave_modelo)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    datos = {
        'sintetico': False,
        'request': resultado.get('request'),
        'response': resultado.get('response'),
        'usage': resultado.get('usage'),
        'json': resultado.get('json'),
    }
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    consola.ok(f'fixture Bedrock guardado: {ruta.relative_to(RAIZ)}')
    return ruta
