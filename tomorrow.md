# Sesión siguiente

## Estado

**Tareas 1-12, 14, 15 y 16: HECHAS.** Josem revisó H4, aprobó D20/D21 (anexo 2026-10-04 del
plan) y pidió reordenar: 14 → 12 (ya hecha, sin tocar) → 15 → 13. Dio el visto bueno a la
Tarea 14 ("sigue siigue") tras pedir dos retoques rápidos (bitácora el doble de ancha; fuera la
fuente de mapa de bits propia, VT323 en su lugar). Tarea 15 (lanzar desde la página) cerrada.
**Tarea 16 (D22/D23, "la mesa de papeles") cerrada**: sustituye la escena única de personajes
(D20) por una rejilla de tarjetas HTML en el orden del flujo -- ver la sección propia más abajo.
Queda la Tarea 13 (Aceptación, H6), que lanza Josem.

- Tarea 1: cimientos del repo, fixtures, logger LogCentral.
- Tarea 2: `enjambre/agentes.py` (`cargar`, `ROLES`, `Agente`).
- Tarea 3: `enjambre/guardia.py` (`permitido`, el muro de permisos, D8).
- Tarea 4: `enjambre/parsers.py` (`ids_de_piezas`, `fallos`, `veredicto`, `SalidaIlegible`).
- Tarea 5: `enjambre/tipos.py` + `enjambre/eventos.py` (`Resultado`, `Contexto`, `Lanzar`, `Eventos`).
- Tarea 6: `enjambre/orquestar.py` (el guion: `orquestar`, `main`) + `enjambre/falso.py`.
- Tarea 7: `enjambre/lanzador.py` (`lanzar`, `opciones`, `hacer_hook`, `Traductor`) — la única
  costura con `claude_agent_sdk` (D6). Investigación del SDK real + smoke test [API]: ver
  `CLAUDE.md` → "Verificado del SDK".
- **Parche D16-D18** (tras la Tarea 7, antes del primer run real con ≥2 vueltas): D16 (borrar
  y exigir `verificacion.md`/`dudas.md` desde vuelta ≥2, luego también en vuelta 1 — ver más
  abajo), D17 (`fichero`/`aviso` desde el resultado real de la tool, no desde el hook), D18
  (`strict_mcp_config=True`, confirmado como causa real del gasto anómalo de tokens — ver
  diagnóstico [API] post-D18 más abajo). Además: regex de "bloqueado" insensible a mayúsculas
  y sin colarse en negaciones; `num_turns` hasta `fin_agente`; aviso si el `init` trae tools
  no pedidas.
- **Dos arreglos pedidos por Josem tras revisar el parche D16-D18**: (1) la exigencia D16
  (`_exige verificacion.md/dudas.md`) ahora corre también en la vuelta 1, no solo desde la 2 —
  antes, un fallo de escritura en la vuelta 1 se demoraba un ciclo completo (redactor +
  verificador + novato) antes de notarse; (2) `hacer_hook`/`Traductor` comparten un set de
  `tool_use_id` ya denegados, para que una escritura denegada por el guardia nunca dispare
  TAMBIÉN un `aviso` de "escritura rechazada" por el mismo hecho; de paso, el `detalle` de un
  `Glob` denegado ya no sale vacío (caía a `""` porque `ruta_de` no cubre `pattern`).
- **Tarea 8**: `enjambre/pantalla.py` — servidor HTTP stdlib (`ThreadingHTTPServer`), rutas de
  §5.1, protección de rutas por `_resuelve_dentro` (resolve + `is_relative_to`). Revisión de
  seguridad: sin fugas de contenido (24 casos de path traversal probados entre dos pasadas de
  revisión — symlinks, doble encoding, bytes nulos, barra invertida, UTF-8 overlong — todos
  404/vacío). 3 rondas de endurecimiento de robustez tras revisión: keepalive SSE para detectar
  cliente desconectado, lectura binaria con buffer para no partir un carácter UTF-8 multibyte a
  medio escribir, aislamiento por-run en `/api/runs` para que un `eventos.jsonl` corrupto no
  tumbe la lista entera.
