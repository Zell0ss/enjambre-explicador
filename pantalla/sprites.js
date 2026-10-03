// sprites.js — arte pixel de la pantalla (Tarea 11, D14).
//
// Formato de fotograma (plan, Tarea 11): un fotograma es un array de
// strings, una fila de píxeles por string, un carácter por píxel:
//   "."  -> índice 0 de PALETA (transparente)
//   "0"  -> también índice 0 (alias de ".", tolerado)
//   "1".."9" -> índices 1-9 de PALETA
//   "a".."v" -> índices 10-31 de PALETA
// (el comentario del plan dice `"." = 0, "0"-"9","a"-"v" = índice`; aquí se
// interpreta "0" como alias de "." porque, si no, índice 0 tendría dos
// dueños a la vez y el hueco "0" sobraría. Documentado por si hace falta
// revisarlo.)
//
// Los sprites de personajes y del fondo NO están tecleados a mano como
// matrices literales: se generan con pequeñas funciones constructoras
// (`_grid`, `_rect`, `_px`, `_linea`...) a partir de una config por rol.
// Razón: 7 roles × 5 estados × 2 fotogramas = 70 fotogramas de 24×32; a
// mano habría sido enorme y proclive a errores de tecleo. El resultado
// exportado sigue siendo el formato plano que pide el contrato (arrays de
// strings): la generación es un detalle interno de este módulo.
//
// La fuente de texto (§B del encargo) sí está tecleada a mano, glifo a
// glifo: es la parte que de verdad hay que poder leer letra a letra.

// ---------------------------------------------------------------------------
// Paleta: hasta 32 colores, índice 0 = transparente (representado por
// `null` aquí; los caracteres "." y "0" apuntan a él).
// ---------------------------------------------------------------------------

export const PALETA = [
  /* 0  */ null,
  /* 1  */ "#0a0e1a", // casi negro: contornos, sombra
  /* 2  */ "#121a2e", // cielo noche, banda más oscura
  /* 3  */ "#1b2744",
  /* 4  */ "#24345c", // también pantalón/tela oscura
  /* 5  */ "#2f4a7a",
  /* 6  */ "#3f6aa8",
  /* 7  */ "#5e8fc9",
  /* 8  */ "#7fb0e0", // brillo de luna
  /* 9  */ "#4a2f6b", // morado sombra, horizonte nocturno
  /* a  */ "#6b3f91",
  /* b  */ "#9a5fc0",
  /* c  */ "#c9a0e8",
  /* d  */ "#e8c84a", // amarillo farol, cálido
  /* e  */ "#f2e08a", // brillo farol / luna
  /* f  */ "#c47a2e", // madera/farol naranja
  /* g  */ "#8a5a2e", // madera media (tablas de cubierta)
  /* h  */ "#5e3d1f", // madera oscura (muebles, barriles)
  /* i  */ "#e8d8b8", // piel clara
  /* j  */ "#c9a87a", // piel media
  /* k  */ "#8a6a4a", // pelo/piel oscura
  /* l  */ "#3a2a1e", // cuero/pelo muy oscuro
  /* m  */ "#e8e8e8", // blanco: ojos, papel, gorro de cocinero
  /* n  */ "#c23b3b", // rojo: aviso, "!", pico del loro
  /* o  */ "#3f9c56", // verde: loro, acento "terminado"
  /* p  */ "#2f7fb8", // azul estado "leyendo" (reservado para acentos)
  /* q  */ "#d98c27", // naranja estado "escribiendo"
  /* r  */ "#5a6b7a", // gris estado "esperando" / Zzz
  /* s  */ "#8fd0e8", // cian lector-de-pieza
  /* t  */ "#ff9ecb", // rosa novato
  /* u  */ "#d6a9e8", // lila redactor
  /* v  */ "#f2d06b", // dorado cartógrafo / estrellas
];

function _indiceDesdeCaracter(ch) {
  if (ch === "." || ch === "0") return 0;
  if (ch >= "1" && ch <= "9") return ch.charCodeAt(0) - "0".charCodeAt(0);
  if (ch >= "a" && ch <= "v") return 10 + (ch.charCodeAt(0) - "a".charCodeAt(0));
  return 0; // carácter desconocido: transparente, nunca lanza (degradación)
}

