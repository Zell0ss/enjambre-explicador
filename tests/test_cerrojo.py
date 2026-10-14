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
