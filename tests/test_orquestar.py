import asyncio
import json
from pathlib import Path

import pytest

from enjambre.falso import hacer_lanzar_falso
from enjambre.orquestar import orquestar
from enjambre.tipos import Resultado


def eventos(salidas: Path) -> list[dict]:
    [f] = list(salidas.glob("*/*/eventos.jsonl"))
    return [json.loads(l) for l in f.read_text().splitlines()]


def lanzados(evs):
    return [e["agente"] for e in evs if e["tipo"] == "lanzado"]


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "agora"
    r.mkdir()
    return r


async def test_orden_y_aprobado_en_la_primera_vuelta(repo, tmp_path):
    fin = await orquestar(repo, tmp_path / "s", hacer_lanzar_falso(), run="r1")
    evs = eventos(tmp_path / "s")
    assert fin["motivo"] == "aprobado" and fin["vueltas"] == 1
    orden = lanzados(evs)
    assert orden[:2] == ["cartografo", "despiezador"]
    assert set(orden[2:5]) == {"lector-de-pieza:a-uno", "lector-de-pieza:b-dos", "lector-de-pieza:c-tres"}
    assert orden[5:7] == ["trazador", "redactor"]
    assert set(orden[7:9]) == {"verificador", "novato"}
    assert evs[0]["tipo"] == "run_inicio" and evs[-1]["tipo"] == "run_fin"
    assert (tmp_path / "s" / "agora" / "r1" / "vueltas" / "1" / "verificacion.md").exists()


async def test_lectores_en_paralelo(repo, tmp_path):
    await orquestar(repo, tmp_path / "s", hacer_lanzar_falso(retardo_s=0.05), run="r1")
    evs = eventos(tmp_path / "s")
    lect = [e for e in evs if e.get("agente", "").startswith("lector-de-pieza:")]
    primer_fin = min(i for i, e in enumerate(evs) if e["tipo"] == "fin_agente" and e in lect)
    ultimo_lanzado = max(i for i, e in enumerate(evs) if e["tipo"] == "lanzado" and e in lect)
    assert ultimo_lanzado < primer_fin


async def test_encargos_sin_repo_para_redactor_y_novato(repo, tmp_path):
    await orquestar(repo, tmp_path / "s", hacer_lanzar_falso(), run="r1")
    enc = {e["agente"]: e["encargo"] for e in eventos(tmp_path / "s") if e["tipo"] == "lanzado"}
    assert "REPO=" not in enc["redactor"] and "MODO=borrador" in enc["redactor"]
    assert "REPO=" not in enc["novato"] and "VUELTA=1" in enc["novato"]
    assert "REPO=" in enc["verificador"] and "PIEZA=b-dos" in enc["lector-de-pieza:b-dos"]


def _verificacion_con_fallos(agente, instancia, encargo, ctx):
    (ctx.salida / "verificacion.md").write_text("## Resultado\n- Fallos: 2\n")
    return Resultado("terminado", coste_usd=0.01)


async def test_tope_de_vueltas(repo, tmp_path):
    lanzar = hacer_lanzar_falso({"verificador": [_verificacion_con_fallos] * 3})
    fin = await orquestar(repo, tmp_path / "s", lanzar, run="r1", max_vueltas=2)
    orden = lanzados(eventos(tmp_path / "s"))
    assert fin["motivo"] == "tope_vueltas" and fin["vueltas"] == 3
    assert orden.count("verificador") == 3 and orden.count("novato") == 3
    assert orden.count("redactor") == 3          # borrador + 2 revisiones
    for n in (1, 2, 3):
        assert (tmp_path / "s" / "agora" / "r1" / "vueltas" / str(n) / "dudas.md").exists()


async def test_aprueba_en_la_segunda_vuelta(repo, tmp_path):
    lanzar = hacer_lanzar_falso({"verificador": [_verificacion_con_fallos]})
    fin = await orquestar(repo, tmp_path / "s", lanzar, run="r1")
    assert fin["motivo"] == "aprobado" and fin["vueltas"] == 2


async def test_lector_bloqueado_para_antes_del_trazador(repo, tmp_path):
    lanzar = hacer_lanzar_falso({"lector-de-pieza:b-dos": [Resultado("bloqueado")]})
    fin = await orquestar(repo, tmp_path / "s", lanzar, run="r1")
    orden = lanzados(eventos(tmp_path / "s"))
    assert fin["motivo"] == "fallo:lector-de-pieza:b-dos:bloqueado"
    assert "trazador" not in orden
    assert sum(1 for a in orden if a.startswith("lector-de-pieza:")) == 3   # los otros terminaron


async def test_lector_que_lanza_excepcion(repo, tmp_path):
    def revienta(*a):
        raise RuntimeError("boom")
    fin = await orquestar(repo, tmp_path / "s", hacer_lanzar_falso({"lector-de-pieza:a-uno": [revienta]}), run="r1")
    assert fin["motivo"] == "fallo:lector-de-pieza:a-uno:error"
    for l in (tmp_path / "s" / "agora" / "r1" / "eventos.jsonl").read_text().splitlines():
        json.loads(l)


