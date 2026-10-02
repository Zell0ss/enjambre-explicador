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

(Rellena tras Tarea 7)
