// escena.js — pantalla del enjambre: modo repetición (T10/T11) y modo
// directo por SSE (T12).
//
// Contrato con el resto del sistema:
//   export function arrancar(lienzo, cabecera)  — arranca la página entera.
//   export function pintar(ctx2d, estado, ahoraMs) — SOLO dibuja.
//   export function alimentar(evento) — aplica un evento sobre el estado
//     compartido y repinta; la usa el modo directo (`_arrancarDirecto`, más
//     abajo) por cada `message` de su `EventSource`, tal cual pide el plan.
//
// Acoplamiento documentado con index.html (fuera de la firma de `arrancar`,
// que solo recibe lienzo y cabecera): este módulo busca por id en `document`
// los controles de repetición (#controles, #btn-pausa, botones [data-vel],
// #barra), el aviso del modo directo (#aviso-directo), la lista de runs
// (#lista-runs), el contenedor del lienzo (#zona-lienzo) y el panel lateral
// (#panel-lateral, #panel-contenido, #cerrar-panel). index.html y escena.js
// se escriben juntos, así que esta costura es segura; si se separan algún
// día, pasar a hacerlo explícito por parámetros.

import { inicial, aplicar, ROLES, nombreCorto } from "./estado.js";
import {
  SPRITES,
  LORO,
  COLOR_TEXTO,
  ALTO_GLIFO,
  ANCHO_PERSONAJE,
  ALTO_PERSONAJE,
  dibujar,
  dibujarTexto,
  medirTexto,
  cargarSpritesPersonajes,
  cargarFuenteTexto,
} from "./sprites.js";

// D20: `FONDO` (cielo/cubierta/mástil/mesa larga/farolillos/timón... del
// barco, Tarea 11) ya no se pinta -- Josem, revisión de la Tarea 11: con el
// barco entero y el texto metidos en un lienzo de 320px no se sabía quién
// hablaba ni se podía leer la bitácora. La escena pasa a ser neutra; el
// estilo "Monkey Island" se limita a los personajes (D19), que SÍ se quedan.
// `FONDO` sigue exportado desde sprites.js (no se ha tocado ese fichero más
// que el bug de la fuente, D20 punto 7) por si una tarea futura lo reutiliza;
// aquí simplemente ya no se importa.

// ---------------------------------------------------------------------------
// Estado de módulo: una sola fuente de verdad para pintar/alimentar, como
// pide el diseño (§5.2: "toda la página es una función de estado"). Tanto el
// modo repetición como el modo directo (T12) escriben aquí.
// ---------------------------------------------------------------------------
let _ctx = null;
let _estado = inicial();
let _repo = null;
let _run = null;

// Zonas (en coordenadas del lienzo, 320×200) calculadas en el último
// `pintar`, para hit-test de click/hover sin duplicar la lógica de layout.
// `_zonasInventario` (Tarea 11) desaparece con D20: el inventario ya no se
// pinta dentro del lienzo (punto 6), así que no hace falta hit-test de click
// sobre él -- el panel HTML nuevo tiene sus propios <button> con su propio
// listener (`_actualizarInventario`, más abajo).
let _zonasAgentes = []; // {x,y,w,h, instancia, agente}

// Rectángulos de los bocadillos ya dibujados en el fotograma actual
// (incluido el del loro), para que `_dibujarBocadillo` pueda subir en
// vertical cuando dos agentes muy juntos hablan a la vez -- ver ahí.
let _bocadillosDibujados = []; // {x1,y1,x2,y2}

// Elementos de cabecera, rellenados una vez en `arrancar`.
let _cab = null;

export async function arrancar(lienzo, cabecera) {
  _ctx = lienzo.getContext("2d");
  _ctx.imageSmoothingEnabled = false; // pixel art: nunca interpolar al escalar (pedido de Josem)
  _escalarLienzo(lienzo);
  window.addEventListener("resize", () => _escalarLienzo(lienzo));

  // Arranca la carga de los PNG reales de personajes ya mismo, en paralelo
  // con el resto del arranque (fetch de /api/runs, construir la cabecera...)
  // -- solo se espera justo antes de empezar a pintar agentes de verdad
  // (`_arrancarRepeticion`), para que el primer fotograma ya salga con el
  // arte real y no con un parpadeo del procedural de respaldo.
  const cargaSprites = cargarSpritesPersonajes();
  // Mismo motivo y mismo patrón para VT323 (2026-10-04, sustituye a la
  // fuente de mapa de bits propia en el lienzo): si `fillText` se usa antes
  // de que la fuente haya cargado, el navegador pinta con el fallback
  // `monospace` ESE fotograma y el `<canvas>` no se repinta solo cuando la
  // fuente llega (a diferencia del HTML normal) -- hay que esperar antes
  // del primer pintado real, igual que con los sprites.
  const cargaFuente = cargarFuenteTexto();

  _cab = _construirCabecera(cabecera);
  _actualizarCabecera();

  _instalarInteraccionLienzo(lienzo);
  _instalarPanelLateral();

  const params = new URLSearchParams(location.search);
  const run = params.get("run");
  const modo = params.get("modo") || "repeticion";

  const zonaLienzo = document.getElementById("zona-lienzo");
  const listaRuns = document.getElementById("lista-runs");
  const formLanzar = document.getElementById("form-lanzar");

  if (!run) {
    if (zonaLienzo) zonaLienzo.hidden = true;
    if (listaRuns) listaRuns.hidden = false;
    if (formLanzar) formLanzar.hidden = false;
    _cargarListaRuns(listaRuns);
    _instalarFormularioLanzar(formLanzar);
    // Nada que pintar todavía: se deja el lienzo con el estado inicial
    // en blanco para que no quede un canvas sin inicializar si alguien
    // navega hacia atrás desde una repetición.
    pintar(_ctx, _estado, Date.now());
    _actualizarPaneles(_estado);
    return;
  }

  if (zonaLienzo) zonaLienzo.hidden = false;
  if (listaRuns) listaRuns.hidden = true;
  if (formLanzar) formLanzar.hidden = true;

  const partido = run.split("/");
  _repo = partido[0] || "";
  _run = partido.slice(1).join("/") || "";

  if (modo === "directo") {
    await Promise.all([cargaSprites, cargaFuente]);
    _arrancarDirecto(_repo, _run);
    return;
  }

  await Promise.all([cargaSprites, cargaFuente]);
  _arrancarRepeticion(_repo, _run);
}

