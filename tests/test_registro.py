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
