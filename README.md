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

La propia portada tiene un formulario para lanzar un run nuevo (repo, tope
en $, vueltas, casilla "falso (sin gastar)") sin tocar la terminal: lanza un
subproceso `python -m enjambre.orquestar` aparte y salta a verlo en directo,
con un botón Parar mientras sigue en marcha. El repo tiene que estar bajo
`/data` (ver `enjambre/pantalla.py`, `crear_servidor(..., raiz_repos=...)`).

Un run en marcha (directo o repetición) se ve como **la mesa de papeles**
(D22): una rejilla de tarjetas HTML en el orden del flujo (cartógrafo,
despiezador, lectores, trazador, redactor, verificador, novato), cada una
con su sprite animado, lo que lee/escribe ahora y las fichas que deja
(clic abre su contenido). Debajo, el panel "Ahora" (qué lee cada agente
activo), la bitácora y las puertas del guardia, que se encienden en rojo
(ámbar la del verificador) con cada denegado/salto. Ver
`pantalla/mesa.js`.

Ver `CLAUDE.md` para contexto arquitectónico.