// ---------------------------------------------------------------------------
// pintar y auxiliares -- T11 sustituye SOLO esta sección (de aquí a
// "FIN pintar y auxiliares") por sprites, sin tocar arrancar/alimentar ni el
// resto del fichero.
// ---------------------------------------------------------------------------

const ANCHO = 320;
const ALTO = 200;

// D20: el lienzo se queda en 320×200 -- NO se encoge a 320×144. Los 56px
// que antes ocupaba la barra SCUMM (bitácora + inventario pintados dentro
// del lienzo, Tarea 11) ya no hacen falta para eso -- ese contenido vive
// ahora en el panel HTML de debajo (punto 6) -- pero esos mismos 56px se
// reaprovechan como alto de ESCENA: la colocación por orden de flujo (punto
// 2) mete hasta 8 lectores en una rejilla de 2 columnas (4 filas de ~24-32px
// cada una) y los bocadillos necesitan margen por encima de las cabezas para
// subir sin chocar (punto 5, `_dibujarBocadillo`) -- con 144px de alto eso
// quedaba muy justo para la fila superior de lectores. Ya no hay dos zonas
// distintas (antes `ALTO_ESCENA`/`ALTO_BARRA`): todo el lienzo es la escena.

// Duración de cada fotograma de animación, en ms de `ahoraMs` (reloj
// virtual en repetición -- avanza ×velocidad --, reloj real en directo).
// `pintar` solo recibe ese instante, no la velocidad de reproducción, así
// que a ×16 el ciclo de fotogramas se acelera en la misma proporción; para
// que eso no resulte molesto se mantienen las diferencias entre
// fotogramas pequeñas (parpadeo de "Zzz", vaivén de 1px de la herramienta,
// el "!" de bloqueado que se enciende y apaga). No ha sido posible
// comprobar a ojo, sin navegador, cómo se percibe exactamente a ×16.
const MS_POR_FOTOGRAMA = 450;

function _fotogramaDe(frames, ahoraMs) {
  if (!frames || frames.length === 0) return null;
  const i = Math.floor(Math.max(0, ahoraMs) / MS_POR_FOTOGRAMA) % frames.length;
  return frames[i];
}

// ---------------------------------------------------------------------------
// Colocación por orden del flujo (D20 punto 2): izquierda a derecha,
// cartógrafo · despiezador · lectores (rejilla de 2 columnas) · trazador ·
// redactor · verificador y novato juntos al final. Coordenadas elegidas a
// mano sobre el lienzo de 320×200, verificadas con una captura real (ver
// informe de la tarea) -- no solo a ojo de código.
// ---------------------------------------------------------------------------

// y superior del sprite para todos los roles de una sola columna (todos
// salvo lector-de-pieza): los alinea en una misma fila horizontal, para que
// el avance izquierda->derecha del flujo se lea de un vistazo.
const Y_AGENTE = 74;

const PUESTOS_FLUJO = {
  cartografo: 2,
  despiezador: 40,
  trazador: 168,
  redactor: 204,
  // "juntos al final" (punto 2): separados solo 2px entre sí (en vez de los
  // ~36px del resto), para que se lean como pareja final del flujo y no
  // como dos estaciones más -- sus nombres se solapan un poco a cambio
  // (ambos recortados, `ANCHO_MAX_NOMBRE`), aceptado a propósito.
  verificador: 240,
  novato: 270,
};

// Rejilla de lectores: hasta 8, 2 columnas (punto 2). Columnas separadas
// 36px (ANCHO_PERSONAJE=24 + margen, el mínimo para que no se pisen los
// sprites de dos lectores contiguos -- lección de la Tarea 11 con la fila
// única, D14). Si llegan más de 8 (no debería, tope documentado del
// despiezador) se sigue apilando por fila sin rediseñar, igual que antes.
//
// `LECTOR_PASO_Y` deja sitio para personaje (32) + nombre (8) + el bocadillo
// de la fila siguiente, que aparece justo encima de SU personaje -- con
// menos separación, el bocadillo de la fila k+1 cae encima del NOMBRE de la
// fila k (visto en una captura real contra el servidor: texto de la fila de
// abajo mezclado con el nombre de la de arriba). `_dibujarBocadillo` ya
// evita chocar con lo ya dibujado este fotograma (punto 5) -- por eso cada
// nombre se registra también en `_bocadillosDibujados` justo después de
// pintarlo (ver el bucle de agentes, más abajo): sin ese registro, un
// bocadillo no "ve" los nombres y los pisa igual aunque haya sitio de sobra.
const LECTOR_COLS_X = [82, 118];
const LECTOR_FILA_Y0 = 14;
const LECTOR_PASO_Y = 48;

function _posicionLector(indice) {
  const col = indice % 2;
  const fila = Math.floor(indice / 2);
  return { x: LECTOR_COLS_X[col], y: LECTOR_FILA_Y0 + fila * LECTOR_PASO_Y };
}

