"""Local-only request authentication, CSRF boundaries, and response headers."""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware


_ACCESS_COOKIE = "trainer_access"
_ACCESS_HEADER = "x-trainer-token"
_ACCESS_QUERY = "access_token"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "testserver")
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalSecuritySettings:
    """Per-process settings for the local web server boundary."""

    enabled: bool
    request_token: str
    allowed_hosts: tuple[str, ...]


def build_local_security_settings(
    *,
    enabled: bool,
    request_token: str | None = None,
    allowed_hosts: tuple[str, ...] | None = None,
) -> LocalSecuritySettings:
    """Build local access settings, generating a process-local token if needed."""
    configured_hosts = allowed_hosts or _configured_allowed_hosts()
    token = request_token or os.environ.get("TRAINER_REQUEST_TOKEN", "")
    if enabled and not token:
        token = secrets.token_urlsafe(32)
        _LOG.warning(
            "Generated a local access token. Start with app.web.launcher or open "
            "the tokenized URL printed at startup."
        )
    return LocalSecuritySettings(
        enabled=enabled,
        request_token=token,
        allowed_hosts=configured_hosts,
    )


class LocalAccessMiddleware(BaseHTTPMiddleware):
    """Require a local token and reject cross-origin state-changing requests."""

    def __init__(self, app, *, settings: LocalSecuritySettings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if not self._settings.enabled:
            return await call_next(request)

        query_token = request.query_params.get(_ACCESS_QUERY, "")
        provided_token = (
            request.headers.get(_ACCESS_HEADER, "")
            or query_token
            or request.cookies.get(_ACCESS_COOKIE, "")
        )
        if not _tokens_match(provided_token, self._settings.request_token):
            return PlainTextResponse("Local access token required.", status_code=401)

        if request.method in _UNSAFE_METHODS and not _is_same_origin(request):
            return PlainTextResponse("Cross-origin request rejected.", status_code=403)

        if query_token and request.method in {"GET", "HEAD"}:
            response = RedirectResponse(_url_without_access_token(request), status_code=303)
            _set_access_cookie(response, self._settings.request_token)
            return response

        response = await call_next(request)
        if query_token:
            _set_access_cookie(response, self._settings.request_token)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach conservative browser isolation headers to every response."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'",
        )
        return response


def _configured_allowed_hosts() -> tuple[str, ...]:
    configured = os.environ.get("TRAINER_ALLOWED_HOSTS", "")
    if not configured.strip():
        return _DEFAULT_ALLOWED_HOSTS
    return tuple(
        host.strip().lower()
        for host in configured.split(",")
        if host.strip()
    )


def _tokens_match(provided: str, expected: str) -> bool:
    return bool(provided and expected and hmac.compare_digest(provided, expected))


def _is_same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin:
        return origin == f"{request.url.scheme}://{request.headers.get('host', '')}"
    referer = request.headers.get("referer")
    if not referer:
        return True
    parsed = urlparse(referer)
    return parsed.scheme == request.url.scheme and parsed.netloc == request.headers.get("host", "")


def _url_without_access_token(request: Request) -> str:
    pairs = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key != _ACCESS_QUERY
    ]
    return str(request.url.replace(query=urlencode(pairs, doseq=True)))


def _set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        _ACCESS_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
