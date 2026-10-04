// mesa.js — pantalla del enjambre: "la mesa de papeles" (D22), que sustituye
// a la escena única de personajes (D20, escena.js) por una rejilla de
// tarjetas HTML en el orden del flujo. Modo repetición (T10/T11) y modo
// directo por SSE (T12) se mantienen sin cambios de mecánica -- solo cambia
// la COMPOSICIÓN visual.
//
// Contrato con el resto del sistema:
//   export async function arrancar(mesaEl, cabecera) — arranca la página
//     entera. CAMBIO DE FIRMA respecto a escena.js (documentado abajo, junto
//     a la declaración): el primer parámetro ya no es un <canvas> único
//     (D20 lo pintaba con `pintar(ctx2d, ...)`), es el contenedor `<div
//     id="mesa">` donde este módulo construye las tarjetas -- no hay un solo
//     lienzo que escalar, hay varios <canvas> pequeños (uno por sprite),
//     fijos a escala entera por CSS (ver `_crearCartaFija`/`_crearFilaLector`
//     más abajo), así que no hace falta recibirlo como parámetro ni
//     escucharlo con ResizeObserver para escalarlo.
//   export function alimentar(evento) — aplica un evento sobre el estado
//     compartido y repinta. La usa el modo directo (`_arrancarDirecto`, más
//     abajo) por cada `message` de su `EventSource`, igual que antes.
//
// Acoplamiento documentado con index.html (fuera de la firma de `arrancar`):
// este módulo busca por id en `document` los controles de repetición
// (#controles, #btn-pausa, botones [data-vel], #barra), el aviso del modo
// directo (#aviso-directo), el botón Parar (#btn-parar), la lista de runs
// (#lista-runs), el formulario de lanzar (#form-lanzar y sus campos), la
// zona de la mesa (#zona-mesa), el contenedor de flechas (#flechas), el
// panel "Ahora" (#lista-ahora), la bitácora (#lista-bitacora), las puertas
// (#puertas) y el panel lateral (#panel-lateral, #panel-contenido,
// #cerrar-panel). index.html y mesa.js se escriben juntos, así que esta
// costura es segura; si se separan algún día, pasar a hacerlo explícito por
// parámetros.

import { inicial, aplicar, nombreCorto } from "./estado.js";
import { SPRITES, COLOR_TEXTO, ANCHO_PERSONAJE, ALTO_PERSONAJE, dibujar, cargarSpritesPersonajes } from "./sprites.js";

// D22: todo el texto de la vista (nombres, estados, bocadillos, fichas,
// puertas, bitácora) pasa a ser HTML normal, no texto dibujado a mano en un
// <canvas> -- por eso este módulo YA NO importa `dibujarTexto`, `medirTexto`,
// `cargarFuenteTexto`, `FUENTE_CSS`, `ANCHO_GLIFO` ni `ALTO_GLIFO` de
// `sprites.js`. Esas funciones se QUEDAN en `sprites.js` sin tocar (no se
// borran): mismo criterio que Josem pidió explícitamente esta sesión para
// `pantalla/fuente-pixel.js` ("la usaremos para algo", código que funciona y
// podría reutilizarse no se borra solo porque esta tarea deje de llamarlo).
// `pantalla/fuente-pixel.js` tampoco se toca por el mismo motivo -- ya estaba
// sin ningún llamador antes de esta tarea (confirmado por grep), y sigue así.

// ---------------------------------------------------------------------------
// Estado de módulo -- una sola fuente de verdad para `_render` (§5.2: "toda
// la página es una función de estado"). Tanto el modo repetición como el
// modo directo (T12) escriben aquí.
// ---------------------------------------------------------------------------
let _estado = inicial();
let _repo = null;
let _run = null;
let _cab = null;
let _cartas = {}; // rol -> elemento <div class="carta">, más "lector-de-pieza" -> la tarjeta de lectores

// Duración de cada fotograma de animación, en ms de `ahoraMs` (reloj
// virtual en repetición -- avanza ×velocidad --, reloj real en directo).
// Mismo valor y mismo razonamiento que tenía escena.js (D19/D20): a ×16 el
// ciclo se acelera en la misma proporción; no se ha podido comprobar a ojo,
// sin navegador, cómo se percibe exactamente ahí.
const MS_POR_FOTOGRAMA = 450;

function _fotogramaDe(frames, ahoraMs) {
  if (!frames || frames.length === 0) return null;
  const i = Math.floor(Math.max(0, ahoraMs) / MS_POR_FOTOGRAMA) % frames.length;
  return frames[i];
}

// Paleta de 8 tonos para lectores (D20 punto 4, heredada tal cual): un color
// por INSTANCIA, no por rol -- el índice se asigna por orden de aparición en
// `estado.agentes` (ver `_indicesLectores`, más abajo), así que un mismo
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

