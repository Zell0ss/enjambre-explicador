// escena.js — render provisional (T10) de la pantalla del enjambre.
//
// Contrato con el resto del sistema (Tareas 11 y 12, ver plan §Tarea 10):
//   export function arrancar(lienzo, cabecera)  — arranca la página entera.
//   export function pintar(ctx2d, estado, ahoraMs) — SOLO dibuja: T11 la
//     sustituye (junto a sus auxiliares de más abajo) por sprites, sin tocar
//     nada de lo que hay debajo de la marca "FIN pintar y auxiliares".
//   export function alimentar(evento) — aplica un evento sobre el estado
//     compartido y repinta; la usará el modo directo (T12) tras importar
//     este módulo y abrir su propio EventSource. Aquí solo tiene que existir
//     y funcionar: no se abre SSE desde esta tarea.
//
// Acoplamiento documentado con index.html (fuera de la firma de `arrancar`,
// que solo recibe lienzo y cabecera): este módulo busca por id en `document`
// los controles de repetición (#controles, #btn-pausa, botones [data-vel],
// #barra), la lista de runs (#lista-runs), el contenedor del lienzo
// (#zona-lienzo) y el panel lateral (#panel-lateral, #panel-contenido,
// #cerrar-panel). index.html y escena.js se escriben juntos en esta misma
// tarea, así que esta costura es segura; si se separan algún día, pasar a
// hacerlo explícito por parámetros.

import { inicial, aplicar, ROLES } from "./estado.js";
import {
  SPRITES,
  FONDO,
  LORO,
  COLOR_TEXTO,
  ALTO_GLIFO,
  ANCHO_PERSONAJE,
  ALTO_PERSONAJE,
  dibujar,
  dibujarTexto,
  medirTexto,
} from "./sprites.js";

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
let _zonasAgentes = []; // {x,y,w,h, instancia, agente}
let _zonasInventario = []; // {x,y,w,h, item}

// Rectángulos de los bocadillos ya dibujados en el fotograma actual
// (incluido el del loro), para que `_dibujarBocadillo` pueda subir de
// carril cuando dos agentes muy juntos hablan a la vez -- ver ahí.
let _bocadillosDibujados = []; // {x1,y1,x2,y2}

// Elementos de cabecera, rellenados una vez en `arrancar`.
let _cab = null;

export function arrancar(lienzo, cabecera) {
  _ctx = lienzo.getContext("2d");
  _ctx.imageSmoothingEnabled = false; // pixel art: nunca interpolar al escalar (pedido de Josem)
  _escalarLienzo(lienzo);
  window.addEventListener("resize", () => _escalarLienzo(lienzo));

  _cab = _construirCabecera(cabecera);
  _actualizarCabecera();

  _instalarInteraccionLienzo(lienzo);
  _instalarPanelLateral();

  const params = new URLSearchParams(location.search);
  const run = params.get("run");
  const modo = params.get("modo") || "repeticion";

  const zonaLienzo = document.getElementById("zona-lienzo");
  const listaRuns = document.getElementById("lista-runs");

  if (!run) {
    if (zonaLienzo) zonaLienzo.hidden = true;
    if (listaRuns) listaRuns.hidden = false;
    _cargarListaRuns(listaRuns);
    // Nada que pintar todavía: se deja el lienzo con el estado inicial
    // en blanco para que no quede un canvas sin inicializar si alguien
    // navega hacia atrás desde una repetición.
    pintar(_ctx, _estado, Date.now());
    return;
  }

  if (zonaLienzo) zonaLienzo.hidden = false;
  if (listaRuns) listaRuns.hidden = true;

  const partido = run.split("/");
  _repo = partido[0] || "";
  _run = partido.slice(1).join("/") || "";

  if (modo === "directo") {
    // Fuera de alcance de T10 (plan: "en esta tarea NO la uses todavía").
    // Se deja el estado inicial pintado y la cabecera avisando; T12 importa
    // `alimentar` de este módulo y la llama por cada mensaje SSE recibido
    // de `/api/directo/<repo>/<run>` — no hace falta tocar `arrancar` para
    // eso, que es justo el punto de tener `alimentar` ya separada.
    _estado = inicial();
    _estado.run = _run;
    _actualizarCabecera("modo directo: pendiente (Tarea 12)");
    pintar(_ctx, _estado, Date.now());
    return;
  }

  _arrancarRepeticion(_repo, _run);
}

