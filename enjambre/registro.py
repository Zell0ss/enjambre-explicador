import logging
from pathlib import Path

# D44: LogCentral es opcional (solo existe en el servidor del autor). Sin él, `logging` escribe en
# `<log_dir>/enjambre.log`, y un clon nuevo funciona con `pip install -r requirements.txt`.
try:
    from logcentral_client import get_logger
except ImportError:  # no instalado
    get_logger = None

DIR_LOGS = Path(__file__).resolve().parent.parent / "logs"


def obtener_log(log_dir: Path = DIR_LOGS):
    # Solo errores del propio orquestador; lo de los agentes va a eventos.jsonl (§6).
    log_dir.mkdir(parents=True, exist_ok=True)
    if get_logger is not None:
        return get_logger("enjambre", log_dir=log_dir)
    log = logging.getLogger("enjambre")
    log.setLevel(logging.INFO)
    fichero = str((log_dir / "enjambre.log").resolve())
    # Sin repetir el handler si se llama varias veces con la misma carpeta.
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == fichero for h in log.handlers):
        h = logging.FileHandler(fichero, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        log.addHandler(h)
    return log
