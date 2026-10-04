# Sesión siguiente

## Estado

**Tareas 1-12: HECHAS.** Josem revisó H4 ("si, lo he revisado y aunque tengo que afinar el
look, eso en fase final") y dio luz verde para seguir. Queda la Tarea 13 (Aceptación, H6),
que lanza Josem.

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

## Siguiente

**Fin de H5.** Queda la **Tarea 13 (Aceptación, H6), que lanza Josem** — no hay más trabajo
de implementación pendiente del plan de fase 2 por mi parte salvo lo que salga de esa
aceptación.

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
