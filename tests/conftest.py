"""Configuración común de los tests del taller (100 % offline, sin red, sin credenciales).

- Fija LAB_MODO=offline y NO_COLOR=1 ANTES de importar textract_lab (así ningún test
  puede tocar AWS ni depender del perfil de la máquina).
- Cambia el cwd a la raíz del repo (los labs se ejecutan desde ahí).
- Limpia al final los archivos que los tests dejaron en salida/ (y el acumulado de costos
  si algún test lo creara por error).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DIR_DOCS = RAIZ / 'docs'
DIR_FIXTURES = RAIZ / 'fixtures'
DIR_SALIDA = RAIZ / 'salida'
DIR_GROUND_TRUTH = DIR_DOCS / 'ground_truth'

# Entorno blindado: se aplica al importar conftest, antes de cualquier import de la librería.
os.environ['LAB_MODO'] = 'offline'
os.environ['NO_COLOR'] = '1'
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
# Un perfil inexistente a propósito: si algún código intentara crear una sesión real,
# fallaría con ProfileNotFound en vez de usar el perfil 'default' de la máquina.
os.environ.setdefault('AWS_PROFILE', 'taller-tests-sin-credenciales')
os.chdir(RAIZ)
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from textract_lab import cliente, queries  # noqa: E402  (después de fijar el entorno)

DOCUMENTOS = {
    'mini': 'docs/mini.png',
    'factura_limpia': 'docs/factura_limpia.png',
    'factura_trampa': 'docs/factura_trampa.png',
    'factura_foto': 'docs/factura_foto.jpg',
    'formulario_inscripcion': 'docs/formulario_inscripcion.png',
    'orden_compra_prosa': 'docs/orden_compra_prosa.png',
    'recibo_restaurante': 'docs/extra/recibo_restaurante.png',
}


def _archivos_salida() -> set[Path]:
    if not DIR_SALIDA.exists():
        return set()
    return {p for p in DIR_SALIDA.rglob('*') if p.is_file()}


def _acumulado_costos() -> dict:
    """Contadores de cache/.costos.json ({} si no existe): en offline no deben moverse."""
    ruta = RAIZ / 'cache' / '.costos.json'
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


@pytest.fixture(scope='session', autouse=True)
def entorno_offline():
    """Garantiza el entorno offline durante toda la sesión y limpia salida/ al terminar."""
    assert os.environ.get('LAB_MODO') == 'offline'
    assert cliente.resolver_modo() == 'offline'
    previos = _archivos_salida()
    existia_salida = DIR_SALIDA.exists()
    costos_previos = (RAIZ / 'cache' / '.costos.json').exists()
    # cache/ existe en el repo desde que se grabaron los fixtures reales contra AWS: no basta con
    # exigir que no aparezca, hay que exigir que el acumulado no CREZCA durante los tests.
    acumulado_previo = _acumulado_costos()
    yield
    # Limpieza: solo lo que apareció durante los tests.
    for p in _archivos_salida() - previos:
        try:
            p.unlink()
        except OSError:
            pass
    if not existia_salida and DIR_SALIDA.exists():
        for d in sorted((p for p in DIR_SALIDA.rglob('*') if p.is_dir()), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            DIR_SALIDA.rmdir()
        except OSError:
            pass
    if not costos_previos and (RAIZ / 'cache' / '.costos.json').exists():
        # En offline nunca debería registrarse costo: si apareció, algo llamó a AWS.
        (RAIZ / 'cache' / '.costos.json').unlink()
        pytest.fail('apareció cache/.costos.json durante los tests: algún test llamó a AWS')
    acumulado_final = _acumulado_costos()
    if acumulado_final != acumulado_previo:
        pytest.fail('cambió el acumulado de cache/.costos.json durante los tests '
                    f'({acumulado_previo} → {acumulado_final}): algún test llamó a AWS')


@pytest.fixture(scope='session')
def raiz() -> Path:
    return RAIZ


@pytest.fixture(scope='session')
def documentos() -> dict[str, str]:
    return dict(DOCUMENTOS)


@pytest.fixture(scope='session')
def cargar_fixture():
    """cargar_fixture('factura_limpia/detect_document_text') → dict crudo del fixture."""

    def _cargar(clave: str) -> dict:
        datos = cliente.leer_json(cliente.ruta_fixture(clave))
        if datos is None:
            pytest.fail(f'falta el fixture fixtures/{clave}.json (regenera con tools/gen_fixtures_sinteticos.py)')
        return datos

    return _cargar


@pytest.fixture(scope='session')
def resp_texto(cargar_fixture):
    """resp_texto('factura_limpia') → respuesta de DetectDocumentText."""
    return lambda doc: cargar_fixture(f'{doc}/detect_document_text')


@pytest.fixture(scope='session')
def resp_estructura(cargar_fixture):
    """resp_estructura('factura_limpia') → respuesta de AnalyzeDocument FORMS+LAYOUT+TABLES."""
    return lambda doc: cargar_fixture(f'{doc}/analyze_document__FORMS_LAYOUT_TABLES')


@pytest.fixture(scope='session')
def resp_queries(cargar_fixture):
    """resp_queries('factura_limpia') → respuesta de AnalyzeDocument QUERIES (set del taller)."""

    def _cargar(doc: str) -> dict:
        set_q = queries.QUERIES_ORDEN_COMPRA if doc == 'orden_compra_prosa' else queries.QUERIES_FACTURA
        clave = cliente.clave_llamada(DOCUMENTOS.get(doc, doc), 'analyze_document', ['QUERIES'], set_q)
        return cargar_fixture(clave)

    return _cargar


@pytest.fixture(scope='session')
def ground_truth():
    """ground_truth('factura_limpia') → dict de docs/ground_truth/<doc>.json."""

    def _cargar(doc: str) -> dict:
        ruta = DIR_GROUND_TRUTH / f'{doc}.json'
        if not ruta.exists():
            pytest.fail(f'falta {ruta.relative_to(RAIZ)}')
        return json.loads(ruta.read_text(encoding='utf-8'))

    return _cargar


@pytest.fixture(scope='session')
def ejecutar():
    """ejecutar('01_texto.py', 'docs/mini.png', '--offline') → CompletedProcess (cwd = raíz, entorno offline)."""

    def _ejecutar(*args: str, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update({'LAB_MODO': 'offline', 'NO_COLOR': '1', 'PYTHONIOENCODING': 'utf-8',
                    'AWS_PROFILE': 'taller-tests-sin-credenciales'})
        return subprocess.run([sys.executable, *args], cwd=str(cwd or RAIZ), env=env,
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)

    return _ejecutar
