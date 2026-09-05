"""Colores ANSI, tablas de texto y semáforo de confianza, sin dependencias.

Respeta la convención NO_COLOR (https://no-color.org): si la variable existe,
no se emiten códigos ANSI. También se desactivan si la salida no es una
terminal (por ejemplo, al redirigir a un archivo), salvo FORCE_COLOR=1.
"""
from __future__ import annotations

import os
import re
import sys

COLORES = {
    'rojo': '31', 'verde': '32', 'amarillo': '33', 'azul': '34',
    'magenta': '35', 'cian': '36', 'gris': '90', 'blanco': '97',
    'negrita': '1', 'tenue': '2',
}
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

UMBRAL_ALTO = 90.0   # >= 90: verde (decisiones financieras, buenas prácticas de AWS)
UMBRAL_MEDIO = 70.0  # 70-90: amarillo; < 70: rojo


def colores_activos() -> bool:
    """True si se deben emitir códigos ANSI."""
    if os.environ.get('NO_COLOR') is not None:
        return False
    if os.environ.get('FORCE_COLOR'):
        return True
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def color(txt: str, nombre: str) -> str:
    """Envuelve `txt` con el color ANSI `nombre` ('rojo', 'verde', 'amarillo', ...)."""
    codigo = COLORES.get(nombre)
    if not codigo or not colores_activos():
        return str(txt)
    return f'\x1b[{codigo}m{txt}\x1b[0m'


def sin_ansi(txt: str) -> str:
    """Quita los códigos ANSI (para medir anchos o guardar en archivos)."""
    return _ANSI_RE.sub('', str(txt))


def _emitir(txt: str) -> str:
    print(txt, flush=True)
    return txt


def ok(txt: str) -> str:
    """Imprime en verde con el prefijo ✔ y devuelve la línea formateada."""
    return _emitir(color(f'✔ {txt}', 'verde'))


def aviso(txt: str) -> str:
    """Imprime en amarillo con el prefijo ! y devuelve la línea formateada."""
    return _emitir(color(f'! {txt}', 'amarillo'))


def error(txt: str) -> str:
    """Imprime en rojo con el prefijo ✘ y devuelve la línea formateada."""
    return _emitir(color(f'✘ {txt}', 'rojo'))


def titulo(txt: str) -> str:
    """Imprime un título en negrita con subrayado y lo devuelve."""
    linea = '─' * min(len(sin_ansi(txt)), 120)
    return _emitir(color(f'\n{txt}\n{linea}', 'negrita'))


def nombre_color_confianza(conf: float) -> str:
    """'verde' >= 90, 'amarillo' 70-90, 'rojo' < 70."""
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return 'rojo'
    if c >= UMBRAL_ALTO:
        return 'verde'
    if c >= UMBRAL_MEDIO:
        return 'amarillo'
    return 'rojo'


def semaforo(conf: float) -> str:
    """Devuelve '●' coloreado según la confianza (verde/amarillo/rojo)."""
    return color('●', nombre_color_confianza(conf))


def confianza_coloreada(conf: float, decimales: int = 1) -> str:
    """'98.7' coloreado por umbral, con semáforo delante."""
    try:
        txt = f'{float(conf):.{decimales}f}'
    except (TypeError, ValueError):
        txt = str(conf)
    return f'{semaforo(conf)} {color(txt, nombre_color_confianza(conf))}'


def _ancho(txt: str) -> int:
    return len(sin_ansi(txt))


def _recortar(txt: str, ancho: int) -> str:
    visible = sin_ansi(txt)
    if len(visible) <= ancho:
        return txt
    # Si hay ANSI, recortamos sobre el texto visible para no romper códigos.
    return visible[: max(ancho - 1, 0)] + '…'


def tabla(filas: list[list[str]], cabecera: list[str] | None = None,
          max_ancho_col: int = 48) -> str:
    """Tabla de texto de ancho fijo (sin dependencias). Devuelve el string.

    Las celdas pueden traer códigos ANSI; el ancho se mide sobre el texto visible.
    """
    filas_txt = [[str(c) for c in f] for f in filas]
    cab = [str(c) for c in cabecera] if cabecera else []
    n_cols = max([len(cab)] + [len(f) for f in filas_txt]) if (cab or filas_txt) else 0
    if n_cols == 0:
        return '(sin filas)'
    cab = cab + [''] * (n_cols - len(cab)) if cab else []
    filas_txt = [f + [''] * (n_cols - len(f)) for f in filas_txt]
    todas = ([cab] if cab else []) + filas_txt
    anchos = [min(max(_ancho(f[i]) for f in todas), max_ancho_col) for i in range(n_cols)]

    def linea(f: list[str]) -> str:
        celdas = []
        for i, c in enumerate(f):
            c = _recortar(c, anchos[i])
            celdas.append(c + ' ' * (anchos[i] - _ancho(c)))
        return '│ ' + ' │ '.join(celdas) + ' │'

    borde = '┼'.join('─' * (a + 2) for a in anchos)
    arriba = '┌' + borde.replace('┼', '┬') + '┐'
    abajo = '└' + borde.replace('┼', '┴') + '┘'
    salida = [arriba]
    if cab:
        salida.append(linea([color(c, 'negrita') for c in cab]))
        salida.append('├' + borde + '┤')
    salida.extend(linea(f) for f in filas_txt)
    salida.append(abajo)
    return '\n'.join(salida)


def clave_valor(pares: dict, ancho_clave: int | None = None) -> str:
    """Lista 'clave : valor' alineada (para dicts pequeños)."""
    if not pares:
        return '(vacío)'
    ancho = ancho_clave or min(max(_ancho(str(k)) for k in pares), 40)
    return '\n'.join(f'{str(k):<{ancho}} : {v}' for k, v in pares.items())