/**
 * dibujar(ctx2d, fotograma, x, y, espejo = false) — pinta un fotograma a
 * razón de un fillRect de 1×1 por carácter no transparente. El pixel=1
 * encaja con el lienzo lógico 320×200 de escena.js: el zoom real lo da el
 * escalado CSS entero (image-rendering: pixelated), no este fillRect.
 */
export function dibujar(ctx2d, fotograma, x, y, espejo = false) {
  if (!fotograma) return;
  if (!Array.isArray(fotograma)) {
    // No es una matriz de paleta, es un PNG real ya cargado (ver
    // `cargarSpritesPersonajes` más abajo, D14: "sustituibles por PNG").
    // `ctx2d.imageSmoothingEnabled = false` ya está puesto una vez en
    // `arrancar` (escena.js); drawImage respeta eso igual que el fillRect
    // de abajo respeta el escalado CSS entero.
    if (espejo) {
      ctx2d.save();
      ctx2d.translate(x + fotograma.naturalWidth, y);
      ctx2d.scale(-1, 1);
      ctx2d.drawImage(fotograma, 0, 0);
      ctx2d.restore();
    } else {
      ctx2d.drawImage(fotograma, x, y);
    }
    return;
  }
  for (let fila = 0; fila < fotograma.length; fila++) {
    const cadena = fotograma[fila];
    const ancho = cadena.length;
    for (let col = 0; col < ancho; col++) {
      const idx = _indiceDesdeCaracter(cadena[col]);
      if (idx === 0) continue;
      const color = PALETA[idx];
      if (!color) continue;
      ctx2d.fillStyle = color;
      const cx = espejo ? x + (ancho - 1 - col) : x + col;
      ctx2d.fillRect(cx, y + fila, 1, 1);
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers de rejilla para construir fotogramas por código (personajes y
// fondo). `_toFrame` es lo único que cruza la frontera hacia el formato
// plano del contrato.
// ---------------------------------------------------------------------------

function _grid(ancho, alto) {
  return Array.from({ length: alto }, () => Array(ancho).fill("."));
}

function _toFrame(g) {
  return g.map((fila) => fila.join(""));
}

function _rect(g, x, y, w, h, ch) {
  const alto = g.length;
  const ancho = g[0] ? g[0].length : 0;
  for (let fy = y; fy < y + h; fy++) {
    if (fy < 0 || fy >= alto) continue;
    for (let fx = x; fx < x + w; fx++) {
      if (fx < 0 || fx >= ancho) continue;
      g[fy][fx] = ch;
    }
  }
}

function _px(g, x, y, ch) {
  if (y >= 0 && y < g.length && g[y] && x >= 0 && x < g[y].length) g[y][x] = ch;
}

// Bresenham simple, para accesorios diagonales (catalejo, pluma, cuchillo).
function _linea(g, x0, y0, x1, y1, ch) {
  let x = x0;
  let y = y0;
  const dx = Math.abs(x1 - x0);
  const sx = x0 < x1 ? 1 : -1;
  const dy = -Math.abs(y1 - y0);
  const sy = y0 < y1 ? 1 : -1;
  let err = dx + dy;
  for (;;) {
    _px(g, x, y, ch);
    if (x === x1 && y === y1) break;
    const e2 = 2 * err;
    if (e2 >= dy) {
      err += dy;
      x += sx;
    }
    if (e2 <= dx) {
      err += dx;
      y += sy;
    }
  }
}

function _puntosCirculo(r) {
  const pts = [];
  for (let dy = -r; dy <= r; dy++) {
    for (let dx = -r; dx <= r; dx++) {
      if (dx * dx + dy * dy <= r * r) pts.push([dx, dy]);
    }
  }
  return pts;
}

// ---------------------------------------------------------------------------
// Personajes: unos 24×32 (§5.3). Pose + accesorio + marca de estado
// (Zzz, libro, herramienta del rol, "!") construyen la silueta; el color de
// la túnica distingue el rol incluso a tamaño reducido.
// ---------------------------------------------------------------------------

export const ANCHO_PERSONAJE = 24;
export const ALTO_PERSONAJE = 32;
const SW = ANCHO_PERSONAJE;
const SH = ALTO_PERSONAJE;

function _figuraBase({ piel, pelo, tunica, pantalon, pose, ojosAbiertos, fase, extra }) {
  const g = _grid(SW, SH);

  _rect(g, 7, 2, 10, 2, pelo); // pelo/gorro (visible como fleco si la cabeza lo tapa)
  _rect(g, 8, 3, 8, 7, piel); // cabeza
  if (ojosAbiertos) {
    _px(g, 10, 7, "1");
    _px(g, 13, 7, "1");
  }

  if (pose === "sentado") {
    // "terminado": figura más baja y ancha (sentado en un banco), sin
    // piernas visibles -- silueta deliberadamente distinta del resto.
    _rect(g, 6, 11, 12, 10, tunica);
    _rect(g, 4, 20, 16, 4, pantalon); // banco/cadera
    _rect(g, 3, 15, 3, 6, piel); // brazos relajados
    _rect(g, 18, 15, 3, 6, piel);
  } else {
    _rect(g, 6, 11, 12, 11, tunica);
    _rect(g, 7, 22, 4, 8, pantalon);
    _rect(g, 13, 22, 4, 8, pantalon);
    if (pose === "alzado") {
      // un brazo arriba cerca de la cabeza, sosteniendo la herramienta del rol
      _rect(g, 3, 6 - fase, 3, 7, piel);
      _rect(g, 18, 13, 3, 7, piel);
    } else if (pose === "ambos") {
      // "bloqueado": los dos brazos arriba, pose de alarma
      _rect(g, 3, 6, 3, 7, piel);
      _rect(g, 18, 6, 3, 7, piel);
    } else if (pose === "libro") {
      // "leyendo": brazos adelantados sosteniendo un libro común a todos los roles
      _rect(g, 5, 14, 4, 5, piel);
      _rect(g, 15, 14, 4, 5, piel);
    } else {
      // "abajo": brazos caídos ("esperando")
      _rect(g, 3, 13, 3, 7, piel);
      _rect(g, 18, 13, 3, 7, piel);
    }
  }

  if (extra) extra(g);
  return g;
}

function _zzz(g, fase) {
  const dy = fase ? 1 : 0;
  _px(g, 19, 6 - dy, "r");
  _px(g, 20, 5 - dy, "r");
  _px(g, 21, 4 - dy, "r");
}

function _exclamacion(g) {
  _rect(g, 11, 0, 2, 2, "n");
  _px(g, 11, 2, "n");
  _px(g, 12, 2, "n");
}

function _libro(g) {
  _rect(g, 7, 15, 10, 4, "m");
  _px(g, 7, 15, "1");
  _px(g, 16, 15, "1");
  _rect(g, 11, 15, 1, 4, "1"); // lomo
}

// Herramienta característica de cada rol (§5.3), dibujada en la mano
// adelantada durante "escribiendo". `dy` da el pequeño vaivén entre los dos
// fotogramas de animación.
function _accesorio(g, tipo, color, fase) {
  const dy = fase ? 1 : 0;
  switch (tipo) {
    case "catalejo": // cartógrafo
      _linea(g, 0, 12 - dy, 5, 6 - dy, color);
      break;
    case "cuchillo": // despiezador
      _rect(g, 1, 9 - dy, 1, 4, color);
      _linea(g, 2, 9 - dy, 5, 6 - dy, color);
      break;
    case "vela": // lector-de-pieza
      _rect(g, 2, 6 - dy, 1, 6, "f");
      _px(g, 2, 5 - dy, "e");
      break;
    case "compas": // trazador
      _px(g, 1, 7 - dy, color);
      _px(g, 0, 8 - dy, color);
      _px(g, 2, 8 - dy, color);
      _px(g, 1, 9 - dy, color);
      break;
    case "pluma": // redactor
      _linea(g, 0, 11 - dy, 4, 6 - dy, color);
      _px(g, 4, 5 - dy, color);
      break;
    case "lupa": // verificador
      _px(g, 1, 7 - dy, color);
      _px(g, 2, 6 - dy, color);
      _px(g, 3, 7 - dy, color);
      _px(g, 2, 8 - dy, color);
      _px(g, 3, 9 - dy, color);
      _px(g, 4, 10 - dy, color);
      break;
    default:
      break; // novato: grumete, manos vacías
  }
}

const CONFIG_ROL = {
  cartografo: { tunica: "v", pelo: "m", pantalon: "l", accesorio: "catalejo", accColor: "v" },
  despiezador: { tunica: "f", pelo: "m", pantalon: "l", accesorio: "cuchillo", accColor: "m", gorro: true },
  "lector-de-pieza": { tunica: "s", pelo: "l", pantalon: "4", accesorio: "vela", accColor: "d" },
  trazador: { tunica: "o", pelo: "l", pantalon: "4", accesorio: "compas", accColor: "e" },
  redactor: { tunica: "u", pelo: "k", pantalon: "l", accesorio: "pluma", accColor: "m" },
  verificador: { tunica: "e", pelo: "k", pantalon: "4", accesorio: "lupa", accColor: "s" },
  novato: { tunica: "t", pelo: "k", pantalon: "4", accesorio: "ninguno", accColor: "m" },
};

const PIEL = "i";

function _construirEstadosRol(cfg) {
  const base = { piel: PIEL, pelo: cfg.pelo, tunica: cfg.tunica, pantalon: cfg.pantalon };
  const gorroFn = cfg.gorro ? (g) => _rect(g, 7, 1, 10, 2, "m") : null;

  function compon(extraFns) {
    return (g) => {
      if (gorroFn) gorroFn(g);
      for (const fn of extraFns) fn(g);
    };
  }

  const fotograma = (pose, ojosAbiertos, extraFns) =>
    _toFrame(_figuraBase({ ...base, pose, ojosAbiertos, fase: 0, extra: compon(extraFns) }));
  const fotogramaFase = (pose, ojosAbiertos, extraFns, fase) =>
    _toFrame(_figuraBase({ ...base, pose, ojosAbiertos, fase, extra: compon(extraFns) }));

  return {
    esperando: [
      fotogramaFase("abajo", false, [(g) => _zzz(g, 0)], 0),
      fotogramaFase("abajo", false, [(g) => _zzz(g, 1)], 0),
    ],
    leyendo: [fotograma("libro", true, [_libro]), fotograma("libro", true, [_libro])],
    escribiendo: [
      fotogramaFase("alzado", true, [(g) => _accesorio(g, cfg.accesorio, cfg.accColor, 0)], 0),
      fotogramaFase("alzado", true, [(g) => _accesorio(g, cfg.accesorio, cfg.accColor, 1)], 1),
    ],
    bloqueado: [fotograma("ambos", true, [_exclamacion]), fotograma("ambos", true, [])],
    terminado: [fotograma("sentado", false, []), fotograma("sentado", false, [])],
  };
}

export const SPRITES = Object.fromEntries(
  Object.entries(CONFIG_ROL).map(([rol, cfg]) => [rol, _construirEstadosRol(cfg)]),
);

// ---------------------------------------------------------------------------
// Sustitución por PNG real (D14: "sprites dibujados en código... sustituibles
// por PNG"; Josem trajo el arte en pantalla/sprites/<rol>/<estado>_<0|1>.png,
// mismo contrato exacto -- 7 roles, 5 estados, 2 fotogramas, 24×32 -- que ya
// usa `SPRITES` arriba, confirmado contra su propio manifest.json).
//
// Sustituye cada fotograma EN SITIO, uno a uno según va cargando: `SPRITES`
// sigue siendo el mismo objeto (no se reasigna la constante), así que
// escena.js no necesita saber que esto existe -- sigue leyendo
// `SPRITES[rol][estado]` como siempre. Si un PNG concreto no carga (404,
// red), ese hueco se queda con el fotograma procedural que ya había desde
// la construcción de arriba: degradación silenciosa, nunca una pantalla
// rota ni una promesa rechazada por un solo fallo (igual que el resto del
// proyecto: ver `_resuelve_dentro`/`isinstance` en pantalla.py).
// ---------------------------------------------------------------------------

const ESTADOS_PERSONAJE = ["esperando", "leyendo", "escribiendo", "bloqueado", "terminado"];

function _cargarImagen(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`no se pudo cargar ${url}`));
    img.src = url;
  });
}

