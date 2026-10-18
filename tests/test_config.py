from pathlib import Path

import pytest

from enjambre import config


def test_entorno_gana_a_env_y_env_a_defecto(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ENJAMBRE_NOTAS=/desde/env\nENJAMBRE_COPIAS=/copias/env\n")
    monkeypatch.setattr(config, "RUTA_ENV", env)
    monkeypatch.setenv("ENJAMBRE_NOTAS", "/desde/entorno")
    monkeypatch.delenv("ENJAMBRE_COPIAS", raising=False)
    assert config.raiz_notas() == Path("/desde/entorno")
    assert config.raiz_copias() == Path("/copias/env")


def test_valores_por_defecto(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUTA_ENV", tmp_path / "no-existe")
    for v in config.VARIABLES:
        monkeypatch.delenv(v, raising=False)
    assert config.raiz_notas() == config.RAIZ_REPO / "notas"
    assert config.raiz_copias() == config.RAIZ_REPO / "copias"
    assert config.raiz_local() == Path.home()
    assert config.host() == "127.0.0.1" and config.puerto() == 8790


def test_relativa_y_tilde(monkeypatch):
    monkeypatch.setenv("ENJAMBRE_NOTAS", "mis-notas")
    monkeypatch.setenv("ENJAMBRE_COPIAS", "~/copias")
    assert config.raiz_notas() == config.RAIZ_REPO / "mis-notas"
    assert config.raiz_copias() == Path.home() / "copias"


@pytest.mark.parametrize("malo", ["0.0.0.0", "::"])
def test_host_nunca_todas_las_interfaces(monkeypatch, malo):
    monkeypatch.setenv("ENJAMBRE_HOST", malo)
    with pytest.raises(ValueError):
        config.host()


def test_se_resuelve_al_usarlo(monkeypatch):
    monkeypatch.setenv("ENJAMBRE_COPIAS", "/una")
    assert config.raiz_copias() == Path("/una")
    monkeypatch.setenv("ENJAMBRE_COPIAS", "/otra")
    assert config.raiz_copias() == Path("/otra")


def test_el_conftest_aisla():
    assert config.RUTA_ENV != config.RAIZ_REPO / ".env"
    assert "Obsidian" not in str(config.raiz_notas()) and "github-abordaje" not in str(config.raiz_copias())


def test_sin_codigo_de_seb01():
    import subprocess
    salida = subprocess.run(["git", "grep", "-nE", r"/data/|100\.87\.|mi-wiki", "--", "enjambre", "pantalla"],
                            cwd=config.RAIZ_REPO, capture_output=True, text=True).stdout
    assert salida == ""


# --- añadido 2026-10-18 (la sesión del README): los valores por defecto no se cuelan en git ---

def test_notas_y_copias_estan_en_gitignore():
    import subprocess
    # `-q` solo admite una ruta (el anexo la daba junta): una llamada por cada una.
    for ruta in ("notas/x.md", "copias/x/a.py"):
        assert subprocess.run(["git", "check-ignore", "-q", ruta], cwd=config.RAIZ_REPO).returncode == 0, ruta


# --- añadidas (no normativas) ---

def test_puerto_invalido(monkeypatch):
    for malo in ("abc", "0", "70000"):
        monkeypatch.setenv("ENJAMBRE_PUERTO", malo)
        with pytest.raises(ValueError):
            config.puerto()


def test_host_de_nombre_vale_y_un_valor_vacio_es_el_defecto(monkeypatch):
    monkeypatch.setenv("ENJAMBRE_HOST", "localhost")
    assert config.host() == "localhost"
    monkeypatch.setenv("ENJAMBRE_HOST", "  ")
    assert config.host() == "127.0.0.1"


def test_host_del_env_de_seb01_vale(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('ENJAMBRE_HOST="100.87.64.121"\n')
    monkeypatch.setattr(config, "RUTA_ENV", env)
    monkeypatch.delenv("ENJAMBRE_HOST", raising=False)
    assert config.host() == "100.87.64.121"
