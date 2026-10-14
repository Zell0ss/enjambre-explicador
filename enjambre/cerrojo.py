"""
El cerrojo de máquina (D31): un run a la vez, venga de la página, de la cola o
de la línea de órdenes.

Es un `flock` sobre un fichero. Lo suelta el sistema si el proceso muere, así
que no hay cerrojos huérfanos que limpiar a mano. El fichero se crea una vez y
nunca se borra: borrarlo mientras otro proceso lo tiene abierto permitiría que
un tercero creara otro y tomara "el mismo" cerrojo sobre un inodo distinto.
"""

import fcntl
from contextlib import contextmanager
from pathlib import Path

# parent = enjambre/, parent.parent = raíz del repo.
RUTA = Path(__file__).resolve().parent.parent / "cerrojo.lock"


class Ocupado(RuntimeError): ...


@contextmanager
def tomar(ruta: Path | None = None):
    # `None` y no `= RUTA`: un valor por defecto se fija al definir la función
    # y las pruebas no podrían redirigirlo.
    ruta = ruta or RUTA
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Ocupado(f"hay otro run en marcha ({ruta})") from None
        # Sin `try/finally` para el desbloqueo: al cerrar `f` el sistema suelta
        # el flock, también si el cuerpo lanza.
        yield


def ocupado(ruta: Path | None = None) -> bool:
    """Prueba a tomarlo y lo suelta."""
    try:
        with tomar(ruta):
            return False
    except Ocupado:
        return True
