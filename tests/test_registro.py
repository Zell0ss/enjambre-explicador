import json
from pathlib import Path

from enjambre.registro import obtener_log


def test_logger_escribe_json_con_source(tmp_path: Path):
    log = obtener_log(tmp_path)
    log.error("prueba")
    lineas = (tmp_path / "enjambre.log").read_text().splitlines()
    entrada = json.loads(lineas[-1])
    assert entrada["source"] == "enjambre"
    assert entrada["level"] == "ERROR"
    assert entrada["message"] == "prueba"


# --- D44 (anexo 2026-10-18, Tarea 32): normativa, tal cual ---

import importlib
import sys


def test_sin_logcentral_cae_a_logging(tmp_path, monkeypatch):
    import enjambre.registro as registro
    try:
        with monkeypatch.context() as m:       # no `monkeypatch.undo()`: desharía también lo del conftest
            m.setitem(sys.modules, "logcentral_client", None)   # el import falla
            r = importlib.reload(registro)
            log = r.obtener_log(tmp_path)
            r.obtener_log(tmp_path).warning("hola")             # segunda llamada: sin handlers repetidos
            for h in log.handlers:
                h.flush()
            assert (tmp_path / "enjambre.log").read_text().count("hola") == 1
    finally:
        importlib.reload(registro)