- **Tarea 9**: `pantalla/estado.js` — reductor de estado puro (`inicial`, `aplicar`, `ROLES`).
  Corregido tras lectura propia (no lo pilla el test literal): la regla de compatibilidad para
  tipos de evento desconocidos es "solo t", pero tocaba también la bitácora.
- **Tarea 10**: `pantalla/index.html` + `pantalla/escena.js` — página, modo repetición (reloj
  virtual con compresión de huecos >5s a 1s), render provisional de rectángulos de color.
  Josem lo probó en navegador real (captura en `image.png`, ya no versionada) y pidió retoques
  — ver Tarea 11.
- **Tarea 11** (arte pixel, D14): `pantalla/sprites.js` nuevo — 7 roles × 5 estados × 2
  fotogramas generados por código (no matrices a mano), fondo del barco con parpadeo, loro
  guardián (`LORO`, volando/posado), fuente de mapa de bits 5×7 propia +
  `dibujarTexto`/`medirTexto` (nada de `ctx2d.font`). `escena.js` repintado para usar sprites
  reales. Además, los 8 puntos que Josem pidió tras revisar la captura de la Tarea 10, todos
  resueltos:
  1. Sprites — hechos.
  2. Fuente de mapa de bits — hecha, usada en bocadillos/bitácora/inventario.
  3. Escala entera ×1-×4 (`_escalarLienzo`, ya existía desde la Tarea 10, confirmada) +
     `image-rendering: pixelated` + `imageSmoothingEnabled = false`.
  4. Bocadillos con ruta relativa a `salida`/`repo` — `_relativiza()` en `estado.js`, con test.
  5. Inventario con nombre corto visible bajo cada icono.
  6. `fin_agente` en la bitácora ya no repite el nombre del agente: muestra
     `estado_final`/duración/coste.
  7. Barra de repetición: confirmado que SÍ funciona (`max`/`oninput` correctos) — lo que
     faltaba en la captura de Josem era solo el recorte de pantalla, no el código. Verificado
     dos veces de forma independiente (por el implementador vía `--dump-dom`, y por mí vía CDP).
  8. Esta reescritura de `tomorrow.md`.

  **Bug crítico encontrado en verificación propia (no en código, en el run real):** el modo
  repetición pasaba a `pintar()` el reloj VIRTUAL comprimido (`t0 + tVirtual`) como `ahoraMs`,
  pero la visibilidad de bocadillo/loro compara contra el timestamp REAL sin comprimir de cada
  evento (`ahoraMs - Date.parse(evento.t)`). En un run real con huecos de verdad el desfase
  crece sin límite (medido: 85s de deriva en el evento 90 de `agora-20261003-1444`), así que la
  edad siempre salía negativa y bocadillo/loro nunca se pintaban — invisible en pruebas
  `--falso` porque esos runs no tienen huecos que comprimir. Arreglado en `17f954c`: `ahoraMs`
  pasa a ser el timestamp real del último evento aplicado; `vTimes`/el ritmo de reproducción no
  se tocan. Verificado independientemente por mí contra el servidor real (100.87.64.121:8790)
  con un script CDP propio (`captura.mjs`, sin dependencias nuevas — `WebSocket`/`fetch` nativos
  de Node 22 contra `google-chrome --headless=new`): loro posado + "¡Prohibido!" y bocadillos sí
  se ven ahora.

  Captura final entregada a Josem: `docs/capturas/tarea11-mitad-lectores-agora-20261003-1444.png`
  (run real, evento 138, mitad de los 7 lectores en paralelo).

  Commits: a6cdfc1 (estado.js), 45f054e (sprites/escena), 17f954c (arreglo del reloj), bb78055
  (captura). 10/10 tests JS, 126/126 Python.

