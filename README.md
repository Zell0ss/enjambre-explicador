# enjambre

Orquestador Python que lanza 7 agentes Claude vía Claude Agent SDK, más una pantalla de píxeles que visualiza la ejecución.

## Instalación

```bash
.venv/bin/pip install -r requirements.txt
```

## Uso

```bash
# Tests
.venv/bin/pytest -v

# Ejecutar orquestador (desarrollo)
python -m enjambre.orquestar --repo <ruta> [--falso]

# Arrancar pantalla
python -m enjambre.pantalla
```

Ver `CLAUDE.md` para contexto arquitectónico.