function _posicionAgente(rol, indiceLector) {
  if (rol === "lector-de-pieza") return _posicionLector(indiceLector);
  const x = PUESTOS_FLUJO[rol];
  return { x: typeof x === "number" ? x : 150, y: Y_AGENTE };
}

// Paleta de 8 tonos para lectores (D20 punto 4): un color por INSTANCIA, no
// por rol -- cada lector de pieza es una instancia distinta del mismo rol,
// así que `COLOR_TEXTO["lector-de-pieza"]` (una sola entrada, Tarea 11) ya
// no basta para distinguirlos. Elegida por contraste visual entre sí y
// contra los colores de `COLOR_TEXTO` de los demás roles (no por una
// fórmula de distancia de color, ver el mensaje de commit); el índice se
// asigna por orden de aparición en `estado.agentes` (mismo contador
// `indiceLector` que decide la posición en la rejilla), así que un mismo
// lector conserva su color entre fotogramas mientras el run avanza.
const COLOR_LECTORES = [
  "#ff6b6b", // rojo coral
  "#48dbfb", // cian
  "#1dd1a1", // verde turquesa
  "#feca57", // ámbar
  "#a29bfe", // lavanda
  "#ff9f43", // naranja
  "#54a0ff", // azul
  "#ee5a6f", // magenta
];

/**
 * pintar(ctx2d, estado, ahoraMs) — dibuja la escena entera con los sprites
 * de `sprites.js`. Pura en el sentido de que solo lee `estado`/`ahoraMs` y
 * escribe en `ctx2d` (y en las cachés de zonas de módulo, para hit-test de
 * click/hover); no hace fetch ni toca `location`.
 */
export function pintar(ctx2d, estado, ahoraMs) {
  _zonasAgentes = [];
  _bocadillosDibujados = [];

  // --- Fondo neutro (D20 punto 1): sin barco -- un azul noche liso de
  // fondo y una franja de suelo sutil, apenas más oscura, nada más. El
  // estilo "Monkey Island" se queda en los personajes (D19), no en el
  // decorado: Josem, revisión de la Tarea 11, "con el barco y el texto
  // metidos en un lienzo de 320px no se sabía quién hablaba".
  ctx2d.fillStyle = "#121a2e"; // mismo tono que usaba la banda media del cielo (Tarea 11), por continuidad
  ctx2d.fillRect(0, 0, ANCHO, ALTO);
  ctx2d.fillStyle = "#0a0e1a"; // suelo sutil: una sombra, no una cubierta de tablas
  ctx2d.fillRect(0, ALTO - 14, ANCHO, 14);

  // --- Agentes, colocados en el orden del flujo (D20 punto 2) ---------------
  // Orden de inserción de `estado.agentes` ya es estable (claves string),
  // así que basta un contador para numerar a los lectores en la rejilla (y,
  // con él, asignarles también su color de `COLOR_LECTORES`).
  let indiceLector = 0;
  for (const [instancia, agente] of Object.entries(estado.agentes || {})) {
    const rol = agente.rol;
    const esLector = rol === "lector-de-pieza";
    const indice = esLector ? indiceLector++ : 0;
    const pos = _posicionAgente(rol, indice);
    // Color por instancia (punto 4): un lector saca el suyo de la paleta de
    // 8 por su turno de aparición; el resto de roles sigue con el color fijo
    // de `COLOR_TEXTO` (Tarea 10/11) que ya tenían.
    const color = esLector ? COLOR_LECTORES[indice % COLOR_LECTORES.length] : COLOR_TEXTO[rol] || "#ffffff";

    const frames = SPRITES[rol] && SPRITES[rol][agente.estado];
    const fotograma = _fotogramaDe(frames, ahoraMs);
    if (fotograma) dibujar(ctx2d, fotograma, pos.x, pos.y);

    // Nombre bajo el personaje, siempre visible (punto 3): el rol, o el id
    // de la pieza para los lectores -- mismo `nombreCorto` que usa la
    // bitácora (estado.js), para que escena y bitácora hablen del mismo
    // nombre. Centrado en el personaje y recortado a `ANCHO_MAX_NOMBRE`
    // (no solo al borde del lienzo): con nombres de rol largos
    // ("despiezador", "verificador"...) y estaciones a menos de 70px entre
    // sí en 320px de ancho, un nombre sin recortar se come el de al lado --
    // visto en una captura real contra el servidor. El recorte width-aware
    // (`_recortarTexto`, igual que el que ya usaba el inventario en la
    // Tarea 11) deja la mayoría legibles del todo; los más largos se leen
    // abreviados con un "." final, nunca solapados con el vecino.
    const nombre = _recortarTexto(nombreCorto(instancia), ANCHO_MAX_NOMBRE);
    const anchoNombre = medirTexto(nombre);
    const xNombre = Math.max(0, Math.min(ANCHO - anchoNombre, Math.round(pos.x + ANCHO_PERSONAJE / 2 - anchoNombre / 2)));
    const yNombre = pos.y + ALTO_PERSONAJE + 1;
    dibujarTexto(ctx2d, nombre, xNombre, yNombre, color);
    // Se registra como "ya dibujado este fotograma" (mismo mecanismo que
    // los bocadillos, ver `_dibujarBocadillo`): si no, el bocadillo de la
    // fila de lectores de abajo lo pisa aunque haya sitio de sobra más
    // arriba -- ver el comentario de `LECTOR_PASO_Y`.
    _bocadillosDibujados.push({ x1: xNombre, y1: yNombre, x2: xNombre + anchoNombre, y2: yNombre + ALTO_GLIFO });

    _zonasAgentes.push({ x: pos.x, y: pos.y, w: ANCHO_PERSONAJE, h: ALTO_PERSONAJE, instancia, agente });

    // Bocadillo centrado sobre la cabeza, recortado al lienzo; se borra a
    // los ~3s de `bocadillo.t` (§5.3). Mismo color que el nombre (punto 4).
    if (agente.bocadillo && agente.bocadillo.t) {
      const edadMs = ahoraMs - Date.parse(agente.bocadillo.t);
      if (edadMs >= 0 && edadMs < 3000) {
        _dibujarBocadillo(ctx2d, agente.bocadillo.texto, pos.x + ANCHO_PERSONAJE / 2, pos.y - 2, color);
      }
    }
  }

  // --- El loro: vuela del borde del lienzo al agente denegado -------------
  // (misma regla de visibilidad ~3s que los bocadillos, mismo campo `t`;
  // mecánica sin cambios -- D20 no la toca, solo el decorado alrededor).
  if (estado.loro && estado.loro.t) {
    const edadMs = ahoraMs - Date.parse(estado.loro.t);
    if (edadMs >= 0 && edadMs < 3000) {
      const zona = _zonasAgentes.find((z) => z.instancia === estado.loro.agente);
      const destino = zona ? { x: zona.x + zona.w + 1, y: zona.y - 2 } : { x: ANCHO - 18, y: 10 };
      const origen = { x: ANCHO - 2, y: 4 };
      const t = Math.min(1, edadMs / 800); // 800ms de vuelo, luego posado
      const px = Math.round(origen.x + (destino.x - origen.x) * t);
      const py = Math.round(origen.y + (destino.y - origen.y) * t);
      const frames = t < 1 ? LORO.volando : LORO.posado;
      dibujar(ctx2d, _fotogramaDe(frames, ahoraMs), px, py, destino.x < origen.x);
      if (t >= 1) _dibujarBocadillo(ctx2d, "¡Prohibido!", px + 7, py - 1, "#ff7a7a");
    }
  }

  // D20 punto 6: bitácora e inventario YA NO se pintan aquí -- viven en el
  // panel HTML bajo el lienzo (`_actualizarBitacora`/`_actualizarInventario`,
  // más abajo), que cada llamador de `pintar` refresca a la vez.
}

