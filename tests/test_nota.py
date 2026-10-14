from datetime import datetime

import pytest

from enjambre.nota import NotaAjena, escribir, leer_frontmatter

ARGS = dict(
    fuente="https://github.com/x/proyecto", nombre="proyecto", commit="abc1234def",
    run="proyecto-20261015-023000", coste_usd=1.234567, motivo="aprobado", vueltas=1,
    articulo="# Proyecto\n\nTexto.\n", leido=datetime(2026, 10, 15, 2, 47, 13),
)


def test_nota_con_frontmatter(tmp_path):
    ruta = escribir(tmp_path, **ARGS)
    assert ruta == tmp_path / "proyecto.md"
    assert leer_frontmatter(ruta) == {
        "fuente": "https://github.com/x/proyecto", "commit": "abc1234def",
        "leido": "2026-10-15T02:47", "run": "proyecto-20261015-023000",
        "coste_usd": 1.23, "veredicto": "aprobado", "generado_por": "enjambre",
    }
    texto = ruta.read_text()
    assert texto.startswith("---\n") and texto.endswith("# Proyecto\n\nTexto.\n")
    assert list(tmp_path.iterdir()) == [ruta]


def test_tope_de_vueltas(tmp_path):
    ruta = escribir(tmp_path, **{**ARGS, "motivo": "tope_vueltas", "vueltas": 3})
    assert leer_frontmatter(ruta)["veredicto"] == "sin aprobar tras 3 vueltas"


@pytest.mark.parametrize("motivo", ["tope_coste", "interrumpido", "fallo:novato:error", "sin_cambios"])
def test_run_no_acabado_no_escribe(tmp_path, motivo):
    with pytest.raises(ValueError):
        escribir(tmp_path, **{**ARGS, "motivo": motivo})
    assert list(tmp_path.iterdir()) == []


def test_crea_la_carpeta(tmp_path):
    assert escribir(tmp_path / "repo-articles", **ARGS).exists()


def test_misma_fuente_sobrescribe(tmp_path):
    escribir(tmp_path, **ARGS)
    ruta = escribir(tmp_path, **{**ARGS, "commit": "fff0000"})
    assert leer_frontmatter(ruta)["commit"] == "fff0000"


def test_otra_fuente_con_el_mismo_nombre(tmp_path):
    ruta = escribir(tmp_path, **ARGS)
    antes = ruta.read_text()
    with pytest.raises(NotaAjena):
        escribir(tmp_path, **{**ARGS, "fuente": "https://github.com/otro/proyecto"})
    assert ruta.read_text() == antes


def test_nota_humana_con_el_mismo_nombre(tmp_path):
    (tmp_path / "proyecto.md").write_text("# Mis notas\n")
    with pytest.raises(NotaAjena):
        escribir(tmp_path, **ARGS)
    assert (tmp_path / "proyecto.md").read_text() == "# Mis notas\n"


def test_commit_none(tmp_path):
    assert leer_frontmatter(escribir(tmp_path, **{**ARGS, "commit": None}))["commit"] is None
