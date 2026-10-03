import asyncio
import json
from pathlib import Path

import pytest

import enjambre.orquestar as orquestar_mod
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


_LINEA_SALIDA_D18 = (
    "Tu directorio de trabajo ya es SALIDA: donde tus instrucciones dicen SALIDA/x, usa x o la ruta absoluta."
)


async def test_encargo_aclara_salida_para_todos_los_roles(repo, tmp_path):
    # D18: el novato parecía tomar "SALIDA/articulo.md" como ruta literal en
    # vez de entender que su cwd ya es esa carpeta; la línea debe salir en
    # TODOS los encargos, incluidos los de redactor/novato (que no ven REPO).
    await orquestar(repo, tmp_path / "s", hacer_lanzar_falso(), run="r1")
    enc = {e["agente"]: e["encargo"] for e in eventos(tmp_path / "s") if e["tipo"] == "lanzado"}
    assert enc  # hay al menos un lanzamiento
    for agente, encargo in enc.items():
        assert _LINEA_SALIDA_D18 in encargo, f"falta la línea D18 en el encargo de {agente}"


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


# --- Patch B: --salidas por defecto, y guion con entradas asíncronas -------


def test_salidas_por_defecto_es_absoluta_y_no_depende_del_cwd(monkeypatch, tmp_path):
    """El default de `--salidas` debe calcularse desde la ubicación del propio
    módulo (`enjambre/orquestar.py`), no desde el cwd del proceso -- si no,
    invocar `python -m enjambre.orquestar` desde fuera del repo escribiría en
    <cwd>/salidas en vez de en <repo>/salidas."""
    monkeypatch.chdir(tmp_path)  # cwd distinto de la raíz del repo
    analizador = orquestar_mod._crear_analizador()
    esperado = Path(orquestar_mod.__file__).resolve().parent.parent / "salidas"
    assert analizador.get_default("salidas") == esperado
    assert analizador.parse_args(["--repo", "x"]).salidas == esperado


# --- D16: borrar-y-exigir verificacion.md/dudas.md desde la vuelta 2 -------


def _novato_escribe_dudas(agente, instancia, encargo, ctx):
    (ctx.salida / "dudas.md").write_text("## Veredicto\n\n`no listo`\n")
    return Resultado("terminado", coste_usd=0.01)


def _novato_sin_dudas(agente, instancia, encargo, ctx):
    return Resultado("terminado", coste_usd=0.01)  # no toca dudas.md


async def test_novato_sin_dudas_en_vuelta_2_para_el_run_con_falta_dudas(repo, tmp_path):
    """La tool `Write` real no reescribe un fichero no leído en la sesión, y
    el novato no puede leer `dudas.md` (D2/D8): sin el borrado+exigencia de
    D16, un novato que en la vuelta 2 no reescribe `dudas.md` seguiría
    teniendo el `dudas.md` que dejó la vuelta 1 -- el run podría seguir
    adelante leyendo en silencio una decisión vieja. Con D16 tiene que parar
    con `falta:dudas.md` exactamente (no "aprobado" ni ningún otro motivo).

    Guion: el verificador falla en la vuelta 1 (fuerza la vuelta 2); en la
    vuelta 1 el novato sí escribe `dudas.md` (comportamiento normal, para no
    confundir el caso con uno donde nunca se escribió nada); en la vuelta 2
    el novato "olvida" escribirlo -- exactamente el escenario D16 describe
    para una `Write` real rechazada."""
    lanzar = hacer_lanzar_falso({
        "verificador": [_verificacion_con_fallos],
        "novato": [_novato_escribe_dudas, _novato_sin_dudas],
    })
    fin = await orquestar(repo, tmp_path / "s", lanzar, run="r1")
    assert fin["motivo"] == "falta:dudas.md"
    # La vuelta 1 completó normal y quedó archivada -- D16 no debe tocar la
    # vuelta 1 en absoluto.
    assert (tmp_path / "s" / "agora" / "r1" / "vueltas" / "1" / "dudas.md").exists()


def _verificador_sin_verificacion(agente, instancia, encargo, ctx):
    return Resultado("terminado", coste_usd=0.01)  # no toca verificacion.md


