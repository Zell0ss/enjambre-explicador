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


# --- Regresión tras revisión de la tarea 3 (no normativos del brief original) ---
#
# El revisor encontró dos huecos adversariales reales:
# 1. "~" sin expandir cae bajo `salida` literalmente (es el directorio
#    "salida/~/...") y se aprobaba; si la tool real que toca disco expande
#    "~" a $HOME antes de escribir/leer, el guardia estaría juzgando una
#    ruta distinta de la que se usa de verdad.
# 2. Entradas malformadas (byte nulo, bucle de symlinks, tipos inesperados)
#    hacían que `permitido()`/`ruta_de()` lanzaran una excepción en vez de
#    denegar — inaceptable en un hook `PreToolUse` (tarea 7), donde eso
#    tiraría el run entero en vez de bloquear una sola tool call.
CASOS_REGRESION = [
    # "~" sin resolver: ni al principio ni como segmento intermedio.
    ("redactor", "Read", "~/.ssh/id_rsa", False),
    ("cartografo", "Read", "R:~/x", False),
    # byte nulo: Path.resolve() lanza ValueError si no se captura.
    ("cartografo", "Read", "/tmp/x\x00y", False),
]


@pytest.mark.parametrize("rol,herramienta,ruta,esperado", CASOS_REGRESION)
def test_tabla_del_guardia_regresion(dirs, rol, herramienta, ruta, esperado):
    repo, salida = dirs
    ok, motivo = permitido(rol, herramienta, _ruta(ruta, repo, salida), repo, salida)
    assert ok is esperado
    assert (motivo == "") is esperado


def test_symlink_en_bucle_no_rompe_el_guardia(dirs):
    repo, salida = dirs
    bucle = salida / "bucle"
    bucle.symlink_to(bucle)  # symlink a sí mismo: resolve() falla (ELOOP)
    ok, motivo = permitido("redactor", "Read", str(bucle), repo, salida)
    assert ok is False
    assert motivo != ""


def test_ruta_de_valor_no_string_es_none():
    assert ruta_de("Read", {"file_path": 123}) is None
    assert ruta_de("Write", {"file_path": None}) is None


# --- Parche de seguimiento a la tarea 3: eventos.jsonl/vueltas de solo
# lectura, y forma del pattern de Glob (independiente de ruta_de()/hooks) ---

CASOS_SOLO_LECTURA = [
    # rol con escritura normalmente abierta a toda `salida` (cartografo) o
    # con regla "exacto" estrecha (novato): ambos deniegan sobre
    # eventos.jsonl/vueltas, aunque su tabla normal lo permitiría.
    ("cartografo", "Write", "S:eventos.jsonl", False),
    ("cartografo", "Write", "S:vueltas/1/verificacion.md", False),
    ("cartografo", "Edit", "S:vueltas/2/dudas.md", False),
    # otro rol con escritura abierta a toda `salida` (no solo cartografo).
    ("redactor", "Write", "S:eventos.jsonl", False),
    ("redactor", "Edit", "S:vueltas/1/verificacion.md", False),
    # no regresión: el resto de salida sigue escribible para cartografo.
    ("cartografo", "Write", "S:mapa.md", True),
    # no regresión: un directorio hermano cuyo nombre empieza igual que
    # "vueltas" no debe caer en la denegación por un bug de prefijo de
    # string en vez de "estar bajo" real (is_relative_to compara por
    # partes de ruta, no por prefijo de texto).
    ("cartografo", "Write", "S:vueltas_evil/foo.md", True),
    # novato: dudas.md (su único fichero de escritura) no está bajo
    # vueltas/ ni es eventos.jsonl, así que su permiso normal no se toca.
    ("novato", "Write", "S:dudas.md", True),
    # novato ya estaba denegado aquí por su regla "exacto" (no es dudas.md);
    # se comprueba igualmente para que la nueva regla no dependa de eso.
    ("novato", "Write", "S:vueltas/1/x.md", False),
]


@pytest.mark.parametrize("rol,herramienta,ruta,esperado", CASOS_SOLO_LECTURA)
def test_eventos_y_vueltas_son_de_solo_lectura(dirs, rol, herramienta, ruta, esperado):
    repo, salida = dirs
    (salida / "vueltas" / "1").mkdir(parents=True, exist_ok=True)
    (salida / "vueltas" / "2").mkdir(parents=True, exist_ok=True)
    ok, motivo = permitido(rol, herramienta, _ruta(ruta, repo, salida), repo, salida)
    assert ok is esperado
    assert (motivo == "") is esperado


CASOS_GLOB_PATRON = [
    # patron con ".." o absoluto: denegado con independencia del rol,
    # aunque cartografo tenga lectura abierta a repo+salida.
    ("cartografo", "../../../etc/*", False),
    ("cartografo", "/etc/*", False),
    # llave sin expandir: ningún segmento es literalmente "..", pero un
    # motor de glob que expanda llaves antes de comparar (node-glob/
    # minimatch) lo convertiría en "../etc/*". El chequeo por substring
    # (no por segmento exacto) lo pilla igual.
    ("cartografo", "{..,x}/etc/*", False),
    # "~" en el patrón: mismo razonamiento que "~" en rutas normales (D8).
    ("cartografo", "~/etc/*", False),
    # patrón relativo normal, sin "..": no regresión.
    ("cartografo", "**/*.py", True),
    ("cartografo", "backend/**/*.py", True),
]


@pytest.mark.parametrize("rol,patron,esperado", CASOS_GLOB_PATRON)
def test_glob_patron_fuera_del_muro(dirs, rol, patron, esperado):
    repo, salida = dirs
    # ruta=None: Glob sin path explícito se evalúa sobre cwd/salida (ya
    # permitido para cartografo); lo que se comprueba aquí es `patron`.
    ok, motivo = permitido(rol, "Glob", None, repo, salida, patron=patron)
    assert ok is esperado
    assert (motivo == "") is esperado


def test_symlink_a_vueltas_no_esquiva_la_denegacion(dirs):
    # Un symlink dentro de salida que apunta a vueltas/: escribir a través
    # de él debe resolver a vueltas/ de verdad y denegarse igual, no solo
    # la ruta literal "salida/vueltas/...".
    repo, salida = dirs
    (salida / "vueltas" / "1").mkdir(parents=True)
    (salida / "atajo").symlink_to(salida / "vueltas")
    ok, motivo = permitido(
        "cartografo", "Write", str(salida / "atajo" / "1" / "verificacion.md"), repo, salida
    )
    assert ok is False
    assert motivo != ""
