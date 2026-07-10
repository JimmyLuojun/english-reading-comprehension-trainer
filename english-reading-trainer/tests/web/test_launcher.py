"""Tests for the loopback-only local web launcher."""

from __future__ import annotations

from app.web import launcher


def test_launcher_sets_token_prints_url_and_binds_loopback(monkeypatch) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr(launcher.secrets, "token_urlsafe", lambda size: "local-token")
    monkeypatch.setattr(launcher.typer, "echo", lambda value: calls.setdefault("echo", value))
    monkeypatch.setattr(
        launcher.uvicorn,
        "run",
        lambda target, **kwargs: calls.update(target=target, **kwargs),
    )

    launcher.run(port=9123, reload=True)

    assert launcher.os.environ["TRAINER_REQUEST_TOKEN"] == "local-token"
    assert calls == {
        "echo": "Open: http://127.0.0.1:9123/?access_token=local-token",
        "target": "app.web.fastapi_app:app",
        "host": "127.0.0.1",
        "port": 9123,
        "reload": True,
    }
