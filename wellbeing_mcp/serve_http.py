"""
Run the wellbeing MCP server in HTTP mode for remote Claude instances.

Listens on port 8766. Exposed to the internet via Cloudflare Tunnel
as wellbeing.superterran.net (see ~/.cloudflared/config.yml).

Transport: streamable-http at /mcp
  Claude.ai remote connector: https://wellbeing.superterran.net/mcp?token=<key>
  Claude CLI:  claude mcp add wellbeing -t http -- https://wellbeing.superterran.net/mcp

Authentication: Bearer token or ?token= query param on all requests.
Set WELLBEING_API_KEY in the environment (sourced from .env).
"""

import os
import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from .server import mcp


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests missing the correct Bearer token."""

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        token_param = request.query_params.get("token", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
        elif token_param:
            token = token_param
        else:
            return Response("Unauthorized", status_code=401)

        if token != self.api_key:
            return Response("Forbidden", status_code=403)

        return await call_next(request)


if __name__ == "__main__":
    api_key = os.environ.get("WELLBEING_API_KEY")
    if not api_key:
        raise RuntimeError(
            "WELLBEING_API_KEY must be set in the environment. "
            "Add it to repos/wellbeing-mcp/.env: WELLBEING_API_KEY=your-secret-key"
        )

    app = mcp.http_app(transport="streamable-http", path="/mcp")
    app.add_middleware(BearerAuthMiddleware, api_key=api_key)

    uvicorn.run(app, host="127.0.0.1", port=8766, log_level="info")
