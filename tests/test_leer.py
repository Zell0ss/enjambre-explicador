import json
from types import SimpleNamespace

import pytest

from enjambre.falso import hacer_lanzar_falso
from enjambre.fuente import resolver
from enjambre.leer import leer, ultimo_parado
from enjambre.nota import leer_frontmatter
from enjambre.tipos import Resultado
from tests.gitutil import repo_con_commit, rev


@pytest.fixture
def e(tmp_path):
    data = tmp_path / "data"
    repo = repo_con_commit(data / "proyecto")
    return SimpleNamespace(data=data, repo=repo, salidas=tmp_path / "salidas",
                           notas=tmp_path / "notas", copias=data / "github-abordaje")


def _f(e):
    return resolver(str(e.repo), raiz_local=e.data, raiz_copias=e.copias)


def _kw(e, **kw):
    return dict(salidas=e.salidas, raiz_copias=e.copias, raiz_notas=e.notas, **kw)


FALLA = {"cartografo": [Resultado(estado_final="error")]}


def _eventos(salida):
    return [json.loads(l) for l in (salida / "eventos.jsonl").read_text().splitlines()]


async def test_aprobado_deja_nota(e):
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r1", **_kw(e))
    assert l.motivo == "aprobado" and l.run == "r1" and l.nota == e.notas / "proyecto.md"
    fm = leer_frontmatter(l.nota)
    assert fm["fuente"] == str(e.repo.resolve()) and fm["commit"] == rev(e.repo) and fm["run"] == "r1"
    ri = _eventos(l.salida)[0]
    assert ri["fuente"] == str(e.repo.resolve()) and ri["commit"] == rev(e.repo)


async def test_falso_no_toca_el_vault(e):
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r1", falso=True, **_kw(e))
    assert l.nota == l.salida / "nota.md" and l.nota.exists()
    assert not e.notas.exists()


async def test_parado_no_deja_nota(e):
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(FALLA), run="r1", **_kw(e))
    assert l.motivo.startswith("fallo:cartografo") and l.nota is None
    assert not e.notas.exists()


async def test_saltar_si_la_nota_ya_tiene_ese_commit(e):
    await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r1", **_kw(e))
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r2", saltar_si_igual=True, **_kw(e))
    assert l.motivo == "sin_cambios" and l.coste_usd == 0 and l.run is None
    assert not (e.salidas / "proyecto" / "r2").exists()


async def test_saltar_no_salta_si_hay_commit_nuevo(e):
    await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r1", **_kw(e))
    repo_con_commit(e.repo, "b.py", "y = 2\n")
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r2", saltar_si_igual=True, **_kw(e))
    assert l.motivo == "aprobado" and leer_frontmatter(l.nota)["commit"] == rev(e.repo)


async def test_continua_si_el_commit_es_el_mismo(e):
    parado = await leer(_f(e), lanzar=hacer_lanzar_falso(FALLA), run="r1", **_kw(e))
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), reanudar=parado.salida, **_kw(e))
    assert l.continuado and l.run == "r1" and l.motivo == "aprobado" and l.nota is not None
    assert any(ev["tipo"] == "reanudado" for ev in _eventos(parado.salida))


async def test_run_nuevo_si_el_commit_cambio(e):
    parado = await leer(_f(e), lanzar=hacer_lanzar_falso(FALLA), run="r1", **_kw(e))
    repo_con_commit(e.repo, "b.py", "y = 2\n")
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), reanudar=parado.salida, run="r2", **_kw(e))
    assert not l.continuado and l.run == "r2"