/**
 * cargarSpritesPersonajes(baseUrl) — lanza la carga de los 70 PNG y
 * sustituye cada fotograma de `SPRITES` por el que vaya llegando. Devuelve
 * una promesa que se resuelve cuando se ha INTENTADO cargar los 70 (éxito o
 * fallo individual); nunca se rechaza entera por un solo PNG que falte.
 */
export function cargarSpritesPersonajes(baseUrl = "/static/sprites/") {
  const tareas = [];
  for (const rol of Object.keys(SPRITES)) {
    for (const estado of ESTADOS_PERSONAJE) {
      const frames = SPRITES[rol][estado];
      if (!frames) continue;
      frames.forEach((_fotogramaProcedural, i) => {
        const url = `${baseUrl}${rol}/${estado}_${i}.png`;
        tareas.push(
          _cargarImagen(url)
            .then((img) => {
              frames[i] = img;
            })
            .catch(() => {}), // se queda el fotograma procedural ya puesto
        );
      });
    }
  }
  return Promise.all(tareas);
}

// ---------------------------------------------------------------------------
// Fondo: cubierta de un barco de noche (§5.3). `cielo` + `cubierta` suman
// 144 px de alto (= ALTO_ESCENA de escena.js); el resto de piezas son
// elementos sueltos que escena.js posiciona por su cuenta.
// ---------------------------------------------------------------------------

