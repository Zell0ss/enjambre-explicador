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
- `strict_mcp_config` existe como campo de `ClaudeAgentOptions` (`types.py`,
  línea ~2018: "only use MCP servers passed via mcp_servers, ignoring all
  other MCP configurations... Maps to the CLI's --strict-mcp-config flag") --
  base del parche D18.
- El resultado real de un `Write`/`Edit` (no si el guardia lo permitió) llega
  como `ToolResultBlock` dentro de un `UserMessage.content`, nunca dentro de
  un `AssistantMessage` (`_internal/message_parser.py`, case "user" ->
  "tool_result", línea ~124) -- base del parche D17.
- El mensaje `system`/`init` cae en el caso genérico `SystemMessage(subtype,
  data)` del parser (`_internal/message_parser.py`, línea ~299: `case _:
  return SystemMessage(...)`) -- la CLI no lo lista en los subtypes
  especiales que el parser reconoce por nombre, así que su forma la define
  la CLI, no el SDK Python. CONFIRMADO leyendo el binario bundled
  (`_bundled/claude`, minificado; `grep -a 'subtype:x("init")'` localiza el
  esquema zod del mensaje): `u({type:x("system"),subtype:x("init"),...
  tools:A(o()),...})` -- `tools` es un array de strings (`A(o())`) y, a
  diferencia de otros campos del mismo esquema (`betas`, `startup_timing`,
  ...), NO lleva `.optional()`: es un campo requerido por contrato de la CLI
  actual. Aun así se lee defensivamente (`isinstance(..., list)`, no
  `data["tools"]`), por si una CLI futura lo renombra o lo vuelve opcional --
  en ese caso `Traductor` avisa de que la comprobación no se pudo hacer, en
  vez de tratar la ausencia como "cero tools" (ver D18/I4 en el cuerpo del
  módulo).

Parche D16-D18 (2026-10-03): ver `CLAUDE.md` -> "Verificado del SDK" para el
resto del detalle de estas tres citas.
"""

import re
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
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


def hacer_hook(agente: Agente, instancia: str, ctx: Contexto, denegados: set[str] | None = None):
    """Fabrica el callback `PreToolUse` de este lanzamiento (D8).

    Cierra sobre `agente`/`instancia`/`ctx` porque la firma que exige el SDK
    (`HookCallback`) no tiene sitio para pasárselos de otro modo: la consulta
    solo nos da `tool_name`/`tool_input` del turno en curso.

    D17: este hook ya NO emite `fichero` al permitir un Write/Edit -- que el
    guardia permita una escritura no significa que ocurriera; la tool real
    puede rechazarla después (p.ej. `Write` sobre un fichero no leído en la
    sesión). Ese evento ahora sale de `Traductor`, a partir del resultado
    real de la tool (`ToolResultBlock`), más abajo en este módulo.

    `denegados`: conjunto compartido con el `Traductor` de este mismo
    lanzamiento (`lanzar()` crea uno por lanzamiento y lo pasa a los dos).
    Cuando este hook deniega una tool, apunta aquí su `tool_use_id` para que
    `Traductor` sepa que ese id ya se reportó vía `denegado` y no emita
    también un `aviso` de "escritura rechazada" si la CLI, tras la
    denegación, todavía entrega un `ToolResultBlock` con `is_error=True` para
    el mismo id -- dos alertas en pantalla por el mismo hecho. Default `None`
    en vez de `set()` para no compartir un set mutable entre llamadas que se
    olviden de pasarlo explícitamente; si no se pasa, simplemente no hay
    nada que compartir con ningún `Traductor`.
    """
    if denegados is None:
        denegados = set()

    async def hook(entrada: dict[str, Any], tool_use_id: str | None, contexto: dict) -> dict:
        # Este hook es el único sitio donde el guardia (D8) se conecta al
        # SDK real. `permitido()` ya falla cerrado por construcción (Tarea 3),
        # pero el CÓDIGO ALREDEDOR de esa llamada (acceso a `entrada`, el
        # propio `emitir`) no tenía esa garantía: bajo
        # `permission_mode="bypassPermissions"` (ver
        # `opciones()`), una excepción sin capturar aquí no se traduce en una
        # denegación -- el SDK no tiene ninguna decisión que tomar, así que
        # el permiso por defecto de `bypassPermissions` (aprobar) es lo que
        # queda, y la tool se ejecutaría SIN que el guardia haya dicho nada.
        # Es la única frontera de seguridad real de todo el sistema, así que
        # se envuelve entero: cualquier excepción aquí dentro deniega, igual
        # que una denegación normal del guardia.
        try:
            tool_name = entrada["tool_name"]
            tool_input = entrada.get("tool_input", {})
            ruta = ruta_de(tool_name, tool_input)

            # Solo Glob lleva `patron`: es el único hueco de traversal que no
            # pasa por `ruta_de` (un `pattern` puede escapar del muro aunque
            # `path` no venga, ver guardia.py). Para el resto, `patron=None`
            # es un no-op.
            patron = tool_input.get("pattern") if tool_name == "Glob" else None

            ok, motivo = permitido(agente.rol, tool_name, ruta, ctx.repo, ctx.salida, patron=patron)
        except Exception as e:
            # `entrada["tool_name"]` pudo ser precisamente lo que falló: no
            # asumir que existe al construir el evento/motivo de esta rama.
            tool_name = entrada.get("tool_name", "?") if isinstance(entrada, dict) else "?"
            ok, motivo = False, f"error interno del hook: {type(e).__name__}: {e}"
            ruta = None
            # Sin esto, si el fallo ocurrió antes de calcular `patron` más
            # arriba, el `ruta or patron or ""` de abajo sería un NameError
            # dentro de la rama que precisamente tiene que fallar cerrado sin
            # reventar.
            patron = None

        if not ok:
            if tool_use_id is not None:
                denegados.add(tool_use_id)
            ctx.eventos.emitir(
                # `ruta_de` no cubre Glob (solo tiene `pattern`, no
                # `path`/`file_path`): sin caer a `patron`, un Glob denegado
                # siempre mostraba `detalle=""` en pantalla aunque el patrón
                # que se intentó ya se había extraído arriba.
                "denegado", instancia, herramienta=tool_name, detalle=ruta or patron or "", motivo=motivo
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": motivo,
                }
            }

        return {}

    return hook


def opciones(agente: Agente, ctx: Contexto, hook) -> ClaudeAgentOptions:
    """Construye las `ClaudeAgentOptions` de un lanzamiento (ver cabecera del
    módulo para la justificación de cada elección).

    D18: `strict_mcp_config=True` y sin `mcp_servers` -- hipótesis del gasto
    anómalo de la prueba de humo (836K tokens de entrada en una pasada del
    novato): sin esto, las tools de servidores MCP de plugins/conectores de
    este entorno viajan en cada turno aunque ningún agente del enjambre las
    use nunca (ninguna está en `agente.tools`).
    """
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
        strict_mcp_config=True,
    )


def _ruta_relativa_a_salida(ruta: str, salida: Path) -> str | None:
    """Resuelve `ruta` (absoluta o relativa a `salida`, el cwd del agente) y
    la expresa relativa a `salida` -- misma normalización que hacía antes el
    hook (D17) al emitir `fichero`. `None` si `ruta` no cae bajo `salida` o
    es inválida (byte nulo, etc.): no debería ocurrir para un Write/Edit que
    el guardia ya aprobó, pero `Traductor` no es quien decide el muro (D8),
    así que no asume nada sobre `ruta`."""
    try:
        resuelta = Path(ruta)
        if not resuelta.is_absolute():
            resuelta = salida / resuelta
        return str(resuelta.resolve().relative_to(salida.resolve()))
    except (OSError, ValueError, RuntimeError):
        return None


def _texto_de_resultado(content: object) -> str:
    """Extrae el texto plano de un `ToolResultBlock.content`, que puede ser
    una cadena o una lista de bloques `{"type": "text", "text": ...}` (forma
    real de un error de `Write`/`Edit`, Tarea 7/D17)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            bloque["text"]
            for bloque in content
            if isinstance(bloque, dict) and isinstance(bloque.get("text"), str)
        )
    return ""


