import asyncio
import json
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

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


def test_hook_permite_escritura_y_no_emite_fichero(tmp_path):
    # D17: permitir un Write ya NO implica que se escribiera -- ese evento
    # ahora lo emite `Traductor` a partir del resultado real de la tool, no
    # el hook `PreToolUse` al dejarla pasar (ver tests de más abajo).
    c = ctx(tmp_path)
    hook = hacer_hook(cargar("cartografo"), "cartografo", c)
    entrada = {"hook_event_name": "PreToolUse", "tool_name": "Write",
               "tool_input": {"file_path": str(c.salida / "mapa.md"), "content": "x"}, "tool_use_id": "1"}
    assert asyncio.run(hook(entrada, "1", {"signal": None})) == {}
    assert not [e for e in leer(c) if e["tipo"] == "fichero"]


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


def test_opciones_strict_mcp_config(tmp_path):
    # D18: hipótesis del gasto anómalo de tokens de la prueba de humo -- sin
    # esto, tools MCP de plugins/conectores ajenos al enjambre viajarían en
    # cada turno aunque ningún agente las pida.
    c = ctx(tmp_path)
    o = opciones(cargar("redactor"), c, hook=None)
    assert o.strict_mcp_config is True


# --- D17: `fichero`/`aviso` desde el resultado real de la tool, no del hook ----


def test_traductor_emite_fichero_desde_resultado_real_de_write(tmp_path):
    c = ctx(tmp_path)
    t = Traductor("cartografo", c)
    ruta_absoluta = str(c.salida / "mapa.md")
    t.procesar(am([ToolUseBlock("t1", "Write", {"file_path": ruta_absoluta, "content": "x"})]))
    t.procesar(UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="ok", is_error=False)]))
    # El `fichero` sale del resultado real de la tool (este `UserMessage`),
    # no de haber visto la llamada (el `ToolUseBlock` de arriba, por sí
    # solo, no emite nada -- a diferencia del hook de antes de D17).
    [f] = [e for e in leer(c) if e["tipo"] == "fichero"]
    assert f["ruta"] == "mapa.md"


def test_traductor_emite_aviso_si_la_escritura_se_rechaza(tmp_path):
    c = ctx(tmp_path)
    t = Traductor("novato", c)
    ruta_absoluta = str(c.salida / "dudas.md")
    t.procesar(am([ToolUseBlock("t2", "Write", {"file_path": ruta_absoluta, "content": "x"})]))
    error = "File has not been read yet. Read it first before writing to it." * 5  # > 200 chars
    t.procesar(
        UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="t2",
                    content=[{"type": "text", "text": error}],
                    is_error=True,
                )
            ]
        )
    )
    evs = leer(c)
    assert not [e for e in evs if e["tipo"] == "fichero"]
    [a] = [e for e in evs if e["tipo"] == "aviso"]
    assert a["texto"].startswith("escritura rechazada: dudas.md: ")
    assert len(a["texto"]) < len("escritura rechazada: dudas.md: ") + 201


# --- Regex de "bloqueado": insensible a mayúsculas, no se cuela en negaciones -


def test_bloqueado_no_estoy_bloqueado_no_cuenta(tmp_path):
    c = ctx(tmp_path)
    t = Traductor("redactor", c)
    t.procesar(am([TextBlock("no estoy bloqueado")]))
    assert t.resultado().estado_final != "bloqueado"


def test_bloqueado_no_bloqueado_no_cuenta(tmp_path):
    c = ctx(tmp_path)
    t = Traductor("redactor", c)
    t.procesar(am([TextBlock("no bloqueado")]))
    assert t.resultado().estado_final != "bloqueado"


def test_bloqueado_mayuscula_cuenta(tmp_path):
    c = ctx(tmp_path)
    t = Traductor("redactor", c)
    t.procesar(am([TextBlock("Bloqueado, necesito ayuda")]))
    assert t.resultado().estado_final == "bloqueado"


def test_bloqueado_femenino_cuenta(tmp_path):
    c = ctx(tmp_path)
    t = Traductor("redactor", c)
    t.procesar(am([TextBlock("estoy bloqueada")]))
    assert t.resultado().estado_final == "bloqueado"


# --- D18/I4: tools inesperadas en el mensaje `init` ----------------------------


def test_init_con_tool_extra_emite_aviso(tmp_path):
    c = ctx(tmp_path)
    agente = cargar("cartografo")  # tools: Read, Glob, Grep, Write
    t = Traductor("cartografo", c, agente)
    t.procesar(SystemMessage(subtype="init", data={"tools": [*agente.tools, "Bash"]}))
    [a] = [e for e in leer(c) if e["tipo"] == "aviso"]
    assert "Bash" in a["texto"]


def test_init_sin_tools_extra_no_emite_aviso(tmp_path):
    c = ctx(tmp_path)
    agente = cargar("cartografo")
    t = Traductor("cartografo", c, agente)
    t.procesar(SystemMessage(subtype="init", data={"tools": list(agente.tools)}))
    assert not [e for e in leer(c) if e["tipo"] == "aviso"]


# --- num_turns: de ResultMessage a Resultado ------------------------------------


def test_num_turns_llega_desde_result_message(tmp_path):
    c = ctx(tmp_path)
    t = Traductor("cartografo", c)
    t.procesar(
        ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=7, session_id="x",
        )
    )
    assert t.resultado().num_turns == 7
