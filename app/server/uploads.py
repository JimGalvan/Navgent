"""Bound request bodies before the multipart parser writes temporary files."""

from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.runs.evidence import MAX_REQUEST_BYTES


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/reproductions" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        message = "Evidence uploads are too large. Use up to 10 images (10 MB each) and one recording (50 MB)."
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    too_large = int(value) > MAX_REQUEST_BYTES
                except ValueError:
                    too_large = False
                if too_large:
                    await JSONResponse({"detail": message}, status_code=413)(scope, receive, send)
                    return

        received = 0

        async def limited_receive():
            nonlocal received
            event = await receive()
            received += len(event.get("body", b""))
            if received > MAX_REQUEST_BYTES:
                raise HTTPException(status_code=413, detail=message)
            return event

        await self.app(scope, limited_receive, send)
