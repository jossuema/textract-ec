#!/usr/bin/env python3
"""Precalienta la compilación del esquema de structured outputs en Amazon Bedrock.

La primera llamada con un JSON Schema nuevo en outputConfig puede tardar minutos mientras Bedrock
compila la gramática; después se cachea 24 h POR CUENTA. Este script hace UNA llamada converse con
el esquema EXACTO de textract_lab.bedrock.SCHEMA_DOCUMENTO (el mismo que usa 05_bonus_bedrock.py),
mide la latencia y muestra usage y costo aproximado. Ejecutar jueves, viernes y sábado a T-2h.

    AWS_PROFILE=personal python3 tools/precalentar_esquema.py
    python3 tools/precalentar_esquema.py --dry-run     # muestra la huella del esquema y valida parámetros, sin red

Si cambias SCHEMA_DOCUMENTO (aunque sea un 'description'), la huella cambia y hay que precalentar otra vez.
Los modelos Nova no usan structured outputs (tool use): no necesitan precalentar.

La llamada se hace con read_timeout=300 s y UN solo intento (no los 60 s / 3 intentos del bonus en vivo):
así una compilación lenta no se corta a los 60 s ni se repite tres veces, y el tiempo medido es real.
Si aun así termina por timeout, la compilación probablemente siguió del lado del servidor: repite a los
2-3 minutos antes de concluir que falla (LAB_BEDROCK_TIMEOUT cambia el default de la librería).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import bedrock, bloques, cliente, consola  # noqa: E402

UMBRAL_COMPILACION_MS = 5000
TIMEOUT_PRECALENTAR_S = 300  # la primera compilación de un esquema nuevo puede tardar minutos
TEXTO_RESPALDO = '\n'.join([
    'FACTURA No. 001-001-000001234', 'RUC: 1790456129001', 'Fecha Emisión: 01/09/2026',
    'SUBTOTAL 15% 821.60', 'IVA 15% 123.24', 'VALOR TOTAL 944.84',
])


def huella_esquema() -> str:
    return hashlib.sha256(json.dumps(bedrock.SCHEMA_DOCUMENTO, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:16]


def texto_de_prueba() -> tuple[str, str]:
    """Texto linealizado del fixture de factura_limpia (offline explícito) o un respaldo de 6 líneas."""
    try:
        resp = cliente.llamar('detect_document_text', 'docs/factura_limpia.png', modo='offline', silencioso=True)
        return bloques.texto_completo(resp), 'fixtures/factura_limpia/detect_document_text.json'
    except (cliente.FixtureFaltante, OSError):
        return TEXTO_RESPALDO, 'texto de respaldo'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--modelo', default=bedrock.MODELO_DEFAULT,
                    help=f'clave de MODELOS o modelId (default {bedrock.MODELO_DEFAULT})')
    ap.add_argument('--tambien', action='append', default=[], metavar='CLAVE',
                    help='precalentar además con este modelo (por ejemplo --tambien haiku-global)')
    ap.add_argument('--dry-run', action='store_true', help='no llamar a AWS: huella del esquema + validación de parámetros')
    ap.add_argument('--mostrar-request', action='store_true', help='imprimir el request completo (sin el texto OCR)')
    args = ap.parse_args(argv)

    texto, origen_texto = texto_de_prueba()
    claves = [args.modelo, *args.tambien]
    consola.titulo(f'Esquema SCHEMA_DOCUMENTO · huella {huella_esquema()} · texto de prueba: {origen_texto}')
    requests = []
    for clave in claves:
        clave, model_id = bedrock.resolver_modelo(clave)
        estrategia = bedrock.estrategia_para(model_id)
        req = bedrock.construir_request(texto, {}, [], clave)
        requests.append((clave, model_id, estrategia, req))
        nota = '' if estrategia == 'json_schema' else f' (estrategia {estrategia}: no hay gramática que compilar)'
        print(f'- {clave} → {model_id} · {estrategia}{nota}')
        if args.mostrar_request:
            copia = json.loads(json.dumps(req))
            copia['messages'][0]['content'][0]['text'] = f'<texto OCR: {len(texto)} caracteres>'
            print(json.dumps(copia, ensure_ascii=False, indent=2))

    if args.dry_run:
        from bedrock_check import validar_contra_service_model  # mismo directorio tools/

        fallo = False
        for clave, model_id, _, req in requests:
            reporte = validar_contra_service_model(req)
            if reporte:
                fallo = True
                consola.error(f'{clave}: {reporte}')
            else:
                consola.ok(f'{clave}: parámetros válidos ({len(json.dumps(req))} bytes)')
        if fallo:
            return 1
        consola.ok('DRY-RUN: no se llamó a AWS. Sin --dry-run se hace una llamada converse por modelo.')
        return 0

    perfil = os.environ.get('AWS_PROFILE')
    if not perfil or perfil.lower() == 'default':
        consola.error("define AWS_PROFILE con el perfil de tu cuenta (distinto de 'default')")
        return 1
    if os.environ.get('LAB_MODO', '').lower() == 'offline':
        consola.error('LAB_MODO=offline: quita la variable para llamar a Bedrock')
        return 1

    fallos = 0
    for clave, model_id, estrategia, req in requests:
        if estrategia != 'json_schema':
            consola.aviso(f'{clave}: no usa structured outputs; se omite (no hace falta precalentar)')
            continue
        t0 = time.perf_counter()
        try:
            resp = bedrock.cliente_bedrock(read_timeout=TIMEOUT_PRECALENTAR_S, intentos=1).converse(**req)
        except Exception as e:  # noqa: BLE001
            ms = round((time.perf_counter() - t0) * 1000)
            consola.error(f'{clave} ({model_id}) tras {ms} ms: {bedrock.traducir_error(e)}')
            fallos += 1
            continue
        ms = round((time.perf_counter() - t0) * 1000)
        usage = resp.get('usage') or {}
        try:
            salida = bedrock.extraer_json(resp, estrategia)
            resumen = f'JSON válido ({len(salida)} claves, total={salida.get("total")})'
        except cliente.ErrorAWS as e:
            resumen = f'respuesta sin JSON válido: {e}'
        consola.ok(f'{clave} ({model_id}): {ms} ms · {usage.get("inputTokens", "?")} in / '
                   f'{usage.get("outputTokens", "?")} out · ${bedrock.costo_aprox(usage, clave):.4f} aprox. · {resumen}')
        if ms > UMBRAL_COMPILACION_MS:
            consola.aviso(f'{ms} ms: probablemente compiló el esquema ahora; queda cacheado 24 h en esta cuenta. '
                          'Vuelve a ejecutar para confirmar que la segunda llamada baja de 5 s.')
        else:
            print('  esquema ya cacheado (o compilación rápida). Repetir mañana y el sábado a T-2h.')
    return 2 if fallos and fallos == len([r for r in requests if r[2] == 'json_schema']) else (1 if fallos else 0)


if __name__ == '__main__':
    sys.exit(main())