// ---------------------------------------------------------------------------
// pintar y auxiliares -- T11 sustituye SOLO esta sección (de aquí a
// "FIN pintar y auxiliares") por sprites, sin tocar arrancar/alimentar ni el
// resto del fichero.
// ---------------------------------------------------------------------------

const ANCHO = 320;
const ALTO = 200;
const ALTO_ESCENA = 144;
const ALTO_BARRA = 56;

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

// Mobiliario de cubierta y el puesto del agente que trabaja en él (§5.3).
// `fx,fy` posiciona el elemento de FONDO; `x,y` ancla la esquina superior
// izquierda del sprite de 24×32 del agente, justo encima/detrás del
// mueble para que quede a sus pies. Coordenadas elegidas a mano sobre el
// lienzo de 320×144 (cielo 0-71, cubierta 72-143); revisadas con una
// captura real (ver informe de la tarea), no solo a ojo de código.
// (x,y de cada agente separados al menos ~40px en x o en y del resto: con
// 24×32 por personaje, dos puestos en la misma columna y menos de eso de
// diferencia en y se fusionan en un solo tótem apilado -- visto en la
// primera captura real contra el servidor, corregido aquí.)
const PUESTOS = {
  despiezador: { furn: "cocina", fx: 12, fy: 50, x: 10, y: 46 }, // cocina, atrás a babor
  redactor: { furn: "escritorio", fx: 254, fy: 48, x: 252, y: 46 }, // escritorio, atrás a estribor
  cartografo: { furn: "mesaMapa", fx: 46, fy: 100, x: 44, y: 86 }, // mesa del mapa, delante
  verificador: { furn: "barriles", fx: 238, fy: 106, x: 236, y: 92 }, // barriles, delante centro-estribor
  trazador: { furn: "timon", fx: 288, fy: 98, x: 286, y: 80 }, // timón, delante a estribor
  novato: { furn: null, x: 146, y: 10 }, // cofa, en lo alto del mástil
};

const MASTIL_X = 140;
const MASTIL_Y = 0;
const MESA_LARGA_X = 84;
const MESA_LARGA_Y = 104;

// Fila de lectores sobre la mesa larga (hasta 8, tope del despiezador; si
// llegan más se apilan encima, sin rediseñar — §5.3).
// = ANCHO_PERSONAJE (24): con menos que eso dos lectores contiguos se pisan
// (el sprite usa casi todo su ancho de 24px -- brazos/herramienta incluidos
// -- así que cualquier paso menor solapa cuerpos). Visto en captura real
// contra el servidor (Josem: "lector de piezas están muy juntos"),
// corregido aquí: antes era 18.
const LECTORES_PASO_X = ANCHO_PERSONAJE;

function _posicionLector(indice) {
  const i = indice % 8;
  const pila = Math.floor(indice / 8);
  return { x: MESA_LARGA_X + 6 + i * LECTORES_PASO_X, y: MESA_LARGA_Y - 28 - pila * 10 };
}

function _posicionAgente(rol, indiceLector) {
  if (rol === "lector-de-pieza") return _posicionLector(indiceLector);
  const puesto = PUESTOS[rol];
  return puesto ? { x: puesto.x, y: puesto.y } : { x: 150, y: 70 };
}

// Farolillos fijos que parpadean (2 fotogramas en FONDO.farolillo).
const FAROLES = [
  { x: 36, y: 28 },
  { x: 150, y: 24 },
  { x: 288, y: 30 },
];

/**
 * pintar(ctx2d, estado, ahoraMs) — dibuja la escena entera con los sprites
 * de `sprites.js`. Pura en el sentido de que solo lee `estado`/`ahoraMs` y
 * escribe en `ctx2d` (y en las cachés de zonas de módulo, para hit-test de
 * click/hover); no hace fetch ni toca `location`.
 */
