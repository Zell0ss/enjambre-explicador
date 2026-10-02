# enjambre — Arquitectura

## Qué es

Orquestador Python que lanza 7 agentes Claude vía Claude Agent SDK, más una pantalla de píxeles que visualiza la ejecución. Spec: `/data/library/mi-wiki/docs/Obsidian/30-projects/enjambre/`.

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

- **Python 3.12**: venv local, nunca global ni conda.
- **PEP 8** + type hints donde añaden claridad, comentarios explican el *por qué*.
- Commits pequeños, enfocados, descriptivos.
- Logs: LogCentral (`enjambre.registro.log`).

## Verificado del SDK

(Rellena tras Tarea 7)