async def test_piezas_ilegibles(repo, tmp_path):
    def piezas_malas(agente, instancia, encargo, ctx):
        (ctx.salida / "piezas.md").write_text("## Resumen\n| Id |\n|---|\n| Acceso Datos |\n")
        return Resultado("terminado")
    fin = await orquestar(repo, tmp_path / "s", hacer_lanzar_falso({"despiezador": [piezas_malas]}), run="r1")
    assert fin["motivo"] == "piezas_ilegibles"
    assert not any(a.startswith("lector") for a in lanzados(eventos(tmp_path / "s")))


async def test_fichero_esperado_ausente(repo, tmp_path):
    fin = await orquestar(repo, tmp_path / "s", hacer_lanzar_falso({"cartografo": [Resultado("terminado")]}), run="r1")
    assert fin["motivo"] == "falta:mapa.md"


async def test_tope_de_coste(repo, tmp_path):
    caro = Resultado("terminado", coste_usd=10.0)
    def cartografo_caro(agente, instancia, encargo, ctx):
        (ctx.salida / "mapa.md").write_text("x")
        return caro
    fin = await orquestar(repo, tmp_path / "s", hacer_lanzar_falso({"cartografo": [cartografo_caro]}), run="r1", tope_usd=5)
    assert fin["motivo"] == "tope_coste"
    assert lanzados(eventos(tmp_path / "s")) == ["cartografo"]


async def test_cancelacion_deja_run_fin(repo, tmp_path):
    tarea = asyncio.create_task(orquestar(repo, tmp_path / "s", hacer_lanzar_falso(retardo_s=0.2), run="r1"))
    await asyncio.sleep(0.3)
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea
    evs = eventos(tmp_path / "s")
    assert evs[-1]["tipo"] == "run_fin" and evs[-1]["motivo"] == "interrumpido"


async def test_run_existente_es_error(repo, tmp_path):
    await orquestar(repo, tmp_path / "s", hacer_lanzar_falso(), run="r1")
    with pytest.raises(FileExistsError):
        await orquestar(repo, tmp_path / "s", hacer_lanzar_falso(), run="r1")


# --- Pruebas de regresión añadidas tras la revisión de la Tarea 6 (no son parte
# del guion normativo del brief; cubren los dos bugs reales que encontró el
# revisor) -----------------------------------------------------------------


def _redactor_borrador_barato(agente, instancia, encargo, ctx):
    (ctx.salida / "articulo.md").write_text("# Artículo (de pega)\n")
    return Resultado("terminado", coste_usd=0.01)


def _redactor_revision_cara(agente, instancia, encargo, ctx):
    (ctx.salida / "articulo.md").write_text("# Artículo revisado (de pega)\n")
    return Resultado("terminado", coste_usd=10.0)


async def test_tope_de_coste_no_cuenta_una_vuelta_que_nunca_se_lanzo(repo, tmp_path):
    """Bug real: el coste se dispara DURANTE la revisión de la vuelta 1 (la
    redactor caro cuesta 10 contra un tope de 5); la vuelta 2 no debe contar
    como hecha ni aparecer en el jsonl, porque su verificador+novato nunca
    llegan a lanzarse -- el tope se comprueba antes de intentarlos."""
    lanzar = hacer_lanzar_falso({
        "verificador": [_verificacion_con_fallos],
        "redactor": [_redactor_borrador_barato, _redactor_revision_cara],
    })
    fin = await orquestar(repo, tmp_path / "s", lanzar, run="r1", tope_usd=5, max_vueltas=5)
    assert fin["motivo"] == "tope_coste"
    assert fin["vueltas"] == 1

    evs = eventos(tmp_path / "s")
    orden = lanzados(evs)
    assert orden.count("verificador") == 1 and orden.count("novato") == 1
    assert [e["n"] for e in evs if e["tipo"] == "vuelta"] == [1]


async def test_excepcion_en_lanzar_emite_aviso(repo, tmp_path):
    """La excepción de un `lanzar` inyectado (aquí, de pega; en producción,
    cualquier fallo del SDK real -- auth, rate limit, red) no debe desaparecer
    sin rastro al convertirse en Resultado('error'): es un evento de AGENTE
    (§6: va al jsonl, no a LogCentral -- eso es solo para excepciones no
    previstas del propio orquestador), así que tiene que quedar como `aviso`
    con el tipo y el mensaje de la excepción."""

    def revienta(*a):
        raise RuntimeError("boom")

    fin = await orquestar(
        repo, tmp_path / "s", hacer_lanzar_falso({"lector-de-pieza:a-uno": [revienta]}), run="r1"
    )
    assert fin["motivo"] == "fallo:lector-de-pieza:a-uno:error"

    avisos = [e for e in eventos(tmp_path / "s") if e["tipo"] == "aviso"]
    assert len(avisos) == 1
    assert avisos[0]["agente"] == "lector-de-pieza:a-uno"
    assert avisos[0]["texto"] == "RuntimeError: boom"
