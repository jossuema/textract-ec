#!/usr/bin/env python3
"""Compara salida/<doc>.validado.json con docs/ground_truth/<doc>.json y reporta aciertos por campo.

Funciona 100 % offline. Evalúa lo que cada ground truth declara: tipo_documento, estado_esperado,
alertas_esperadas (por fragmento), campos_esperados (alias canónicos; montos y fechas se comparan
normalizados), campos y checkboxes de formularios, y queries_esperadas_sin_respuesta.

    python3 04_sistema.py docs/ --offline && python3 tools/evaluar.py
    python3 tools/evaluar.py --procesar            # genera salida/<doc>.validado.json aquí mismo (offline)
    python3 tools/evaluar.py factura_trampa --json
    python3 tools/evaluar.py --bedrock             # además compara fixtures/bedrock/<doc>__<modelo>.json

Código de salida: 0 si todos los campos evaluados coinciden; 1 si hay diferencias o no hay nada que evaluar.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import bedrock, cliente, consola, etapas  # noqa: E402
from textract_lab.modelo import Campo, Resultado  # noqa: E402
from textract_lab.validadores import parse_fecha, parse_monto  # noqa: E402

DIR_GT = RAIZ / 'docs' / 'ground_truth'
DIR_SALIDA_DEFAULT = RAIZ / 'salida'
MODELOS_BEDROCK = ('haiku', 'nova')


# ---------------------------------------------------------------- comparación

def _plano(s) -> str:
    s = unicodedata.normalize('NFKD', str(s if s is not None else ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.casefold().split())


def iguales(esperado, obtenido) -> bool:
    """Montos por valor Decimal, fechas por date, resto por texto normalizado (sin tildes ni mayúsculas)."""
    e, o = str(esperado if esperado is not None else ''), str(obtenido if obtenido is not None else '')
    if _plano(e) == _plano(o):
        return True
    fe, fo = parse_fecha(e), parse_fecha(o)
    if fe is not None and fo is not None:
        return fe == fo
    me, mo = parse_monto(e), parse_monto(o)
    if me is not None and mo is not None and not any(ch.isalpha() for ch in e + o):
        return me == mo
    return e.replace(' ', '') == o.replace(' ', '')


def _sin_parentesis(texto: str) -> str:
    salida, nivel = [], 0
    for ch in texto:
        if ch == '(':
            nivel += 1
        elif ch == ')':
            nivel = max(nivel - 1, 0)
        elif nivel == 0:
            salida.append(ch)
    return ' '.join(''.join(salida).split()).strip(' :')


def alerta_presente(esperada: str, alertas: list[str]) -> bool:
    """La alerta esperada es un fragmento: vale si alguna alerta real la contiene, o contiene su parte antes de ':'."""
    limpia = _plano(_sin_parentesis(esperada))
    prefijo = limpia.split(':', 1)[0].strip()
    reales = [_plano(a) for a in alertas]
    return any(limpia and limpia in a for a in reales) or any(prefijo and prefijo in a for a in reales)


def _valor(campos: dict[str, Campo], *claves: str) -> str | None:
    """Valor del primer campo cuyo nombre coincida (exacto o normalizado); None si no está."""
    for k in claves:
        if k in campos:
            return campos[k].valor
    objetivo = {_plano(k) for k in claves}
    for nombre, campo in campos.items():
        if _plano(nombre) in objetivo or _plano(nombre).strip('[]') in objetivo:
            return campo.valor
    return None


def filas_documento(gt: dict, r: Resultado) -> list[dict]:
    """[{campo, esperado, obtenido, ok}] con todo lo que el ground truth permite evaluar."""
    filas: list[dict] = []

    # Campos que el ground truth declara como fallo A PROPÓSITO: son la lección del taller
    # (sobre prosa, Queries responde con seguridad y se equivoca), no un defecto del kit.
    intencionales = set((gt.get('desajustes_intencionales') or {}).get('campos') or [])

    def fila(campo, esperado, obtenido, ok):
        alias = campo.split(' (')[0]
        filas.append({'campo': campo, 'esperado': '' if esperado is None else str(esperado),
                      'obtenido': '(ausente)' if obtenido is None else str(obtenido),
                      'ok': bool(ok), 'intencional': (not ok) and alias in intencionales})

    if 'tipo_documento' in gt:
        fila('tipo_documento', gt['tipo_documento'], r.tipo_documento, gt['tipo_documento'] == r.tipo_documento)
    if 'estado_esperado' in gt:
        fila('estado', gt['estado_esperado'], r.estado, gt['estado_esperado'] == r.estado)
    for esperada in gt.get('alertas_esperadas') or []:
        fila(f'alerta «{_sin_parentesis(esperada)[:48]}»', 'presente',
             'presente' if alerta_presente(esperada, r.alertas) else 'ausente', alerta_presente(esperada, r.alertas))
    if 'alertas_esperadas' in gt and not gt['alertas_esperadas']:
        fila('sin alertas', '0', str(len(r.alertas)), not r.alertas)

    sin_respuesta = set(gt.get('queries_esperadas_sin_respuesta') or [])
    for alias, esperado in (gt.get('campos_esperados') or {}).items():
        obtenido = _valor(r.campos, alias)
        if alias in sin_respuesta:
            vacio = obtenido is None or not str(obtenido).strip()
            fila(f'{alias} (query sin respuesta)', '(vacío)', '(vacío)' if vacio else obtenido, vacio)
        else:
            fila(alias, esperado, obtenido, obtenido is not None and iguales(esperado, obtenido))

    for clave, esperado in (gt.get('campos') or {}).items():
        obtenido = _valor(r.campos, clave)
        fila(clave, esperado, obtenido, obtenido is not None and iguales(esperado, obtenido))
    for grupo, opciones in (gt.get('checkboxes') or {}).items():
        for opcion, marcado in opciones.items():
            esperado = '[X]' if marcado else '[ ]'
            obtenido = _valor(r.campos, f'[{opcion}]', opcion)
            fila(f'{_sin_parentesis(grupo)} · {opcion}', esperado, obtenido, obtenido == esperado)
    return filas


# ----------------------------------------------------------------- Bedrock

def _llm_valor(j: dict, alias: str):
    d = j or {}
    try:
        if alias == 'PROVEEDOR' or alias == 'RUC_EMISOR':
            return d['emisor']['razon_social' if alias == 'PROVEEDOR' else 'ruc']
        if alias == 'TOTAL_COMPRA' or alias == 'VALOR_TOTAL':
            return d['total']
        if alias == 'CANT_MONITORES':
            for item in d.get('items') or []:
                if 'monitor' in _plano(item.get('descripcion')):
                    return item.get('cantidad')
            return None
        return {'NUM_FACTURA': d.get('numero_factura'), 'CLAVE_ACCESO': d.get('clave_acceso'),
                'FECHA_EMISION': d.get('fecha_emision'), 'SUBTOTAL_15': d.get('subtotal'),
                'IVA_15': d.get('iva'), 'PROPINA': d.get('propina')}.get(alias)
    except (KeyError, TypeError):
        return None


def filas_bedrock(gt: dict, stem: str) -> dict[str, list[dict]]:
    salida: dict[str, list[dict]] = {}
    for modelo in MODELOS_BEDROCK:
        ruta = bedrock.ruta_fixture_bedrock(stem, modelo)
        if not ruta.exists():
            continue
        datos = json.loads(ruta.read_text(encoding='utf-8'))
        j = datos.get('json') or {}
        filas = []
        for alias, esperado in (gt.get('campos_esperados') or {}).items():
            obtenido = _llm_valor(j, alias)
            filas.append({'campo': alias, 'esperado': str(esperado), 'obtenido': '(ausente)' if obtenido is None else str(obtenido),
                          'ok': obtenido is not None and iguales(esperado, obtenido)})
        if 'total' in gt and 'campos_esperados' not in gt:
            filas.append({'campo': 'total', 'esperado': str(gt['total']), 'obtenido': str(j.get('total')),
                          'ok': iguales(gt['total'], j.get('total'))})
        etiqueta = f'{modelo}{" (sintético)" if datos.get("sintetico") else ""}'
        salida[etiqueta] = filas
    return salida


# ------------------------------------------------------------------ E/S

def cargar_resultado(ruta: Path) -> Resultado:
    return Resultado.desde_dict(json.loads(ruta.read_text(encoding='utf-8')))


def procesar(gt: dict, stem: str, dir_salida: Path) -> Path | None:
    """Genera salida/<stem>.validado.json en offline (equivalente a 04_sistema.py para un documento)."""
    archivo = gt.get('archivo') or f'docs/{stem}.png'
    try:
        r = etapas.procesar_documento(archivo, modo='offline')
    except cliente.FixtureFaltante as e:
        consola.aviso(f'{stem}: sin fixtures ({e})')
        return None
    dir_salida.mkdir(parents=True, exist_ok=True)
    ruta = dir_salida / f'{stem}.validado.json'
    ruta.write_text(r.to_json(), encoding='utf-8')
    return ruta


def imprimir_tabla(filas: list[dict]) -> None:
    print(consola.tabla([[f['campo'], f['esperado'][:44], f['obtenido'][:44],
                          consola.color('✔', 'verde') if f['ok'] else consola.color('✘', 'rojo')] for f in filas],
                        ['campo', 'esperado', 'obtenido', '']))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('documentos', nargs='*', help='stems o rutas (docs/factura_trampa.png); default: todos los ground truth')
    ap.add_argument('--salida', default=str(DIR_SALIDA_DEFAULT), help='directorio con <doc>.validado.json (default salida/)')
    ap.add_argument('--procesar', action='store_true', help='generar salida/<doc>.validado.json aquí mismo (offline)')
    ap.add_argument('--bedrock', action='store_true', help='comparar también fixtures/bedrock/<doc>__<modelo>.json')
    ap.add_argument('--json', action='store_true', help='imprimir el resumen como JSON')
    args = ap.parse_args(argv)

    dir_salida = Path(args.salida)
    if not dir_salida.is_absolute() and not dir_salida.exists():
        dir_salida = RAIZ / args.salida
    stems = [Path(d).stem for d in args.documentos] or sorted(p.stem for p in DIR_GT.glob('*.json')
                                                              if not p.name.endswith('.layout.json'))
    resumen = {'documentos': {}, 'aciertos': 0, 'total': 0}
    sin_salida: list[str] = []
    for stem in stems:
        ruta_gt = DIR_GT / f'{stem}.json'
        if not ruta_gt.exists():
            consola.error(f'{stem}: no existe {ruta_gt.relative_to(RAIZ)}')
            sin_salida.append(stem)
            continue
        gt = json.loads(ruta_gt.read_text(encoding='utf-8'))
        ruta_salida = dir_salida / f'{stem}.validado.json'
        if args.procesar:
            ruta_salida = procesar(gt, stem, dir_salida) or ruta_salida
        if not ruta_salida.exists():
            sin_salida.append(stem)
            if not args.json:
                consola.aviso(f'{stem}: falta {ruta_salida.relative_to(RAIZ) if ruta_salida.is_relative_to(RAIZ) else ruta_salida} '
                              '(genera con: python3 04_sistema.py docs/ --offline, o usa --procesar)')
            continue
        r = cargar_resultado(ruta_salida)
        filas = filas_documento(gt, r)
        ok = sum(1 for f in filas if f['ok'])
        intencionales = sum(1 for f in filas if f.get('intencional'))
        entrada = {'aciertos': ok, 'total': len(filas), 'intencionales': intencionales, 'filas': filas}
        if args.bedrock:
            entrada['bedrock'] = filas_bedrock(gt, stem)
        resumen['documentos'][stem] = entrada
        resumen['aciertos'] += ok
        resumen['total'] += len(filas)
        resumen['intencionales'] = resumen.get('intencionales', 0) + intencionales
        if not args.json:
            extra = f' (+{intencionales} desajuste(s) a propósito)' if intencionales else ''
            consola.titulo(f'{stem} · {ok}/{len(filas)} aciertos{extra} · estado {r.estado} · tipo {r.tipo_documento}')
            if filas:
                imprimir_tabla(filas)
            else:
                print('  (el ground truth no declara campos evaluables; solo se generó la salida)')
            for etiqueta, filas_b in (entrada.get('bedrock') or {}).items():
                ok_b = sum(1 for f in filas_b if f['ok'])
                print(f'  Bedrock {etiqueta}: {ok_b}/{len(filas_b)}')
                imprimir_tabla(filas_b)
                resumen['aciertos'] += ok_b
                resumen['total'] += len(filas_b)

    resumen['sin_salida'] = sin_salida
    if args.json:
        print(json.dumps(resumen, ensure_ascii=False, indent=2))
    else:
        consola.titulo('Total')
        inten = resumen.get('intencionales', 0)
        efectivo = resumen['aciertos'] + inten
        pct = (100.0 * resumen['aciertos'] / resumen['total']) if resumen['total'] else 0.0
        linea = f'{resumen["aciertos"]}/{resumen["total"]} campos correctos ({pct:.1f} %) en {len(resumen["documentos"])} documento(s)'
        todo_bien = bool(resumen['total']) and efectivo == resumen['total']
        (consola.ok if todo_bien else consola.error)(linea)
        if inten:
            consola.aviso(f'{inten} de esos desajustes son A PROPÓSITO: el ground truth guarda la verdad '
                          'del documento y Queries se equivoca sobre prosa. Es la lección del bonus, '
                          'no un fallo (ver desajustes_intencionales en el ground truth).')
        if sin_salida:
            consola.aviso(f'sin salida evaluable: {", ".join(sin_salida)}')
    if not resumen['total']:
        return 1
    # Sale 0 si lo único que no cuadra son los desajustes declarados como intencionales.
    return 0 if resumen['aciertos'] + resumen.get('intencionales', 0) == resumen['total'] else 1


if __name__ == '__main__':
    sys.exit(main())
