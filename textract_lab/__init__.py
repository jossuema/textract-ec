"""textract_lab — paquete del taller "Construye un sistema inteligente de OCR con Amazon Textract y Python".

Módulos:
- cliente     : llamar() decide ONLINE (Textract + cache/) u OFFLINE (fixtures/). Única dependencia: boto3.
- bloques     : navegación del grafo de Blocks (LINE/WORD, FORMS, TABLES, QUERIES, checkboxes).
- modelo      : dataclasses Campo{valor, confianza, origen}, Tabla, Resultado.
- queries     : set fijo de queries en inglés/ASCII y su validación.
- validadores : módulo 10/11 (cédula, RUC, clave de acceso), montos, fechas, reglas de factura y formulario.
- clasificar  : factura | formulario | desconocido por evidencia.
- etapas      : pipeline ETAPAS = [texto, estructura, consultas, clasificar_etapa, validar, salida].
- overlay     : cajas por confianza con Pillow (opcional).
- costos      : tarifas aproximadas y acumulador de la sesión.
- bedrock     : capa opcional con Converse (Claude Haiku 4.5 / Nova Lite); offline con fixtures.
- consola     : colores ANSI (NO_COLOR), tabla() y semaforo().

Todo el código de parseo ignora de qué modo vino el JSON: la respuesta cruda de boto3
y un fixture tienen la misma forma.
"""
from __future__ import annotations

from . import bedrock, bloques, clasificar, cliente, consola, costos, etapas, modelo, overlay, queries, validadores
from .cliente import (RAIZ, REGION_DEFAULT, ErrorAWS, FixtureFaltante, banner_modo, clave_llamada,
                      info_credenciales, llamar, resolver_modo, stem)
from .etapas import ETAPAS, procesar_documento
from .modelo import Campo, Resultado, Tabla

__version__ = '1.0.0'
__all__ = [
    'bedrock', 'bloques', 'clasificar', 'cliente', 'consola', 'costos', 'etapas', 'modelo', 'overlay',
    'queries', 'validadores',
    'RAIZ', 'REGION_DEFAULT', 'ErrorAWS', 'FixtureFaltante', 'banner_modo', 'clave_llamada',
    'info_credenciales', 'llamar', 'resolver_modo', 'stem',
    'ETAPAS', 'procesar_documento', 'Campo', 'Resultado', 'Tabla', '__version__',
]
