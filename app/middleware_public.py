from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from . import config


def _same_origin(headers: Headers) -> bool:
    if "origin" in headers:
        return headers.getlist("origin") == [config.PUBLIC_ORIGIN]
    try:
        referrer = urlsplit(headers.get("referer", ""))
    except ValueError:
        return False
    return f"{referrer.scheme}://{referrer.netloc}" == config.PUBLIC_ORIGIN


class PublicAccessMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not config.PUBLIC_ORIGIN or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if config.LOCAL_PUBLIC_PREVIEW and (
            (scope.get("server") or (None,))[0] != config.LOCAL_PREVIEW_HOST
            or (scope.get("client") or (None,))[0] != config.LOCAL_PREVIEW_HOST
        ):
            await JSONResponse({"detail": "Local preview requires loopback"}, status_code=403)(scope, receive, send)
            return

        scope.setdefault("state", {})["public_mode"] = True
        path = scope["path"].rstrip("/")
        method = scope["method"]
        headers = Headers(scope=scope)
        if path == "/admin" or path.startswith("/admin/") or path in {
            "/users/backup", "/users/restore", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json",
        }:
            response = JSONResponse({"detail": "Not found"}, status_code=404)
        elif method not in {"GET", "HEAD", "OPTIONS"} and not _same_origin(headers):
            response = JSONResponse({"detail": "Invalid request origin"}, status_code=403)
        elif method == "POST" and path in {"/auth/login", "/auth/register"}:
            media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            length = headers.get("content-length", "")
            if media_type != "application/x-www-form-urlencoded":
                response = JSONResponse({"detail": "Unsupported media type"}, status_code=415)
            elif not length.isascii() or not length.isdecimal() or len(length) > 4 or int(length) > 4096:
                response = JSONResponse({"detail": "Request body too large"}, status_code=413)
            else:
                await self.app(scope, receive, send)
                return
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)
