"""Parsers for markdown artifacts (piezas, verificacion, dudas)."""

import re
from typing import Optional


class SalidaIlegible(ValueError):
    """Raised when a markdown artifact contains invalid or unparseable data."""

    pass


def ids_de_piezas(texto: str) -> list[str]:
    """
    Extract and validate IDs from the ## Resumen table in a piezas.md artifact.

    The ## Resumen table must have IDs in the first column that match ^[a-z0-9-]+$.
    Backticks are stripped from IDs. If no valid IDs are found or any ID is invalid,
    raises SalidaIlegible.

    Args:
        texto: The full text of a piezas.md artifact.

    Returns:
        list of valid IDs in table order.

    Raises:
        SalidaIlegible: If no ## Resumen section, no data rows, or any ID fails validation.
    """
    lines = texto.split("\n")

    # Find the ## Resumen section
    resumen_idx = None
    for i, line in enumerate(lines):
        if line.startswith("## Resumen"):
            resumen_idx = i
            break

    if resumen_idx is None:
        raise SalidaIlegible("No '## Resumen' section found")

    # Parse table rows after ## Resumen
    # Skip the header line and separator line, then extract data rows until we hit a non-table line
    ids = []
    i = resumen_idx + 1
    in_header = True

    while i < len(lines):
        line = lines[i]

        # Any line not starting with | terminates the table, including blank lines
        if not line.startswith("|"):
            # End of table
            break

        # Skip header and separator rows
        if "---" in line:
            in_header = False
            i += 1
            continue

        if in_header:
            # This is the header row
            i += 1
            continue

        # This is a data row; extract the first cell (ID)
        cells = line.split("|")
        if len(cells) < 2:
            i += 1
            continue

        id_cell = cells[1].strip()

        # Remove backticks
        id_cell = id_cell.replace("`", "").strip()

        # Validate ID against regex
        if not re.fullmatch(r"[a-z0-9-]+", id_cell):
            raise SalidaIlegible(f"Invalid ID format: '{id_cell}'")

        if id_cell:  # Only add non-empty IDs
            ids.append(id_cell)

        i += 1

    if not ids:
        raise SalidaIlegible("No valid IDs found in '## Resumen' table")

    return ids


def fallos(texto: str) -> Optional[int]:
    """
    Extract the number of failures from a verificacion.md artifact.

    Looks for "Fallos:" or "**Fallos:**" followed by a number.

    Args:
        texto: The full text of a verificacion.md artifact.

    Returns:
        The integer count of failures, or None if not found.
    """
    match = re.search(r"Fallos:?\**:?\s*(\d+)", texto)
    if match:
        return int(match.group(1))
    return None


def veredicto(texto: str) -> Optional[str]:
    """
    Extract and validate the verdict from a dudas.md artifact.

    The verdict is the first non-empty line after the ## Veredicto section.
    Backticks and whitespace are stripped. The value is returned only if it matches
    one of the valid verdicts ("listo" or "necesita otra vuelta"), otherwise None.

    Args:
        texto: The full text of a dudas.md artifact.

    Returns:
        The valid verdict string, or None if not found or invalid.
    """
    lines = texto.split("\n")

    # Find the ## Veredicto section
    veredicto_idx = None
    for i, line in enumerate(lines):
        if line.startswith("## Veredicto"):
            veredicto_idx = i
            break

    if veredicto_idx is None:
        return None

    # Get the first non-empty line after ## Veredicto
    for i in range(veredicto_idx + 1, len(lines)):
        line = lines[i].strip()

        if not line:
            # Skip empty lines
            continue

        # Remove backticks
        value = line.replace("`", "").strip()

        # Check if it's a valid verdict
        if value in ("listo", "necesita otra vuelta"):
            return value

        # If it's not a valid verdict, return None
        return None

    return None
