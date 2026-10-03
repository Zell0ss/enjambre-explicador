"""
`lanzar` de verdad: la única costura del enjambre que importa `claude_agent_sdk`
(D6) -- ningún otro módulo debe hacerlo. Traduce el guion del agente a opciones
del SDK, gobierna cada tool call con el guardia (D8) desde un hook `PreToolUse`,
y traduce los mensajes del SDK a los eventos que entiende la pantalla (D11: los
estados vienen de qué tool se usa, no de que el agente "diga" en qué estado está).

Verificado contra el SDK instalado (claude-agent-sdk==0.2.163), con cita de
dónde en `CLAUDE.md` -> "Verificado del SDK"; resumen aquí, en la costura que
gobierna cada decisión:

- `setting_sources=[]` desactiva la carga de ficheros de settings -- incluido
  `~/.claude/CLAUDE.md` -- (`types.py`: "Pass [] to disable filesystem
  settings (SDK isolation mode)"). Sin esto, el agente lanzado vería el
  CLAUDE.md global de Josem, que no es parte del encargo (I2 de la spec).
- El hook `PreToolUse` se dispara con independencia del `permission_mode`
  (`types.py`, docstring de `hooks`: "To observe or gate *every* tool call
  regardless of permission rules, use a PreToolUse hook"); `permission_mode`
  solo decide qué pasa cuando el hook NO da una decisión explícita. Con
  `"dontAsk"` eso sería "denegar lo no pre-aprobado por reglas de `allow`" --
  y no tenemos reglas de `allow` en settings (`setting_sources=[]`), así que
  denegaría todo lo que el guardia sí permite. Con `"bypassPermissions"` el
  comportamiento por defecto (cuando el hook no decide) es aprobar, y el hook
  sigue pudiendo denegar explícitamente -- exactamente lo que `guardia.py`
  necesita para ser la única autoridad real.
- `tools=agente.tools` limita qué tools están disponibles para el modelo, no
  solo cuáles se auto-aprueban (`types.py`, docstring de `tools` vs.
  `allowed_tools`: "To restrict which tools the model may call without being
  prompted, use allowed_tools instead" -- `tools` es la lista disponible).
- `system_prompt=<str>` se traduce a `--system-prompt <str>`
  (`subprocess_cli.py::_build_command`), que sustituye el prompt de Claude
  Code; solo la forma `{"type": "preset", "append": ...}` añade en vez de
  sustituir.
"""

import re
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from enjambre.agentes import Agente
from enjambre.guardia import permitido, ruta_de
from enjambre.tipos import Contexto, Resultado

# Tools que, al permitirse, mueven el estado del agente a "leyendo"/"escribiendo"
# (D11: el estado lo decide la tool usada, no lo que el agente dice de sí mismo).
_ESTADO_POR_TOOL = {
    "Read": "leyendo",
    "Glob": "leyendo",
    "Grep": "leyendo",
    "Write": "escribiendo",
    "Edit": "escribiendo",
}

# Longitud máxima de `respuesta` tras recortar a su última línea no vacía.
_MAX_RESPUESTA = 500


def hacer_hook(agente: Agente, instancia: str, ctx: Contexto):
    """Fabrica el callback `PreToolUse` de este lanzamiento (D8).

    Cierra sobre `agente`/`instancia`/`ctx` porque la firma que exige el SDK
    (`HookCallback`) no tiene sitio para pasárselos de otro modo: la consulta
    solo nos da `tool_name`/`tool_input` del turno en curso.
    """

    async def hook(entrada: dict[str, Any], tool_use_id: str | None, contexto: dict) -> dict:
        tool_name = entrada["tool_name"]
        tool_input = entrada.get("tool_input", {})
        ruta = ruta_de(tool_name, tool_input)

        # Solo Glob lleva `patron`: es el único hueco de traversal que no pasa
        # por `ruta_de` (un `pattern` puede escapar del muro aunque `path` no
        # venga, ver guardia.py). Para el resto, `patron=None` es un no-op.
        patron = tool_input.get("pattern") if tool_name == "Glob" else None

        ok, motivo = permitido(agente.rol, tool_name, ruta, ctx.repo, ctx.salida, patron=patron)

        if not ok:
            ctx.eventos.emitir(
                "denegado", instancia, herramienta=tool_name, detalle=ruta or "", motivo=motivo
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": motivo,
                }
            }

        if tool_name in ("Write", "Edit") and ruta is not None:
            resuelta = Path(ruta)
            if not resuelta.is_absolute():
                resuelta = ctx.salida / resuelta
            ctx.eventos.emitir(
                "fichero", instancia, ruta=str(resuelta.resolve().relative_to(ctx.salida.resolve()))
            )

        return {}

    return hook


