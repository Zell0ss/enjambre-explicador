# Sesión siguiente

## Estado

**Tareas 1-6: HECHAS**

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

## Siguiente

**Fin de H2. Para y pide revisión al arquitecto antes de la Tarea 7** (instrucción
explícita del plan, `task-6-brief.md`).

Tarea 7: `enjambre/lanzador.py` — la única costura con `claude_agent_sdk` (D6). Lee
§3.2 de `ENJAMBRE-DISENIO.md` antes de empezar: hay que comprobar contra el SDK
instalado (`claude-agent-sdk==0.2.163`) los nombres exactos de las opciones
(`system_prompt`, `model`, `tools`/`allowed_tools`, `setting_sources=[]`, `cwd`,
`max_turns`, `permission_mode`, `hooks`), y si el hook `PreToolUse` (→
`guardia.permitido`) se ejecuta aunque el permiso ya esté concedido (si no, usar
`can_use_tool`). Dejar anotado en `CLAUDE.md` del repo qué se verificó ("Verificado
del SDK").

Dos incógnitas abiertas que la Tarea 3 (guardia) dejó pendientes para cuando se
conecte el SDK real:
- **Crítico parcado en T3 (Glob/Grep, path traversal vía patrón):** el guardia no
  valida el contenido del `pattern` de Glob (solo evalúa `cwd` cuando no hay ruta
  explícita) — comprobar si la herramienta Glob real del SDK permite patrones con
  `..` o absolutos que se saltarían el muro.
- **I2 (`ENJAMBRE-DISENIO.md` incógnitas):** ¿`setting_sources=[]` aísla de verdad al
  agente de `~/.claude/CLAUDE.md`? Falsación: un agente que cita en su respuesta algo
  que solo está en ese CLAUDE.md global indica que lo cargó.

## Bloqueos / le toca a Josem

**LogCentral vector.toml:** Para que LogCentral recoja los logs de enjambre, hay que añadir en `/data/logcentral/vector/vector.toml`:

1. Nuevo `[sources.enjambre]` con `include = ["/data/enjambre-explicador/logs/enjambre.log"]`
2. Nuevo `[transforms.parse_enjambre]` copiado de `parse_saxhero` pero con nombre `parse_enjambre`
3. Añadir `parse_enjambre` a los dos `inputs = [...]` que agregan todos los parse (buscar líneas que agreguen todos los parse)
4. Reiniciar Vector: `docker compose -f /data/logcentral/vector/docker-compose.yml restart`

Sin esto, `/data/enjambre-explicador/logs/enjambre.log` se crea pero no se indexa en LogCentral.
