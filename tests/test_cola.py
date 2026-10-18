import json
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


async def test_excepcion_desconocida_para_la_noche(tmp_path):
    # R5 de la revisión de H3: no es un problema del repo, así que seguir solo gastaría intentos.
    _encola(tmp_path, A, B)
    llamadas = []
    r = await noche(raiz_cola=tmp_path, leer_fn=_leer_fn({A: RuntimeError("SDK roto"), B: ("aprobado", 1.0)}, llamadas))
    assert [f for f, _ in llamadas] == [A]
    assert r["parada"] == "excepcion:RuntimeError" and r["errores"][0][0] == A
    [a, b] = pendientes(tmp_path)
    assert a["fuente"] == A and a["intentos"] == 1 and a["historial"][0]["error"].startswith("RuntimeError")
    assert b["fuente"] == B and b["intentos"] == 0


def test_encolar_no_distingue_mayusculas(tmp_path):
    # Hallado en la prueba manual de H4: `.../Claude-Fables` y `.../claude-fables` son el mismo repo.
    p1, nuevo1 = encolar("https://github.com/x/Proyecto", raiz_cola=tmp_path)
    p2, nuevo2 = encolar("https://github.com/X/proyecto", raiz_cola=tmp_path)
    assert nuevo1 and not nuevo2 and p1 == p2


# --- D39 (anexo 2026-10-16, Tarea 27): normativas, tal cual ---
from datetime import datetime, timedelta


def _l(fuente, motivo, coste, reintentar_a=None):
    l = _lectura(fuente, motivo, coste)
    l.reintentar_a = reintentar_a
    return l


def _secuencia(respuestas, llamadas):
    async def f(fuente, tope_usd):
        llamadas.append((fuente, tope_usd))
        return respuestas.pop(0)
    return f


INICIO = datetime(2026, 10, 16, 2, 30)


async def test_espera_al_reset_y_sigue(tmp_path):
    _encola(tmp_path, A)
    dormidos, llamadas = [], []
    async def dormir(s): dormidos.append(s)
    r = await noche(raiz_cola=tmp_path, ahora=lambda: INICIO, dormir=dormir,
                    leer_fn=_secuencia([_l(A, "fallo:trazador:error", 2.74, datetime(2026, 10, 16, 2, 40)),
                                        _l(A, "aprobado", 1.0)], llamadas))
    assert [f for f, _ in llamadas] == [A, A] and llamadas[1][1] == 5.0
    assert len(dormidos) == 1 and dormidos[0] >= 60
    assert r["parada"] is None and pendientes(tmp_path) == []
    [hecha] = [json.loads(p.read_text()) for p in (tmp_path / "hechas").iterdir()]
    assert hecha["intentos"] == 1 and len(hecha["historial"]) == 2


async def test_no_espera_si_el_reset_es_despues_de_las_7(tmp_path):
    _encola(tmp_path, A, B)
    dormidos, llamadas = [], []
    async def dormir(s): dormidos.append(s)
    r = await noche(raiz_cola=tmp_path, ahora=lambda: INICIO, dormir=dormir,
                    leer_fn=_secuencia([_l(A, "fallo:trazador:error", 1.0, datetime(2026, 10, 16, 7, 30))], llamadas))
    assert dormidos == [] and [f for f, _ in llamadas] == [A] and r["parada"] == "fallo:trazador:error"


async def test_solo_una_espera_por_noche(tmp_path):
    _encola(tmp_path, A)
    dormidos, llamadas = [], []
    async def dormir(s): dormidos.append(s)
    reset = datetime(2026, 10, 16, 2, 40)
    r = await noche(raiz_cola=tmp_path, ahora=lambda: INICIO, dormir=dormir,
                    leer_fn=_secuencia([_l(A, "fallo:trazador:error", 1.0, reset),
                                        _l(A, "fallo:redactor:error", 0.5, reset + timedelta(hours=1))], llamadas))
    assert len(dormidos) == 1 and len(llamadas) == 2 and r["parada"] == "fallo:redactor:error"
    [pend] = pendientes(tmp_path)
    assert pend["intentos"] == 1 and len(pend["historial"]) == 2


