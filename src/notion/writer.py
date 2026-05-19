"""Phase 13A - thin Notion write client.

Wraps notion-client to expose three operations the MCP tools actually
need:

    create_page(database_id, properties, children=None)  -> page_id
    update_page(page_id, properties)                     -> None
    find_by_internal_id(database_id, internal_id)        -> page_id | None

`find_by_internal_id` queries the database for pages whose "Internal ID"
rich-text property equals the given value. This is the fallback when
the local `notion_sync_map` cache is missing the row (e.g. dev box reset
but Notion still has stale pages). Normal flow uses `upsert_via_sync_map`
which goes through the local cache first.

Per CLAUDE.md, this file imports `notion_client` lazily inside methods
so test boxes without the secret can still run `pytest`.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from sqlalchemy.orm import Session

from src.api.models.notion_sync_map import NotionSyncMap


_LOGGER = logging.getLogger(__name__)


class NotionWriteError(RuntimeError):
    """Raised when the Notion API returns an error we don't want to swallow."""


class NotionWriter:
    """Wraps notion-client with idempotent upsert semantics.

    One writer instance per workspace token. `workspace` is a label
    ('teamspace' / 'publicspace') used for the notion_sync_map row.
    """

    def __init__(self, token: str, *, workspace: str) -> None:
        if not token:
            raise ValueError("NotionWriter requires a non-empty token.")
        if not workspace:
            raise ValueError("NotionWriter requires a workspace label.")
        self._token = token
        self.workspace = workspace
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from notion_client import Client  # lazy import - see module docstring

            self._client = Client(auth=self._token)
        return self._client

    # --- raw operations -----------------------------------------------------

    def create_page(
        self,
        database_id: str,
        properties: dict[str, Any],
        children: Iterable[dict[str, Any]] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        if children:
            payload["children"] = list(children)
        try:
            response = self.client.pages.create(**payload)
        except Exception as exc:  # notion_client.errors.APIResponseError
            raise NotionWriteError(f"create_page failed: {exc}") from exc
        page_id = response.get("id") if isinstance(response, dict) else None
        if not page_id:
            raise NotionWriteError(f"create_page response missing id: {response!r}")
        return page_id

    def update_page(self, page_id: str, properties: dict[str, Any]) -> None:
        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            raise NotionWriteError(f"update_page failed: {exc}") from exc

    def append_blocks(
        self, page_id: str, children: Iterable[dict[str, Any]]
    ) -> None:
        children_list = list(children)
        if not children_list:
            return
        try:
            self.client.blocks.children.append(
                block_id=page_id, children=children_list
            )
        except Exception as exc:
            raise NotionWriteError(f"append_blocks failed: {exc}") from exc

    def find_by_internal_id(
        self,
        database_id: str,
        internal_id: str,
        *,
        property_name: str = "Internal ID",
    ) -> str | None:
        """Database query fallback (used when sync_map is missing)."""
        try:
            response = self.client.databases.query(
                database_id=database_id,
                filter={
                    "property": property_name,
                    "rich_text": {"equals": internal_id},
                },
                page_size=1,
            )
        except Exception as exc:
            raise NotionWriteError(
                f"find_by_internal_id failed: {exc}"
            ) from exc
        results = response.get("results") if isinstance(response, dict) else None
        if results:
            page = results[0]
            return page.get("id") if isinstance(page, dict) else None
        return None

    # --- idempotent upsert via sync_map ------------------------------------

    def upsert_via_sync_map(
        self,
        session: Session,
        *,
        database_id: str,
        internal_table: str,
        internal_id: str,
        properties: dict[str, Any],
        children: Iterable[dict[str, Any]] | None = None,
    ) -> tuple[str, bool]:
        """Create-or-update a page; record the mapping.

        Returns `(page_id, created)`. `created=True` means we created a
        new Notion page; `False` means we updated an existing one (the
        sync_map row pointed us at it).
        """
        existing = (
            session.query(NotionSyncMap)
            .filter_by(
                internal_table=internal_table,
                internal_id=internal_id,
                notion_workspace=self.workspace,
            )
            .one_or_none()
        )

        if existing is not None:
            try:
                self.update_page(existing.notion_page_id, properties)
            except NotionWriteError as exc:
                existing.sync_status = "failed"
                existing.error_message = str(exc)
                raise
            existing.notion_database_id = database_id
            existing.sync_status = "success"
            existing.error_message = None
            session.flush()
            return existing.notion_page_id, False

        page_id = self.create_page(database_id, properties, children)
        row = NotionSyncMap(
            internal_table=internal_table,
            internal_id=internal_id,
            notion_workspace=self.workspace,
            notion_database_id=database_id,
            notion_page_id=page_id,
            sync_status="success",
        )
        session.add(row)
        session.flush()
        return page_id, True
