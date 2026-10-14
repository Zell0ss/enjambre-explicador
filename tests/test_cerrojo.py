import subprocess
import sys

import pytest

from enjambre.cerrojo import Ocupado, ocupado, tomar

RETENER = (
    "import fcntl, sys, time\n"
    "f = open(sys.argv[1], 'a')\n"
    "fcntl.flock(f, fcntl.LOCK_EX)\n"
    "print('ok', flush=True)\n"
    "time.sleep(30)\n"
)


@pytest.fixture
def retenido(tmp_path):
    ruta = tmp_path / "c.lock"
    p = subprocess.Popen([sys.executable, "-c", RETENER, str(ruta)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ok"
    yield ruta
    p.kill()
    p.wait()


def test_otro_proceso_lo_tiene(retenido):
    assert ocupado(retenido)
    with pytest.raises(Ocupado):
        with tomar(retenido):
            pass


def test_muere_el_proceso_y_queda_libre(tmp_path):
    ruta = tmp_path / "c.lock"
    p = subprocess.Popen([sys.executable, "-c", RETENER, str(ruta)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ok"
    p.kill()
    p.wait()
    assert not ocupado(ruta)


def test_tomar_y_soltar(tmp_path):
    ruta = tmp_path / "c.lock"
    with tomar(ruta):
        assert ocupado(ruta)
    assert not ocupado(ruta)


def test_orquestar_main_respeta_el_cerrojo(retenido, tmp_path, capsys):
    from enjambre.orquestar import main
    repo = tmp_path / "agora"
    repo.mkdir()
    codigo = main(["--repo", str(repo), "--falso", "--salidas", str(tmp_path / "s"), "--cerrojo", str(retenido)])
    assert codigo == 3
    assert "hay otro run en marcha" in capsys.readouterr().err
    assert not (tmp_path / "s").exists()


def test_sin_argumento_usa_la_ruta_aislada_por_el_conftest(tmp_path):
    # R2 de la revisión de H1: `tomar()`/`ocupado()` sin ruta leen `RUTA` en cada
    # llamada, así que el fixture autouse las protege también a ellas.
    from enjambre import cerrojo
    real = cerrojo.RUTA
    assert real.parent == tmp_path
    assert not ocupado()
    with tomar():
        assert ocupado() and ocupado(real)
    assert real.exists()