const ANCHO_ESCENA = 320;
const ALTO_CIELO = 72;
const ALTO_CUBIERTA = 72;

function _construirCielo() {
  const g = _grid(ANCHO_ESCENA, ALTO_CIELO);
  const bandas = ["2", "3", "4", "5", "6", "9", "a"];
  for (let y = 0; y < ALTO_CIELO; y++) {
    const banda = bandas[Math.floor((y / ALTO_CIELO) * bandas.length)];
    for (let x = 0; x < ANCHO_ESCENA; x++) g[y][x] = banda;
  }
  // Estrellas: patrón determinista (sin Math.random) para que el fotograma
  // sea estable entre cargas -- no hay animación de estrellas, solo de
  // farolillos.
  for (let y = 0; y < ALTO_CIELO - 10; y++) {
    for (let x = 0; x < ANCHO_ESCENA; x++) {
      if ((x * 37 + y * 17) % 97 === 0) g[y][x] = "m";
      else if ((x * 53 + y * 29) % 131 === 0) g[y][x] = "c";
    }
  }
  // Luna
  const lx = 262;
  const ly = 16;
  for (const [dx, dy] of _puntosCirculo(6)) _px(g, lx + dx, ly + dy, "e");
  return [_toFrame(g)];
}

function _construirCubierta() {
  const g = _grid(ANCHO_ESCENA, ALTO_CUBIERTA);
  for (let y = 0; y < ALTO_CUBIERTA; y++) {
    const base = y % 4 === 0 ? "h" : "g";
    for (let x = 0; x < ANCHO_ESCENA; x++) g[y][x] = base;
  }
  for (let x = 0; x < ANCHO_ESCENA; x += 24) {
    for (let y = 0; y < ALTO_CUBIERTA; y++) g[y][x] = "1";
  }
  return [_toFrame(g)];
}

