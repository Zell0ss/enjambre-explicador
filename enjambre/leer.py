"""
`python -m enjambre.leer <fuente>`: los cuatro pasos de §8.1 para una fuente.

    1. actualizar la copia (D27)
    2. orquestar, o continuar el run parado (D24)
    3. nota -> Clippings/repo-articles/<repo>.md (D28)
    4. aviso por Telegram (D32)

`leer()` hace 1-3 y devuelve una `Lectura`. No toma el cerrojo ni avisa: eso es
de `main` (un "Lanzar ahora") y de la cola (la noche), que lo hacen una vez
para todo lo que lean (D31).
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

from enjambre import aviso, cerrojo
from enjambre.fuente import RAIZ_COPIAS, CopiaAjena, Fuente, FuenteInvalida, GitFallo, actualizar, resolver
from enjambre.nota import FINALES, RAIZ_NOTAS, NotaAjena, comprobar, escribir, leer_frontmatter
from enjambre.orquestar import orquestar, reanudar
from enjambre.tipos import Lanzar, Lectura


class RepoCambiado(ValueError):
    """D36: se pidió continuar un run, pero el repo ya no está en el commit que ese run leyó."""


def _eventos(salida: Path) -> list[dict]:
    lineas = (salida / "eventos.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lineas if l.strip()]


def _run_inicio(eventos: list[dict]) -> dict:
    return next(e for e in eventos if e.get("tipo") == "run_inicio")


def _escribir_nota(
    f: Fuente, commit: str | None, salida: Path, fin: dict, coste_usd: float, *,
    falso: bool, raiz_notas: Path, ahora,
) -> Path | None:
    if fin["motivo"] not in FINALES:
        return None
    articulo = (salida / "articulo.md").read_text(encoding="utf-8")
    # `falso`: la demo escribe en la salida del run, nunca en el vault.
    raiz, fichero = (salida, "nota.md") if falso else (raiz_notas, None)
    return escribir(
        raiz, fuente=f.texto, nombre=f.nombre, commit=commit, run=fin["run"],
        # La nota lleva lo que costó el artículo entero (el run), no solo esta
        # continuación; `Lectura.coste_usd` es lo de esta lectura (foco 4).
        coste_usd=fin["coste_total_usd"], motivo=fin["motivo"], vueltas=fin["vueltas"],
        articulo=articulo, leido=ahora(), fichero=fichero,
    )


async def leer(
    f: Fuente, *, salidas: Path, lanzar: Lanzar, raiz_copias: Path = RAIZ_COPIAS,
    raiz_notas: Path = RAIZ_NOTAS, tope_usd: float = 5.0, max_vueltas: int | None = 2,
    run: str | None = None, falso: bool = False, reanudar: Path | None = None,
    saltar_si_igual: bool = False, remoto: str | None = None, ahora=datetime.now,
    si_cambio: Literal["nuevo", "error"] = "nuevo",
) -> Lectura:
    """`max_vueltas=None` solo tiene sentido al continuar: hereda el del run
    parado (D24); en un run nuevo vale 2.

    `si_cambio` (D36) decide qué pasa si se pide continuar (`reanudar`) y el
    commit de ahora no es el del run: `"nuevo"` lanza un run nuevo (la cola,
    D30: allí sí se pidió leer el repo) y `"error"` lanza `RepoCambiado` antes
    de lanzar nada ("Continuar" promete seguir con lo ya pagado, no gastar en
    un run entero que nadie pidió)."""
    # R3 (revisión de H2): un choque de nombre con una nota ajena se sabe ya, y
    # no hay que pagar un run entero para descubrirlo. Con `falso` la nota no va al vault.
    if not falso:
        comprobar(raiz_notas, f.nombre, f.texto)
    ruta, commit = actualizar(f, raiz_copias=raiz_copias, remoto=remoto)

    # D35: el salto se decide con `salidas/` (el último run ACABADO de esta fuente
    # y este commit), no con la nota: una nota que Josem sacó de Clippings/ no
    # debe hacer que se pague otra vez el mismo commit.
    if saltar_si_igual and commit is not None:
        acabado = _ultimo_acabado(salidas, f.texto)
        if acabado is not None and acabado.get("commit") == commit:
            nota = raiz_notas / f"{f.nombre}.md"
            return Lectura(fuente=f.texto, nombre=f.nombre, commit=commit, run=None, salida=None,
                           motivo="sin_cambios", vueltas=0, coste_usd=0.0,
                           nota=nota if nota.exists() else None)

    if reanudar is not None:
        previos = _eventos(reanudar)
        inicio = _run_inicio(previos)
        # Con otro commit el código ha cambiado: lo que hay en disco habla de
        # una versión que ya no existe, así que no se continúa. Sin commit
        # (fuente local sin git) tampoco hay nada con qué compararlo.
        if si_cambio == "error" and (commit is None or inicio.get("commit") != commit):
            viejo, nuevo = (inicio.get("commit") or "?")[:7], (commit or "?")[:7]
            raise RepoCambiado(f"el repo ha cambiado desde que se paró ({viejo} → {nuevo}): lanza uno nuevo")
        if commit is not None and inicio.get("commit") == commit:
            fin = await _reanudar(reanudar, lanzar, tope_usd, max_vueltas)
            coste = round(fin["coste_total_usd"] - _coste_previo(reanudar), 6)
            es_falso = bool((inicio.get("params") or {}).get("falso", falso))
            nota = _escribir_nota(f, commit, reanudar, fin, coste, falso=es_falso,
                                  raiz_notas=raiz_notas, ahora=ahora)
            return Lectura(fuente=f.texto, nombre=f.nombre, commit=commit, run=fin["run"],
                           salida=reanudar, motivo=fin["motivo"], vueltas=fin["vueltas"],
                           coste_usd=coste, nota=nota, continuado=True)

    fin = await orquestar(
        ruta, salidas, lanzar, tope_usd=tope_usd, max_vueltas=2 if max_vueltas is None else max_vueltas,
        run=run, falso=falso, fuente=f.texto, commit=commit,
    )
    salida = salidas / ruta.name / fin["run"]
    coste = fin["coste_total_usd"]
    nota = _escribir_nota(f, commit, salida, fin, coste, falso=falso, raiz_notas=raiz_notas, ahora=ahora)
    return Lectura(fuente=f.texto, nombre=f.nombre, commit=commit, run=fin["run"], salida=salida,
                   motivo=fin["motivo"], vueltas=fin["vueltas"], coste_usd=coste, nota=nota)


async def _reanudar(salida: Path, lanzar: Lanzar, tope_usd: float, max_vueltas: int | None) -> dict:
    return await reanudar(salida, lanzar, tope_usd=tope_usd, max_vueltas=max_vueltas)


def _coste_previo(salida: Path) -> float:
    """Lo gastado antes de la última continuación: `run_fin.coste_total_usd` de
    una continuación lo incluye (D24), y el techo de la noche (D30) cuenta solo
    lo de esta lectura."""
    ultimo = [e for e in _eventos(salida) if e.get("tipo") == "reanudado"][-1]
    return ultimo.get("coste_previo_usd") or 0.0


def _runs_de(salidas: Path, fuente: str) -> list[tuple[str, Path, dict, dict]]:
    """`(t del run_inicio, carpeta, run_inicio, última línea)` de cada run de `fuente`."""
    runs = []
    for ruta in salidas.glob("*/*/eventos.jsonl"):
        try:
            eventos = _eventos(ruta.parent)
            inicio = _run_inicio(eventos)
        except (OSError, ValueError, StopIteration):
            continue  # un eventos.jsonl corrupto no tumba la búsqueda
        if inicio.get("fuente") == fuente:
            runs.append((inicio.get("t", ""), ruta.parent, inicio, eventos[-1]))
    return runs


def _ultimo_acabado(salidas: Path, fuente: str) -> dict | None:
    """El `run_inicio` del run más reciente de `fuente` que acabó (`FINALES`).
    Los `--falso` no cuentan: una demo no puede hacer que se salte una lectura
    real del mismo commit."""
    acabados = [
        r for r in _runs_de(salidas, fuente)
        if r[3].get("tipo") == "run_fin" and r[3].get("motivo") in FINALES
        and not (r[2].get("params") or {}).get("falso")
    ]
    return max(acabados, key=lambda r: r[0])[2] if acabados else None


def ultimo_parado(salidas: Path, fuente: str, *, falso: bool = False) -> Path | None:
    """El run más reciente de `fuente` **del modo `falso`**, si terminó en un
    `run_fin` con un motivo no final. Aprobado, `tope_vueltas`, sin `run_fin`
    (muerto o en marcha) o sin runs: `None`.

    El modo se filtra aquí y no después (R4 de la revisión de H3): una demo
    `--falso` posterior no debe tapar un run real parado, ni al revés."""
    candidatos = [r for r in _runs_de(salidas, fuente) if bool((r[2].get("params") or {}).get("falso")) == falso]
    if not candidatos:
        return None
    _, salida, _, ultimo = max(candidatos, key=lambda c: c[0])
    if ultimo.get("tipo") == "run_fin" and ultimo.get("motivo") not in FINALES:
        return salida
    return None


def _crear_analizador() -> argparse.ArgumentParser:
    a = argparse.ArgumentParser(prog="python -m enjambre.leer")
    a.add_argument("fuente", nargs="?", default=None, help="URL de GitHub o ruta bajo /data")
    a.add_argument("--reanudar", type=Path, default=None)
    a.add_argument("--tope-usd", type=float, default=5.0)
    a.add_argument("--max-vueltas", type=int, default=None)
    a.add_argument("--run", default=None)
    a.add_argument("--salidas", type=Path, default=Path(__file__).resolve().parent.parent / "salidas")
    a.add_argument("--falso", action="store_true")
    a.add_argument("--cerrojo", type=Path, default=None)  # None = cerrojo.RUTA, leído al ejecutar
    a.add_argument("--sin-aviso", action="store_true")
    return a


def _elegir_lanzar(falso: bool) -> Lanzar:
    if falso:
        from enjambre.falso import hacer_lanzar_falso

        return hacer_lanzar_falso(retardo_s=0.5)
    # D6: solo `lanzador.py` importa el SDK, y solo cuando de verdad hace falta.
    from enjambre.lanzador import lanzar

    return lanzar


def _falso_del_run(salida: Path) -> bool | None:
    try:
        params = _run_inicio(_eventos(salida)).get("params") or {}
    except (OSError, ValueError, StopIteration):
        return None
    return params.get("falso")


async def _continuar_sin_fuente(args, falso: bool) -> int:
    """Un run anterior a esta fase (sin `fuente`): se continúa como antes de
    ella, sin actualizar, sin nota y sin aviso."""
    fin = await reanudar(args.reanudar, _elegir_lanzar(falso), tope_usd=args.tope_usd, max_vueltas=args.max_vueltas)
    print(f"{fin['run']} {fin['motivo']} {fin['vueltas']} {fin['coste_total_usd']} {args.reanudar}")
    return {"aprobado": 0, "interrumpido": 130}.get(fin["motivo"], 1)


async def _main_async(args) -> int:
    falso = args.falso
    texto = args.fuente
    if args.reanudar is not None:
        es_falso = _falso_del_run(args.reanudar)
        if es_falso is None:
            print(f"--reanudar {args.reanudar}: no tiene params.falso (run anterior a D24) -- "
                  "no se puede saber si era real o --falso", file=sys.stderr)
            return 2
        falso = es_falso  # el modo lo fija el run, no quien continúa (D24)
        if texto is None:
            texto = _run_inicio(_eventos(args.reanudar)).get("fuente")
            if texto is None:
                return await _continuar_sin_fuente(args, falso)
    if texto is None:
        print("falta la fuente (o --reanudar <salida>)", file=sys.stderr)
        return 2

    f = resolver(texto)
    lectura = await leer(
        f, salidas=args.salidas, lanzar=_elegir_lanzar(falso), tope_usd=args.tope_usd,
        max_vueltas=args.max_vueltas,
        run=args.run, falso=falso, reanudar=args.reanudar,
        # D36: "Continuar" (la página) no lanza un run nuevo si el repo cambió.
        si_cambio="error" if args.reanudar else "nuevo",
    )
    print(f"{lectura.run} {lectura.motivo} {lectura.vueltas} {lectura.coste_usd} {lectura.salida}")
    mensaje = aviso.texto_run(lectura)
    if falso:
        print(mensaje)  # la demo no manda Telegram
    elif not args.sin_aviso:
        aviso.enviar(mensaje)
    if lectura.motivo == "interrumpido":
        return 130
    return 0 if lectura.nota is not None else 1


def main(argv: list[str] | None = None) -> int:
    args = _crear_analizador().parse_args(argv)
    # D31: el cerrojo cubre la lectura entera, también la clonación.
    try:
        with cerrojo.tomar(args.cerrojo):
            return asyncio.run(_main_async(args))
    except cerrojo.Ocupado:
        print("hay otro run en marcha", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("interrumpido")
        return 130
    except (FuenteInvalida, CopiaAjena, GitFallo, NotaAjena, ValueError) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
