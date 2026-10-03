import asyncio
import json
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from enjambre.agentes import cargar
from enjambre.eventos import Eventos
from enjambre.lanzador import Traductor, hacer_hook, opciones
from enjambre.tipos import Contexto


def ctx(tmp_path: Path) -> Contexto:
    repo, salida = tmp_path / "agora", tmp_path / "s"
    repo.mkdir(); salida.mkdir()
    return Contexto(repo=repo, salida=salida, eventos=Eventos(salida / "eventos.jsonl", "r"))


def leer(c: Contexto) -> list[dict]:
    c.eventos.cerrar()
    return [json.loads(l) for l in (c.salida / "eventos.jsonl").read_text().splitlines()]


def am(bloques, model="claude-haiku-4-5-20251001"):
    return AssistantMessage(content=bloques, model=model)


def test_traductor_estados_y_resultado(tmp_path):
    c = ctx(tmp_path)
    t = Traductor("cartografo", c)
    t.procesar(am([ToolUseBlock("1", "Read", {"file_path": str(c.repo / "README.md")})]))
    t.procesar(am([ToolUseBlock("2", "Grep", {"pattern": "def "})]))
    t.procesar(am([ToolUseBlock("3", "Write", {"file_path": str(c.salida / "mapa.md"), "content": "x"})]))
    t.procesar(am([TextBlock("hecho.\n/s/mapa.md - 18 rutas, 17 módulos")]))
    t.procesar(ResultMessage(subtype="success", duration_ms=96000, duration_api_ms=90000, is_error=False,
                             num_turns=5, session_id="x", total_cost_usd=0.04,
                             usage={"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 20}))
    r = t.resultado()
    assert r.estado_final == "terminado" and r.modelo_real == "claude-haiku-4-5-20251001"
    assert r.respuesta == "/s/mapa.md - 18 rutas, 17 módulos"
    assert (r.coste_usd, r.tokens_in, r.tokens_out, r.duracion_s, r.num_herramientas) == (0.04, 150, 20, 96.0, 3)
    evs = leer(c)
    estados = [e["estado"] for e in evs if e["tipo"] == "estado"]
    assert estados == ["leyendo", "escribiendo", "terminado"]          # Grep no repite "leyendo"
    assert [e["herramienta"] for e in evs if e["tipo"] == "herramienta"] == ["Read", "Grep", "Write"]


def test_traductor_bloqueado_y_aviso_de_modelo(tmp_path):
    c = ctx(tmp_path)
    t = Traductor("despiezador", c)
    t.procesar(am([TextBlock("x")], model="claude-sonnet-5"))
    t.procesar(am([TextBlock("Estado: bloqueado. Falta el mapa.")], model="claude-opus-5-5"))
    t.procesar(ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="x"))
    assert t.resultado().estado_final == "bloqueado"
    assert any(e["tipo"] == "aviso" for e in leer(c))


def test_hook_deniega_y_emite(tmp_path):
    c = ctx(tmp_path)
    hook = hacer_hook(cargar("novato"), "novato", c)
    entrada = {"hook_event_name": "PreToolUse", "tool_name": "Read",
               "tool_input": {"file_path": str(c.salida / "fichas" / "x.md")}, "tool_use_id": "1"}
    salida = asyncio.run(hook(entrada, "1", {"signal": None}))
    assert salida["hookSpecificOutput"]["permissionDecision"] == "deny"
    [d] = [e for e in leer(c) if e["tipo"] == "denegado"]
    assert d["agente"] == "novato" and d["herramienta"] == "Read"


def test_hook_permite_escritura_y_emite_fichero(tmp_path):
    c = ctx(tmp_path)
    hook = hacer_hook(cargar("cartografo"), "cartografo", c)
    entrada = {"hook_event_name": "PreToolUse", "tool_name": "Write",
               "tool_input": {"file_path": str(c.salida / "mapa.md"), "content": "x"}, "tool_use_id": "1"}
    assert asyncio.run(hook(entrada, "1", {"signal": None})) == {}
    [f] = [e for e in leer(c) if e["tipo"] == "fichero"]
    assert f["ruta"] == "mapa.md"


def test_hook_excepcion_interna_deniega_no_aprueba_ni_explota(tmp_path):
    # Entrada malformada (sin "tool_name"): fuerza una excepción DENTRO del
    # cuerpo del hook, no una denegación normal de `permitido()`. Bajo
    # permission_mode="bypassPermissions" una excepción sin capturar aquí
    # dejaría pasar la tool (falla abierto en la única frontera real de
    # seguridad) -- el hook debe denegar, no reventar ni aprobar.
    c = ctx(tmp_path)
    hook = hacer_hook(cargar("novato"), "novato", c)
    entrada = {"hook_event_name": "PreToolUse",
               "tool_input": {"file_path": str(c.salida / "articulo.md")}, "tool_use_id": "1"}
    salida = asyncio.run(hook(entrada, "1", {"signal": None}))
    assert salida["hookSpecificOutput"]["permissionDecision"] == "deny"
    [d] = [e for e in leer(c) if e["tipo"] == "denegado"]
    assert d["agente"] == "novato"


def test_traductor_respuesta_se_recorta_de_espacios(tmp_path):
    # La línea elegida puede venir con espacios de sobra alrededor (no solo
    # líneas en blanco intercaladas, que ya se filtran): sin `.strip()` sobre
    # la línea elegida, esos espacios se cuelan tal cual en `respuesta`.
    c = ctx(tmp_path)
    t = Traductor("redactor", c)
    t.procesar(am([TextBlock("primera línea.\n   /s/articulo.md listo   ")]))
    assert t.resultado().respuesta == "/s/articulo.md listo"


def test_opciones(tmp_path):
    c = ctx(tmp_path)
    a = cargar("redactor")
    o = opciones(a, c, hook=None)
    assert o.model == "sonnet" and o.system_prompt == a.prompt
    assert o.setting_sources == [] and str(o.cwd) == str(c.salida)
    assert o.max_turns == c.max_turns
