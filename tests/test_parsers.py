from pathlib import Path

import pytest

from enjambre.parsers import SalidaIlegible, fallos, ids_de_piezas, veredicto

FIX = Path(__file__).parent / "fixtures" / "agora_test"


def test_ids_reales():
    assert ids_de_piezas((FIX / "piezas.md").read_text()) == [
        "arranque-config", "acceso-datos", "api-entidades", "construccion-prompt",
        "cliente-llm", "orquestacion-turno", "compresion-contexto", "sintesis-export",
    ]


def test_ids_con_backticks_se_limpian():
    t = "## Resumen\n| Id | Pieza | R |\n|---|---|---|\n| `uno` | a | b |\n| dos | a | b |\n\n## uno — a\n"
    assert ids_de_piezas(t) == ["uno", "dos"]


@pytest.mark.parametrize("texto", [
    "# nada\n",
    "## Resumen\n| Id | Pieza | R |\n|---|---|---|\n\n## Otra\n",
    "## Resumen\n| Id | Pieza | R |\n|---|---|---|\n| Acceso Datos | a | b |\n",
    "## Resumen\n| Id | Pieza | R |\n|---|---|---|\n| ../x | a | b |\n",
])
def test_ids_ilegibles(texto):
    with pytest.raises(SalidaIlegible):
        ids_de_piezas(texto)


def test_blank_line_terminates_table_scan():
    """Regression test: blank line inside table must terminate scan, not skip to stray row."""
    # Stray row after blank line should NOT be included in ids
    t = (
        "## Resumen\n"
        "| Id | Pieza | R |\n"
        "|---|---|---|\n"
        "| uno | a | b |\n"
        "\n"
        "| stray-row | x | y |\n"
        "\n"
        "## Otra\n"
    )
    # Should only contain 'uno', not 'stray-row'
    assert ids_de_piezas(t) == ["uno"]


def test_fallos_reales():
    assert fallos((FIX / "verificacion.md").read_text()) == 0


def test_fallos_variantes():
    assert fallos("## Resultado\n- Fallos: 3\n") == 3
    assert fallos("## Resultado\n- **Fallos:** 2\n") == 2
    assert fallos("sin resultado") is None


def test_veredicto_real():
    assert veredicto((FIX / "dudas.md").read_text()) == "listo"


def test_veredicto_variantes():
    assert veredicto("## Veredicto\n`necesita otra vuelta`\n") == "necesita otra vuelta"
    assert veredicto("## Veredicto\n\nlisto\n") == "listo"
    assert veredicto("## Veredicto\nquizá\n") is None
    assert veredicto("nada") is None
