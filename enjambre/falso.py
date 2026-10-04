"""
Lanzar falso: implementa el contrato `Lanzar` (T5) sin tocar el SDK, para que
`orquestar` se pueda probar y hacer una demo sin gastar tokens ni llamadas a
la API (el `lanzar` real vive en `enjambre/lanzador.py`, Tarea 7; nada de aquí
lo importa).

Por defecto, cada rol escribe el fichero "de pega" que el rol real dejaría en
`ctx.salida`, emitiendo los eventos que le tocan a `lanzar` -- `estado`,
`herramienta`, `fichero` -- y nunca `lanzado`/`respuesta`/`fin_agente`, que
son responsabilidad de `orquestar` (D5: el guion narra el run, no el agente).

`guion` permite sustituir, por instancia (p.ej. "verificador" o
"lector-de-pieza:b-dos"), una lista de `Resultado` o funciones que se
consumen por orden de llamada (`.pop(0)`). Al agotarse la lista de una
instancia, sus llamadas siguientes caen de vuelta al comportamiento de pega
por defecto: el guion solo sustituye un PREFIJO de las llamadas de esa
instancia, no todas para siempre.

Una entrada-función puede ser síncrona o `async def` (o cualquier callable
cuya llamada devuelva un awaitable): se llama igual en los dos casos y, si lo
que devuelve es awaitable, se espera antes de usarlo como `Resultado` -- una
entrada de guion de prueba puede así ejercitar una ruta `await` real (p.ej.
`asyncio.sleep`) sin que eso cambie en nada el caso de una `Resultado` suelta,
que nunca se llama ni se espera.
"""

import asyncio
import inspect
import time
from pathlib import Path
from typing import Callable

from enjambre.parsers import SalidaIlegible, ids_de_piezas
from enjambre.tipos import Contexto, Lanzar, Resultado


def _parse_encargo(encargo: str) -> dict[str, str]:
    """Separa las líneas `CLAVE=valor` del encargo en un diccionario."""
    campos: dict[str, str] = {}
    for linea in encargo.splitlines():
        clave, separador, valor = linea.partition("=")
        if separador:
            campos[clave.strip()] = valor.strip()
    return campos


def _escribir_de_pega(rol: str, campos: dict[str, str], ctx: Contexto) -> list[Path]:
    """Escribe el/los fichero(s) de pega que el rol real dejaría y los
    devuelve, para poder emitir un evento `fichero` por cada uno."""
    if rol == "cartografo":
        ruta = ctx.salida / "mapa.md"
        ruta.write_text("# Mapa (de pega)\n\nUn repo de mentira para probar el guion.\n")
        return [ruta]

    if rol == "despiezador":
        ruta = ctx.salida / "piezas.md"
        ruta.write_text(
            "## Resumen\n"
            "| Id | Descripción |\n"
            "|---|---|\n"
            "| a-uno | pieza de pega |\n"
            "| b-dos | pieza de pega |\n"
            "| c-tres | pieza de pega |\n"
        )
        return [ruta]

    if rol == "lector-de-pieza":
        pieza = campos["PIEZA"]
        ruta = ctx.salida / "fichas" / f"{pieza}.md"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(f"# Ficha de {pieza} (de pega)\n")
        return [ruta]

    if rol == "trazador":
        ruta = ctx.salida / "flujos.md"
        ruta.write_text("# Flujos (de pega)\n")
        return [ruta]

    if rol == "redactor":
        articulo = ctx.salida / "articulo.md"
        articulo.write_text("# Artículo (de pega)\n")
        rutas = [articulo]
        if campos.get("MODO") == "revision":
            # D13 (vía orquestar): verificacion.md/dudas.md ya se copiaron a
            # vueltas/<n>/ antes de llegar aquí; cambios.md es la respuesta
            # del redactor a esa vuelta, no algo que D13 tenga que proteger.
            cambios = ctx.salida / "cambios.md"
            previo = cambios.read_text() if cambios.exists() else ""
            cambios.write_text(previo + "- revisión de pega\n")
            rutas.append(cambios)
        return rutas

    if rol == "verificador":
        ruta = ctx.salida / "verificacion.md"
        ruta.write_text("## Resultado\n\n- Fallos: 0\n")
        return [ruta]

    if rol == "novato":
        ruta = ctx.salida / "dudas.md"
        ruta.write_text("## Veredicto\n\n`listo`\n")
        return [ruta]

    raise ValueError(f"hacer_lanzar_falso: rol desconocido '{rol}'")


