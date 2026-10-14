import pytest

from enjambre import cerrojo


@pytest.fixture(autouse=True)
def _cerrojo_aislado(tmp_path, monkeypatch):
    # Las pruebas que llaman a `orquestar.main` sin `--cerrojo` no deben tocar
    # el cerrojo real de la máquina (D31): ni crearlo ni verse bloqueadas por él.
    monkeypatch.setattr(cerrojo, "RUTA", tmp_path / "cerrojo-de-prueba.lock")
