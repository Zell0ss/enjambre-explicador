// fuente-pixel.js — la fuente de mapa de bits propia que se construyó en la
// Tarea 11 para el lienzo de la pantalla (5×7, "#"/"." por carácter),
// retirada del camino activo el 2026-10-04 a petición de Josem: "VT323 en
// vez de ctx2d.fillText con la fuente de sistema" seguía siendo la regla
// (nunca texto de sistema dentro del `<canvas>`, sale borroso al escalar
// con `image-rendering: pixelated`), pero el tipo "estilo Spectrum" de esta
// fuente propia no encajaba con el resto -- "no funciona" -- así que
// `pantalla/sprites.js` pasó a usar VT323 también dentro del lienzo (ver su
// cabecera para el porqué de esa decisión y sus matices).
//
// Josem, literal: "construiste tu la fuente? no la borres: dejala por ahi
// que la usaremos para algo". Vive aquí, completa y funcional, sin usar
// desde ningún otro módulo del proyecto por ahora -- candidata para lo que
// haga falta más adelante (otro elemento de la UI, un modo retro, etc.).
//
// Formato de glifo: array de 7 strings de 5 caracteres, "#" = píxel
// encendido, "." = apagado. `dibujarTexto`/`medirTexto` tienen la misma
// forma que sus homónimas activas en `sprites.js` (mismo contrato:
// `dibujarTexto(ctx2d, texto, x, y, color)` pinta desde la esquina superior
// izquierda a fillRect de 1×1 por píxel; `medirTexto(texto)` devuelve el
// ancho en píxeles lógicos del lienzo) para que, si algún día se vuelve a
// enchufar, el cambio en el llamador sea mínimo.

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
  // D20 punto 7: la fila 1 dibujaba literalmente la "P" mayúscula (".####",
  // bombo abierto a la izquierda) en vez de cerrar el bombo de la "p" por la
  // izquierda como hacen las filas 4-6 (el tallo descendente, ya correcto).
  // Verificado a mano contra "q" (bombo abierto a ambos lados en las mismas
  // filas, tallo a la derecha): confirma que aquí el bombo debía cerrarse a
  // la izquierda desde la fila 1, no solo desde la 4. Único cambio: esa fila.
  p: [".....", "####.", "#...#", "#...#", "####.", "#....", "#...."],
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
  const copia = glifo.slice();
  const fila = copia[0].split("");
  fila[4] = "#";
  copia[0] = fila.join("");
  return copia;
}

function _conAcentoMin(glifo) {
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