# D22 (Tarea 16, anexo 2026-10-04 (2)): roles con acceso al repo -- cartógrafo
# (lo mapea), despiezador (lo trocea en piezas), lector-de-pieza (lee la suya)
# y trazador (traza flujos por el código). redactor/verificador/novato NO
# -- D2 ("el redactor no ve el repo"; verificador y novato no lo necesitan
# para su trabajo, solo ven la salida). Decisión propia: el plan dice
# "los agentes con repo leen uno o dos ficheros del repo" sin enumerar
# cuáles son "los agentes con repo" -- se interpreta como los cuatro de
# arriba, consistentes con quién tiene REPO en su encargo real
# (`orquestar._encargo`, D2: "al redactor y al novato no se les pasa REPO").
_ROLES_CON_REPO = {"cartografo", "despiezador", "lector-de-pieza", "trazador"}


def _lecturas_de_pega(rol: str, campos: dict[str, str], ctx: Contexto) -> list[Path]:
    """D22: qué lee cada rol en la demo --falso, de la salida y del repo si
    le toca, antes de ponerse a escribir -- para que la mesa de papeles
    tenga lecturas por agente, papel que se enciende y puertas que enseñar.
    Rutas ABSOLUTAS en cada caso (igual que emitiría el `lanzar` real, D17):
    relativizarlas para mostrarlas es cosa del reductor del lado de la
    pantalla, no de aquí."""
    salida, repo = ctx.salida, ctx.repo
    lecturas: list[Path] = []

    if rol == "despiezador":
        lecturas.append(salida / "mapa.md")
    elif rol == "lector-de-pieza":
        lecturas.append(salida / "piezas.md")
    elif rol in ("trazador", "redactor"):
        # Todas las fichas que el despiezador ya decidió y los lectores ya
        # escribieron -- se leen de piezas.md de verdad, no de una lista
        # hardcodeada aquí, para que un guion de prueba que cambie las
        # piezas (otros ids, menos o más lectores) se refleje también aquí.
        piezas_path = salida / "piezas.md"
        if piezas_path.exists():
            try:
                ids = ids_de_piezas(piezas_path.read_text())
            except SalidaIlegible:
                ids = []
            for id_ in ids:
                ficha = salida / "fichas" / f"{id_}.md"
                if ficha.exists():
                    lecturas.append(ficha)
    elif rol in ("verificador", "novato"):
        # "El verificador nunca lee fichas, así que en la demo la puerta del
        # prompt se queda en 0" (Paso 3) -- por eso NO hay una rama que le dé
        # fichas aquí, a diferencia de trazador/redactor arriba.
        lecturas.append(salida / "articulo.md")

    if rol in _ROLES_CON_REPO:
        lecturas.append(repo / "README.md")

    return lecturas


def _denegado_de_pega(rol: str, campos: dict[str, str], ctx: Contexto, instancia: str) -> None:
    """D22: en la primera vuelta, el redactor y el novato "intentan" leer
    algo fuera de su muro -- puro teatro para que la demo --falso enseñe
    las puertas del guardia encendidas al menos una vez. Emite el evento
    `denegado` directamente, SIN pasar por `guardia.permitido()`: esto no es
    el lanzador real (D6/D8 no aplican a este módulo, D6 dice explícitamente
    que todo el acceso al SDK -- y el guardia real cuelga del hook del
    lanzador real -- vive detrás de `lanzar()`), así que no hay ningún
    guardia de verdad al que consultar aquí. El comentario es la advertencia:
    estos `denegado` no demuestran que el muro funcione, solo que la vista
    sabe pintarlo."""
    if rol == "redactor" and campos.get("MODO") == "borrador":
        intento = ctx.repo / "backend" / "servicio.py"
        ctx.eventos.emitir(
            "denegado",
            instancia,
            herramienta="Read",
            detalle=str(intento),
            motivo="el redactor no ve el repo (D2) -- teatro de demo, --falso",
        )
    elif rol == "novato" and campos.get("VUELTA") == "1":
        intento = ctx.salida / "fichas" / "a-uno.md"
        ctx.eventos.emitir(
            "denegado",
            instancia,
            herramienta="Read",
            detalle=str(intento),
            motivo="el novato solo ve articulo.md y dudas.md (D2) -- teatro de demo, --falso",
        )


