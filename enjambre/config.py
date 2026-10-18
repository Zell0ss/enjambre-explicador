"""
Configuración por entorno (D44): variable de entorno > `.env` del repo > valor por
defecto genérico. Sin rutas ni IPs de ninguna máquina en el código: lo propio de cada máquina va
en el `.env` (o en el entorno), y un clon nuevo funciona sin nada.

Todo se resuelve **en cada llamada**, nunca al importar: un valor leído al importar (o
puesto como valor por defecto de una firma) no se puede redirigir en pruebas, que es el
fallo que tuvo `cerrojo.tomar` (R2 de la revisión de H1).
"""

import ipaddress
import os
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
RUTA_ENV = RAIZ_REPO / ".env"  # las pruebas lo redirigen (conftest)
VARIABLES = ("ENJAMBRE_NOTAS", "ENJAMBRE_COPIAS", "ENJAMBRE_RAIZ_LOCAL", "ENJAMBRE_HOST", "ENJAMBRE_PUERTO")


def cargar_env(ruta: Path | None = None) -> dict[str, str]:
    """`CLAVE=valor` por línea; sin fichero, vacío. Ignora comentarios y comillas."""
    try:
        lineas = (ruta or RUTA_ENV).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    env = {}
    for linea in lineas:
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        clave, sep, valor = linea.removeprefix("export ").partition("=")
        if not sep:
            continue
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        env[clave.strip()] = valor
    return env


def valor(nombre: str) -> str | None:
    """Entorno > `.env` > `None`. Un valor vacío cuenta como no puesto."""
    v = os.environ.get(nombre)
    if v is None or not v.strip():
        v = cargar_env().get(nombre)
    return v.strip() if v and v.strip() else None


def _ruta(nombre: str, defecto: Path) -> Path:
    v = valor(nombre)
    ruta = Path(v).expanduser() if v else defecto
    # Una ruta relativa se toma desde la raíz del repo, no desde donde se lance el comando.
    return ruta if ruta.is_absolute() else RAIZ_REPO / ruta


def raiz_notas() -> Path:
    return _ruta("ENJAMBRE_NOTAS", RAIZ_REPO / "notas")


def raiz_copias() -> Path:
    return _ruta("ENJAMBRE_COPIAS", RAIZ_REPO / "copias")


def raiz_local() -> Path:
    return _ruta("ENJAMBRE_RAIZ_LOCAL", Path.home())


def host() -> str:
    h = valor("ENJAMBRE_HOST") or "127.0.0.1"
    try:
        todas = ipaddress.ip_address(h.strip("[]")).is_unspecified
    except ValueError:
        todas = False  # un nombre de host, no una IP
    if todas:
        # D12: la pantalla lanza runs que gastan; nunca en todas las interfaces.
        raise ValueError(f"ENJAMBRE_HOST={h!r} escucharía en todas las interfaces (D12)")
    return h


def puerto() -> int:
    v = valor("ENJAMBRE_PUERTO") or "8790"
    try:
        p = int(v)
    except ValueError:
        raise ValueError(f"ENJAMBRE_PUERTO no es un número: {v!r}") from None
    if not 1 <= p <= 65535:
        raise ValueError(f"ENJAMBRE_PUERTO fuera de rango: {p}")
    return p
