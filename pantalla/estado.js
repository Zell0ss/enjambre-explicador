export const ROLES = ["cartografo", "despiezador", "lector-de-pieza", "trazador", "redactor", "verificador", "novato"];

export function inicial() {
  return {
    run: null,
    motivo: null,
    vuelta: 0,
    // D22: tope de vueltas del propio run (run_inicio.params.max_vueltas),
    // para poder rotular "vuelta n/max" en la vista.
    max_vueltas: null,
    coste: 0,
    t: null,
    agentes: {},
    inventario: [],
    bitacora: [],
    loro: null,
    repo: null,
    salida: null,
    // D22: puertas del guardia, una por ROL (no por instancia -- los
    // lectores comparten "lector-de-pieza"). Preinicializadas a n=0 para
    // los siete roles desde el principio, no creadas al vuelo en el primer
    // `denegado`, para que una puerta sin denegar siga existiendo con n=0.
    puertas: Object.fromEntries(ROLES.map((rol) => [rol, { n: 0, ultimo: null }])),
    // D22: lecturas del verificador en la salida que no son articulo.md --
    // es una norma del PROMPT (el guardia le deja leer toda la salida), no
    // del muro, así que se cuenta aparte de `puertas`.
    saltos: [],
  };
}

// Quita el prefijo repo/salida (tal cual vino en run_inicio) de una ruta
// absoluta para mostrarla corta en un bocadillo. Solo para presentación: no
// resuelve symlinks ni normaliza, es comparación de string literal. Si la
// ruta no empieza por ninguno de los dos (ya es relativa, o es un patrón de
// Glob) se devuelve tal cual.
//
// D22/D23: si la ruta ES exactamente la raíz del repo o de la salida (un
// Glob sobre "." entero, p.ej.), no hay nada detrás del prefijo que cortar
// -- se devuelve el literal "(repo)"/"(salida)" en vez de la cadena vacía.
function _relativiza(ruta, repo, salida) {
  if (typeof ruta !== "string") return ruta;
  if (typeof salida === "string" && salida.length > 0 && ruta === salida) return "(salida)";
  if (typeof repo === "string" && repo.length > 0 && ruta === repo) return "(repo)";
  for (const prefijo of [salida, repo]) {
    if (typeof prefijo === "string" && prefijo.length > 0 && ruta.startsWith(`${prefijo}/`)) {
      return ruta.slice(prefijo.length + 1);
    }
  }
  return ruta;
}

// D23: texto de bocadillo/puerta para un evento `herramienta`/`denegado`.
// Si hay `patron` (Glob/Grep) y no coincide con `detalle` (p.ej. un Glob
// con `path` explícito: detalle=carpeta, patron=patrón de verdad),
// "<herramienta> <patron> en <detalle relativizado>"; si no, el formato de
// siempre, "<herramienta> <detalle relativizado>" (cubre tanto las tools
// sin patrón como un Glob/Grep sin `path`, donde `detalle` ya es el propio
// patrón -- lanzador.py los iguala ahí, D23 no cambia esa regla).
function _textoHerramienta(herramienta, detalle, patron, repo, salida) {
  const detalleRel = _relativiza(detalle || "", repo, salida);
  if (patron && patron !== detalle) {
    return `${herramienta} ${patron} en ${detalleRel}`.trim();
  }
  return `${herramienta} ${detalleRel}`.trim();
}