def hacer_lanzar_falso(
    guion: "dict[str, list[Resultado | Callable]] | None" = None,
    retardo_s: float = 0.0,
) -> Lanzar:
    """Fabrica un `lanzar` falso. Ver el docstring del módulo."""
    # Copia las listas: no mutamos el dict que nos pasó quien llama (varias
    # pruebas reutilizan el mismo literal de guion para hacer varios asserts).
    guion_restante: dict[str, list] = {
        instancia: list(entradas) for instancia, entradas in (guion or {}).items()
    }

    async def lanzar(agente, instancia: str, encargo: str, ctx: Contexto) -> Resultado:
        pendientes = guion_restante.get(instancia)
        if pendientes:
            entrada = pendientes.pop(0)
            if isinstance(entrada, Resultado):
                return entrada
            # Función (agente, instancia, encargo, ctx) -> Resultado, o
            # -> Awaitable[Resultado] (p.ej. `async def`); puede escribir
            # ficheros distintos de los de pega, o lanzar.
            resultado = entrada(agente, instancia, encargo, ctx)
            if inspect.isawaitable(resultado):
                resultado = await resultado
            return resultado

        campos = _parse_encargo(encargo)
        inicio = time.monotonic()

        ctx.eventos.emitir("estado", instancia, estado="leyendo", detalle="encargo")

        # D22 (Tarea 16, retoque 5): ya NO se emite un `herramienta` Read de
        # "encargo" -- no es una ruta, y el panel "Ahora" (que lista
        # `agente.lecturas`, construido solo a partir de Read de rutas, ver
        # estado.js) lo enseñaba tal cual, como si fuera un papel más.
        # Lecturas de verdad de la salida/repo + el Glob con patrón del
        # cartógrafo (D23) + el teatro de denegados de redactor/novato en su
        # primera vuelta -- todo dentro de la misma fase "leyendo", sin
        # sleeps nuevos, para no alargar la demo.
        lecturas_extra = _lecturas_de_pega(agente.rol, campos, ctx)
        for ruta_leida in lecturas_extra:
            ctx.eventos.emitir("herramienta", instancia, herramienta="Read", detalle=str(ruta_leida))
        if agente.rol == "cartografo":
            # D23: en el run real, la mitad de los Glob del cartógrafo
            # decían solo la ruta del repo -- aquí se emite ya con patrón,
            # para que la demo enseñe el campo nuevo desde el principio.
            ctx.eventos.emitir(
                "herramienta", instancia, herramienta="Glob", detalle=str(ctx.repo), patron="**/*.py"
            )
        _denegado_de_pega(agente.rol, campos, ctx, instancia)

        if retardo_s:
            await asyncio.sleep(retardo_s)

        ctx.eventos.emitir("estado", instancia, estado="escribiendo")
        rutas = _escribir_de_pega(agente.rol, campos, ctx)
        for ruta in rutas:
            ctx.eventos.emitir("herramienta", instancia, herramienta="Write", detalle=str(ruta))
            ctx.eventos.emitir("fichero", instancia, ruta=str(ruta.relative_to(ctx.salida)))
        if retardo_s:
            await asyncio.sleep(retardo_s)

        ctx.eventos.emitir("estado", instancia, estado="terminado")

        num_herramientas = (
            len(rutas) + len(lecturas_extra) + (1 if agente.rol == "cartografo" else 0)
        )
        return Resultado(
            estado_final="terminado",
            respuesta=f"{instancia}: listo (de pega)",
            modelo_real=f"claude-{agente.modelo}-falso",
            duracion_s=time.monotonic() - inicio,
            tokens_in=100,
            tokens_out=50,
            coste_usd=0.01,
            num_herramientas=num_herramientas,
        )

    return lanzar
