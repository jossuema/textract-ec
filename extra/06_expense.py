#!/usr/bin/env python3
"""Extra 06 — AnalyzeExpense sobre un recibo de restaurante (EXPERIMENTO fuera de soporte oficial).

AnalyzeExpense está documentado oficialmente SOLO para inglés (FAQ de Textract: "Invoices and
Receipts ... are in English only"). Con documentos en español funciona "parcialmente" según reportes
de la comunidad; por eso en el taller es un experimento, no parte del camino principal. Lo interesante:
la respuesta NO es un grafo de Blocks sino ExpenseDocuments[] con SummaryFields[] (taxonomía normalizada:
VENDOR_NAME, TAX_PAYER_ID, INVOICE_RECEIPT_DATE, SUBTOTAL, TAX, GRATUITY, TOTAL...) y
LineItemGroups[].LineItems[].LineItemExpenseFields[] (ITEM, QUANTITY, UNIT_PRICE, PRICE).
Costo aproximado: US$ 0.01 por página (tarifa Oregón).

Uso:
  python3 extra/06_expense.py [documento=docs/extra/recibo_restaurante.png] [--offline|--online] [--json]

Offline: usa fixtures/<doc>/analyze_expense.json si existe; si no, explica cómo grabarlo (sin fallar).
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path


def _raiz_repo() -> Path:
    aqui = Path(__file__).resolve()
    for p in (aqui.parent, *aqui.parents):
        if (p / 'textract_lab' / '__init__.py').exists():
            return p
    return aqui.parent


RAIZ = _raiz_repo()
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import cliente, consola, costos  # noqa: E402
from textract_lab.cliente import ErrorAWS, FixtureFaltante  # noqa: E402
from textract_lab.validadores import TOLERANCIA, dv_ruc, formatear_monto, parse_fecha, parse_monto  # noqa: E402

DOCUMENTO_DEFAULT = 'docs/extra/recibo_restaurante.png'
DIR_SALIDA = RAIZ / 'salida'
TIPOS_MONTO = ('SUBTOTAL', 'TAX', 'GRATUITY', 'TOTAL', 'AMOUNT_DUE', 'DISCOUNT', 'SERVICE_CHARGE')


def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Extra 06: AnalyzeExpense (experimento, inglés-only oficial).')
    ap.add_argument('documento', nargs='?', default=DOCUMENTO_DEFAULT)
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument('--offline', action='store_true', help='usar solo fixtures/ (sin AWS)')
    modo.add_argument('--online', action='store_true', help='llamar a Textract (con cache/)')
    ap.add_argument('--json', action='store_true', help='guardar salida/<doc>.expense.json e imprimirlo')
    return ap.parse_args(argv)


# ----------------------------------------------------------------- parseo

def campo_texto(campo: dict) -> tuple[str, str, str, float, str]:
    """(Type, etiqueta, valor, confianza, moneda) de un ExpenseField."""
    tipo = (campo.get('Type') or {}).get('Text', 'OTHER')
    etiqueta = ((campo.get('LabelDetection') or {}).get('Text') or '').strip()
    det = campo.get('ValueDetection') or {}
    valor = (det.get('Text') or '').strip().replace('\n', ' ')
    conf = float(det.get('Confidence') or (campo.get('Type') or {}).get('Confidence') or 0.0)
    # Currency {Code, Confidence} es miembro de ExpenseField (hermano de ValueDetection), no de ExpenseDetection.
    moneda = ((campo.get('Currency') or {}).get('Code') or '')
    return tipo, etiqueta, valor, conf, moneda


def resumen(expense_doc: dict) -> dict[str, tuple[str, float]]:
    """Type → (valor, confianza) de SummaryFields (si un Type se repite, gana la mayor confianza)."""
    salida: dict[str, tuple[str, float]] = {}
    for campo in expense_doc.get('SummaryFields') or []:
        tipo, _, valor, conf, _ = campo_texto(campo)
        if valor and (tipo not in salida or conf > salida[tipo][1]):
            salida[tipo] = (valor, conf)
    return salida


def lineas(expense_doc: dict) -> list[dict[str, str]]:
    """Una fila por LineItem: {ITEM, QUANTITY, UNIT_PRICE, PRICE, ...}."""
    filas = []
    for grupo in expense_doc.get('LineItemGroups') or []:
        for item in grupo.get('LineItems') or []:
            fila: dict[str, str] = {}
            for campo in item.get('LineItemExpenseFields') or []:
                tipo, _, valor, _, _ = campo_texto(campo)
                if valor and tipo != 'EXPENSE_ROW':
                    fila[tipo] = valor
            if fila:
                filas.append(fila)
    return filas


def validar(res: dict[str, tuple[str, float]]) -> list[str]:
    """Reglas rápidas con Decimal: RUC (TAX_PAYER_ID/VENDOR_VAT_NUMBER), fecha y subtotal + IVA + propina = total."""
    alertas: list[str] = []
    ruc = (res.get('TAX_PAYER_ID') or res.get('VENDOR_VAT_NUMBER') or ('', 0))[0]
    if ruc:
        limpio = ''.join(ch for ch in ruc if ch.isdigit())
        if len(limpio) != 13 or not dv_ruc(limpio):
            alertas.append(f'RUC del vendedor inválido o incompleto: {ruc!r}')
    else:
        alertas.append('no se encontró el RUC (TAX_PAYER_ID)')
    fecha = (res.get('INVOICE_RECEIPT_DATE') or ('', 0))[0]
    if fecha and parse_fecha(fecha) is None:
        alertas.append(f'fecha no parseable: {fecha!r}')
    montos = {t: parse_monto(res[t][0]) for t in TIPOS_MONTO if t in res}
    sub, total = montos.get('SUBTOTAL'), montos.get('TOTAL')
    # TAX/GRATUITY ausentes (caso probable en español: 'IVA 15%' y 'PROPINA' mapeados a OTHER) valen 0.
    cero = Decimal('0')
    tax = montos.get('TAX') if montos.get('TAX') is not None else cero
    tip = montos.get('GRATUITY') if montos.get('GRATUITY') is not None else cero
    if sub is not None and total is not None:
        esperado = sub + tax + tip
        if abs(esperado - total) > TOLERANCIA:
            alertas.append(f'subtotal {formatear_monto(sub)} + impuesto {formatear_monto(tax)} + propina '
                           f'{formatear_monto(tip)} = {formatear_monto(esperado)} pero TOTAL dice {formatear_monto(total)}'
                           + ('' if 'TAX' in montos and 'GRATUITY' in montos
                              else ' (IVA/propina no reconocidos como TAX/GRATUITY: revisa los campos OTHER)'))
    elif total is None:
        alertas.append('no se encontró TOTAL')
    for t, (_, conf) in res.items():
        if t in TIPOS_MONTO and conf < 90:
            alertas.append(f'confianza baja en {t}: {conf:.1f} < 90')
    return alertas


def explicar_como_grabar(documento: str, e: Exception) -> None:
    stem = cliente.stem(documento)
    consola.aviso(str(e).splitlines()[0])
    print(f"""
