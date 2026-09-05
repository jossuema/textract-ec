#!/usr/bin/env python3
"""Comprueba el acceso a Amazon Bedrock con un converse mínimo por modelo y traduce los errores.

Modelos por defecto: haiku (perfil us.), haiku-global y nova (ver textract_lab.bedrock.MODELOS).
Errores traducidos: formulario de caso de uso de Anthropic (FTUFormNotFilled), suscripción de
Marketplace en curso (MPAgreementBeingCreated), IAM (AccessDeniedException), ID base sin prefijo
(ValidationException 'on-demand'), throttling, modelo no encontrado, timeouts.

    AWS_PROFILE=personal python3 tools/bedrock_check.py
    python3 tools/bedrock_check.py --dry-run        # solo valida los parámetros contra el service model, sin red

Códigos de salida: 0 = el modelo por defecto (haiku) responde; 1 = solo responde un modelo de respaldo
(cambia MODELO_DEFAULT o usa --modelo nova en el bonus); 2 = ningún modelo responde.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import bedrock, cliente, consola  # noqa: E402

MODELOS_DEFAULT = ['haiku', 'haiku-global', 'nova']
PREGUNTA = 'Responde únicamente con la palabra OK.'


def request_minimo(model_id: str) -> dict:
    return {
        'modelId': model_id,
        'messages': [{'role': 'user', 'content': [{'text': PREGUNTA}]}],
        'inferenceConfig': {'maxTokens': 16, 'temperature': 0},
    }


def validar_contra_service_model(req: dict) -> str:
    """Valida kwargs de converse con botocore (sin red). Devuelve '' si todo está bien o el reporte de errores."""
    try:
        from botocore import loaders, validate
        from botocore.model import ServiceModel
    except ImportError as e:
        return f'boto3 no instalado: {e}'
    # Se carga el service model directamente desde los JSON de botocore: sin sesión, sin perfil, sin red.
    cargador = loaders.create_loader()
    servicio = ServiceModel(cargador.load_service_model('bedrock-runtime', 'service-2'), service_name='bedrock-runtime')
    modelo_op = servicio.operation_model('Converse')
    if 'outputConfig' not in modelo_op.input_shape.members:
        return 'este boto3 no conoce outputConfig (structured outputs): actualiza boto3>=1.43'
    errores = validate.ParamValidator().validate(req, modelo_op.input_shape)
    return errores.generate_report() if errores.has_errors() else ''


def revisar_prefijo(model_id: str) -> str:
    mid = model_id.lower()
    if mid.startswith('anthropic.'):
        return 'ID base de Anthropic: en us-east-1 falla con on-demand; usa el prefijo us. o global.'
    return ''


def dry_run(claves: list[str]) -> int:
    consola.titulo('DRY-RUN · validación local de parámetros (sin llamar a AWS)')
    info = cliente.info_credenciales()
    print(f'AWS_PROFILE={os.environ.get("AWS_PROFILE") or "(no definido)"} · región {info["region"]} · '
          f'credenciales: {"sí" if info["tiene_credenciales"] else "no"} ({info.get("fuente") or "-"})')
    filas = []
    todo_ok = True
    for clave in claves:
        clave, model_id = bedrock.resolver_modelo(clave)
        estrategia = bedrock.estrategia_para(model_id)
        problemas = []
        aviso_prefijo = revisar_prefijo(model_id)
        if aviso_prefijo:
            problemas.append(aviso_prefijo)
        for nombre, req in (('mínimo', request_minimo(model_id)),
                            ('esquema', bedrock.construir_request('texto de prueba', {}, [], clave))):
            reporte = validar_contra_service_model(req)
            if reporte:
                problemas.append(f'{nombre}: {reporte}')
        ok = not problemas
        todo_ok &= ok
        filas.append([clave, model_id, estrategia, '✔ parámetros válidos' if ok else '✘ ' + ' | '.join(problemas)])
    print(consola.tabla(filas, ['clave', 'modelId', 'estrategia JSON', 'validación']))
    if todo_ok:
        consola.ok('parámetros válidos para bedrock-runtime.converse (incluido outputConfig json_schema). '
                   'Sin --dry-run se hace la llamada real.')
        return 0
    consola.error('hay parámetros inválidos: revisa textract_lab/bedrock.py')
    return 1


def probar(clave: str) -> dict:
    clave, model_id = bedrock.resolver_modelo(clave)
    resultado = {'clave': clave, 'modelo_id': model_id, 'ok': False, 'ms': None, 'texto': '', 'error': '', 'codigo': ''}
    req = request_minimo(model_id)
    t0 = time.perf_counter()
    try:
        resp = bedrock.cliente_bedrock().converse(**req)
    except Exception as e:  # noqa: BLE001 — se traduce
        resultado['ms'] = round((time.perf_counter() - t0) * 1000)
        resultado['error'] = bedrock.traducir_error(e)
        try:
            resultado['codigo'] = e.response.get('Error', {}).get('Code', type(e).__name__)
        except AttributeError:
            resultado['codigo'] = type(e).__name__
        return resultado
    resultado['ms'] = round((time.perf_counter() - t0) * 1000)
    contenido = (((resp.get('output') or {}).get('message') or {}).get('content') or [])
    resultado['texto'] = ' '.join(b.get('text', '') for b in contenido if 'text' in b).strip()
    resultado['usage'] = resp.get('usage') or {}
    resultado['costo'] = bedrock.costo_aprox(resultado['usage'], clave)
    resultado['ok'] = True
    return resultado


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--modelo', action='append', metavar='CLAVE',
                    help=f'clave de MODELOS o modelId completo (repetible). Default: {", ".join(MODELOS_DEFAULT)}')
    ap.add_argument('--todos', action='store_true', help='probar todas las claves de textract_lab.bedrock.MODELOS')
    ap.add_argument('--dry-run', action='store_true', help='validar parámetros contra el service model sin llamar a AWS')
    args = ap.parse_args(argv)

    claves = list(bedrock.MODELOS) if args.todos else (args.modelo or MODELOS_DEFAULT)
    if args.dry_run:
        return dry_run(claves)

    perfil = os.environ.get('AWS_PROFILE')
    if not perfil or perfil.lower() == 'default':
        consola.error("define AWS_PROFILE con el perfil de tu cuenta (distinto de 'default'): "
                      'AWS_PROFILE=personal python3 tools/bedrock_check.py')
        return 1
    if os.environ.get('LAB_MODO', '').lower() == 'offline':
        consola.error('LAB_MODO=offline: esta comprobación necesita llamar a Bedrock; quita la variable')
        return 1
    region = os.environ.get('LAB_REGION', cliente.REGION_DEFAULT)
    consola.titulo(f'Bedrock converse mínimo · región {region} · perfil {perfil}')
    resultados = [probar(c) for c in claves]
    for r in resultados:
        if r['ok']:
            u = r.get('usage') or {}
            consola.ok(f'{r["clave"]} ({r["modelo_id"]}): {r["texto"]!r} en {r["ms"]} ms · '
                       f'{u.get("inputTokens", "?")} in / {u.get("outputTokens", "?")} out · ${r.get("costo", 0):.6f} aprox.')
        else:
            consola.error(f'{r["clave"]} ({r["modelo_id"]}) [{r["codigo"]}]: {r["error"]}')

    ok = {r['clave'] for r in resultados if r['ok']}
    print()
    if bedrock.MODELO_DEFAULT in ok:
        consola.ok(f'MODELO_DEFAULT={bedrock.MODELO_DEFAULT!r} responde: el bonus puede correr tal cual. '
                   'Siguiente paso: python3 tools/precalentar_esquema.py')
        return 0
    if ok:
        mejor = next(c for c in claves if bedrock.resolver_modelo(c)[0] in ok)
        consola.aviso(f'{bedrock.MODELO_DEFAULT!r} no responde pero {sorted(ok)} sí: usa --modelo {mejor} en '
                      f'05_bonus_bedrock.py o cambia MODELO_DEFAULT = {mejor!r} en textract_lab/bedrock.py')
        if any('Marketplace' in r['error'] for r in resultados if not r['ok']):
            print('  La suscripción de Marketplace tarda hasta 15 min: repite este script antes de cambiar el default.')
        return 1
    consola.error('ningún modelo respondió. Revisa: formulario de caso de uso (Anthropic), política IAM '
                  '(iam/bedrock-workshop-policy.json), método de pago, región. El bonus tiene --offline como red.')
    return 2


if __name__ == '__main__':
    sys.exit(main())
