"""Phase 13A - one-time Notion workspace bootstrap.

Reads config/notion.yaml + .env, ensures the RFP Q&A Evaluation database
exists under each workspace's root page, and writes the database_id
back to config/notion.yaml.

Idempotent: re-running after success is a no-op except for refreshing
the file timestamps. Failure leaves the YAML untouched.

Usage:
    ~/miniconda3/envs/bd-coldcall/python.exe scripts/bootstrap_notion.py

Pre-reqs (see docs/phase13.md):
  1. config/notion.yaml has real root_page_ids
  2. .env has NOTION_TEAMSPACE_TOKEN (and NOTION_PUBLICSPACE_TOKEN if you
     also want to bootstrap Publicspace).
  3. Each integration has been added to its root page in Notion.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path

from src.notion.config import (
    CONFIG_PATH,
    WorkspaceConfig,
    load_notion_config,
    save_notion_config,
)
from src.notion.databases.rfp_qa import (
    DATABASE_TITLE,
    database_schema,
)


_LOGGER = logging.getLogger("bootstrap_notion")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


def _ensure_rfp_qa_db(ws: WorkspaceConfig) -> str:
    """Find or create the RFP Q&A Evaluation DB under ws.root_page_id."""
    from notion_client import Client

    client = Client(auth=ws.token)

    if ws.rfp_qa_database_id:
        _LOGGER.info("[%s] RFP Q&A DB already recorded: %s", ws.name, ws.rfp_qa_database_id)
        return ws.rfp_qa_database_id

    # Search children of root_page_id for an existing DB with our title.
    cursor = None
    while True:
        kwargs = {"block_id": ws.root_page_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        children = client.blocks.children.list(**kwargs)
        for block in children.get("results", []):
            if block.get("type") == "child_database":
                title = (block.get("child_database") or {}).get("title")
                if title == DATABASE_TITLE:
                    _LOGGER.info(
                        "[%s] found existing %r DB: %s",
                        ws.name,
                        DATABASE_TITLE,
                        block["id"],
                    )
                    return block["id"]
        if not children.get("has_more"):
            break
        cursor = children.get("next_cursor")

    _LOGGER.info("[%s] creating %r under root page", ws.name, DATABASE_TITLE)
    response = client.databases.create(
        parent={"type": "page_id", "page_id": ws.root_page_id},
        title=[{"type": "text", "text": {"content": DATABASE_TITLE}}],
        properties=database_schema(),
    )
    db_id = response.get("id")
    if not db_id:
        raise RuntimeError(f"[{ws.name}] databases.create returned no id: {response!r}")
    _LOGGER.info("[%s] created %s -> %s", ws.name, DATABASE_TITLE, db_id)
    return db_id


def main() -> int:
    if not CONFIG_PATH.exists():
        _LOGGER.error(
            "config/notion.yaml is missing - copy config/notion.example.yaml and fill in root_page_ids first."
        )
        return 2

    cfg = load_notion_config()
    updated_team = cfg.teamspace
    updated_pub = cfg.publicspace

    if cfg.teamspace.has_credentials:
        try:
            db_id = _ensure_rfp_qa_db(cfg.teamspace)
        except Exception:
            _LOGGER.exception("[teamspace] bootstrap failed")
            return 1
        updated_team = replace(cfg.teamspace, rfp_qa_database_id=db_id)
    else:
        _LOGGER.warning(
            "[teamspace] skipped - need NOTION_TEAMSPACE_TOKEN + a real root_page_id."
        )

    if cfg.publicspace.has_credentials:
        try:
            db_id = _ensure_rfp_qa_db(cfg.publicspace)
        except Exception:
            _LOGGER.exception("[publicspace] bootstrap failed")
            return 1
        updated_pub = replace(cfg.publicspace, rfp_qa_database_id=db_id)
    else:
        _LOGGER.info(
            "[publicspace] skipped (optional in Phase 13A; needed in Phase 13.5)."
        )

    new_cfg = replace(cfg, teamspace=updated_team, publicspace=updated_pub)
    save_notion_config(new_cfg)
    _LOGGER.info("config/notion.yaml updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
