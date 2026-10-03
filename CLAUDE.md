# enjambre — Arquitectura

## Qué es

Orquestador Python que lanza 7 agentes Claude vía Claude Agent SDK, más una pantalla de píxeles que visualiza la ejecución. Spec: `/data/library/mi-wiki/docs/Obsidian/30-projects/enjambre-explicador/ENJAMBRE-DISENIO.md`.

## Comandos

```bash
# Tests
.venv/bin/pytest -v

# Ejecutar orquestador sobre un repo (desarrollo con repo fake/test)
python -m enjambre.orquestar --repo <ruta> [--falso]

# Arrancar pantalla
python -m enjambre.pantalla
```

## Reglas

**Código:**
- **Python 3.12** (`.venv` local, nunca global ni conda; `.venv` en .gitignore).
- **PEP 8** + type hints donde aclaren. Comentarios: el *por qué*, no el *qué*. Citar `D<n>` en el código en la costura que gobierna.
- **Solo `enjambre/lanzador.py` importa `claude_agent_sdk`** (D6).

**Periféricos (prohibido modificar):**
- **No tocar `.claude/agents/*.md`** — son symlinks al vault, cuidados por Josem y el arquitecto. 
- **No tocar el vault de Obsidian** (lo lleva el arquitecto).
- **No tocar `/data/logcentral/`** (lo hace Josem, ver Tarea 1).

**Pruebas y API:**
- **Las pruebas no llaman a la API.** Nada en `pytest` gasta tokens. Llamadas reales solo en pasos marcados [API] con modelo indicado.

**Pantalla:**
- Escucha por defecto en `100.87.64.121:8790` (Tailscale seb01), nunca `0.0.0.0`. 
- Pruebas en `127.0.0.1` con puerto efímero.
- Estados de agente exactos: `esperando`, `leyendo`, `escribiendo`, `bloqueado`, `terminado`.
- Tipos de evento exactos (§4 spec): `run_inicio`, `lanzado`, `estado`, `herramienta`, `denegado`, `fichero`, `respuesta`, `fin_agente`, `aviso`, `vuelta`, `run_fin`.

**Git:**
- Commits pequeños, `git add` de ficheros concretos (nunca `git add .`).
- Mensaje: terminado en `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Logs: LogCentral (`enjambre.registro.log` en `/data/enjambre-explicador/logs/`).

## Verificado del SDK

Contra `claude-agent-sdk==0.2.163` instalado en `.venv`, leyendo
`claude_agent_sdk/types.py` y `claude_agent_sdk/_internal/transport/subprocess_cli.py`,
y confirmado empíricamente en el paso [API] de la Tarea 7 (`ps aux` sobre el
subproceso real + contenido de `eventos.jsonl` + disco).

1. **`setting_sources=[]` aísla de verdad** (I2 resuelta: no hay rastro del
   CLAUDE.md global de Josem en ninguna respuesta del novato). `types.py:2297-2306`:
   "Pass `[]` to disable filesystem settings (SDK isolation mode)". Con
   `setting_sources=[]` explícito (no `None`), `_apply_skills_defaults()`
   (`subprocess_cli.py:543-568`) no lo reescribe (solo pone `["user","project"]`
   si venía `None` y hay `skills`), y `_build_command` emite
   `--setting-sources=` vacío (`subprocess_cli.py:729-730`) — confirmado en el
   argv real del subproceso lanzado por el smoke test.
2. **El hook `PreToolUse` se dispara con independencia del `permission_mode`**;
   se usa `permission_mode="bypassPermissions"`, no `"dontAsk"`.
   `types.py:2171-2173` (docstring de `can_use_tool`): "To observe or gate
   *every* tool call regardless of permission rules, use a `PreToolUse` hook
   instead". Con `"bypassPermissions"` el comportamiento por defecto (cuando
   el hook no decide) es aprobar, y el hook sigue pudiendo denegar
   explícitamente (`types.py:1868-1874`: "bypassPermissions' auto-approves
   every tool call (except explicit deny rules)"). `"dontAsk"` habría sido la
   opción equivocada: `types.py:2032` — "deny if not pre-approved [por reglas
   `allow` de settings]", y no tenemos reglas `allow` (`setting_sources=[]`),
   así que denegaría todo lo que el guardia permite devolviendo `{}`.
3. **`tools=agente.tools` limita qué tools están disponibles, no solo cuáles
   se auto-aprueban.** `types.py:1974-1994`: "To restrict which tools the
   model may call without being prompted, use `allowed_tools` instead" —
   `tools` es la lista disponible; `allowed_tools` (que no usamos, el hook
   gobierna todo) es solo sobre el prompt de confirmación.
4. **`system_prompt=<str>` sustituye el prompt de Claude Code, no se añade.**
   `subprocess_cli.py:576-589`: un `str` se traduce a `--system-prompt <str>`;
   solo `{"type":"preset","append":...}` usa `--append-system-prompt`.
   Confirmado en el argv real: el `--system-prompt` del subproceso del novato
   es exactamente `agente.prompt` (el cuerpo de `novato.md`), sin ningún
   texto adicional de Claude Code antes o después.

**Hallazgo no pedido, crítico (encontrado en el paso [API], no en el código
del SDK):** el tool real `Write` del CLI (hardcodeado en el binario de
`_bundled/claude`, cadena literal `"File has not been read yet. Read it
first before writing to it."`) **exige haber leído con éxito un fichero
existente en la misma sesión antes de poder sobrescribirlo** — igual que
`Edit`, pero esto no estaba documentado para `Write` en los hechos ya
comprobados del brief. No es una opción de `ClaudeAgentOptions`: no hay forma
de desactivarlo desde `lanzador.py`.