// ---------------------------------------------------------------------------
// D22 punto 1: tarjetas fijas en el orden del flujo. `col`/`fila` son
// posiciones LÓGICAS de rejilla (CSS las traduce vía selectores
// `[data-rol]`, ver index.html) -- nunca píxeles. La tarjeta de lectores
// (col 2, ocupa las dos filas) se construye aparte, `_crearCartaLectores`.
// ---------------------------------------------------------------------------
const CARTAS_FIJAS = [
  { rol: "cartografo", titulo: "Cartógrafo" },
  { rol: "despiezador", titulo: "Despiezador" },
  { rol: "trazador", titulo: "Trazador" },
  { rol: "redactor", titulo: "Redactor" },
  { rol: "verificador", titulo: "Verificador" },
  { rol: "novato", titulo: "Novato" },
];

export async function arrancar(mesaEl, cabecera) {
  const cargaSprites = cargarSpritesPersonajes();

  _cab = _construirCabecera(cabecera);
  _actualizarCabecera();

  _cartas = _construirMesa(mesaEl);
  _construirPuertas(document.getElementById("puertas"));
  _instalarPanelLateral();

  // D22 punto 1: "las flechas salen de la posición real de las tarjetas...
  // nunca coordenadas de píxel fijas" -- se recalculan dentro de `_render`
  // en cada fotograma (barato: 7 `getBoundingClientRect`), y también al
  // cambiar el tamaño de ventana mientras la repetición está en pausa (ahí
  // `_render` no se vuelve a llamar solo, así que hace falta este listener
  // aparte para que un resize en pausa no deje las flechas desincronizadas).
  window.addEventListener("resize", () => _recalcularFlechas(_estado));

  const params = new URLSearchParams(location.search);
  const run = params.get("run");
  const modo = params.get("modo") || "repeticion";

  const zonaMesa = document.getElementById("zona-mesa");
  const listaRuns = document.getElementById("lista-runs");
  const formLanzar = document.getElementById("form-lanzar");

  if (!run) {
    if (zonaMesa) zonaMesa.hidden = true;
    if (listaRuns) listaRuns.hidden = false;
    if (formLanzar) formLanzar.hidden = false;
    if (_cab.volver) _cab.volver.hidden = true;
    _cargarListaRuns(listaRuns);
    _instalarFormularioLanzar(formLanzar);
    // Nada que pintar todavía: se deja la mesa en su estado inicial para que
    // no quede nada sin inicializar si alguien navega hacia atrás desde una
    // repetición.
    _render(_estado, Date.now());
    return;
  }

  if (zonaMesa) zonaMesa.hidden = false;
  if (listaRuns) listaRuns.hidden = true;
  if (formLanzar) formLanzar.hidden = true;
  // Botón para volver a la portada (lista de runs / formulario de lanzar)
  // sin tocar la barra de direcciones -- `href="?"` quita `run`/`modo` sin
  // tocar el resto de la URL (no hay otros parámetros que conservar).
  if (_cab.volver) _cab.volver.hidden = false;

  const partido = run.split("/");
  _repo = partido[0] || "";
  _run = partido.slice(1).join("/") || "";

  if (modo === "directo") {
    await cargaSprites;
    _arrancarDirecto(_repo, _run);
    return;
  }

  await cargaSprites;
  _arrancarRepeticion(_repo, _run);
}

/**
 * alimentar(evento) — aplica un evento sobre el estado compartido de módulo
 * y repinta. La usa el modo directo (T12).
 */
export function alimentar(evento) {
  _estado = aplicar(_estado, evento);
  _actualizarCabecera();
  _render(_estado, Date.now());
}

// ---------------------------------------------------------------------------
// Construcción de la mesa (tarjetas) -- una vez, al arrancar.
// ---------------------------------------------------------------------------

function _construirMesa(mesaEl) {
  mesaEl.innerHTML = "";
  const cartas = {};
  for (const spec of CARTAS_FIJAS) {
    const carta = _crearCartaFija(spec);
    mesaEl.appendChild(carta);
    cartas[spec.rol] = carta;
  }
  const cartaLectores = _crearCartaLectores();
  mesaEl.appendChild(cartaLectores);
  cartas["lector-de-pieza"] = cartaLectores;
  return cartas;
}

function _crearCartaFija({ rol, titulo }) {
  const carta = document.createElement("div");
  carta.className = "carta";
  carta.dataset.rol = rol;
  const anchoCanvas = ANCHO_PERSONAJE * 3;
  const altoCanvas = ALTO_PERSONAJE * 3;
  carta.innerHTML =
    `<h3 class="carta-titulo">${titulo}</h3>` +
    `<div class="carta-cabeza">` +
    `<canvas class="carta-sprite" width="${ANCHO_PERSONAJE}" height="${ALTO_PERSONAJE}" ` +
    `style="width:${anchoCanvas}px;height:${altoCanvas}px"></canvas>` +
    `<div class="carta-info">` +
    `<div class="carta-estado">esperando</div>` +
    `<div class="carta-modelo">modelo —</div>` +
    `<div class="carta-fin" hidden></div>` +
    `</div></div>` +
    `<div class="carta-ahora"></div>` +
    `<ul class="carta-fichas"></ul>`;
  return carta;
}