// Ancho máximo de un nombre bajo un personaje (punto 3) -- ver el comentario
// en el bucle de agentes, más arriba. Con la fuente de mapa de bits fija de
// la Tarea 14 (6px/carácter) este tope recortaba casi todos los nombres a
// 4-5 letras ("desp.", "traz."); con VT323 (2026-10-04, proporcional, más
// estrecha) el mismo tope de 34px deja bastantes más enteros ("novato") o
// casi ("cartog.", "verific.") sin tocar el valor -- no ha hecho falta
// subirlo. Sigue evitando que un nombre invada la estación de al lado en
// los huecos de ~36-40px que separan los puestos del flujo de un personaje.
const ANCHO_MAX_NOMBRE = 34;

// Recorte por medida real del texto (igual que el que usaba el inventario
// dentro del lienzo en la Tarea 11, antes de que D20 lo sacara al panel
// HTML -- el mismo patrón sigue haciendo falta aquí, para los nombres):
// añade un "." final mientras no quepa en `anchoMax`.
function _recortarTexto(texto, anchoMax) {
  let recortado = String(texto);
  if (medirTexto(recortado) > anchoMax) {
    while (recortado.length > 1 && medirTexto(`${recortado}.`) > anchoMax) {
      recortado = recortado.slice(0, -1);
    }
    recortado = `${recortado}.`;
  }
  return recortado;
}

// Bocadillo de diálogo: centrado horizontalmente sobre `cx`, con el pie en
// `yInferior`, recortado para no salirse del lienzo de 320 de ancho.
//
// D20 punto 5 quita el sistema de "carriles anticolisión" de la Tarea 11
// (una tabla fija de hasta 9 alturas, pensada para 8 lectores apretados en
// una sola fila de 24px de paso). Con la rejilla nueva (2 columnas, mucho
// más separadas entre sí -- `LECTOR_COLS_X`) la colisión horizontal entre
// dos hablantes distintos ya es rara, así que basta una regla mucho más
// simple: si el candidato choca con un bocadillo ya pintado este mismo
// fotograma, sube una altura de glifo y lo intenta otra vez, siempre
// centrado en la misma `x` del hablante -- NUNCA se desliza en horizontal
// hacia otro sitio, como pide el plan. Si llega a y=0 (techo del lienzo) se
// dibuja ahí de todos modos: ilegible en el peor caso de muchísimos
// hablantes a la vez, pero ya no decidido por una tabla de carriles fija.
function _dibujarBocadillo(ctx2d, texto, cx, yInferior, color) {
  if (!texto) return;
  const ancho = medirTexto(texto);
  const x = Math.max(1, Math.min(ANCHO - ancho - 1, Math.round(cx - ancho / 2)));
  let y = Math.max(0, yInferior - ALTO_GLIFO);
  while (
    y > 0 &&
    _bocadillosDibujados.some((b) => x < b.x2 && x + ancho > b.x1 && y < b.y2 && y + ALTO_GLIFO > b.y1)
  ) {
    y = Math.max(0, y - (ALTO_GLIFO + 1));
  }
  _bocadillosDibujados.push({ x1: x, y1: y, x2: x + ancho, y2: y + ALTO_GLIFO });
  dibujarTexto(ctx2d, texto, x, y, color);
}

// ---------------------------------------------------------------------------
// FIN pintar y auxiliares
// ---------------------------------------------------------------------------