async def test_sin_reintentar_a_no_espera(tmp_path):
    _encola(tmp_path, A)
    dormidos = []
    async def dormir(s): dormidos.append(s)
    r = await noche(raiz_cola=tmp_path, ahora=lambda: INICIO, dormir=dormir,
                    leer_fn=_secuencia([_l(A, "fallo:trazador:error", 1.0)], []))
    assert dormidos == [] and r["parada"] == "fallo:trazador:error"


# --- añadidas (no normativas) ---

async def test_la_espera_no_se_hace_si_ya_no_queda_techo(tmp_path):
    # Esperar para poder gastar menos de `minimo_usd` no tiene sentido.
    _encola(tmp_path, A)
    dormidos = []
    async def dormir(s): dormidos.append(s)
    r = await noche(raiz_cola=tmp_path, ahora=lambda: INICIO, dormir=dormir, techo_usd=3.0, tope_run_usd=3.0,
                    leer_fn=_secuencia([_l(A, "fallo:trazador:error", 2.5, datetime(2026, 10, 16, 2, 40))], []))
    assert dormidos == [] and r["parada"] == "fallo:trazador:error"


async def test_el_resumen_dice_a_que_hora_se_espero(tmp_path):
    from enjambre.aviso import texto_noche
    _encola(tmp_path, A)
    async def dormir(s): pass
    r = await noche(raiz_cola=tmp_path, ahora=lambda: INICIO, dormir=dormir,
                    leer_fn=_secuencia([_l(A, "fallo:trazador:error", 2.0, datetime(2026, 10, 16, 2, 40)),
                                        _l(A, "aprobado", 1.0)], []))
    assert r["esperado_a"] == datetime(2026, 10, 16, 2, 40)
    assert "esperé al reset de las 02:40" in texto_noche(r).lower()


async def test_una_excepcion_no_espera(tmp_path):
    _encola(tmp_path, A)
    dormidos = []
    async def dormir(s): dormidos.append(s)
    r = await noche(raiz_cola=tmp_path, ahora=lambda: INICIO, dormir=dormir,
                    leer_fn=_leer_fn({A: RuntimeError("SDK roto")}, []))
    assert dormidos == [] and r["parada"] == "excepcion:RuntimeError"


async def test_la_noche_que_empieza_despues_de_las_7_cuenta_la_del_dia_siguiente(tmp_path):
    # Una noche que arranca a las 23:00: el límite es las 07:00 de MAÑANA, no las de hoy (ya pasadas).
    _encola(tmp_path, A)
    dormidos = []
    async def dormir(s): dormidos.append(s)
    ahora = datetime(2026, 10, 16, 23, 0)
    await noche(raiz_cola=tmp_path, ahora=lambda: ahora, dormir=dormir,
                leer_fn=_secuencia([_l(A, "fallo:trazador:error", 1.0, datetime(2026, 10, 17, 1, 0)),
                                    _l(A, "aprobado", 1.0)], []))
    assert len(dormidos) == 1


# --- D42 (anexo 2026-10-17, Tarea 30): normativas, tal cual ---
from enjambre.cola import retirar


def test_retirar_mueve_a_retiradas(tmp_path):
    _encola(tmp_path, A, B)
    pa, pb = pendientes(tmp_path)
    assert retirar(pa["id"], raiz_cola=tmp_path)
    assert [p["fuente"] for p in pendientes(tmp_path)] == [B]
    [movida] = (tmp_path / "retiradas").glob("*.json")
    datos = json.loads(movida.read_text())
    assert movida.stem == pa["id"] and datos["historial"][-1]["motivo"] == "retirada" and "id" not in datos