function _crearCartaLectores() {
  const carta = document.createElement("div");
  carta.className = "carta carta-lectores";
  carta.dataset.rol = "lector-de-pieza";
  carta.innerHTML =
    `<h3 class="carta-titulo">Lectores <span class="carta-subtitulo"></span></h3>` +
    `<div class="filas-lectores"></div>`;
  return carta;
}

// instancia -> fila ya creada (nunca se destruyen: un lector no desaparece).
const _filasLectores = new Map();
// instancia -> índice estable (orden de aparición), para el color de
// `COLOR_LECTORES` -- igual que `indiceLector` en la vieja escena.js.
const _indicesLectores = new Map();

function _crearFilaLector() {
  const el = document.createElement("div");
  el.className = "fila-lector";
  const anchoCanvas = ANCHO_PERSONAJE * 2;
  const altoCanvas = ALTO_PERSONAJE * 2;
  el.innerHTML =
    `<canvas class="fila-lector-sprite" width="${ANCHO_PERSONAJE}" height="${ALTO_PERSONAJE}" ` +
    `style="width:${anchoCanvas}px;height:${altoCanvas}px"></canvas>` +
    `<div class="fila-lector-datos">` +
    `<div class="fila-lector-nombre"></div>` +
    `<div class="fila-lector-estado"></div>` +
    `<ul class="fila-lector-fichas"></ul>` +
    `</div>`;
  return {
    el,
    canvas: el.querySelector("canvas"),
    nombre: el.querySelector(".fila-lector-nombre"),
    estado: el.querySelector(".fila-lector-estado"),
    fichas: el.querySelector(".fila-lector-fichas"),
  };
}

// ---------------------------------------------------------------------------
// `_render` -- la única función que vuelve a pintar TODO a partir de
// `estado`, llamada tanto por el reloj virtual de la repetición como por
// `alimentar` en directo (mismo patrón que `pintar`+`_actualizarPaneles` en
// escena.js, fusionados aquí en una sola función porque ya no hay un
// <canvas> de escena que pintar aparte de los paneles).
// ---------------------------------------------------------------------------

function _render(estado, ahoraMs) {
  for (const spec of CARTAS_FIJAS) {
    _actualizarCartaFija(_cartas[spec.rol], spec.rol, estado, ahoraMs);
  }
  _actualizarLectores(_cartas["lector-de-pieza"], estado, ahoraMs);
  _recalcularFlechas(estado);
  _actualizarAhora(estado);
  _actualizarBitacora(estado);
  _actualizarPuertas(estado, ahoraMs);
}

function _actualizarCartaFija(carta, rol, estado, ahoraMs) {
  if (!carta) return;
  const instancia = rol; // los seis roles fijos tienen una sola instancia, == su rol (sin ":")
  const agente = (estado.agentes || {})[instancia];
  const estadoAgente = agente ? agente.estado : "esperando";

  const canvas = carta.querySelector("canvas.carta-sprite");
  if (canvas) _pintarSprite(canvas, rol, estadoAgente, ahoraMs);

  carta.classList.toggle("carta--activa", estadoAgente === "leyendo" || estadoAgente === "escribiendo");
  carta.classList.toggle("carta--bloqueada", estadoAgente === "bloqueado");

  const estadoEl = carta.querySelector(".carta-estado");
  if (estadoEl) estadoEl.textContent = estadoAgente;

  const modeloEl = carta.querySelector(".carta-modelo");
  if (modeloEl) modeloEl.textContent = agente && agente.modelo_pedido ? `modelo ${agente.modelo_pedido}` : "modelo —";

  // "Al terminar, duración y coste" (punto 2) -- se muestra en cuanto
  // `fin_agente` ha llegado (duracion_s deja de ser null), con
  // independencia de qué diga el ÚLTIMO evento `estado` (normalmente
  // "terminado", pero un agente que acabó bloqueado también trae
  // `fin_agente` y merece ver su duración/coste).
  const finEl = carta.querySelector(".carta-fin");
  if (finEl) {
    if (agente && typeof agente.duracion_s === "number") {
      finEl.hidden = false;
      const coste = typeof agente.coste_usd === "number" ? `$${agente.coste_usd.toFixed(4)}` : "—";
      finEl.textContent = `${agente.duracion_s.toFixed(1)}s · ${coste}`;
    } else {
      finEl.hidden = true;
    }
  }

  const ahoraEl = carta.querySelector(".carta-ahora");
  if (ahoraEl) {
    ahoraEl.style.color = COLOR_TEXTO[rol] || "#ffffff";
    ahoraEl.textContent = agente && agente.bocadillo ? agente.bocadillo.texto : "";
  }

  const fichasEl = carta.querySelector(".carta-fichas");
  if (fichasEl) {
    const items = (estado.inventario || []).filter((i) => i.agente === instancia);
    _listaFichas(fichasEl, items, ahoraMs);
  }
}

