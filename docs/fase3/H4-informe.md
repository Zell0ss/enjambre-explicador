# H4 — informe (la página)

Trabajo en el worktree `/data/enjambre-explicador-h4`, rama `feature/fase3-h4` (por el anexo §6 de la
revisión de H3). `.venv` propio; sin `.env`. `/data/enjambre-explicador` sigue en `main`, limpio. Incluye los
retoques R4 y R5 de la revisión de H3 (`b7db79d`, ya en `main`).

## Hecho

- **Tarea 25, servidor** (`474aeae`, `enjambre/pantalla.py`):
  - `_valida_lanzar` acepta URL o ruta con `fuente.resolver(raiz_local=raiz_repos)` y devuelve la fuente canónica.
  - El `comando` por defecto es `python -m enjambre.leer`. `/api/lanzar` manda `<fuente> --salidas … --tope-usd …
    --max-vueltas … --run <nombre>-<fecha> --cerrojo … [--falso]`; `/api/reanudar` manda `--reanudar <salida> …`.
    La respuesta 202 sigue siendo `{"repo": <nombre>, "run": <run>}`.
  - **409** `"hay otro run en marcha (¿la cola?)"` si `cerrojo.ocupado(servidor.cerrojo)`, en `/api/lanzar` y en
    `/api/reanudar`, además del control de proceso propio de siempre.
  - `/api/lanzador`: si el proceso acabó **sin crear el run**, devuelve `{"en_marcha": false, "repo", "run",
    "codigo", "error"}` (última línea no vacía de su log). Si el run existe, la forma de siempre.
  - `/api/directo` ya no espera 30 s fijos: espera mientras el proceso de **ese** run siga vivo (hasta 15 min por
    si se cuelga) y da 404 en cuanto muere sin crearlo. Se lee "terminado" antes de mirar el disco, para no perder
    un run creado justo antes de salir.
  - `POST /api/encolar` (201 nueva, 200 ya estaba, 400 inválida; mismas cabeceras anti-CSRF) y `GET /api/cola`.
  - `crear_servidor(..., raiz_cola=None, cerrojo=None)`, resueltos al llamar (no en la firma: el problema de R2).
- **Tarea 25, página** (`f169749`, `pantalla/index.html`, `pantalla/mesa.js`): campo con placeholder "URL de
  GitHub o ruta bajo /data", **Lanzar ahora** y **Encolar para esta noche**, bloque "Esta noche" en la portada
  (nombre, encolado, intentos, último error/motivo; las rendidas aparte), y el error del lanzador en el directo
  cuando el proceso muere antes del run.
- Además (`4dc8843`): `encolar` no duplica una fuente por diferir en mayúsculas (ver Desviaciones 4).
- README al día (sección de la página).
- Pruebas: **273 Python** (260 de antes + 13) y 19/19 JS. Las seis del plan, más: encolar rechaza lo inválido,
  el directo de un run muerto es 404 rápido, el directo espera a un run que aún se clona, 409 también en
  `/api/reanudar`, el hijo recibe el mismo `--cerrojo`, la pantalla no importa el orquestador ni el SDK
  (comprobado en un subproceso limpio), y la de mayúsculas de la cola.

### Prueba manual sin gastar (hecha)

Servidor efímero en `127.0.0.1:8801` con salidas, cola y cerrojo en el scratchpad:

- Encolar `https://github.com/henrik-thevibe/Claude-Fables/`: 201; otra vez: 200 `nuevo: false`; `…/mal;rm`: 400.
- **Lanzar ahora** esa URL con `falso`: 202; un segundo lanzar mientras corre: 409; el directo (curl) entregó
  `run_inicio, estado…`; el run acabó `aprobado`, con `nota.md` en su salida.
- **URL que no existe** (`https://github.com/x/no-existe-seguro`, falso): el proceso real murió en un instante con
  `GitFallo: git clone falló (128): fatal: could not read Username for 'https://github.com': terminal prompts
  disabled (¿repo privado o inexistente?)`, código 2. `/api/lanzador` lo devolvió con el error y el directo dio
  404 en 1 ms. Esto confirma **de verdad** el foco 1 de la revisión: `git` no se queda pidiendo credenciales.
- Capturas: `docs/capturas/tarea25-portada.png` (formulario, dos botones, "Esta noche" con lo encolado) y
  `docs/capturas/tarea25-error-lanzador.png` (el directo del run muerto con el error de `git`).
- No hice clic con un navegador dirigido (no hay CDP en esta sesión): la página se comprobó con las capturas
  de Chrome headless y las llamadas a la API que usa `mesa.js`. El flujo de clics (escribir en el campo, pulsar
  los botones) queda sin probar en un navegador.
- El servidor efímero ya está parado. No toqué `/data/enjambre-explicador/cola/` (hay una petición, `repomix`,
  que no es mía), ni la pantalla real. `/data/github-abordaje/Claude-Fables` sigue limpia.

## Gasto

0. La red solo se usó para `git fetch` de un repo público y un `git clone` fallido.

## Desviaciones

1. **El hijo recibe `--cerrojo <ruta del servidor>`** (el plan no lo menciona). Si el servidor mira un cerrojo y
   el hijo toma otro (el de por defecto), D31 no protege nada. En producción coinciden; lo vi en la prueba manual,
   donde no.
2. **`/api/lanzador` con error incluye `repo` y `run`** (el plan solo cita `en_marcha`, `codigo`, `error`); la
   página los necesita para saber que el error es del run que está esperando.
3. **El directo espera hasta 15 min** (no hay tope en el plan) mientras el proceso viva: un clon puede tardar
   hasta los 300 s de `fuente.actualizar` y el run no existe hasta entonces.
4. **`encolar` ya no distingue mayúsculas** (`…/Claude-Fables` y `…/claude-fables` se encolaron como dos en mi
   prueba manual): GitHub no las distingue y habría dos copias en disco y dos notas. Solo en la cola; **un
   "Lanzar ahora" con la otra grafía sigue creando otra copia**: es el mismo hueco de fondo en `fuente.resolver`
   (el nombre del repo conserva las mayúsculas, como pide la prueba normativa). Lo dejo para el arquitecto.
5. **Una carrera mínima** de `cerrojo.ocupado()`: toma el cerrojo un instante para mirarlo; si la cola arrancara
   justo entonces, esa noche avisaría "había otro run en marcha". Aceptado: es microsegundos y la cola avisa.

## Decisiones que necesito

1. **Continuar desde la página un run de una URL cuyo repo cambió.** `leer --reanudar` actualiza la copia y, si el
   commit ya no es el del run, **lanza un run nuevo** (D24/D30) con un nombre por defecto que la página no
   conoce: el 202 de `/api/reanudar` dice `{repo, run}` del run viejo y el directo mostraría ese. ¿Cómo quieres
   que se comporte "Continuar" ahí? Opciones: (a) dejarlo (el run nuevo aparece en la lista de la portada);
   (b) que `/api/reanudar` falle con 409 "el repo ha cambiado, lanza uno nuevo" (requiere que el servidor
   compare commits, es decir, que toque `git`); (c) que `leer` reciba `--run` y la página lo conozca. No lo he
   tocado.
2. **Las mayúsculas del nombre del repo** (Desviación 4): ¿se normaliza el nombre (minúsculas) en `resolver`?
   Cambiaría una prueba normativa (`Claude-Fables`).
3. **Fusión:** cuando apruebes H4, `git merge --ff-only feature/fase3-h4` desde `/data/enjambre-explicador`, reinicio
   de la pantalla real y `git worktree remove` los haces tú (no los hago).
