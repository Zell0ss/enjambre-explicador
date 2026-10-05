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

# Continuar un run parado (D24) -- excluye --repo/--run/--falso, salen del propio run
python -m enjambre.orquestar --reanudar <salidas/repo/run> [--tope-usd] [--max-vueltas]

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
`pantalla/mesa.js`. Un enlace "← volver" en la cabecera regresa a la
portada (lista de runs / formulario de lanzar) sin tocar la URL a mano.

Un run parado por cualquier motivo salvo `aprobado` (sobre todo el tope de
coste) se puede **continuar** (D24): la cabecera muestra un botón
"Continuar" (tanto en directo como en repetición) con el tope extra en $ y
las vueltas máximas: salta al mismo directo y sigue exactamente donde se
quedó, sin relanzar lo que ya está hecho ni gastar de más (D25 borra antes
los ficheros que cada paso relanzado va a crear, para que la tool `Write`
real no se encuentre con uno que no ha leído en su sesión). El tope que se
da al continuar es dinero EXTRA, no un total nuevo; el modo (`--falso` o
real) lo decide siempre el propio run, nunca quien lo continúa.

Ver `CLAUDE.md` para contexto arquitectónico.


[Explicacion hecha con el propio enjambre](articulo.md)