"""Clasificación trivial por evidencia: factura | formulario | desconocido.

Es deliberadamente simple (palabras clave + bloques presentes). En producción
se reemplaza por reglas más ricas, un clasificador entrenado, un LLM o
Bedrock Data Automation; lo importante es que el pipeline elige el conjunto
de reglas de validación según el tipo.
"""
from __future__ import annotations

import re

from .bloques import lineas, normalizar_clave, por_tipo

TIPOS = ('factura', 'formulario', 'desconocido')
UMBRAL_FACTURA = 2


def _evidencias_factura(textos: list[str]) -> list[str]:
    """Pistas fuertes de factura RIDE: cada una suma 1 (CLAVE DE ACCESO suma 2)."""
    ev: list[str] = []
    todo = '\n'.join(textos)
    if 'clave de acceso' in todo:
        ev.append("'CLAVE DE ACCESO' presente")
        ev.append("'CLAVE DE ACCESO' (evidencia fuerte)")
    if re.search(r'\bruc\b', todo):
        ev.append("'RUC' presente")
    if any(re.match(r'^factura\b', t) for t in textos):
        ev.append("línea que empieza con 'FACTURA'")
    if 'valor total' in todo:
        ev.append("'VALOR TOTAL' presente")
    if 'subtotal' in todo:
        ev.append("'SUBTOTAL' presente")
    if re.search(r'\d{3}-\d{3}-\d{9}', todo):
        ev.append('número de comprobante 001-001-000000000')
    return ev


def clasificar(resp_texto: dict, resp_forms: dict | None = None) -> tuple[str, list[str]]:
    """('factura'|'formulario'|'desconocido', evidencias).

    Reglas: 'CLAVE DE ACCESO' / línea 'FACTURA' / 'RUC' / totales → factura (≥ 2 evidencias);
    SELECTION_ELEMENT presentes o 'Inscripción' / etiquetas 'Nombre:' → formulario; si no → desconocido.
    """
    textos = [normalizar_clave(t) for t, _ in lineas(resp_texto or {})]
    if resp_forms and not textos:
        textos = [normalizar_clave(t) for t, _ in lineas(resp_forms)]

    ev_factura = _evidencias_factura(textos)
    if len(ev_factura) >= UMBRAL_FACTURA:
        return 'factura', ev_factura

    ev_form: list[str] = []
    n_sel = len(por_tipo(resp_forms, 'SELECTION_ELEMENT')) if resp_forms else 0
    if n_sel:
        ev_form.append(f'{n_sel} SELECTION_ELEMENT (checkboxes)')
    todo = '\n'.join(textos)
    if 'inscripcion' in todo:
        ev_form.append("'Inscripción' presente")
    etiquetas = [t for t, _ in lineas(resp_texto or {}) if re.match(r'^[A-Za-zÁÉÍÓÚáéíóúÑñ¿? ]{2,30}:\s*\S', t.strip())
                 or re.fullmatch(r'[A-Za-zÁÉÍÓÚáéíóúÑñ¿? ]{2,30}:', t.strip())]
    if 'nombre' in [normalizar_clave(e.split(':')[0]) for e in etiquetas]:
        ev_form.append("etiqueta 'Nombre:'")
    if len(etiquetas) >= 3:
        ev_form.append(f'{len(etiquetas)} etiquetas tipo "Campo:"')
    if any(re.search(r'\[x\]|\[ \]', t) for t in textos):
        ev_form.append('marcas [X]/[ ] en el texto')
    if ev_form and (n_sel or 'inscripcion' in todo or any('Nombre' in e for e in ev_form)):
        return 'formulario', ev_form

    evidencias = ev_factura + ev_form
    evidencias.append('sin patrones de factura ni de formulario')
    return 'desconocido', evidencias
