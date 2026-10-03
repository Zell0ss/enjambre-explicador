# Sesión siguiente

## Estado

**Tareas 1-7: HECHAS**

- Tarea 1: cimientos del repo, fixtures, logger LogCentral.
- Tarea 2: `enjambre/agentes.py` (`cargar`, `ROLES`, `Agente`).
- Tarea 3: `enjambre/guardia.py` (`permitido`, el muro de permisos, D8).
- Tarea 4: `enjambre/parsers.py` (`ids_de_piezas`, `fallos`, `veredicto`, `SalidaIlegible`).
- Tarea 5: `enjambre/tipos.py` + `enjambre/eventos.py` (`Resultado`, `Contexto`, `Lanzar`, `Eventos`).
- Tarea 6: `enjambre/orquestar.py` (el guion: `orquestar`, `main`) + `enjambre/falso.py`
  (`hacer_lanzar_falso`, el `lanzar` de mentira para probar y hacer demos sin gastar
  tokens). Tests: `tests/test_orquestar.py` (12 pruebas, todas verdes). Suite completa:
  63 passed.
- Smoke test manual (`--falso` sobre `/data/agora`): termina en ~6 s con `aprobado`,
  `jq -c .tipo salidas/agora/*/eventos.jsonl` muestra todos los tipos salvo `denegado`
  y `aviso` (ninguno de los dos aplica sin el guardia real ni un modelo real cambiando
  de versión).
- Confirmado por inspección de código + import con `claude_agent_sdk` bloqueado:
  ningún módulo de la Tarea 6 importa el SDK a nivel de módulo; `main()` lo importa
  dentro de su propio cuerpo (D6).
- Tarea 7: `enjambre/lanzador.py` (`lanzar`, `opciones`, `hacer_hook`, `Traductor`) —
  la única costura con `claude_agent_sdk` (D6), confirmado por grep sobre todo el
  repo. Tests: `tests/test_lanzador.py` (5 pruebas, todas verdes a la primera).
  Suite completa: 88 passed. Investigación del SDK instalado + smoke test real
  [API] con el novato: ver `CLAUDE.md` → "Verificado del SDK" (las 4 preguntas del
  brief quedaron confirmadas; además salió un hallazgo no pedido, crítico, sobre
  `Write` y ficheros preexistentes — ver siguiente sección).

## Siguiente

**Fin de H3 por la parte del programador** (instrucción explícita del plan,
`task-7-brief.md`). El primer run real completo
(`python -m enjambre.orquestar --repo /data/agora`) lo lanza Josem.

**Bloqueante para un run real con ≥2 vueltas, necesita decisión del arquitecto
antes de intentarlo** (no se ha tocado `guardia.py` ni `orquestar.py` en la
Tarea 7 — fuera de su alcance): el tool real `Write` del CLI exige haber leído
con éxito un fichero existente en la misma sesión antes de poder
sobrescribirlo (mismo invariante que `Edit`, hardcodeado en el binario,
`"File has not been read yet. Read it first before writing to it."` — no es
una opción de `ClaudeAgentOptions`). El novato puede escribir `dudas.md` pero
tiene prohibido leerlo (D8, para no sesgarse con sus dudas de la vuelta
anterior). En la vuelta 1 de un run real `dudas.md` no existe aún, así que no
pasa nada; **desde la vuelta 2, `dudas.md` ya existe (de la vuelta 1) y el
novato ya no puede reescribirlo nunca** — `Write` falla, el novato no termina
limpio, `orquestar.py` para el run con `fallo:novato:<estado>`. Reproducido
limpio con un agente sintético (ver `CLAUDE.md` → "Verificado del SDK" para
el detalle y la cita literal del error). Arreglo más simple que no toca el
muro: que `orquestar.py` borre/trunque `salida/dudas.md` antes de cada
lanzamiento del novato. Queda para decidir con el arquitecto (probablemente
un `D<n>` nuevo en `ENJAMBRE-DISENIO.md`), no implementado aquí.

Las dos incógnitas que la Tarea 3 había dejado pendientes para cuando se
conectara el SDK real quedan resueltas:
- **Glob/Grep, path traversal vía patrón:** resuelto. `hacer_hook` (Tarea 7)
  pasa `patron=tool_input.get("pattern")` a `permitido()` específicamente para
  `Glob` (el parche de la Tarea 3 al guardia ya validaba la forma del
  patrón; solo faltaba conectarlo a un hook real).
- **I2 — ¿`setting_sources=[]` aísla de verdad?:** confirmado que sí, por
  código (`types.py`) y empíricamente (ninguna respuesta del novato mostró
  rastro del CLAUDE.md global de Josem; el argv real del subproceso lleva
  `--setting-sources=` vacío).

### `fin_agente` real del smoke test [API] (novato, Haiku)

No viene literal del jsonl porque el smoke test llamó a `lanzar()` directamente
(sin pasar por `orquestar.py`, que es quien emite `fin_agente`); estos son los
mismos campos, tomados del `Resultado` real devuelto:

```json
{"tipo": "fin_agente", "agente": "novato", "estado_final": "terminado",
 "modelo_real": "claude-haiku-4-5-20251001", "duracion_s": 157.245,
 "tokens_in": 836833, "tokens_out": 14274, "coste_usd": 0.6600866,
 "num_herramientas": 5}
```

`estado_final` salió `"terminado"` porque el `ResultMessage.subtype` fue
`"success"` y la respuesta no matcheaba `\bbloqueado\b` — pero el propio
intento de `Write` de `dudas.md` chocó con el bloqueo de arriba (no se
reescribió). El `Traductor` no tiene manera de distinguir "escribí bien" de
"la tool rechazó mi escritura pero seguí sin bloquearme": ese distingo solo
existe en el campo `result` crudo del `ResultMessage` (visible en el smoke
test, no en los 500 caracteres de `respuesta`). Anotado como hallazgo, no
arreglado — no está en el contrato de `Traductor` que pide el brief.

### Diagnóstico [API] post-D18: I4

Una sola llamada real (novato, Haiku), tras el parche D16-D18
(`strict_mcp_config=True` en `enjambre/lanzador.py::opciones()`), para
confirmar o falsar I4 ("el gasto anómalo de 836K tokens de entrada del smoke
test de la Tarea 7 venía de tools MCP de este entorno viajando en cada turno,
sin filtrar por `strict_mcp_config`"). Repo real, sin tocar nada committeado:
copia temporal de `tests/fixtures/agora_test/` en `/tmp` (con `dudas.md`
borrado de la copia, para que el `Write` del novato no chocara con D16 por un
motivo ajeno a esta medición), `REPO=/data/agora` (el novato no lee nada
`REPO`-scoped), `SALIDA=` esa copia, `VUELTA=1`, encargo construido con el
`_encargo()` real de `orquestar.py` (incluye la línea D18 de `SALIDA/x`
significa `x`). Script suelto en el scratchpad de la sesión, no versionado.

**`usage` crudo del `ResultMessage`:**

```json
{
  "input_tokens": 3044,
  "cache_creation_input_tokens": 18070,
  "cache_read_input_tokens": 11163,
  "output_tokens": 7349,
  "output_tokens_details": {"thinking_tokens": 5176},
  "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
  "service_tier": "standard",
  "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 18070},
  "inference_geo": "not_available",
  "iterations": [
    {"input_tokens": 8, "output_tokens": 252, "cache_read_input_tokens": 11163,
     "cache_creation_input_tokens": 6907,
     "cache_creation": {"ephemeral_5m_input_tokens": 6907, "ephemeral_1h_input_tokens": 0},
     "type": "message"}
  ],
  "speed": "standard",
  "fallback_credit": null
}
```

**Init `SystemMessage.tools`:** `["Read", "Write"]` (longitud 2) — exactamente
`agente.tools` de `novato.md`, cero tools extra (ninguna MCP de plugins/
conectores de este entorno). La comprobación en vivo D18/I4 del propio
`Traductor` (lanzador.py §`procesar`, caso `SystemMessage`) no emitió ningún
`aviso` de "tools no pedidas", coherente con esto.

**`Resultado` (contrato `enjambre.tipos.Resultado`):**

```
estado_final=terminado
modelo_real=claude-haiku-4-5-20251001
duracion_s=80.597
tokens_in=32277   (3044 + 18070 + 11163)
tokens_out=7349
coste_usd=0.0645568
num_herramientas=2
num_turns=3
```

**Veredicto I4: CONFIRMADO.** `tokens_in=32277`, muy por debajo del umbral de
falsación (200K) y casi 26× menos que los 836,833 del smoke test original
(`fin_agente` de arriba) con el mismo rol, mismo modelo, fixture equivalente.
`strict_mcp_config=True` (D18) fue un contribuyente real a la anomalía. No se
ha hecho ninguna llamada adicional para aislar si el resto de la diferencia
(32K vs. lo que costaría un novato "limpio" sin ningún MCP de por medio) es
ruido de fixture/cache o algo más — queda para quien retome I4 si hiciera
falta, no se ha chequeado aquí (tope: una sola llamada, según el brief).

Fixtures committeadas (`tests/fixtures/agora_test/`) sin tocar — solo se usó
una copia temporal en `/tmp`, borrada tras el diagnóstico junto con el script
suelto.

## Bloqueos / le toca a Josem

**LogCentral vector.toml:** Para que LogCentral recoja los logs de enjambre, hay que añadir en `/data/logcentral/vector/vector.toml`:

1. Nuevo `[sources.enjambre]` con `include = ["/data/enjambre-explicador/logs/enjambre.log"]`
2. Nuevo `[transforms.parse_enjambre]` copiado de `parse_saxhero` pero con nombre `parse_enjambre`
3. Añadir `parse_enjambre` a los dos `inputs = [...]` que agregan todos los parse (buscar líneas que agreguen todos los parse)
4. Reiniciar Vector: `docker compose -f /data/logcentral/vector/docker-compose.yml restart`

Sin esto, `/data/enjambre-explicador/logs/enjambre.log` se crea pero no se indexa en LogCentral.