class Traductor:
    """Convierte los mensajes del SDK de un lanzamiento en eventos (vía
    `ctx.eventos`) y en un `Resultado` acumulado (D11)."""

    def __init__(
        self,
        instancia: str,
        ctx: Contexto,
        agente: Agente | None = None,
        denegados: set[str] | None = None,
    ):
        self._instancia = instancia
        self._ctx = ctx
        # `agente` es opcional (default None) solo para no romper las pruebas
        # que construyen un `Traductor` suelto sin agente de verdad; `lanzar()`
        # siempre lo pasa. Lo usa la comprobación de D18/I4 de abajo (tools
        # inesperadas en el mensaje `init`) -- sin agente no hay con qué
        # comparar, así que esa comprobación simplemente no hace nada.
        self._agente = agente
        # Conjunto compartido con el hook (`hacer_hook`) de este mismo
        # lanzamiento: ids de `tool_use_id` que el guardia ya denegó (y ya
        # reportó vía `denegado`). `None` para las pruebas que construyen un
        # `Traductor` suelto sin hook -- sin conjunto compartido, ningún id
        # puede estar "ya denegado", así que el comportamiento de D17 sigue
        # exactamente igual que antes de este arreglo.
        self._denegados = denegados
        self._estado_actual: str | None = None
        self._modelo_real: str | None = None
        self._respuesta = ""
        self._num_herramientas = 0
        self._resultado: ResultMessage | None = None
        # D17: tool_use_id -> ruta (relativa a salida) de cada Write/Edit en
        # vuelo, para emitir `fichero`/`aviso` cuando llegue su resultado real
        # (`ToolResultBlock`, en un `UserMessage` posterior), no al permitirlo.
        self._escrituras_en_vuelo: dict[str, str] = {}

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
                    # D17: recordar a qué ruta apunta este Write/Edit para
                    # cuando llegue su resultado real -- el `fichero`/`aviso`
                    # ya no sale de si el guardia lo permitió (eso lo hacía el
                    # hook antes), sino de si la tool de verdad lo escribió.
                    if bloque.name in ("Write", "Edit"):
                        ruta = ruta_de(bloque.name, bloque.input)
                        if ruta is not None:
                            rel = _ruta_relativa_a_salida(ruta, self._ctx.salida)
                            if rel is not None:
                                self._escrituras_en_vuelo[bloque.id] = rel
                elif isinstance(bloque, TextBlock):
                    self._respuesta = _recortar(bloque.text)
            return

        if isinstance(mensaje, UserMessage):
            # D17: aquí llega el resultado real de un Write/Edit permitido
            # antes por el hook -- `is_error` dice si la tool lo rechazó
            # (p.ej. `Write` sobre un fichero no leído en la sesión).
            if isinstance(mensaje.content, list):
                for bloque in mensaje.content:
                    if not isinstance(bloque, ToolResultBlock):
                        continue
                    ruta = self._escrituras_en_vuelo.pop(bloque.tool_use_id, None)
                    if ruta is None:
                        continue  # no era un Write/Edit que estuviéramos siguiendo
                    if bloque.is_error:
                        if self._denegados is not None and bloque.tool_use_id in self._denegados:
                            # El hook ya reportó esta misma llamada como
                            # `denegado`; si la CLI, tras la denegación,
                            # todavía entrega este `ToolResultBlock` de
                            # error, no emitir también un `aviso` -- sería
                            # la misma alerta dos veces en pantalla. Se quita
                            # del conjunto para no dejarlo creciendo sin
                            # límite dentro de esta misma sesión de `lanzar`.
                            self._denegados.discard(bloque.tool_use_id)
                            continue
                        error = _texto_de_resultado(bloque.content)[:200]
                        self._ctx.eventos.emitir(
                            "aviso",
                            self._instancia,
                            texto=f"escritura rechazada: {ruta}: {error}",
                        )
                    else:
                        self._ctx.eventos.emitir("fichero", self._instancia, ruta=ruta)
            return

        if isinstance(mensaje, SystemMessage):
            # Comprobación en vivo, cada run, de que `tools=agente.tools`
            # (verificado una vez en Tarea 7) sigue siendo la lista real de
            # herramientas disponibles para esta sesión -- no solo lo que se
            # pidió. Relacionado con D18/I4: si aquí aparecieran tools MCP de
            # plugins/conectores, sería la prueba de que `strict_mcp_config`
            # no bastó. La clave `tools` del mensaje `init` es un array de
            # strings REQUERIDO por el esquema zod de la CLI (`tools:A(o())`,
            # sin `.optional()` -- ver cabecera del módulo), así que ausente
            # o con otra forma es una CLI que cambió el contrato, no "cero
            # tools": tratarlo como lista vacía escondería justo el caso que
            # esta comprobación existe para pescar, así que avisa en vez de
            # callar.
            if mensaje.subtype == "init" and self._agente is not None:
                tools_init = mensaje.data.get("tools")
                if not isinstance(tools_init, list):
                    self._ctx.eventos.emitir(
                        "aviso",
                        self._instancia,
                        texto="init sin lista tools: comprobación D18/I4 no aplicada",
                    )
                else:
                    extra = [t for t in tools_init if t not in self._agente.tools]
                    if extra:
                        self._ctx.eventos.emitir(
                            "aviso",
                            self._instancia,
                            texto=f"init trae tools no pedidas: {', '.join(extra)}",
                        )
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
        # Corrección tras la revisión de la Tarea 7: el detector de
        # "bloqueado" era sensible a mayúsculas y no distinguía una negación
        # ("no estoy bloqueado") de una afirmación. Los dos lookbehind son de
        # anchura fija cada uno (lo único que exige `re`), así que se pueden
        # encadenar: ninguno de los dos bloquea por sí solo "tampoco
        # bloqueado" (no es la negación que había que excluir -- el
        # arquitecto no la pidió), pero sí "no bloqueado" y "no estoy
        # bloqueado". `bloquead[oa]` cubre también la forma femenina
        # ("bloqueada").
        #
        # Regresión encontrada en revisión (re-parcheada aquí): la reescritura
        # de arriba había perdido los `\b` originales. Sin ellos,
        # "desbloqueado" (justo el sentido CONTRARIO: acceso concedido, no
        # bloqueado) colaba un falso positivo -- "bloquead[oa]" es substring
        # de "desbloqueado". Y en la otra dirección, sin `\b` DENTRO del
        # lookbehind, "casino bloqueado" se denegaba por error: los 3
        # caracteres que preceden a "bloqueado" ahí son "no " (de "casiNO "),
        # aunque no sean la palabra "no" -- el lookbehind necesita su propio
        # `\b` para exigir que esos caracteres formen la palabra suelta "no",
        # no cualquier substring que termine igual. `\bbloquead[oa]\b` exige
        # además un límite de palabra tras la raíz, para no colar "bloqueados"
        # dentro de otra palabra mayor.
        if re.search(r"(?<!\bno )(?<!\bno estoy )\bbloquead[oa]\b", self._respuesta, re.IGNORECASE):
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
            num_turns=(r.num_turns if r is not None else 0),
        )