def _run(salidas, nombre, run, fuente, t, motivo):
    d = salidas / nombre / run
    d.mkdir(parents=True)
    lineas = [{"t": t, "run": run, "tipo": "run_inicio", "fuente": fuente, "commit": "c"}]
    if motivo:
        lineas.append({"t": t, "run": run, "tipo": "run_fin", "motivo": motivo})
    (d / "eventos.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lineas))
    return d


F1, F2 = "https://github.com/x/p", "https://github.com/y/p"


def test_ultimo_parado(tmp_path):
    s = tmp_path / "s"
    assert ultimo_parado(s, F1) is None
    r1 = _run(s, "p", "p-1", F1, "2026-10-15T02:30:00", "tope_coste")
    assert ultimo_parado(s, F1) == r1
    _run(s, "p", "p-0", F2, "2026-10-15T02:40:00", "tope_coste")
    assert ultimo_parado(s, F1) == r1
    _run(s, "p", "p-2", F1, "2026-10-16T02:30:00", "aprobado")
    assert ultimo_parado(s, F1) is None
    r3 = _run(s, "p", "p-3", F1, "2026-10-17T02:30:00", "fallo:novato:error")
    assert ultimo_parado(s, F1) == r3
    _run(s, "p", "p-4", F1, "2026-10-18T02:30:00", None)
    assert ultimo_parado(s, F1) is None


# --- añadidas (no normativas) ---

async def test_continuacion_cuenta_solo_lo_de_esta_lectura(e):
    # Foco 4: `run_fin.coste_total_usd` de una continuación incluye lo anterior (D24);
    # `Lectura.coste_usd` (el techo de la noche, D30) no.
    base = hacer_lanzar_falso({"despiezador": [Resultado(estado_final="error")]})

    async def con_coste(agente, instancia, encargo, ctx):
        r = await base(agente, instancia, encargo, ctx)
        if instancia == "cartografo":
            r.coste_usd = 2.0
        return r

    parado = await leer(_f(e), lanzar=con_coste, run="r1", **_kw(e))
    assert parado.motivo.startswith("fallo:despiezador") and parado.coste_usd == 2.0
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), reanudar=parado.salida, **_kw(e))
    assert l.continuado and l.motivo == "aprobado"
    # El falso gasta unos céntimos por paso: lo de esta lectura es poco, y sin los 2 $ de antes.
    assert 0 < l.coste_usd < 1.0
    # La nota sí lleva lo que costó el artículo entero.
    assert leer_frontmatter(l.nota)["coste_usd"] == round(2.0 + l.coste_usd, 2)


def test_main_falso_sobre_fuente_local(e, monkeypatch, capsys):
    import functools

    import enjambre.leer as leer_mod
    monkeypatch.setattr(leer_mod, "resolver", functools.partial(resolver, raiz_local=e.data, raiz_copias=e.copias))
    codigo = leer_mod.main([str(e.repo), "--falso", "--run", "r1", "--salidas", str(e.salidas),
                            "--cerrojo", str(e.data.parent / "c.lock")])
    fuera = capsys.readouterr().out
    assert codigo == 0 and "proyecto" in fuera and "aprobado" in fuera
    assert (e.salidas / "proyecto" / "r1" / "nota.md").exists()
    assert not e.notas.exists()


def test_main_fuente_invalida_devuelve_2(tmp_path, capsys):
    from enjambre.leer import main
    assert main(["https://gitlab.com/x/y", "--salidas", str(tmp_path / "s"), "--cerrojo", str(tmp_path / "c")]) == 2
    assert "FuenteInvalida" in capsys.readouterr().err


def test_main_sin_fuente_ni_reanudar(tmp_path, capsys):
    from enjambre.leer import main
    assert main(["--salidas", str(tmp_path / "s"), "--cerrojo", str(tmp_path / "c")]) == 2