- **Pulido post-cierre de la Tarea 11**, pedido por Josem al ver la captura:
  1. *"lector de piezas estan muy juntos y su texto se sobreescribe"* — dos arreglos en
     `escena.js`: `LECTORES_PASO_X` pasa de 18 a `ANCHO_PERSONAJE` (24), ya no se pisan los
     cuerpos; y `_dibujarBocadillo` ahora lleva un sistema de carriles anticolisión (hasta 9,
     cubre 8 lectores + el loro a la vez) — si un bocadillo nuevo choca con uno ya pintado ese
     mismo fotograma, sube una altura de glifo y reintenta. Verificado contra el run real con
     hasta 6 bocadillos simultáneos, todos legibles. Commit d81dfcc.
  2. *"dentro de pantalla/ he dejado una carpeta sprites... a ver si los podemos usar"* —
     Josem trajo arte real (PNG, 7×5×2 = 70 ficheros, mismo contrato exacto que el
     procedural: 24×32px, 450ms/fotograma) en `pantalla/sprites/`. Exactamente lo que D14 dejó
     previsto ("sustituibles por PNG"). `sprites.js`: `cargarSpritesPersonajes()` carga los 70
     y sustituye cada fotograma de `SPRITES` en sitio (si un PNG falla, se queda el procedural
     — degradación, nunca rotura); `dibujar()` distingue matriz de paleta de imagen real.
     `escena.js`: `arrancar()` espera la carga antes de `_arrancarRepeticion`. `pantalla.py`:
     `_NOMBRE_STATIC` ahora permite `/` (el arte vive en subcarpetas por rol) — la barrera de
     seguridad real sigue siendo `_resuelve_dentro`, sin cambios ahí; test nuevo
     (`test_static_sirve_subcarpetas`) + caso de traversal con subcarpeta. Commit 66f122c.
  3. Captura de `docs/capturas/` renovada dos veces (2ebb0fd, c2afb42) para reflejar cada
     arreglo visual.

  128/128 Python, 10/10 JS tras todo el pulido.

- **Tarea 12** (modo directo, H5): `pantalla/escena.js` — `_arrancarDirecto(repo, run)` abre
  un `EventSource` contra `/api/directo/<repo>/<run>` y llama `alimentar(JSON.parse(e.data))`
  por cada mensaje (sin reloj virtual ni barra: el servidor ya manda los eventos al ritmo
  real). Controles de repetición ocultos; cabecera "EN DIRECTO" mientras no haya `run_fin`;
  al llegar, `close()` + enlace a la repetición del mismo run. Si el `EventSource` falla sin
  `run_fin`: aviso "conexión perdida, reintentando…" + se vacía el estado (el navegador
  reconecta solo, y el servidor siempre reabre `eventos.jsonl` desde el principio, así que
  hay que vaciar antes de reaplicar o se duplica todo). Lista de runs: `[directo]` solo para
  runs sin `motivo` (en marcha).

  **Dos bugs reales encontrados probando esto en un navegador de verdad** (no solo
  `--falso` rápido: usé un run con retardo largo a propósito para tener margen, más un
  script CDP que mata y relanza el servidor de pantalla a mitad de run):
  1. `.controles`/`.zona-lienzo` fijan `display: flex`, que pisa el `[hidden]{display:none}`
     por defecto del navegador (cascada CSS: una regla de autor siempre gana a la del
     user-agent) — `controles.hidden = true` no ocultaba nada. Arreglado con una única regla
     `[hidden] { display: none !important; }` en `index.html`, que de paso corrige el mismo
     problema latente que tenía `zonaLienzo.hidden` desde la Tarea 10.
  2. El aviso de "conexión perdida" se quedaba pegado en pantalla aunque ya se hubiera
     recuperado la conexión — se oculta ahora en cuanto llega el primer mensaje bueno tras
     reconectar.

  Commit e6d2d4c. 128/128 Python, 10/10 JS (ninguno de los dos tocado).

- **Anexo 2026-10-04 (D20/D21):** tras revisar H4, Josem aprueba D20 (escena neutra, orden
  del flujo, texto fuera del lienzo) y D21 (lanzar desde la página) — `ENJAMBRE-DISENIO.md`
  §5.4, detalle en el anexo al final de `docs/plans/2026-10-03-fase-2.md`. Nuevo orden:
  **Tarea 14 → Tarea 12 (ya hecha, sin cambios) → Tarea 15 → Tarea 13.**

