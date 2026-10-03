"""
El guion del enjambre: orden fijo en código, no un LLM orquestando (D5).

`orquestar` lanza los siete agentes sobre `repo`, escribe `salidas/<repo>/<run>/`
y decide cuándo parar leyendo lo que los propios agentes dejaron en disco
(`Fallos:`/`## Veredicto` vía `enjambre.parsers`) más un tope de coste y de
vueltas (D9) -- nunca un LLM opinando sobre si ya ha terminado.

`lanzar` se recibe por parámetro (contrato `Lanzar`, T5): en pruebas y en
`--falso` es `enjambre.falso.hacer_lanzar_falso()`; con la API real es
`enjambre.lanzador.lanzar`, importado solo dentro de `main()` para que
`import enjambre.orquestar` (lo que hacen las pruebas) nunca cargue
`claude_agent_sdk` (D6).
"""

import argparse
import asyncio
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from enjambre.agentes import ROLES, Agente, cargar
from enjambre.eventos import Eventos
from enjambre.parsers import SalidaIlegible, fallos, ids_de_piezas, veredicto
from enjambre.registro import obtener_log
from enjambre.tipos import Contexto, Lanzar, Resultado


class _ParaRun(Exception):
    """Señala que el run debe terminar con un motivo dado.

    D9: la parada la decide código leyendo ficheros (Fallos/veredicto) y
    comprobando topes, no un LLM. Se usa como mecanismo de control para
    salir de cualquier punto del guion (incluido dentro de un
    `asyncio.gather`) y llegar siempre al mismo `finally`, que es quien
    realmente emite `run_fin`.
    """

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


@dataclass
class _Coste:
    """Acumulador de coste del run; mutable para que `_paso` lo vaya sumando."""
    total: float = 0.0


def _comprueba_tope(coste: _Coste, tope_usd: float) -> None:
    """Para el run si el coste acumulado ya pasó el tope (D9) -- antes de
    lanzar nada. La usa tanto `_paso` (antes de cada agente suelto) como el
    bucle de vueltas (antes de empezar una vuelta: si el tope ya salta aquí,
    ni el evento `vuelta` ni el contador de vueltas deben llegar a existir
    para esa `n`, porque su verificador+novato nunca se intentan)."""
    if coste.total > tope_usd:
        raise _ParaRun("tope_coste")


def _encargo(rol: str, repo: Path, salida: Path, **campos: object) -> str:
    """Construye el encargo (`CLAVE=valor`, una por línea) de un lanzamiento.

    D2: al redactor y al novato no se les pasa `REPO` -- no ven el repo, solo
    lo que otros agentes dejaron en `SALIDA`.
    """
    lineas = []
    if rol not in ("redactor", "novato"):
        lineas.append(f"REPO={repo}")
    lineas.append(f"SALIDA={salida}")
    for clave, valor in campos.items():
        lineas.append(f"{clave}={valor}")
    return "\n".join(lineas) + "\n"


