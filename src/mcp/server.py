"""Phase 13A - FastMCP stdio server entry point.

Launched by Claude Desktop / Codex via the `python main.py mcp` CLI
subcommand. Each tool lives in `src/mcp/tools/<name>.py` and registers
itself on the shared FastMCP instance.

Why stdio and not HTTP: stdio is the lowest-friction transport for
single-user Claude Desktop and avoids needing FastAPI to be running.
HTTP/SSE is a Phase 14 follow-up.

Important - Windows stdout encoding:
  Claude Desktop launches this server as a subprocess and reads JSON-RPC
  off its stdout. If stdout is left at the default cp949 codepage,
  Korean characters in tool descriptions or returned strings will break
  the JSON frame. We reconfigure stdio to UTF-8 the same way `main.py`
  does for the Typer CLI.
"""
from __future__ import annotations

import sys


def _reconfigure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
            except (ValueError, AttributeError):
                pass


_reconfigure_stdio_utf8()


from mcp.server.fastmcp import FastMCP  # noqa: E402

from src.mcp.tools import answer_rfp_question as _answer_rfp_tool  # noqa: E402
from src.mcp.tools import query_rag as _query_rag_tool  # noqa: E402
from src.mcp.tools import version as _version_tool  # noqa: E402


def build_server() -> FastMCP:
    mcp = FastMCP(
        name="bd-coldcall-agent",
        instructions=(
            "BD intelligence agent for cold-call research, RAG retrieval, and "
            "RFP / security questionnaire answering. Backed by a local "
            "ChromaDB corpus and Claude Sonnet. Results are logged to the "
            "internal app DB and synced to the BDINT Notion workspaces."
        ),
    )
    _version_tool.register(mcp)
    _query_rag_tool.register(mcp)
    _answer_rfp_tool.register(mcp)
    return mcp


def main() -> None:
    """Run the FastMCP server on stdio.

    Claude Desktop's claude_desktop_config.json should point at this:

        {
          "mcpServers": {
            "bd-coldcall-agent": {
              "command": "<path to conda python>",
              "args": ["<repo root>/main.py", "mcp"]
            }
          }
        }

    See docs/phase13.md for the full setup.
    """
    mcp = build_server()
    mcp.run()  # stdio transport is FastMCP's default


if __name__ == "__main__":
    main()