export function pintar(ctx2d, estado, ahoraMs) {
  _zonasAgentes = [];
  _zonasInventario = [];
  _bocadillosDibujados = [];

  // --- Fondo: cielo, cubierta y mobiliario fijo del barco -----------------
  dibujar(ctx2d, _fotogramaDe(FONDO.cielo, ahoraMs), 0, 0);
  dibujar(ctx2d, _fotogramaDe(FONDO.cubierta, ahoraMs), 0, 72);
  dibujar(ctx2d, _fotogramaDe(FONDO.mastil, ahoraMs), MASTIL_X, MASTIL_Y);
  dibujar(ctx2d, _fotogramaDe(FONDO.mesaLarga, ahoraMs), MESA_LARGA_X, MESA_LARGA_Y);
  for (const puesto of Object.values(PUESTOS)) {
    if (puesto.furn) dibujar(ctx2d, _fotogramaDe(FONDO[puesto.furn], ahoraMs), puesto.fx, puesto.fy);
  }
  for (const farol of FAROLES) dibujar(ctx2d, _fotogramaDe(FONDO.farolillo, ahoraMs), farol.x, farol.y);

  // Fondo liso de la barra SCUMM (el arte ahí es solo este rectángulo: la
  // barra en sí no forma parte de la escena 320×144).
  ctx2d.fillStyle = "#3a2a1e";
  ctx2d.fillRect(0, ALTO_ESCENA, ANCHO, ALTO_BARRA);

  // --- Agentes --------------------------------------------------------------
  // Orden de inserción de `estado.agentes` ya es estable (claves string),
  // así que basta un contador para numerar a los lectores en fila.
  let indiceLector = 0;
  for (const [instancia, agente] of Object.entries(estado.agentes || {})) {
    const rol = agente.rol;
    const indice = rol === "lector-de-pieza" ? indiceLector++ : 0;
    const pos = _posicionAgente(rol, indice);
    const frames = SPRITES[rol] && SPRITES[rol][agente.estado];
    const fotograma = _fotogramaDe(frames, ahoraMs);
    if (fotograma) dibujar(ctx2d, fotograma, pos.x, pos.y);

    _zonasAgentes.push({ x: pos.x, y: pos.y, w: ANCHO_PERSONAJE, h: ALTO_PERSONAJE, instancia, agente });

    // Bocadillo centrado sobre la cabeza, recortado al lienzo; se borra a
    // los ~3s de `bocadillo.t` (§5.3).
    if (agente.bocadillo && agente.bocadillo.t) {
      const edadMs = ahoraMs - Date.parse(agente.bocadillo.t);
      if (edadMs >= 0 && edadMs < 3000) {
        _dibujarBocadillo(
          ctx2d,
          agente.bocadillo.texto,
          pos.x + ANCHO_PERSONAJE / 2,
          pos.y - 2,
          COLOR_TEXTO[rol] || "#ffffff",
        );
      }
    }
  }

  // --- El loro: vuela del borde del lienzo al agente denegado -------------
  // (misma regla de visibilidad ~3s que los bocadillos, mismo campo `t`).
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

  // --- Barra inferior: bitácora a la izquierda... --------------------------
  const lineas = (estado.bitacora || []).slice(-5);
  lineas.forEach((linea, i) => {
    _dibujarTextoRecortado(ctx2d, linea, 4, ALTO_ESCENA + 4 + i * 9, 216, "#e8e0c8");
  });

  // ...e inventario a la derecha: un icono por fichero, con el nombre corto
  // (basename) debajo para que no haga falta pasar el ratón para leerlo
  // (pedido de Josem: "antes solo había iconos sin nombre"). El hover
  // (`lienzo.title`, más abajo) sigue dando la ruta completa.
  const inventario = estado.inventario || [];
  const colInicioX = 224;
  const iconoLado = 14;
  const pasoCol = 48;
  const porFila = Math.max(1, Math.floor((ANCHO - colInicioX - 2) / pasoCol));
  inventario.forEach((item, i) => {
    const fila = Math.floor(i / porFila);
    const col = i % porFila;
    const x = colInicioX + col * pasoCol;
    const y = ALTO_ESCENA + 3 + fila * (iconoLado + 11);
    if (y > ALTO_ESCENA + ALTO_BARRA - iconoLado - 2) return; // sin sitio: no desborda el lienzo (§5.3, "no rediseñar")
    ctx2d.fillStyle = "#c8a24a";
    ctx2d.fillRect(x, y, iconoLado, iconoLado);
    ctx2d.strokeStyle = "#000000";
    ctx2d.strokeRect(x + 0.5, y + 0.5, iconoLado - 1, iconoLado - 1);
    const nombreCorto = (item.ruta || "").split("/").pop() || "?";
    _dibujarTextoRecortado(ctx2d, nombreCorto, x, y + iconoLado + 1, pasoCol - 2, "#e8e0c8");
    _zonasInventario.push({ x, y, w: iconoLado, h: iconoLado, item });
  });
}