async def _paso(
    ctx: Contexto,
    lanzar: Lanzar,
    coste: _Coste,
    tope_usd: float,
    instancia: str,
    agente: Agente,
    encargo: str,
    timeout_s: float,
) -> Resultado:
    """Un lanzamiento de agente.

    Antes de llamar: si el coste acumulado ya pasó el tope (D9), para sin ni
    siquiera emitir `lanzado` -- el agente en marcha anterior ya terminó, y
    este nunca llega a arrancar.

    `lanzar` (T5) solo emite `estado`/`herramienta`/`denegado`/`fichero`/
    `aviso`; los tres eventos que enmarcan la llamada -- `lanzado`,
    `respuesta`, `fin_agente` -- los emite el guion aquí (D5), para que quien
    narra el run sea el código, no el agente.

    Nunca deja escapar una excepción del `lanzar` inyectado: se traduce en
    un `Resultado(estado_final="error")`, que el guion interpreta más tarde
    como una parada normal (`fallo:<instancia>:error`), no como un fallo del
    propio orquestador. `asyncio.CancelledError` (no es `Exception`) sí se
    deja pasar sin tocar, para que una cancelación real llegue hasta el
    `try/finally` de `orquestar`.
    """
    _comprueba_tope(coste, tope_usd)

    ctx.eventos.emitir(
        "lanzado", instancia, rol=agente.rol, modelo_pedido=agente.modelo, encargo=encargo
    )
    try:
        resultado = await asyncio.wait_for(lanzar(agente, instancia, encargo, ctx), timeout=timeout_s)
    except TimeoutError as e:
        # §6: un fallo de `lanzar` es un evento de AGENTE, no una excepción
        # no prevista del propio orquestador -- va al jsonl (`aviso`), no a
        # LogCentral. Sin esto, "estado_final: timeout" no deja ningún rastro
        # de qué tardó tanto.
        ctx.eventos.emitir("aviso", instancia, texto=f"{type(e).__name__}: {e}")
        resultado = Resultado("timeout")
    except Exception as e:
        # Idem: sin el `aviso`, un error de autenticación/rate-limit/red del
        # SDK real (Tarea 7) se convierte en un "error" opaco, sin tipo ni
        # mensaje, en vez de quedar documentado en el propio jsonl del run.
        ctx.eventos.emitir("aviso", instancia, texto=f"{type(e).__name__}: {e}")
        resultado = Resultado("error")

    coste.total += resultado.coste_usd
    ctx.eventos.emitir("respuesta", instancia, texto=resultado.respuesta)
    ctx.eventos.emitir(
        "fin_agente",
        instancia,
        estado_final=resultado.estado_final,
        modelo_real=resultado.modelo_real,
        duracion_s=resultado.duracion_s,
        tokens_in=resultado.tokens_in,
        tokens_out=resultado.tokens_out,
        coste_usd=resultado.coste_usd,
        num_herramientas=resultado.num_herramientas,
    )
    return resultado


def _exige(salida: Path, ruta_relativa: str) -> None:
    """Para el run si un fichero que el paso anterior debía dejar no está."""
    if not (salida / ruta_relativa).exists():
        raise _ParaRun(f"falta:{ruta_relativa}")


def _exige_terminado(instancia: str, resultado: Resultado) -> None:
    """Para el run si el agente no terminó limpio."""
    if resultado.estado_final != "terminado":
        raise _ParaRun(f"fallo:{instancia}:{resultado.estado_final}")


def _resultado_o_fallo(instancia: str, r) -> Resultado:
    """Normaliza el resultado de una tarea de un `asyncio.gather(return_exceptions=True)`:
    una `_ParaRun` se repropaga tal cual; cualquier otra excepción que se
    hubiera escapado de `_paso` (no debería, pero `gather` es la red de
    seguridad que pide el brief) cuenta como `error`, igual que si `lanzar`
    hubiera lanzado dentro de `_paso`."""
    if isinstance(r, _ParaRun):
        raise r
    if isinstance(r, BaseException):
        raise _ParaRun(f"fallo:{instancia}:error")
    return r


