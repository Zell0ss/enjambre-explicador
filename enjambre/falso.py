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
"""

import asyncio
import time
from pathlib import Path
from typing import Callable

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
            # Función (agente, instancia, encargo, ctx) -> Resultado; puede
            # escribir ficheros distintos de los de pega, o lanzar.
            return entrada(agente, instancia, encargo, ctx)

        campos = _parse_encargo(encargo)
        inicio = time.monotonic()

        ctx.eventos.emitir("estado", instancia, estado="leyendo", detalle="encargo")
        ctx.eventos.emitir("herramienta", instancia, herramienta="Read", detalle="encargo")
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

        return Resultado(
            estado_final="terminado",
            respuesta=f"{instancia}: listo (de pega)",
            modelo_real=f"claude-{agente.modelo}-falso",
            duracion_s=time.monotonic() - inicio,
            tokens_in=100,
            tokens_out=50,
            coste_usd=0.01,
            num_herramientas=len(rutas) + 1,
        )

    return lanzar
