"""Shared helpers for router registration tests."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI


def registered_paths(
    register: Callable[[FastAPI, Callable[[], object]], None],
) -> set[tuple[str, str]]:
    app = FastAPI()
    register(app, lambda: object())
    return {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
