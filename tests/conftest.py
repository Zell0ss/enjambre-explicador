import pytest

from enjambre import cerrojo, config


@pytest.fixture(autouse=True)
def _cerrojo_aislado(tmp_path, monkeypatch):
    # Las pruebas que llaman a `orquestar.main` sin `--cerrojo` no deben tocar
    # el cerrojo real de la máquina (D31): ni crearlo ni verse bloqueadas por él.
    monkeypatch.setattr(cerrojo, "RUTA", tmp_path / "cerrojo-de-prueba.lock")


@pytest.fixture(autouse=True)
def _config_aislada(tmp_path, monkeypatch):
    # D44: ninguna prueba puede llegar al vault, a las copias reales ni al `.env` real,
    # aunque se le olvide pasar una ruta. El `.env` apunta a un fichero que no existe,
    # se borran las `ENJAMBRE_*` del entorno y notas/copias van a carpetas de `tmp_path`
    # (que no se crean: solo se fija dónde irían).
    monkeypatch.setattr(config, "RUTA_ENV", tmp_path / "no-hay-.env")
    for v in config.VARIABLES:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("ENJAMBRE_NOTAS", str(tmp_path / "notas-de-prueba"))
    monkeypatch.setenv("ENJAMBRE_COPIAS", str(tmp_path / "copias-de-prueba"))
