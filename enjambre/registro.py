from pathlib import Path

from logcentral_client import get_logger

DIR_LOGS = Path(__file__).resolve().parent.parent / "logs"


def obtener_log(log_dir: Path = DIR_LOGS):
    # Solo errores del propio orquestador; lo de los agentes va a eventos.jsonl (§6).
    log_dir.mkdir(parents=True, exist_ok=True)
    return get_logger("enjambre", log_dir=log_dir)
