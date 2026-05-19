"""Phase 13A - Notion workspace config loader.

Loads non-secret ids from `config/notion.yaml` and tokens from `.env`,
keeping the two lifecycles separate. Matches the project-wide 3-tier
config convention (CLAUDE.md).

If config/notion.yaml is absent, `load_notion_config()` returns a
config with empty ids - callers that need a real id will fail loudly
when they try to use it. This keeps `pytest` working out of the box on
boxes that haven't set Notion up yet.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.config.loader import PROJECT_ROOT


CONFIG_PATH = PROJECT_ROOT / "config" / "notion.yaml"


@dataclass(frozen=True)
class WorkspaceConfig:
    name: str
    token: str | None
    root_page_id: str
    rfp_qa_database_id: str

    @property
    def has_credentials(self) -> bool:
        return bool(self.token) and bool(self.root_page_id) and not self.root_page_id.startswith("REPLACE_ME")


@dataclass(frozen=True)
class NotionConfig:
    teamspace: WorkspaceConfig
    publicspace: WorkspaceConfig

    def get(self, name: str) -> WorkspaceConfig:
        if name == "teamspace":
            return self.teamspace
        if name == "publicspace":
            return self.publicspace
        raise ValueError(f"Unknown notion workspace: {name!r}")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level.")
    return data


def load_notion_config(path: Path | None = None) -> NotionConfig:
    raw = _load_yaml(path or CONFIG_PATH)
    workspaces = (raw.get("workspaces") or {}) if isinstance(raw, dict) else {}

    def _build(name: str, token_env: str) -> WorkspaceConfig:
        block = workspaces.get(name) or {}
        return WorkspaceConfig(
            name=name,
            token=os.getenv(token_env) or None,
            root_page_id=str(block.get("root_page_id") or "").strip(),
            rfp_qa_database_id=str(block.get("rfp_qa_database_id") or "").strip(),
        )

    return NotionConfig(
        teamspace=_build("teamspace", "NOTION_TEAMSPACE_TOKEN"),
        publicspace=_build("publicspace", "NOTION_PUBLICSPACE_TOKEN"),
    )


def save_notion_config(cfg: NotionConfig, path: Path | None = None) -> None:
    """Write non-secret ids back to config/notion.yaml.

    Tokens are read from env and intentionally not persisted here.
    Used by `scripts/bootstrap_notion.py` after it creates the RFP Q&A
    database to record the new database_id.
    """
    target = path or CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workspaces": {
            "teamspace": {
                "root_page_id": cfg.teamspace.root_page_id,
                "rfp_qa_database_id": cfg.teamspace.rfp_qa_database_id,
            },
            "publicspace": {
                "root_page_id": cfg.publicspace.root_page_id,
                "rfp_qa_database_id": cfg.publicspace.rfp_qa_database_id,
            },
        }
    }
    with target.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
