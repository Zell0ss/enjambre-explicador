import subprocess
from pathlib import Path


def git(*args: str, cwd: Path | None = None) -> str:
    r = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=trunk", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )
    return r.stdout.strip()


def repo_con_commit(ruta: Path, fichero: str = "a.py", texto: str = "x = 1\n") -> Path:
    ruta.mkdir(parents=True, exist_ok=True)
    if not (ruta / ".git").exists():
        git("init", cwd=ruta)
    (ruta / fichero).write_text(texto)
    git("add", fichero, cwd=ruta)
    git("commit", "-m", f"{fichero}", cwd=ruta)
    return ruta


def rev(ruta: Path) -> str:
    return git("rev-parse", "HEAD", cwd=ruta)
