from honest_cv import __version__
from honest_cv.cli import main


def test_version():
    assert __version__


def test_cli_runs():
    assert main([]) == 0


def test_serve_stdio_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr("honest_cv.server.main", lambda port=None, token=None: calls.append((port, token)))
    assert main(["serve"]) == 0
    assert calls == [(None, None)]


def test_serve_http_on_its_port_with_the_token(monkeypatch):
    calls = []
    monkeypatch.setattr("honest_cv.server.main", lambda port=None, token=None: calls.append((port, token)))
    monkeypatch.setenv("HONEST_CV_TOKEN", "s3cret")
    assert main(["serve", "--http"]) == 0
    assert main(["serve", "--http", "--port", "40123"]) == 0
    assert calls == [(38471, "s3cret"), (40123, "s3cret")]


def test_serve_http_without_a_token_makes_one_and_prints_it(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("honest_cv.server.main", lambda port=None, token=None: calls.append(token))
    monkeypatch.delenv("HONEST_CV_TOKEN", raising=False)
    assert main(["serve", "--http"]) == 0
    assert len(calls[0]) >= 32
    assert calls[0] in capsys.readouterr().err


def test_http_requests_need_the_token():
    from starlette.testclient import TestClient

    from honest_cv.server import require_token

    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    client = TestClient(require_token(ok, "s3cret"))
    assert client.get("/mcp").status_code == 401
    assert client.get("/mcp", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/mcp", headers={"Authorization": "Bearer s3cret"}).status_code == 200