async def orquestar(
    repo: Path,
    salidas: Path,
    lanzar: Lanzar,
    *,
    tope_usd: float = 5.0,
    max_vueltas: int = 2,
    timeout_s: float = 600,
    max_turns: int = 60,
    run: str | None = None,
) -> dict:
    """Lanza el enjambre sobre `repo` y devuelve el evento `run_fin`."""
    run = run or f"{repo.name}-{datetime.now():%Y%m%d-%H%M}"
    salida = salidas / repo.name / run
    if salida.exists():
        raise FileExistsError(f"ya existe una ejecución en {salida}")
    salida.mkdir(parents=True)

    eventos = Eventos(salida / "eventos.jsonl", run)
    inicio = time.monotonic()
    coste = _Coste()
    vueltas_hechas = 0
    motivo = "excepcion:desconocido"  # se sobrescribe siempre en algún except; no debería sobrevivir.

    try:
        agentes = {rol: cargar(rol) for rol in ROLES}
        params = {
            "tope_usd": tope_usd,
            "max_vueltas": max_vueltas,
            "timeout_s": timeout_s,
            "max_turns": max_turns,
        }
        eventos.emitir(
            "run_inicio",
            repo=str(repo),
            salida=str(salida),
            params=params,
            roles={rol: a.modelo for rol, a in agentes.items()},
        )
        for rol in ("cartografo", "despiezador", "trazador", "redactor", "verificador", "novato"):
            eventos.emitir("estado", rol, estado="esperando")

        ctx = Contexto(repo=repo, salida=salida, eventos=eventos, timeout_s=timeout_s, max_turns=max_turns)

        async def lanza(instancia: str, rol: str, **campos) -> Resultado:
            encargo = _encargo(rol, repo, salida, **campos)
            return await _paso(ctx, lanzar, coste, tope_usd, instancia, agentes[rol], encargo, timeout_s)

        # --- cartografo ---------------------------------------------------
        r = await lanza("cartografo", "cartografo")
        _exige_terminado("cartografo", r)
        _exige(salida, "mapa.md")

        # --- despiezador ---------------------------------------------------
        r = await lanza("despiezador", "despiezador")
        _exige_terminado("despiezador", r)
        _exige(salida, "piezas.md")
        try:
            ids = ids_de_piezas((salida / "piezas.md").read_text())
        except SalidaIlegible:
            raise _ParaRun("piezas_ilegibles")

        # --- lectores, en paralelo -----------------------------------------
        instancias = [f"lector-de-pieza:{id_}" for id_ in ids]
        resultados = await asyncio.gather(
            *(lanza(instancia, "lector-de-pieza", PIEZA=id_) for instancia, id_ in zip(instancias, ids)),
            return_exceptions=True,
        )
        for instancia, r in zip(instancias, resultados):
            r = _resultado_o_fallo(instancia, r)
            _exige_terminado(instancia, r)
        for id_ in ids:
            _exige(salida, f"fichas/{id_}.md")

        # --- trazador -------------------------------------------------------
        r = await lanza("trazador", "trazador")
        _exige_terminado("trazador", r)
        _exige(salida, "flujos.md")

        # --- redactor, borrador ----------------------------------------------
        r = await lanza("redactor", "redactor", MODO="borrador")
        _exige_terminado("redactor", r)
        _exige(salida, "articulo.md")

        # --- vueltas de verificación / revisión --------------------------------
        n = 1
        while True:
            # Comprobar el tope de coste ANTES de emitir `vuelta` y de contar
            # esta `n` como una vuelta hecha: si una revisión anterior ya lo
            # agotó, el verificador+novato de esta vuelta nunca se intentan,
            # así que ni el evento `vuelta` ni `vueltas_hechas` deben existir
            # para ella (bug real: sin este chequeo aquí, `_paso` seguía
            # frenando a verificador/novato dentro del `gather` de más abajo,
            # pero `vueltas_hechas = n` ya se había ejecutado para una vuelta
            # que nunca llegó a lanzar nada).
            _comprueba_tope(coste, tope_usd)
            eventos.emitir("vuelta", n=n)
            r_ver, r_nov = await asyncio.gather(
                lanza("verificador", "verificador", VUELTA=n),
                lanza("novato", "novato", VUELTA=n),
                return_exceptions=True,
            )
            vueltas_hechas = n
            r_ver = _resultado_o_fallo("verificador", r_ver)
            _exige_terminado("verificador", r_ver)
            r_nov = _resultado_o_fallo("novato", r_nov)
            _exige_terminado("novato", r_nov)

            # D13: copiar verificacion.md/dudas.md a vueltas/<n>/ antes de que
            # la vuelta siguiente los sobrescriba (en la fase 1 la vuelta 1 se
            # perdió así); copiar los que existan, sin tocar los prompts.
            destino = salida / "vueltas" / str(n)
            destino.mkdir(parents=True, exist_ok=True)
            for nombre in ("verificacion.md", "dudas.md"):
                origen = salida / nombre
                if origen.exists():
                    shutil.copy2(origen, destino / nombre)

            ruta_verificacion = salida / "verificacion.md"
            ruta_dudas = salida / "dudas.md"
            n_fallos = fallos(ruta_verificacion.read_text()) if ruta_verificacion.exists() else None
            v = veredicto(ruta_dudas.read_text()) if ruta_dudas.exists() else None

            if n_fallos == 0 and v == "listo":
                raise _ParaRun("aprobado")
            if n > max_vueltas:
                raise _ParaRun("tope_vueltas")

            r = await lanza("redactor", "redactor", MODO="revision")
            _exige_terminado("redactor", r)
            n += 1

    except _ParaRun as p:
        motivo = p.motivo
    except asyncio.CancelledError:
        motivo = "interrumpido"
        raise
    except Exception as e:
        motivo = f"excepcion:{type(e).__name__}"
        obtener_log().exception("orquestar: excepción no prevista")
        raise
    finally:
        fin = eventos.emitir(
            "run_fin",
            motivo=motivo,
            vueltas=vueltas_hechas,
            coste_total_usd=round(coste.total, 6),
            duracion_s=time.monotonic() - inicio,
        )
        eventos.cerrar()

    return fin


