"""Run the local web server with a local access token."""

from __future__ import annotations

import os
import secrets

import typer
import uvicorn


app = typer.Typer(add_completion=False)


@app.command()
def run(
    port: int = typer.Option(8001, min=1, max=65535),
    reload: bool = typer.Option(False, help="Reload code during local development"),
    access_token: str | None = typer.Option(
        None,
        "--access-token",
        help=(
            "Reuse this token after manual restarts. "
            "TRAINER_REQUEST_TOKEN is used when this option is omitted."
        ),
    ),
) -> None:
    """Start a loopback-only server and print its browser entry URL."""
    token = access_token or os.environ.get("TRAINER_REQUEST_TOKEN") or secrets.token_urlsafe(32)
    os.environ["TRAINER_REQUEST_TOKEN"] = token
    typer.echo(f"Open: http://127.0.0.1:{port}/?access_token={token}")
    uvicorn.run(
        "app.web.fastapi_app:app",
        host="127.0.0.1",
        port=port,
        reload=reload,
    )


if __name__ == "__main__":  # pragma: no cover - exercised by the console entry point
    app()
