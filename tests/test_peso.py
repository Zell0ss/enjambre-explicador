import pytest

from enjambre.fuente import resolver
from enjambre.peso import Peso, estimar, pesar, pesar_fuente, texto
from tests.gitutil import git, repo_con_commit


@pytest.mark.parametrize("tokens,banda,alerta", [
    (49_000, "S", "cabe"),          # agora, 1,68 $
    (111_000, "M", "cabe"),         # enjambre-explicador, 4,17 $
    (135_000, "M", "cabe"),         # Claude-Fables, 4,76 $
    (604_000, "M", "cabe"),         # repomix, 4,66 $
    (3_000_000, "L", "justo"),
    (20_472_000, "XL", "no cabe"),  # golden-thread, > 5,35 $ sin acabar
])
def test_bandas_calibradas(tokens, banda, alerta):
    e = estimar(Peso(1, tokens * 4, 1, tokens * 4), 5.0)
    assert (e.banda, e.alerta) == (banda, alerta)


def test_limites_de_banda():
    assert estimar(Peso(1, 1, 1, 74_999 * 4)).banda == "S"
    assert estimar(Peso(1, 1, 1, 75_000 * 4)).banda == "M"
    assert estimar(Peso(1, 1, 1, 6_000_000 * 4)).banda == "XL"


def test_la_alerta_depende_del_tope():
    m = Peso(1, 1, 1, 600_000 * 4)
    assert estimar(m, 4.0).alerta == "justo" and estimar(m, 3.0).alerta == "no cabe"


def test_texto():
    p = Peso(1187, 6_600_000, 470, 2_400_000)
    assert texto(p, estimar(p)) == "1.187 ficheros, 6,6 MB · código 2,4 MB (~600k tokens) · M · 3,5-5 $ · cabe en 5 $"
    q = Peso(50, 561_000, 42, 530_000)
    assert texto(q, estimar(q, 4.0)) == "50 ficheros, 561 kB · código 530 kB (~132k tokens) · M · 3,5-5 $ · justo para 4 $"
    g = Peso(8804, 126_400_000, 3607, 81_888_000)
    assert texto(g, estimar(g)) == "8.804 ficheros, 126,4 MB · código 81,9 MB (~20,5M tokens) · XL · 7-12 $ · no cabe en 5 $"


def test_pesar_cuenta_lo_que_sigue_git(tmp_path):
    r = repo_con_commit(tmp_path / "r", "a.py", "x" * 400)
    repo_con_commit(r, "README.md", "y" * 100)
    repo_con_commit(r, "big.js", "z" * 300_000)
    (r / "node_modules").mkdir()
    repo_con_commit(r, "node_modules/dep.js", "w" * 1000)
    (r / "img.py").write_bytes(b"\x00" * 50)
    git("add", "img.py", cwd=r); git("commit", "-m", "bin", cwd=r)
    (r / "suelto.py").write_text("q" * 999)          # sin seguir: no cuenta
    assert pesar(r) == Peso(ficheros=4, bytes=400 + 100 + 300_000 + 50, ficheros_codigo=1, bytes_codigo=400)


def test_pesar_carpeta_sin_git(tmp_path):
    (tmp_path / "a.py").write_text("x" * 40)
    (tmp_path / "vendor").mkdir(); (tmp_path / "vendor" / "b.py").write_text("y" * 40)
    assert pesar(tmp_path) == Peso(1, 40, 1, 40)


def test_pesar_fuente_url_no_toca_las_copias(tmp_path, monkeypatch):
    import enjambre.fuente as fuente_mod
    trabajo = repo_con_commit(tmp_path / "trabajo", "a.py", "x" * 80)
    bare = tmp_path / "remoto.git"
    git("clone", "--bare", str(trabajo), str(bare))
    monkeypatch.setenv("ENJAMBRE_COPIAS", str(tmp_path / "copias"))
    tmp = tmp_path / "tmp"; tmp.mkdir()
    p = pesar_fuente(resolver("https://github.com/x/proyecto"), remoto=f"file://{bare}", tmp=tmp)
    assert p == Peso(1, 80, 1, 80)
    assert not (tmp_path / "copias").exists() and list(tmp.iterdir()) == []