def _crear_analizador() -> argparse.ArgumentParser:
    """Construye el `ArgumentParser` de la CLI.

    Factorizado fuera de `main()` para poder inspeccionar el default de
    `--salidas` en pruebas sin invocar una orquestación real.
    """
    analizador = argparse.ArgumentParser(prog="python -m enjambre.orquestar")
    analizador.add_argument("--repo", required=True, type=Path)
    # Absoluto y relativo a este fichero (no al cwd): invocar el módulo desde
    # fuera de la raíz del repo no debe desviar las salidas a <cwd>/salidas.
    # parent = enjambre/, parent.parent = raíz del repo.
    analizador.add_argument(
        "--salidas", type=Path, default=Path(__file__).resolve().parent.parent / "salidas"
    )
    analizador.add_argument("--tope-usd", type=float, default=5.0)
    analizador.add_argument("--max-vueltas", type=int, default=2)
    analizador.add_argument("--timeout", type=float, default=600.0)
    analizador.add_argument("--falso", action="store_true")
    return analizador


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m enjambre.orquestar --repo <ruta> [--falso]`."""
    args = _crear_analizador().parse_args(argv)

    if args.falso:
        # Modo de demo/desarrollo: cero llamadas a la API, cero tokens.
        from enjambre.falso import hacer_lanzar_falso

        lanzar = hacer_lanzar_falso(retardo_s=0.5)
    else:
        # D5/D6: el único módulo que importa claude_agent_sdk es lanzador.py,
        # y se importa aquí dentro -- nunca al nivel de módulo de este
        # fichero -- para que `import enjambre.orquestar` (lo que hacen las
        # pruebas, vía el `lanzar` falso) nunca arrastre el SDK.
        from enjambre.lanzador import lanzar

    try:
        fin = asyncio.run(
            orquestar(
                args.repo,
                args.salidas,
                lanzar,
                tope_usd=args.tope_usd,
                max_vueltas=args.max_vueltas,
                timeout_s=args.timeout,
            )
        )
    except KeyboardInterrupt:
        ruta = args.salidas / args.repo.name
        print(f"{args.repo.name} interrumpido ? ? {ruta}")
        return 130

    ruta = args.salidas / args.repo.name / fin["run"]
    print(f"{fin['run']} {fin['motivo']} {fin['vueltas']} {fin['coste_total_usd']} {ruta}")

    if fin["motivo"] == "aprobado":
        return 0
    if fin["motivo"] == "interrumpido":
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
