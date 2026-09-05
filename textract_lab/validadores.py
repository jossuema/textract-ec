"""Validadores deterministas ecuatorianos (Decimal, sin float) y normalización sin LLM.

Algoritmos (§6 del contrato):
- Cédula: módulo 10 con coeficientes 2,1,2,1,2,1,2,1,2 (restar 9 si el producto > 9).
- RUC: natural (3er dígito < 6) = cédula + '001'; sociedad privada (9) módulo 11 con
  coeficientes 4,3,2,7,6,5,4,3,2 + '001'; pública (6) módulo 11 con 3,2,7,6,5,4,3,2 + '0001'.
- Clave de acceso SRI (49 dígitos): módulo 11 con pesos cíclicos 2..7 de derecha a izquierda.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .bloques import columna, normalizar_clave
from .modelo import Campo, Tabla, como_campo

UMBRAL_CONFIANZA = Decimal('90')
TOLERANCIA = Decimal('0.01')
IVA = Decimal('0.15')
PATRON_NUM_FACTURA = re.compile(r'^\d{3}-\d{3}-\d{9}$')

# Campos canónicos de una factura y sus sinónimos en FORMS (claves normalizadas).
SINONIMOS: dict[str, tuple[str, ...]] = {
    'RUC_EMISOR': ('ruc', 'r.u.c.', 'r.u.c', 'ruc emisor', 'ruc del emisor'),
    'NUM_FACTURA': ('factura no.', 'factura no', 'factura n°', 'factura nº', 'no. factura', 'no factura',
                    'numero de factura', 'factura numero', 'factura #', 'no.', 'nro.', 'nro'),
    'CLAVE_ACCESO': ('clave de acceso', 'clave acceso', 'numero de autorizacion', 'no. de autorizacion',
                     'autorizacion'),
    'FECHA_EMISION': ('fecha emision', 'fecha de emision', 'fecha'),
    'SUBTOTAL_15': ('subtotal 15%', 'subtotal 15', 'subtotal iva 15%', 'subtotal 15 %'),
    'SUBTOTAL_SIN_IMPUESTOS': ('subtotal sin impuestos', 'subtotal'),
    'IVA_15': ('iva 15%', 'iva 15', 'iva 15 %', 'iva'),
    'PROPINA': ('propina', 'servicio 10%', 'propina 10%'),
    'VALOR_TOTAL': ('valor total', 'total', 'total a pagar', 'importe total'),
}
CAMPOS_MONTO = ('SUBTOTAL_15', 'SUBTOTAL_SIN_IMPUESTOS', 'IVA_15', 'PROPINA', 'VALOR_TOTAL')
CAMPOS_IDENTIFICADOR = ('RUC_EMISOR', 'NUM_FACTURA', 'CLAVE_ACCESO')
CAMPOS_OBLIGATORIOS = ('RUC_EMISOR', 'NUM_FACTURA', 'CLAVE_ACCESO', 'FECHA_EMISION',
                       'SUBTOTAL_15', 'IVA_15', 'VALOR_TOTAL')
CAMPOS_FECHA = ('FECHA_EMISION',)

# Claves de FORMS de un formulario (normalizadas) para validar_formulario.
_TRACKS = ('workshop ocr con textract', 'serverless', 'datos y analitica')
_NIVELES = ('principiante', 'intermedio', 'avanzado')
_CUENTA = ('si', 'no')


# ------------------------------------------------------------- utilidades

def solo_digitos(s: str) -> bool:
    return bool(s) and s.isdigit() and s.isascii()


def _d(s: str) -> list[int]:
    return [int(c) for c in s]


def _modulo11(digitos: list[int], coeficientes: list[int]) -> int | None:
    """dv módulo 11: 0 si residuo 0; 11 − residuo; None si el resultado es 10 (inválido)."""
    suma = sum(d * c for d, c in zip(digitos, coeficientes))
    residuo = suma % 11
    dv = 0 if residuo == 0 else 11 - residuo
    return None if dv == 10 else dv


# ---------------------------------------------------------- dígitos verificadores

def dv_cedula(c: str) -> bool:
    """Cédula ecuatoriana de 10 dígitos (módulo 10). Rechaza letras (no int('O'))."""
    c = str(c or '').strip()
    if len(c) != 10 or not solo_digitos(c):
        return False
    provincia = int(c[:2])
    if not (1 <= provincia <= 24 or provincia == 30):
        return False
    if int(c[2]) >= 6:
        return False
    coef = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    suma = 0
    for d, k in zip(_d(c[:9]), coef):
        p = d * k
        if p > 9:
            p -= 9
        suma += p
    dv = (10 - suma % 10) % 10
    return dv == int(c[9])


def dv_ruc(r: str) -> bool:
    """RUC de 13 dígitos: natural / sociedad privada / pública según el tercer dígito."""
    r = str(r or '').strip()
    if len(r) != 13 or not solo_digitos(r):
        return False
    provincia = int(r[:2])
    if not (1 <= provincia <= 24 or provincia == 30):
        return False
    tercero = int(r[2])
    if tercero < 6:
        return dv_cedula(r[:10]) and r[10:] == '001'
    if tercero == 9:
        dv = _modulo11(_d(r[:9]), [4, 3, 2, 7, 6, 5, 4, 3, 2])
        return dv is not None and dv == int(r[9]) and r[10:] == '001'
    if tercero == 6:
        dv = _modulo11(_d(r[:8]), [3, 2, 7, 6, 5, 4, 3, 2])
        return dv is not None and dv == int(r[8]) and r[9:] == '0001'
    return False


def dv_clave_acceso(k: str) -> bool:
    """Clave de acceso SRI de 49 dígitos: módulo 11, pesos 2..7 cíclicos de derecha a izquierda."""
    k = str(k or '').strip()
    if len(k) != 49 or not solo_digitos(k):
        return False
    suma = 0
    peso = 2
    for ch in reversed(k[:48]):
        suma += int(ch) * peso
        peso = 2 if peso == 7 else peso + 1
    residuo = suma % 11
    dv = 11 - residuo
    if dv == 11:
        dv = 0
    elif dv == 10:
        dv = 1
    return dv == int(k[48])


def dv_clave_acceso_esperado(k: str) -> int | None:
    """Dígito verificador que debería llevar la clave (para explicar la alerta)."""
    k = str(k or '').strip()
    if len(k) < 48 or not solo_digitos(k[:48]):
        return None
    suma, peso = 0, 2
    for ch in reversed(k[:48]):
        suma += int(ch) * peso
        peso = 2 if peso == 7 else peso + 1
    dv = 11 - suma % 11
    return {11: 0, 10: 1}.get(dv, dv)


# ------------------------------------------------------------------ parseo

_MONTO_RE = re.compile(r'-?\d[\d.,]*')


def parse_monto(s: str) -> Decimal | None:
    """'944.84', '$ 944.84', '1,234.56', 'USD 12' → Decimal; None si no parsea.

    Punto decimal (formato SRI). Si aparecen ',' y '.', el último es el decimal.
    Solo ',' con grupos de 3 dígitos → separador de miles; si no → decimal.
    """
    if s is None:
        return None
    if isinstance(s, (int, float, Decimal)):
        try:
            return Decimal(str(s)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return None
    txt = str(s).strip().replace(' ', ' ')
    m = _MONTO_RE.search(txt)
    if not m:
        return None
    num = m.group(0)
    if ',' in num and '.' in num:
        if num.rfind(',') > num.rfind('.'):
            num = num.replace('.', '').replace(',', '.')
        else:
            num = num.replace(',', '')
    elif ',' in num:
        if re.fullmatch(r'-?\d{1,3}(,\d{3})+', num):
            num = num.replace(',', '')
        else:
            num = num.replace(',', '.')
    if num.count('.') > 1:
        # '1.234.567' → miles con punto
        num = num.replace('.', '')
    try:
        return Decimal(num).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


_FECHAS = (
    (re.compile(r'^(\d{1,2})/(\d{1,2})/(\d{4})$'), 'dma'),
    (re.compile(r'^(\d{1,2})-(\d{1,2})-(\d{4})$'), 'dma'),
    (re.compile(r'^(\d{4})-(\d{1,2})-(\d{1,2})$'), 'amd'),
    (re.compile(r'^(\d{4})/(\d{1,2})/(\d{1,2})$'), 'amd'),
)


def parse_fecha(s: str) -> date | None:
    """dd/mm/aaaa, dd-mm-aaaa, aaaa-mm-dd (y aaaa/mm/dd) → date; None si no parsea."""
    if s is None:
        return None
    if isinstance(s, date):
        return s
    txt = str(s).strip()
    # Tolera 'FECHA EMISION: 01/09/2026' o '01/09/2026 09:15:00'
    m = re.search(r'\d{1,4}[/-]\d{1,2}[/-]\d{1,4}', txt)
    if not m:
        return None
    txt = m.group(0)
    for patron, orden in _FECHAS:
        m = patron.match(txt)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups())
        try:
            return date(c, b, a) if orden == 'dma' else date(a, b, c)
        except ValueError:
            return None
    return None


def formatear_monto(d: Decimal | int | float | str) -> str:
    """'944.84' con dos decimales (ROUND_HALF_UP). Acepta int/float/str por comodidad (0 → '0.00')."""
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return f'{d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)}'


# --------------------------------------------------- resolución de campos

def _como_campos(campos: dict) -> dict[str, Campo]:
    return {k: como_campo(v) for k, v in (campos or {}).items()}


def campo_canonico(campos: dict, nombre: str) -> Campo | None:
    """Busca `nombre` (alias canónico) o cualquiera de sus sinónimos de FORMS.

    Entre varios candidatos con valor, devuelve el de mayor confianza.
    """
    campos = _como_campos(campos)
    candidatos: list[Campo] = []
    if nombre in campos:
        candidatos.append(campos[nombre])
    sinonimos = set(SINONIMOS.get(nombre, ()))
    for clave, campo in campos.items():
        if clave == nombre:
            continue
        if normalizar_clave(clave) in sinonimos:
            candidatos.append(campo)
    con_valor = [c for c in candidatos if not c.vacio()]
    if con_valor:
        return max(con_valor, key=lambda c: c.confianza)
    return candidatos[0] if candidatos else None


def campos_canonicos(campos: dict) -> dict[str, Campo]:
    """Dict alias → mejor Campo para cada campo canónico de factura presente."""
    salida: dict[str, Campo] = {}
    for nombre in SINONIMOS:
        c = campo_canonico(campos, nombre)
        if c is not None and not c.vacio():
            salida[nombre] = c
    return salida


def tabla_items(tablas: list[Tabla]) -> tuple[Tabla | None, int | None]:
    """La tabla cuya cabecera contiene 'Precio Total' (o 'PRECIO TOTAL') y el índice de esa columna."""
    for t in tablas or []:
        idx = columna(t, 'precio total')
        if idx is None:
            idx = columna(t, 'total')
            if idx is None:
                continue
        return t, idx
    return None, None


def suma_items(tablas: list[Tabla]) -> Decimal | None:
    """Suma de la columna 'Precio Total' de la tabla de ítems; None si no hay tabla."""
    t, idx = tabla_items(tablas)
    if t is None:
        return None
    total = Decimal('0')
    hay = False
    for fila in t.datos:
        if idx >= len(fila):
            continue
        monto = parse_monto(fila[idx])
        if monto is not None:
            total += monto
            hay = True
    return total if hay else None


# ------------------------------------------------------------- validadores

def validar_factura(campos: dict[str, Campo], tablas: list[Tabla]) -> list[str]:
    """Alertas (español) de una factura ecuatoriana. Lista vacía = todo cuadra."""
    alertas: list[str] = []
    c = campos_canonicos(campos)

    for nombre in CAMPOS_OBLIGATORIOS:
        if nombre not in c:
            alertas.append(f'no se encontró {nombre}')

    # Identificadores
    ruc = c.get('RUC_EMISOR')
    if ruc is not None:
        v = ruc.valor.strip()
        if not solo_digitos(v):
            alertas.append(f'RUC_EMISOR contiene caracteres no numéricos: {v!r}')
        elif len(v) != 13:
            alertas.append(f'RUC_EMISOR debe tener 13 dígitos (tiene {len(v)}): {v}')
        elif not dv_ruc(v):
            alertas.append(f'RUC_EMISOR con dígito verificador inválido: {v}')

    num = c.get('NUM_FACTURA')
    if num is not None:
        v = num.valor.strip()
        if not PATRON_NUM_FACTURA.match(v):
            alertas.append(f'NUM_FACTURA no tiene el formato 001-001-000000001: {v!r}')

    clave = c.get('CLAVE_ACCESO')
    if clave is not None:
        v = clave.valor.replace(' ', '').strip()
        if not solo_digitos(v):
            alertas.append(f'CLAVE_ACCESO contiene caracteres no numéricos: {v!r}')
        elif len(v) != 49:
            alertas.append(f'CLAVE_ACCESO debe tener 49 dígitos (tiene {len(v)})')
        elif not dv_clave_acceso(v):
            esperado = dv_clave_acceso_esperado(v)
            alertas.append(f'clave de acceso con dígito verificador inválido '
                           f'(esperado {esperado}, leído {v[48]})')

    fecha = c.get('FECHA_EMISION')
    if fecha is not None:
        f = parse_fecha(fecha.valor)
        if f is None:
            alertas.append(f'FECHA_EMISION no es una fecha válida: {fecha.valor!r}')
        elif f > date.today():
            alertas.append(f'FECHA_EMISION es posterior a hoy: {f.isoformat()}')

    # Montos
    montos: dict[str, Decimal | None] = {}
    for nombre in CAMPOS_MONTO:
        campo = c.get(nombre)
        if campo is None:
            montos[nombre] = None
            continue
        m = parse_monto(campo.valor)
        if m is None:
            alertas.append(f'{nombre} no es un monto válido: {campo.valor!r}')
        montos[nombre] = m

    sub15, iva, total = montos.get('SUBTOTAL_15'), montos.get('IVA_15'), montos.get('VALOR_TOTAL')
    propina = montos.get('PROPINA') or Decimal('0')
    if sub15 is not None and iva is not None:
        esperado = (sub15 * IVA).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if abs(esperado - iva) > TOLERANCIA:
            alertas.append(f'IVA 15% no cuadra: {formatear_monto(sub15)} × 0.15 = '
                           f'{formatear_monto(esperado)} pero IVA_15 dice {formatear_monto(iva)}')
    if sub15 is not None and iva is not None and total is not None:
        suma = sub15 + iva + propina
        if abs(suma - total) > TOLERANCIA:
            alertas.append(f'el total no cuadra: subtotal {formatear_monto(sub15)} + IVA '
                           f'{formatear_monto(iva)} + propina {formatear_monto(propina)} = '
                           f'{formatear_monto(suma)} pero VALOR_TOTAL dice {formatear_monto(total)}')

    subtotal_ref = montos.get('SUBTOTAL_SIN_IMPUESTOS')
    if subtotal_ref is None:
        subtotal_ref = sub15
    items = suma_items(tablas)
    if items is not None and subtotal_ref is not None and abs(items - subtotal_ref) > TOLERANCIA:
        alertas.append(f'ítems no suman el subtotal: ítems {formatear_monto(items)} '
                       f'vs SUBTOTAL {formatear_monto(subtotal_ref)}')

    # Confianza
    for nombre in CAMPOS_MONTO + CAMPOS_IDENTIFICADOR:
        campo = c.get(nombre)
        if campo is not None and Decimal(str(campo.confianza)) < UMBRAL_CONFIANZA:
            alertas.append(f'confianza baja en {nombre}: {campo.confianza:.1f} < 90 (origen {campo.origen})')
    return alertas


def _grupo(selecciones: list[tuple[str, str, float]], etiquetas: tuple[str, ...]) -> list[tuple[str, str]]:
    """Checkboxes cuya clave normalizada contiene una de las etiquetas."""
    salida = []
    for clave, estado, _ in selecciones or []:
        n = normalizar_clave(clave)
        n_tokens = set(re.split(r'[^a-z0-9]+', n))
        for et in etiquetas:
            if (' ' in et and et in n) or (' ' not in et and et in n_tokens):
                salida.append((et, estado))
                break
    return salida


def validar_formulario(campos: dict[str, Campo], selecciones: list[tuple[str, str, float]]) -> list[str]:
    """Alertas de un formulario de inscripción: cédula, correo, nombre y grupos de checkboxes."""
    alertas: list[str] = []
    campos = _como_campos(campos)

    def buscar(*nombres: str) -> Campo | None:
        objetivo = {normalizar_clave(n) for n in nombres}
        for k, v in campos.items():
            if normalizar_clave(k) in objetivo:
                return v
        return None

    cedula = buscar('cedula', 'cedula/ruc', 'c.i.', 'ci', 'identificacion')
    if cedula is None or cedula.vacio():
        alertas.append('no se encontró la cédula')
    else:
        v = cedula.valor.replace(' ', '').replace('-', '')
        if not solo_digitos(v):
            alertas.append(f'cédula contiene caracteres no numéricos: {cedula.valor!r}')
        elif len(v) == 10 and not dv_cedula(v):
            alertas.append(f'cédula con dígito verificador inválido: {v}')
        elif len(v) == 13 and not dv_ruc(v):
            alertas.append(f'RUC con dígito verificador inválido: {v}')
        elif len(v) not in (10, 13):
            alertas.append(f'cédula debe tener 10 dígitos (tiene {len(v)})')
        if cedula.confianza < float(UMBRAL_CONFIANZA):
            alertas.append(f'confianza baja en cédula: {cedula.confianza:.1f} < 90')

    correo = buscar('correo', 'email', 'e-mail', 'correo electronico')
    if correo is None or correo.vacio():
        alertas.append('no se encontró el correo')
    elif '@' not in correo.valor or '.' not in correo.valor.split('@')[-1]:
        alertas.append(f'correo sin formato válido: {correo.valor!r}')

    nombre = buscar('nombre', 'nombres')
    if nombre is None or nombre.vacio():
        alertas.append('no se encontró el nombre')

    for etiqueta, grupo, exacto in (('track', _TRACKS, 1), ('nivel', _NIVELES, 1), ('cuenta AWS', _CUENTA, 1)):
        encontrados = _grupo(selecciones, grupo)
        if not encontrados:
            continue  # el grupo no está en este formulario
        marcados = [et for et, estado in encontrados if estado == 'SELECTED']
        if len(marcados) != exacto:
            alertas.append(f'{etiqueta}: debe haber exactamente {exacto} opción marcada '
                           f'(marcadas {len(marcados)}: {", ".join(marcados) or "ninguna"})')
    return alertas


# --------------------------------------------------------- normalización

_SUSTITUCIONES = str.maketrans({'O': '0', 'o': '0', 'l': '1', 'I': '1', '|': '1'})


def _corregir_numerico(valor: str) -> str:
    return valor.translate(_SUSTITUCIONES)


def normalizar_sin_llm(campos: dict[str, Campo]) -> tuple[dict[str, Campo], list[str]]:
    """Normaliza sin IA generativa. Devuelve (campos_normalizados, alertas).

    - Fechas → ISO (YYYY-MM-DD); montos → '944.84'.
    - En identificadores numéricos: O→0, l→1, I→1 con re-validación (módulo 10/11 o regex);
      si la corrección hace válido el valor se aplica, se marca origen='NORMALIZADO' y se
      agrega la alerta 'corregido automáticamente: X → Y'.
    El origen se conserva cuando solo cambia el formato (no hubo corrección de caracteres).
    """
    campos = _como_campos(campos)
    salida: dict[str, Campo] = dict(campos)
    alertas: list[str] = []

    def canon_de(clave: str) -> str | None:
        if clave in SINONIMOS:
            return clave
        n = normalizar_clave(clave)
        for nombre, sinonimos in SINONIMOS.items():
            if n in sinonimos:
                return nombre
        return None

    validadores = {
        'RUC_EMISOR': dv_ruc,
        'CLAVE_ACCESO': lambda v: dv_clave_acceso(v.replace(' ', '')),
        'NUM_FACTURA': lambda v: bool(PATRON_NUM_FACTURA.match(v)),
    }

    for clave, campo in campos.items():
        canon = canon_de(clave)
        if canon is None:
            n = normalizar_clave(clave)
            if n in ('cedula', 'identificacion', 'ci', 'c.i.'):
                canon = 'CEDULA'
            else:
                continue
        valor = str(campo.valor).strip()
        if not valor:
            continue

        if canon in CAMPOS_FECHA:
            f = parse_fecha(valor)
            if f is not None and f.isoformat() != valor:
                salida[clave] = Campo(f.isoformat(), campo.confianza, campo.origen)
            continue

        if canon in CAMPOS_MONTO:
            m = parse_monto(valor)
            if m is None:
                corregido = _corregir_numerico(valor)
                m = parse_monto(corregido)
                if m is not None:
                    salida[clave] = Campo(formatear_monto(m), campo.confianza, 'NORMALIZADO')
                    alertas.append(f'corregido automáticamente: {valor} → {formatear_monto(m)}')
            elif formatear_monto(m) != valor:
                salida[clave] = Campo(formatear_monto(m), campo.confianza, campo.origen)
            continue

        validar = validadores.get(canon, dv_cedula if canon == 'CEDULA' else None)
        if validar is None:
            continue
        limpio = valor.replace(' ', '') if canon in ('CLAVE_ACCESO', 'CEDULA', 'RUC_EMISOR') else valor
        if validar(limpio):
            if limpio != valor:
                salida[clave] = Campo(limpio, campo.confianza, campo.origen)
            continue
        corregido = _corregir_numerico(limpio)
        if corregido != limpio and validar(corregido):
            salida[clave] = Campo(corregido, campo.confianza, 'NORMALIZADO')
            alertas.append(f'corregido automáticamente: {valor} → {corregido}')
    return salida, alertas


def estado_final(alertas: list[str]) -> str:
    """'OK' si no hay alertas, si no 'REVISAR'."""
    return 'OK' if not alertas else 'REVISAR'