// Bocadillo de diálogo: centrado horizontalmente sobre `cx`, con el pie en
// `yInferior`, recortado para no salirse del lienzo de 320 de ancho.
//
// Con los lectores en fila (hasta 8, separados solo ANCHO_PERSONAJE=24px),
// sus bocadillos son casi siempre más anchos que la separación entre ellos
// -- varios a la vez se escribían unos encima de otros (Josem, captura real:
// "su texto se sobreescribe"). Si el rectángulo candidato choca en x e y con
// uno ya dibujado este mismo fotograma, sube un carril (una altura de
// glifo) y reintenta, hasta MAX_CARRILES; si para entonces sigue chocando
// (muchos lectores hablando literalmente a la vez) se dibuja de todos
// modos en el último carril probado -- ilegible en el peor caso, pero ya
// no 100% de las veces como antes, y sin rediseñar el layout de la mesa.
// 9 carriles cubre el peor caso real: hasta 8 lectores simultáneos (tope
// documentado en `_posicionLector` antes de apilar) más el bocadillo del
// loro -- probado con 5 a la vez (4 lectores + loro) a 4 carriles y seguía
// chocando uno; con 9 cabe de sobra en el cielo del lienzo (banda 0-71,
// carril 8 queda en y≈3) sin tocar nada más de la escena.
const PASO_CARRIL = ALTO_GLIFO + 1;
const MAX_CARRILES = 9;

function _dibujarBocadillo(ctx2d, texto, cx, yInferior, color) {
  if (!texto) return;
  const ancho = medirTexto(texto);
  const x = Math.max(1, Math.min(ANCHO - ancho - 1, Math.round(cx - ancho / 2)));
  let y = Math.max(0, yInferior - ALTO_GLIFO);
  for (let carril = 1; carril < MAX_CARRILES; carril++) {
    const choca = _bocadillosDibujados.some(
      (b) => x < b.x2 && x + ancho > b.x1 && y < b.y2 && y + ALTO_GLIFO > b.y1,
    );
    if (!choca || y <= 0) break;
    y = Math.max(0, y - PASO_CARRIL);
  }
  _bocadillosDibujados.push({ x1: x, y1: y, x2: x + ancho, y2: y + ALTO_GLIFO });
  dibujarTexto(ctx2d, texto, x, y, color);
}

// Recorte por medida real de la fuente de mapa de bits (ya no por conteo
// tosco de caracteres, como en el render provisional de T10): añade un "."
// final mientras no quepa.
function _dibujarTextoRecortado(ctx2d, texto, x, y, anchoMax, color) {
  if (!texto) return;
  let recortado = String(texto);
  if (medirTexto(recortado) > anchoMax) {
    while (recortado.length > 1 && medirTexto(recortado + ".") > anchoMax) {
      recortado = recortado.slice(0, -1);
    }
    recortado = `${recortado}.`;
  }
  dibujarTexto(ctx2d, recortado, x, y, color);
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
    const aDir = document.createElement("a");
    aDir.href = `?run=${encodeURIComponent(id)}&modo=directo`;
    aDir.textContent = "[directo]";
    li.append(etiqueta, aRep, document.createTextNode(" "), aDir);
    ul.appendChild(li);
  }
  contenedor.innerHTML = "";
  contenedor.appendChild(ul);
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
// Interacción con el lienzo: hover (tooltip nativo vía `title`) y click
// (inventario -> panel lateral). Elección documentada en el informe de la
// tarea: un único <canvas> con hit-test manual contra las zonas calculadas
// en el último `pintar`, en vez de superponer elementos HTML invisibles —
// más simple de mantener sincronizado con un render que se repinta en cada
// frame.
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

  lienzo.addEventListener("click", (evt) => {
    const { x, y } = _coordsDesdeEvento(lienzo, evt);
    const zona = _zonaEnPunto(_zonasInventario, x, y);
    if (!zona) return;
    _abrirFicheroEnPanel(zona.item.ruta);
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
