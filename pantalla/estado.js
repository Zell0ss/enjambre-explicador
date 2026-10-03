export const ROLES = ["cartografo", "despiezador", "lector-de-pieza", "trazador", "redactor", "verificador", "novato"];

export function inicial() {
  return {
    run: null,
    motivo: null,
    vuelta: 0,
    coste: 0,
    t: null,
    agentes: {},
    inventario: [],
    bitacora: [],
    loro: null,
    repo: null,
    salida: null,
  };
}

// Quita el prefijo repo/salida (tal cual vino en run_inicio) de una ruta
// absoluta para mostrarla corta en un bocadillo. Solo para presentación: no
// resuelve symlinks ni normaliza, es comparación de string literal. Si la
// ruta no empieza por ninguno de los dos (ya es relativa, o es un patrón de
// Glob) se devuelve tal cual.
function _relativiza(ruta, repo, salida) {
  if (typeof ruta !== "string") return ruta;
  for (const prefijo of [salida, repo]) {
    if (typeof prefijo === "string" && prefijo.length > 0 && ruta.startsWith(`${prefijo}/`)) {
      return ruta.slice(prefijo.length + 1);
    }
  }
  return ruta;
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
      const agente = evento.agente || "";
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
        const detalle = _relativiza(evento.detalle || "", s.repo, s.salida);
        const texto = `${evento.herramienta} ${detalle}`.trim();
        s.agentes[evento.agente].bocadillo = {
          texto,
          t: evento.t,
        };
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
