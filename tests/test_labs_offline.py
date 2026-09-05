"""Ejecuta cada lab (00-05, checkpoints) con --offline vía subprocess: exit 0 y texto clave en la salida.

Si un script todavía no existe, el test FALLA con un mensaje claro (SI_FALTA = 'fail') o se
SALTA (SI_FALTA = 'skip'); cambia la constante según la fase del kit.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from conftest import RAIZ

SI_FALTA = 'skip'  # 'fail' | 'skip' — qué hacer cuando falta un lab que escribe otro agente

PROPIETARIOS = {
    '00_check.py': 'labs-a', '01_texto.py': 'labs-a', '02_formulario_tabla.py': 'labs-a',
    '03_inteligente.py': 'labs-b', '04_sistema.py': 'labs-b', '05_bonus_bedrock.py': 'labs-b',
    'checkpoints/lab1/01_texto.py': 'labs-a', 'checkpoints/lab2/02_formulario_tabla.py': 'labs-a',
    'checkpoints/lab3/03_inteligente.py': 'labs-b',
}
LABS_PRINCIPALES = ['00_check.py', '01_texto.py', '02_formulario_tabla.py', '03_inteligente.py', '04_sistema.py',
                    '05_bonus_bedrock.py']
_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def requiere(script: str) -> Path:
    ruta = RAIZ / script
    if not ruta.exists():
        msg = f'falta {script} (lo escribe el agente [{PROPIETARIOS.get(script, "?")}]); no se puede probar el lab'
        pytest.skip(msg) if SI_FALTA == 'skip' else pytest.fail(msg)
    return ruta


def _salida(r) -> str:
    return (r.stdout or '') + '\n' + (r.stderr or '')


def _explicar(script, args, r) -> str:
    return (f'{script} {" ".join(args)} → exit {r.returncode}\n--- stdout ---\n{r.stdout[-3000:]}\n'
            f'--- stderr ---\n{r.stderr[-2000:]}')


# (script, args, textos que deben aparecer, globs de archivos que deben existir tras ejecutar)
CASOS = [
    ('00_check.py', ['--offline'], ['OFFLINE', 'fixtures'], []),
    ('01_texto.py', ['docs/factura_limpia.png', '--offline'], ['1790456129001'], []),
    ('01_texto.py', ['docs/mini.png', '--offline', '--json'], ['Cuenca'], []),
    ('01_texto.py', ['docs/factura_foto.jpg', '--offline', '--overlay'], ['overlay'], []),
    ('02_formulario_tabla.py', ['docs/factura_limpia.png', '--offline'], ['944.84', 'Precio Total'], []),
    ('02_formulario_tabla.py', ['docs/factura_limpia.png', '--offline', '--csv'], ['csv'], ['salida/factura_limpia*.csv']),
    ('02_formulario_tabla.py', ['docs/formulario_inscripcion.png', '--offline'], ['[X]', 'Ana Lucía'], []),
    ('03_inteligente.py', ['docs/factura_limpia.png', '--offline'], ['OK', 'QUERIES', 'FORMS'], []),
    ('03_inteligente.py', ['docs/factura_trampa.png', '--offline'],
     ['REVISAR', 'ítems no suman el subtotal', 'clave de acceso con dígito verificador inválido'], []),
    # La foto real se lee bien: OK y sin alertas. El momento "alerta" lo da factura_trampa (arriba).
    ('03_inteligente.py', ['docs/factura_foto.jpg', '--offline'], ['OK', '944.84', 'QUERIES', 'FORMS'], []),
    ('03_inteligente.py', ['docs/factura_limpia.png', '--offline', '--sin-queries'], ['OK'], []),
    ('03_inteligente.py', ['docs/factura_limpia.png', '--offline', '--json'], [], []),
    ('04_sistema.py', ['docs/', '--offline'], ['OK', 'REVISAR', 'factura_limpia', 'formulario_inscripcion'],
     ['salida/resumen.json', 'salida/factura_limpia.validado.json']),
    ('04_sistema.py', ['docs/extra', '--offline'], ['recibo_restaurante'], []),
    ('05_bonus_bedrock.py', ['docs/orden_compra_prosa.png', '--offline', '--modelo', 'haiku'],
     ['PROVEEDOR', '1221.2'], []),
    ('05_bonus_bedrock.py', ['docs/factura_foto.jpg', '--offline', '--modelo', 'nova'], ['2026-09-01'], []),
    ('checkpoints/lab1/01_texto.py', ['docs/factura_limpia.png', '--offline'], ['1790456129001'], []),
    ('checkpoints/lab2/02_formulario_tabla.py', ['docs/factura_limpia.png', '--offline'], ['coincide'], []),
    ('checkpoints/lab3/03_inteligente.py', ['docs/factura_trampa.png', '--offline'], ['REVISAR'], []),
]


@pytest.mark.parametrize('script, args, textos, globs', CASOS,
                         ids=[f'{s} {" ".join(a)}' for s, a, _, _ in CASOS])
def test_lab_offline(script, args, textos, globs, ejecutar):
    requiere(script)
    r = ejecutar(script, *args)
    assert r.returncode == 0, _explicar(script, args, r)
    salida = _salida(r)
    for texto in textos:
        assert texto in salida, f'no aparece {texto!r}\n' + _explicar(script, args, r)
    for patron in globs:
        assert list(RAIZ.glob(patron)), f'no se generó {patron}\n' + _explicar(script, args, r)
    assert '\x1b[' not in salida, 'con NO_COLOR=1 no debe haber códigos ANSI'


@pytest.mark.parametrize('script', LABS_PRINCIPALES)
def test_banner_offline_en_primera_linea(script, ejecutar):
    """Contrato §5: la primera línea de cada script es el banner de modo."""
    requiere(script)
    args = ['docs/factura_limpia.png', '--offline'] if script not in ('00_check.py', '04_sistema.py') else ['--offline']
    if script == '05_bonus_bedrock.py':
        args = ['docs/orden_compra_prosa.png', '--offline']
    r = ejecutar(script, *args)
    assert r.returncode == 0, _explicar(script, args, r)
    lineas = [ln for ln in _ANSI.sub('', r.stdout).splitlines() if ln.strip()]
    # 04_sistema.py trabaja por defecto con cache/ + fixtures/ y lo anuncia como [LOCAL · ...]; el resto [OFFLINE · ...].
    assert lineas and lineas[0].startswith(('[OFFLINE', '[LOCAL')), f'primera línea: {lineas[:1]}'
    assert 'fixtures' in lineas[0]


@pytest.mark.parametrize('script', LABS_PRINCIPALES + ['checkpoints/lab2/02_formulario_tabla.py'])
def test_help_sale_cero(script, ejecutar):
    requiere(script)
    r = ejecutar(script, '--help')
    assert r.returncode == 0, _explicar(script, ['--help'], r)
    assert '--offline' in r.stdout or '--online' in r.stdout


@pytest.mark.parametrize('script', ['01_texto.py', '03_inteligente.py'])
def test_offline_y_online_son_excluyentes(script, ejecutar):
    requiere(script)
    r = ejecutar(script, 'docs/factura_limpia.png', '--offline', '--online')
    assert r.returncode != 0


def test_documento_sin_fixture_falla_con_mensaje(ejecutar):
    requiere('01_texto.py')
    r = ejecutar('01_texto.py', 'docs/no_existe.png', '--offline')
    assert r.returncode != 0
    assert 'fixture' in _salida(r).lower() or 'no existe' in _salida(r).lower()


def test_scripts_funcionan_desde_otro_cwd(ejecutar, tmp_path):
    """Contrato §5: los scripts deben funcionar aunque el cwd no sea la raíz del repo."""
    requiere('00_check.py')
    requiere('01_texto.py')
    r = ejecutar(str(RAIZ / '00_check.py'), '--offline', cwd=tmp_path)
    assert r.returncode == 0, _explicar('00_check.py', ['--offline'], r)
    r = ejecutar(str(RAIZ / '01_texto.py'), 'docs/mini.png', '--offline', cwd=tmp_path)
    assert r.returncode == 0, _explicar('01_texto.py', ['docs/mini.png', '--offline'], r)
    assert 'Cuenca' in _salida(r)


def test_04_sistema_resumen_json(ejecutar):
    requiere('04_sistema.py')
    r = ejecutar('04_sistema.py', 'docs/', '--offline')
    assert r.returncode == 0, _explicar('04_sistema.py', ['docs/', '--offline'], r)
    resumen = json.loads((RAIZ / 'salida' / 'resumen.json').read_text(encoding='utf-8'))
    filas = resumen if isinstance(resumen, list) else resumen.get('documentos') or list(resumen.values())
    assert filas
    texto = json.dumps(filas, ensure_ascii=False)
    for stem in ('factura_limpia', 'factura_trampa', 'formulario_inscripcion', 'orden_compra_prosa', 'mini'):
        assert stem in texto, f'{stem} no está en salida/resumen.json'
    validado = json.loads((RAIZ / 'salida' / 'factura_trampa.validado.json').read_text(encoding='utf-8'))
    assert validado['estado'] == 'REVISAR' and len(validado['alertas']) == 2


def test_04_sistema_documento_sin_fixture_es_sin_datos(ejecutar, tmp_path):
    requiere('04_sistema.py')
    carpeta = tmp_path / 'docs_prueba'
    carpeta.mkdir()
    shutil.copy(RAIZ / 'docs' / 'mini.png', carpeta / 'mini.png')
    shutil.copy(RAIZ / 'docs' / 'mini.png', carpeta / 'documento_sin_fixture.png')
    r = ejecutar('04_sistema.py', str(carpeta), '--offline')
    assert r.returncode == 0, _explicar('04_sistema.py', [str(carpeta), '--offline'], r)
    assert 'SIN DATOS' in _salida(r)
    assert 'mini' in _salida(r)


def test_05_bonus_offline_muestra_queries_vacias_y_json(ejecutar):
    requiere('05_bonus_bedrock.py')
    r = ejecutar('05_bonus_bedrock.py', 'docs/orden_compra_prosa.png', '--offline', '--modelo', 'haiku')
    assert r.returncode == 0, _explicar('05_bonus_bedrock.py', ['docs/orden_compra_prosa.png', '--offline'], r)
    salida = _salida(r)
    for alias in ('PROVEEDOR', 'TOTAL_COMPRA', 'CANT_MONITORES'):
        assert alias in salida
    assert 'Tecnología Andina Ejemplo' in salida
    assert 'usage' in salida.lower() or 'tokens' in salida.lower()


def _instantanea_cache() -> tuple[dict, set[str]]:
    """(contadores de cache/.costos.json, inventario de archivos de cache/). Ambos deben quedar igual."""
    dir_cache = RAIZ / 'cache'
    ruta_costos = dir_cache / '.costos.json'
    contadores = json.loads(ruta_costos.read_text(encoding='utf-8')) if ruta_costos.exists() else {}
    inventario = {str(p.relative_to(RAIZ)) for p in dir_cache.rglob('*') if p.is_file()} if dir_cache.exists() else set()
    return contadores, inventario


def test_ningun_lab_llama_a_aws_en_offline(ejecutar):
    """En offline ningún lab AÑADE llamadas: ni costo acumulado ni entradas nuevas en cache/.

    cache/ existe en el repo desde que se grabaron los fixtures reales contra AWS (16 llamadas,
    $0.3955 el 2026-09-04), así que no vale con exigir que no exista: lo que se vigila es que
    el contador de cache/.costos.json y el inventario de cache/ no se muevan al correr los labs.
    """
    corridas = [('01_texto.py', ['docs/factura_limpia.png', '--offline']),
                ('02_formulario_tabla.py', ['docs/formulario_inscripcion.png', '--offline']),
                ('03_inteligente.py', ['docs/factura_foto.jpg', '--offline']),
                ('04_sistema.py', ['docs/', '--offline']),
                ('05_bonus_bedrock.py', ['docs/orden_compra_prosa.png', '--offline', '--modelo', 'haiku'])]
    corridas = [(s, a) for s, a in corridas if (RAIZ / s).exists()]
    if not corridas:
        pytest.skip('todavía no hay ningún lab que ejecutar')

    contadores_antes, inventario_antes = _instantanea_cache()
    for script, args in corridas:
        r = ejecutar(script, *args)
        assert r.returncode == 0, _explicar(script, args, r)
    contadores_despues, inventario_despues = _instantanea_cache()

    assert contadores_despues == contadores_antes, (
        f'cambió el acumulado de cache/.costos.json: {contadores_antes} → {contadores_despues}; '
        'algún lab llamó a AWS estando en offline')
    assert inventario_despues == inventario_antes, (
        f'aparecieron/desaparecieron entradas en cache/: {inventario_despues ^ inventario_antes}')
