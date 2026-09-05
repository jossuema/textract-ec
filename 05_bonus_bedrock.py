#!/usr/bin/env python3
"""Bonus (demo del ponente) — Bedrock razona sobre lo que Textract extrajo.

Patrón híbrido: Textract extrae (texto linealizado, campos, alertas) y un LLM en Bedrock, vía Converse,
devuelve el mismo esquema JSON normalizado con explicaciones en español. Dos partes según el documento:
  (a) docs/orden_compra_prosa.png: las 3 queries fallan sobre prosa (PROVEEDOR devuelve el cargo del firmante
      con 60.0, CANT_MONITORES devuelve 27 -las pulgadas- con 99.0, y solo TOTAL_COMPRA se abstiene, que es
      lo correcto); el LLM, leyendo el texto de DetectDocumentText, devuelve proveedor, cantidades y total bien.
  (b) docs/factura_foto.jpg (o docs/factura_foto_real.jpg si existe): normalización + explicación de alertas.
Regla del taller: "el LLM propone, el módulo 11 dispone": el JSON del modelo vuelve a pasar por
textract_lab/validadores.py y toda corrección queda etiquetada como alerta para un revisor humano.

Fallback automático: si la llamada online falla → intenta `nova` una vez → luego fixtures/bedrock/ (offline).

Uso:
  python3 05_bonus_bedrock.py [documento=docs/orden_compra_prosa.png] [--modelo haiku|haiku-global|nova|nova-micro]
                              [--offline|--online] [--grabar-fixture]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def _raiz_repo() -> Path:
    """Sube directorios hasta encontrar textract_lab/ (funciona desde otro cwd)."""
    aqui = Path(__file__).resolve()
    for p in (aqui.parent, *aqui.parents):
        if (p / 'textract_lab' / '__init__.py').exists():
            return p
    return aqui.parent


RAIZ = _raiz_repo()
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import bedrock, bloques, cliente, consola, costos, etapas  # noqa: E402
from textract_lab.clasificar import clasificar  # noqa: E402
from textract_lab.cliente import ErrorAWS, FixtureFaltante  # noqa: E402
from textract_lab.modelo import Campo, Tabla  # noqa: E402
from textract_lab.queries import set_para_tipo  # noqa: E402
from textract_lab.validadores import (TOLERANCIA, dv_ruc, estado_final, formatear_monto, parse_fecha,  # noqa: E402
                                      parse_monto, validar_factura)

DOCUMENTO_DEFAULT = 'docs/orden_compra_prosa.png'
FOTO_REAL = 'docs/factura_foto_real.jpg'
FOTO_SINTETICA = 'docs/factura_foto.jpg'
DIR_SALIDA = RAIZ / 'salida'
MAX_LINEAS_TEXTO = 24


# ------------------------------------------------------------------ CLI

def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Bonus: Textract extrae, Bedrock razona, el módulo 11 dispone.')
    ap.add_argument('documento', nargs='?', default=DOCUMENTO_DEFAULT,
                    help=f'imagen del documento (default: {DOCUMENTO_DEFAULT}; parte (b): {FOTO_SINTETICA})')
    ap.add_argument('--modelo', default=bedrock.MODELO_DEFAULT, metavar='|'.join(bedrock.MODELOS),
                    help=f'clave de textract_lab/bedrock.py o un modelId completo (default: {bedrock.MODELO_DEFAULT})')
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument('--offline', action='store_true', help='usar fixtures/bedrock/ (sin AWS)')
    modo.add_argument('--online', action='store_true', help='llamar a Bedrock (requiere credenciales y acceso)')
    ap.add_argument('--grabar-fixture', action='store_true',
                    help='en online, guardar request/response/usage en fixtures/bedrock/<doc>__<modelo>.json')
    return ap.parse_args(argv)


# ------------------------------------------------------------- Textract

def extraer_con_textract(documento: str, modo: str) -> dict:
    """Texto linealizado + (queries o pipeline completo según el tipo). Solo cache/fixtures en offline."""
    resp_texto = cliente.llamar('detect_document_text', documento, modo=modo, silencioso=True)
    texto = bloques.texto_completo(resp_texto)
    tipo, evidencias = clasificar(resp_texto)
    datos = {'texto': texto, 'tipo': tipo, 'evidencias': evidencias, 'respuestas': {}, 'queries': [],
             'campos': {}, 'alertas': [], 'tablas': [], 'estado_textract': None, 'avisos': []}
    if tipo == 'factura':
        # Reutiliza la tubería del Lab 4 (FORMS/TABLES/QUERIES + validadores): todo sale de cache/fixtures.
        ctx = etapas.procesar_con_contexto(documento, modo=modo)
        datos.update(respuestas=ctx.get('respuestas_queries', {}), queries=ctx.get('queries', []),
                     campos=ctx.get('campos_canonicos', {}), alertas=list(ctx.get('alertas', [])),
                     tablas=ctx.get('tablas', []), estado_textract=ctx.get('estado'), avisos=ctx.get('avisos', []))
        return datos
    queries = set_para_tipo(tipo) or []
    datos['queries'] = queries
    if queries:
        try:
            resp_q = cliente.llamar('analyze_document', documento, feature_types=['QUERIES'], queries=queries,
                                    modo=modo, silencioso=True)
            datos['respuestas'] = bloques.respuestas_queries(resp_q)
        except FixtureFaltante as e:
            datos['avisos'].append(str(e))
    datos['campos'] = {k: c for k, c in datos['respuestas'].items() if not c.vacio()}
    return datos


def imprimir_queries(queries: list[dict], respuestas: dict[str, Campo]) -> None:
    filas = []
    for q in queries:
        alias = q.get('Alias') or q['Text']
        c = respuestas.get(alias)
        if c is None or c.vacio():
            filas.append([alias, q['Text'], consola.color('(sin respuesta)', 'rojo'), '—'])
        else:
            filas.append([alias, q['Text'], c.valor, consola.confianza_coloreada(c.confianza)])
    print(consola.tabla(filas, ['alias', 'query', 'QUERY_RESULT.Text', 'confianza'], max_ancho_col=52))


# -------------------------------------------------------------- Bedrock

def estructurar_con_fallback(texto: str, campos: dict, alertas: list[str], modelo: str, modo: str,
                             documento: str) -> dict:
    """Intenta modelo pedido → nova (online, una vez) → fixtures offline (modelo pedido, haiku, nova)."""
    clave, _ = bedrock.resolver_modelo(modelo)
    intentos: list[tuple[str, str, str]] = [(modelo, modo, documento)]
    if modo == 'online':
        if clave != 'nova':
            intentos.append(('nova', 'online', documento))
        intentos.append((modelo, 'offline', documento))
    for alterno in ('haiku', 'nova'):
        if clave != alterno:
            intentos.append((alterno, 'offline', documento))
    stem = cliente.stem(documento)
    if stem.startswith('factura_foto') and stem != cliente.stem(FOTO_SINTETICA):
        # La foto real no tiene fixture de Bedrock salvo que se grabe: cae al de la foto sintética.
        for m in dict.fromkeys([modelo, 'haiku', 'nova']):
            intentos.append((m, 'offline', FOTO_SINTETICA))

    vistos: set[tuple[str, str, str]] = set()
    errores: list[str] = []
    for m, md, doc in intentos:
        if (m, md, doc) in vistos:
            continue
        vistos.add((m, md, doc))
        try:
            r = bedrock.estructurar(texto, campos, alertas, modelo=m, modo=md, documento=doc)
            r['intentos_fallidos'] = errores
            r['documento_fixture'] = doc if doc != documento else None
            return r
        except (ErrorAWS, FixtureFaltante) as e:
            msg = str(e).splitlines()[0]
            errores.append(f'{m} ({md}): {msg}')
            consola.aviso(f'{m} en modo {md} falló: {msg}')
            if md == 'online' and m != 'nova' and clave != 'nova':
                consola.aviso('reintentando una vez con --modelo nova (Nova Lite, tool use forzado)…')
    mensaje = ('Bedrock no respondió y no hay fixture en fixtures/bedrock/ para este documento:\n  - '
               + '\n  - '.join(errores)
               + f'\ngrábalo en online (python3 05_bonus_bedrock.py {documento} --online --grabar-fixture) '
               f'o usa {DOCUMENTO_DEFAULT} / {FOTO_SINTETICA}')
    # En offline no es un error de AWS (exit 1); en online sí lo fue (exit 2).
    raise (FixtureFaltante if modo == 'offline' else ErrorAWS)(mensaje)


def imprimir_resultado_llm(r: dict, clave_modelo: str) -> None:
    origen = r.get('modo')
    detalle = f'{r["modelo_id"]} · estrategia {r["estrategia"]} · modo {origen}'
    if origen == 'offline':
        detalle += f' · {r.get("fixture")}' + (' (fixture SINTÉTICO, no salió de Bedrock)' if r.get('sintetico') else '')
    if r.get('documento_fixture'):
        consola.aviso(f'se muestra el fixture de {r["documento_fixture"]} (no hay uno para este documento)')
    print('  ' + detalle)
    if r.get('latencia_ms') is not None:
        print(f'  latencia: {r["latencia_ms"]} ms · stopReason: {r.get("stopReason")}')
    print(json.dumps(r['json'], ensure_ascii=False, indent=2))
    u = r.get('usage') or {}
    print(f'\n  usage: {u.get("inputTokens", 0)} in / {u.get("outputTokens", 0)} out '
          f'({u.get("totalTokens", 0)} total) ≈ {costos.formatear(r.get("costo_usd_aprox", 0.0))} '
          f'con {clave_modelo} ({bedrock.NOTA_PRECIOS})')


# ---------------------------------------------------------- re-validación

def _dec(valor) -> Decimal | None:
    return parse_monto(valor) if valor not in (None, '') else None


def revalidar_factura(js: dict, campos_textract: dict[str, Campo], tablas: list[Tabla]) -> tuple[list[str], str]:
    """El JSON del LLM vuelve a pasar por validar_factura; cada cambio respecto a Textract es una alerta."""
    campos_llm = bedrock.json_a_campos(js)
    alertas: list[str] = []
    for k, c in campos_llm.items():
        previo = campos_textract.get(k)
        if previo is None:
            alertas.append(f'el LLM agregó {k} = {c.valor} (Textract no lo tenía): confirmar con el documento')
        elif previo.valor.strip() != c.valor.strip():
            alertas.append(f'el LLM cambió {k}: {previo.valor} → {c.valor} (revisar)')
    alertas += validar_factura(campos_llm, tablas)
    return alertas, estado_final(alertas)


def revalidar_generico(js: dict) -> tuple[list[str], str]:
    """Reglas mínimas para documentos que no son factura: RUC, cuadre de ítems, fecha."""
    alertas: list[str] = []
    ruc = str(((js.get('emisor') or {}).get('ruc')) or '').strip()
    if ruc and not dv_ruc(ruc):
        alertas.append(f'RUC del emisor con dígito verificador inválido: {ruc}')
    suma = Decimal('0')
    for i, it in enumerate(js.get('items') or [], start=1):
        cant, unit, tot = _dec(it.get('cantidad')), _dec(it.get('precio_unitario')), _dec(it.get('total'))
        if None in (cant, unit, tot):
            alertas.append(f'ítem {i} incompleto: {it}')
            continue
        if abs(cant * unit - tot) > TOLERANCIA:
            alertas.append(f'ítem {i} no cuadra: {cant} × {formatear_monto(unit)} ≠ {formatear_monto(tot)}')
        suma += tot
    sub, iva, prop, total = (_dec(js.get(k)) for k in ('subtotal', 'iva', 'propina', 'total'))
    if total is not None and (js.get('items') or []) and abs(suma - (sub if sub is not None else suma)) > TOLERANCIA:
        alertas.append(f'ítems suman {formatear_monto(suma)} pero subtotal dice {formatear_monto(sub)}')
    if None not in (sub, total):
        esperado = sub + (iva or Decimal('0')) + (prop or Decimal('0'))
        if abs(esperado - total) > TOLERANCIA:
            alertas.append(f'subtotal + IVA + propina = {formatear_monto(esperado)} pero total dice {formatear_monto(total)}')
    fecha = str(js.get('fecha_emision') or '').strip()
    if fecha and parse_fecha(fecha) is None:
        alertas.append(f'fecha_emision no es una fecha válida: {fecha!r}')
    return alertas, estado_final(alertas)


def comparar_queries_vs_llm(respuestas: dict[str, Campo], js: dict) -> None:
    """Tabla Queries vs LLM para la orden de compra (PROVEEDOR, TOTAL_COMPRA, CANT_MONITORES)."""
    monitores = sum(int(_dec(it.get('cantidad')) or 0) for it in js.get('items') or []
                    if 'monitor' in str(it.get('descripcion', '')).lower())
    llm = {
        'PROVEEDOR': (js.get('emisor') or {}).get('razon_social', ''),
        'TOTAL_COMPRA': formatear_monto(_dec(js.get('total'))) if _dec(js.get('total')) is not None else '',
        'CANT_MONITORES': str(monitores) if monitores else '',
    }
    filas = []
    for alias, valor_llm in llm.items():
        c = respuestas.get(alias)
        textract = c.valor if c is not None and not c.vacio() else consola.color('(sin respuesta)', 'rojo')
        filas.append([alias, textract, consola.color(valor_llm, 'verde') if valor_llm else '(vacío)'])
    print(consola.tabla(filas, ['campo', 'Textract Queries', 'LLM (Bedrock)']))


# ------------------------------------------------------------------ main

def ejecutar(args: argparse.Namespace) -> int:
    modo_pedido = 'offline' if args.offline else 'online' if args.online else None
    modo = cliente.resolver_modo(modo_pedido)
    print(cliente.banner_modo(modo), flush=True)

    documento = args.documento
    if documento == FOTO_REAL and not cliente.resolver_documento(documento).exists():
        consola.aviso(f'{FOTO_REAL} no existe todavía (se toma el sábado): usando {FOTO_SINTETICA}')
        documento = FOTO_SINTETICA
    clave_modelo, model_id = bedrock.resolver_modelo(args.modelo)
    stem = cliente.stem(documento)

    # ---- 1. Textract
    consola.titulo('1. Textract: texto linealizado (DetectDocumentText) y lo que las queries encontraron')
    datos = extraer_con_textract(documento, modo)
    lineas = datos['texto'].splitlines()
    for ln in lineas[:MAX_LINEAS_TEXTO]:
        print('  │ ' + ln)
    if len(lineas) > MAX_LINEAS_TEXTO:
        print(f'  │ … ({len(lineas) - MAX_LINEAS_TEXTO} líneas más)')
    print(f'  tipo tentativo: {datos["tipo"]} · {len(lineas)} líneas')
    for a in datos['avisos']:
        consola.aviso(a.splitlines()[0])
    if datos['queries']:
        print()
        imprimir_queries(datos['queries'], datos['respuestas'])
    if datos['tipo'] == 'factura':
        print(f'  campos del Lab 3 (fuente ganadora): {len(datos["campos"])} · alertas: {len(datos["alertas"])} '
              f'· estado Textract: {datos["estado_textract"]}')
        for a in datos['alertas']:
            print('    - ' + a)

    # ---- 2. Bedrock
    consola.titulo(f'2. Bedrock Converse ({clave_modelo} → {model_id}): el LLM propone')
    if modo == 'online':
        print(f'  system prompt en español · temperature {bedrock.TEMPERATURA} · maxTokens {bedrock.MAX_TOKENS} · '
              f'estrategia {bedrock.estrategia_para(model_id)}')
    r = estructurar_con_fallback(datos['texto'], datos['campos'], datos['alertas'], args.modelo, modo, documento)
    clave_usada, _ = bedrock.resolver_modelo(r.get('modelo_id') or args.modelo)
    imprimir_resultado_llm(r, clave_usada)
    js = r['json'] if isinstance(r.get('json'), dict) else {}
    if r.get('modo') == 'online' and args.grabar_fixture:
        bedrock.guardar_fixture(documento, clave_usada, r)
        consola.aviso('recuerda regenerar fixtures/MANIFEST.sha256 (tools/grabar_fixtures.py) antes de commitear')

    # ---- 3. El módulo 11 dispone
    consola.titulo('3. El LLM propone, el módulo 11 dispone (re-validación determinista)')
    if datos['tipo'] == 'factura':
        alertas, estado = revalidar_factura(js, datos['campos'], datos['tablas'])
    else:
        comparar_queries_vs_llm(datos['respuestas'], js)
        alertas, estado = revalidar_generico(js)
    if js.get('alertas'):
        print('  alertas explicadas por el LLM:')
        for a in js['alertas']:
            print('    · ' + str(a))
    if js.get('explicacion'):
        print(f'  explicación del LLM: {js["explicacion"]}')
    print('  alertas de los validadores sobre el JSON del LLM:')
    if alertas:
        for a in alertas:
            print('    ' + consola.color('- ' + a, 'rojo' if not a.startswith('el LLM') else 'amarillo'))
    else:
        print(consola.color('    (ninguna: el JSON del LLM pasa todas las reglas)', 'verde'))
    print('\n  revalidado por módulo 11: ' + consola.color(f' {estado} ', 'verde' if estado == 'OK' else 'rojo'))

    # ---- 4. Guardar
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = DIR_SALIDA / f'{stem}.bedrock.json'
    ruta.write_text(json.dumps({
        'generado': datetime.now().isoformat(timespec='seconds'),
        'documento': documento, 'tipo_textract': datos['tipo'],
        'modelo_id': r.get('modelo_id'), 'estrategia': r.get('estrategia'), 'modo': r.get('modo'),
        'fixture': r.get('fixture'), 'sintetico': r.get('sintetico', False),
        'usage': r.get('usage'), 'costo_usd_aprox': r.get('costo_usd_aprox'),
        'intentos_fallidos': r.get('intentos_fallidos', []),
        'json_llm': js,
        'revalidacion': {'alertas': alertas, 'estado': estado},
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    consola.ok(f'guardado {ruta.relative_to(RAIZ)}')
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parsear_args(argv)
    try:
        return ejecutar(args)
    except ErrorAWS as e:
        consola.error(str(e))
        return 2
    except (FixtureFaltante, FileNotFoundError) as e:
        consola.error(str(e))
        return 1
    except KeyboardInterrupt:
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
