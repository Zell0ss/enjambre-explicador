"""
Del run acabado a la nota del vault (D28).

Es el único código del enjambre que escribe en el vault, y solo dentro de
`Clippings/repo-articles/` (contrato del vault, §5). Una nota por repo,
sobrescrita en cada lectura; el historial queda en `salidas/` (D7).

La escritura es atómica (temporal en la misma carpeta y `os.replace`) porque
Syncthing puede leer el fichero mientras se escribe.
"""

import json
import os
from datetime import datetime
from pathlib import Path

RAIZ_NOTAS = Path("/data/library/mi-wiki/docs/Obsidian/Clippings/repo-articles")

# Un run parado (tope de coste, interrumpido, fallo) no deja nota: el artículo
# a medias no es el resultado (D28).
FINALES = frozenset({"aprobado", "tope_vueltas"})

_CLAVES = ("fuente", "commit", "leido", "run", "coste_usd", "veredicto", "generado_por")


class NotaAjena(RuntimeError):
    """Ya hay una nota con ese nombre y no es de esta fuente ni la escribió el enjambre."""


def _veredicto(motivo: str, vueltas: int) -> str:
    return "aprobado" if motivo == "aprobado" else f"sin aprobar tras {vueltas} vueltas"


def leer_frontmatter(ruta: Path) -> dict | None:
    """Lee lo que escribe `escribir`: `clave: <JSON>`, una por línea entre dos
    `---`. `None` si no existe el fichero o no empieza con ese bloque (una nota
    humana, por ejemplo)."""
    try:
        lineas = ruta.read_text(encoding="utf-8").split("\n")
    except OSError:
        return None
    if not lineas or lineas[0] != "---":
        return None
    datos = {}
    for linea in lineas[1:]:
        if linea == "---":
            return datos
        clave, sep, valor = linea.partition(": ")
        if not sep:
            return None
        try:
            datos[clave] = json.loads(valor)
        except json.JSONDecodeError:
            return None
    return None  # sin cierre


def escribir(
    raiz: Path,
    *,
    fuente: str,
    nombre: str,
    commit: str | None,
    run: str,
    coste_usd: float,
    motivo: str,
    vueltas: int,
    articulo: str,
    leido: datetime,
    fichero: str | None = None,
) -> Path:
    """Escribe `raiz/<nombre>.md` (o `raiz/<fichero>`) y devuelve su ruta.

    `fichero` existe para `--falso`: la demo escribe `nota.md` en la salida del
    run, nunca en el vault. Lanza `ValueError` si el run no acabó (D28) y
    `NotaAjena` si el destino ya existe y no es una nota de esta fuente.
    """
    if motivo not in FINALES:
        raise ValueError(f"un run con motivo {motivo!r} no deja nota (D28)")
    nombre_fichero = fichero or f"{nombre}.md"
    if Path(nombre_fichero).name != nombre_fichero or nombre_fichero.startswith("."):
        raise ValueError(f"nombre de nota no válido: {nombre_fichero!r}")

    destino = raiz / nombre_fichero
    if destino.exists():
        previa = leer_frontmatter(destino)
        if previa is None or previa.get("generado_por") != "enjambre" or previa.get("fuente") != fuente:
            raise NotaAjena(f"{destino} ya existe y no es una nota de {fuente}")

    valores = {
        "fuente": fuente,
        "commit": commit,
        "leido": leido.isoformat(timespec="minutes"),
        "run": run,
        "coste_usd": round(coste_usd, 2),
        "veredicto": _veredicto(motivo, vueltas),
        "generado_por": "enjambre",
    }
    cabecera = "".join(f"{k}: {json.dumps(valores[k], ensure_ascii=False)}\n" for k in _CLAVES)
    texto = f"---\n{cabecera}---\n{articulo}"

    raiz.mkdir(parents=True, exist_ok=True)
    tmp = raiz / f".{nombre_fichero}.{os.getpid()}.tmp"
    try:
        tmp.write_text(texto, encoding="utf-8")
        os.replace(tmp, destino)
    finally:
        tmp.unlink(missing_ok=True)
    return destino