def test_retirar_una_fallida(tmp_path):
    _encola(tmp_path, A)
    [pa] = pendientes(tmp_path)
    (tmp_path / "fallidas").mkdir()
    (tmp_path / "pendientes" / f"{pa['id']}.json").rename(tmp_path / "fallidas" / f"{pa['id']}.json")
    assert retirar(pa["id"], raiz_cola=tmp_path) and fallidas(tmp_path) == []


def test_retirar_lo_que_no_esta_o_no_vale(tmp_path):
    assert retirar("20261014-200000-nada", raiz_cola=tmp_path) is False
    for malo in ("../x", "20261014-200000-a/b", "", "x", "20261014-200000-a.json/.."):
        with pytest.raises(ValueError):
            retirar(malo, raiz_cola=tmp_path)


def test_el_id_no_se_escribe_en_el_json(tmp_path):
    _encola(tmp_path, A)
    [pa] = pendientes(tmp_path)
    assert "id" not in json.loads((tmp_path / "pendientes" / f"{pa['id']}.json").read_text())


async def test_noche_salta_una_que_se_saco_antes_de_leerla(tmp_path):
    _encola(tmp_path, A, B)
    pa, pb = pendientes(tmp_path)
    llamadas = []
    async def leer_fn(fuente, tope):
        llamadas.append(fuente)
        if fuente == A:
            retirar(pb["id"], raiz_cola=tmp_path)
        return _lectura(fuente, "aprobado", 1.0)
    await noche(raiz_cola=tmp_path, leer_fn=leer_fn)
    assert llamadas == [A]


async def test_noche_no_recrea_la_que_se_saca_durante_su_lectura(tmp_path):
    _encola(tmp_path, A)
    [pa] = pendientes(tmp_path)
    async def leer_fn(fuente, tope):
        retirar(pa["id"], raiz_cola=tmp_path)
        return _lectura(fuente, "aprobado", 1.0)
    r = await noche(raiz_cola=tmp_path, leer_fn=leer_fn)
    assert pendientes(tmp_path) == [] and not list((tmp_path / "hechas").glob("*.json"))
    assert len(list((tmp_path / "retiradas").glob("*.json"))) == 1 and r["gastado_usd"] == 1.0


# --- añadidas (no normativas) ---

def test_retirar_dos_veces_la_segunda_es_false(tmp_path):
    _encola(tmp_path, A)
    [pa] = pendientes(tmp_path)
    assert retirar(pa["id"], raiz_cola=tmp_path) is True
    assert retirar(pa["id"], raiz_cola=tmp_path) is False


def test_retirar_un_json_ilegible_lo_mueve_igual(tmp_path):
    (tmp_path / "pendientes").mkdir()
    (tmp_path / "pendientes" / "20261014-200000-roto.json").write_text("{no es json")
    assert retirar("20261014-200000-roto", raiz_cola=tmp_path) is True
    assert (tmp_path / "retiradas" / "20261014-200000-roto.json").exists()


def test_retirar_no_acepta_ids_con_mayusculas_ni_rutas(tmp_path):
    for malo in ("20261014-200000-Repo", "/etc/passwd", "20261014-200000-a\n", "20261014-200000-a b", None):
        with pytest.raises(ValueError):
            retirar(malo, raiz_cola=tmp_path)


def test_raiz_cola_por_defecto_se_lee_al_llamar(tmp_path, monkeypatch):
    # R2 / `CLAUDE.md`: el valor por defecto no se fija en la firma.
    import enjambre.cola as cola_mod
    monkeypatch.setattr(cola_mod, "RAIZ_COLA", tmp_path)
    encolar("https://github.com/x/a")
    assert [p["nombre"] for p in pendientes()] == ["a"] and fallidas() == []
    assert retirar(pendientes()[0]["id"]) is True


async def test_noche_sin_raiz_cola_usa_la_de_modulo(tmp_path, monkeypatch):
    import enjambre.cola as cola_mod
    monkeypatch.setattr(cola_mod, "RAIZ_COLA", tmp_path)
    r = await noche(leer_fn=_leer_fn({}, []))
    assert r["quedan"] == 0 and r["lecturas"] == []