function _construirMastil() {
  const g = _grid(18, 110);
  _rect(g, 8, 0, 2, 110, "1"); // palo
  _rect(g, 2, 6, 14, 8, "h"); // cofa
  _rect(g, 4, 4, 10, 2, "l"); // borde de la cofa
  _px(g, 9, 0, "n"); // banderín
  _px(g, 10, 1, "n");
  return [_toFrame(g)];
}

function _construirTimon() {
  const g = _grid(20, 20);
  for (const [dx, dy] of _puntosCirculo(9)) {
    const d2 = dx * dx + dy * dy;
    if (d2 <= 81 && d2 >= 49) _px(g, 10 + dx, 10 + dy, "h");
  }
  _px(g, 10, 10, "1");
  for (const ang of [0, 60, 120, 180, 240, 300]) {
    const rad = (ang * Math.PI) / 180;
    _linea(g, 10, 10, 10 + Math.round(9 * Math.cos(rad)), 10 + Math.round(9 * Math.sin(rad)), "g");
  }
  return [_toFrame(g)];
}

function _construirBarriles() {
  const g = _grid(22, 16);
  for (const cx of [5, 15]) {
    _rect(g, cx - 4, 4, 8, 11, "g");
    _rect(g, cx - 4, 4, 8, 1, "h");
    _rect(g, cx - 4, 7, 8, 1, "h");
    _rect(g, cx - 4, 13, 8, 1, "h");
  }
  return [_toFrame(g)];
}

