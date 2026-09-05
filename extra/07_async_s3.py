#!/usr/bin/env python3
"""Extra 07 — operaciones ASÍNCRONAS: StartDocumentAnalysis / GetDocumentAnalysis desde S3.

Cuándo hace falta: PDF/TIFF de varias páginas (hasta 500 MB y 3.000 páginas) o más de 10 MB.
Las operaciones asíncronas NO aceptan Bytes: el documento debe estar en un bucket S3 de la MISMA
región que Textract (us-east-1). Sin SNS: hacemos polling con GetDocumentAnalysis y paginamos
con NextToken (MaxResults máximo 1.000 bloques por página de resultados). El JobId vale 7 días.

Este extra es SOLO ONLINE. `--dry-run` imprime exactamente lo que haría (sin tocar AWS).

Uso:
  python3 extra/07_async_s3.py documento.pdf --bucket mi-bucket [--clave prefijo/nombre.pdf]
                               [--features FORMS TABLES] [--solo-texto] [--intervalo 5] [--timeout 600] [--dry-run]

Permisos IAM adicionales a los del taller: textract:StartDocumentAnalysis, textract:GetDocumentAnalysis
(o *TextDetection), s3:PutObject y s3:GetObject sobre el bucket (Textract lee el objeto con tus credenciales).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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

from textract_lab import bloques, cliente, consola, costos  # noqa: E402
from textract_lab.cliente import ErrorAWS  # noqa: E402

DOCUMENTO_DEFAULT = 'docs/factura_limpia.pdf'
EXTENSIONES = ('.pdf', '.tiff', '.tif', '.png', '.jpg', '.jpeg')
FEATURES_VALIDAS = ('FORMS', 'TABLES', 'QUERIES', 'SIGNATURES', 'LAYOUT')
DIR_SALIDA = RAIZ / 'salida'


def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Extra 07: Textract asíncrono desde S3 (solo online).')
    ap.add_argument('documento', nargs='?', default=DOCUMENTO_DEFAULT, help='PDF/TIFF/PNG/JPG local')
    ap.add_argument('--bucket', required=True, help='bucket S3 en la misma región (us-east-1)')
    ap.add_argument('--clave', default=None, help='clave S3 destino (default: textract-ec/<nombre>)')
    ap.add_argument('--features', nargs='+', default=['FORMS', 'TABLES'], metavar='FEATURE',
                    help='FeatureTypes para StartDocumentAnalysis (default: FORMS TABLES)')
    ap.add_argument('--solo-texto', action='store_true',
                    help='usar StartDocumentTextDetection/GetDocumentTextDetection (sin features, más barato)')
    ap.add_argument('--intervalo', type=float, default=5.0, help='segundos entre consultas de estado (default 5)')
    ap.add_argument('--timeout', type=float, default=600.0, help='segundos máximos de espera (default 600)')
    ap.add_argument('--no-subir', action='store_true', help='el objeto ya está en S3: no volver a subirlo')
    ap.add_argument('--dry-run', action='store_true', help='mostrar el plan sin llamar a AWS')
    return ap.parse_args(argv)


def region() -> str:
    return os.environ.get('LAB_REGION', cliente.REGION_DEFAULT)


def plan(args: argparse.Namespace, ruta: Path, clave: str) -> dict:
    """Los parámetros exactos de cada llamada (lo que imprime --dry-run y lo que ejecuta el modo real)."""
    features = [f.upper() for f in args.features]
    for f in features:
        if f not in FEATURES_VALIDAS:
            raise ValueError(f'FeatureType desconocido: {f} (válidos: {", ".join(FEATURES_VALIDAS)})')
    if 'QUERIES' in features:
        # Textract exige QueriesConfig cuando se pide QUERIES; este extra no admite pasar queries.
        raise ValueError('QUERIES requiere QueriesConfig y este extra no admite --queries: usa FORMS, TABLES, '
                         'LAYOUT o SIGNATURES (para queries, ver 03_inteligente.py con textract_lab.queries)')
    if args.solo_texto:
        inicio, consulta, params = 'start_document_text_detection', 'get_document_text_detection', {}
    else:
        inicio, consulta, params = 'start_document_analysis', 'get_document_analysis', {'FeatureTypes': features}
    return {
        'region': region(),
        'subir': None if args.no_subir else {'api': 's3.upload_file', 'Filename': str(ruta), 'Bucket': args.bucket, 'Key': clave},
        'inicio': {'api': f'textract.{inicio}',
                   'params': {'DocumentLocation': {'S3Object': {'Bucket': args.bucket, 'Name': clave}}, **params}},
        'consulta': {'api': f'textract.{consulta}', 'params': {'JobId': '<JobId>', 'MaxResults': 1000, 'NextToken': '<opcional>'}},
        'features': [] if args.solo_texto else features,
        'operacion_costo': 'detect_document_text' if args.solo_texto else 'analyze_document',
    }


def imprimir_plan(p: dict, args: argparse.Namespace) -> None:
    consola.titulo('Plan (--dry-run: no se llama a AWS)')
    print(f'  región: {p["region"]} (el bucket debe estar en la misma región)')
    if p['subir']:
        print(f'  1. {p["subir"]["api"]}(Filename={p["subir"]["Filename"]!r}, Bucket={args.bucket!r}, Key={p["subir"]["Key"]!r})')
    else:
        print('  1. (sin subir: --no-subir)')
    print(f'  2. {p["inicio"]["api"]}(**{json.dumps(p["inicio"]["params"], ensure_ascii=False)})')
    print(f'     → JobId (válido 7 días). Sin NotificationChannel: no hace falta SNS ni iam:PassRole.')
    print(f'  3. cada {args.intervalo:g} s: {p["consulta"]["api"]}(JobId=...) hasta JobStatus != IN_PROGRESS (máx. {args.timeout:g} s)')
    print('  4. si SUCCEEDED (o PARTIAL_SUCCESS: algunas páginas fallaron, con aviso): acumular Blocks siguiendo '
          'NextToken (MaxResults 1000) hasta que no venga más; FAILED → código 2')
    print(f'  5. guardar salida/<documento>.async.json y resumir bloques por tipo y páginas')
    costo_pag = costos.costo(p['operacion_costo'], p['features'] or None)
    print(f'  costo aproximado: {costos.formatear(costo_pag)} por página ({costos.NOTA_TARIFAS})')
    print('  permisos: textract:Start*/Get* + s3:PutObject/GetObject sobre el bucket (no están en iam/textract-workshop-policy.json)')


def ejecutar_real(p: dict, args: argparse.Namespace, ruta: Path, stem: str) -> int:
    import boto3
    from botocore import exceptions as bexc
    from botocore.config import Config

    perfil = os.environ.get('AWS_PROFILE')
    sesion = boto3.Session(profile_name=perfil) if perfil else boto3.Session()
    cfg = Config(retries={'total_max_attempts': 10, 'mode': 'standard'})
    try:
        if p['subir']:
            s3 = sesion.client('s3', region_name=p['region'], config=cfg)
            s3.upload_file(p['subir']['Filename'], p['subir']['Bucket'], p['subir']['Key'])
            consola.ok(f'subido s3://{args.bucket}/{p["subir"]["Key"]}')
        tx = sesion.client('textract', region_name=p['region'], config=cfg)
        inicio = p['inicio']['api'].split('.', 1)[1]
        consulta = p['consulta']['api'].split('.', 1)[1]
        job = getattr(tx, inicio)(**p['inicio']['params'])
        job_id = job['JobId']
        print(f'JobId: {job_id}')

        t0 = time.monotonic()
        estado, resp = 'IN_PROGRESS', {}
        while estado == 'IN_PROGRESS':
            if time.monotonic() - t0 > args.timeout:
                consola.error(f'tiempo de espera agotado ({args.timeout:g} s); el JobId sigue válido 7 días')
                return 2
            time.sleep(args.intervalo)
            resp = getattr(tx, consulta)(JobId=job_id, MaxResults=1000)
            estado = resp.get('JobStatus', 'IN_PROGRESS')
            print(f'  {time.monotonic() - t0:5.1f} s · JobStatus={estado}', flush=True)
        if estado == 'PARTIAL_SUCCESS':
            # Algunas páginas fallaron pero el trabajo (ya cobrado) trae bloques: se aprovechan.
            consola.aviso(f'el trabajo terminó en PARTIAL_SUCCESS: {resp.get("StatusMessage", "")} · '
                          f'Warnings: {json.dumps(resp.get("Warnings") or [], ensure_ascii=False)}')
        elif estado != 'SUCCEEDED':
            consola.error(f'el trabajo terminó en {estado}: {resp.get("StatusMessage", "")}')
            return 2

        bloques_totales = list(resp.get('Blocks') or [])
        paginas_resultado = 1
        token = resp.get('NextToken')
        while token:
            resp = getattr(tx, consulta)(JobId=job_id, MaxResults=1000, NextToken=token)
            bloques_totales += resp.get('Blocks') or []
            paginas_resultado += 1
            token = resp.get('NextToken')
    except bexc.NoCredentialsError:
        consola.error('sin credenciales de AWS: este extra solo funciona online (exporta AWS_PROFILE)')
        return 2
    except (bexc.BotoCoreError, bexc.ClientError) as e:
        raise ErrorAWS(cliente.explicar_error(e, inicio), e) from e

    paginas_doc = int((resp.get('DocumentMetadata') or {}).get('Pages', 1) or 1)
    completo = {'DocumentMetadata': resp.get('DocumentMetadata'), 'JobStatus': estado, 'Blocks': bloques_totales,
                'AnalyzeDocumentModelVersion': resp.get('AnalyzeDocumentModelVersion')
                or resp.get('DetectDocumentTextModelVersion')}
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    ruta_salida = DIR_SALIDA / f'{stem}.async.json'
    cliente.escribir_json(ruta_salida, completo)
    consola.ok(f'{len(bloques_totales)} bloques en {paginas_resultado} página(s) de resultados → {ruta_salida.relative_to(RAIZ)}')
    print(f'páginas del documento: {paginas_doc} · bloques por tipo: {bloques.resumen_bloques(completo)}')
    for texto, conf in bloques.lineas(completo)[:10]:
        print(f'  {consola.semaforo(conf)} {conf:5.1f}  {texto}')
    costo = costos.costo(p['operacion_costo'], p['features'] or None, paginas_doc)
    costos.registrar(p['operacion_costo'], p['features'] or None, paginas_doc)
    print(f'costo aproximado: {costos.formatear(costo)} ({costos.NOTA_TARIFAS})')
    return 0


def ejecutar(args: argparse.Namespace) -> int:
    ruta = cliente.resolver_documento(args.documento)
    if ruta.suffix.lower() not in EXTENSIONES:
        consola.error(f'formato no soportado: {ruta.suffix} (usa {", ".join(EXTENSIONES)})')
        return 1
    if not ruta.exists() and not args.no_subir:
        consola.error(f'no existe {ruta}')
        return 1
    stem = cliente.stem(ruta)
    clave = args.clave or f'textract-ec/{ruta.name}'
    p = plan(args, ruta, clave)

    if args.dry_run:
        print('[DRY-RUN · sin llamadas a AWS]', flush=True)
        imprimir_plan(p, args)
        return 0
    modo = cliente.resolver_modo(None)
    if modo != 'online':
        consola.aviso('este extra solo funciona online (LAB_MODO=offline o sin credenciales): mostrando el plan')
        imprimir_plan(p, args)
        return 0
    print(cliente.banner_modo(modo), flush=True)
    return ejecutar_real(p, args, ruta, stem)


def main(argv: list[str] | None = None) -> int:
    args = parsear_args(argv)
    try:
        return ejecutar(args)
    except ErrorAWS as e:
        consola.error(str(e))
        return 2
    except ValueError as e:
        consola.error(str(e))
        return 1
    except KeyboardInterrupt:
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
