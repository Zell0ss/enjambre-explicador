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


def _copia(remoto, tmp_path):
    """Clona con `actualizar` (así lleva la marca de D38) y devuelve su ruta."""
    trabajo, bare = remoto
    copias = tmp_path / "copias"
    ruta, _ = actualizar(F, raiz_copias=copias, remoto=f"file://{bare}")
    return trabajo, bare, copias, ruta


def _otra_vez(copias, bare):
    return actualizar(F, raiz_copias=copias, remoto=f"file://{bare}")


# --- D38 (revisión de H4, §6): solo se toca una copia marcada e intacta. (a)-(g) normativas. ---

def test_a_copia_sin_marca_es_ajena(remoto, tmp_path):
    trabajo, bare = remoto
    ajena = repo_con_commit(tmp_path / "copias" / "proyecto")
    git("remote", "add", "origin", f"file://{bare}", cwd=ajena)  # misma URL, pero no la clonó el enjambre
    (ajena / "marca.txt").write_text("mío\n")
    antes = rev(ajena)
    with pytest.raises(CopiaAjena, match="marca"):
        _otra_vez(tmp_path / "copias", bare)
    assert (ajena / "marca.txt").read_text() == "mío\n" and rev(ajena) == antes
    assert (ajena / "a.py").exists()


def test_b_rama_local_nueva(remoto, tmp_path):
    _, bare, copias, ruta = _copia(remoto, tmp_path)
    git("branch", "fase1-motor", cwd=ruta)
    with pytest.raises(CopiaAjena, match="fase1-motor"):
        _otra_vez(copias, bare)
    assert "fase1-motor" in git("branch", "--list", cwd=ruta)


def test_c_fichero_sin_seguimiento(remoto, tmp_path):
    _, bare, copias, ruta = _copia(remoto, tmp_path)
    (ruta / "articulo.md").write_text("suelto\n")
    with pytest.raises(CopiaAjena, match="articulo.md"):
        _otra_vez(copias, bare)
    assert (ruta / "articulo.md").read_text() == "suelto\n"


def test_d_commit_local(remoto, tmp_path):
    _, bare, copias, ruta = _copia(remoto, tmp_path)
    repo_con_commit(ruta, "mio.py", "z = 3\n")
    local = rev(ruta)
    with pytest.raises(CopiaAjena, match="commit local"):
        _otra_vez(copias, bare)
    assert rev(ruta) == local and (ruta / "mio.py").exists()


def test_e_fichero_ignorado(remoto, tmp_path):
    _, bare, copias, ruta = _copia(remoto, tmp_path)
    (ruta / ".git" / "info" / "exclude").write_text("*.log\n")
    (ruta / "x.log").write_text("ignorado\n")
    with pytest.raises(CopiaAjena, match="x.log"):
        _otra_vez(copias, bare)
    assert (ruta / "x.log").read_text() == "ignorado\n"


def test_f_intacta_se_actualiza_y_la_marca_lleva_el_commit_nuevo(remoto, tmp_path):
    trabajo, bare, copias, ruta = _copia(remoto, tmp_path)
    repo_con_commit(trabajo, "b.py", "y = 2\n")
    git("push", "origin", "trunk", cwd=trabajo)

    ruta, commit = _otra_vez(copias, bare)
    assert commit == rev(trabajo) and (ruta / "b.py").exists()
    assert (ruta / ".git" / "enjambre").read_text().strip() == commit
    # ...y como sigue intacta, la siguiente vez también se puede actualizar.
    assert _otra_vez(copias, bare)[1] == commit


def test_g_clone_nuevo_deja_la_marca(remoto, tmp_path):
    trabajo, _, _, ruta = _copia(remoto, tmp_path)
    assert (ruta / ".git" / "enjambre").read_text().strip() == rev(trabajo)


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
