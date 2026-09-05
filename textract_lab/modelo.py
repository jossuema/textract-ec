"""Modelo de datos del taller, desacoplado del proveedor.

`Campo`, `Tabla` y `Resultado` son dataclasses puras (sin boto3) para que el
mismo modelo pueda alimentarse mañana con Textract, Bedrock Data Automation
o un LLM multimodal sin reescribir los validadores.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

ORIGENES = ('FORMS', 'TABLES', 'QUERIES', 'TEXTO', 'LLM', 'NORMALIZADO')
ESTADOS = ('OK', 'REVISAR')


@dataclass
class Campo:
    """Un valor extraído con su confianza (0-100) y la fuente de la que salió."""

    valor: str
    confianza: float
    origen: str  # uno de ORIGENES

    def vacio(self) -> bool:
        """True si el campo no tiene valor útil."""
        return not str(self.valor).strip()


@dataclass
class Tabla:
    """Tabla como matriz de strings; la primera fila suele ser la cabecera."""

    filas: list[list[str]]
    confianza: float
    titulo: str = ''

    @property
    def cabecera(self) -> list[str]:
        return self.filas[0] if self.filas else []

    @property
    def datos(self) -> list[list[str]]:
        return self.filas[1:] if self.filas else []


@dataclass
class Resultado:
    """Salida final del pipeline para un documento."""

    documento: str
    tipo_documento: str
    campos: dict[str, Campo]
    tablas: list[Tabla]
    alertas: list[str]
    estado: str  # 'OK' | 'REVISAR'
    paginas: int = 1
    costo_usd: float = 0.0
    modo: str = 'offline'
    extra: dict = field(default_factory=dict)  # evidencias, avisos, etc.

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def desde_dict(cls, d: dict) -> 'Resultado':
        """Reconstruye un Resultado desde el dict de to_dict() (por ejemplo, un JSON guardado)."""
        campos = {k: Campo(**v) if isinstance(v, dict) else v for k, v in d.get('campos', {}).items()}
        tablas = [Tabla(**t) if isinstance(t, dict) else t for t in d.get('tablas', [])]
        return cls(
            documento=d.get('documento', ''),
            tipo_documento=d.get('tipo_documento', 'desconocido'),
            campos=campos,
            tablas=tablas,
            alertas=list(d.get('alertas', [])),
            estado=d.get('estado', 'REVISAR'),
            paginas=int(d.get('paginas', 1)),
            costo_usd=float(d.get('costo_usd', 0.0)),
            modo=d.get('modo', 'offline'),
            extra=dict(d.get('extra', {})),
        )


def como_campo(valor, confianza: float = 100.0, origen: str = 'TEXTO') -> Campo:
    """Convierte un str/número/Campo en Campo (útil para validar JSON de un LLM)."""
    if isinstance(valor, Campo):
        return valor
    if valor is None:
        return Campo('', 0.0, origen)
    return Campo(str(valor), float(confianza), origen)