def test_main_respeta_el_cerrojo(tmp_path, capsys):
    import subprocess
    import sys

    from enjambre.leer import main
    ruta = tmp_path / "c.lock"
    retener = ("import fcntl, sys, time\nf = open(sys.argv[1], 'a')\nfcntl.flock(f, fcntl.LOCK_EX)\n"
               "print('ok', flush=True)\ntime.sleep(30)\n")
    p = subprocess.Popen([sys.executable, "-c", retener, str(ruta)], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "ok"
        assert main(["https://github.com/x/y", "--salidas", str(tmp_path / "s"), "--cerrojo", str(ruta)]) == 3
        assert "hay otro run en marcha" in capsys.readouterr().err
    finally:
        p.kill()
        p.wait()


async def test_main_reanudar_run_sin_fuente_sigue_como_antes(e, capsys):
    # Un run anterior a la fase 3 (run_inicio con fuente None): sin actualizar, sin nota, sin aviso.
    import asyncio

    from enjambre.orquestar import orquestar
    await orquestar(e.repo, e.salidas, hacer_lanzar_falso(FALLA), run="r1", falso=True)
    salida = e.salidas / "proyecto" / "r1"
    from enjambre.leer import main
    codigo = await asyncio.to_thread(
        main, ["--reanudar", str(salida), "--cerrojo", str(e.data.parent / "c.lock")])
    assert codigo == 0 and not e.notas.exists()
    assert not (salida / "nota.md").exists()


async def test_nota_ajena_se_descubre_antes_de_gastar(e):
    # R3 de la revisión de H2: ni `lanzar` ni `salidas/<repo>/` si la nota no es nuestra.
    from enjambre.nota import NotaAjena
    e.notas.mkdir()
    (e.notas / "proyecto.md").write_text("# Mis notas\n")
    llamadas = []

    async def lanzar(*a, **k):
        llamadas.append(a)
        raise AssertionError("no debía lanzarse nada")

    with pytest.raises(NotaAjena):
        await leer(_f(e), lanzar=lanzar, run="r1", **_kw(e))
    assert llamadas == [] and not (e.salidas / "proyecto").exists()
    assert (e.notas / "proyecto.md").read_text() == "# Mis notas\n"


async def test_nota_ajena_no_afecta_a_falso(e):
    e.notas.mkdir()
    (e.notas / "proyecto.md").write_text("# Mis notas\n")
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r1", falso=True, **_kw(e))
    assert l.nota == l.salida / "nota.md"


# --- D35: el salto se decide con salidas/, no con la nota ---

async def test_d35_nota_borrada_no_hace_releer(e):
    l1 = await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r1", **_kw(e))
    l1.nota.unlink()
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r2", saltar_si_igual=True, **_kw(e))
    assert l.motivo == "sin_cambios" and l.coste_usd == 0 and l.nota is None
    assert not (e.salidas / "proyecto" / "r2").exists()


async def test_d35_cuenta_el_ultimo_acabado_no_el_ultimo_parado(e):
    await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r1", **_kw(e))
    parado = await leer(_f(e), lanzar=hacer_lanzar_falso(FALLA), run="r2", **_kw(e))
    assert parado.motivo.startswith("fallo:")
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), reanudar=parado.salida, saltar_si_igual=True, **_kw(e))
    assert l.motivo == "sin_cambios" and not l.continuado


async def test_d35_commit_nuevo_no_salta(e):
    await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r1", **_kw(e))
    (e.notas / "proyecto.md").unlink()
    repo_con_commit(e.repo, "b.py", "y = 2\n")
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r2", saltar_si_igual=True, **_kw(e))
    assert l.motivo == "aprobado" and l.run == "r2"


async def test_d35_un_run_falso_no_cuenta(e):
    # Añadida: la demo `--falso` de una fuente no puede suprimir su lectura real.
    await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r1", falso=True, **_kw(e))
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), run="r2", saltar_si_igual=True, **_kw(e))
    assert l.motivo == "aprobado" and l.run == "r2"


