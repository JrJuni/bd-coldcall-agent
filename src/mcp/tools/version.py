"""Phase 13A - `version` MCP smoke tool.

Returns a small dict describing the agent runtime. The point of this
tool is registration verification - it's the cheapest possible payload
that proves Claude Desktop can talk to the server, schemas are wired up,
and the conda Python is the one actually running. If `version()` works
in Claude Desktop, every later tool will register the same way.
"""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.config.loader import PROJECT_ROOT


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip() or "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def _app_version() -> str:
    pyproject = PROJECT_ROOT / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("version"):
            # version = "0.1.0"
            _, _, rhs = stripped.partition("=")
            return rhs.strip().strip('"').strip("'")
    return "unknown"


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="version",
        description=(
            "Return runtime metadata for the bd-coldcall-agent MCP server: "
            "app version, python version, platform, and git sha. Useful as a "
            "smoke test to confirm the server is reachable."
        ),
    )
    def version() -> dict[str, Any]:
        return {
            "app_version": _app_version(),
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "git_sha": _git_sha(),
            "project_root": str(PROJECT_ROOT),
        }
