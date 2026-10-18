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
import re
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

from enjambre import aviso, cerrojo
from enjambre.fuente import CopiaAjena, FuenteInvalida, GitFallo, resolver
from enjambre.nota import FINALES, NotaAjena
from enjambre.registro import obtener_log

# parent = enjambre/, parent.parent = raíz del repo.
RAIZ_COLA = Path(__file__).resolve().parent.parent / "cola"

_HECHOS = FINALES | {"sin_cambios"}

# Lo único que es "un problema de ese repo": la noche sigue con el siguiente.
# Cualquier otra excepción (SDK roto, disco lleno...) no es del repo, y seguir
# solo gastaría un intento de cada petición (R5 de la revisión de H3).
_DEL_REPO = (FuenteInvalida, CopiaAjena, GitFallo, NotaAjena)


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


def _con_id(carpeta: Path) -> list[dict]:
    # D42: `id` (el nombre del fichero sin `.json`) lo añade la lectura y NUNCA se escribe en el
    # JSON: es el nombre del fichero, y un id guardado dentro podría discrepar de él.
    return [{**d, "id": ruta.stem} for ruta, d in _listar(carpeta)]


# Lo que `encolar` pone en el nombre: AAAAMMDD-HHMMSS-<nombre en minúsculas, D37>[-n].
_ID = re.compile(r"\d{8}-\d{6}-[a-z0-9._-]+")


def pendientes(raiz_cola: Path | None = None) -> list[dict]:
    return _con_id((raiz_cola or RAIZ_COLA) / "pendientes")


def fallidas(raiz_cola: Path | None = None) -> list[dict]:
    return _con_id((raiz_cola or RAIZ_COLA) / "fallidas")


def retirar(id: str, *, raiz_cola: Path | None = None, ahora=datetime.now) -> bool:
    """D42: saca una petición (pendiente o fallida) de la cola, a `retiradas/`. No se
    borra nada: se conservan el historial y el coste. `True` si estaba, `False` si no;
    `ValueError` si `id` no tiene la forma de un nombre de la cola (nunca llega a tocar
    el disco con una ruta que venga de fuera)."""
    if not isinstance(id, str) or not _ID.fullmatch(id):
        raise ValueError(f"id de petición no válido: {id!r}")
    raiz_cola = raiz_cola or RAIZ_COLA
    for carpeta in ("pendientes", "fallidas"):
        ruta = raiz_cola / carpeta / f"{id}.json"
        if not ruta.is_file():
            continue
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            datos.setdefault("historial", []).append({"t": f"{ahora():%Y-%m-%dT%H:%M:%S}", "motivo": "retirada"})
            _escribir(ruta, datos)
        except (OSError, ValueError):
            pass  # ilegible: se mueve igual, sin entrada nueva
        try:
            _mover(ruta, raiz_cola / "retiradas")
        except FileNotFoundError:
            return False  # se la llevó otro (la noche, otro "Sacar") entre medias
        return True
    return False