/**
 * alimentar(evento) — aplica un evento sobre el estado compartido de módulo
 * y repinta. La usará el modo directo (T12); aquí solo tiene que existir y
 * funcionar, nadie la llama todavía desde `arrancar` en modo repetición
 * (que mantiene su propio reloj virtual más abajo).
 */
export function alimentar(evento) {
  _estado = aplicar(_estado, evento);
  _actualizarCabecera();
  if (_ctx) pintar(_ctx, _estado, Date.now());
  _actualizarPaneles(_estado);
}

// ---------------------------------------------------------------------------
// Cabecera HTML (run, vuelta, coste, reloj, motivo) — fuera del lienzo.
// ---------------------------------------------------------------------------

function _construirCabecera(cabecera) {
  cabecera.innerHTML =
    '<span class="campo">run <strong id="c-run">—</strong></span>' +
    '<span class="campo">vuelta <strong id="c-vuelta">—</strong></span>' +
    '<span class="campo">coste <strong id="c-coste">—</strong></span>' +
    '<span class="campo">reloj <strong id="c-reloj">—</strong></span>' +
    '<span class="campo">motivo <strong id="c-motivo">—</strong></span>';
  return {
    run: cabecera.querySelector("#c-run"),
    vuelta: cabecera.querySelector("#c-vuelta"),
    coste: cabecera.querySelector("#c-coste"),
    reloj: cabecera.querySelector("#c-reloj"),
    motivo: cabecera.querySelector("#c-motivo"),
  };
}

function _actualizarCabecera(motivoForzado) {
  if (!_cab) return;
  _cab.run.textContent = _estado.run || "—";
  _cab.vuelta.textContent = String(_estado.vuelta ?? "—");
  _cab.coste.textContent = typeof _estado.coste === "number" ? `$${_estado.coste.toFixed(4)}` : "—";
  _cab.reloj.textContent = _estado.t ? _estado.t.substring(11, 19) : "—";
  _cab.motivo.textContent = motivoForzado || _estado.motivo || "—";
}

// ---------------------------------------------------------------------------
// Panel HTML de bitácora e inventario (D20 punto 6) — fuera del lienzo.
// Cada llamador que antes solo llamaba a `pintar` ahora llama también a
// `_actualizarPaneles` justo después, para que las dos vistas (lienzo y
// panel) se refresquen siempre juntas sobre el mismo `estado`.
// ---------------------------------------------------------------------------

function _actualizarPaneles(estado) {
  _actualizarBitacora(estado);
  _actualizarInventario(estado);
}

function _actualizarBitacora(estado) {
  const lista = document.getElementById("lista-bitacora");
  if (!lista) return;
  const lineas = estado.bitacora || [];
  // "Las más recientes arriba" (punto 6): el array guarda la más reciente al
  // final (`push`, estado.js) -- aquí solo se invierte el orden de pintado,
  // sin tocar esa convención del estado.
  lista.innerHTML = "";
  for (let i = lineas.length - 1; i >= 0; i--) {
    const li = document.createElement("li");
    li.textContent = lineas[i];
    lista.appendChild(li);
  }
}

