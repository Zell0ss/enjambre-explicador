"""Pruebas añadidas (no normativas) sobre el foco de revisión 1-3 de la fase 3."""
import subprocess

import pytest

import enjambre.fuente as fuente
from enjambre.fuente import CopiaAjena, Fuente, FuenteInvalida, GitFallo, actualizar, resolver
from tests.gitutil import git, repo_con_commit, rev

F = resolver("https://github.com/x/proyecto")


@pytest.fixture
def remoto(tmp_path):
    trabajo = repo_con_commit(tmp_path / "trabajo")
    bare = tmp_path / "remoto.git"
    git("clone", "--bare", str(trabajo), str(bare))
    git("remote", "add", "origin", str(bare), cwd=trabajo)
    return trabajo, bare


@pytest.mark.parametrize("nombre", ["../fuera", "..", ".", "-x", "a/b", "", "a b"])
def test_nombre_a_mano_se_revalida(nombre, tmp_path):
    f = Fuente(texto="https://github.com/x/y", nombre=nombre, url="https://github.com/x/y")
    with pytest.raises(FuenteInvalida):
        actualizar(f, raiz_copias=tmp_path / "copias", remoto="file:///no")
    assert not (tmp_path / "copias").exists()


def test_url_con_usuario_o_puerto_no_es_github():
    for t in ("https://github.com@evil.example/a/b", "https://github.com:444/a/b", "https://evil.example/github.com/a/b"):
        with pytest.raises(FuenteInvalida):
            resolver(t)


def test_duenio_y_repo_en_mayusculas_se_normalizan():
    # D37 (antes, el repo conservaba sus mayúsculas): la identidad va en minúsculas.
    f = resolver("https://github.com/Henrik-TheVibe/Claude-Fables.GIT")
    assert f.texto == "https://github.com/henrik-thevibe/claude-fables" and f.nombre == "claude-fables"


def test_ruta_local_conserva_sus_mayusculas(tmp_path):
    # D37: solo los repos de GitHub; un directorio de /data se queda como está.
    d = tmp_path / "MiProyecto"
    d.mkdir()
    f = resolver(str(d), raiz_local=tmp_path, raiz_copias=tmp_path / "copias")
    assert f.nombre == "MiProyecto" and f.texto == str(d.resolve())


def test_symlink_hacia_fuera_no_se_toca(remoto, tmp_path):
    _, bare = remoto
    fuera = repo_con_commit(tmp_path / "fuera" / "proyecto")
    git("remote", "add", "origin", f"file://{bare}", cwd=fuera)
    (fuera / "marca.txt").write_text("mío\n")
    copias = tmp_path / "copias"
    copias.mkdir()
    (copias / "proyecto").symlink_to(fuera)
    with pytest.raises(CopiaAjena):
        actualizar(F, raiz_copias=copias, remoto=f"file://{bare}")
    assert (fuera / "marca.txt").exists()


def test_directorio_dentro_de_otro_repo_no_se_toca(remoto, tmp_path):
    # Sin `.git` propio, `git reset --hard` actuaría sobre el repo de arriba.
    _, bare = remoto
    padre = repo_con_commit(tmp_path / "padre")
    d = padre / "copias" / "proyecto"
    d.mkdir(parents=True)
    (padre / "sucio.txt").write_text("sin commitear\n")
    with pytest.raises(CopiaAjena):
        actualizar(F, raiz_copias=padre / "copias", remoto=f"file://{bare}")
    assert (padre / "sucio.txt").exists() and (padre / "a.py").exists()


def test_cambia_la_rama_por_defecto_del_remoto(remoto, tmp_path):
    trabajo, bare = remoto
    copias = tmp_path / "copias"
    actualizar(F, raiz_copias=copias, remoto=f"file://{bare}")
    git("checkout", "-b", "principal", cwd=trabajo)
    repo_con_commit(trabajo, "c.py", "z = 3\n")
    git("push", "origin", "principal", cwd=trabajo)
    git("symbolic-ref", "HEAD", "refs/heads/principal", cwd=bare)

    ruta, commit = actualizar(F, raiz_copias=copias, remoto=f"file://{bare}")
    assert commit == rev(trabajo) and (ruta / "c.py").exists()


def test_git_va_sin_terminal_ni_credenciales(remoto, tmp_path, monkeypatch):
    _, bare = remoto
    visto = []
    real = subprocess.Popen

    def espia(argv, **kw):
        visto.append((argv, kw))
        return real(argv, **kw)

    monkeypatch.setattr(fuente.subprocess, "Popen", espia)
    actualizar(F, raiz_copias=tmp_path / "copias", remoto=f"file://{bare}")
    assert visto
    for argv, kw in visto:
        assert isinstance(argv, list) and not kw.get("shell")
        assert kw["stdin"] == subprocess.DEVNULL
        assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0" and kw["env"]["GIT_ASKPASS"] == ""
        assert "credential.helper=" in argv
    clon = next(a for a, _ in visto if "clone" in a)
    # `--` antes de URL y ruta.
    assert clon[clon.index("clone"):][1:4] == ["--depth", "1", "--"]


def test_timeout_falla_sin_restos(remoto, tmp_path):
    _, bare = remoto
    copias = tmp_path / "copias"
    with pytest.raises(GitFallo, match="tardó"):
        actualizar(F, raiz_copias=copias, remoto=f"file://{bare}", timeout_s=0.0001)
    assert not (copias / "proyecto").exists()


def test_origin_con_mayusculas_no_es_copia_ajena(remoto, tmp_path):
    # R1 de la revisión de H1: la comparación de `origin` no distingue mayúsculas.
    trabajo, _ = remoto
    bare = tmp_path / "Remoto.git"
    git("clone", "--bare", str(trabajo), str(bare))
    copias = tmp_path / "copias"
    actualizar(F, raiz_copias=copias, remoto=f"file://{bare}")
    ruta, commit = actualizar(F, raiz_copias=copias, remoto=f"file://{tmp_path}/REMOTO.git")
    assert commit == rev(trabajo)