def opciones(agente: Agente, ctx: Contexto, hook) -> ClaudeAgentOptions:
    """Construye las `ClaudeAgentOptions` de un lanzamiento (ver cabecera del
    módulo para la justificación de cada elección)."""
    hooks = None
    if hook is not None:
        hooks = {"PreToolUse": [HookMatcher(matcher=None, hooks=[hook])]}

    return ClaudeAgentOptions(
        tools=agente.tools,
        system_prompt=agente.prompt,
        model=agente.modelo,
        cwd=ctx.salida,
        max_turns=ctx.max_turns,
        permission_mode="bypassPermissions",
        setting_sources=[],
        hooks=hooks,
    )


class Traductor:
    """Convierte los mensajes del SDK de un lanzamiento en eventos (vía
    `ctx.eventos`) y en un `Resultado` acumulado (D11)."""

    def __init__(self, instancia: str, ctx: Contexto):
        self._instancia = instancia
        self._ctx = ctx
        self._estado_actual: str | None = None
        self._modelo_real: str | None = None
        self._respuesta = ""
        self._num_herramientas = 0
        self._resultado: ResultMessage | None = None

    def _emitir_estado(self, estado: str) -> None:
        """Emite `estado` solo si cambia -- varias tools de lectura seguidas
        (p.ej. Read, Grep) no deben repetir "leyendo" en el jsonl."""
        if estado != self._estado_actual:
            self._estado_actual = estado
            self._ctx.eventos.emitir("estado", self._instancia, estado=estado)

    def procesar(self, mensaje) -> None:
        if isinstance(mensaje, AssistantMessage):
            if self._modelo_real is None:
                self._modelo_real = mensaje.model
            elif mensaje.model != self._modelo_real:
                # Un modelo real distinto del primero (p.ej. tras un fallback
                # del SDK) es algo que Josem debe poder ver en el jsonl, no
                # solo deducir de `fin_agente.modelo_real` al final del run.
                self._ctx.eventos.emitir(
                    "aviso",
                    self._instancia,
                    texto=f"modelo cambió de {self._modelo_real} a {mensaje.model}",
                )

            for bloque in mensaje.content:
                if isinstance(bloque, ToolUseBlock):
                    self._num_herramientas += 1
                    detalle = ruta_de(bloque.name, bloque.input) or bloque.input.get("pattern", "")
                    self._ctx.eventos.emitir(
                        "herramienta", self._instancia, herramienta=bloque.name, detalle=detalle
                    )
                    estado = _ESTADO_POR_TOOL.get(bloque.name)
                    if estado is not None:
                        self._emitir_estado(estado)
                elif isinstance(bloque, TextBlock):
                    self._respuesta = _recortar(bloque.text)
            return

        if isinstance(mensaje, ResultMessage):
            self._resultado = mensaje
            estado_final = self._estado_final()
            # D11: el estado final (terminado/bloqueado) también viene del
            # guion -- aquí, del propio ResultMessage -- no de que el agente
            # lo "diga" en texto libre sin más (eso solo decide CUÁL de los
            # dos es).
            self._emitir_estado("bloqueado" if estado_final == "bloqueado" else "terminado")

    def _estado_final(self) -> str:
        r = self._resultado
        if re.search(r"\bbloqueado\b", self._respuesta):
            return "bloqueado"
        if r is not None and (r.is_error or r.subtype != "success"):
            return "error"
        return "terminado"

    def resultado(self) -> Resultado:
        r = self._resultado
        usage = (r.usage if r is not None else None) or {}
        tokens_in = (
            usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
        )
        return Resultado(
            estado_final=self._estado_final(),
            respuesta=self._respuesta,
            modelo_real=self._modelo_real,
            duracion_s=(r.duration_ms / 1000 if r is not None else 0.0),
            tokens_in=tokens_in,
            tokens_out=usage.get("output_tokens", 0),
            coste_usd=(r.total_cost_usd or 0) if r is not None else 0.0,
            num_herramientas=self._num_herramientas,
        )


def _recortar(texto: str) -> str:
    """Última línea no vacía de `texto`, recortada a `_MAX_RESPUESTA`."""
    lineas_no_vacias = [l for l in texto.splitlines() if l.strip()]
    ultima = lineas_no_vacias[-1] if lineas_no_vacias else ""
    return ultima[:_MAX_RESPUESTA]


async def lanzar(agente: Agente, instancia: str, encargo: str, ctx: Contexto) -> Resultado:
    """Cumple el contrato `Lanzar` (T5): lanza `agente` con `encargo` y
    devuelve su `Resultado`, emitiendo por el camino los eventos que le tocan
    a `lanzar` -- `estado`/`herramienta`/`denegado`/`fichero`/`aviso` -- nunca
    `lanzado`/`respuesta`/`fin_agente`, que son responsabilidad del guion
    (D5, ver `orquestar.py`)."""
    traductor = Traductor(instancia, ctx)
    hook = hacer_hook(agente, instancia, ctx)
    opts = opciones(agente, ctx, hook)

    async for mensaje in query(prompt=encargo, options=opts):
        traductor.procesar(mensaje)

    return traductor.resultado()