def _recortar(texto: str) -> str:
    """Última línea no vacía de `texto`, recortada a `_MAX_RESPUESTA`.

    `.strip()` sobre la línea elegida, no solo para decidir si cuenta como
    "no vacía": sin él, una línea con espacio/tabulación de sobra pero sin
    contenido visible pasaría el filtro `if l.strip()` y se usaría tal cual,
    pisando una `respuesta` previa válida con basura en blanco.
    """
    lineas_no_vacias = [l.strip() for l in texto.splitlines() if l.strip()]
    ultima = lineas_no_vacias[-1] if lineas_no_vacias else ""
    return ultima[:_MAX_RESPUESTA]


async def lanzar(agente: Agente, instancia: str, encargo: str, ctx: Contexto) -> Resultado:
    """Cumple el contrato `Lanzar` (T5): lanza `agente` con `encargo` y
    devuelve su `Resultado`, emitiendo por el camino los eventos que le tocan
    a `lanzar` -- `estado`/`herramienta`/`denegado`/`fichero`/`aviso` -- nunca
    `lanzado`/`respuesta`/`fin_agente`, que son responsabilidad del guion
    (D5, ver `orquestar.py`)."""
    # Compartido entre el hook y el `Traductor` de este lanzamiento (D17 +
    # arreglo de la doble alerta): se crea una vez aquí, uno por lanzamiento
    # -- nunca como default mutable de `hacer_hook`/`Traductor`, que viviría
    # entre llamadas distintas.
    denegados: set[str] = set()
    traductor = Traductor(instancia, ctx, agente, denegados)
    hook = hacer_hook(agente, instancia, ctx, denegados)
    opts = opciones(agente, ctx, hook)

    async for mensaje in query(prompt=encargo, options=opts):
        traductor.procesar(mensaje)

    return traductor.resultado()