function _construirCocina() {
  const g = _grid(26, 18);
  _rect(g, 2, 8, 22, 8, "h"); // tajo
  _rect(g, 4, 2, 6, 6, "l"); // fogón/olla
  _px(g, 6, 1, "q");
  _px(g, 7, 0, "d");
  return [_toFrame(g)];
}

function _construirMesaLarga() {
  const g = _grid(150, 14);
  _rect(g, 0, 4, 150, 6, "h");
  _rect(g, 0, 4, 150, 1, "g");
  for (let x = 6; x < 150; x += 18) _rect(g, x, 10, 2, 4, "l");
  return [_toFrame(g)];
}

function _construirEscritorio() {
  const g = _grid(26, 16);
  _rect(g, 2, 6, 22, 8, "h");
  _rect(g, 4, 3, 8, 4, "m");
  _px(g, 5, 4, "1");
  return [_toFrame(g)];
}

function _construirMesaMapa() {
  const g = _grid(26, 16);
  _rect(g, 2, 7, 22, 7, "h");
  _rect(g, 5, 3, 16, 6, "e");
  _rect(g, 5, 3, 16, 1, "1");
  _px(g, 10, 6, "o");
  _px(g, 15, 5, "n");
  return [_toFrame(g)];
}

function _construirFarolillo() {
  const marco = () => {
    const g = _grid(7, 11);
    _px(g, 3, 0, "1");
    _rect(g, 2, 1, 3, 1, "1");
    return g;
  };
  const f1 = marco();
  _rect(f1, 1, 2, 5, 6, "f");
  _rect(f1, 2, 3, 3, 4, "d");
  const f2 = marco();
  _rect(f2, 1, 2, 5, 6, "f");
  _rect(f2, 2, 3, 3, 4, "e");
  _px(f2, 1, 3, "d");
  _px(f2, 5, 3, "d");
  return [_toFrame(f1), _toFrame(f2)];
}

export const FONDO = {
  cielo: _construirCielo(),
  cubierta: _construirCubierta(),
  mastil: _construirMastil(),
  timon: _construirTimon(),
  barriles: _construirBarriles(),
  cocina: _construirCocina(),
  mesaLarga: _construirMesaLarga(),
  escritorio: _construirEscritorio(),
  mesaMapa: _construirMesaMapa(),
  farolillo: _construirFarolillo(),
};

// ---------------------------------------------------------------------------
// Loro guardián: vuela al agente denegado y grazna (D-el guardia del §5.3
// "tabla de roles").
// ---------------------------------------------------------------------------

function _construirLoroVolando() {
  const marco = (alasArriba) => {
    const g = _grid(14, 10);
    _rect(g, 5, 3, 5, 3, "o");
    _px(g, 10, 4, "n");
    _rect(g, 3, 2, 2, 2, "o");
    if (alasArriba) {
      _linea(g, 5, 3, 1, 0, "o");
      _linea(g, 9, 3, 13, 0, "o");
    } else {
      _linea(g, 5, 5, 1, 8, "o");
      _linea(g, 9, 5, 13, 8, "o");
    }
    return _toFrame(g);
  };
  return [marco(true), marco(false)];
}

function _construirLoroPosado() {
  const g = _grid(12, 10);
  _rect(g, 4, 3, 5, 4, "o");
  _px(g, 9, 4, "n");
  _rect(g, 3, 2, 2, 2, "o");
  _rect(g, 5, 7, 1, 2, "h"); // patas/percha
  return [_toFrame(g)];
}

