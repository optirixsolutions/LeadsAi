"""Exposes the catalog over the official MCP SDK. Identity comes from `identity`, a callable the
server owns, so nothing a client sends can change who a call runs as.

Calls bypass the SDK's own argument handling and go straight to `execute`. That way an unknown
tool or a malformed argument is refused and logged like any other call, and an extra argument
is an error, not something silently dropped.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from mcp.types import Tool as MCPTool
from sqlalchemy.orm import Session, sessionmaker

from app.mcp.registry import DEFAULT_TIMEOUT_S, Identity, ToolResult, execute
from app.mcp.tools import CATALOG


class CatalogServer(MCPServer):
    def __init__(
        self,
        identity: Callable[[], Identity],
        session_factory: sessionmaker[Session],
        on_result: Callable[[ToolResult], None] | None = None,
        **server_kwargs: Any,
    ) -> None:
        super().__init__("salesiq", **server_kwargs)
        self._identity = identity
        self._session_factory = session_factory
        self._on_result = on_result

    async def list_tools(self) -> list[MCPTool]:
        return [
            MCPTool(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_model.model_json_schema(),
                output_schema=spec.output_model.model_json_schema(),
                annotations=ToolAnnotations(
                    read_only_hint=spec.side_effect == "read",
                    destructive_hint=False,
                ),
            )
            for spec in CATALOG.values()
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any = None
    ) -> CallToolResult:
        spec = CATALOG.get(name)
        timeout = (spec.timeout_s if spec else DEFAULT_TIMEOUT_S) + 2
        identity = self._identity()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    execute, CATALOG, identity, name, arguments or {}, self._session_factory
                ),
                timeout=timeout,
            )
        except TimeoutError:
            # The database's statement timeout ends the work itself.
            return _error("timeout", "This tool took too long")
        if self._on_result:
            self._on_result(result)
        if not result.ok:
            return _error(result.error_category or "error", result.message or "Refused")
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result.output, default=str))],
            structured_content=result.output,
        )


def _error(category: str, message: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"{category}: {message}")],
        is_error=True,
    )


def build_server(
    identity: Callable[[], Identity],
    session_factory: sessionmaker[Session],
    *,
    on_result: Callable[[ToolResult], None] | None = None,
    **server_kwargs: Any,
) -> CatalogServer:
    return CatalogServer(identity, session_factory, on_result, **server_kwargs)
