import json
import threading
from pathlib import Path

from enjambre.eventos import Eventos


def test_emitir_escribe_una_linea_json(tmp_path: Path):
    ev = Eventos(tmp_path / "eventos.jsonl", run="agora-1")
    e = ev.emitir("estado", agente="cartografo", estado="leyendo", detalle="README.md")
    ev.cerrar()
    linea = json.loads((tmp_path / "eventos.jsonl").read_text().splitlines()[0])
    assert linea == e
    assert linea["run"] == "agora-1" and linea["tipo"] == "estado" and linea["agente"] == "cartografo"
    assert "T" in linea["t"]


def test_eventos_de_run_no_llevan_agente(tmp_path: Path):
    ev = Eventos(tmp_path / "e.jsonl", run="r")
    assert "agente" not in ev.emitir("run_inicio", repo="/data/agora")


def test_concurrencia_no_mezcla_lineas(tmp_path: Path):
    ev = Eventos(tmp_path / "e.jsonl", run="r")
    largo = "x" * 5000

    def escribir(i):
        for _ in range(200):
            ev.emitir("herramienta", agente=f"lector-de-pieza:{i}", herramienta="Read", detalle=largo)

    hilos = [threading.Thread(target=escribir, args=(i,)) for i in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    ev.cerrar()
    lineas = (tmp_path / "e.jsonl").read_text().splitlines()
    assert len(lineas) == 1600
    assert all(json.loads(l)["detalle"] == largo for l in lineas)