Esto choca con el muro del novato (D8): puede escribir `dudas.md` pero tiene
prohibido leerlo (para no sesgarse con sus propias dudas de la vuelta
anterior). En la primera vuelta de un run real, `dudas.md` no existe aún, así
que `Write` no pide lectura previa y todo funciona. **Desde la vuelta 2 en
adelante, `dudas.md` ya existe en disco (de la vuelta 1) y el novato nunca
podrá sobrescribirlo**: cualquier intento de `Write` falla con ese error, el
agente lo reporta como "No puedo completar la tarea" (`ResultMessage.result`
real capturado en el diagnóstico), y `orquestar.py` interpretaría eso como
`fallo:novato:<estado>`, parando el run. Reproducido limpio con un agente
sintético minimal (rol `novato`, prompt de una sola instrucción) sobre un
`dudas.md` preexistente: dos intentos de `Write`, ambos rechazados por el CLI
con el mismo mensaje, cero reescrituras en disco. **No se toca `guardia.py`
ni `orquestar.py` en esta tarea** (fuera del alcance de la Tarea 7); queda
pendiente de decisión del arquitecto. Arreglo más simple que no requiere
tocar el muro: que `orquestar.py` borre/trunque `salida/dudas.md` antes de
cada lanzamiento del novato, para que `Write` lo vea como fichero nuevo.

**Smoke test real (Paso 2, novato/Haiku) contra una copia de
`tests/fixtures/agora_test/`:** por el mismo motivo (el fixture ya trae un
`dudas.md` de una vuelta anterior), el novato leyó `articulo.md` con éxito
pero **no logró reescribir `dudas.md`** — su intento de `Write` fue el que
chocó con el bloqueo de arriba, y su respuesta final (una línea) reportó la
ruta y "listo" igualmente (el agente no distingue "lo escribí" de "la tool
dijo que no podía porque el guardia me negó el Read" en su resumen de una
línea; el fallo real sí quedó en el campo `result` crudo del `ResultMessage`,
no visible en el recorte a 500 caracteres de `Traductor.respuesta`). El resto
de comprobaciones del Paso 2 sí se confirmaron: modelo Haiku, `herramienta`
Read de `articulo.md`, varios `denegado` (rutas con el prefijo `SALIDA/`
tomado literalmente del encargo, y el intento de releer `dudas.md`), sin
rastro del CLAUDE.md global. Ver `tomorrow.md` para el `fin_agente` real.