def test_ultimo_parado_filtra_por_modo(tmp_path):
    # R4 de la revisión de H3: una demo --falso posterior no tapa un run real parado.
    s = tmp_path / "s"
    real = _run(s, "p", "p-1", F1, "2026-10-15T02:30:00", "tope_coste")
    demo = _run(s, "p", "p-2", F1, "2026-10-15T10:00:00", "aprobado")
    for d in (real, demo):
        lineas = [json.loads(l) for l in (d / "eventos.jsonl").read_text().splitlines()]
        lineas[0]["params"] = {"falso": d is demo}
        (d / "eventos.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lineas))
    assert ultimo_parado(s, F1, falso=False) == real
    assert ultimo_parado(s, F1, falso=True) is None  # la demo acabó: nada que continuar


# --- D36: "Continuar" no lanza un run nuevo si el repo cambió ---

async def test_d36_reanudar_con_commit_nuevo_y_si_cambio_error(e):
    from enjambre.leer import RepoCambiado
    parado = await leer(_f(e), lanzar=hacer_lanzar_falso(FALLA), run="r1", **_kw(e))
    viejo = rev(e.repo)
    repo_con_commit(e.repo, "b.py", "y = 2\n")
    llamadas = []

    async def lanzar(*a, **k):
        llamadas.append(a)
        raise AssertionError("no debía lanzarse nada")

    with pytest.raises(RepoCambiado, match=rf"ha cambiado desde que se paró \({viejo[:7]} → {rev(e.repo)[:7]}\): lanza uno nuevo"):
        await leer(_f(e), lanzar=lanzar, reanudar=parado.salida, si_cambio="error", run="r2", **_kw(e))
    assert llamadas == [] and [d.name for d in (e.salidas / "proyecto").iterdir()] == ["r1"]


async def test_d36_con_el_mismo_commit_si_cambio_error_si_continua(e):
    parado = await leer(_f(e), lanzar=hacer_lanzar_falso(FALLA), run="r1", **_kw(e))
    l = await leer(_f(e), lanzar=hacer_lanzar_falso(), reanudar=parado.salida, si_cambio="error", **_kw(e))
    assert l.continuado and l.motivo == "aprobado"


async def test_d36_sin_commit_con_que_comparar_tambien_es_error(e):
    # Fuente local sin git: no hay forma de saber si cambió, y "Continuar" no gasta a ciegas.
    from enjambre.leer import RepoCambiado
    sin_git = e.data / "suelto"
    sin_git.mkdir()
    f = resolver(str(sin_git), raiz_local=e.data, raiz_copias=e.copias)
    parado = await leer(f, lanzar=hacer_lanzar_falso(FALLA), run="r1", **_kw(e))
    with pytest.raises(RepoCambiado):
        await leer(f, lanzar=hacer_lanzar_falso(), reanudar=parado.salida, si_cambio="error", **_kw(e))


async def test_d36_la_cola_sigue_con_run_nuevo(e):
    # Por defecto (`si_cambio="nuevo"`, lo que usa la cola, D30) no cambia nada: ya cubierto por
    # `test_run_nuevo_si_el_commit_cambio`; aquí solo se fija que el valor por defecto es "nuevo".
    import inspect
    assert inspect.signature(leer).parameters["si_cambio"].default == "nuevo"


async def test_d36_main_reanudar_devuelve_2_y_el_mensaje_va_a_stderr(e, monkeypatch, capsys):
    import asyncio
    import functools

    import enjambre.leer as leer_mod
    monkeypatch.setattr(leer_mod, "resolver", functools.partial(resolver, raiz_local=e.data, raiz_copias=e.copias))
    parado = await leer(_f(e), lanzar=hacer_lanzar_falso(FALLA), run="r1", falso=True, **_kw(e))
    repo_con_commit(e.repo, "b.py", "y = 2\n")
    codigo = await asyncio.to_thread(
        leer_mod.main, ["--reanudar", str(parado.salida), "--cerrojo", str(e.data.parent / "c.lock")])
    err = capsys.readouterr().err
    assert codigo == 2 and "ha cambiado desde que se paró" in err and "lanza uno nuevo" in err
    assert [d.name for d in (e.salidas / "proyecto").iterdir()] == ["r1"]