function _actualizarInventario(estado) {
  const lista = document.getElementById("lista-inventario");
  if (!lista) return;
  const inventario = estado.inventario || [];
  lista.innerHTML = "";
  for (const item of inventario) {
    const li = document.createElement("li");
    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "item-inventario";
    // Nombre de fichero COMPLETO (ruta relativa a `salida`, punto 6) -- ya
    // viene así en `item.ruta` (ver `_ruta_relativa_a_salida` en
    // lanzador.py), nada que recortar aquí.
    boton.textContent = item.ruta;
    boton.onclick = () => _abrirFicheroEnPanel(item.ruta);
    li.appendChild(boton);
    lista.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// Lista de runs (sin ?run= en la URL).
// ---------------------------------------------------------------------------

async function _cargarListaRuns(contenedor) {
  if (!contenedor) return;
  contenedor.textContent = "cargando runs…";
  let runs;
  try {
    const resp = await fetch("/api/runs");
    runs = await resp.json();
  } catch (err) {
    contenedor.textContent = `no se pudo cargar /api/runs: ${err}`;
    return;
  }
  if (!Array.isArray(runs) || runs.length === 0) {
    contenedor.textContent = "sin runs todavía.";
    return;
  }
  const ul = document.createElement("ul");
  for (const r of runs) {
    const id = `${r.repo}/${r.run}`;
    const li = document.createElement("li");
    const etiqueta = document.createElement("span");
    etiqueta.textContent = `${id} — ${r.inicio || "?"} — ${r.motivo || "en marcha"}  `;
    const aRep = document.createElement("a");
    aRep.href = `?run=${encodeURIComponent(id)}&modo=repeticion`;
    aRep.textContent = "[repetición]";
    li.append(etiqueta, aRep);
    if (!r.motivo) {
      // Directo solo tiene sentido para un run todavía en marcha (plan,
      // Tarea 12): uno ya terminado no tiene nada que emitir por SSE.
      const aDir = document.createElement("a");
      aDir.href = `?run=${encodeURIComponent(id)}&modo=directo`;
      aDir.textContent = "[directo]";
      li.append(document.createTextNode(" "), aDir);
    }
    ul.appendChild(li);
  }
  contenedor.innerHTML = "";
  contenedor.appendChild(ul);
}

// ---------------------------------------------------------------------------
// Formulario de lanzar (anexo 2026-10-04, Tarea 15, D21): en la portada
// (sin ?run=), encima de la lista de runs. Instalado una vez por carga de
// página -- si Josem navega de vuelta a la portada, `arrancar()` vuelve a
// llamar a esta función sobre el mismo <form> del DOM, reemplazando el
// `onsubmit` anterior sin duplicarlo.
// ---------------------------------------------------------------------------

async function _instalarFormularioLanzar(form) {
  if (!form) return;
  const btn = document.getElementById("btn-lanzar");
  const error = document.getElementById("error-lanzar");
  if (error) error.textContent = "";

  // "El botón Lanzar se desactiva si /api/lanzador dice en_marcha" -- se
  // comprueba una vez al mostrar la portada (no hay polling continuo
  // pedido por el plan); si Josem para el run o este termina mientras tiene
  // la portada abierta, un refresco de página vuelve a comprobarlo.
  try {
    const resp = await fetch("/api/lanzador");
    const estado = await resp.json();
    if (estado.en_marcha) {
      if (btn) btn.disabled = true;
      if (error) error.textContent = `ya hay un run en marcha: ${estado.repo}/${estado.run}`;
    } else if (btn) {
      btn.disabled = false;
    }
  } catch {
    // Un fallo aquí no debe bloquear el formulario entero -- se deja el
    // botón como estuviera y que sea /api/lanzar quien dé la última
    // palabra (409 si de verdad hay un run en marcha).
  }

  form.onsubmit = async (evt) => {
    evt.preventDefault();
    if (error) error.textContent = "";
    if (btn) btn.disabled = true;

    const repo = (document.getElementById("f-repo") || {}).value?.trim() || "";
    const tope_usd = Number((document.getElementById("f-tope") || {}).value);
    const max_vueltas = Number((document.getElementById("f-vueltas") || {}).value);
    const falso = !!(document.getElementById("f-falso") || {}).checked;

    try {
      const resp = await fetch("/api/lanzar", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Enjambre": "1" },
        body: JSON.stringify({ repo, tope_usd, max_vueltas, falso }),
      });
      const cuerpo = await resp.json().catch(() => ({}));
      if (resp.status === 202) {
        location.href = `?run=${encodeURIComponent(`${cuerpo.repo}/${cuerpo.run}`)}&modo=directo`;
        return; // la navegación ya se encarga de todo lo demás
      }
      if (error) error.textContent = cuerpo.error || `error ${resp.status} al lanzar`;
    } catch (err) {
      if (error) error.textContent = `no se pudo contactar con el servidor: ${err}`;
    } finally {
      if (btn) btn.disabled = false;
    }
  };
}

// ---------------------------------------------------------------------------
// Modo repetición: reloj virtual propio, con compresión de huecos >5s a 1s
// (si no, ver a un Sonnet "pensando" en un hueco real es aburrido — pedido
// explícito del plan, Tarea 10).
// ---------------------------------------------------------------------------

async function _arrancarRepeticion(repo, run) {
  let eventos;
  try {
    const resp = await fetch(`/api/eventos/${encodeURIComponent(repo)}/${encodeURIComponent(run)}.jsonl`);
    const texto = await resp.text();
    eventos = texto
      .split("\n")
      .map((linea) => linea.trim())
      .filter((linea) => linea.length > 0)
      .map((linea) => {
        try {
          return JSON.parse(linea);
        } catch {
          return null; // línea corrupta: se ignora, no tumba la repetición
        }
      })
      .filter((ev) => ev !== null);
  } catch (err) {
    _actualizarCabecera(`error cargando eventos: ${err}`);
    return;
  }

  if (eventos.length === 0) {
    _actualizarCabecera("run sin eventos");
    return;
  }

  // vTimes[i]: instante virtual (ms desde el inicio, con huecos grandes
  // comprimidos) en el que el evento i ya está aplicado.
  const vTimes = new Array(eventos.length);
  vTimes[0] = 0;
  for (let i = 1; i < eventos.length; i++) {
    const real = Date.parse(eventos[i].t) - Date.parse(eventos[i - 1].t);
    const comprimido = real > 5000 ? 1000 : Math.max(0, real || 0);
    vTimes[i] = vTimes[i - 1] + comprimido;
  }
  const tVirtualMax = vTimes[vTimes.length - 1];
  const t0 = Date.parse(eventos[0].t);

  let tVirtual = 0;
  let velocidad = 1;
  let pausado = false;
  let ultimoFrame = null;
  let rafId = null;

  const barra = document.getElementById("barra");
  const btnPausa = document.getElementById("btn-pausa");
  const botonesVelocidad = Array.from(document.querySelectorAll("#controles [data-vel]"));

  if (barra) {
    barra.min = "0";
    barra.max = String(eventos.length);
    barra.value = "0";
  }

  // k: número de eventos aplicados dado el `tVirtual` actual.
  function _kDesdeVirtual(tv) {
    let k = 0;
    while (k < vTimes.length && vTimes[k] <= tv) k++;
    return k;
  }

  function _aplicarHasta(k) {
    _estado = eventos.slice(0, k).reduce(aplicar, inicial());
    _actualizarCabecera();
    // `ahoraMs` para `pintar` tiene que estar en la misma base que los
    // timestamps `t` de los eventos (reales, sin comprimir): `bocadillo.t`
    // y `loro.t` (T11) son timestamps reales tal cual vienen del evento, y
    // su edad se mide como `ahoraMs - Date.parse(ese.t)`. `t0 + tVirtual`
    // está en la base COMPRIMIDA (huecos >5s cuentan como 1s, para que la
    // repetición no sea aburrida -- ver más abajo, vTimes) -- mezclar las
    // dos bases en esa resta hace que, pasados los primeros huecos largos,
    // `ahoraMs` quede muy por debajo del timestamp real del evento recién
    // aplicado: la edad sale negativa, falla `edadMs >= 0` y el bocadillo o
    // el loro nunca se pintan. Encontrado contra un run real con huecos de
    // verdad (un `--falso` no lo manifiesta: sus eventos están casi
    // pegados en el tiempo y la compresión apenas actúa).
    // El *ritmo* de reproducción (qué `k` toca en cada frame) se sigue
    // decidiendo con `tVirtual`/`vTimes`, sin tocar eso: solo cambia qué
    // instante se le pasa a `pintar`, para que quede en la misma base que
    // usará el modo directo (T12), que llamará a `pintar` vía `alimentar`
    // con un reloj real (`Date.now()`-like), no comprimido.
    const ahoraMs = k > 0 ? Date.parse(eventos[k - 1].t) : t0;
    pintar(_ctx, _estado, ahoraMs);
    _actualizarPaneles(_estado);
    if (barra) barra.value = String(k);
  }

  function _frame(ahora) {
    if (ultimoFrame === null) ultimoFrame = ahora;
    const dt = ahora - ultimoFrame;
    ultimoFrame = ahora;
    if (!pausado) {
      tVirtual = Math.min(tVirtual + dt * velocidad, tVirtualMax);
      _aplicarHasta(_kDesdeVirtual(tVirtual));
    }
    rafId = requestAnimationFrame(_frame);
  }

  if (btnPausa) {
    btnPausa.textContent = "Pausa";
    btnPausa.onclick = () => {
      pausado = !pausado;
      btnPausa.textContent = pausado ? "Reanudar" : "Pausa";
      ultimoFrame = null; // evita un salto grande de dt al reanudar
    };
  }

  for (const boton of botonesVelocidad) {
    boton.onclick = () => {
      velocidad = Number(boton.dataset.vel) || 1;
      for (const b of botonesVelocidad) b.classList.toggle("activo", b === boton);
    };
  }
  if (botonesVelocidad.length > 0) botonesVelocidad[0].classList.add("activo");

  if (barra) {
    barra.oninput = () => {
      const k = Number(barra.value);
      tVirtual = k === 0 ? 0 : vTimes[Math.min(k, vTimes.length) - 1];
      ultimoFrame = null;
      _aplicarHasta(k);
    };
  }

  // Pintado inicial (k=0) antes de que arranque el primer frame.
  _aplicarHasta(0);
  rafId = requestAnimationFrame(_frame);

  // Expuesto solo para depuración manual desde la consola del navegador;
  // no forma parte del contrato con T11/T12.
  window.__enjambre_debug = { eventos, vTimes, detener: () => rafId && cancelAnimationFrame(rafId) };
}

// ---------------------------------------------------------------------------
// Modo directo (T12): un EventSource contra /api/directo/<repo>/<run>,
// `alimentar` por cada mensaje tal cual pide el plan -- nada de reloj
// virtual ni barra, el servidor ya manda los eventos al ritmo real.
// ---------------------------------------------------------------------------

function _arrancarDirecto(repo, run) {
  const controles = document.getElementById("controles");
  if (controles) controles.hidden = true; // el plan pide ocultar los controles de repetición

  const aviso = document.getElementById("aviso-directo");
  const ocultarAviso = () => { if (aviso) aviso.hidden = true; };
  const mostrarAviso = (texto) => {
    if (!aviso) return;
    aviso.textContent = texto;
    aviso.hidden = false;
  };

  // Botón Parar (D21): visible en directo mientras no llegue `run_fin`,
  // igual que pide el plan. Pulsarlo llama a `POST /api/parar` -- el propio
  // `run_fin` (con `motivo: interrumpido`) llega por el mismo `EventSource`
  // de siempre, no hace falta tocar nada más aquí para que la pantalla se
  // entere. Si el servidor dice 409 (nada que parar desde su punto de
  // vista -- p.ej. este run se lanzó por CLI, no desde la página, D21:
  // "el servidor solo sabe lo que lanzó él mismo"), se avisa en vez de
  // fallar en silencio.
  const btnParar = document.getElementById("btn-parar");
  if (btnParar) {
    btnParar.hidden = false;
    btnParar.disabled = false;
    btnParar.onclick = async () => {
      btnParar.disabled = true;
      try {
        const resp = await fetch("/api/parar", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Enjambre": "1" },
          body: "{}",
        });
        if (resp.status !== 202) {
          const cuerpo = await resp.json().catch(() => ({}));
          mostrarAviso(cuerpo.error || `no se pudo parar (error ${resp.status})`);
          btnParar.disabled = false;
        }
        // 202: no hace falta nada más -- el run_fin:interrumpido llegará
        // solo por el EventSource y disparará la rama de abajo, que ya
        // oculta este botón.
      } catch (err) {
        mostrarAviso(`no se pudo contactar con el servidor: ${err}`);
        btnParar.disabled = false;
      }
    };
  }

  _estado = inicial();
  _estado.run = run;
  _actualizarCabecera("EN DIRECTO");
  pintar(_ctx, _estado, Date.now());
  _actualizarPaneles(_estado);
  ocultarAviso();

  let terminado = false;
  const url = `/api/directo/${encodeURIComponent(repo)}/${encodeURIComponent(run)}`;
  const es = new EventSource(url);

  es.onmessage = (ev) => {
    let evento;
    try {
      evento = JSON.parse(ev.data);
    } catch {
      return; // línea corrupta: se ignora, mismo criterio que la repetición
    }
    alimentar(evento);
    if (evento.tipo === "run_fin") {
      terminado = true;
      es.close();
      if (btnParar) btnParar.hidden = true;
      if (aviso) {
        aviso.innerHTML = "";
        aviso.append("run terminado -- ");
        const enlace = document.createElement("a");
        enlace.href = `?run=${encodeURIComponent(`${repo}/${run}`)}&modo=repeticion`;
        enlace.textContent = "ver repetición";
        aviso.append(enlace);
        aviso.hidden = false;
      }
    } else {
      // `alimentar` ya ha repintado la cabecera con el motivo real (null
      // todavía), que dejaría "—"; mientras no haya `run_fin` se fuerza
      // "EN DIRECTO" en su lugar.
      _actualizarCabecera("EN DIRECTO");
      // Si el aviso de "conexión perdida" seguía puesto de un corte
      // anterior, un mensaje que llega de verdad confirma que ya se ha
      // recuperado -- quitarlo, si no se queda pegado en pantalla aunque
      // todo vuelva a ir bien (visto al probar la reconexión de verdad
      // contra un servidor reiniciado a mitad de un run).
      ocultarAviso();
    }
  };

  es.onerror = () => {
    if (terminado) return; // cierre limpio tras run_fin: `close()` no es un error
    // El propio EventSource reintenta solo (comportamiento nativo del
    // navegador); cuando reconecte, `_servir_directo` siempre reabre
    // `eventos.jsonl` desde el principio (pantalla.py), así que hay que
    // vaciar el estado AHORA -- si no, los eventos reenviados se
    // reaplicarían sobre el estado ya construido y duplicarían bitácora/
    // inventario/coste.
    mostrarAviso("conexión perdida, reintentando…");
    _estado = inicial();
    _estado.run = run;
    _actualizarCabecera("conexión perdida, reintentando…");
    _actualizarPaneles(_estado);
  };
}