- **Tarea 14** (escena neutra, D20): fuera el barco entero (cielo, cubierta, mástil, mesa
  larga, farolillos, timón) — fondo liso oscuro + suelo sutil; el estilo "Monkey Island" se
  queda solo en los personajes (D19). Colocación por orden del flujo, izquierda a derecha:
  cartógrafo · despiezador · lectores (rejilla 2 columnas, hasta 8) · trazador · redactor ·
  verificador y novato juntos al final. Nombre bajo cada personaje (`nombreCorto` nueva en
  `estado.js`, también usada por la bitácora). Color propio por instancia de lector (paleta
  de 8 tonos), nombre y bocadillo del mismo color. Bocadillos: fuera el sistema de carriles
  de la Tarea 11, ahora solo sube en vertical si choca, nunca en horizontal. Bitácora e
  inventario salen del lienzo a un panel HTML debajo (`#panel-registro`), fuente VT323 de
  Google Fonts con fallback a monospace — bitácora con líneas completas y scroll, más
  recientes arriba; inventario con rutas completas, clic reutiliza el panel lateral que ya
  existía. Arreglada la `p` minúscula de la fuente de mapa de bits (fila 1 de su matriz
  dibujaba literalmente una `P`).

  Lienzo: se queda en 320×200 (no se encoge a 320×144) — los 56px que antes ocupaba la barra
  SCUMM se reaprovechan como alto de escena para que quepan las 4 filas de lectores.

  Commit 94c6104. 128/128 Python, 12/12 JS (10 + 2 nuevas de `nombreCorto`/bitácora,
  literales del plan). Captura en `docs/capturas/tarea14-mitad-lectores.png`.

