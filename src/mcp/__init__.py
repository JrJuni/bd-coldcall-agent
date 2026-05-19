"""Phase 13A - MCP server package.

Hosts the FastMCP stdio server that Claude Desktop / Codex connect to.
Tools live in `src/mcp/tools/<tool_name>.py` and are registered through
`register(mcp)` functions called from `src/mcp/server.py`.

Module name `src.mcp` does NOT collide with the PyPI `mcp` package -
Python resolves the latter via top-level absolute imports and the former
only via the `src.` prefix.
"""
