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