No hay fixture de AnalyzeExpense para {stem} (es un extra: los fixtures del taller no lo incluyen).
Para grabarlo desde tu cuenta (≈ US$ 0.01):
  1. AWS_PROFILE=personal python3 extra/06_expense.py {documento} --online
     → la respuesta cruda queda en cache/{stem}/analyze_expense.json
  2. cp cache/{stem}/analyze_expense.json fixtures/{stem}/analyze_expense.json
  3. shasum -a 256 $(find fixtures -name '*.json' -not -name META.json | sort) > fixtures/MANIFEST.sha256
     (desde la raíz del repo: regenera el manifest que valida 00_check.py --offline)
A partir de ahí `--offline` funciona. Recuerda: AnalyzeExpense está documentado solo para inglés; con
recibos en español es un experimento (puede mapear 'PROPINA' a GRATUITY y 'IVA 15%' a TAX... o no).""")


# ------------------------------------------------------------------ main

def ejecutar(args: argparse.Namespace) -> int:
    modo_pedido = 'offline' if args.offline else 'online' if args.online else None
    modo = cliente.resolver_modo(modo_pedido)
    print(cliente.banner_modo(modo), flush=True)
    consola.aviso('AnalyzeExpense está documentado oficialmente solo para inglés: esto es un experimento')
    documento = args.documento
    stem = cliente.stem(documento)

    try:
        resp = cliente.llamar('analyze_expense', documento, modo=modo)
    except FixtureFaltante as e:
        explicar_como_grabar(documento, e)
        return 0
    origen = cliente.ULTIMA_LLAMADA.get('origen')
    docs = resp.get('ExpenseDocuments') or []
    print(f'origen: {origen} · {len(docs)} ExpenseDocument(s) · costo por página '
          f'{costos.formatear(costos.costo("analyze_expense"))}')

    salida = []
    for n, ed in enumerate(docs, start=1):
        consola.titulo(f'SummaryFields (documento {n})')
        filas = []
        for campo in ed.get('SummaryFields') or []:
            tipo, etiqueta, valor, conf, moneda = campo_texto(campo)
            filas.append([tipo, etiqueta, valor + (f' {moneda}' if moneda else ''), consola.confianza_coloreada(conf)])
        print(consola.tabla(filas, ['Type', 'etiqueta en el documento', 'valor', 'confianza']) if filas else '  (vacío)')

        consola.titulo(f'LineItemGroups (documento {n})')
        items = lineas(ed)
        if items:
            columnas = ['ITEM', 'QUANTITY', 'UNIT_PRICE', 'PRICE']
            extra = sorted({k for f in items for k in f} - set(columnas))
            columnas += extra
            print(consola.tabla([[f.get(c, '') for c in columnas] for f in items], columnas))
        else:
            print('  (sin líneas de detalle)')

        consola.titulo('Validación rápida (Decimal)')
        res = resumen(ed)
        alertas = validar(res)
        if alertas:
            for a in alertas:
                print('  ' + consola.color('- ' + a, 'rojo'))
        else:
            print(consola.color('  (ninguna alerta: RUC válido y los montos cuadran)', 'verde'))
        salida.append({'resumen': {k: {'valor': v, 'confianza': c} for k, (v, c) in res.items()},
                       'items': items, 'alertas': alertas, 'estado': 'OK' if not alertas else 'REVISAR'})

    if args.json:
        DIR_SALIDA.mkdir(parents=True, exist_ok=True)
        ruta = DIR_SALIDA / f'{stem}.expense.json'
        ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding='utf-8')
        consola.ok(f'guardado {ruta.relative_to(RAIZ)}')
        print(json.dumps(salida, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parsear_args(argv)
    try:
        return ejecutar(args)
    except ErrorAWS as e:
        consola.error(str(e))
        return 2
    except FileNotFoundError as e:
        consola.error(str(e))
        return 1


if __name__ == '__main__':
    sys.exit(main())
