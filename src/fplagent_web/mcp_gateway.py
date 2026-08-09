from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class FplMcpError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LocalFplMcpGateway:
    """Narrow application adapter over the separately running local FPL MCP server."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ.get("FPLAGENT_MCP_URL", "http://127.0.0.1:8021/mcp")

    async def list_tools(self) -> list[str]:
        try:
            async with (
                streamablehttp_client(self.url, timeout=5) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.list_tools()
                return [tool.name for tool in result.tools]
        except Exception as exc:
            raise FplMcpError(
                "mcp_offline",
                "The local FPL MCP server is not reachable on port 8021.",
            ) from exc

    async def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with (
                streamablehttp_client(self.url, timeout=45) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(name, dict(arguments or {}))
        except Exception as exc:
            raise FplMcpError(
                "mcp_offline",
                "The local FPL MCP server could not complete the request.",
            ) from exc
        if result.isError:
            detail = " ".join(
                str(getattr(item, "text", "")) for item in result.content
            ).strip()
            raise FplMcpError("mcp_tool_failed", detail or f"MCP tool {name} failed.")
        structured = result.structuredContent
        if isinstance(structured, Mapping):
            payload = dict(structured)
            if set(payload) == {"result"} and isinstance(payload["result"], Mapping):
                return dict(payload["result"])
            return payload
        for item in result.content:
            text = getattr(item, "text", None)
            if not isinstance(text, str):
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping):
                return dict(payload)
        raise FplMcpError("invalid_mcp_result", f"MCP tool {name} returned no structured data.")
