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
node --test tests/js/*.mjs

# Ejecutar orquestador (desarrollo)
python -m enjambre.orquestar --repo <ruta> [--falso]

# Arrancar pantalla
python -m enjambre.pantalla
```

La pantalla sirve una lista de runs en `/`; cada uno con un enlace a su
repetición (reproduce `eventos.jsonl` entero, con barra y velocidad) y,
mientras sigue en marcha, otro a verlo en directo (SSE, en vivo, sin barra).

Ver `CLAUDE.md` para contexto arquitectónico.
