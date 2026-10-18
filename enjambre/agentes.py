"""
Carga y parsea los agentes del enjambre desde .claude/agents/<rol>.md.

Cada archivo tiene un frontmatter YAML-like y un cuerpo (el prompt).
No usamos PyYAML; parseamos a mano.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path


DIR_AGENTES = Path(__file__).parent.parent / ".claude" / "agents"


@dataclass(frozen=True)
class Agente:
    """Descripción de un agente del enjambre."""
    rol: str
    modelo: str  # "haiku" o "sonnet"
    tools: list[str]  # p.ej. ["Read", "Glob", "Grep", "Write"]
    prompt: str  # cuerpo tras el frontmatter, sin espacios iniciales


ROLES: tuple[str, ...] = (
    "cartografo",
    "despiezador",
    "lector-de-pieza",
    "trazador",
    "redactor",
    "verificador",
    "novato",
)


# D43: el orden de los prompts, el mismo con el que se numeran sus copias de lectura (01..07).
ORDEN = ROLES


def aviso_copia(rol: str) -> str:
    return (f"> [!note] Copia de lectura. El original está en el repo: `.claude/agents/{rol}.md`. "
            "Si la editas aquí, la próxima copia la pisa.")


def copiar_a(destino: Path, dir_agentes: Path | None = None) -> list[Path]:
    """D43: escribe `destino/<NN>-<rol>.md`, una copia de lectura de cada prompt: el
    original con `aviso_copia` justo después del `---` que cierra el frontmatter.

    El repo es el original y el vault (u otro sitio) solo tiene copias; el código no
    sabe dónde está el vault: `destino` lo da quien lo lanza. Escritura atómica (un
    temporal en la misma carpeta y `os.replace`), porque Syncthing puede leer a medias.
    `destino` tiene que existir (`FileNotFoundError`)."""
    dir_agentes = dir_agentes or DIR_AGENTES
    if not destino.is_dir():
        raise FileNotFoundError(f"no existe la carpeta de destino: {destino}")
    escritas = []
    for n, rol in enumerate(ORDEN, 1):
        original = (dir_agentes / f"{rol}.md").read_text(encoding="utf-8")
        if not original.startswith("---\n") or "\n---\n" not in original[3:]:
            raise ValueError(f"{rol}.md no tiene un frontmatter cerrado")
        cierre = original.index("\n---\n", 3) + len("\n---\n")
        copia = original[:cierre] + aviso_copia(rol) + "\n\n" + original[cierre:]
        ruta = destino / f"{n:02d}-{rol}.md"
        tmp = destino / f".{ruta.name}.{os.getpid()}.tmp"
        try:
            tmp.write_text(copia, encoding="utf-8")
            os.replace(tmp, ruta)
        finally:
            tmp.unlink(missing_ok=True)
        escritas.append(ruta)
    return escritas


def main(argv: list[str] | None = None) -> int:
    """`python -m enjambre.agentes --copiar-a <carpeta>` (lo lanza el arquitecto, D43)."""
    a = argparse.ArgumentParser(prog="python -m enjambre.agentes")
    a.add_argument("--copiar-a", type=Path, required=True, metavar="CARPETA")
    args = a.parse_args(argv)
    try:
        for ruta in copiar_a(args.copiar_a):
            print(ruta)
    except (FileNotFoundError, ValueError) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return 0


def cargar(rol: str, dir_agentes: Path = DIR_AGENTES) -> Agente:
    """
    Carga y parsea un agente por su rol.

    Args:
        rol: nombre del rol (p.ej. "cartografo")
        dir_agentes: directorio donde buscar los archivos .md

    Returns:
        Agente parseado

    Raises:
        FileNotFoundError: si el archivo del rol no existe
        ValueError: si falta el frontmatter o faltan campos obligatorios
    """
    # Construir la ruta del archivo (D43: son ficheros del repo, ya no enlaces al vault)
    archivo = dir_agentes / f"{rol}.md"

    try:
        contenido = archivo.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"No existe agente '{rol}' en {dir_agentes}")

    # Parsear el frontmatter
    # Debe empezar con "---\n"
    if not contenido.startswith("---\n"):
        raise ValueError(f"Frontmatter ausente en {archivo}: debe empezar con '---'")

    # Buscar el segundo "---\n" que cierra el frontmatter
    lines = contenido.split("\n")
    if lines[0] != "---":
        raise ValueError(f"Frontmatter mal formado en {archivo}")

    # Encontrar la línea de cierre del frontmatter
    cierre_idx = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            cierre_idx = i
            break

    if cierre_idx is None:
        raise ValueError(f"Frontmatter no cerrado en {archivo}")

    # Parsear las líneas del frontmatter (entre los dos "---")
    frontmatter_lines = lines[1:cierre_idx]
    fm_dict = {}

    for linea in frontmatter_lines:
        linea = linea.strip()
        if not linea:
            continue
        # Partir por el primer ":"
        if ":" not in linea:
            continue
        clave, valor = linea.split(":", 1)
        clave = clave.strip()
        valor = valor.strip()
        fm_dict[clave] = valor

    # Validar campos obligatorios
    if "model" not in fm_dict:
        raise ValueError(f"Campo 'model' faltante en {archivo}")
    if "tools" not in fm_dict:
        raise ValueError(f"Campo 'tools' faltante en {archivo}")

    # Parsear 'tools': es una cadena separada por comas, con espacios posibles
    tools_str = fm_dict["tools"]
    tools_list = [t.strip() for t in tools_str.split(",")]

    # El prompt es todo después del cierre del frontmatter (línea cierre_idx + 1 en adelante)
    # Saltamos la línea vacía que suele venir después de "---"
    prompt_lines = lines[cierre_idx + 1:]

    # Eliminar espacios en blanco al inicio y final del prompt
    # pero mantener la estructura interna
    prompt_text = "\n".join(prompt_lines).strip()

    return Agente(
        rol=rol,
        modelo=fm_dict["model"],
        tools=tools_list,
        prompt=prompt_text,
    )


if __name__ == "__main__":
    sys.exit(main())
