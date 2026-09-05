"""Overlay de cajas por confianza sobre la imagen (Pillow opcional).

Verde >= 90, amarillo 70-90, rojo < 70. La geometría de Textract es normalizada
(0-1) respecto al ancho/alto de la página: se multiplica por el tamaño en píxeles.
"""
from __future__ import annotations

from pathlib import Path

from . import consola
from .bloques import por_tipo

try:  # Pillow es opcional: si falta, dibujar() devuelve None con aviso.
    from PIL import Image, ImageDraw
    PIL_DISPONIBLE = True
except ImportError:  # pragma: no cover
    Image = ImageDraw = None
    PIL_DISPONIBLE = False

COLORES = {'verde': (34, 197, 94), 'amarillo': (245, 158, 11), 'rojo': (239, 68, 68)}


def color_rgb(conf: float) -> tuple[int, int, int]:
    return COLORES[consola.nombre_color_confianza(conf)]


def _abrir(imagen: Path):
    """Abre PNG/JPEG; para PDF de 1 página intenta PyMuPDF (opcional)."""
    if imagen.suffix.lower() == '.pdf':
        try:
            import fitz  # PyMuPDF (opcional)
        except ImportError:
            return None
        doc = fitz.open(str(imagen))
        pix = doc[0].get_pixmap(dpi=150)
        return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    return Image.open(imagen).convert('RGB')


def _fuente(tamano: int):
    """Fuente de las etiquetas: la de Pillow escalada (>= 10.1); en versiones viejas, la bitmap fija."""
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=tamano)
    except TypeError:  # Pillow < 10.1: load_default() no acepta tamaño
        return ImageFont.load_default()


def _etiqueta(dibujo, texto: str, rgb, caja, ancho: int, grosor: int, fuentes: dict) -> None:
    """Etiqueta compacta con la confianza, a la derecha de la caja (dentro de ella si no hay sitio).

    Se escala con la altura de la línea para que se lea al hacer zoom y no tape la línea de arriba.
    """
    x0, y0, x1, y1 = caja
    alto_caja = max(y1 - y0, 1)
    tam = int(min(max(alto_caja * 0.6, 10), 48))
    fuente = fuentes.get(tam)
    if fuente is None:
        fuente = fuentes[tam] = _fuente(tam)
    izq, arriba, der, abajo = dibujo.textbbox((0, 0), texto, font=fuente)
    tw, th = der - izq, abajo - arriba
    pad = max(1, grosor)
    lx0 = x1 + 2 * grosor
    if lx0 + tw + 2 * pad > ancho:  # pegado al borde derecho: dentro de la caja, alineado a la derecha
        lx0 = max(x1 - tw - 2 * pad, 0)
    ly0 = max(y0 + (alto_caja - th - 2 * pad) / 2, 0)
    dibujo.rectangle([lx0, ly0, lx0 + tw + 2 * pad, ly0 + th + 2 * pad], fill=rgb)
    dibujo.text((lx0 + pad - izq, ly0 + pad - arriba), texto, fill=(255, 255, 255), font=fuente)


def dibujar(imagen: str | Path, resp: dict, salida: str | Path, tipos=('LINE',)) -> Path | None:
    """Dibuja las cajas de los bloques de `tipos` y guarda en `salida`. None si no hay Pillow."""
    if not PIL_DISPONIBLE:
        consola.aviso('overlay omitido: Pillow no está instalado (pip3 install --user pillow); ver docs/salidas/')
        return None
    imagen = Path(imagen)
    if not imagen.exists():
        consola.aviso(f'overlay omitido: no existe {imagen}')
        return None
    img = _abrir(imagen)
    if img is None:
        consola.aviso('overlay omitido: para PDF hace falta PyMuPDF; usa el PNG')
        return None
    ancho, alto = img.size
    dibujo = ImageDraw.Draw(img)
    grosor = max(1, round(min(ancho, alto) / 500))
    fuentes: dict[int, object] = {}
    n = 0
    for tipo in tipos:
        for b in por_tipo(resp, tipo):
            bb = ((b.get('Geometry') or {}).get('BoundingBox') or {})
            if not bb:
                continue
            x0 = bb.get('Left', 0) * ancho
            y0 = bb.get('Top', 0) * alto
            x1 = x0 + bb.get('Width', 0) * ancho
            y1 = y0 + bb.get('Height', 0) * alto
            conf = float(b.get('Confidence', 0) or 0)
            rgb = color_rgb(conf)
            dibujo.rectangle([x0, y0, x1, y1], outline=rgb, width=grosor)
            _etiqueta(dibujo, f'{conf:.0f}', rgb, (x0, y0, x1, y1), ancho, grosor, fuentes)
            n += 1
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    img.save(salida)
    consola.ok(f'overlay guardado: {salida} ({n} cajas)')
    return salida