async def test_verificador_sin_verificacion_en_vuelta_2_para_el_run_con_falta_verificacion(repo, tmp_path):
    """Simétrico al de `dudas.md` arriba, para el otro fichero que D16
    borra-y-exige: si el verificador no reescribe `verificacion.md` en la
    vuelta 2, el run debe parar con `falta:verificacion.md` (no seguir con
    el `dudas.md` del novato, que sí se reescribió normal)."""
    lanzar = hacer_lanzar_falso({
        "verificador": [_verificacion_con_fallos, _verificador_sin_verificacion],
    })
    fin = await orquestar(repo, tmp_path / "s", lanzar, run="r1")
    assert fin["motivo"] == "falta:verificacion.md"


async def test_novato_sin_dudas_en_vuelta_1_para_el_run_con_falta_dudas(repo, tmp_path):
    """Simetriza D16 a la vuelta 1: hasta ahora `_exige(salida, "verificacion.md")`
    y `_exige(salida, "dudas.md")` solo corrían desde la vuelta 2, así que un
    novato que no escribe `dudas.md` ya en la vuelta 1 no paraba el run ahí
    mismo -- `n_fallos`/`v` salían `None`, no contaban como aprobado, y el
    run seguía de largo: redactor en modo revisión + una vuelta 2 completa
    (coste real de más) antes de que nada lo notara. Con la exigencia también
    en vuelta 1, debe parar de inmediato con `falta:dudas.md`, sin llegar a
    lanzar la revisión del redactor ni una segunda vuelta.

    No se duplica el caso simétrico (`verificacion.md` sin escribir en vuelta
    1): el mecanismo es el mismo `_exige` para los dos ficheros, y el test de
    `verificacion.md` ya existente para la vuelta 2 (arriba) cubre que
    `_exige` distingue bien cuál de los dos ficheros falta."""
    lanzar = hacer_lanzar_falso({"novato": [_novato_sin_dudas]})
    fin = await orquestar(repo, tmp_path / "s", lanzar, run="r1")
    assert fin["motivo"] == "falta:dudas.md"
    assert fin["vueltas"] == 1
    evs = eventos(tmp_path / "s")
    assert [e["n"] for e in evs if e["tipo"] == "vuelta"] == [1]
    orden = lanzados(evs)
    assert orden.count("verificador") == 1 and orden.count("novato") == 1
    assert orden.count("redactor") == 1  # solo el borrador; nunca llega la revisión


async def test_vuelta_1_no_se_ve_afectada_por_el_borrado_de_d16(repo, tmp_path):
    """D16 actúa solo desde la vuelta >= 2: en la vuelta 1 no hay nada que
    borrar (ni verificacion.md ni dudas.md existen todavía) y el run normal
    de una sola vuelta debe seguir aprobando igual que antes del parche."""
    fin = await orquestar(repo, tmp_path / "s", hacer_lanzar_falso(), run="r1")
    assert fin["motivo"] == "aprobado" and fin["vueltas"] == 1


# --- num_turns: de Resultado al evento fin_agente ---------------------------


def _cartografo_con_num_turns(agente, instancia, encargo, ctx):
    (ctx.salida / "mapa.md").write_text("# Mapa (de pega)\n")
    return Resultado("terminado", coste_usd=0.01, num_turns=3)


async def test_num_turns_llega_al_evento_fin_agente(repo, tmp_path):
    lanzar = hacer_lanzar_falso({"cartografo": [_cartografo_con_num_turns]})
    fin = await orquestar(repo, tmp_path / "s", lanzar, run="r1")
    assert fin["motivo"] == "aprobado"  # el resto del run sigue de pega, normal
    [fin_cartografo] = [
        e for e in eventos(tmp_path / "s") if e["tipo"] == "fin_agente" and e["agente"] == "cartografo"
    ]
    assert fin_cartografo["num_turns"] == 3


async def test_guion_con_entrada_asincrona(repo, tmp_path):
    """D-pendiente (patch B): una entrada de guion puede ser `async def` (o
    cualquier callable cuya llamada devuelva un awaitable), no solo sync."""

    async def _verificador_async(agente, instancia, encargo, ctx):
        await asyncio.sleep(0)
        (ctx.salida / "verificacion.md").write_text("## Resultado\n- Fallos: 0\n")
        return Resultado("terminado", coste_usd=0.01)

    lanzar = hacer_lanzar_falso({"verificador": [_verificador_async]})
    fin = await orquestar(repo, tmp_path / "s", lanzar, run="r1")
    assert fin["motivo"] == "aprobado" and fin["vueltas"] == 1
