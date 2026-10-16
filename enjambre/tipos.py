"""
Modelo de datos compartido entre el orquestador, los agentes y la pantalla.

Sin lógica: solo las formas de dato que cruzan los módulos (D-pendiente: ver
spec §... del enjambre-explicador). `Contexto` referencia `Eventos` (para que
cualquier pieza con un `Contexto` pueda emitir) y `Lanzar` referencia `Agente`;
ambos imports viven solo bajo TYPE_CHECKING para evitar el ciclo tipos<->agentes
y tipos<->eventos (ninguno de los dos necesita los tipos en tiempo de ejecución,
solo para anotar).
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Literal

if TYPE_CHECKING:
    from enjambre.agentes import Agente
    from enjambre.eventos import Eventos


EstadoFinal = Literal["terminado", "bloqueado", "error", "timeout"]


@dataclass
class Resultado:
    """Resultado de lanzar un agente (una instancia, un encargo)."""
    estado_final: EstadoFinal
    respuesta: str = ""
    modelo_real: str | None = None
    duracion_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    coste_usd: float = 0.0
    num_herramientas: int = 0
    num_turns: int = 0  # De `ResultMessage.num_turns` (ver lanzador.Traductor.resultado()).


@dataclass
class Contexto:
    """Contexto compartido que recibe cada lanzamiento de agente."""
    repo: Path
    salida: Path
    eventos: "Eventos"
    timeout_s: float = 600
    max_turns: int = 60


# lanzar(agente, instancia, encargo, ctx) -> Resultado
Lanzar = Callable[["Agente", str, str, Contexto], Awaitable[Resultado]]


@dataclass
class Lectura:
    """Resultado de leer una fuente (fase 3): lo que `leer` devuelve a la cola,
    al aviso y a la línea de órdenes."""
    fuente: str
    nombre: str
    commit: str | None
    run: str | None  # None si no se lanzó nada (sin_cambios)
    salida: Path | None
    motivo: str  # el de run_fin, o "sin_cambios"
    vueltas: int
    coste_usd: float  # lo gastado EN ESTA lectura: una continuación no cuenta lo anterior (D24, D30)
    nota: Path | None
    continuado: bool = False
    # D39: cuándo se renueva el límite de sesión, si el run paró por eso (hora local de seb01).
    reintentar_a: datetime | None = None