function _actualizarLectores(carta, estado, ahoraMs) {
  if (!carta) return;
  const subtitulo = carta.querySelector(".carta-subtitulo");
  const filasCont = carta.querySelector(".filas-lectores");
  // D22 punto 3: "el rótulo de la tarjeta dice cuántas piezas decidió el
  // despiezador" -- contando las instancias de rol lector-de-pieza que haya
  // en `estado.agentes`, tal cual pide el encargo (no un campo nuevo del
  // reductor).
  const entradas = Object.entries(estado.agentes || {}).filter(([, a]) => a.rol === "lector-de-pieza");
  if (subtitulo) subtitulo.textContent = `(${entradas.length} pieza${entradas.length === 1 ? "" : "s"})`;

  for (const [instancia, agente] of entradas) {
    if (!_indicesLectores.has(instancia)) _indicesLectores.set(instancia, _indicesLectores.size);
    let fila = _filasLectores.get(instancia);
    if (!fila) {
      fila = _crearFilaLector();
      _filasLectores.set(instancia, fila);
      if (filasCont) filasCont.appendChild(fila.el);
    }
    const indice = _indicesLectores.get(instancia);
    const color = COLOR_LECTORES[indice % COLOR_LECTORES.length];

    _pintarSprite(fila.canvas, "lector-de-pieza", agente.estado, ahoraMs);
    fila.el.classList.toggle("fila-lector--activa", agente.estado === "leyendo" || agente.estado === "escribiendo");
    fila.el.classList.toggle("fila-lector--bloqueada", agente.estado === "bloqueado");
    fila.nombre.textContent = nombreCorto(instancia);
    fila.nombre.style.color = color;
    fila.estado.textContent = agente.estado;

    const items = (estado.inventario || []).filter((i) => i.agente === instancia);
    _listaFichas(fila.fichas, items, ahoraMs);
  }
}

function _pintarSprite(canvas, rol, estadoAgente, ahoraMs) {
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false; // pixel art: nunca interpolar (D19/D20)
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const frames = SPRITES[rol] && SPRITES[rol][estadoAgente];
  const fotograma = _fotogramaDe(frames, ahoraMs);
  if (fotograma) dibujar(ctx, fotograma, 0, 0);
}

// ---------------------------------------------------------------------------
// D22 punto 4: "el papel se enciende" -- una ficha cuyo `ultima_lectura`
// está a menos de 3s VIRTUALES del reloj del estado se resalta. A ×4/×16 esa
// ventana dura menos de 1s real y puede no pintarse ni un fotograma entero
// (el reloj virtual de la repetición avanza mucho más rápido que
// `requestAnimationFrame`) -- por eso se trackea, aparte de la condición
// virtual, un reloj de PARED real (`performance.now()`) por cada ficha:
// cuando la condición virtual se cumple por primera vez (o se renueva por
// una lectura más reciente), se apunta `performance.now()`; mientras no
// hayan pasado 500ms reales desde ese instante, sigue "encendida" aunque la
// condición virtual ya no se cumpla. Mismo mecanismo exacto para las
// puertas (`_estaEncendidaPuerta`, más abajo) -- deliberadamente la misma
// función con dos mapas distintos, no dos implementaciones.
// ---------------------------------------------------------------------------

const VENTANA_VIRTUAL_MS = 3000;
const GRACIA_REAL_MS = 500;

function _estaEncendida(mapa, clave, marca, ahoraMs) {
  const virtualCierto =
    !!marca && (() => {
      const edad = ahoraMs - Date.parse(marca);
      return edad >= 0 && edad < VENTANA_VIRTUAL_MS;
    })();
  const previo = mapa.get(clave);
  if (virtualCierto) {
    if (!previo || previo.marca !== marca) {
      mapa.set(clave, { marca, inicioReal: performance.now() });
    }
    return true;
  }
  if (previo) {
    if (performance.now() - previo.inicioReal < GRACIA_REAL_MS) return true;
    mapa.delete(clave);
  }
  return false;
}

const _encendidosPapel = new Map(); // ruta -> {marca, inicioReal}
const _encendidosPuerta = new Map(); // key-puerta -> {marca, inicioReal}

