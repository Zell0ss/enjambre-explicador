"""
El muro de permisos del enjambre (D8): decide si un rol puede leer o escribir
una ruta dada.

`permitido()` es una función pura: la única E/S que hace es `Path.resolve()`,
necesaria para que `..` y los symlinks no salten el muro — resolver antes de
comparar es lo que impide que una ruta relativa o un enlace dentro de `salida`
escapen hacia fuera (D8, foco de revisión §"Escapar del muro").

Se usa como hook `PreToolUse` del Agent SDK (tarea 7): por cada llamada a una
tool se calcula su ruta con `ruta_de()` y se consulta `permitido()` antes de
dejarla pasar.

Tabla de permisos (spec §3.3):

- cartografo, despiezador, lector-de-pieza, trazador, verificador:
  leer repo y salida; escribir solo salida.
- redactor: leer y escribir solo salida.
- novato: leer solo salida/articulo.md; escribir solo salida/dudas.md
  (en ambos casos, igualdad exacta de ruta resuelta, no "estar bajo").

Glob/Grep sin ruta explícita (`ruta=None`) se evalúan sobre `cwd` (= `salida`).
Una herramienta que no está en la tabla (p.ej. `Bash`) se deniega siempre.
"""

from pathlib import Path

# Tools de lectura y de escritura (spec §3.3). Cualquier otra tool se deniega.
LECTURAS = frozenset({"Read", "Glob", "Grep"})
ESCRITURAS = frozenset({"Write", "Edit"})

# Campo de la entrada de la tool donde viene la ruta.
_CAMPO_RUTA = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Glob": "path",
    "Grep": "path",
}

# Regla de muro por rol: "ambos" = repo o salida; "salida" = solo salida;
# "exacto" = igualdad exacta con un fichero concreto de salida (solo novato).
MURO: dict[str, tuple[str, str]] = {
    # (regla de lectura, regla de escritura)
    "cartografo": ("ambos", "salida"),
    "despiezador": ("ambos", "salida"),
    "lector-de-pieza": ("ambos", "salida"),
    "trazador": ("ambos", "salida"),
    "verificador": ("ambos", "salida"),
    "redactor": ("salida", "salida"),
    "novato": ("exacto", "exacto"),
}

# Los únicos ficheros exactos que puede tocar el novato (relativos a salida).
NOVATO_LEER = "articulo.md"
NOVATO_ESCRIBIR = "dudas.md"


def ruta_de(herramienta: str, entrada: dict) -> str | None:
    """Saca la ruta de la entrada de una tool, o None si no aplica/falta."""
    campo = _CAMPO_RUTA.get(herramienta)
    if campo is None:
        return None
    return entrada.get(campo)


def permitido(
    rol: str, herramienta: str, ruta: str | None, repo: Path, salida: Path
) -> tuple[bool, str]:
    """
    Decide si `rol` puede usar `herramienta` sobre `ruta`.

    `ruta=None` (Glob/Grep sin ruta explícita) se evalúa sobre `salida`, que
    es el cwd del agente. Las rutas relativas se resuelven contra `salida`.
    Siempre se resuelve (`Path.resolve()`) antes de comparar con
    `is_relative_to`, para que `..` y los symlinks no se salten el muro.

    Devuelve (ok, motivo); motivo es una frase corta en español, vacía si ok.
    """
    if herramienta in LECTURAS:
        categoria = "leer"
    elif herramienta in ESCRITURAS:
        categoria = "escribir"
    else:
        return False, f"herramienta '{herramienta}' fuera de la tabla de permisos"

    regla_lectura, regla_escritura = MURO.get(rol, (None, None))
    regla = regla_lectura if categoria == "leer" else regla_escritura
    if regla is None:
        return False, f"rol '{rol}' desconocido"

    # Ruta efectiva: sin ruta explícita, se evalúa el cwd (= salida).
    objetivo = Path(ruta) if ruta is not None else salida
    if not objetivo.is_absolute():
        objetivo = salida / objetivo

    resuelta = objetivo.resolve()
    repo_r = repo.resolve()
    salida_r = salida.resolve()

    if regla == "exacto":
        nombre = NOVATO_LEER if categoria == "leer" else NOVATO_ESCRIBIR
        permitido_ok = resuelta == (salida_r / nombre).resolve()
    elif regla == "salida":
        permitido_ok = resuelta.is_relative_to(salida_r)
    elif regla == "ambos":
        permitido_ok = resuelta.is_relative_to(repo_r) or resuelta.is_relative_to(salida_r)
    else:  # pragma: no cover - defensivo, MURO no produce otros valores
        permitido_ok = False

    if permitido_ok:
        return True, ""
    return False, f"ruta fuera del muro permitido para '{rol}'"
