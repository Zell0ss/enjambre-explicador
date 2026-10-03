import { test } from "node:test";
import assert from "node:assert/strict";
import { inicial, aplicar, ROLES } from "../../pantalla/estado.js";

const ev = (tipo, extra = {}) => ({ t: "2026-10-03T00:00:01.000", run: "r1", tipo, ...extra });
const corre = (...evs) => evs.reduce(aplicar, inicial());

test("run_inicio crea los roles fijos en esperando", () => {
  const s = corre(ev("run_inicio"));
  assert.deepEqual(Object.keys(s.agentes).sort(), ROLES.filter(r => r !== "lector-de-pieza").sort());
  assert.ok(Object.values(s.agentes).every(a => a.estado === "esperando"));
});

test("lanzado de un lector lo crea", () => {
  const s = corre(ev("run_inicio"), ev("lanzado", { agente: "lector-de-pieza:a", rol: "lector-de-pieza", modelo_pedido: "haiku" }));
  assert.equal(s.agentes["lector-de-pieza:a"].rol, "lector-de-pieza");
  assert.equal(s.agentes["lector-de-pieza:a"].modelo_pedido, "haiku");
});

test("estado, bocadillo, fichero, denegado, fin, vuelta y run_fin", () => {
  const s = corre(
    ev("run_inicio"),
    ev("estado", { agente: "novato", estado: "leyendo", detalle: "articulo.md" }),
    ev("denegado", { agente: "novato", herramienta: "Read", detalle: "fichas/x.md", motivo: "solo articulo.md" }),
    ev("fichero", { agente: "novato", ruta: "dudas.md" }),
    ev("fichero", { agente: "novato", ruta: "dudas.md" }),
    ev("fin_agente", { agente: "novato", modelo_real: "claude-haiku-4-5-20251001", duracion_s: 30, coste_usd: 0.02 }),
    ev("vuelta", { n: 2 }),
    ev("run_fin", { motivo: "aprobado" }),
  );
  assert.equal(s.agentes.novato.estado, "leyendo");
  assert.equal(s.agentes.novato.bocadillo.texto, "articulo.md");
  assert.equal(s.loro.agente, "novato");
  assert.deepEqual(s.inventario.map(i => i.ruta), ["dudas.md"]);
  assert.equal(s.agentes.novato.modelo_real, "claude-haiku-4-5-20251001");
  assert.equal(s.coste, 0.02);
  assert.equal(s.vuelta, 2);
  assert.equal(s.motivo, "aprobado");
});

test("aplicar no muta la entrada y tolera tipos desconocidos", () => {
  const a = corre(ev("run_inicio"));
  const copia = JSON.stringify(a);
  const b = aplicar(a, ev("tipo_del_futuro", { agente: "x", raro: 1 }));
  assert.equal(JSON.stringify(a), copia);
  assert.equal(b.t, "2026-10-03T00:00:01.000");
});

test("la bitácora se queda en 50 líneas", () => {
  const evs = [ev("run_inicio"), ...Array.from({ length: 80 }, (_, i) => ev("aviso", { texto: `a${i}` }))];
  assert.equal(corre(...evs).bitacora.length, 50);
});

// --- Prueba añadida tras revisión: la regla de compatibilidad para tipos
// desconocidos es "solo t" -- ni bitácora ni nada más, para que un tipo de
// evento futuro no contamine la vista con una línea sin sentido.
test("tipo desconocido no añade línea a la bitácora", () => {
  const a = corre(ev("run_inicio"));
  const bitacoraAntes = a.bitacora.length;
  const b = aplicar(a, ev("tipo_del_futuro", { agente: "x", raro: 1 }));
  assert.equal(b.bitacora.length, bitacoraAntes);
});
