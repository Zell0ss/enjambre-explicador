from pathlib import Path

import pytest

from enjambre.agentes import ROLES, cargar


def test_carga_los_siete_roles_reales():
    for rol in ROLES:
        a = cargar(rol)
        assert a.rol == rol
        assert a.modelo in ("haiku", "sonnet")
        assert "Read" in a.tools
        assert not a.prompt.startswith("---")
        assert len(a.prompt) > 200


def test_modelos_y_tools_de_la_spec():
    assert cargar("cartografo").modelo == "haiku"
    assert cargar("redactor").modelo == "sonnet"
    assert cargar("redactor").tools == ["Read", "Write", "Edit"]
    assert cargar("novato").tools == ["Read", "Write"]


def test_frontmatter_ausente_es_error(tmp_path: Path):
    (tmp_path / "x.md").write_text("sin frontmatter\n")
    with pytest.raises(ValueError):
        cargar("x", dir_agentes=tmp_path)


def test_rol_inexistente_es_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        cargar("nadie", dir_agentes=tmp_path)


# --- D43 (anexo 2026-10-18, Tarea 31): normativas, tal cual ---
from enjambre.agentes import DIR_AGENTES, ORDEN, aviso_copia, copiar_a


def test_los_prompts_son_ficheros_del_repo():
    ficheros = sorted(DIR_AGENTES.glob("*.md"))
    assert len(ficheros) == 7 and not any(f.is_symlink() for f in ficheros)
    assert {f.stem for f in ficheros} == set(ORDEN)


def test_copiar_a(tmp_path):
    copiar_a(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "01-cartografo.md", "02-despiezador.md", "03-lector-de-pieza.md", "04-trazador.md",
        "05-redactor.md", "06-verificador.md", "07-novato.md"]
    for n, rol in enumerate(ORDEN, 1):
        copia = (tmp_path / f"{n:02d}-{rol}.md").read_text(encoding="utf-8")
        original = (DIR_AGENTES / f"{rol}.md").read_text(encoding="utf-8")
        assert copia.startswith("---\n") and copia.count(aviso_copia(rol)) == 1
        assert copia.replace(aviso_copia(rol) + "\n\n", "", 1) == original
        cierre = copia.index("\n---\n", 4) + len("\n---\n")
        assert copia[cierre:].startswith(aviso_copia(rol))


def test_copiar_a_una_carpeta_que_no_existe(tmp_path):
    with pytest.raises(FileNotFoundError):
        copiar_a(tmp_path / "no")


# --- añadidas (no normativas) ---

def test_main_copiar_a(tmp_path, capsys):
    from enjambre.agentes import main
    assert main(["--copiar-a", str(tmp_path)]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 7 and len(list(tmp_path.iterdir())) == 7


def test_main_destino_inexistente_devuelve_2(tmp_path, capsys):
    from enjambre.agentes import main
    assert main(["--copiar-a", str(tmp_path / "no")]) == 2
    assert "FileNotFoundError" in capsys.readouterr().err


def test_copiar_a_no_deja_temporales_y_se_puede_repetir(tmp_path):
    copiar_a(tmp_path)
    copiar_a(tmp_path)  # la segunda copia pisa la primera: el aviso no se duplica
    assert len(list(tmp_path.iterdir())) == 7
    assert all((tmp_path / f"{n:02d}-{rol}.md").read_text().count("Copia de lectura") == 1 for n, rol in enumerate(ORDEN, 1))


def test_copiar_a_rechaza_un_original_sin_frontmatter(tmp_path):
    origen = tmp_path / "agentes"
    origen.mkdir()
    for rol in ORDEN:
        (origen / f"{rol}.md").write_text("sin frontmatter\n")
    destino = tmp_path / "copias"
    destino.mkdir()
    with pytest.raises(ValueError):
        copiar_a(destino, origen)
    assert list(destino.iterdir()) == []
