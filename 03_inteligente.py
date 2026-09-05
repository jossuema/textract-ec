#!/usr/bin/env python3
"""Lab 3 — la capa inteligente: QUERIES + combinación de fuentes + validadores ecuatorianos.

Qué hace, en orden:
  1. Reutiliza FORMS + TABLES + LAYOUT del Lab 2 (cache/ o fixtures/): no se paga dos veces.
  2. Pide SOLO QUERIES en una llamada separada (US$ 0.015/página, aprox.) con las 7 preguntas
     en inglés/ASCII de textract_lab/queries.py.
  3. Para cada campo canónico elige la fuente con mayor confianza (QUERIES vs FORMS vs la fila
     de totales de la tabla) y lo guarda como Campo{valor, confianza, origen}.
  4. Corre los validadores deterministas (módulo 10/11, regex, IVA 15 %, cuadres con Decimal),
     normaliza sin LLM (fecha ISO, montos, O→0 con re-validación) y decide OK / REVISAR.
  5. Guarda salida/<documento>.validado.json y muestra el costo de la sesión.

Uso:
  python3 03_inteligente.py [documento=docs/factura_limpia.png] [--offline|--online] [--sin-queries] [--json]

Ejercicio opcional: completa `cuadre_por_fila()` al final del archivo (ver checkpoints/lab3/).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def _raiz_repo() -> Path:
    """Sube directorios hasta encontrar textract_lab/ (funciona desde otro cwd o desde checkpoints/)."""
    aqui = Path(__file__).resolve()
    for p in (aqui.parent, *aqui.parents):
        if (p / 'textract_lab' / '__init__.py').exists():
            return p
    return aqui.parent


RAIZ = _raiz_repo()
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import bloques, cliente, consola, costos, etapas  # noqa: E402
from textract_lab.clasificar import clasificar  # noqa: E402
from textract_lab.cliente import ErrorAWS, FixtureFaltante  # noqa: E402
from textract_lab.modelo import Campo, Resultado, Tabla  # noqa: E402
from textract_lab.queries import QUERIES_FACTURA  # noqa: E402
from textract_lab.validadores import (SINONIMOS, TOLERANCIA, campos_canonicos, estado_final,  # noqa: E402
                                      formatear_monto, normalizar_sin_llm, parse_monto, tabla_items,
                                      validar_factura)

DOCUMENTO_DEFAULT = 'docs/factura_limpia.png'
FEATURES_LAB2 = ['FORMS', 'TABLES', 'LAYOUT']  # misma clave de cache/fixture que 02_formulario_tabla.py
DIR_SALIDA = RAIZ / 'salida'
ANCHO_COL = 52  # la clave de acceso tiene 49 dígitos: que se vea completa en la tabla


# ------------------------------------------------------------------ CLI

def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Lab 3: QUERIES + combinación de fuentes + validadores.')
    ap.add_argument('documento', nargs='?', default=DOCUMENTO_DEFAULT,
                    help=f'imagen o PDF de una página (default: {DOCUMENTO_DEFAULT})')
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument('--offline', action='store_true', help='usar solo fixtures/ (sin AWS)')
    modo.add_argument('--online', action='store_true', help='usar AWS (con cache/); requiere credenciales')
    ap.add_argument('--sin-queries', action='store_true', help='no pedir QUERIES: solo FORMS/TABLES')
    ap.add_argument('--json', action='store_true', help='imprimir además el JSON validado completo')
    return ap.parse_args(argv)


# --------------------------------------------------------------- fuentes

def total_en_tablas(tablas: list[Tabla], nombre: str) -> Campo | None:
    """Fila de totales 'VALOR TOTAL | 944.84' de cualquier tabla → Campo(origen='TABLES')."""
    sinonimos = set(SINONIMOS.get(nombre, ()))
    for t in tablas:
        for fila in t.filas:
            celdas = [c for c in fila if str(c).strip()]
            if len(celdas) >= 2 and bloques.normalizar_clave(celdas[-2]) in sinonimos \
                    and parse_monto(celdas[-1]) is not None:
                return Campo(str(celdas[-1]).strip(), t.confianza, 'TABLES')
    return None


def candidatos_por_campo(campos_forms: dict[str, Campo], respuestas: dict[str, Campo],
                         tablas: list[Tabla]) -> dict[str, list[Campo]]:
    """Todas las fuentes con valor para cada campo canónico (para enseñar quién gana y por qué)."""
    forms = campos_canonicos(campos_forms)
    salida: dict[str, list[Campo]] = {}
    for nombre in SINONIMOS:
        lista = []
        q = respuestas.get(nombre)
        if q is not None and not q.vacio():
            lista.append(q)
        f = forms.get(nombre)
        if f is not None and not f.vacio():
            lista.append(f)
        t = total_en_tablas(tablas, nombre)
        if t is not None:
            lista.append(t)
        if lista:
            salida[nombre] = lista
    return salida


# ---------------------------------------------------------- validador extra

def cuadre_por_fila(campos: dict[str, Campo], tablas: list[Tabla]) -> list[str]:
    """EJERCICIO OPCIONAL (2 min): valida cada fila de la tabla de ítems.

    Regla: Cant. × Precio Unitario − Descuento = Precio Total (tolerancia 0.01, con Decimal).
    Hoy la librería solo compara la SUMA de los ítems con el subtotal; esta regla señala QUÉ fila
    está mal. Con docs/factura_trampa.png debe aparecer una alerta para la fila 2 (1 × 85.60 ≠ 95.60).
    Descomenta el bloque y borra el `return []`. La versión resuelta está en checkpoints/lab3/.
    """
    return []
    # alertas: list[str] = []
    # tabla, col_total = tabla_items(tablas)
    # if tabla is None:
    #     return alertas
    # col_cant = bloques.columna(tabla, 'cant')
    # col_unit = bloques.columna(tabla, 'precio unitario')
    # col_desc = bloques.columna(tabla, 'descuento')
    # if col_cant is None or col_unit is None:
    #     return alertas
    # for i, fila in enumerate(tabla.datos, start=1):
    #     if max(col_cant, col_unit, col_total) >= len(fila):
    #         continue
    #     cant, unit, total = parse_monto(fila[col_cant]), parse_monto(fila[col_unit]), parse_monto(fila[col_total])
    #     desc = parse_monto(fila[col_desc]) if col_desc is not None and col_desc < len(fila) else Decimal('0')
    #     if None in (cant, unit, total):
    #         continue
    #     esperado = (cant * unit - (desc or Decimal('0'))).quantize(Decimal('0.01'))
    #     if abs(esperado - total) > TOLERANCIA:
    #         alertas.append(f'fila {i} de ítems no cuadra: {cant} × {formatear_monto(unit)} − '
    #                        f'{formatear_monto(desc or Decimal("0"))} = {formatear_monto(esperado)} '
    #                        f'pero Precio Total dice {formatear_monto(total)}')
    # return alertas


VALIDADORES_EXTRA = [cuadre_por_fila]  # agrega aquí tus propias reglas: (campos, tablas) -> list[str]


# ------------------------------------------------------------------ main

def imprimir_alertas(alertas: list[str]) -> None:
    if not alertas:
        print(consola.color('  (ninguna)', 'verde'))
        return
    for a in alertas:
        tono = 'amarillo' if a.startswith('corregido automáticamente') else 'rojo'
        print('  ' + consola.color('- ' + a, tono))


def ejecutar(args: argparse.Namespace) -> int:
    modo_pedido = 'offline' if args.offline else 'online' if args.online else None
    modo = cliente.resolver_modo(modo_pedido)
    print(cliente.banner_modo(modo), flush=True)

    documento = args.documento
    stem = cliente.stem(documento)
    costo_ejecucion = 0.0
    llamadas: list[dict] = []

    def registrar_llamada() -> None:
        nonlocal costo_ejecucion
        ultima = dict(cliente.ULTIMA_LLAMADA)
        llamadas.append(ultima)
        costo_ejecucion += float(ultima.get('costo_usd') or 0.0)

    # ---- 1. FORMS + TABLES + LAYOUT del Lab 2 (reutilizado, nunca se repite la feature cara)
    consola.titulo('1. FORMS + TABLES + LAYOUT del Lab 2 (reutilizado)')
    resp_estructura: dict | None = None
    # En online llamar() solo consulta cache/ (los fixtures son para offline): se avisa si va a costar.
    if modo == 'online' and not cliente.hay_cache(documento, 'analyze_document', FEATURES_LAB2):
        consola.aviso(f'no está en cache/: se pedirá UNA sola vez a Textract '
                      f'({costos.formatear(costos.costo("analyze_document", FEATURES_LAB2))} por página)')
    try:
        resp_estructura = cliente.llamar('analyze_document', documento, feature_types=FEATURES_LAB2, modo=modo)
        registrar_llamada()
    except FixtureFaltante as e:
        consola.aviso(f'sin FORMS/TABLES para {stem}: {e}')
    campos_forms: dict[str, Campo] = bloques.pares_clave_valor(resp_estructura) if resp_estructura else {}
    tablas: list[Tabla] = bloques.tablas(resp_estructura) if resp_estructura else []
    if resp_estructura:
        origen = cliente.ULTIMA_LLAMADA.get('origen')
        print(f'  origen: {origen} · {len(campos_forms)} pares clave-valor · {len(tablas)} tablas '
              f'· layout: {bloques.resumen_layout(resp_estructura) or "sin bloques LAYOUT"}')
        tipo, evidencias = clasificar({}, resp_estructura)
        if tipo != 'factura':
            consola.aviso(f'{stem} parece "{tipo}" ({"; ".join(evidencias[:3])}). Este lab aplica las reglas '
                          f'de FACTURA igual, para que veas las alertas; para otros tipos usa 04_sistema.py')

    # ---- 2. QUERIES en llamada separada (solo se paga esta feature)
    consola.titulo('2. QUERIES: 7 preguntas en inglés/ASCII (llamada separada)')
    respuestas: dict[str, Campo] = {}
    if args.sin_queries:
        consola.aviso('--sin-queries: se combinan solo FORMS y TABLES')
    else:
        try:
            resp_queries = cliente.llamar('analyze_document', documento, feature_types=['QUERIES'],
                                          queries=QUERIES_FACTURA, modo=modo)
            registrar_llamada()
            respuestas = bloques.respuestas_queries(resp_queries)
            filas = []
            for q in QUERIES_FACTURA:
                alias = q['Alias']
                c = respuestas.get(alias)
                if c is None or c.vacio():
                    filas.append([alias, q['Text'], consola.color('(sin respuesta)', 'rojo'), '—'])
                else:
                    filas.append([alias, q['Text'], c.valor, consola.confianza_coloreada(c.confianza)])
            print(consola.tabla(filas, ['alias', 'query (inglés, ASCII)', 'QUERY_RESULT.Text', 'confianza'],
                                max_ancho_col=ANCHO_COL))
            print(f'  origen: {cliente.ULTIMA_LLAMADA.get("origen")} · costo de esta feature: '
                  f'{costos.formatear(costos.costo("analyze_document", ["QUERIES"]))} por página')
        except FixtureFaltante as e:
            consola.aviso(f'sin QUERIES para {stem}: {e}')

    if resp_estructura is None and not respuestas:
        consola.error(f'sin datos para {stem}: ni FORMS/TABLES ni QUERIES (¿documento sin fixture? prueba --online)')
        return 1

    # ---- 3. Combinación de fuentes: gana la mayor confianza (a igual confianza QUERIES > FORMS > TABLES)
    consola.titulo('3. Combinación de fuentes por confianza → Campo{valor, confianza, origen}')
    campos = etapas.combinar_fuentes(campos_forms, respuestas, tablas)
    filas = [[k, c.valor, consola.confianza_coloreada(c.confianza), c.origen] for k, c in campos.items()]
    print(consola.tabla(filas, ['campo', 'valor', 'confianza', 'origen'], max_ancho_col=ANCHO_COL)
          if filas else '  (ningún campo canónico encontrado)')
    candidatos = candidatos_por_campo(campos_forms, respuestas, tablas)
    disputados = {n: lista for n, lista in candidatos.items() if len(lista) > 1}
    if disputados:
        print('  quién compitió por cada campo (gana la mayor confianza):')
        for nombre, lista in disputados.items():
            partes = ' · '.join(f'{c.origen} {c.confianza:.1f}' for c in lista)
            ganador = campos[nombre]
            print(f'    {nombre:<22} {partes}  → gana {ganador.origen}')

    # ---- 4. Validadores deterministas + normalización sin LLM
    consola.titulo('4. Validadores ecuatorianos (Decimal, módulo 10/11) + normalización sin LLM')
    alertas = validar_factura(campos, tablas)
    normalizados, alertas_norm = normalizar_sin_llm(campos)
    if alertas_norm:
        # Hubo correcciones O→0 / l→1 re-validadas: se vuelve a validar con los valores corregidos.
        alertas = alertas_norm + validar_factura(normalizados, tablas)
    for validador in VALIDADORES_EXTRA:
        alertas += validador(normalizados, tablas)
    estado = estado_final(alertas)

    cambios = [(k, campos[k].valor, normalizados[k].valor) for k in campos
               if k in normalizados and normalizados[k].valor != campos[k].valor]
    if cambios:
        print('  normalizado: ' + ' · '.join(f'{k}: {a} → {b}' for k, a, b in cambios))
    print('  alertas:')
    imprimir_alertas(alertas)
    color_estado = 'verde' if estado == 'OK' else 'rojo'
    print('\n  ESTADO: ' + consola.color(f' {estado} ', color_estado) +
          ('  (todo cuadra)' if estado == 'OK' else f'  ({len(alertas)} alerta(s) → cola de revisión humana)'))

    # ---- 5. Salida JSON + costo
    paginas = max([int(ll.get('paginas') or 1) for ll in llamadas] or [1])
    resultado = Resultado(
        documento=str(documento), tipo_documento='factura', campos=normalizados, tablas=tablas,
        alertas=alertas, estado=estado, paginas=paginas, costo_usd=round(costo_ejecucion, 6), modo=modo,
        extra={
            'generado': datetime.now().isoformat(timespec='seconds'),
            'script': '03_inteligente.py',
            'respuestas_queries': {k: c.__dict__ for k, c in respuestas.items()},
            'fuentes': {n: [c.__dict__ for c in lista] for n, lista in candidatos.items()},
            'llamadas': llamadas,
        },
    )
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    ruta_json = DIR_SALIDA / f'{stem}.validado.json'
    ruta_json.write_text(resultado.to_json(), encoding='utf-8')
    consola.ok(f'guardado {ruta_json.relative_to(RAIZ)}')
    if args.json:
        print(resultado.to_json())

    acum = costos.acumulado()
    print(f'\nCosto de esta ejecución: {costos.formatear(costo_ejecucion)}'
          + ('' if costo_ejecucion else ' — todo desde cache/fixtures')
          + f' · acumulado de la sesión: {costos.formatear(acum["usd"])} '
          f'({acum["llamadas"]} llamadas, {acum["paginas"]} páginas; {acum["nota"]})')
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
    except KeyboardInterrupt:
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
