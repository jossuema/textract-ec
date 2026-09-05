"""Tarifas aproximadas de Textract y acumulador de costo por sesión.

Tarifas por página (US$), primer millón de páginas/mes, región Oregón como
aproximación de us-east-1 (https://aws.amazon.com/textract/pricing/). Son
APROXIMADAS: confirmar en la calculadora oficial antes de facturar a alguien.
Las features de AnalyzeDocument se SUMAN cuando van juntas en una llamada.
LAYOUT es gratis si va acompañado de TABLES, FORMS o QUERIES.
"""
from __future__ import annotations

import json
from pathlib import Path

TARIFAS: dict[str, float] = {
    'detect_document_text': 0.0015,
    'FORMS': 0.05,
    'TABLES': 0.015,
    'QUERIES': 0.015,
    'SIGNATURES': 0.0035,
    'LAYOUT': 0.004,  # gratis si va con TABLES/FORMS/QUERIES
    'analyze_expense': 0.01,
    'analyze_id': 0.025,
}
NOTA_TARIFAS = 'tarifa Oregón, primer millón de páginas/mes, aproximada'
_FEATURES_QUE_REGALAN_LAYOUT = {'TABLES', 'FORMS', 'QUERIES'}


def _raiz() -> Path:
    return Path(__file__).resolve().parent.parent


def ruta_acumulado() -> Path:
    return _raiz() / 'cache' / '.costos.json'


def costo(operacion: str, feature_types: list[str] | None = None, paginas: int = 1) -> float:
    """Costo aproximado en US$ de una llamada síncrona de `paginas` páginas."""
    paginas = max(int(paginas or 1), 1)
    if operacion in ('detect_document_text', 'analyze_expense', 'analyze_id'):
        return round(TARIFAS[operacion] * paginas, 6)
    if operacion == 'analyze_document':
        features = {f.upper() for f in (feature_types or [])}
        total = 0.0
        for f in features:
            if f == 'LAYOUT' and features & _FEATURES_QUE_REGALAN_LAYOUT:
                continue  # LAYOUT sin costo adicional
            total += TARIFAS.get(f, 0.0)
        return round(total * paginas, 6)
    raise ValueError(f'operación desconocida para costos: {operacion!r}')


def acumulado() -> dict:
    """Lee el acumulado de la sesión: {'llamadas': n, 'paginas': n, 'usd': x}."""
    ruta = ruta_acumulado()
    try:
        if ruta.exists():
            datos = json.loads(ruta.read_text(encoding='utf-8'))
            return {
                'llamadas': int(datos.get('llamadas', 0)),
                'paginas': int(datos.get('paginas', 0)),
                'usd': float(datos.get('usd', 0.0)),
                'nota': NOTA_TARIFAS,
            }
    except (OSError, ValueError):
        pass
    return {'llamadas': 0, 'paginas': 0, 'usd': 0.0, 'nota': NOTA_TARIFAS}


def registrar(operacion: str, feature_types: list[str] | None = None, paginas: int = 1) -> None:
    """Suma una llamada real (no cache) al acumulado en cache/.costos.json."""
    datos = acumulado()
    datos['llamadas'] += 1
    datos['paginas'] += max(int(paginas or 1), 1)
    datos['usd'] = round(datos['usd'] + costo(operacion, feature_types, paginas), 6)
    ruta = ruta_acumulado()
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError:
        pass  # el costo es informativo; nunca debe romper un lab


def reiniciar() -> None:
    """Borra el acumulado (útil antes de una demo)."""
    try:
        ruta_acumulado().unlink(missing_ok=True)
    except OSError:
        pass


def formatear(usd: float) -> str:
    """'$0.0150 (aprox.)'"""
    return f'${usd:.4f} (aprox.)'