export const LORO = {
  volando: _construirLoroVolando(),
  posado: _construirLoroPosado(),
};

// ---------------------------------------------------------------------------
// Color de texto por rol (bocadillos). Mismos valores que usaba
// `COLOR_ROL` en la Tarea 10 de escena.js -- se centralizan aquí para no
// mantener la misma paleta en dos sitios (pedido del encargo).
// ---------------------------------------------------------------------------

export const COLOR_TEXTO = {
  cartografo: "#f2d06b",
  despiezador: "#e8835a",
  "lector-de-pieza": "#8fd0e8",
  trazador: "#a9e88f",
  redactor: "#d6a9e8",
  verificador: "#e8e08f",
  novato: "#ff9ecb",
};

// ---------------------------------------------------------------------------
// Fuente de mapa de bits: 5 píxeles de ancho × 7 de alto. "#" = encendido,
// "." = apagado -- es un esquema binario propio, no índices de PALETA:
// dibujarTexto() recibe el color ya resuelto (p.ej. COLOR_TEXTO[rol]) y
// pinta con él directamente, para poder usar cualquier color sin tener que
// duplicar cada glifo por color.
//
// No hay fila reservada aparte para los acentos: las vocales con tilde y
// la Ñ/ñ se derivan de la letra base sustituyendo su fila 0 (la mayoría ya
// la tienen en blanco) por la marca de acento/tilde -- ver _conAcento* más
// abajo. Es una aproximación tipográfica, no un acento geométricamente
// exacto, pero mantiene la letra reconocible sin añadir un segundo juego
// de glifos.
// ---------------------------------------------------------------------------

export const ANCHO_GLIFO = 5;
export const ALTO_GLIFO = 7;

