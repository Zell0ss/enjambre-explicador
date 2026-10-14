from datetime import datetime
from pathlib import Path

import pytest

from enjambre.cola import encolar, fallidas, noche, pendientes
from enjambre.fuente import FuenteInvalida, GitFallo
from enjambre.tipos import Lectura

A, B, C = (f"https://github.com/x/{n}" for n in ("a", "b", "c"))


def _encola(raiz, *fuentes):
    for i, f in enumerate(fuentes):
        encolar(f, raiz_cola=raiz, ahora=lambda i=i: datetime(2026, 10, 14, 20, 0, i))


def _lectura(fuente, motivo, coste):
    return Lectura(fuente=fuente, nombre=fuente.rsplit("/", 1)[1], commit="c", run="r",
                   salida=Path("/s"), motivo=motivo, vueltas=1, coste_usd=coste, nota=None)


def _leer_fn(guion, llamadas):
    async def f(fuente, tope_usd):
        llamadas.append((fuente, tope_usd))
        r = guion[fuente]
        if isinstance(r, Exception):
            raise r
        return _lectura(fuente, *r)
    return f


def test_encolar_y_no_duplicar(tmp_path):
    p1, nuevo1 = encolar(A, raiz_cola=tmp_path)
    p2, nuevo2 = encolar(A + ".git", raiz_cola=tmp_path)
    assert nuevo1 and not nuevo2 and p1 == p2
    [pend] = pendientes(tmp_path)
    assert pend["fuente"] == A and pend["nombre"] == "a" and pend["intentos"] == 0


def test_encolar_invalida(tmp_path):
    with pytest.raises(FuenteInvalida):
        encolar("https://gitlab.com/x/a", raiz_cola=tmp_path)
    assert pendientes(tmp_path) == []


async def test_noche_en_orden_y_con_techo(tmp_path):
    _encola(tmp_path, A, B, C)
    llamadas = []
    r = await noche(raiz_cola=tmp_path, leer_fn=_leer_fn(
        {A: ("aprobado", 4.5), B: ("aprobado", 5.0), C: ("aprobado", 1.0)}, llamadas))
    # 4.5 + 5.0 = 9.5: quedan 0.5 $, menos que minimo_usd (1 $), así que C espera a otra noche
    assert llamadas == [(A, 5.0), (B, 5.0)]
    assert r["parada"] == "techo" and r["gastado_usd"] == 9.5 and r["quedan"] == 1
    assert [p["fuente"] for p in pendientes(tmp_path)] == [C]
    assert len(list((tmp_path / "hechas").iterdir())) == 2


async def test_tope_del_run_es_lo_que_queda(tmp_path):
    _encola(tmp_path, A, B)
    llamadas = []
    await noche(raiz_cola=tmp_path, leer_fn=_leer_fn({A: ("aprobado", 7.5), B: ("aprobado", 1.0)}, llamadas))
    assert llamadas == [(A, 5.0), (B, 2.5)]


async def test_sin_cambios_va_a_hechas_sin_gastar(tmp_path):
    _encola(tmp_path, A)
    r = await noche(raiz_cola=tmp_path, leer_fn=_leer_fn({A: ("sin_cambios", 0.0)}, []))
    assert r["gastado_usd"] == 0 and pendientes(tmp_path) == []


async def test_tope_coste_sigue_pendiente_y_sigue_la_noche(tmp_path):
    _encola(tmp_path, A, B)
    llamadas = []
    r = await noche(raiz_cola=tmp_path, leer_fn=_leer_fn({A: ("tope_coste", 5.0), B: ("aprobado", 1.0)}, llamadas))
    assert [f for f, _ in llamadas] == [A, B] and r["parada"] is None
    [pend] = pendientes(tmp_path)
    assert pend["fuente"] == A and pend["intentos"] == 1 and pend["historial"][0]["motivo"] == "tope_coste"


