#!/usr/bin/env python3
"""Genera los documentos de ejemplo del taller (docs/) y su ground truth.

Dibuja con Pillow cada documento ficticio (factura RIDE limpia, factura con
trampas, formulario de inscripción, orden de compra en prosa, mini.png,
recibo de restaurante) y, mientras dibuja, registra la geometría de cada
texto en docs/ground_truth/<doc>.layout.json para que
tools/gen_fixtures_sinteticos.py pueda fabricar respuestas con la forma de
Amazon Textract sin llamar a AWS.

Uso:
    python3 tools/gen_docs.py            # genera todo
    python3 tools/gen_docs.py --dpi 220  # reduce la resolución si los PNG pesan demasiado

No requiere credenciales ni red. Única dependencia: Pillow.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont
except ImportError:  # pragma: no cover
    print('ERROR: este generador necesita Pillow (pip install pillow en tu entorno virtual).')
    sys.exit(1)

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / 'docs'
GROUND_TRUTH = DOCS / 'ground_truth'
EXTRA = DOCS / 'extra'

A4_300 = (2480, 3508)
DPI_BASE = 300

# Fuentes candidatas (regular, negrita). Se usa el primer par que cargue.
CANDIDATOS_FUENTES: list[tuple[str, str]] = [
    ('/Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages/reportlab/fonts/Vera.ttf',
     '/Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages/reportlab/fonts/VeraBd.ttf'),
    ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf'),
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('/System/Library/Fonts/Supplemental/Arial.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
]

_FUENTES: tuple[str, str] | None = None
_CACHE_FUENTES: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def cargar_fuentes() -> tuple[str, str]:
    """Devuelve las rutas (regular, negrita) de la primera fuente TTF que carga."""
    global _FUENTES
    if _FUENTES:
        return _FUENTES
    errores = []
    for regular, negrita in CANDIDATOS_FUENTES:
        try:
            f = ImageFont.truetype(regular, 20)
            ImageFont.truetype(negrita, 20)
            # La fuente debe tener tildes y ñ (Latin-1); si no, el ancho de 'ñ' saldría 0.
            if f.getlength('ñáéíóú¿') <= 0:
                raise OSError('la fuente no tiene glifos latinos')
            _FUENTES = (regular, negrita)
            return _FUENTES
        except OSError as exc:
            errores.append(f'  - {regular}: {exc}')
    print('ERROR: no se pudo cargar ninguna fuente TrueType. Intentos:')
    print('\n'.join(errores))
    print('Instala DejaVu Sans o Bitstream Vera, o edita CANDIDATOS_FUENTES en tools/gen_docs.py.')
    sys.exit(1)


def fuente(tam: int, negrita: bool = False) -> ImageFont.FreeTypeFont:
    """Fuente TTF cacheada por tamaño en píxeles."""
    clave = (tam, negrita)
    if clave not in _CACHE_FUENTES:
        regular, bold = cargar_fuentes()
        _CACHE_FUENTES[clave] = ImageFont.truetype(bold if negrita else regular, tam)
    return _CACHE_FUENTES[clave]


# ---------------------------------------------------------------------------
# Algoritmos de validación (copia exacta de §6 del contrato; sirven para
# generar y verificar los identificadores ficticios).
# ---------------------------------------------------------------------------

def dv_cedula(c: str) -> bool:
    """Módulo 10 de la cédula ecuatoriana."""
    if len(c) != 10 or not c.isdigit():
        return False
    provincia = int(c[:2])
    if not (1 <= provincia <= 24 or provincia == 30) or int(c[2]) >= 6:
        return False
    suma = 0
    for d, k in zip(c[:9], [2, 1, 2, 1, 2, 1, 2, 1, 2]):
        p = int(d) * k
        suma += p - 9 if p > 9 else p
    return (10 - suma % 10) % 10 == int(c[9])


def calcular_dv_ruc_privada(base9: str) -> int | None:
    """Dígito verificador módulo 11 de una sociedad privada (tercer dígito 9). None si sale 10."""
    suma = sum(int(d) * k for d, k in zip(base9, [4, 3, 2, 7, 6, 5, 4, 3, 2]))
    residuo = suma % 11
    dv = 0 if residuo == 0 else 11 - residuo
    return None if dv == 10 else dv


def dv_ruc(r: str) -> bool:
    """Valida un RUC de 13 dígitos (natural / privada / pública)."""
    if len(r) != 13 or not r.isdigit():
        return False
    tercero = int(r[2])
    if tercero < 6:
        return dv_cedula(r[:10]) and r[10:] == '001'
    if tercero == 9:
        dv = calcular_dv_ruc_privada(r[:9])
        return dv is not None and dv == int(r[9]) and r[10:] == '001'
    if tercero == 6:
        suma = sum(int(d) * k for d, k in zip(r[:8], [3, 2, 7, 6, 5, 4, 3, 2]))
        residuo = suma % 11
        dv = 0 if residuo == 0 else 11 - residuo
        return dv != 10 and dv == int(r[8]) and r[9:] == '0001'
    return False


def calcular_dv_clave_acceso(k48: str) -> int:
    """Módulo 11 con pesos 2..7 de derecha a izquierda sobre los 48 primeros dígitos."""
    pesos = [2, 3, 4, 5, 6, 7]
    suma = sum(int(d) * pesos[i % 6] for i, d in enumerate(reversed(k48)))
    dv = 11 - suma % 11
    return {11: 0, 10: 1}.get(dv, dv)


def dv_clave_acceso(k: str) -> bool:
    """Valida la clave de acceso de 49 dígitos del SRI."""
    return len(k) == 49 and k.isdigit() and calcular_dv_clave_acceso(k[:48]) == int(k[48])


def generar_ruc_privada(prefijo9: str) -> str:
    """Completa un RUC de sociedad privada a partir de sus 9 primeros dígitos."""
    dv = calcular_dv_ruc_privada(prefijo9)
    if dv is None:
        raise ValueError(f'el prefijo {prefijo9} produce dv 10 (inválido); usa otro prefijo')
    return f'{prefijo9}{dv}001'


# ---------------------------------------------------------------------------
# Datos ficticios fijos (§3 del contrato)
# ---------------------------------------------------------------------------

EMISOR = {
    'razon_social': 'TECNOLOGÍA ANDINA EJEMPLO S.A.',
    'ruc': '1790456129001',
    'direccion_matriz': 'Av. Amazonas N33-123 y Rumipamba, Quito',
    'direccion_sucursal': 'Av. Amazonas N33-123 y Rumipamba, Quito',
    'obligado_contabilidad': 'SÍ',
    'regimen': 'Contribuyente Régimen General',
}
COMPRADOR = {
    'nombre': 'Comunidad AWS Ecuador Ejemplo',
    'identificacion': '0103456786',
    'direccion': 'Calle Larga 4-56, Cuenca',
    'correo': 'hola@ejemplo.ec',
}
FACTURA = {
    'numero': '001-001-000001234',
    'fecha_emision': '01/09/2026',
    'fecha_emision_iso': '2026-09-01',
    'clave_acceso': '0109202601179045612900120010010000012341234567813',
    'fecha_autorizacion': '01/09/2026 09:15:00',
    'ambiente': 'PRODUCCIÓN',
    'emision': 'NORMAL',
}
CLAVE_ACCESO_TRAMPA = '0109202601179045612900120010010000012341234567814'
ITEMS = [
    {'cantidad': '2', 'descripcion': 'Monitor 27" 4K Ejemplo', 'precio_unitario': '350.00', 'descuento': '0.00', 'precio_total': '700.00'},
    {'cantidad': '1', 'descripcion': 'Teclado mecánico ES', 'precio_unitario': '85.60', 'descuento': '0.00', 'precio_total': '85.60'},
    {'cantidad': '3', 'descripcion': 'Cable HDMI 2.1 2m', 'precio_unitario': '12.00', 'descuento': '0.00', 'precio_total': '36.00'},
]
TOTALES = [
    ('SUBTOTAL 15%', '821.60'),
    ('SUBTOTAL 0%', '0.00'),
    ('SUBTOTAL NO OBJETO DE IVA', '0.00'),
    ('SUBTOTAL EXENTO DE IVA', '0.00'),
    ('SUBTOTAL SIN IMPUESTOS', '821.60'),
    ('TOTAL DESCUENTO', '0.00'),
    ('ICE', '0.00'),
    ('IVA 15%', '123.24'),
    ('PROPINA', '0.00'),
    ('VALOR TOTAL', '944.84'),
]
FORMA_PAGO = ('TARJETA DE CRÉDITO', '944.84')

FORMULARIO_CAMPOS = [
    ('Nombre:', 'Ana Lucía'),
    ('Apellido:', 'Sarmiento Vera'),
    ('Cédula:', '0103456786'),
    ('Correo:', 'ana.sarmiento@ejemplo.ec'),
    ('Ciudad:', 'Cuenca'),
    ('Empresa:', 'Andina Datos Ejemplo'),
    ('Teléfono:', '099 123 4567'),
]
FORMULARIO_GRUPOS = [
    ('Track (marcar con X):', [('Workshop OCR con Textract', True), ('Serverless', False), ('Datos y analítica', False)]),
    ('¿Tienes cuenta AWS?:', [('Sí', True), ('No', False)]),
    ('Nivel:', [('Principiante', False), ('Intermedio', True), ('Avanzado', False)]),
]

ORDEN_COMPRA_PARRAFOS = [
    'Cuenca, 28 de agosto de 2026.',
    '',
    'Estimados señores de Tecnología Andina Ejemplo S.A.:',
    '',
    'Por medio de la presente confirmamos la compra de tres monitores de 27 pulgadas a un precio de '
    '350 dólares cada uno, más dos teclados mecánicos a 85.60 dólares por unidad. Solicitamos la '
    'entrega en nuestras oficinas de la Calle Larga 4-56 antes del 10 de septiembre. El pago se '
    'realizará por transferencia bancaria a la recepción de la factura.',
    '',
    'Atentamente,',
    '',
    '',
    'María José Cabrera',
    'Gerente de Compras',
    'Andina Datos Ejemplo',
]

MINI_LINEAS = [
    'Cuenca, 5 de septiembre de 2026',
    'AWS Community Day Ecuador',
    '¿Funciona el español? Sí: ñ, á, é, í, ó, ú',
    'Textract lee esto en 1 llamada',
]

RECIBO = {
    'nombre': 'EL CANGREJO SABROSO EJEMPLO',
    'ruc': generar_ruc_privada('099012345'),
    'direccion': 'Av. Francisco de Orellana 123, Guayaquil',
    'numero': '002-001-000004567',
    'fecha': '02/09/2026 20:35',
    'items': [
        ('2', 'Encebollado de pescado', '4.50', '9.00'),
        ('1', 'Cangrejada criolla', '18.00', '18.00'),
        ('2', 'Jugo de naranja', '2.50', '5.00'),
    ],
    'subtotal': '32.00',
    'servicio': '3.20',
    'iva': '4.80',
    'total': '40.00',
}

PIE_FICTICIO = 'DOCUMENTO FICTICIO · SOLO PARA DEMOSTRACIÓN · AWS Community Day Ecuador 2026'


def verificar_datos() -> None:
    """Comprueba con los algoritmos de §6 que los datos ficticios son válidos."""
    assert dv_ruc(EMISOR['ruc']), 'RUC del emisor inválido'
    assert dv_cedula(COMPRADOR['identificacion']), 'cédula del comprador inválida'
    assert dv_ruc('0103456786001'), 'RUC natural de ejemplo inválido'
    assert dv_clave_acceso(FACTURA['clave_acceso']), 'clave de acceso limpia inválida'
    assert not dv_clave_acceso(CLAVE_ACCESO_TRAMPA), 'la clave trampa debería ser inválida'
    assert dv_ruc(RECIBO['ruc']), 'RUC del recibo inválido'
    assert RECIBO['ruc'][:2] == '09' and RECIBO['ruc'][2] == '9', 'el RUC del recibo debe ser sociedad privada de Guayas'
    # Cuadre aritmético de la factura limpia.
    suma_items = sum(float(i['precio_total']) for i in ITEMS)
    assert abs(suma_items - 821.60) < 0.005, suma_items
    assert abs(821.60 * 0.15 - 123.24) < 0.005
    assert abs(821.60 + 123.24 - 944.84) < 0.005
    # Cuadre del recibo: consumo + servicio 10 % + IVA 15 % (el servicio no lleva IVA).
    consumo = sum(float(i[3]) for i in RECIBO['items'])
    assert abs(consumo - 32.00) < 0.005 and abs(consumo * 0.10 - 3.20) < 0.005
    assert abs(consumo * 0.15 - 4.80) < 0.005 and abs(consumo + 3.20 + 4.80 - 40.00) < 0.005


# ---------------------------------------------------------------------------
# Lienzo: dibuja y registra la geometría de cada texto
# ---------------------------------------------------------------------------

class Lienzo:
    """Imagen + registro de elementos (texto, bbox en píxeles, rol semántico).

    Roles registrados en el layout:
      - 'titulo'   : línea que actúa como título (LAYOUT_TITLE)
      - 'linea'    : línea de texto suelta
      - 'clave'    : parte clave de un par clave-valor (comparte 'par' con su valor)
      - 'valor'    : parte valor de un par (puede tener texto vacío, p. ej. 'Firma: ____')
      - 'celda'    : celda de tabla ('tabla', 'fila', 'col', 'cabecera', 'celda_bbox')
      - 'checkbox' : casilla dibujada ('estado', 'etiqueta' = id del elemento clave)
    Los elementos que comparten 'linea' se funden en un solo bloque LINE.
    Cada palabra lleva su bbox calculado con font.getlength (avance horizontal)
    y font.getbbox (alto de los glifos).
    """

    def __init__(self, nombre: str, ancho: int, alto: int, dpi: int, fondo=(255, 255, 255)):
        self.nombre = nombre
        self.ancho, self.alto, self.dpi = ancho, alto, dpi
        self.img = Image.new('RGB', (ancho, alto), fondo)
        self.d = ImageDraw.Draw(self.img)
        self.elementos: list[dict] = []
        self._contador = 0

    # -- utilidades ---------------------------------------------------------
    def _id(self, prefijo: str = 'e') -> str:
        self._contador += 1
        return f'{prefijo}{self._contador}'

    def escala(self, v: float) -> int:
        """Convierte una medida pensada a 300 DPI a los DPI del lienzo."""
        return int(round(v * self.dpi / DPI_BASE))

    def ancho_texto(self, txt: str, tam: int, negrita: bool = False) -> float:
        return fuente(self.escala(tam), negrita).getlength(txt)

    # -- texto --------------------------------------------------------------
    def texto(self, x: float, y: float, txt: str, tam: int = 36, negrita: bool = False, rol: str = 'linea',
              linea: str | None = None, par: str | None = None, color=(0, 0, 0), alinear: str = 'izq',
              **extra) -> dict:
        """Dibuja txt con la esquina superior izquierda en (x, y) y registra el elemento."""
        f = fuente(self.escala(tam), negrita)
        if alinear == 'der':
            x = x - f.getlength(txt)
        elif alinear == 'centro':
            x = x - f.getlength(txt) / 2
        self.d.text((x, y), txt, font=f, fill=color)
        bb = f.getbbox(txt)
        bbox = [round(x + bb[0]), round(y + bb[1]), round(x + bb[2]), round(y + bb[3])]
        palabras = []
        pos = 0
        for w in txt.split(' '):
            if w:
                prefijo = txt[:pos]
                x0 = x + f.getlength(prefijo)
                x1 = x + f.getlength(prefijo + w)
                wb = f.getbbox(w)
                palabras.append({'texto': w, 'bbox': [round(x0 + wb[0]), round(y + wb[1]), round(x0 + wb[2] if wb[2] > 0 else x1), round(y + wb[3])]})
            pos += len(w) + 1
        eid = self._id()
        elemento = {
            'id': eid, 'rol': rol, 'texto': ' '.join(txt.split()), 'bbox': bbox,
            'palabras': palabras, 'linea': linea or eid,
        }
        if par:
            elemento['par'] = par
        elemento.update(extra)
        self.elementos.append(elemento)
        return elemento

    def par(self, x: float, y: float, clave: str, valor: str, tam: int = 36, negrita_clave: bool = False,
            separacion: str = '  ', misma_linea: bool = True, dy_valor: float = 0, tam_valor: int | None = None,
            negrita_valor: bool = False) -> tuple[dict, dict]:
        """Dibuja 'clave  valor' y registra ambos como par KEY/VALUE."""
        pid = self._id('P')
        lid = self._id('L') if misma_linea else None
        ek = self.texto(x, y, clave, tam, negrita_clave, rol='clave', linea=lid, par=pid)
        f = fuente(self.escala(tam), negrita_clave)
        if misma_linea:
            xv = x + f.getlength(clave + separacion)
            yv = y
        else:
            xv = x
            yv = y + dy_valor
        ev = self.texto(xv, yv, valor, tam_valor or tam, negrita_valor, rol='valor', linea=lid, par=pid)
        return ek, ev

    def valor_vacio(self, clave_elem: dict, bbox: list[int]) -> dict:
        """Registra un VALUE sin texto (p. ej. la raya de una firma)."""
        elemento = {'id': self._id(), 'rol': 'valor', 'texto': '', 'bbox': bbox, 'palabras': [],
                    'linea': None, 'par': clave_elem['par']}
        self.elementos.append(elemento)
        return elemento

    def checkbox(self, x: float, y: float, lado: float, marcado: bool, etiqueta: str, tam: int = 36,
                 grupo: str = '') -> tuple[dict, dict]:
        """Dibuja un cuadrado (con X si está marcado) y su etiqueta a la derecha."""
        grosor = max(2, self.escala(4))
        self.d.rectangle([x, y, x + lado, y + lado], outline=(0, 0, 0), width=grosor)
        if marcado:
            m = lado * 0.18
            self.d.line([x + m, y + m, x + lado - m, y + lado - m], fill=(0, 0, 0), width=grosor + 2)
            self.d.line([x + lado - m, y + m, x + m, y + lado - m], fill=(0, 0, 0), width=grosor + 2)
        pid = self._id('P')
        f = fuente(self.escala(tam))
        alto_texto = f.getbbox('Xg')[3]
        ye = y + (lado - alto_texto) / 2
        el = self.texto(x + lado + self.escala(24), ye, etiqueta, tam, rol='clave', par=pid, grupo=grupo)
        ec = {'id': self._id(), 'rol': 'checkbox', 'texto': '', 'bbox': [round(x), round(y), round(x + lado), round(y + lado)],
              'palabras': [], 'linea': None, 'estado': 'SELECTED' if marcado else 'NOT_SELECTED', 'par': pid,
              'etiqueta': el['id'], 'grupo': grupo}
        self.elementos.append(ec)
        return ec, el

    def tabla(self, x: float, y: float, columnas: list[tuple[str, float, str]], filas: list[list[str]],
              tam: int = 32, alto_fila: float = 70, fondo_cabecera=(228, 228, 228), tabla_id: str | None = None,
              titulo: str = '') -> float:
        """Dibuja una tabla con bordes. columnas = [(título, ancho, 'izq'|'der'|'centro')]. Devuelve el y final."""
        tid = tabla_id or self._id('T')
        grosor = max(1, self.escala(2))
        pad = self.escala(14)
        f = fuente(self.escala(tam))
        alto_texto = f.getbbox('Xg')[3]
        todas = [[c[0] for c in columnas]] + filas
        yy = y
        for i, fila in enumerate(todas):
            xx = x
            if i == 0:
                self.d.rectangle([x, yy, x + sum(c[1] for c in columnas), yy + alto_fila], fill=fondo_cabecera)
            for j, (col, celda) in enumerate(zip(columnas, fila)):
                ancho = col[1]
                self.d.rectangle([xx, yy, xx + ancho, yy + alto_fila], outline=(0, 0, 0), width=grosor)
                if celda != '':
                    ty = yy + (alto_fila - alto_texto) / 2
                    if col[2] == 'der':
                        tx, al = xx + ancho - pad, 'der'
                    elif col[2] == 'centro':
                        tx, al = xx + ancho / 2, 'centro'
                    else:
                        tx, al = xx + pad, 'izq'
                    self.texto(tx, ty, celda, tam, negrita=(i == 0), rol='celda', alinear=al, tabla=tid,
                               fila=i + 1, col=j + 1, cabecera=(i == 0),
                               celda_bbox=[round(xx), round(yy), round(xx + ancho), round(yy + alto_fila)])
                else:
                    # Celda vacía: se registra sin palabras para que el fixture tenga la celda igual.
                    self.elementos.append({'id': self._id(), 'rol': 'celda', 'texto': '', 'bbox': [round(xx), round(yy), round(xx + ancho), round(yy + alto_fila)],
                                           'palabras': [], 'linea': None, 'tabla': tid, 'fila': i + 1, 'col': j + 1,
                                           'cabecera': (i == 0), 'celda_bbox': [round(xx), round(yy), round(xx + ancho), round(yy + alto_fila)]})
                xx += ancho
            yy += alto_fila
        if titulo:
            self.elementos.append({'id': self._id(), 'rol': 'tabla_titulo', 'texto': titulo, 'tabla': tid, 'bbox': [round(x), round(y), round(x + sum(c[1] for c in columnas)), round(yy)], 'palabras': [], 'linea': None})
        return yy

    def marco(self, x0: float, y0: float, x1: float, y1: float, grosor: int = 3) -> None:
        self.d.rectangle([x0, y0, x1, y1], outline=(0, 0, 0), width=max(1, self.escala(grosor)))

    def linea_h(self, x0: float, y: float, x1: float, grosor: int = 3, color=(0, 0, 0)) -> None:
        self.d.line([x0, y, x1, y], fill=color, width=max(1, self.escala(grosor)))

    def qr_falso(self, x: float, y: float, lado: float, semilla: int = 7) -> None:
        """Patrón de bloques que parece un QR (no codifica nada; Textract no lee QR)."""
        rng = random.Random(semilla)
        n = 25
        celda = lado / n
        self.d.rectangle([x, y, x + lado, y + lado], fill=(255, 255, 255))

        def buscador(cx, cy):
            self.d.rectangle([x + cx * celda, y + cy * celda, x + (cx + 7) * celda, y + (cy + 7) * celda], fill=(0, 0, 0))
            self.d.rectangle([x + (cx + 1) * celda, y + (cy + 1) * celda, x + (cx + 6) * celda, y + (cy + 6) * celda], fill=(255, 255, 255))
            self.d.rectangle([x + (cx + 2) * celda, y + (cy + 2) * celda, x + (cx + 5) * celda, y + (cy + 5) * celda], fill=(0, 0, 0))

        for i in range(n):
            for j in range(n):
                en_buscador = (i < 8 and j < 8) or (i < 8 and j >= n - 8) or (i >= n - 8 and j < 8)
                if not en_buscador and rng.random() < 0.45:
                    self.d.rectangle([x + i * celda, y + j * celda, x + (i + 1) * celda - 1, y + (j + 1) * celda - 1], fill=(0, 0, 0))
        buscador(0, 0)
        buscador(n - 7, 0)
        buscador(0, n - 7)

    # -- salida -------------------------------------------------------------
    def layout(self, archivo: str, **extra) -> dict:
        datos = {
            'documento': self.nombre, 'archivo': archivo, 'ancho': self.ancho, 'alto': self.alto, 'dpi': self.dpi,
            'rotacion_grados': 0.0,
            'nota': 'Geometría en píxeles [x0, y0, x1, y1]; bbox de cada palabra calculado con font.getlength/getbbox al dibujar.',
            'elementos': self.elementos,
        }
        datos.update(extra)
        return datos


def guardar_json(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def guardar_png(img: Image.Image, ruta: Path, dpi: int) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    img.save(ruta, format='PNG', optimize=True, dpi=(dpi, dpi))


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------

def dibujar_factura(nombre: str, dpi: int, trampa: bool = False) -> tuple[Lienzo, dict]:
    """Factura RIDE del SRI (limpia o con dos errores deliberados)."""
    ancho, alto = (round(A4_300[0] * dpi / DPI_BASE), round(A4_300[1] * dpi / DPI_BASE))
    L = Lienzo(nombre, ancho, alto, dpi)
    E = L.escala
    clave = CLAVE_ACCESO_TRAMPA if trampa else FACTURA['clave_acceso']
    items = [dict(i) for i in ITEMS]
    if trampa:
        items[1]['precio_total'] = '95.60'

    # --- bloque emisor (izquierda) ---
    L.qr_falso(E(140), E(150), E(260))
    L.texto(E(440), E(170), EMISOR['razon_social'], 40, negrita=True, rol='titulo')
    L.texto(E(440), E(240), 'Quito - Ecuador', 30)
    L.texto(E(440), E(300), 'Venta de equipos y accesorios de cómputo', 28, color=(60, 60, 60))
    y = E(450)
    L.par(E(140), y, 'Dirección Matriz:', EMISOR['direccion_matriz'], 30)
    L.par(E(140), y + E(55), 'Dirección Sucursal:', EMISOR['direccion_sucursal'], 30)
    L.texto(E(140), y + E(110), EMISOR['regimen'], 30)
    L.par(E(140), y + E(165), 'OBLIGADO A LLEVAR CONTABILIDAD:', EMISOR['obligado_contabilidad'], 30, negrita_clave=True)
    L.marco(E(120), E(130), E(1290), E(700))

    # --- bloque factura (derecha) ---
    L.marco(E(1320), E(130), E(2360), E(790))
    xr = E(1350)
    L.par(xr, E(165), 'RUC:', EMISOR['ruc'], 36, negrita_clave=True)
    L.texto(xr, E(235), 'FACTURA', 52, negrita=True, rol='titulo')
    L.par(xr, E(320), 'No.', FACTURA['numero'], 36, negrita_clave=True)
    L.par(xr, E(395), 'NÚMERO DE AUTORIZACIÓN', clave, 30, negrita_clave=True, misma_linea=False, dy_valor=E(45))
    L.par(xr, E(505), 'FECHA Y HORA DE AUTORIZACIÓN:', FACTURA['fecha_autorizacion'], 30, negrita_clave=True, misma_linea=False, dy_valor=E(45))
    L.par(xr, E(615), 'AMBIENTE:', FACTURA['ambiente'], 30, negrita_clave=True)
    L.par(E(1900), E(615), 'EMISIÓN:', FACTURA['emision'], 30, negrita_clave=True)
    L.par(xr, E(685), 'CLAVE DE ACCESO', clave, 30, negrita_clave=True, misma_linea=False, dy_valor=E(45))

    # --- bloque comprador ---
    L.marco(E(120), E(830), E(2360), E(1060))
    L.par(E(150), E(860), 'Razón Social / Nombres y Apellidos:', COMPRADOR['nombre'], 30)
    L.par(E(1520), E(860), 'Identificación:', COMPRADOR['identificacion'], 30)
    L.par(E(150), E(940), 'Fecha Emisión:', FACTURA['fecha_emision'], 30)
    L.par(E(1520), E(940), 'Dirección:', COMPRADOR['direccion'], 30)
    L.par(E(150), E(1000), 'Guía Remisión:', '001-001-000000456', 28)

    # --- detalle ---
    columnas = [('Cant.', E(200), 'centro'), ('Descripción', E(1040), 'izq'), ('Precio Unitario', E(340), 'der'),
                ('Descuento', E(300), 'der'), ('Precio Total', E(360), 'der')]
    filas = [[i['cantidad'], i['descripcion'], i['precio_unitario'], i['descuento'], i['precio_total']] for i in items]
    y_fin = L.tabla(E(120), E(1120), columnas, filas, tam=32, alto_fila=E(72), tabla_id='T_ITEMS', titulo='detalle')

    # --- totales (derecha) como pares clave-valor en una rejilla ---
    y = y_fin + E(60)
    x0, xm, x1 = E(1560), E(2040), E(2360)
    alto_fila = E(62)
    for i, (etiqueta, valor) in enumerate(TOTALES):
        yy = y + i * alto_fila
        L.d.rectangle([x0, yy, xm, yy + alto_fila], outline=(0, 0, 0), width=max(1, E(2)))
        L.d.rectangle([xm, yy, x1, yy + alto_fila], outline=(0, 0, 0), width=max(1, E(2)))
        pid = L._id('P')
        f = fuente(E(30), etiqueta == 'VALOR TOTAL')
        ty = yy + (alto_fila - f.getbbox('Xg')[3]) / 2
        L.texto(x0 + E(14), ty, etiqueta, 30, negrita=(etiqueta == 'VALOR TOTAL'), rol='clave', par=pid)
        L.texto(x1 - E(14), ty, valor, 30, negrita=(etiqueta == 'VALOR TOTAL'), rol='valor', par=pid, alinear='der')
    y_totales_fin = y + len(TOTALES) * alto_fila

    # --- información adicional y forma de pago (izquierda) ---
    L.texto(E(120), y, 'Información Adicional', 32, negrita=True, rol='titulo')
    L.par(E(120), y + E(60), 'Correo:', COMPRADOR['correo'], 30)
    L.par(E(120), y + E(115), 'Teléfono:', '07 283 4567', 30)
    columnas_pago = [('Forma de Pago', E(900), 'izq'), ('Valor', E(320), 'der')]
    L.tabla(E(120), y + E(200), columnas_pago, [[FORMA_PAGO[0], FORMA_PAGO[1]]], tam=30, alto_fila=E(66), tabla_id='T_PAGO', titulo='forma de pago')

    # --- pie ---
    L.linea_h(E(120), y_totales_fin + E(120), E(2360), 2, color=(120, 120, 120))
    L.texto(ancho / 2, alto - E(140), PIE_FICTICIO, 26, color=(90, 90, 90), alinear='centro')

    gt = {
        'documento': nombre,
        'archivo': f'docs/{nombre}.png',
        'tipo_documento': 'factura',
        'emisor': {'razon_social': EMISOR['razon_social'], 'ruc': EMISOR['ruc'], 'direccion': EMISOR['direccion_matriz'],
                   'obligado_contabilidad': EMISOR['obligado_contabilidad']},
        'comprador': dict(COMPRADOR),
        'numero_factura': FACTURA['numero'],
        'fecha_emision': FACTURA['fecha_emision'],
        'fecha_emision_iso': FACTURA['fecha_emision_iso'],
        'numero_autorizacion': clave,
        'clave_acceso': clave,
        'fecha_autorizacion': FACTURA['fecha_autorizacion'],
        'ambiente': FACTURA['ambiente'],
        'emision': FACTURA['emision'],
        'items': items,
        'totales': {k: v for k, v in TOTALES},
        'forma_pago': {'forma': FORMA_PAGO[0], 'valor': FORMA_PAGO[1]},
        'moneda': 'USD',
        'campos_esperados': {
            'RUC_EMISOR': EMISOR['ruc'], 'NUM_FACTURA': FACTURA['numero'], 'CLAVE_ACCESO': clave,
            'FECHA_EMISION': FACTURA['fecha_emision'], 'SUBTOTAL_15': '821.60', 'IVA_15': '123.24', 'VALOR_TOTAL': '944.84',
        },
        'estado_esperado': 'REVISAR' if trampa else 'OK',
        'alertas_esperadas': [],
    }
    if trampa:
        gt['errores_inyectados'] = [
            {'campo': 'items[1].precio_total', 'impreso': '95.60', 'correcto': '85.60',
             'efecto': 'los ítems suman 831.60 pero el SUBTOTAL 15% / SUBTOTAL SIN IMPUESTOS siguen diciendo 821.60',
             'alerta_esperada': 'ítems no suman el subtotal'},
            {'campo': 'clave_acceso', 'impreso': CLAVE_ACCESO_TRAMPA, 'correcto': FACTURA['clave_acceso'],
             'efecto': 'el dígito verificador (módulo 11) no coincide; se imprime igual en NÚMERO DE AUTORIZACIÓN y CLAVE DE ACCESO',
             'alerta_esperada': 'clave de acceso con dígito verificador inválido'},
        ]
        gt['alertas_esperadas'] = ['ítems no suman el subtotal', 'clave de acceso con dígito verificador inválido']
    return L, gt


def dibujar_formulario(dpi: int) -> tuple[Lienzo, dict]:
    """Formulario de inscripción con pares clave:valor y casillas."""
    ancho, alto = (round(A4_300[0] * dpi / DPI_BASE), round(A4_300[1] * dpi / DPI_BASE))
    L = Lienzo('formulario_inscripcion', ancho, alto, dpi)
    E = L.escala
    L.texto(ancho / 2, E(190), 'Inscripción · AWS Community Day Ecuador 2026', 52, negrita=True, rol='titulo', alinear='centro')
    L.texto(ancho / 2, E(290), 'Universidad Politécnica Salesiana · Cuenca · 5 de septiembre de 2026', 30, alinear='centro', color=(70, 70, 70))
    L.linea_h(E(200), E(370), E(2280), 3)
    L.texto(E(200), E(410), 'Datos del participante', 36, negrita=True, rol='titulo')
    y = E(500)
    for clave, valor in FORMULARIO_CAMPOS:
        L.par(E(200), y, clave, valor, 38)
        L.linea_h(E(200), y + E(62), E(1500), 1, color=(150, 150, 150))
        y += E(105)

    lado = E(47)  # 4 mm a 300 DPI
    y += E(40)
    checkboxes_gt: dict[str, dict[str, bool]] = {}
    for titulo, opciones in FORMULARIO_GRUPOS:
        L.texto(E(200), y, titulo, 38, negrita=True, rol='titulo')
        y += E(80)
        checkboxes_gt[titulo] = {}
        for etiqueta, marcado in opciones:
            L.checkbox(E(240), y, lado, marcado, etiqueta, 36, grupo=titulo)
            checkboxes_gt[titulo][etiqueta] = marcado
            y += E(85)
        y += E(50)

    y += E(60)
    ek = L.texto(E(200), y, 'Firma:', 38, rol='clave', par=L._id('P'))
    L.linea_h(E(360), y + E(52), E(1200), 2)
    L.valor_vacio(ek, [E(360), y - E(10), E(1200), y + E(55)])
    L.texto(ancho / 2, alto - E(140), PIE_FICTICIO, 26, color=(90, 90, 90), alinear='centro')

    gt = {
        'documento': 'formulario_inscripcion',
        'archivo': 'docs/formulario_inscripcion.png',
        'tipo_documento': 'formulario',
        'campos': {c.rstrip(':'): v for c, v in FORMULARIO_CAMPOS},
        'checkboxes': checkboxes_gt,
        'checkboxes_total': sum(len(o) for _, o in FORMULARIO_GRUPOS),
        'checkboxes_marcados': sum(1 for _, o in FORMULARIO_GRUPOS for _, m in o if m),
        'estado_esperado': 'OK',
        'alertas_esperadas': [],
    }
    return L, gt


def envolver(txt: str, f: ImageFont.FreeTypeFont, ancho_max: float) -> list[str]:
    """Parte un párrafo en líneas que quepan en ancho_max píxeles."""
    lineas, actual = [], ''
    for palabra in txt.split(' '):
        prueba = f'{actual} {palabra}'.strip()
        if f.getlength(prueba) <= ancho_max or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def dibujar_orden_compra(dpi: int) -> tuple[Lienzo, dict]:
    """Carta en prosa, sin etiquetas ni tabla."""
    ancho, alto = (round(A4_300[0] * dpi / DPI_BASE), round(A4_300[1] * dpi / DPI_BASE))
    L = Lienzo('orden_compra_prosa', ancho, alto, dpi)
    E = L.escala
    L.texto(E(220), E(200), 'Andina Datos Ejemplo', 34, negrita=True, rol='titulo')
    L.texto(E(220), E(255), 'Calle Larga 4-56, Cuenca · compras@ejemplo.ec', 26, color=(70, 70, 70))
    L.linea_h(E(220), E(320), E(2260), 2, color=(120, 120, 120))
    f = fuente(E(38))
    y = E(420)
    texto_completo = []
    for parrafo in ORDEN_COMPRA_PARRAFOS:
        if not parrafo:
            y += E(45)
            continue
        for linea in envolver(parrafo, f, E(2040)):
            L.texto(E(220), y, linea, 38)
            texto_completo.append(linea)
            y += E(64)
        y += E(20)
    L.texto(ancho / 2, alto - E(140), PIE_FICTICIO, 26, color=(90, 90, 90), alinear='centro')
    gt = {
        'documento': 'orden_compra_prosa',
        'archivo': 'docs/orden_compra_prosa.png',
        'tipo_documento': 'desconocido',
        'tipo_real': 'orden de compra en prosa',
        'proveedor': 'Tecnología Andina Ejemplo S.A.',
        'comprador': 'Andina Datos Ejemplo',
        'fecha_carta': '2026-08-28',
        'fecha_entrega': '2026-09-10',
        'lugar_entrega': 'Calle Larga 4-56, Cuenca',
        'items': [
            {'descripcion': 'Monitor de 27 pulgadas', 'cantidad': 3, 'precio_unitario': 350.00, 'total': 1050.00},
            {'descripcion': 'Teclado mecánico', 'cantidad': 2, 'precio_unitario': 85.60, 'total': 171.20},
        ],
        'monitores': 3,
        'teclados': 2,
        'total': 1221.20,
        'moneda': 'USD',
        'forma_pago': 'transferencia bancaria a la recepción de la factura',
        'firmante': {'nombre': 'María José Cabrera', 'cargo': 'Gerente de Compras'},
        'campos_esperados': {'PROVEEDOR': 'Tecnología Andina Ejemplo S.A.', 'TOTAL_COMPRA': '1221.20', 'CANT_MONITORES': '3'},
        'queries_esperadas_sin_respuesta': ['PROVEEDOR', 'TOTAL_COMPRA', 'CANT_MONITORES'],
        'texto': ' '.join(p for p in ORDEN_COMPRA_PARRAFOS if p),
    }
    return L, gt


def dibujar_mini() -> tuple[Lienzo, dict]:
    """Imagen pequeña con 4 líneas para el checkpoint 0."""
    L = Lienzo('mini', 900, 400, 200)
    f = fuente(L.escala(48))  # 32 px reales
    y = 40
    for linea in MINI_LINEAS:
        L.texto(60, y, linea, 48, negrita=(linea == MINI_LINEAS[1]))
        y += 85
    gt = {'documento': 'mini', 'archivo': 'docs/mini.png', 'tipo_documento': 'desconocido', 'lineas': MINI_LINEAS,
          'caracteres_especiales': ['ñ', 'á', 'é', 'í', 'ó', 'ú', '¿'],
          # El pipeline (etapas.validar) marca REVISAR todo documento 'desconocido': es lo esperado para mini.
          'estado_esperado': 'REVISAR', 'alertas_esperadas': ['tipo de documento no reconocido']}
    return L, gt


def dibujar_recibo(dpi: int) -> tuple[Lienzo, dict]:
    """Recibo de restaurante (documento extra opcional)."""
    ancho, alto = (round(1100 * dpi / DPI_BASE), round(1700 * dpi / DPI_BASE))
    L = Lienzo('recibo_restaurante', ancho, alto, dpi, fondo=(252, 252, 250))
    E = L.escala
    cx = ancho / 2
    L.texto(cx, E(80), RECIBO['nombre'], 40, negrita=True, rol='titulo', alinear='centro')
    L.texto(cx, E(150), 'Mariscos y comida típica', 28, alinear='centro')
    L.par(E(80), E(230), 'RUC:', RECIBO['ruc'], 30)
    L.texto(E(80), E(280), RECIBO['direccion'], 28)
    L.linea_h(E(80), E(340), ancho - E(80), 2)
    L.par(E(80), E(370), 'NOTA DE VENTA No.', RECIBO['numero'], 30, negrita_clave=True)
    L.par(E(80), E(425), 'Fecha:', RECIBO['fecha'], 30)
    L.par(E(80), E(480), 'Mesa:', '7', 30)
    columnas = [('Cant.', E(130), 'centro'), ('Descripción', E(520), 'izq'), ('P. Unit.', E(180), 'der'), ('Total', E(190), 'der')]
    filas = [list(i) for i in RECIBO['items']]
    y = L.tabla(E(40), E(550), columnas, filas, tam=28, alto_fila=E(64), tabla_id='T_ITEMS')
    y += E(50)
    for etiqueta, valor, negrita in [('SUBTOTAL', RECIBO['subtotal'], False), ('SERVICIO 10%', RECIBO['servicio'], False),
                                     ('IVA 15%', RECIBO['iva'], False), ('TOTAL', RECIBO['total'], True)]:
        pid = L._id('P')
        L.texto(E(420), y, etiqueta, 30, negrita=negrita, rol='clave', par=pid)
        L.texto(ancho - E(60), y, valor, 30, negrita=negrita, rol='valor', par=pid, alinear='der')
        y += E(58)
    L.linea_h(E(80), y + E(20), ancho - E(80), 2)
    L.texto(cx, y + E(60), '¡Gracias por su visita!', 30, alinear='centro')
    L.texto(cx, y + E(120), 'Propina voluntaria · Servicio incluido', 24, alinear='centro', color=(80, 80, 80))
    L.texto(cx, alto - E(90), 'DOCUMENTO FICTICIO · SOLO PARA DEMOSTRACIÓN', 22, color=(90, 90, 90), alinear='centro')
    gt = {
        'documento': 'recibo_restaurante',
        'archivo': 'docs/extra/recibo_restaurante.png',
        'tipo_documento': 'factura',
        'tipo_real': 'nota de venta de restaurante',
        'emisor': {'razon_social': RECIBO['nombre'], 'ruc': RECIBO['ruc'], 'direccion': RECIBO['direccion'], 'provincia': 'Guayas'},
        'numero': RECIBO['numero'],
        'fecha': RECIBO['fecha'],
        'items': [{'cantidad': c, 'descripcion': d, 'precio_unitario': p, 'total': t} for c, d, p, t in RECIBO['items']],
        'totales': {'SUBTOTAL': RECIBO['subtotal'], 'SERVICIO 10%': RECIBO['servicio'], 'IVA 15%': RECIBO['iva'], 'TOTAL': RECIBO['total']},
        'nota_calculo': 'IVA 15% sobre el consumo (32.00); el servicio 10% no lleva IVA; TOTAL = consumo + servicio + IVA',
        'moneda': 'USD',
    }
    return L, gt


# ---------------------------------------------------------------------------
# Foto degradada de la factura limpia
# ---------------------------------------------------------------------------

def rotar_punto(x: float, y: float, cx: float, cy: float, ncx: float, ncy: float, grados: float) -> tuple[float, float]:
    """Mapea un punto de la imagen original a la rotada por Image.rotate(grados, expand=True)."""
    t = math.radians(grados)
    dx, dy = x - cx, y - cy
    return (ncx + dx * math.cos(t) + dy * math.sin(t), ncy - dx * math.sin(t) + dy * math.cos(t))


def degradar_a_foto(img: Image.Image, layout: dict, grados: float = 2.0, ancho_final: int = 1200, semilla: int = 42) -> tuple[Image.Image, dict]:
    """Simula una foto de celular: baja resolución, giro, desenfoque, ruido, contraste y luz desigual.

    Devuelve la imagen y un layout nuevo con las geometrías transformadas
    (bbox envolvente + polígono de 4 puntos rotado) para cada elemento y palabra.
    """
    w0, h0 = img.size
    # 1) resize 0.33 y 2) re-escalar a ~1200 px de ancho (pierde nitidez como una foto).
    chica = img.resize((round(w0 * 0.33), round(h0 * 0.33)), Image.BILINEAR)
    escala = ancho_final / w0
    w1, h1 = ancho_final, round(h0 * escala)
    media = chica.resize((w1, h1), Image.BICUBIC)
    # 3) rotación con fondo gris claro (mesa/escritorio).
    rot = media.rotate(grados, expand=True, resample=Image.BICUBIC, fillcolor=(214, 212, 208))
    W, H = rot.size
    # 4) desenfoque suave.
    rot = rot.filter(ImageFilter.GaussianBlur(0.8))
    # 5) ruido gaussiano leve.
    rng = random.Random(semilla)
    ruido = Image.effect_noise((W, H), 18).convert('RGB')
    rot = Image.blend(rot, ruido, 0.10)
    # 6) contraste 0.85.
    rot = ImageEnhance.Contrast(rot).enhance(0.85)
    # 7) brillo desigual: gradiente diagonal multiplicado.
    grad = Image.new('L', (W, H))
    px = grad.load()
    for yy in range(H):
        for xx in range(W):
            v = 255 - int(70 * (xx / W) * 0.6 + 70 * (yy / H) * 0.4)
            px[xx, yy] = v
    rot = ImageChops.multiply(rot, grad.convert('RGB'))
    rot = ImageEnhance.Brightness(rot).enhance(1.05)
    del rng

    # Geometría: escala + rotación sobre el centro (misma convención que Image.rotate expand=True).
    cx, cy = w1 / 2, h1 / 2
    ncx, ncy = W / 2, H / 2

    def transformar_bbox(bb: list[int]) -> tuple[list[int], list[list[int]]]:
        esquinas = [(bb[0], bb[1]), (bb[2], bb[1]), (bb[2], bb[3]), (bb[0], bb[3])]
        pol = [rotar_punto(x * escala, y * escala, cx, cy, ncx, ncy, grados) for x, y in esquinas]
        xs, ys = [p[0] for p in pol], [p[1] for p in pol]
        env = [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]
        return env, [[round(p[0], 2), round(p[1], 2)] for p in pol]

    elementos = []
    for e in layout['elementos']:
        ne = json.loads(json.dumps(e))
        if 'bbox' in ne and ne['bbox']:
            ne['bbox'], ne['poligono'] = transformar_bbox(e['bbox'])
        if 'celda_bbox' in ne:
            ne['celda_bbox'], ne['celda_poligono'] = transformar_bbox(e['celda_bbox'])
        for p in ne.get('palabras', []):
            p['bbox'], p['poligono'] = transformar_bbox(p['bbox'])
        elementos.append(ne)
    nuevo = {
        'documento': 'factura_foto', 'archivo': 'docs/factura_foto.jpg', 'ancho': W, 'alto': H, 'dpi': None,
        'rotacion_grados': grados, 'derivado_de': layout['documento'], 'escala': escala,
        'nota': 'Geometría transformada de factura_limpia: escala + rotación de 2° (polígono real de 4 puntos y bbox envolvente).',
        'elementos': elementos,
    }
    return rot, nuevo


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description='Genera los documentos de ejemplo del taller y su ground truth.')
    ap.add_argument('--dpi', type=int, default=DPI_BASE, help='resolución de los documentos A4 (300 por defecto; 220 si pesan demasiado)')
    args = ap.parse_args()
    dpi = args.dpi

    cargar_fuentes()
    verificar_datos()
    print(f'Fuentes: {cargar_fuentes()[0]}')
    DOCS.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH.mkdir(parents=True, exist_ok=True)
    EXTRA.mkdir(parents=True, exist_ok=True)
    generados: list[Path] = []

    def emitir(L: Lienzo, gt: dict, ruta_png: Path, dpi_doc: int) -> dict:
        guardar_png(L.img, ruta_png, dpi_doc)
        rel = ruta_png.relative_to(RAIZ).as_posix()
        layout = L.layout(rel)
        guardar_json(GROUND_TRUTH / f'{L.nombre}.json', gt)
        guardar_json(GROUND_TRUTH / f'{L.nombre}.layout.json', layout)
        generados.append(ruta_png)
        print(f'  {rel:45s} {ruta_png.stat().st_size / 1024:8.1f} KB  ({L.ancho}x{L.alto})  elementos={len(L.elementos)}')
        return layout

    print('Generando documentos...')
    # mini
    L, gt = dibujar_mini()
    emitir(L, gt, DOCS / 'mini.png', 200)

    # factura limpia (+ PDF de 1 página)
    L, gt = dibujar_factura('factura_limpia', dpi)
    layout_limpia = emitir(L, gt, DOCS / 'factura_limpia.png', dpi)
    L.img.save(DOCS / 'factura_limpia.pdf', format='PDF', resolution=dpi)
    print(f'  {"docs/factura_limpia.pdf":45s} {(DOCS / "factura_limpia.pdf").stat().st_size / 1024:8.1f} KB  (1 página)')
    img_limpia = L.img

    # factura trampa
    L, gt = dibujar_factura('factura_trampa', dpi, trampa=True)
    emitir(L, gt, DOCS / 'factura_trampa.png', dpi)

    # factura foto (derivada de la limpia)
    foto, layout_foto = degradar_a_foto(img_limpia, layout_limpia)
    ruta_foto = DOCS / 'factura_foto.jpg'
    foto.save(ruta_foto, format='JPEG', quality=62, optimize=True)
    gt_foto = json.loads((GROUND_TRUTH / 'factura_limpia.json').read_text(encoding='utf-8'))
    gt_foto.update({
        'documento': 'factura_foto', 'archivo': 'docs/factura_foto.jpg', 'derivado_de': 'factura_limpia',
        'degradacion': {'resize': 0.33, 'ancho_final': foto.size[0], 'rotacion_grados': 2.0, 'gaussian_blur': 0.8,
                        'ruido': 'effect_noise sigma 18 mezclado al 10%', 'contraste': 0.85, 'brillo': 'gradiente diagonal', 'jpeg_calidad': 62},
        'estado_esperado': 'OK',
        'alertas_esperadas': [],
        'nota': ('Los valores impresos son idénticos a factura_limpia. Con los fixtures REALES de Textract '
                 '(grabados el 2026-09-04) la foto degradada se lee perfecta: estado OK y 0 alertas. NO se espera '
                 'la corrección O→0 ni alertas de confianza baja: eran artefactos de los fixtures sintéticos. '
                 'Si el ponente toma una foto NUEVA y sale peor, este ground truth deja de aplicar a esa foto.'),
    })
    # Conserva lo que se anotó a mano tras grabar los fixtures reales (no lo pisa al regenerar las imágenes).
    anterior = GROUND_TRUTH / 'factura_foto.json'
    if anterior.exists():
        previo = json.loads(anterior.read_text(encoding='utf-8'))
        for clave in ('confianza_real_textract', 'estado_esperado', 'alertas_esperadas', 'nota'):
            if clave in previo:
                gt_foto[clave] = previo[clave]
    guardar_json(GROUND_TRUTH / 'factura_foto.json', gt_foto)
    guardar_json(GROUND_TRUTH / 'factura_foto.layout.json', layout_foto)
    generados.append(ruta_foto)
    print(f'  {"docs/factura_foto.jpg":45s} {ruta_foto.stat().st_size / 1024:8.1f} KB  ({foto.size[0]}x{foto.size[1]})')

    # formulario
    L, gt = dibujar_formulario(dpi)
    emitir(L, gt, DOCS / 'formulario_inscripcion.png', dpi)

    # orden de compra en prosa
    L, gt = dibujar_orden_compra(dpi)
    emitir(L, gt, DOCS / 'orden_compra_prosa.png', dpi)

    # recibo (extra)
    L, gt = dibujar_recibo(dpi)
    emitir(L, gt, EXTRA / 'recibo_restaurante.png', dpi)

    # Verificaciones de tamaño.
    problemas = []
    for ruta in generados:
        kb = ruta.stat().st_size / 1024
        limite = 100 if ruta.name == 'mini.png' else 1536
        if kb > limite:
            problemas.append(f'{ruta.relative_to(RAIZ)} pesa {kb:.0f} KB (límite {limite} KB)')
    if problemas:
        print('AVISO: documentos demasiado pesados; vuelve a correr con --dpi 220:')
        for p in problemas:
            print('  -', p)
        return 1
    print(f'Listo: {len(generados)} imágenes + PDF + ground truth en {GROUND_TRUTH.relative_to(RAIZ)}/')
    return 0


if __name__ == '__main__':
    sys.exit(main())