const FUENTE_BASE = {
  " ": [".....", ".....", ".....", ".....", ".....", ".....", "....."],
  ".": [".....", ".....", ".....", ".....", ".....", ".##..", ".##.."],
  ",": [".....", ".....", ".....", ".....", ".....", ".##..", ".#..."],
  ":": [".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."],
  "/": ["....#", "...#.", "...#.", "..#..", ".#...", ".#...", "#...."],
  "-": [".....", ".....", ".....", "#####", ".....", ".....", "....."],
  $: ["..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."],
  "(": ["...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."],
  ")": [".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."],
  "!": ["..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."],
  "¡": ["..#..", ".....", "..#..", "..#..", "..#..", "..#..", "..#.."],
  "?": [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."],
  "¿": ["..#..", ".....", "..#..", ".#...", "#....", "#...#", ".###."],
  0: [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
  1: ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", "#####"],
  2: [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
  3: [".###.", "#...#", "....#", "..##.", "....#", "#...#", ".###."],
  4: ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
  5: ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
  6: ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
  7: ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
  8: [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
  9: [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
  A: [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
  B: ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
  C: [".####", "#....", "#....", "#....", "#....", "#....", ".####"],
  D: ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
  E: ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
  F: ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
  G: [".####", "#....", "#....", "#.###", "#...#", "#...#", ".####"],
  H: ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
  I: ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
  J: ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
  K: ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
  L: ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
  M: ["#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"],
  N: ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
  O: [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  P: ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
  Q: [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
  R: ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
  S: [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
  T: ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
  U: ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  V: ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
  W: ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
  X: ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
  Y: ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
  Z: ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
  a: [".....", ".....", ".###.", "....#", ".####", "#...#", ".####"],
  b: ["#....", "#....", "#.##.", "##..#", "#...#", "#...#", "####."],
  c: [".....", ".....", ".####", "#....", "#....", "#....", ".####"],
  d: ["....#", "....#", ".##.#", "#..##", "#...#", "#...#", ".####"],
  e: [".....", ".....", ".###.", "#...#", "#####", "#....", ".###."],
  f: ["..##.", ".#..#", ".#...", "###..", ".#...", ".#...", ".#..."],
  g: [".....", ".####", "#...#", "#...#", ".####", "....#", ".###."],
  h: ["#....", "#....", "#.##.", "##..#", "#...#", "#...#", "#...#"],
  i: ["..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###."],
  j: ["...#.", ".....", "..##.", "...#.", "...#.", "#..#.", ".##.."],
  k: ["#....", "#....", "#..#.", "#.#..", "##...", "#.#..", "#..#."],
  l: [".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
  m: [".....", ".....", "##.#.", "#.#.#", "#.#.#", "#...#", "#...#"],
  n: [".....", ".....", "#.##.", "##..#", "#...#", "#...#", "#...#"],
  o: [".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###."],
  p: [".....", ".####", "#...#", "#...#", "####.", "#....", "#...."],
  q: [".....", ".####", "#...#", "#...#", ".####", "....#", "....#"],
  r: [".....", ".....", "#.##.", "##..#", "#....", "#....", "#...."],
  s: [".....", ".....", ".####", "#....", ".###.", "....#", "####."],
  t: ["..#..", "..#..", "#####", "..#..", "..#..", "..#..", "...##"],
  u: [".....", ".....", "#...#", "#...#", "#...#", "#...#", ".####"],
  v: [".....", ".....", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
  w: [".....", ".....", "#...#", "#...#", "#.#.#", "#.#.#", ".#.#."],
  x: [".....", ".....", "#...#", ".#.#.", "..#..", ".#.#.", "#...#"],
  y: [".....", ".....", "#...#", "#...#", ".####", "....#", ".###."],
  z: [".....", ".....", "#####", "...#.", "..#..", ".#...", "#####"],
};

function _conAcento(glifo) {
  // Mayúscula acentuada: añade una marca en la esquina sup. derecha de la
  // fila 0 (aproximación, no un acento geométrico exacto -- ver comentario
  // de cabecera).
  const copia = glifo.slice();
  const fila = copia[0].split("");
  fila[4] = "#";
  copia[0] = fila.join("");
  return copia;
}

function _conAcentoMin(glifo) {
  // Minúscula acentuada: la fila 0 está libre en todas las vocales
  // (incluida "i", donde sustituye al punto -- tipográficamente razonable).
  const copia = glifo.slice();
  copia[0] = "...#.";
  return copia;
}

function _conTilde(glifo) {
  const copia = glifo.slice();
  copia[0] = ".#.#.";
  return copia;
}

const FUENTE = {
  ...FUENTE_BASE,
  Á: _conAcento(FUENTE_BASE.A),
  É: _conAcento(FUENTE_BASE.E),
  Í: _conAcento(FUENTE_BASE.I),
  Ó: _conAcento(FUENTE_BASE.O),
  Ú: _conAcento(FUENTE_BASE.U),
  á: _conAcentoMin(FUENTE_BASE.a),
  é: _conAcentoMin(FUENTE_BASE.e),
  í: _conAcentoMin(FUENTE_BASE.i),
  ó: _conAcentoMin(FUENTE_BASE.o),
  ú: _conAcentoMin(FUENTE_BASE.u),
  Ñ: _conTilde(FUENTE_BASE.N),
  ñ: _conTilde(FUENTE_BASE.n),
};

/**
 * dibujarTexto(ctx2d, texto, x, y, color) — pinta `texto` con la fuente de
 * mapa de bits de arriba. Un carácter sin glifo (emoji, acento raro) cae en
 * "?" en vez de lanzar una excepción.
 */
export function dibujarTexto(ctx2d, texto, x, y, color) {
  if (!texto) return;
  ctx2d.fillStyle = color;
  let cx = x;
  for (const ch of String(texto)) {
    const glifo = FUENTE[ch] || FUENTE["?"];
    if (glifo) {
      for (let fila = 0; fila < glifo.length; fila++) {
        const cadena = glifo[fila];
        for (let col = 0; col < cadena.length; col++) {
          if (cadena[col] === "#") ctx2d.fillRect(cx + col, y + fila, 1, 1);
        }
      }
    }
    cx += ANCHO_GLIFO + 1;
  }
}

/** Ancho en píxeles que ocupará `texto` pintado con dibujarTexto(). */
export function medirTexto(texto) {
  return String(texto || "").length * (ANCHO_GLIFO + 1);
}