export function aplicar(estado, evento) {
  // Never mutate the input: use structuredClone to create a deep copy
  const s = structuredClone(estado);

  // All events update t
  s.t = evento.t;

  // Add a line to bitacora with format "hh:mm:ss agente texto"
  const addBitacora = (text) => {
    if (evento.t) {
      const time = evento.t.substring(11, 19); // Extract hh:mm:ss from ISO string
      // D20: nombre corto (sin el prefijo "lector-de-pieza:") -- es el mismo
      // identificador que escena.js pinta bajo cada personaje, así que la
      // bitácora y la escena hablan del mismo "nombre" en vez de uno completo
      // y otro recortado.
      const agente = evento.agente ? nombreCorto(evento.agente) : "";
      // Eventos sin agente (run_inicio, vuelta, run_fin) dejarían un hueco
      // doble entre la hora y el texto si no se colapsa.
      const line = `${time} ${agente} ${text}`.replace(/ {2,}/g, " ").trim();
      s.bitacora.push(line);
      // Keep only last 50 lines
      if (s.bitacora.length > 50) {
        s.bitacora = s.bitacora.slice(-50);
      }
    }
  };

  switch (evento.tipo) {
    case "run_inicio": {
      s.run = evento.run;
      s.bitacora = [];
      s.agentes = {};
      s.inventario = [];
      s.loro = null;
      s.coste = 0;
      s.vuelta = 0;
      s.motivo = null;
      s.repo = evento.repo || null;
      s.salida = evento.salida || null;
      // D22: todos se reinician en run_inicio, como el resto del estado.
      s.max_vueltas =
        evento.params && typeof evento.params.max_vueltas === "number" ? evento.params.max_vueltas : null;
      s.puertas = Object.fromEntries(ROLES.map((rol) => [rol, { n: 0, ultimo: null }]));
      s.saltos = [];
      // Create instances for all ROLES except lector-de-pieza
      for (const rol of ROLES) {
        if (rol !== "lector-de-pieza") {
          s.agentes[rol] = {
            rol,
            estado: "esperando",
            bocadillo: null,
            modelo_pedido: null,
            modelo_real: null,
            duracion_s: null,
            coste_usd: null,
            lecturas: [],
          };
        }
      }
      addBitacora(`run iniciado`);
      break;
    }

    case "lanzado": {
      const instancia = evento.agente;
      const rol = getRol(instancia);
      s.agentes[instancia] = {
        rol,
        estado: "esperando",
        bocadillo: null,
        modelo_pedido: evento.modelo_pedido || null,
        modelo_real: null,
        duracion_s: null,
        coste_usd: null,
        lecturas: [],
      };
      addBitacora(`lanzado ${instancia}`);
      break;
    }

    case "estado": {
      if (s.agentes[evento.agente]) {
        s.agentes[evento.agente].estado = evento.estado;
        if (evento.detalle) {
          s.agentes[evento.agente].bocadillo = {
            texto: _relativiza(evento.detalle, s.repo, s.salida),
            t: evento.t,
          };
        }
      }
      addBitacora(`estado: ${evento.estado}`);
      break;
    }

    case "herramienta": {
      if (s.agentes[evento.agente]) {
        s.agentes[evento.agente].bocadillo = {
          texto: _textoHerramienta(evento.herramienta, evento.detalle, evento.patron, s.repo, s.salida),
          t: evento.t,
        };
      }

      if (evento.herramienta === "Read" && typeof evento.detalle === "string") {
        const rel = _relativiza(evento.detalle, s.repo, s.salida);

        // D22: lecturas recientes del agente -- la más reciente primero,
        // sin repetir (una relectura la mueve al frente en vez de
        // duplicarla), tope de 8.
        if (s.agentes[evento.agente]) {
          const previas = s.agentes[evento.agente].lecturas.filter((r) => r !== rel);
          s.agentes[evento.agente].lecturas = [rel, ...previas].slice(0, 8);
        }

        // D22: si la ruta ya está en el inventario, el papel "recuerda"
        // quién lo ha leído y cuándo fue la última vez -- si no está (una
        // lectura del repo, o de algo que esta vista no sigue), se ignora
        // sin error.
        const papel = s.inventario.find((i) => i.ruta === rel);
        if (papel) {
          papel.ultima_lectura = evento.t;
          if (!papel.leido_por.includes(evento.agente)) {
            papel.leido_por.push(evento.agente);
          }
        }

        // D22: el verificador solo debería leer articulo.md de la
        // salida -- es una norma del PROMPT (el guardia le deja leer toda
        // la salida, D2/guardia.py), así que una lectura de otra cosa en
        // la salida es un "salto" de esa norma, no un `denegado` del muro.
        const enSalida =
          typeof s.salida === "string" && s.salida.length > 0 && evento.detalle.startsWith(`${s.salida}/`);
        if (evento.agente === "verificador" && enSalida && rel !== "articulo.md") {
          s.saltos.push({ agente: evento.agente, ruta: rel, t: evento.t });
        }
      }

      addBitacora(`herramienta: ${evento.herramienta}`);
      break;
    }

    case "denegado": {
      s.loro = {
        agente: evento.agente,
        motivo: evento.motivo || "",
        t: evento.t,
      };

      // D22: puertas del guardia -- por ROL (getRol), no por instancia:
      // los hasta 8 lectores comparten un único contador bajo
      // "lector-de-pieza". Preinicializadas en inicial()/run_inicio para
      // los siete roles, así que siempre debería existir; el `if` es
      // defensivo (mismo criterio que el resto del reductor: nunca
      // reventar por un rol inesperado).
      const rolPuerta = getRol(evento.agente);
      if (s.puertas[rolPuerta]) {
        s.puertas[rolPuerta].n += 1;
        s.puertas[rolPuerta].ultimo = {
          instancia: evento.agente,
          texto: _textoHerramienta(evento.herramienta, evento.detalle, evento.patron, s.repo, s.salida),
          motivo: evento.motivo || "",
          t: evento.t,
        };
      }

      addBitacora(`denegado: ${evento.herramienta}`);
      break;
    }

    case "fichero": {
      // Add to inventario if not already present (no duplicates by ruta)
      if (!s.inventario.find(i => i.ruta === evento.ruta)) {
        s.inventario.push({
          ruta: evento.ruta,
          agente: evento.agente,
          t: evento.t,
          // D22: "el papel leído recuerda quién lo leyó" -- se rellenan
          // cuando llegue un `herramienta: Read` sobre esta misma ruta
          // (ver el caso "herramienta" de arriba), vacíos hasta entonces.
          leido_por: [],
          ultima_lectura: null,
        });
      }
      addBitacora(`fichero: ${evento.ruta}`);
      break;
    }

    case "fin_agente": {
      if (s.agentes[evento.agente]) {
        s.agentes[evento.agente].modelo_real = evento.modelo_real || null;
        s.agentes[evento.agente].duracion_s = evento.duracion_s || null;
        s.agentes[evento.agente].coste_usd = evento.coste_usd || null;
        // Add to total coste
        if (typeof evento.coste_usd === "number") {
          s.coste += evento.coste_usd;
        }
      }
      // No repetir el agente (addBitacora ya lo antepone): mostrar algo útil
      // en su lugar -- estado final, duración y coste del propio evento.
      const estadoFinal = evento.estado_final ?? "desconocido";
      const duracion = typeof evento.duracion_s === "number" ? evento.duracion_s.toFixed(1) : "?";
      const coste = typeof evento.coste_usd === "number" ? evento.coste_usd.toFixed(4) : "?";
      addBitacora(`fin: ${estadoFinal} ${duracion}s $${coste}`);
      break;
    }

    case "vuelta": {
      s.vuelta = evento.n;
      addBitacora(`vuelta ${evento.n}`);
      break;
    }

    case "run_fin": {
      s.motivo = evento.motivo || null;
      addBitacora(`run terminado: ${evento.motivo}`);
      break;
    }

    case "respuesta": {
      addBitacora(`respuesta: ${evento.texto}`);
      break;
    }

    case "aviso": {
      addBitacora(`aviso: ${evento.texto}`);
      break;
    }

    default:
      // Tipo desconocido: la regla de compatibilidad del plan exige que
      // SOLO se actualice `t` (ya hecho arriba) -- no tocar bitacora ni
      // nada más, para que un tipo de evento futuro no reviente ni
      // contamine la vista con una línea sin sentido.
      break;
  }

  return s;
}

// Helper: extract role from instance name (part before ':')
function getRol(instancia) {
  const colonIndex = instancia.indexOf(":");
  if (colonIndex !== -1) {
    return instancia.substring(0, colonIndex);
  }
  return instancia;
}

// nombreCorto(instancia) -- D20 punto 3/6: el identificador legible de un
// agente, para el nombre bajo su personaje y para la bitácora.
// "lector-de-pieza:llm" -> "llm" (la parte tras ":", el id de la pieza);
// "verificador" (sin ":") -> "verificador" tal cual, porque ahí el rol ES el
// nombre. Lo inverso de `getRol`: esa toma lo de ANTES de ":", esta lo de
// DESPUÉS (o todo, si no hay ":").
export function nombreCorto(instancia) {
  if (typeof instancia !== "string") return instancia;
  const colonIndex = instancia.indexOf(":");
  return colonIndex === -1 ? instancia : instancia.slice(colonIndex + 1);
}