// ---------------------------------------------------------------------------
// Interacción con el lienzo: hover (tooltip nativo vía `title`) sobre un
// agente. D20 punto 6 quita el click sobre el inventario pintado dentro del
// lienzo (ya no existe ahí) -- el panel HTML de inventario tiene sus
// propios <button>, cada uno con su listener (`_actualizarInventario`, más
// arriba). Elección documentada en el informe de la tarea: un único
// <canvas> con hit-test manual contra las zonas calculadas en el último
// `pintar`, en vez de superponer elementos HTML invisibles — más simple de
// mantener sincronizado con un render que se repinta en cada frame.
// ---------------------------------------------------------------------------

function _coordsDesdeEvento(lienzo, evt) {
  const rect = lienzo.getBoundingClientRect();
  const escalaX = lienzo.width / rect.width;
  const escalaY = lienzo.height / rect.height;
  return {
    x: (evt.clientX - rect.left) * escalaX,
    y: (evt.clientY - rect.top) * escalaY,
  };
}

function _zonaEnPunto(zonas, x, y) {
  for (const z of zonas) {
    if (x >= z.x && x < z.x + z.w && y >= z.y && y < z.y + z.h) return z;
  }
  return null;
}

function _instalarInteraccionLienzo(lienzo) {
  lienzo.addEventListener("mousemove", (evt) => {
    const { x, y } = _coordsDesdeEvento(lienzo, evt);
    const zona = _zonaEnPunto(_zonasAgentes, x, y);
    if (!zona) {
      lienzo.title = "";
      return;
    }
    const a = zona.agente;
    const modelo = a.modelo_real || a.modelo_pedido || "—";
    const duracion = typeof a.duracion_s === "number" ? `${a.duracion_s.toFixed(1)}s` : "—";
    const coste = typeof a.coste_usd === "number" ? `$${a.coste_usd.toFixed(4)}` : "—";
    lienzo.title = `${zona.instancia}\nmodelo: ${modelo}\nduración: ${duracion}\ncoste: ${coste}`;
  });
}

