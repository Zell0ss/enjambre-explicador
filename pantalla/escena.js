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

// Elementos de cabecera, rellenados una vez en `arrancar`.
let _cab = null;

export function arrancar(lienzo, cabecera) {
  _ctx = lienzo.getContext("2d");
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

// Paleta provisional por estado (T11 la sustituye por fotogramas de sprite;
// aquí solo gobierna el color de fondo del rectángulo de cada agente).
const COLOR_ESTADO = {
  esperando: "#5a6b7a",
  leyendo: "#2f7fb8",
  escribiendo: "#d98c27",
  bloqueado: "#c23b3b",
  terminado: "#3f9c56",
};
const COLOR_ESTADO_DEFECTO = "#888888";

// Color de texto por rol, para el bocadillo (§5.3: "cada personaje tiene un
// color de texto"). `lector-de-pieza` cubre cualquier instancia de ese rol.
const COLOR_ROL = {
  cartografo: "#f2d06b",
  despiezador: "#e8835a",
  "lector-de-pieza": "#8fd0e8",
  trazador: "#a9e88f",
  redactor: "#d6a9e8",
  verificador: "#e8e08f",
  novato: "#ff9ecb",
};
const COLOR_ROL_DEFECTO = "#ffffff";

// Posiciones fijas en cubierta (§5.3) para los roles únicos; coordenadas del
// rectángulo 20×20 en la escena (320×144). Provisional: T11 puede ajustarlas
// al tamaño real del sprite.
const POSICION_ROL = {
  cartografo: { x: 20, y: 18 },
  despiezador: { x: 20, y: 54 },
  novato: { x: 20, y: 100 },
  trazador: { x: 272, y: 18 },
  redactor: { x: 272, y: 54 },
  verificador: { x: 272, y: 100 },
};

// Fila de lectores (hasta 8, tope del despiezador; si llegan más se apilan
// sin rediseñar — §5.3).
const LECTORES_FILA_Y = 70;
const LECTORES_FILA_X0 = 90;
const LECTORES_FILA_PASO = 22;

function _posicionAgente(rol, indiceLector) {
  if (rol === "lector-de-pieza") {
    const i = indiceLector % 8;
    const pila = Math.floor(indiceLector / 8); // apilar si hay más de 8
    return { x: LECTORES_FILA_X0 + i * LECTORES_FILA_PASO, y: LECTORES_FILA_Y + pila * 10 };
  }
  return POSICION_ROL[rol] || { x: 150, y: 70 };
}

/**
 * pintar(ctx2d, estado, ahoraMs) — render provisional con rectángulos de
 * color. Pura en el sentido de que solo lee `estado`/`ahoraMs` y escribe en
 * `ctx2d` (y en las cachés de zonas de módulo, para hit-test de
 * click/hover); no hace fetch ni toca `location`.
 */
export function pintar(ctx2d, estado, ahoraMs) {
  _zonasAgentes = [];
  _zonasInventario = [];

  // Fondo liso de la escena y de la barra, bien diferenciados (de noche /
  // madera de la barra SCUMM) -- el arte real es la Tarea 11.
  ctx2d.fillStyle = "#101826";
  ctx2d.fillRect(0, 0, ANCHO, ALTO_ESCENA);
  ctx2d.fillStyle = "#3a2a1e";
  ctx2d.fillRect(0, ALTO_ESCENA, ANCHO, ALTO_BARRA);

  ctx2d.textBaseline = "top";
  ctx2d.font = "8px monospace";

  // Agentes: orden de inserción de `estado.agentes` ya es estable (claves
  // string), así que basta un contador para numerar a los lectores en fila.
  let indiceLector = 0;
  for (const [instancia, agente] of Object.entries(estado.agentes || {})) {
    const rol = agente.rol;
    const indice = rol === "lector-de-pieza" ? indiceLector++ : 0;
    const pos = _posicionAgente(rol, indice);
    const w = 18;
    const h = 20;

    ctx2d.fillStyle = COLOR_ESTADO[agente.estado] || COLOR_ESTADO_DEFECTO;
    ctx2d.fillRect(pos.x, pos.y, w, h);
    ctx2d.strokeStyle = "#000000";
    ctx2d.strokeRect(pos.x + 0.5, pos.y + 0.5, w - 1, h - 1);

    _zonasAgentes.push({ x: pos.x, y: pos.y, w, h, instancia, agente });

    // Bocadillo: se borra a los ~3s de `bocadillo.t` (§5.3).
    if (agente.bocadillo && agente.bocadillo.t) {
      const edadMs = ahoraMs - Date.parse(agente.bocadillo.t);
      if (edadMs >= 0 && edadMs < 3000) {
        ctx2d.fillStyle = COLOR_ROL[rol] || COLOR_ROL_DEFECTO;
        _dibujarTextoRecortado(ctx2d, agente.bocadillo.texto, pos.x - 10, pos.y - 9, 48);
      }
    }
  }

  // El loro: vuela al agente denegado y grazna, visible ~3s (misma regla que
  // los bocadillos, usando el mismo campo `t`).
  if (estado.loro && estado.loro.t) {
    const edadMs = ahoraMs - Date.parse(estado.loro.t);
    if (edadMs >= 0 && edadMs < 3000) {
      const zona = _zonasAgentes.find((z) => z.instancia === estado.loro.agente);
      const px = zona ? zona.x + zona.w + 2 : 4;
      const py = zona ? zona.y - 10 : 4;
      ctx2d.fillStyle = "#39b54a";
      ctx2d.fillRect(px, py, 6, 6);
      ctx2d.fillStyle = "#ffffff";
      _dibujarTextoRecortado(ctx2d, "¡Prohibido!", px - 20, py - 9, 60);
    }
  }

  // Barra inferior: bitácora (últimas 5 líneas) a la izquierda...
  ctx2d.fillStyle = "#e8e0c8";
  ctx2d.font = "7px monospace";
  const lineas = (estado.bitacora || []).slice(-5);
  lineas.forEach((linea, i) => {
    _dibujarTextoRecortado(ctx2d, linea, 4, ALTO_ESCENA + 4 + i * 10, 220);
  });

  // ...e inventario (un icono por fichero) a la derecha.
  const inventario = estado.inventario || [];
  const colInicioX = 230;
  const iconoLado = 16;
  const porFila = Math.max(1, Math.floor((ANCHO - colInicioX - 4) / (iconoLado + 2)));
  inventario.forEach((item, i) => {
    const fila = Math.floor(i / porFila);
    const col = i % porFila;
    const x = colInicioX + col * (iconoLado + 2);
    const y = ALTO_ESCENA + 4 + fila * (iconoLado + 2);
    ctx2d.fillStyle = "#c8a24a";
    ctx2d.fillRect(x, y, iconoLado, iconoLado);
    ctx2d.strokeStyle = "#000000";
    ctx2d.strokeRect(x + 0.5, y + 0.5, iconoLado - 1, iconoLado - 1);
    _zonasInventario.push({ x, y, w: iconoLado, h: iconoLado, item });
  });
}

function _dibujarTextoRecortado(ctx2d, texto, x, y, anchoMax) {
  if (!texto) return;
  // Recorte tosco por caracteres (no hay medida real de fuente de bitmap
  // todavía): suficiente para el render provisional de T10.
  const maxChars = Math.max(1, Math.floor(anchoMax / 4));
  const recortado = texto.length > maxChars ? texto.slice(0, maxChars - 1) + "…" : texto;
  ctx2d.fillText(recortado, x, y);
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
    pintar(_ctx, _estado, t0 + tVirtual);
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
