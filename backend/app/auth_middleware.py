"""
HTTP Basic authentication for the whole app (static UI + API): uses the
browser's native prompt, no login page to build/maintain.

Enabled ONLY if ADMIN_PASSWORD is set (via .env / docker-compose).
If left empty, the app stays open as before (unchanged behavior for
anyone who doesn't configure it) — useful because the network is
already isolated on Tailscale, but recommended if the app is exposed
beyond the VPN.

/api/health always remains reachable without authentication, because
the Docker healthcheck uses it (and doesn't send credentials).
"""
import base64
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import settings

_UNAUTHENTICATED_PATHS = {"/api/health"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.admin_password:
            return await call_next(request)

        if request.url.path in _UNAUTHENTICATED_PATHS:
            return await call_next(request)

        if _credentials_valid(request):
            return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="fb-downloader"'},
        )


def _credentials_valid(request: Request) -> bool:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[len("Basic "):]).decode("utf-8")
        username, _, password = decoded.partition(":")
    except Exception:  # noqa: BLE001
        return False

    # constant-time comparison to avoid making timing attacks easier
    user_ok = secrets.compare_digest(username, settings.admin_username)
    pass_ok = secrets.compare_digest(password, settings.admin_password)
    return user_ok and pass_ok
