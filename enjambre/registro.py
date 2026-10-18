import json
import logging
from datetime import datetime
from pathlib import Path

# D44: LogCentral es opcional (solo existe en el servidor del autor). Sin él, `logging` escribe en
# `<log_dir>/enjambre.log`, y un clon nuevo funciona con `pip install -r requirements.txt`.
try:
    from logcentral_client import get_logger
except ImportError:  # no instalado
    get_logger = None



class _FormatoJson(logging.Formatter):
    """Una línea JSON por entrada, con los mismos campos que LogCentral (`source`,
    `level`, `message`): quien lea `logs/enjambre.log` no nota si LogCentral está."""

    def format(self, record: logging.LogRecord) -> str:
        entrada = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "source": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entrada["exception"] = self.formatException(record.exc_info)
        return json.dumps(entrada, ensure_ascii=False)


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
        h.setFormatter(_FormatoJson())
        log.addHandler(h)
    return log
