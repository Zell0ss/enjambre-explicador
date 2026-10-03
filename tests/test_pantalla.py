import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from enjambre.pantalla import crear_servidor


@pytest.fixture
def srv(tmp_path):
    salidas, est = tmp_path / "salidas", tmp_path / "pantalla"
    run = salidas / "agora" / "r1"
    run.mkdir(parents=True); est.mkdir()
    (est / "index.html").write_text("<h1>hola</h1>")
    (run / "mapa.md").write_text("# Mapa")
    (run / "eventos.jsonl").write_text('{"t":"2026-10-03T00:00:00.000","run":"r1","tipo":"run_inicio"}\n')
    (tmp_path / "secreto.txt").write_text("NO")
    s = crear_servidor("127.0.0.1", 0, salidas, est)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}", run
    s.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode()


def test_index_y_runs(srv):
    base, _ = srv
    assert get(base + "/")[1] == "<h1>hola</h1>"
    [r] = json.loads(get(base + "/api/runs")[1])
    assert (r["repo"], r["run"], r["motivo"]) == ("agora", "r1", None)


def test_eventos_y_fichero(srv):
    base, _ = srv
    assert '"run_inicio"' in get(base + "/api/eventos/agora/r1.jsonl")[1]
    assert get(base + "/api/fichero/agora/r1/mapa.md")[1] == "# Mapa"


@pytest.mark.parametrize("ruta", [
    "/api/fichero/agora/r1/../../../secreto.txt",
    "/api/fichero/agora/r1/%2e%2e/%2e%2e/%2e%2e/secreto.txt",
    "/api/fichero/agora/r1/%2E%2E%2F%2E%2E%2F%2E%2E%2Fsecreto.txt",
    "/static/../secreto.txt",
    "/api/eventos/../../secreto.txt",
])
def test_traversal_es_404(srv, ruta):
    base, _ = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + ruta)
    assert e.value.code == 404


def test_directo_emite_lineas_nuevas_y_cierra_en_run_fin(srv):
    base, run = srv
    recibidas = []

    def leer():
        with urllib.request.urlopen(base + "/api/directo/agora/r1", timeout=10) as r:
            for linea in r:
                if linea.startswith(b"data: "):
                    recibidas.append(json.loads(linea[6:]))

    h = threading.Thread(target=leer); h.start()
    time.sleep(0.8)
    with open(run / "eventos.jsonl", "a") as f:
        f.write('{"t":"x","run":"r1","tipo":"estado","agente":"cartografo","estado":"leyen')   # línea a medias
        f.flush(); time.sleep(0.7)
        f.write('do"}\n{"t":"y","run":"r1","tipo":"run_fin","motivo":"aprobado"}\n')
    h.join(timeout=5)
    assert not h.is_alive()
    assert [e["tipo"] for e in recibidas] == ["run_inicio", "estado", "run_fin"]
    assert recibidas[1]["estado"] == "leyendo"
