import pytest

from enjambre.fuente import CopiaAjena, FuenteInvalida, GitFallo, actualizar, resolver
from tests.gitutil import git, repo_con_commit, rev

CANON = "https://github.com/henrik-thevibe/Claude-Fables"


@pytest.mark.parametrize("texto", [
    CANON,
    CANON + "/",
    CANON + ".git",
    CANON + "/tree/main/src",
    "http://github.com/henrik-thevibe/Claude-Fables",
    "https://www.github.com/henrik-thevibe/Claude-Fables",
    "  " + CANON + "  ",
])
def test_url_se_normaliza(texto):
    f = resolver(texto)
    assert f.texto == CANON and f.url == CANON and f.nombre == "Claude-Fables"


@pytest.mark.parametrize("texto", [
    "",
    "https://gitlab.com/a/b",
    "git@github.com:a/b.git",
    "https://github.com/a",
    "https://github.com/a/..",
    "https://github.com/a/-b",
    "https://github.com/a/b;rm -rf ~",
    "relativa/x",
])
def test_fuente_invalida(texto, tmp_path):
    with pytest.raises(FuenteInvalida):
        resolver(texto, raiz_local=tmp_path)


def test_ruta_local(tmp_path):
    d = tmp_path / "proyecto"
    d.mkdir()
    f = resolver(str(d), raiz_local=tmp_path, raiz_copias=tmp_path / "copias")
    assert f.url is None and f.nombre == "proyecto" and f.texto == str(d.resolve())


def test_ruta_local_fuera_de_la_raiz(tmp_path):
    (tmp_path / "fuera").mkdir()
    with pytest.raises(FuenteInvalida):
        resolver(str(tmp_path / "fuera"), raiz_local=tmp_path / "data")


def test_ruta_local_inexistente(tmp_path):
    with pytest.raises(FuenteInvalida):
        resolver(str(tmp_path / "no-esta"), raiz_local=tmp_path)


def test_ruta_dentro_de_las_copias_pide_la_url(tmp_path):
    copia = tmp_path / "copias" / "Claude-Fables"
    copia.mkdir(parents=True)
    with pytest.raises(FuenteInvalida, match="URL"):
        resolver(str(copia), raiz_local=tmp_path, raiz_copias=tmp_path / "copias")


@pytest.fixture
def remoto(tmp_path):
    trabajo = repo_con_commit(tmp_path / "trabajo")
    bare = tmp_path / "remoto.git"
    git("clone", "--bare", str(trabajo), str(bare))
    git("remote", "add", "origin", str(bare), cwd=trabajo)
    return trabajo, bare


F = resolver("https://github.com/x/proyecto")


def test_clona_si_no_hay_copia(remoto, tmp_path):
    trabajo, bare = remoto
    copias = tmp_path / "copias"
    ruta, commit = actualizar(F, raiz_copias=copias, remoto=f"file://{bare}")
    assert ruta == copias / "proyecto"
    assert (ruta / "a.py").read_text() == "x = 1\n"
    assert commit == rev(trabajo)


def test_actualiza_y_descarta_lo_local(remoto, tmp_path):
    trabajo, bare = remoto
    copias = tmp_path / "copias"
    ruta, _ = actualizar(F, raiz_copias=copias, remoto=f"file://{bare}")
    (ruta / "a.py").write_text("tocado\n")
    (ruta / "articulo.md").write_text("suelto\n")
    repo_con_commit(trabajo, "b.py", "y = 2\n")
    git("push", "origin", "trunk", cwd=trabajo)

    ruta, commit = actualizar(F, raiz_copias=copias, remoto=f"file://{bare}")
    assert (ruta / "a.py").read_text() == "x = 1\n"
    assert (ruta / "b.py").exists()
    assert not (ruta / "articulo.md").exists()
    assert commit == rev(trabajo)


def test_copia_de_otro_origen_no_se_toca(remoto, tmp_path):
    _, bare = remoto
    ajena = repo_con_commit(tmp_path / "copias" / "proyecto")
    git("remote", "add", "origin", "file:///otro/sitio.git", cwd=ajena)
    (ajena / "marca.txt").write_text("mío\n")
    with pytest.raises(CopiaAjena):
        actualizar(F, raiz_copias=tmp_path / "copias", remoto=f"file://{bare}")
    assert (ajena / "marca.txt").read_text() == "mío\n"


def test_directorio_que_no_es_repo_no_se_toca(remoto, tmp_path):
    _, bare = remoto
    d = tmp_path / "copias" / "proyecto"
    d.mkdir(parents=True)
    (d / "marca.txt").write_text("mío\n")
    with pytest.raises(CopiaAjena):
        actualizar(F, raiz_copias=tmp_path / "copias", remoto=f"file://{bare}")
    assert (d / "marca.txt").exists()


def test_remoto_inexistente_falla_sin_restos(tmp_path):
    copias = tmp_path / "copias"
    with pytest.raises(GitFallo):
        actualizar(F, raiz_copias=copias, remoto=f"file://{tmp_path}/no-existe.git")
    assert not (copias / "proyecto").exists()


def test_fuente_local_no_se_modifica(tmp_path):
    local = repo_con_commit(tmp_path / "data" / "mio")
    (local / "sucio.txt").write_text("sin commitear\n")
    f = resolver(str(local), raiz_local=tmp_path / "data", raiz_copias=tmp_path / "data" / "copias")
    ruta, commit = actualizar(f, raiz_copias=tmp_path / "data" / "copias")
    assert ruta == local.resolve() and commit == rev(local)
    assert (local / "sucio.txt").exists()


def test_fuente_local_sin_git(tmp_path):
    d = tmp_path / "data" / "suelto"
    d.mkdir(parents=True)
    f = resolver(str(d), raiz_local=tmp_path / "data", raiz_copias=tmp_path / "data" / "copias")
    assert actualizar(f, raiz_copias=tmp_path / "data" / "copias") == (d.resolve(), None)
