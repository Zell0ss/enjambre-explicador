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
import json
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from enjambre import cerrojo
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
    """Acumulador de coste del run; mutable para que `_paso` lo vaya sumando.
    En una continuación (D24) arranca en 0 -- solo cuenta lo nuevo de ESTE
    tramo, nunca lo ya gastado (`coste_previo_usd`, aparte); el `tope_usd`
    de `reanudar` se compara contra este acumulador, no contra el total."""
    total: float = 0.0


@dataclass
class _Progreso:
    """Cuántas vueltas se han completado -- mutable y visible desde fuera de
    `_ejecutar` (el `finally` de quien la llama lo necesita incluso si
    `_ejecutar` sale por una excepción a mitad de una vuelta), igual que
    `_Coste` de arriba."""
    vueltas: int = 0


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

    D18: toda instancia recibe además una línea aclarando que `SALIDA/x`
    significa `x` -- hipótesis de la prueba de humo: el novato parecía tomar
    "SALIDA/articulo.md" como una cadena literal (con la subcadena "SALIDA")
    en vez de entender que su cwd (`opciones()`, `cwd=ctx.salida`) YA es esa
    carpeta.
    """
    lineas = []
    if rol not in ("redactor", "novato"):
        lineas.append(f"REPO={repo}")
    lineas.append(f"SALIDA={salida}")
    for clave, valor in campos.items():
        lineas.append(f"{clave}={valor}")
    lineas.append(
        "Tu directorio de trabajo ya es SALIDA: donde tus instrucciones dicen SALIDA/x, usa x o la ruta absoluta."
    )
    return "\n".join(lineas) + "\n"


def _parse_encargo(encargo: str) -> dict[str, str]:
    """Inverso de `_encargo`: separa las líneas `CLAVE=valor` en un
    diccionario. Solo lo necesita D24 (`_lanzamientos_hechos`, más abajo)
    para recuperar `PIEZA`/`MODO` de un `encargo` ya escrito en
    `eventos.jsonl` -- no vale la pena guardar esos campos aparte en el
    propio evento `lanzado` cuando ya están codificados en su `encargo`."""
    campos: dict[str, str] = {}
    for linea in encargo.splitlines():
        clave, separador, valor = linea.partition("=")
        if separador:
            campos[clave.strip()] = valor.strip()
    return campos


def _ficheros_de_paso(rol: str, campos: dict[str, str]) -> list[str]:
    """D25: qué ficheros (relativos a `salida`) deja un paso -- los que hay
    que borrar antes de lanzarlo DE VERDAD. La revisión del redactor
    (`MODO=revision`) devuelve `[]` a propósito -- no crea un fichero
    propio distinguible (edita `articulo.md` en sitio), así que no se borra
    nada antes de relanzarla (D25: "la revisión del redactor no borra
    nada").

    NO se usa para decidir si una aparición anterior está "hecha" -- ver
    `_ficheros_prueba_hecho`, que es una lista distinta para el borrador
    del redactor (hallazgo de Josem, D24: ver su docstring)."""
    if rol == "cartografo":
        return ["mapa.md"]
    if rol == "despiezador":
        return ["piezas.md"]
    if rol == "lector-de-pieza":
        return [f"fichas/{campos['PIEZA']}.md"]
    if rol == "trazador":
        return ["flujos.md"]
    if rol == "redactor":
        if campos.get("MODO") == "revision":
            return []
        return ["articulo.md", "cambios.md"]
    if rol == "verificador":
        return ["verificacion.md"]
    if rol == "novato":
        return ["dudas.md"]
    return []


def _paso_esta_hecho(rol: str, campos: dict[str, str], salida: Path) -> bool:
    """D24: ¿demuestra el disco que una aparición anterior de este paso ya
    está hecha? (`_lanzamientos_hechos`, más abajo). Para la mayoría de
    roles basta con que el fichero que D25 borraría (`_ficheros_de_paso`)
    siga existiendo. Dos excepciones, las dos encontradas por Josem contra
    runs reales:

    1. El BORRADOR del redactor: D25 borra `articulo.md` Y `cambios.md`
       (por si acaso, antes de relanzarlo de verdad), pero el borrador solo
       ESCRIBE `articulo.md` -- `cambios.md` no existe hasta la primera
       revisión. Probar con la lista de borrado completa hacía que el
       borrador NUNCA contara como hecho y se repitiera siempre al
       continuar (Claude-Fables-20261004-220410, un borrador de 0,46 $
       repetido).
    2. Verificador/novato: su fichero (`verificacion.md`/`dudas.md`) vive
       en la RAÍZ de `salida`, y cada vuelta siguiente lo borra (D25) y lo
       vuelve a escribir ahí mismo -- para una vuelta ya ARCHIVADA
       (`vueltas/<n>/`, D13, que solo existe si verificador Y novato
       tuvieron éxito los dos) esa copia es la prueba fiable siempre, pase
       lo que pase después en la raíz; si todavía no se ha archivado (la
       vuelta más reciente, cortada a medio terminar porque solo uno de
       los dos acabó), el fichero de la raíz SÍ es fiable, porque nada
       posterior lo ha tocado todavía. Mirar solo la raíz rompía las
       vueltas YA archivadas en cuanto una vuelta posterior empezaba (y
       D25 borraba su fichero para el intento nuevo): el mismo run real de
       arriba, al interrumpirse a media vuelta 3 y continuar, repitió la
       vuelta 1 entera -- ya archivada en `vueltas/1/`, pero su
       `verificacion.md` de la raíz ya lo había borrado el intento de la
       vuelta 3."""
    if rol == "redactor" and campos.get("MODO") != "revision":
        return (salida / "articulo.md").exists()
    if rol == "verificador" and "VUELTA" in campos:
        n = campos["VUELTA"]
        return (salida / "vueltas" / n / "verificacion.md").exists() or (salida / "verificacion.md").exists()
    if rol == "novato" and "VUELTA" in campos:
        n = campos["VUELTA"]
        return (salida / "vueltas" / n / "dudas.md").exists() or (salida / "dudas.md").exists()
    ficheros = _ficheros_de_paso(rol, campos)
    return not ficheros or all((salida / f).exists() for f in ficheros)


def _lanzamientos_hechos(eventos_previos: list[dict], salida: Path) -> dict[tuple[str, str], int]:
    """D24: qué lanzamientos del `eventos.jsonl` de un run anterior ya están
    hechos -- `lanzado` seguido (más adelante, no necesariamente a
    continuación: otras instancias emiten de por medio mientras corren en
    paralelo) de `fin_agente` con `estado_final: terminado` para la MISMA
    instancia, y el disco demuestra que ese paso está hecho
    (`_paso_esta_hecho`).

    Clave `(instancia, encargo)`, contando apariciones: la revisión del
    redactor repite el mismo encargo en cada vuelta (no lleva `VUELTA=n`),
    así que solo el número de apariciones ya hechas distingue cuántas veces
    se salta -- `reanudar` consume una por cada `lanza(...)` que coincida,
    en el mismo orden en que el guion las vuelve a recorrer (FIFO)."""
    abiertos: dict[str, tuple[str, str]] = {}  # instancia -> (encargo, rol)
    hechos: dict[tuple[str, str], int] = {}
    for ev in eventos_previos:
        tipo = ev.get("tipo")
        if tipo == "lanzado":
            abiertos[ev["agente"]] = (ev["encargo"], ev["rol"])
        elif tipo == "fin_agente":
            abierto = abiertos.pop(ev.get("agente"), None)
            if abierto is None or ev.get("estado_final") != "terminado":
                continue
            encargo, rol = abierto
            if not _paso_esta_hecho(rol, _parse_encargo(encargo), salida):
                continue
            clave = (ev["agente"], encargo)
            hechos[clave] = hechos.get(clave, 0) + 1
    return hechos


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
        num_turns=resultado.num_turns,
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


async def _ejecutar(
    ctx: Contexto,
    lanzar: Lanzar,
    coste: _Coste,
    tope_usd: float,
    max_vueltas: int,
    timeout_s: float,
    agentes: dict[str, Agente],
    progreso: _Progreso,
    hechos: dict[tuple[str, str], int],
) -> None:
    """El guion fijo (D5), de cartógrafo a la última vuelta -- el ÚNICO
    recorrido (D24: "no hay un segundo guion"). Lo usan tanto un run nuevo
    (`orquestar`, `hechos={}`: cada `lanza(...)` se ejecuta siempre de
    verdad, idéntico a antes de la Tarea 17) como una continuación
    (`reanudar`, `hechos` poblado desde el `eventos.jsonl` anterior): la
    diferencia entera vive dentro de `lanza`, más abajo, que decide por cada
    lanzamiento si saltarlo (D24) o lanzarlo de verdad, borrando antes lo
    que vaya a crear (D25).

    Termina lanzando `_ParaRun` (motivo final) o dejando escapar cualquier
    otra excepción -- igual que el cuerpo del `orquestar` de antes de la
    Tarea 17; quien llama (`orquestar`/`reanudar`) pone el `try/except/
    finally` alrededor y emite su propio `run_fin`, porque el coste previo y
    el emisor difieren entre un run nuevo y una continuación."""

    def _consumir_hecho(instancia: str, encargo: str) -> bool:
        """D24: ¿hay una aparición ya hecha de (instancia, encargo) sin
        consumir? Si la hay, la consume (resta una) y devuelve True."""
        clave = (instancia, encargo)
        n = hechos.get(clave, 0)
        if n <= 0:
            return False
        hechos[clave] = n - 1
        return True

    async def lanza(instancia: str, rol: str, **campos) -> Resultado:
        encargo = _encargo(rol, ctx.repo, ctx.salida, **campos)
        if _consumir_hecho(instancia, encargo):
            # D24: ya está hecho -- ni se llama a `lanzar` ni se emite nada
            # (ni `lanzado`, ni `estado`, ni `fin_agente`): el `eventos.jsonl`
            # de la vez anterior ya cuenta esta historia.
            return Resultado(estado_final="terminado")
        # D25: antes de lanzar DE VERDAD, borrar lo que este paso va a crear
        # -- sustituye por completo el borrado puntual de D16 (antes, solo
        # desde la vuelta 2); aquí es un no-op la primera vez que cada
        # fichero no existe todavía, y es lo que permite que un paso
        # relanzado en una continuación encuentre sitio limpio (D25: la tool
        # `Write` real no sobrescribe un fichero que el agente no haya leído
        # en su propia sesión).
        for nombre in _ficheros_de_paso(rol, campos):
            ruta = ctx.salida / nombre
            if ruta.exists():
                ruta.unlink()
        return await _paso(ctx, lanzar, coste, tope_usd, instancia, agentes[rol], encargo, timeout_s)

    # --- cartografo ---------------------------------------------------
    r = await lanza("cartografo", "cartografo")
    _exige_terminado("cartografo", r)
    _exige(ctx.salida, "mapa.md")

    # --- despiezador ---------------------------------------------------
    r = await lanza("despiezador", "despiezador")
    _exige_terminado("despiezador", r)
    _exige(ctx.salida, "piezas.md")
    try:
        ids = ids_de_piezas((ctx.salida / "piezas.md").read_text())
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
        _exige(ctx.salida, f"fichas/{id_}.md")

    # --- trazador -------------------------------------------------------
    r = await lanza("trazador", "trazador")
    _exige_terminado("trazador", r)
    _exige(ctx.salida, "flujos.md")

    # --- redactor, borrador ----------------------------------------------
    r = await lanza("redactor", "redactor", MODO="borrador")
    _exige_terminado("redactor", r)
    _exige(ctx.salida, "articulo.md")

    # --- vueltas de verificación / revisión --------------------------------
    n = 1
    while True:
        # Comprobar el tope de coste ANTES de emitir `vuelta` y de contar
        # esta `n` como una vuelta hecha: si una revisión anterior ya lo
        # agotó, el verificador+novato de esta vuelta nunca se intentan,
        # así que ni el evento `vuelta` ni `progreso.vueltas` deben existir
        # para ella (bug real: sin este chequeo aquí, `_paso` seguía
        # frenando a verificador/novato dentro del `gather` de más abajo,
        # pero `progreso.vueltas = n` ya se había ejecutado para una vuelta
        # que nunca llegó a lanzar nada).
        _comprueba_tope(coste, tope_usd)

        # D24 ("vueltas hechas"): si esta vuelta ya se completó del todo en
        # un tramo anterior -- verificador Y novato hechos, y su copia de
        # archivo en vueltas/<n>/ existe -- no se relanza nada ni se emite
        # `vuelta` otra vez; se restauran sus dos ficheros a la raíz de
        # salida (los de ahí pueden ser de una vuelta MÁS TARDÍA, ya
        # sobrescritos) y se evalúa igual que siempre. Si falta uno de los
        # dos (p.ej. el tope de coste cortó entre los dos lanzamientos en
        # paralelo), esta vuelta NO se da por hecha del todo: se emite
        # `vuelta` otra vez y se relanza solo el que falte -- `lanza` ya
        # sabe saltar el que sí está hecho.
        encargo_ver = _encargo("verificador", ctx.repo, ctx.salida, VUELTA=n)
        encargo_nov = _encargo("novato", ctx.repo, ctx.salida, VUELTA=n)
        copia = ctx.salida / "vueltas" / str(n)
        ver_hecho = hechos.get(("verificador", encargo_ver), 0) > 0
        nov_hecho = hechos.get(("novato", encargo_nov), 0) > 0
        vuelta_hecha = (
            ver_hecho and nov_hecho and (copia / "verificacion.md").exists() and (copia / "dudas.md").exists()
        )

        if vuelta_hecha:
            shutil.copy2(copia / "verificacion.md", ctx.salida / "verificacion.md")
            shutil.copy2(copia / "dudas.md", ctx.salida / "dudas.md")
            _consumir_hecho("verificador", encargo_ver)
            _consumir_hecho("novato", encargo_nov)
            progreso.vueltas = n
        else:
            ctx.eventos.emitir("vuelta", n=n)

            r_ver, r_nov = await asyncio.gather(
                lanza("verificador", "verificador", VUELTA=n),
                lanza("novato", "novato", VUELTA=n),
                return_exceptions=True,
            )
            # Igual que antes de la Tarea 17: se cuenta esta vuelta como
            # "hecha" en cuanto se ha intentado -- ANTES de los `_exige*` de
            # más abajo, que pueden parar el run -- para que un fallo a
            # mitad de vuelta siga contando (`fin["vueltas"]` incluye la
            # vuelta fallida, no solo las que llegaron a completarse).
            progreso.vueltas = n
            r_ver = _resultado_o_fallo("verificador", r_ver)
            _exige_terminado("verificador", r_ver)
            r_nov = _resultado_o_fallo("novato", r_nov)
            _exige_terminado("novato", r_nov)

            # Exigir que de verdad se hayan escrito verificacion.md/dudas.md
            # tras este lanzamiento, en TODAS las vueltas (no solo desde la
            # 2): sin esto, un verificador/novato que no escribe su fichero
            # deja `n_fallos`/`v` en `None` más abajo -- no cuenta como
            # aprobado, así que el run sigue de largo, lanza al redactor en
            # modo revisión y entra en una vuelta completa de más (coste
            # real) antes de que nada lo note, en vez de parar aquí mismo
            # con `falta:<fichero>`.
            _exige(ctx.salida, "verificacion.md")
            _exige(ctx.salida, "dudas.md")

            # D13: copiar verificacion.md/dudas.md a vueltas/<n>/ antes de
            # que la vuelta siguiente los sobrescriba (en la fase 1 la
            # vuelta 1 se perdió así); copiar los que existan, sin tocar los
            # prompts.
            copia.mkdir(parents=True, exist_ok=True)
            for nombre in ("verificacion.md", "dudas.md"):
                origen = ctx.salida / nombre
                if origen.exists():
                    shutil.copy2(origen, copia / nombre)

        ruta_verificacion = ctx.salida / "verificacion.md"
        ruta_dudas = ctx.salida / "dudas.md"
        n_fallos = fallos(ruta_verificacion.read_text()) if ruta_verificacion.exists() else None
        v = veredicto(ruta_dudas.read_text()) if ruta_dudas.exists() else None

        if n_fallos == 0 and v == "listo":
            raise _ParaRun("aprobado")
        if n > max_vueltas:
            raise _ParaRun("tope_vueltas")

        r = await lanza("redactor", "redactor", MODO="revision")
        _exige_terminado("redactor", r)
        n += 1


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
    falso: bool = False,
    fuente: str | None = None,
    commit: str | None = None,
    peso: dict | None = None,
) -> dict:
    """Lanza el enjambre sobre `repo` y devuelve el evento `run_fin`.

    Fase 3: `fuente` y `commit` (de dónde salió el repo y qué versión se lee)
    van al nivel superior de `run_inicio`, siempre presentes y quizá `None`:
    es un campo añadido, que la regla de compatibilidad de §4 permite. Igual
    `peso` (D40: lo que `enjambre.peso` estimó antes de gastar; `None` si falló).

    D24: `falso` no decide qué `lanzar` se usa -- eso lo sigue eligiendo
    quien llama (`main`), igual que antes -- solo se anota en
    `params.falso` de `run_inicio`, para que una futura `reanudar` sepa si
    este run gastaba de verdad sin tener que adivinarlo."""
    run = run or f"{repo.name}-{datetime.now():%Y%m%d-%H%M}"
    salida = salidas / repo.name / run
    if salida.exists():
        raise FileExistsError(f"ya existe una ejecución en {salida}")
    salida.mkdir(parents=True)

    eventos = Eventos(salida / "eventos.jsonl", run)
    inicio = time.monotonic()
    coste = _Coste()
    progreso = _Progreso()
    motivo = "excepcion:desconocido"  # se sobrescribe siempre en algún except; no debería sobrevivir.

    try:
        agentes = {rol: cargar(rol) for rol in ROLES}
        params = {
            "tope_usd": tope_usd,
            "max_vueltas": max_vueltas,
            "timeout_s": timeout_s,
            "max_turns": max_turns,
            "falso": falso,
        }
        eventos.emitir(
            "run_inicio",
            repo=str(repo),
            salida=str(salida),
            params=params,
            roles={rol: a.modelo for rol, a in agentes.items()},
            fuente=fuente,
            commit=commit,
            peso=peso,
        )
        for rol in ("cartografo", "despiezador", "trazador", "redactor", "verificador", "novato"):
            eventos.emitir("estado", rol, estado="esperando")

        ctx = Contexto(repo=repo, salida=salida, eventos=eventos, timeout_s=timeout_s, max_turns=max_turns)
        await _ejecutar(ctx, lanzar, coste, tope_usd, max_vueltas, timeout_s, agentes, progreso, {})

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
            vueltas=progreso.vueltas,
            coste_total_usd=round(coste.total, 6),
            duracion_s=time.monotonic() - inicio,
        )
        eventos.cerrar()

    return fin


async def reanudar(
    salida: Path,
    lanzar: Lanzar,
    *,
    tope_usd: float = 5.0,
    max_vueltas: int | None = None,
) -> dict:
    """Continúa un run parado (D24): mismo directorio, mismo
    `eventos.jsonl` (se sigue escribiendo ahí, nunca uno nuevo), sin otro
    `run_inicio` -- solo un `reanudado`. Recorre el MISMO `_ejecutar` que
    `orquestar`, con `hechos` poblado desde la historia anterior para que
    cada lanzamiento ya hecho se salte sin gastar ni emitir nada (D24) y
    cada paso que sí se relanza de verdad borre antes lo que va a crear
    (D25).

    `tope_usd` se compara contra lo gastado EN ESTA continuación (el
    `_Coste` de `_ejecutar` arranca en 0, igual que en un run nuevo); el
    `coste_total_usd` del `run_fin` nuevo es `coste_previo_usd` + eso.
    """
    ruta_eventos = salida / "eventos.jsonl"
    lineas = [l for l in ruta_eventos.read_text().splitlines() if l.strip()]
    eventos_previos = [json.loads(l) for l in lineas]
    if not eventos_previos or eventos_previos[-1].get("tipo") != "run_fin":
        raise ValueError(f"{ruta_eventos}: no termina en run_fin, no se puede continuar")
    run_fin_previo = eventos_previos[-1]
    if run_fin_previo.get("motivo") == "aprobado":
        raise ValueError(f"{ruta_eventos}: ya está aprobado, nada que continuar")

    run_inicio = next(e for e in eventos_previos if e.get("tipo") == "run_inicio")
    repo = Path(run_inicio["repo"])
    params_previos = dict(run_inicio.get("params") or {})
    timeout_s = params_previos.get("timeout_s", 600)
    max_turns = params_previos.get("max_turns", 60)
    if max_vueltas is None:
        max_vueltas = params_previos.get("max_vueltas", 2)

    hechos = _lanzamientos_hechos(eventos_previos, salida)
    coste_previo_usd = round(
        sum(e.get("coste_usd") or 0 for e in eventos_previos if e.get("tipo") == "fin_agente"), 6
    )

    eventos = Eventos(ruta_eventos, run_inicio["run"])
    inicio = time.monotonic()
    coste = _Coste()
    progreso = _Progreso()
    motivo = "excepcion:desconocido"

    try:
        agentes = {rol: cargar(rol) for rol in ROLES}
        params_efectivos = {**params_previos, "max_vueltas": max_vueltas, "tope_usd": tope_usd}
        # D24: nunca otro `run_inicio` -- un único `reanudado` basta para que
        # la pantalla sepa que el run sigue siendo el mismo.
        eventos.emitir(
            "reanudado",
            params=params_efectivos,
            coste_previo_usd=coste_previo_usd,
            desde=run_fin_previo.get("motivo"),
        )
        ctx = Contexto(repo=repo, salida=salida, eventos=eventos, timeout_s=timeout_s, max_turns=max_turns)
        await _ejecutar(ctx, lanzar, coste, tope_usd, max_vueltas, timeout_s, agentes, progreso, hechos)

    except _ParaRun as p:
        motivo = p.motivo
    except asyncio.CancelledError:
        motivo = "interrumpido"
        raise
    except Exception as e:
        motivo = f"excepcion:{type(e).__name__}"
        obtener_log().exception("reanudar: excepción no prevista")
        raise
    finally:
        fin = eventos.emitir(
            "run_fin",
            motivo=motivo,
            vueltas=progreso.vueltas,
            coste_total_usd=round(coste_previo_usd + coste.total, 6),
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
    # `--repo` ya no es `required`: con `--reanudar` no hace falta (sale del
    # `run_inicio` del propio run) -- `main()` exige uno de los dos a mano.
    analizador.add_argument("--repo", type=Path, default=None)
    # Absoluto y relativo a este fichero (no al cwd): invocar el módulo desde
    # fuera de la raíz del repo no debe desviar las salidas a <cwd>/salidas.
    # parent = enjambre/, parent.parent = raíz del repo.
    analizador.add_argument(
        "--salidas", type=Path, default=Path(__file__).resolve().parent.parent / "salidas"
    )
    analizador.add_argument("--tope-usd", type=float, default=5.0)
    # `None` (no 2) por defecto: así `main()` distingue "no se pasó" de "se
    # pasó 2" -- con `--reanudar`, "no se pasó" significa heredar el
    # `max_vueltas` del `run_inicio` anterior (D24), no forzar 2.
    analizador.add_argument("--max-vueltas", type=int, default=None)
    analizador.add_argument("--timeout", type=float, default=600.0)
    analizador.add_argument("--falso", action="store_true")
    # Anexo 2026-10-04, Tarea 15 (D21): lo fija `pantalla.py` al lanzar un
    # run desde la página -- el nombre lo decide el servidor (con segundos,
    # para no chocar) y se lo pasa aquí para que el subproceso escriba
    # exactamente en el `salida` que la pantalla ya le prometió al navegador
    # antes de que exista. Sin él, igual que siempre (`orquestar()` lo
    # genera a partir de la hora actual).
    analizador.add_argument("--run", default=None)
    # D24 (Tarea 17): continuar un run parado. Excluye --repo/--run/--falso
    # (todos ellos salen del propio run) -- `main()` lo valida a mano porque
    # la exclusión depende de cuál de los dos modos se use, no de un grupo
    # fijo de argparse.
    analizador.add_argument("--reanudar", type=Path, default=None)
    # D31: un run a la vez en la máquina. Parámetro para que las pruebas no
    # toquen el cerrojo real.
    analizador.add_argument("--cerrojo", type=Path, default=cerrojo.RUTA)
    return analizador


def _falso_del_run(salida: Path) -> bool | None:
    """Lee `params.falso` del `run_inicio` de `salida/eventos.jsonl`.
    `None` si el fichero no se puede leer/parsear o el run es anterior a
    D24 (sin esa clave) -- en los dos casos, `main()` sale con código 2:
    no se adivina si un run viejo gastaba de verdad."""
    try:
        lineas = [l for l in (salida / "eventos.jsonl").read_text().splitlines() if l.strip()]
        eventos_previos = [json.loads(l) for l in lineas]
        run_inicio = next(e for e in eventos_previos if e.get("tipo") == "run_inicio")
    except (OSError, json.JSONDecodeError, StopIteration):
        return None
    params = run_inicio.get("params") or {}
    return params["falso"] if "falso" in params else None


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m enjambre.orquestar --repo <ruta> [--falso]`, o
    `python -m enjambre.orquestar --reanudar <salida>` para continuar un run
    parado (D24)."""
    args = _crear_analizador().parse_args(argv)

    # D31: el cerrojo cubre el run entero (también --reanudar) y lo toma quien
    # ejecuta, no `orquestar()`/`reanudar()`: así las pruebas de esas no cambian.
    try:
        with cerrojo.tomar(args.cerrojo):
            return _main_con_cerrojo(args)
    except cerrojo.Ocupado:
        print("hay otro run en marcha", file=sys.stderr)
        return 3


def _main_con_cerrojo(args: argparse.Namespace) -> int:
    if args.reanudar is not None:
        if args.repo is not None or args.run is not None:
            print("--reanudar excluye --repo y --run", file=sys.stderr)
            return 2
        # `--falso` NO se valida como excluyente aquí (a diferencia de
        # --repo/--run): el modo real lo decide siempre `_falso_del_run`,
        # nunca este flag -- pero `/api/reanudar` (pantalla.py) sí lo pasa,
        # derivado de `params.falso` del propio run, así que rechazarlo aquí
        # rompería esa costura. Pasarlo a mano desde la terminal (sin pasar
        # por la pantalla) es inútil pero inofensivo: se ignora.

        es_falso = _falso_del_run(args.reanudar)
        if es_falso is None:
            print(
                f"--reanudar {args.reanudar}: no tiene params.falso (run anterior a D24) -- "
                "no se puede saber si era real o --falso, así que no se continúa a ciegas",
                file=sys.stderr,
            )
            return 2
        if es_falso:
            from enjambre.falso import hacer_lanzar_falso

            lanzar = hacer_lanzar_falso(retardo_s=0.5)
        else:
            from enjambre.lanzador import lanzar

        try:
            fin = asyncio.run(
                reanudar(args.reanudar, lanzar, tope_usd=args.tope_usd, max_vueltas=args.max_vueltas)
            )
        except KeyboardInterrupt:
            print(f"{args.reanudar} interrumpido")
            return 130
        except ValueError as e:
            print(f"--reanudar {args.reanudar}: {e}", file=sys.stderr)
            return 2

        print(f"{fin['run']} {fin['motivo']} {fin['vueltas']} {fin['coste_total_usd']} {args.reanudar}")
        if fin["motivo"] == "aprobado":
            return 0
        if fin["motivo"] == "interrumpido":
            return 130
        return 1

    if args.repo is None:
        print("--repo es obligatorio (salvo con --reanudar)", file=sys.stderr)
        return 2

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
                max_vueltas=args.max_vueltas if args.max_vueltas is not None else 2,
                timeout_s=args.timeout,
                run=args.run,
                falso=args.falso,
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