def encolar(
    texto: str, *, raiz_cola: Path | None = None, ahora=datetime.now, **resolver_kw
) -> tuple[Path, bool]:
    """Devuelve `(ruta, nuevo)`. Una fuente ya pendiente no se duplica. Lanza
    `FuenteInvalida` (sin tocar `git` ni la red: `resolver` es pura)."""
    raiz_cola = raiz_cola or RAIZ_COLA
    f = resolver(texto, **resolver_kw)
    for ruta, pet in _listar(raiz_cola / "pendientes"):
        # Sin distinguir mayúsculas: GitHub tampoco las distingue, y `.../Repo`
        # y `.../repo` son el mismo repo (dos copias en disco y dos notas).
        if str(pet.get("fuente", "")).lower() == f.texto.lower():
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
    *, raiz_cola: Path | None = None, leer_fn, techo_usd: float = 10.0, tope_run_usd: float = 5.0,
    minimo_usd: float = 1.0, max_intentos: int = 3, hasta: time = time(7, 0),
    dormir=asyncio.sleep, ahora=datetime.now,
) -> dict:
    """`leer_fn(fuente_texto, tope_usd) -> Lectura` (async). Devuelve
    `{"lecturas", "errores", "gastado_usd", "quedan", "parada", "esperado_a"}`.

    D39: si una lectura para por el límite de sesión y su aviso dice cuándo se
    renueva (`Lectura.reintentar_a`), la cola espera a esa hora más un minuto y
    vuelve a leer la misma petición (que continúa el run, D24). Una sola vez por
    noche, y solo si la espera acaba antes de `hasta` (la mañana de Josem). La
    segunda lectura no suma otro intento: el de esa noche cubre las dos."""
    raiz_cola = raiz_cola or RAIZ_COLA
    lecturas, errores, gastado, parada = [], [], 0.0, None
    esperado_a: datetime | None = None
    inicio = ahora()
    limite = datetime.combine(inicio.date(), hasta)
    if limite <= inicio:
        limite += timedelta(days=1)

    async def intentar(pet: dict, tope: float):
        """Una llamada a `leer_fn`: devuelve `(lectura | None, parada | None, hecha)` y apunta
        su entrada en `historial` y en `errores`/`lecturas`."""
        nonlocal gastado
        intento = {"t": f"{ahora():%Y-%m-%dT%H:%M:%S}"}
        l, para, hecha = None, None, False
        try:
            l = await leer_fn(pet["fuente"], tope)
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
            errores.append((pet["fuente"], error))
            intento.update(error=error, coste_usd=0.0, run=None)
            if not isinstance(e, _DEL_REPO):
                para = f"excepcion:{type(e).__name__}"
                obtener_log().exception(f"cola: excepción no prevista leyendo {pet['fuente']}")
        else:
            # Foco 4: `l.coste_usd` es lo de esta lectura, no lo de la continuación entera.
            gastado += l.coste_usd
            lecturas.append(l)
            intento.update(motivo=l.motivo, coste_usd=l.coste_usd, run=l.run)
            hecha = l.motivo in _HECHOS
            # El límite de uso de la suscripción es lo más probable detrás de un
            # fallo o una interrupción: seguir solo gastaría intentos.
            if not hecha and (l.motivo.startswith(("fallo:", "excepcion:")) or l.motivo == "interrumpido"):
                para = l.motivo
        pet.setdefault("historial", []).append(intento)
        return l, para, hecha

    for ruta, pet in _listar(raiz_cola / "pendientes"):
        # D42: la lista es de cuando empezó la noche; si alguien sacó esta petición
        # desde la página mientras se leían las anteriores, ya no hay que leerla.
        if not ruta.exists():
            continue
        disponible = techo_usd - gastado
        if disponible < minimo_usd:
            parada = "techo"
            break

        pet["intentos"] = pet.get("intentos", 0) + 1
        l, parada, hecha = await intentar(pet, min(tope_run_usd, disponible))

        reintentar_a = getattr(l, "reintentar_a", None)
        if (parada and l is not None and reintentar_a is not None and esperado_a is None
                and reintentar_a + timedelta(seconds=60) < limite
                and techo_usd - gastado >= minimo_usd):
            esperado_a = reintentar_a
            await dormir(max(0.0, (reintentar_a + timedelta(seconds=60) - ahora()).total_seconds()))
            l, parada, hecha = await intentar(pet, min(tope_run_usd, techo_usd - gastado))

        if not ruta.exists():
            # D42: la sacaron durante su lectura. No se recrea (`_escribir` la resucitaría)
            # ni se mueve: ya está en `retiradas/`. El gasto sí cuenta para el techo.
            obtener_log().info(f"cola: {ruta.name} se retiró durante su lectura; no se actualiza")
            if parada:
                break
            continue
        _escribir(ruta, pet)
        try:
            if hecha:
                _mover(ruta, raiz_cola / "hechas")
            elif pet["intentos"] >= max_intentos:
                _mover(ruta, raiz_cola / "fallidas")
        except FileNotFoundError:  # la sacaron justo entre la comprobación y el movimiento
            obtener_log().info(f"cola: {ruta.name} se retiró justo al acabar; no se mueve")
        if parada:
            break

    return {"lecturas": lecturas, "errores": errores, "gastado_usd": round(gastado, 6),
            "quedan": len(pendientes(raiz_cola)), "parada": parada, "esperado_a": esperado_a}


def _crear_analizador() -> argparse.ArgumentParser:
    a = argparse.ArgumentParser(prog="python -m enjambre.cola")
    a.add_argument("--falso", action="store_true")
    a.add_argument("--cerrojo", type=Path, default=None)  # None = cerrojo.RUTA, leído al ejecutar
    a.add_argument("--techo-usd", type=float, default=10.0)
    a.add_argument("--raiz-cola", type=Path, default=None)  # None = RAIZ_COLA (para pruebas)
    a.add_argument("--salidas", type=Path, default=Path(__file__).resolve().parent.parent / "salidas")
    return a


def _hacer_leer_fn(salidas: Path, falso: bool):
    from enjambre.leer import _elegir_lanzar, leer, ultimo_parado

    lanzar = _elegir_lanzar(falso)

    async def leer_fn(fuente_texto: str, tope_usd: float):
        f = resolver(fuente_texto)
        # Un run real no se continúa con el `lanzar` falso (ni al revés): el
        # modo lo fija el run (D24). Se filtra al buscar, no después, para que
        # una demo posterior no tape un run real parado (R4).
        parado = ultimo_parado(salidas, f.texto, falso=falso)
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
