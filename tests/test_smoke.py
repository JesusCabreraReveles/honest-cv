from honest_cv import __version__
from honest_cv.cli import main


def test_version():
    assert __version__


def test_cli_runs():
    assert main([]) == 0


def test_serve_stdio_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr("honest_cv.server.main", lambda port=None: calls.append(port))
    assert main(["serve"]) == 0
    assert calls == [None]


def test_serve_http_on_its_port(monkeypatch):
    calls = []
    monkeypatch.setattr("honest_cv.server.main", lambda port=None: calls.append(port))
    assert main(["serve", "--http"]) == 0
    assert main(["serve", "--http", "--port", "40123"]) == 0
    assert calls == [38471, 40123]
