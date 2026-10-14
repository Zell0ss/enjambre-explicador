from pathlib import Path

from enjambre.aviso import cargar_env, enviar, texto_noche, texto_run
from enjambre.tipos import Lectura

ENV = {"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "42"}


def test_cargar_env(tmp_path):
    (tmp_path / ".env").write_text('# borracha\nTELEGRAM_BOT_TOKEN="123:abc"\n\nTELEGRAM_CHAT_ID=42\n')
    assert cargar_env(tmp_path / ".env") == {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"}


def test_cargar_env_sin_fichero(tmp_path):
    assert cargar_env(tmp_path / ".env") == {}


def test_enviar():
    llamadas = []
    assert enviar("hola", env=ENV, post=lambda u, d: llamadas.append((u, d)) or 200) is True
    assert llamadas == [("https://api.telegram.org/botT/sendMessage", {"chat_id": "42", "text": "hola"})]


def test_sin_config_no_envia():
    def boom(u, d):
        raise AssertionError("no debía llamarse")
    assert enviar("x", env={}, post=boom) is False


def test_fallo_de_red_no_propaga():
    def red(u, d):
        raise OSError("sin red")
    assert enviar("x", env=ENV, post=red) is False


def test_http_distinto_de_200():
    assert enviar("x", env=ENV, post=lambda u, d: 401) is False


def test_texto_largo_se_recorta():
    visto = {}
    enviar("a" * 10000, env=ENV, post=lambda u, d: visto.update(d) or 200)
    assert len(visto["text"]) <= 4096


def _l(**kw):
    base = dict(fuente="https://github.com/x/proyecto", nombre="proyecto", commit="abc1234def",
                run="r1", salida=Path("/s/proyecto/r1"), motivo="aprobado", vueltas=1,
                coste_usd=1.2345, nota=Path("/v/Clippings/repo-articles/proyecto.md"))
    return Lectura(**{**base, **kw})


def test_texto_run_aprobado():
    t = texto_run(_l())
    assert "proyecto" in t and "aprobado" in t and "1.23 $" in t and "repo-articles/proyecto.md" in t


def test_texto_run_parado():
    t = texto_run(_l(motivo="tope_coste", nota=None))
    assert "tope_coste" in t and "Continuar" in t


def test_texto_noche():
    t = texto_noche({
        "lecturas": [_l(), _l(nombre="otro", motivo="sin_cambios", coste_usd=0, run=None, nota=None)],
        "errores": [("https://github.com/x/privado", "GitFallo: repo privado o inexistente")],
        "gastado_usd": 1.2345, "quedan": 2, "parada": None,
    })
    for trozo in ("proyecto", "otro", "sin cambios", "privado", "1.23 $", "quedan 2"):
        assert trozo in t


def test_el_token_no_llega_al_log(monkeypatch):
    # Añadida: una excepción de urllib puede llevar la URL, y la URL lleva el token.
    import enjambre.aviso as aviso
    logs = []
    monkeypatch.setattr(aviso, "_avisar", logs.append)

    def red(u, d):
        raise OSError(f"fallo en {u}")
    assert enviar("x", env={"TELEGRAM_BOT_TOKEN": "SECRETO", "TELEGRAM_CHAT_ID": "42"}, post=red) is False
    assert logs and all("SECRETO" not in m for m in logs)
