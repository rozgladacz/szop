from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from . import config

AUTH_BODY_LIMIT = 4096
PRIVATE_PATHS = {
    "/users/backup", "/users/restore", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json",
}


def _same_origin(headers: Headers) -> bool:
    if "origin" in headers:
        return headers.getlist("origin") == [config.PUBLIC_ORIGIN]
    try:
        referrer = urlsplit(headers.get("referer", ""))
    except ValueError:
        return False
    return f"{referrer.scheme}://{referrer.netloc}" == config.PUBLIC_ORIGIN


def _reject_public_request(scope) -> JSONResponse | None:
    if config.LOCAL_PUBLIC_PREVIEW and (
        (scope.get("server") or (None,))[0] != config.LOCAL_PREVIEW_HOST
        or (scope.get("client") or (None,))[0] != config.LOCAL_PREVIEW_HOST
    ):
        return JSONResponse({"detail": "Local preview requires loopback"}, status_code=403)

    path = scope["path"]
    root_path = scope.get("root_path", "")
    if root_path and (path == root_path or path.startswith(root_path + "/")):
        path = path[len(root_path):]
    path = path.rstrip("/")
    if path == "/admin" or path.startswith("/admin/") or path in PRIVATE_PATHS:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    method = scope["method"]
    headers = Headers(scope=scope)
    if method not in {"GET", "HEAD", "OPTIONS"} and not _same_origin(headers):
        return JSONResponse({"detail": "Invalid request origin"}, status_code=403)
    if method == "POST" and path in {"/auth/login", "/auth/register"}:
        media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        length = headers.get("content-length", "")
        if media_type != "application/x-www-form-urlencoded":
            return JSONResponse({"detail": "Unsupported media type"}, status_code=415)
        if not length.isascii() or not length.isdecimal() or len(length) > 4 or int(length) > AUTH_BODY_LIMIT:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
    return None


class PublicAccessMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if config.PUBLIC_ORIGIN and scope["type"] == "http":
            response = _reject_public_request(scope)
            if response is not None:
                await response(scope, receive, send)
                return
            scope.setdefault("state", {})["public_mode"] = True
        await self.app(scope, receive, send)
