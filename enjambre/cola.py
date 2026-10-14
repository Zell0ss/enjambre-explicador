"""
La cola y la noche (D29, D30, D35).

Una petición es un JSON en `cola/pendientes/`; al acabar pasa a `hechas/` o,
tras `max_intentos` noches fallando, a `fallidas/`, con un `os.replace` entre
carpetas. Unas pocas peticiones por noche: con ficheros basta, es atómico sin
cerrojos y se depura con `ls`, igual que los runs (D7).

`noche` procesa la cola en serie con un techo de gasto. El cerrojo de máquina
(D31) lo toma `main` para toda la noche: `noche` no sabe nada de él.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from enjambre import aviso, cerrojo
from enjambre.fuente import resolver
from enjambre.nota import FINALES
from enjambre.registro import obtener_log

# parent = enjambre/, parent.parent = raíz del repo.
RAIZ_COLA = Path(__file__).resolve().parent.parent / "cola"

_HECHOS = FINALES | {"sin_cambios"}


def _escribir(ruta: Path, datos: dict) -> None:
    """Atómico: un lector (la pantalla, `ls`, otra noche) nunca ve medio JSON."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(f".{ruta.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, ruta)
    finally:
        tmp.unlink(missing_ok=True)


def _listar(carpeta: Path) -> list[tuple[Path, dict]]:
    """En orden de nombre de fichero (= orden de encolado). Un JSON ilegible se
    salta, no tumba la noche."""
    salida = []
    for ruta in sorted(carpeta.glob("*.json")):
        try:
            salida.append((ruta, json.loads(ruta.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            obtener_log().warning(f"cola: {ruta} ilegible, se ignora")
    return salida


def pendientes(raiz_cola: Path = RAIZ_COLA) -> list[dict]:
    return [d for _, d in _listar(raiz_cola / "pendientes")]


def fallidas(raiz_cola: Path = RAIZ_COLA) -> list[dict]:
    return [d for _, d in _listar(raiz_cola / "fallidas")]


def encolar(
    texto: str, *, raiz_cola: Path = RAIZ_COLA, ahora=datetime.now, **resolver_kw
) -> tuple[Path, bool]:
    """Devuelve `(ruta, nuevo)`. Una fuente ya pendiente no se duplica. Lanza
    `FuenteInvalida` (sin tocar `git` ni la red: `resolver` es pura)."""
    f = resolver(texto, **resolver_kw)
    for ruta, pet in _listar(raiz_cola / "pendientes"):
        if pet.get("fuente") == f.texto:
            return ruta, False
    base = f"{ahora():%Y%m%d-%H%M%S}-{f.nombre}"
    ruta = raiz_cola / "pendientes" / f"{base}.json"
    n = 1
    while ruta.exists():  # mismo segundo y mismo nombre de repo, otro dueño
        n += 1
        ruta = raiz_cola / "pendientes" / f"{base}-{n}.json"
    _escribir(ruta, {"fuente": f.texto, "nombre": f.nombre, "encolado": f"{ahora():%Y-%m-%dT%H:%M:%S}",
                     "intentos": 0, "historial": []})
    return ruta, True


def _mover(ruta: Path, destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    os.replace(ruta, destino / ruta.name)


async def noche(
    *, raiz_cola: Path, leer_fn, techo_usd: float = 10.0, tope_run_usd: float = 5.0,
    minimo_usd: float = 1.0, max_intentos: int = 3, ahora=datetime.now,
) -> dict:
    """`leer_fn(fuente_texto, tope_usd) -> Lectura` (async). Devuelve
    `{"lecturas", "errores", "gastado_usd", "quedan", "parada"}`."""
    lecturas, errores, gastado, parada = [], [], 0.0, None

    for ruta, pet in _listar(raiz_cola / "pendientes"):
        disponible = techo_usd - gastado
        if disponible < minimo_usd:
            parada = "techo"
            break

        intento = {"t": f"{ahora():%Y-%m-%dT%H:%M:%S}"}
        pet["intentos"] = pet.get("intentos", 0) + 1
        hecha = False
        try:
            l = await leer_fn(pet["fuente"], min(tope_run_usd, disponible))
        except Exception as e:  # noqa: BLE001 -- un problema de ESTE repo (privado, copia o nota ajena)
            error = f"{type(e).__name__}: {e}"
            errores.append((pet["fuente"], error))
            intento.update(error=error, coste_usd=0.0, run=None)
        else:
            # Foco 4: `l.coste_usd` es lo de esta lectura, no lo de la continuación entera.
            gastado += l.coste_usd
            lecturas.append(l)
            intento.update(motivo=l.motivo, coste_usd=l.coste_usd, run=l.run)
            hecha = l.motivo in _HECHOS
            # El límite de uso de la suscripción es lo más probable detrás de un
            # fallo o una interrupción: seguir solo gastaría intentos.
            if not hecha and (l.motivo.startswith(("fallo:", "excepcion:")) or l.motivo == "interrumpido"):
                parada = l.motivo
        pet.setdefault("historial", []).append(intento)

        _escribir(ruta, pet)
        if hecha:
            _mover(ruta, raiz_cola / "hechas")
        elif pet["intentos"] >= max_intentos:
            _mover(ruta, raiz_cola / "fallidas")
        if parada:
            break

    return {"lecturas": lecturas, "errores": errores, "gastado_usd": round(gastado, 6),
            "quedan": len(pendientes(raiz_cola)), "parada": parada}


def _crear_analizador() -> argparse.ArgumentParser:
    a = argparse.ArgumentParser(prog="python -m enjambre.cola")
    a.add_argument("--falso", action="store_true")
    a.add_argument("--cerrojo", type=Path, default=None)  # None = cerrojo.RUTA, leído al ejecutar
    a.add_argument("--techo-usd", type=float, default=10.0)
    a.add_argument("--raiz-cola", type=Path, default=None)  # None = RAIZ_COLA (para pruebas)
    a.add_argument("--salidas", type=Path, default=Path(__file__).resolve().parent.parent / "salidas")
    return a


def _hacer_leer_fn(salidas: Path, falso: bool):
    from enjambre.leer import _falso_del_run, _elegir_lanzar, leer, ultimo_parado

    lanzar = _elegir_lanzar(falso)

    async def leer_fn(fuente_texto: str, tope_usd: float):
        f = resolver(fuente_texto)
        parado = ultimo_parado(salidas, f.texto)
        # Un run real no se continúa con el `lanzar` falso (ni al revés): el
        # modo lo fija el run (D24), y mezclarlos escribiría ficheros de pega en
        # uno real o gastaría para seguir una demo.
        if parado is not None and bool(_falso_del_run(parado)) != falso:
            parado = None
        return await leer(f, salidas=salidas, lanzar=lanzar, tope_usd=tope_usd, max_vueltas=None,
                          falso=falso, reanudar=parado, saltar_si_igual=True)

    return leer_fn


def _avisar(texto: str, falso: bool) -> None:
    if falso:
        print(texto)  # la demo no manda Telegram
    else:
        aviso.enviar(texto)


def main(argv: list[str] | None = None) -> int:
    args = _crear_analizador().parse_args(argv)
    raiz_cola = args.raiz_cola or RAIZ_COLA
    if not pendientes(raiz_cola):
        return 0  # nada que hacer, y nada que avisar

    # D31: el cerrojo cubre la noche entera, no cada lectura.
    try:
        with cerrojo.tomar(args.cerrojo):
            resumen = asyncio.run(noche(raiz_cola=raiz_cola, leer_fn=_hacer_leer_fn(args.salidas, args.falso),
                                        techo_usd=args.techo_usd))
    except cerrojo.Ocupado:
        _avisar("enjambre: esta noche no: había otro run en marcha", args.falso)
        return 3
    _avisar(aviso.texto_noche(resumen), args.falso)
    return 1 if resumen["parada"] not in (None, "techo") else 0


if __name__ == "__main__":
    sys.exit(main())
