"""
Carga y parsea los agentes del enjambre desde .claude/agents/<rol>.md.

Cada archivo tiene un frontmatter YAML-like y un cuerpo (el prompt).
No usamos PyYAML; parseamos a mano.
"""

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
    # Construir la ruta del archivo (sigue symlinks)
    archivo = dir_agentes / f"{rol}.md"

    # Si es un symlink, se sigue automáticamente con read_text()
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
