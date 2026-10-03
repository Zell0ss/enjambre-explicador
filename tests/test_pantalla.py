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


def test_directo_cierra_hilo_si_cliente_desconecta_sin_run_fin(srv):
    """Important 1 (revisión de seguridad del commit df61f0d): sin esto, un
    cliente que se desconecta de un run que nunca llega a `run_fin` deja el
    hilo de sondeo vivo para siempre. El keepalive (`: \n\n` cada ~1s de
    inactividad) debe notar el socket cerrado y terminar el hilo solo."""
    base, _ = srv
    hilos_antes = threading.active_count()

    conexion = urllib.request.urlopen(base + "/api/directo/agora/r1", timeout=10)
    conexion.readline()  # consume run_inicio: el hilo ya está en el bucle de sondeo
    conexion.close()  # el cliente se va sin esperar un run_fin que nunca llega

    limite = time.time() + 5
    while threading.active_count() > hilos_antes and time.time() < limite:
        time.sleep(0.2)
    assert threading.active_count() <= hilos_antes


def test_directo_tolera_caracter_multibyte_partido(srv):
    """Important 2 (revisión df61f0d): un lector concurrente puede partir un
    carácter UTF-8 multibyte entre dos escrituras (Foco de revisión #3).
    Partimos la "ó" (b"\\xc3\\xb3") justo entre sus dos bytes, dentro de una
    línea JSON que por lo demás está completa."""
    base, run = srv
    recibidas = []

    def leer():
        with urllib.request.urlopen(base + "/api/directo/agora/r1", timeout=10) as r:
            for linea in r:
                if linea.startswith(b"data: "):
                    evento = json.loads(linea[6:])
                    recibidas.append(evento)
                    if evento["tipo"] == "run_fin":
                        return

    # Hilo lector como daemon: si algo en el servidor se queda bloqueado
    # (precisamente el fallo que este test comprueba que NO ocurre), que no
    # cuelgue el proceso entero de pytest a la salida -- solo este test.
    h = threading.Thread(target=leer, daemon=True); h.start()
    time.sleep(0.6)

    # ensure_ascii=False: json.dumps por defecto escapa "ó" a "ó" (puro
    # ASCII), con lo que nunca habría bytes UTF-8 multibyte que partir.
    linea = json.dumps({"t": "x", "run": "r1", "tipo": "aviso", "texto": "leyó"}, ensure_ascii=False)
    datos = linea.encode("utf-8") + b"\n"
    corte = datos.index("ó".encode("utf-8"))  # primer byte de la "ó" multibyte
    with open(run / "eventos.jsonl", "ab") as f:
        f.write(datos[: corte + 1])  # corta justo tras el primer byte de "ó"
        f.flush(); time.sleep(0.7)
        f.write(datos[corte + 1:])
        f.write(json.dumps({"t": "y", "run": "r1", "tipo": "run_fin", "motivo": "aprobado"}).encode() + b"\n")

    h.join(timeout=5)
    assert not h.is_alive()
    assert [e["tipo"] for e in recibidas] == ["run_inicio", "aviso", "run_fin"]
    assert recibidas[1]["texto"] == "leyó"


def test_directo_tolera_linea_json_no_objeto(srv):
    """Minor (re-revisión de 15b9b3a): mismo fallo que Important 3 pero en el
    camino del SSE -- una línea JSON válida que no es un objeto (p.ej. una
    lista) lanzaba AttributeError en `.get("tipo")`, cortando el stream sin
    llegar a `run_fin`."""
    base, run = srv
    recibidas = []

    def leer():
        with urllib.request.urlopen(base + "/api/directo/agora/r1", timeout=10) as r:
            for linea in r:
                if linea.startswith(b"data: "):
                    recibidas.append(json.loads(linea[6:]))

    h = threading.Thread(target=leer, daemon=True); h.start()
    time.sleep(0.6)
    with open(run / "eventos.jsonl", "a") as f:
        f.write("[1,2,3]\n")
        f.write('{"t":"y","run":"r1","tipo":"run_fin","motivo":"aprobado"}\n')
    h.join(timeout=5)
    assert not h.is_alive()
    assert recibidas[0]["tipo"] == "run_inicio"
    assert recibidas[-1]["tipo"] == "run_fin"  # la línea [1,2,3] no tumbó el stream


def test_runs_omite_eventos_corrupto_sin_tumbar_la_lista(srv):
    """Important 3 (revisión df61f0d): un `eventos.jsonl` cuya primera línea
    es JSON válido pero no un objeto (una lista), o que tiene bytes UTF-8
    inválidos, no debe tumbar /api/runs entero -- el run sano debe seguir
    apareciendo."""
    base, run = srv
    (run.parent / "r2").mkdir()
    (run.parent / "r2" / "eventos.jsonl").write_text("[1,2,3]\n")
    (run.parent / "r3").mkdir()
    (run.parent / "r3" / "eventos.jsonl").write_bytes(b'{"t":"x"\xff\xfe\n')

    status, cuerpo = get(base + "/api/runs")
    assert status == 200
    runs = json.loads(cuerpo)
    assert any(r["run"] == "r1" for r in runs)


def test_byte_nulo_en_ruta_es_404(srv):
    """Minor (revisión df61f0d): un byte nulo en la ruta hacía que
    `Path.__truediv__`/`resolve()` lanzaran `ValueError: embedded null
    byte` sin capturar, tumbando el hilo en vez de responder 404."""
    base, _ = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/fichero/agora/r1/%00")
    assert e.value.code == 404
