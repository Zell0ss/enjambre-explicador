from pathlib import Path

import pytest

from enjambre.guardia import permitido, ruta_de


@pytest.fixture
def dirs(tmp_path: Path):
    repo = tmp_path / "agora"
    salida = tmp_path / "salidas" / "agora" / "run1"
    (repo / "backend").mkdir(parents=True)
    (repo / "backend" / "main.py").write_text("x")
    (salida / "fichas").mkdir(parents=True)
    (salida / "articulo.md").write_text("x")
    return repo, salida


CASOS = [
    # rol, herramienta, ruta (None = sin ruta; "R:" = relativa al repo; "S:" = relativa a salida; "/..." absoluta), esperado
    ("cartografo", "Read", "R:backend/main.py", True),
    ("cartografo", "Grep", "R:", True),
    ("cartografo", "Write", "S:mapa.md", True),
    ("cartografo", "Write", "R:backend/main.py", False),
    ("lector-de-pieza", "Read", "S:piezas.md", True),
    ("lector-de-pieza", "Write", "S:fichas/x.md", True),
    ("trazador", "Read", "R:backend/main.py", True),
    ("verificador", "Read", "R:backend/main.py", True),
    ("verificador", "Read", "S:fichas/x.md", True),   # el prompt se lo prohíbe; el muro no (D2 solo restringe redactor y novato)
    ("redactor", "Read", "S:fichas/x.md", True),
    ("redactor", "Read", "R:backend/main.py", False),
    ("redactor", "Glob", None, True),
    ("redactor", "Edit", "S:articulo.md", True),
    ("novato", "Read", "S:articulo.md", True),
    ("novato", "Read", "articulo.md", True),          # relativa al cwd = salida
    ("novato", "Read", "S:fichas/x.md", False),
    ("novato", "Read", "S:piezas.md", False),
    ("novato", "Glob", None, False),
    ("novato", "Write", "S:dudas.md", True),
    ("novato", "Write", "S:articulo.md", False),
    ("novato", "Read", "R:backend/main.py", False),
    ("cartografo", "Bash", "R:", False),               # herramienta fuera de la tabla
    ("cartografo", "Read", "/etc/passwd", False),
    ("cartografo", "Read", "S:../../../../etc/passwd", False),
    ("redactor", "Read", "S:fichas/../../../../agora/backend/main.py", False),
]


def _ruta(valor, repo, salida):
    if valor is None:
        return None
    if valor.startswith("R:"):
        return str(repo / valor[2:])
    if valor.startswith("S:"):
        return str(salida / valor[2:])
    return valor


@pytest.mark.parametrize("rol,herramienta,ruta,esperado", CASOS)
def test_tabla_del_guardia(dirs, rol, herramienta, ruta, esperado):
    repo, salida = dirs
    ok, motivo = permitido(rol, herramienta, _ruta(ruta, repo, salida), repo, salida)
    assert ok is esperado
    assert (motivo == "") is esperado


def test_symlink_en_salida_hacia_el_repo_no_escapa(dirs):
    repo, salida = dirs
    (salida / "atajo").symlink_to(repo)
    ok, _ = permitido("redactor", "Read", str(salida / "atajo" / "backend" / "main.py"), repo, salida)
    assert ok is False


def test_ruta_de():
    assert ruta_de("Read", {"file_path": "/a/b"}) == "/a/b"
    assert ruta_de("Write", {"file_path": "x.md", "content": "."}) == "x.md"
    assert ruta_de("Grep", {"pattern": "def ", "path": "/a"}) == "/a"
    assert ruta_de("Grep", {"pattern": "def "}) is None
    assert ruta_de("Glob", {"pattern": "**/*.py"}) is None