- **Dos retoques pedidos por Josem tras ver la captura de la Tarea 14:**
  1. *"la bitacora justo el doble de ancha"* — `.panel-bitacora`/`.panel-inventario` en
     `index.html`, `flex: 2 1` vs `flex: 1 1` en vez del 1:1 que tenían. Commit d47f3bd.
  2. *"me joroba lo indecible... me lleva a mis tiempos de spectrum... pero no funciona...
     cambiala por la misma que la bitacora"* — la fuente de mapa de bits propia (5×7, Tarea
     11) deja de usarse en el lienzo (nombres y bocadillos); pasan a VT323, la misma que ya
     usaba el panel de bitácora/inventario. **La fuente vieja no se borró** ("construiste tu
     la fuente? no la borres: dejala por ahi que la usaremos para algo") — vive intacta en
     `pantalla/fuente-pixel.js`, sin usar por nadie, para cuando haga falta. `sprites.js`:
     `dibujarTexto`/`medirTexto` reescritas sobre `ctx2d.font`/`fillText`/`measureText`;
     `cargarFuenteTexto()` nueva (mismo patrón que `cargarSpritesPersonajes`: espera a que
     VT323 cargue de verdad antes del primer pintado, si no el canvas se queda pintando con
     el fallback `monospace` para siempre). Honestidad comprobada a propósito: `fillText` SÍ
     lleva antialiasing (a diferencia del `fillRect` de 1×1 de la fuente vieja) y el lienzo
     se escala con `image-rendering: pixelated` -- verificado a ×4 real que se nota un ligero
     halo gris de cerca pero se lee limpio a tamaño normal, aceptado a sabiendas. Commit
     1f0d403 (+ 3eec993, captura canónica actualizada).

  Un agente en segundo plano empezó la Tarea de la fuente con un encargo mío previo (reducir
  a 4×6) y, tras el cambio de instrucción de Josem a mitad de camino, llegó a escribir la
  base de la solución VT323 antes de agotar su cupo de sesión sin comitear nada; completé el
  enganche, la verificación visual y la preservación de la fuente vieja yo mismo.

  Josem dio el visto bueno ("sigue siigue") y se pasó a la Tarea 15.

- **Tarea 15** (lanzar el run desde la página, H5b, D21): `orquestar.main` gana `--run`
  (pasa a `orquestar(run=...)`, que ya lo aceptaba). `pantalla.crear_servidor` gana
  `raiz_repos` (default `/data`), `comando` (sustituible en pruebas) y `dir_logs`. Rutas
  nuevas: `POST /api/lanzar` (valida repo/tope_usd/max_vueltas/falso, 400/403/409 según
  toque, lanza el subproceso con `start_new_session=True`), `POST /api/parar` (SIGINT),
  `GET /api/lanzador`. Anti-CSRF uniforme (`Content-Type: application/json` + `X-Enjambre:
  1`, si no 403). `_servir_directo` espera hasta 30s a que aparezca `eventos.jsonl` (si se
  acaba de lanzar desde la página, el navegador puede llegar antes de que exista). Portada:
  formulario (repo/tope/vueltas/casilla "falso", marcada por defecto) + botón Parar en
  directo mientras no haya `run_fin`.

  **Bug real encontrado probando esto de verdad** (no solo con las pruebas — el proceso de
  mentira de los tests también lo sufre, con una ventana de carrera minúscula pero real):
  `proc.send_signal(SIGINT)` puede llegar antes de que el subproceso recién lanzado haya
  instalado su propio manejador de señales, y entonces el SIGINT lo mata con el manejador
  por defecto de Python sin dejarle escribir `run_fin: interrumpido`. Medido en este disco:
  ~30ms hasta que un `python -c "..."` registra su manejador, y el flujo HTTP real de
  lanzar+comprobar+parar solo deja ~3ms de margen natural. Arreglo: `_parar` espera lo que
  falte hasta 0.2s desde el lanzamiento antes de mandar la señal — nada si el proceso ya
  llevaba más que eso corriendo (el caso normal).

  Verificado end-to-end contra un servidor real con Chrome headless vía CDP: casilla "falso"
  marcada por defecto, lanzar `/etc` da el error de validación, lanzar `/data/agora` con
  falso navega a directo y se ve en vivo, Parar a mitad deja `motivo: interrumpido`. Ningún
  run real lanzado en la verificación. Commit 787b44f. 139/139 Python (+11), 12/12 JS.

## Siguiente

**Fin de H5b.** Queda la **Tarea 13 (Aceptación, H6), que lanza Josem** — no hay más trabajo
de implementación pendiente del plan de fase 2 por mi parte salvo lo que salga de esa
aceptación o más pulido visual que Josem pida.

### Tarea 16 — la mesa de papeles (D22/D23), Paso 4 y 5

Pasos 1-3 (D23 en el lanzador, el reductor de `estado.js`, `--falso` ejercitando la mesa) ya
estaban hechos y comiteados antes de esta sesión (commits `4165c68`, `008fe03`, `d11c889`).
Este commit es el Paso 4 (la vista) + Paso 5 (prueba manual).

`pantalla/escena.js` (D20, un único `<canvas>` con personajes) se sustituye por
`pantalla/mesa.js`: rejilla CSS de 4 columnas en el orden del flujo (cartógrafo/despiezador en
la 1, lectores en la 2 ocupando las dos filas, trazador/redactor en la 3,
verificador/novato en la 4), cada tarjeta con su `<canvas>` propio (sprite ×3 entero, ×2 en las
filas de lectores, `image-rendering: pixelated`, tamaño intrínseco = tamaño del sprite y escala
por CSS, sin JS de resize dinámico porque la escala es siempre entera fija). Todo el texto
(nombres, bocadillos, fichas, puertas, "Ahora") pasa a ser HTML normal, no dibujado en canvas.

**Decisiones de diseño no explícitas en el plan:**

- **Flechas SVG**: un `<svg id="flechas">` superpuesto (`position:absolute`, `pointer-events:
  none`) sobre `#mesa`. La TOPOLOGÍA (qué tarjeta conecta con cuál, por qué lado) está fija en
  código -- la rejilla de 4 columnas es un layout fijo del plan, no arbitrario -- pero las
  COORDENADAS se leen siempre de `getBoundingClientRect()` de las tarjetas reales en
  `_recalcularFlechas`, nunca de píxeles literales. Se recalcula en cada `_render` (barato: 7
  rects) y además en `resize` de ventana (para cuando la repetición está en pausa y `_render`
  no se vuelve a llamar solo). Las dos flechas de "vuelta" (verificador/novato → redactor)
  llevan trazo discontinuo ámbar y marcador de punta propio, distinto del gris de las flechas
  de ida, con una única etiqueta "vuelta n/max" compartida entre las dos (no duplicada) en el
  punto donde convergen.
- **Encendido a 500ms reales mínimo** (papel y puertas): `_estaEncendida(mapa, clave, marca,
  ahoraMs)` es una única función compartida por fichas y puertas (no dos implementaciones). Lleva
  un mapa `clave -> {marca, inicioReal}`; cuando la condición VIRTUAL (edad respecto a
  `ahoraMs` < 3000ms) se cumple por primera vez o se renueva (la `marca` cambia, es una lectura
  o un denegado nuevo), apunta `performance.now()`; mientras no hayan pasado 500ms reales desde
  ahí, sigue "encendida" aunque la condición virtual ya no se cumpla -- así ×4/×16 no deja
  pasar el encendido sin pintar ni un fotograma.
- **Panel "Ahora", tope de 3**: se eligen los primeros 3 agentes activos (`leyendo`/
  `escribiendo`) en el orden de inserción de `estado.agentes`, que es el orden REAL de
  lanzamiento del run (cada rol se crea en `run_inicio`/`lanzado` en ese orden) -- no había un
  criterio "más urgente" más significativo que ese para un POC pensado para enseñar el avance
  del flujo.
- **`fuente-pixel.js` y las funciones VT323-en-canvas de `sprites.js`** (`dibujarTexto`,
  `medirTexto`, `cargarFuenteTexto`, `FUENTE_CSS`, `ANCHO_GLIFO`, `ALTO_GLIFO`): con todo el
  texto de la mesa en HTML, `mesa.js` no las llama. El plan (Tarea 16, "Ficheros") decía borrar
  `fuente-pixel.js` si quedaba sin uso; pero Josem pidió explícitamente, en esta misma sesión,
  NO borrar código que funciona y podría reutilizarse ("lo usaremos para algo") -- se aplicó
  ese mismo criterio aquí: ninguno de los dos se borra, se quedan sin llamador.
- **Firma de `arrancar`**: cambia de `arrancar(lienzo, cabecera)` (el `<canvas>` único de D20)
  a `arrancar(mesaEl, cabecera)` (el contenedor `<div id="mesa">`) -- ya no hay un solo lienzo
  que escalar/pasar; el resto de elementos (controles, paneles) se siguen buscando por id,
  mismo acoplamiento documentado que ya tenía `escena.js` con `index.html`.

**Verificación visual real** (servidor efímero en `127.0.0.1:8801` + Chrome headless vía CDP
crudo, WebSocket/fetch nativos de Node, sin Playwright):

1. `docs/capturas/tarea16-mitad-lectores.png` -- repetición de `agora/agora-20261003-1444`,
   barra en el evento 135 (mitad de los lectores). Confirmado a ojo: panel "Ahora" con
   lecturas reales de 3 agentes + "+1"; 7 filas de lectores con su sprite, estado y ficha
   (varias con fichero ya escrito, subrayado, clicable); las 4 tarjetas de los roles únicos
   con su sprite, estado, modelo y (cartógrafo/despiezador) duración+coste; 10 elementos
   `<path>` en `#flechas` (8 flechas + 2 puntas de marcador), arrancando de los bordes reales
   de las tarjetas; franja de puertas con los 4 contadores, "los demás" en `n=1` (hubo un
   denegado real en este run), verificador con borde discontinuo.
2. `docs/capturas/tarea16-falso-puertas.png` -- run `--falso` lanzado por mí
   (`tarea16-verif-1791141412`, limpiado después de la captura), barra en el evento 82 (justo
   tras el `denegado` del redactor que sigue a sus tres lecturas de fichas). Confirmado a ojo:
   la tarjeta del redactor con borde resaltado (`leyendo`); la puerta "Redactor" en rojo con el
   texto exacto `Read backend/servicio.py — el redactor no ve el repo (D2) -- teatro de demo,
   --falso`; a la vez, las tres fichas `fichas/a-uno.md`/`b-dos.md`/`c-tres.md` en la tarjeta de
   Lectores con fondo ámbar (encendidas) y tooltip `leído por: trazador, redactor` -- puerta y
   papel encendidos simultáneamente, como pide el punto 4/7 del encargo.
3. Apilado: mismo run/evento a 800px de ancho. `scrollWidth === clientWidth` (sin scroll
   horizontal), `#flechas` con `display:none` (oculto, no recalculado -- decisión documentada
   en `mesa.js`), orden visual de las tarjetas confirmado por CSS `order`: cartógrafo,
   despiezador, lectores, trazador, redactor, verificador, novato (el mismo orden del flujo).

`node --check` de los tres `.js` tocados, `node --test tests/js/*.mjs` (18/18, sin tocar
`estado.js` ni su test) y `.venv/bin/pytest -q` (143/143, sin tocar nada Python) en verde antes
del commit.

### Nota histórica — D16 y el bloqueo de `Write` (YA RESUELTO, no es un pendiente)

El tool real `Write` del CLI exige haber leído con éxito un fichero existente en la misma
sesión antes de sobrescribirlo (mismo invariante que `Edit`, hardcodeado en el binario —
`"File has not been read yet. Read it first before writing to it."`). Esto chocaba con el muro
del novato (D8: prohibido leer `dudas.md`) desde la vuelta 2 en adelante. **Resuelto por D16**
(`orquestar.py` borra `verificacion.md`/`dudas.md` antes de relanzar verificador+novato en cada
vuelta, incluida ahora la vuelta 1, y exige que se reescriban después). Detalle completo y cita
literal del error: `CLAUDE.md` → "Verificado del SDK".

Las dos incógnitas que la Tarea 3 había dejado pendientes para cuando se conectara el SDK real
quedan resueltas (Glob/Grep path traversal vía patrón, conectado en la Tarea 7; I2 —
`setting_sources=[]` aísla de verdad, confirmado por código y empíricamente).

### `fin_agente` real del smoke test [API] (novato, Haiku) — histórico, Tarea 7

```json
{"tipo": "fin_agente", "agente": "novato", "estado_final": "terminado",
 "modelo_real": "claude-haiku-4-5-20251001", "duracion_s": 157.245,
 "tokens_in": 836833, "tokens_out": 14274, "coste_usd": 0.6600866,
 "num_herramientas": 5}
```

El gasto anómalo de `tokens_in` de este run quedó explicado y resuelto por D18 — ver el
diagnóstico siguiente.

### Diagnóstico [API] post-D18: I4 — histórico, confirmado

Una sola llamada real (novato, Haiku) tras `strict_mcp_config=True` (D18): `tokens_in=32277`
frente a los 836,833 de arriba (~26× menos), muy por debajo del umbral de falsación de I4
(200K). **Veredicto: CONFIRMADO**, `strict_mcp_config=True` fue un contribuyente real al gasto
anómalo. Init `SystemMessage.tools` = `["Read", "Write"]` exacto, cero tools MCP extra.
`usage` crudo y `Resultado` completos conservados en el historial de git de este fichero si
hace falta revisarlos (commit 30162b2).

## Bloqueos / le toca a Josem

**LogCentral vector.toml:** Para que LogCentral recoja los logs de enjambre, hay que añadir en `/data/logcentral/vector/vector.toml`:

1. Nuevo `[sources.enjambre]` con `include = ["/data/enjambre-explicador/logs/enjambre.log"]`
2. Nuevo `[transforms.parse_enjambre]` copiado de `parse_saxhero` pero con nombre `parse_enjambre`
3. Añadir `parse_enjambre` a los dos `inputs = [...]` que agregan todos los parse (buscar líneas que agreguen todos los parse)
4. Reiniciar Vector: `docker compose -f /data/logcentral/vector/docker-compose.yml restart`

Sin esto, `/data/enjambre-explicador/logs/enjambre.log` se crea pero no se indexa en LogCentral.