// ---------------------------------------------------------------------------
// Panel lateral: ver el contenido de un fichero de la salida.
// ---------------------------------------------------------------------------

function _instalarPanelLateral() {
  const cerrar = document.getElementById("cerrar-panel");
  const panel = document.getElementById("panel-lateral");
  if (cerrar && panel) {
    cerrar.onclick = () => {
      panel.hidden = true;
    };
  }
}

async function _abrirFicheroEnPanel(ruta) {
  const panel = document.getElementById("panel-lateral");
  const contenido = document.getElementById("panel-contenido");
  if (!panel || !contenido || !_repo || !_run) return;
  panel.hidden = false;
  contenido.textContent = `cargando ${ruta}…`;
  try {
    const url = `/api/fichero/${encodeURIComponent(_repo)}/${encodeURIComponent(_run)}/${ruta
      .split("/")
      .map(encodeURIComponent)
      .join("/")}`;
    const resp = await fetch(url);
    contenido.textContent = resp.ok ? await resp.text() : `(${resp.status}) no se pudo leer ${ruta}`;
  } catch (err) {
    contenido.textContent = `error leyendo ${ruta}: ${err}`;
  }
}

// ---------------------------------------------------------------------------
// Escalado del lienzo: al mayor entero que quepa (CSS, `image-rendering:
// pixelated`), con tope ×4 y mínimo ×1 para los 360px de móvil del plan.
// ---------------------------------------------------------------------------

function _escalarLienzo(lienzo) {
  const margen = 16; // dos gutters laterales de 8px, holgado
  const disponible = Math.max(ANCHO, window.innerWidth - margen);
  let escala = Math.floor(disponible / ANCHO);
  escala = Math.max(1, Math.min(4, escala));
  lienzo.style.width = `${ANCHO * escala}px`;
  lienzo.style.height = `${ALTO * escala}px`;
}

// Export solo para que ROLES quede referenciado (evita warnings de lint por
// import sin uso si alguna herramienta lo exige); no forma parte del
// contrato de esta tarea, que solo pide arrancar/pintar/alimentar.
void ROLES;
