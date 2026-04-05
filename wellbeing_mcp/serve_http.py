"""
Run the wellbeing MCP server in HTTP/SSE mode for remote Claude instances.

Listens on port 8766. Exposed to the internet via Cloudflare Tunnel
as wellbeing.superterran.net (see ~/.cloudflared/config.yml).

Remote clients connect via:
  claude mcp add wellbeing -t sse -- https://wellbeing.superterran.net/sse

Authentication: API key via Authorization header or X-API-Key.
Set WELLBEING_API_KEY in the environment (sourced from ~/.env).
"""

import asyncio
import os
from .server import mcp

if __name__ == "__main__":
    api_key = os.environ.get("WELLBEING_API_KEY")
    if not api_key:
        raise RuntimeError(
            "WELLBEING_API_KEY must be set in the environment. "
            "Add it to repos/wellbeing-mcp/.env: WELLBEING_API_KEY=your-secret-key"
        )

    asyncio.run(
        mcp.run_http_async(
            transport="streamable-http",
            host="127.0.0.1",
            port=8766,
            path="/mcp",
            log_level="info",
            show_banner=False,
        )
    )
