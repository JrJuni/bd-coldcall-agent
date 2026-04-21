"""NotionConnector — pages + database rows → Document stream.

Content is extracted by walking the block tree and concatenating `rich_text`
plain-text from supported block types in API order (no sorting — the API
order is what Notion displays). Child pages are emitted as separate
Documents to keep titles honest and avoid content duplication.

Fields intentionally excluded from content (to stabilize the content hash):
- `last_edited_time`, `created_time` — still captured as `last_modified`
  but not embedded in content
- `url` — captured as `extra_metadata["url"]` only
- DB row system fields like view count — skipped entirely

Hash stability caveat: the Notion API is not strictly deterministic about
block ordering in rare edge cases. If per-run hash churn is observed in
production, the fallback is a secondary structural fingerprint (block
type + index sequence) stored in the manifest — deferred to Phase 3.5.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, ClassVar, Iterable, Iterator

from src.rag.connectors.base import SourceConnector
from src.rag.types import Document


_LOGGER = logging.getLogger(__name__)


# Block types whose rich_text we concatenate into content.
_TEXT_BLOCKS = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "quote",
        "code",
        "callout",
    }
)


class NotionConnector(SourceConnector):
    source_type: ClassVar[str] = "notion"

    def __init__(
        self,
        token: str,
        page_ids: Iterable[str] = (),
        database_ids: Iterable[str] = (),
        *,
        client: Any | None = None,
    ):
        if not token and client is None:
            raise ValueError("NotionConnector requires a token or an injected client")
        self.page_ids = list(page_ids)
        self.database_ids = list(database_ids)
        if client is not None:
            self._client = client
        else:
            from notion_client import Client

            self._client = Client(auth=token)

    def iter_documents(self) -> Iterator[Document]:
        for page_id in self.page_ids:
            try:
                yield from self._emit_page(page_id)
            except Exception as exc:
                _LOGGER.warning(
                    "notion_connector: page %s failed: %s", page_id, exc
                )
        for db_id in self.database_ids:
            try:
                yield from self._emit_database(db_id)
            except Exception as exc:
                _LOGGER.warning(
                    "notion_connector: database %s failed: %s", db_id, exc
                )

    # ------ pages -------------------------------------------------------

    def _emit_page(self, page_id: str) -> Iterator[Document]:
        page = self._client.pages.retrieve(page_id=page_id)
        content, child_page_ids = self._extract_page_text(page_id)
        title = _title_from_page_properties(page.get("properties") or {})
        if not title:
            title = _fallback_heading_title(content) or "Untitled"
        yield Document(
            id=f"notion:page:{page_id}",
            source_type="notion",
            source_ref=page_id,
            title=title,
            content=content,
            last_modified=_parse_notion_time(page.get("last_edited_time")),
            mime_type="text/notion",
            extra_metadata={"url": page.get("url", "")},
        )
        for child_id in child_page_ids:
            try:
                yield from self._emit_page(child_id)
            except Exception as exc:
                _LOGGER.warning(
                    "notion_connector: child page %s failed: %s", child_id, exc
                )

    # ------ databases ---------------------------------------------------

    def _emit_database(self, database_id: str) -> Iterator[Document]:
        for row in self._paginate_database(database_id):
            row_id = row["id"]
            title = _title_from_page_properties(row.get("properties") or {}) or "Untitled"
            try:
                content, _child_pages = self._extract_page_text(row_id)
            except Exception as exc:
                _LOGGER.warning(
                    "notion_connector: db row %s body failed: %s", row_id, exc
                )
                continue
            yield Document(
                id=f"notion:db:{database_id}:{row_id}",
                source_type="notion",
                source_ref=row_id,
                title=title,
                content=content,
                last_modified=_parse_notion_time(row.get("last_edited_time")),
                mime_type="text/notion",
                extra_metadata={
                    "url": row.get("url", ""),
                    "database_id": database_id,
                },
            )

    def _paginate_database(self, database_id: str) -> Iterator[dict]:
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"database_id": database_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self._client.databases.query(**kwargs)
            for row in resp.get("results", []):
                yield row
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
            if not cursor:
                break

    # ------ block tree → text ------------------------------------------

    def _extract_page_text(self, block_id: str) -> tuple[str, list[str]]:
        """Return (text, child_page_ids). Walks all descendants of block_id."""
        lines: list[str] = []
        child_pages: list[str] = []
        self._walk_blocks(block_id, lines, child_pages)
        return "\n".join(lines).strip(), child_pages

    def _walk_blocks(
        self,
        parent_id: str,
        lines: list[str],
        child_pages: list[str],
    ) -> None:
        for block in self._iter_child_blocks(parent_id):
            btype = block.get("type", "")
            if btype == "child_page":
                child_pages.append(block["id"])
                continue
            if btype in _TEXT_BLOCKS:
                body = block.get(btype) or {}
                text = _rich_text_to_plain(body.get("rich_text") or [])
                if text:
                    lines.append(text)
            if block.get("has_children"):
                self._walk_blocks(block["id"], lines, child_pages)

    def _iter_child_blocks(self, block_id: str) -> Iterator[dict]:
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"block_id": block_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self._client.blocks.children.list(**kwargs)
            for item in resp.get("results", []):
                yield item
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
            if not cursor:
                break


# ---- helpers -----------------------------------------------------------


def _rich_text_to_plain(rich_text: list[dict]) -> str:
    parts = [rt.get("plain_text", "") for rt in rich_text]
    return "".join(parts).strip()


def _title_from_page_properties(props: dict) -> str:
    for value in props.values():
        if not isinstance(value, dict):
            continue
        if value.get("type") == "title":
            return _rich_text_to_plain(value.get("title") or [])
    return ""


def _fallback_heading_title(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _parse_notion_time(value: str | None) -> datetime | None:
    if not value:
        return None
    # Notion returns ISO-8601 with "Z" suffix on some payloads
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