function _listaFichas(ulEl, items, ahoraMs) {
  ulEl.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "ficha";
    boton.textContent = item.ruta;
    if (_estaEncendida(_encendidosPapel, item.ruta, item.ultima_lectura, ahoraMs)) {
      boton.classList.add("ficha--encendida");
    }
    if (item.leido_por && item.leido_por.length > 0) {
      boton.title = `leído por: ${item.leido_por.map(nombreCorto).join(", ")}`;
    }
    boton.onclick = () => _abrirFicheroEnPanel(item.ruta);
    li.appendChild(boton);
    ulEl.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// D22 punto 5: panel "Ahora" -- agentes activos (leyendo/escribiendo) y sus
// lecturas. Tope de 3; criterio para elegir cuáles (documentado, como pide
// el encargo): el orden de inserción de `estado.agentes`, que es el orden
// real de lanzamiento del run (cada rol se crea en `run_inicio` o `lanzado`
// en ese mismo orden) -- no hay "más antiguo"/"más reciente" más
// significativo que ese para un POC que quiere enseñar el AVANCE del flujo.
// ---------------------------------------------------------------------------

function _actualizarAhora(estado) {
  const ul = document.getElementById("lista-ahora");
  if (!ul) return;
  const activos = Object.entries(estado.agentes || {}).filter(
    ([, a]) => a.estado === "leyendo" || a.estado === "escribiendo",
  );
  const TOPE = 3;
  ul.innerHTML = "";
  for (const [instancia, a] of activos.slice(0, TOPE)) {
    const li = document.createElement("li");
    const lecturas = a.lecturas && a.lecturas.length > 0 ? a.lecturas.join(", ") : "—";
    li.textContent = `${nombreCorto(instancia)}: ${lecturas}`;
    ul.appendChild(li);
  }
  if (activos.length > TOPE) {
    const li = document.createElement("li");
    li.className = "ahora-resto";
    li.textContent = `+${activos.length - TOPE}`;
    ul.appendChild(li);
  }
  if (activos.length === 0) {
    const li = document.createElement("li");
    li.className = "ahora-vacio";
    li.textContent = "—";
    ul.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// D22 punto 6: bitácora -- LA MISMA de la Tarea 14 (panel HTML, VT323, líneas
// completas sin recortar, scroll, más recientes arriba), solo reubicada.
// ---------------------------------------------------------------------------

function _actualizarBitacora(estado) {
  const lista = document.getElementById("lista-bitacora");
  if (!lista) return;
  const lineas = estado.bitacora || [];
  lista.innerHTML = "";
  for (let i = lineas.length - 1; i >= 0; i--) {
    const li = document.createElement("li");
    li.textContent = lineas[i];
    lista.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// D22 punto 7: puertas del guardia.
// ---------------------------------------------------------------------------

// Los otros cinco roles que la puerta "los demás" suma (todos salvo
// redactor/novato, que tienen su propia puerta, y verificador, que tiene la
// suya aparte -- por saltos, no por denegados).
const ROLES_OTROS = ["cartografo", "despiezador", "lector-de-pieza", "trazador", "verificador"];

function _construirPuertas(cont) {
  if (!cont) return;
  cont.innerHTML = "";
  const specs = [
    { key: "redactor", titulo: "Redactor" },
    { key: "novato", titulo: "Novato" },
    { key: "los-demas", titulo: "Los demás" },
    { key: "verificador", titulo: "Verificador" },
  ];
  for (const { key, titulo } of specs) {
    const div = document.createElement("div");
    div.className = "puerta";
    div.id = `puerta-${key}`;
    if (key === "verificador") div.classList.add("puerta--discontinua");
    div.innerHTML =
      `<div class="puerta-titulo">${titulo}</div>` +
      `<div class="puerta-regla"></div>` +
      `<div class="puerta-estado"></div>`;
    cont.appendChild(div);
  }
}

function _pintarPuerta(key, n, ultimo, ahoraMs, descripcion, esVerificador) {
  const div = document.getElementById(`puerta-${key}`);
  if (!div) return;
  const regla = div.querySelector(".puerta-regla");
  const estadoEl = div.querySelector(".puerta-estado");
  if (regla) regla.textContent = descripcion;

  const encendida = !!ultimo && _estaEncendida(_encendidosPuerta, key, ultimo.t, ahoraMs);
  div.classList.toggle("puerta--roja", encendida && !esVerificador);
  div.classList.toggle("puerta--ambar", encendida && esVerificador);

  // Retoque Tarea 16 (3): encendida o no, el contador "n=" se ve siempre --
  // antes, al encenderse, el texto del último denegado lo sustituía entero.
  if (estadoEl) {
    estadoEl.textContent = encendida ? `n=${n} · ${ultimo.texto} — ${ultimo.motivo}` : `n=${n}`;
  }
}

function _actualizarPuertas(estado, ahoraMs) {
  const p = estado.puertas || {};

  _pintarPuerta("redactor", p.redactor ? p.redactor.n : 0, p.redactor ? p.redactor.ultimo : null, ahoraMs, "sin repo", false);
  _pintarPuerta(
    "novato",
    p.novato ? p.novato.n : 0,
    p.novato ? p.novato.ultimo : null,
    ahoraMs,
    "solo articulo.md y dudas.md",
    false,
  );

  // "Los demás": suma de los otros cinco roles y el denegado más reciente
  // entre ellos (comparando `t`, string ISO -- comparación lexicográfica
  // basta, mismo formato siempre).
  let n = 0;
  let ultimo = null;
  for (const rol of ROLES_OTROS) {
    const puerta = p[rol];
    if (!puerta) continue;
    n += puerta.n;
    if (puerta.ultimo && (!ultimo || puerta.ultimo.t > ultimo.t)) ultimo = puerta.ultimo;
  }
  _pintarPuerta(
    "los-demas",
    n,
    ultimo,
    ahoraMs,
    "solo repo y salida; sin Bash; eventos y vueltas, solo lectura",
    false,
  );

  // Verificador: NO son denegados del muro, son `saltos` -- la norma del
  // prompt (D22/§5.5: "el guardia le deja leer toda la salida, lo impone el
  // prompt"). Se adapta al mismo formato {texto, motivo, t} que usa
  // `_pintarPuerta` para no duplicar su lógica de encendido/contador.
  const saltos = estado.saltos || [];
  const ultimoSalto = saltos.length > 0 ? saltos[saltos.length - 1] : null;
  const ultimoComoDenegado = ultimoSalto
    ? {
        texto: `Read ${ultimoSalto.ruta}`,
        motivo: "el verificador solo debería leer articulo.md (norma del prompt, no del muro)",
        t: ultimoSalto.t,
      }
    : null;
  _pintarPuerta(
    "verificador",
    saltos.length,
    ultimoComoDenegado,
    ahoraMs,
    "sin fichas, mapa ni flujos · lo pide el prompt",
    true,
  );
}

// ---------------------------------------------------------------------------
// D22 punto 1: flechas SVG entre tarjetas, recalculadas a partir de la
// posición REAL de cada una (`getBoundingClientRect`), nunca con píxeles
// fijos. La TOPOLOGÍA (qué tarjeta conecta con cuál, por qué lado) es fija
// en código -- la rejilla de 4 columnas del plan es un layout fijo, no
// arbitrario -- pero las COORDENADAS siempre se leen del DOM en el momento
// de dibujar, así que un cambio de tamaño de ventana (o de alto de la
// tarjeta de lectores al crecer con más filas) se refleja solo.
// ---------------------------------------------------------------------------

function _geometriaCartas() {
  const mesa = document.getElementById("mesa");
  if (!mesa) return null;
  const rMesa = mesa.getBoundingClientRect();
  const rel = (rol) => {
    const el = _cartas[rol];
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const x = r.left - rMesa.left;
    const y = r.top - rMesa.top;
    return { x, y, w: r.width, h: r.height, cx: x + r.width / 2, cy: y + r.height / 2, right: x + r.width, bottom: y + r.height };
  };
  return {
    mesa: { w: rMesa.width, h: rMesa.height },
    cart: rel("cartografo"),
    desp: rel("despiezador"),
    lect: rel("lector-de-pieza"),
    traz: rel("trazador"),
    red: rel("redactor"),
    ver: rel("verificador"),
    nov: rel("novato"),
  };
}

function _marcadores() {
  return (
    `<defs>` +
    `<marker id="punta-ida" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">` +
    `<path d="M0,0 L8,4 L0,8 Z" fill="#7a8aa0" /></marker>` +
    `<marker id="punta-vuelta" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">` +
    `<path d="M0,0 L8,4 L0,8 Z" fill="#f2d06b" /></marker>` +
    `</defs>`
  );
}

function _lineaRecta(x1, y1, x2, y2, tipo) {
  const clase = tipo === "vuelta" ? "flecha-vuelta" : "flecha-ida";
  const marca = tipo === "vuelta" ? "punta-vuelta" : "punta-ida";
  return `<path d="M${x1},${y1} L${x2},${y2}" class="${clase}" marker-end="url(#${marca})" />`;
}

function _lineaElbow(x1, y1, x2, y2, midX, tipo) {
  const clase = tipo === "vuelta" ? "flecha-vuelta" : "flecha-ida";
  const marca = tipo === "vuelta" ? "punta-vuelta" : "punta-ida";
  return `<path d="M${x1},${y1} L${midX},${y1} L${midX},${y2} L${x2},${y2}" class="${clase}" marker-end="url(#${marca})" />`;
}

// "vuelta n/max" -- un solo sitio decide cómo se lee una vuelta; lo usan
// tanto la etiqueta de la flecha (abajo) como la cabecera
// (`_actualizarCabecera`).
function _etiquetaVuelta(estado) {
  const vuelta = estado.vuelta > 0 ? String(estado.vuelta) : "—";
  const maxV = typeof estado.max_vueltas === "number" ? String(estado.max_vueltas) : "?";
  return `vuelta ${vuelta}/${maxV}`;
}

function _recalcularFlechas(estado) {
  const svg = document.getElementById("flechas");
  if (!svg) return;

  // D22 punto 9: por debajo de ~900px las tarjetas se apilan en una columna
  // por CSS (media query en index.html) y las flechas de una rejilla de 4
  // columnas no significan nada sobre ese layout -- se ocultan por CSS
  // (`.flechas{display:none}`) y aquí simplemente no se recalculan, para no
  // gastar ciclos en geometría que no se va a ver. Decisión documentada
  // (encargo, punto 9): no se intenta "doblar" las mismas flechas sobre un
  // layout de una columna.
  if (window.matchMedia("(max-width: 900px)").matches) return;

  const g = _geometriaCartas();
  if (!g || !g.cart || !g.desp || !g.lect || !g.traz || !g.red || !g.ver || !g.nov) return;

  svg.setAttribute("width", g.mesa.w);
  svg.setAttribute("height", g.mesa.h);
  svg.setAttribute("viewBox", `0 0 ${g.mesa.w} ${g.mesa.h}`);

  const etiquetaVuelta = _etiquetaVuelta(estado);

  const midLectTraz = (g.lect.right + g.traz.x) / 2;

  // Retoque Tarea 16 (1): la "y" de despiezador->lectores tiene que caer
  // DENTRO de la tarjeta de lectores -- el centro de despiezador acotado a
  // [lect.y+20, lect.bottom-20] (con margen de 20px por cada lado, salvo que
  // la tarjeta sea tan baja que no quepan los dos); si hay que acotar, la
  // línea deja de ser recta y pasa a tener codo (mismo patrón que
  // lectores->trazador, más abajo).
  const altoLect = g.lect.bottom - g.lect.y;
  const yDespLect =
    altoLect > 40 ? Math.min(Math.max(g.desp.cy, g.lect.y + 20), g.lect.bottom - 20) : g.lect.cy;
  const despLectRecta = Math.abs(yDespLect - g.desp.cy) < 0.5;
  const midDespLect = (g.desp.right + g.lect.x) / 2;

  // Retoque Tarea 16 (2): CSS (`index.html`, `.mesa`) abre una columna
  // espaciadora entre la 3 (trazador/redactor) y la 4 (verificador/novato)
  // para que la etiqueta "vuelta n/max" y los cuatro codos de ida/vuelta
  // quepan sin pisar ninguna tarjeta -- el ancho real de ese hueco se mide
  // aquí (nunca un número fijo, D22 punto 1), y los cuatro codos se reparten
  // dentro de él como fracciones de ese ancho, cada uno a una "x" distinta
  // para que no se dibujen exactamente encima.
  const huecoIzq = g.red.right;
  const anchoHueco = g.ver.x - huecoIzq;
  const xIdaVer = huecoIzq + anchoHueco * 0.25;
  const xIdaNov = huecoIzq + anchoHueco * 0.4;
  const xVueltaVer = huecoIzq + anchoHueco * 0.6;
  const xVueltaNov = huecoIzq + anchoHueco * 0.75;
  // Igual que antes, offsets de ALTURA distintos sobre el borde derecho de
  // "redactor" para que la salida hacia verificador, la salida hacia
  // novato, la entrada de la vuelta de verificador y la de la vuelta de
  // novato no se solapen entre sí.
  const yIdaVer = g.red.y + g.red.h * 0.25;
  const yVueltaVer = g.red.y + g.red.h * 0.1;
  const yIdaNov = g.red.y + g.red.h * 0.75;
  const yVueltaNov = g.red.y + g.red.h * 0.9;

  const partes = [_marcadores()];
  // cartógrafo -> despiezador -> lectores -> trazador -> redactor (flujo
  // principal, D22 punto 1: "sin flecha cartógrafo->lectores", por eso no
  // hay ninguna línea directa entre esos dos).
  partes.push(_lineaRecta(g.cart.cx, g.cart.bottom, g.desp.cx, g.desp.y, "ida"));
  if (despLectRecta) {
    partes.push(_lineaRecta(g.desp.right, g.desp.cy, g.lect.x, yDespLect, "ida"));
  } else {
    partes.push(_lineaElbow(g.desp.right, g.desp.cy, g.lect.x, yDespLect, midDespLect, "ida"));
  }
  partes.push(_lineaElbow(g.lect.right, g.lect.cy, g.traz.x, g.traz.cy, midLectTraz, "ida"));
  partes.push(_lineaRecta(g.traz.cx, g.traz.bottom, g.red.cx, g.red.y, "ida"));
  // redactor -> verificador y redactor -> novato: las dos con codo (retoque
  // Tarea 16 (2) -- "nada de diagonales", novato incluido).
  partes.push(_lineaElbow(g.red.right, yIdaVer, g.ver.x, g.ver.cy, xIdaVer, "ida"));
  partes.push(_lineaElbow(g.red.right, yIdaNov, g.nov.x, g.nov.cy, xIdaNov, "ida"));
  // La vuelta de los dos al redactor, rotulada "vuelta n/max".
  partes.push(_lineaElbow(g.ver.x, g.ver.cy, g.red.right, yVueltaVer, xVueltaVer, "vuelta"));
  partes.push(_lineaElbow(g.nov.x, g.nov.cy, g.red.right, yVueltaNov, xVueltaNov, "vuelta"));

  const xEtiqueta = huecoIzq + anchoHueco * 0.5;
  const yEtiqueta = (yVueltaVer + yVueltaNov) / 2;
  partes.push(
    `<text x="${xEtiqueta}" y="${yEtiqueta}" class="etiqueta-vuelta" text-anchor="middle">${etiquetaVuelta}</text>`,
  );

  svg.innerHTML = partes.join("");
}

// ---------------------------------------------------------------------------
// Cabecera HTML (run, vuelta, coste, reloj, motivo) — sin cambios respecto a
// escena.js.
// ---------------------------------------------------------------------------

function _construirCabecera(cabecera) {
  // D22 (retoque Tarea 16 (4)): "vuelta" ya forma parte del propio texto que
  // pone `_etiquetaVuelta` ("vuelta n/max") -- sin rótulo fijo delante, para
  // no duplicar la palabra.
  //
  // "Volver" (pedido tras la Tarea 16): un enlace a la portada (lista de
  // runs + formulario de lanzar), oculto por defecto -- `arrancar` lo
  // enseña solo cuando hay `?run=` en la URL (ver más abajo), nunca en la
  // propia portada, donde no pintaría nada.
  cabecera.innerHTML =
    '<a id="c-volver" class="campo volver" href="?" hidden>&larr; volver</a>' +
    '<span class="campo">run <strong id="c-run">—</strong></span>' +
    '<span class="campo"><strong id="c-vuelta">vuelta —/?</strong></span>' +
    '<span class="campo">coste <strong id="c-coste">—</strong></span>' +
    '<span class="campo">reloj <strong id="c-reloj">—</strong></span>' +
    '<span class="campo">motivo <strong id="c-motivo">—</strong></span>';
  return {
    volver: cabecera.querySelector("#c-volver"),
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
  // Retoque Tarea 16 (4): "vuelta n/max" ("vuelta —/2" antes de la primera).
  _cab.vuelta.textContent = _etiquetaVuelta(_estado);
  _cab.coste.textContent = typeof _estado.coste === "number" ? `$${_estado.coste.toFixed(4)}` : "—";
  _cab.reloj.textContent = _estado.t ? _estado.t.substring(11, 19) : "—";
  _cab.motivo.textContent = motivoForzado || _estado.motivo || "—";
}

// ---------------------------------------------------------------------------
// Lista de runs (sin ?run= en la URL) -- sin cambios respecto a escena.js.
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
// Formulario de lanzar (D21, Tarea 15) -- sin cambios respecto a escena.js.
// ---------------------------------------------------------------------------

async function _instalarFormularioLanzar(form) {
  if (!form) return;
  const btn = document.getElementById("btn-lanzar");
  const error = document.getElementById("error-lanzar");
  if (error) error.textContent = "";

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
    // Un fallo aquí no debe bloquear el formulario entero.
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
        return;
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
// -- sin cambios de mecánica respecto a escena.js, solo cambia qué se llama
// para repintar (`_render` en vez de `pintar`+`_actualizarPaneles`).
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
          return null;
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

  function _kDesdeVirtual(tv) {
    let k = 0;
    while (k < vTimes.length && vTimes[k] <= tv) k++;
    return k;
  }

  function _aplicarHasta(k) {
    _estado = eventos.slice(0, k).reduce(aplicar, inicial());
    _actualizarCabecera();
    // Misma razón que en escena.js (T11): `ahoraMs` tiene que estar en la
    // base REAL de los timestamps `t` (no la comprimida de `vTimes`), para
    // que la edad de bocadillo/papel/puerta (`Date.parse(t)` real) no salga
    // negativa tras un hueco comprimido.
    const ahoraMs = k > 0 ? Date.parse(eventos[k - 1].t) : t0;
    _render(_estado, ahoraMs);
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
      ultimoFrame = null;
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

  _aplicarHasta(0);
  rafId = requestAnimationFrame(_frame);

  window.__enjambre_debug = { eventos, vTimes, detener: () => rafId && cancelAnimationFrame(rafId) };
}

// ---------------------------------------------------------------------------
// Modo directo (T12, D21) -- sin cambios de mecánica respecto a escena.js.
// ---------------------------------------------------------------------------

function _arrancarDirecto(repo, run) {
  const controles = document.getElementById("controles");
  if (controles) controles.hidden = true;

  const aviso = document.getElementById("aviso-directo");
  const ocultarAviso = () => {
    if (aviso) aviso.hidden = true;
  };
  const mostrarAviso = (texto) => {
    if (!aviso) return;
    aviso.textContent = texto;
    aviso.hidden = false;
  };

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
      } catch (err) {
        mostrarAviso(`no se pudo contactar con el servidor: ${err}`);
        btnParar.disabled = false;
      }
    };
  }

  _estado = inicial();
  _estado.run = run;
  _actualizarCabecera("EN DIRECTO");
  _render(_estado, Date.now());
  ocultarAviso();

  let terminado = false;
  const url = `/api/directo/${encodeURIComponent(repo)}/${encodeURIComponent(run)}`;
  const es = new EventSource(url);

  es.onmessage = (ev) => {
    let evento;
    try {
      evento = JSON.parse(ev.data);
    } catch {
      return;
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
      _actualizarCabecera("EN DIRECTO");
      ocultarAviso();
    }
  };

  es.onerror = () => {
    if (terminado) return;
    mostrarAviso("conexión perdida, reintentando…");
    _estado = inicial();
    _estado.run = run;
    _actualizarCabecera("conexión perdida, reintentando…");
    _render(_estado, Date.now());
  };
}

// ---------------------------------------------------------------------------
// Panel lateral: ver el contenido de un fichero de la salida -- sin cambios
// respecto a escena.js.
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