async def test_fallo_para_la_noche(tmp_path):
    _encola(tmp_path, A, B)
    llamadas = []
    r = await noche(raiz_cola=tmp_path, leer_fn=_leer_fn({A: ("fallo:cartografo:error", 0.0), B: ("aprobado", 1.0)}, llamadas))
    assert [f for f, _ in llamadas] == [A] and r["parada"] == "fallo:cartografo:error"
    assert [p["fuente"] for p in pendientes(tmp_path)] == [A, B]


async def test_excepcion_de_un_repo_no_para_la_noche(tmp_path):
    _encola(tmp_path, A, B)
    r = await noche(raiz_cola=tmp_path, leer_fn=_leer_fn({A: GitFallo("privado"), B: ("aprobado", 1.0)}, []))
    assert r["parada"] is None and r["errores"][0][0] == A and "privado" in r["errores"][0][1]
    [pend] = pendientes(tmp_path)
    assert pend["fuente"] == A and pend["intentos"] == 1


async def test_tres_intentos_y_a_fallidas(tmp_path):
    _encola(tmp_path, A)
    for _ in range(3):
        await noche(raiz_cola=tmp_path, leer_fn=_leer_fn({A: GitFallo("privado")}, []))
    assert pendientes(tmp_path) == []
    [f] = fallidas(tmp_path)
    assert f["fuente"] == A and f["intentos"] == 3 and len(f["historial"]) == 3


async def test_cola_vacia(tmp_path):
    r = await noche(raiz_cola=tmp_path, leer_fn=_leer_fn({}, []))
    assert r["lecturas"] == [] and r["quedan"] == 0 and r["parada"] is None


# --- añadidas (no normativas) ---

def test_main_cola_vacia_sale_en_silencio(tmp_path, capsys):
    from enjambre.cola import main
    assert main(["--falso", "--raiz-cola", str(tmp_path / "cola"), "--cerrojo", str(tmp_path / "c.lock")]) == 0
    assert capsys.readouterr().out == ""


def test_main_con_el_cerrojo_ocupado_avisa_y_sale_con_3(tmp_path, capsys):
    import subprocess
    import sys

    from enjambre.cola import main
    cola = tmp_path / "cola"
    _encola(cola, A)
    ruta = tmp_path / "c.lock"
    retener = ("import fcntl, sys, time\nf = open(sys.argv[1], 'a')\nfcntl.flock(f, fcntl.LOCK_EX)\n"
               "print('ok', flush=True)\ntime.sleep(30)\n")
    p = subprocess.Popen([sys.executable, "-c", retener, str(ruta)], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "ok"
        assert main(["--falso", "--raiz-cola", str(cola), "--cerrojo", str(ruta)]) == 3
    finally:
        p.kill()
        p.wait()
    assert "esta noche no" in capsys.readouterr().out
    assert [p["fuente"] for p in pendientes(cola)] == [A]  # la petición sigue esperando


def test_main_falso_de_punta_a_punta(tmp_path, monkeypatch, capsys):
    # Una fuente local en tmp_path (el `resolver` real solo acepta /data), `lanzar` falso,
    # notas a <salida>/nota.md y el aviso impreso: así se prueba la unidad systemd sin gastar.
    import functools

    import enjambre.cola as cola_mod
    from enjambre.fuente import resolver
    from tests.gitutil import repo_con_commit
    data = tmp_path / "data"
    repo = repo_con_commit(data / "proyecto")
    monkeypatch.setattr(cola_mod, "resolver", functools.partial(resolver, raiz_local=data, raiz_copias=data / "copias"))
    raiz = tmp_path / "cola"
    encolar(str(repo), raiz_cola=raiz, raiz_local=data, raiz_copias=data / "copias")
    codigo = cola_mod.main(["--falso", "--raiz-cola", str(raiz), "--cerrojo", str(tmp_path / "c.lock"),
                            "--salidas", str(tmp_path / "salidas")])
    fuera = capsys.readouterr().out
    assert codigo == 0 and "resumen de la noche" in fuera and "proyecto" in fuera
    assert pendientes(raiz) == [] and len(list((raiz / "hechas").iterdir())) == 1
    [nota] = list((tmp_path / "salidas" / "proyecto").glob("*/nota.md"))
    assert nota.exists()
