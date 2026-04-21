from unittest.mock import MagicMock

import pytest

from src.rag.connectors.notion import NotionConnector


def _rt(text: str) -> dict:
    return {"plain_text": text, "type": "text", "text": {"content": text}}


def _text_block(btype: str, text: str, *, block_id: str = "b", has_children: bool = False) -> dict:
    return {
        "id": block_id,
        "type": btype,
        "has_children": has_children,
        btype: {"rich_text": [_rt(text)]},
    }


def _child_page_block(block_id: str, title: str = "Child") -> dict:
    return {
        "id": block_id,
        "type": "child_page",
        "has_children": False,
        "child_page": {"title": title},
    }


def _make_client(
    *,
    pages: dict | None = None,
    blocks_by_parent: dict[str, list[list[dict]]] | None = None,
    db_rows: list[dict] | None = None,
):
    """Build a MagicMock Notion client with programmable responses.

    - `pages`: page_id -> response dict for pages.retrieve
    - `blocks_by_parent`: parent_id -> list-of-pages; each 'page' is a list of
      blocks. Consecutive pages simulate `has_more` pagination.
    - `db_rows`: rows returned by databases.query (single page, no pagination)
    """
    pages = pages or {}
    blocks_by_parent = blocks_by_parent or {}
    db_rows = db_rows or []

    client = MagicMock()

    def fake_pages_retrieve(*, page_id):
        return pages[page_id]

    client.pages.retrieve.side_effect = fake_pages_retrieve

    def fake_blocks_list(*, block_id, start_cursor=None):
        pages_for_parent = blocks_by_parent.get(block_id, [[]])
        idx = 0 if start_cursor is None else int(start_cursor)
        page = pages_for_parent[idx] if idx < len(pages_for_parent) else []
        has_more = idx + 1 < len(pages_for_parent)
        return {
            "results": page,
            "has_more": has_more,
            "next_cursor": str(idx + 1) if has_more else None,
        }

    client.blocks.children.list.side_effect = fake_blocks_list

    def fake_db_query(*, database_id, start_cursor=None):
        return {
            "results": db_rows,
            "has_more": False,
            "next_cursor": None,
        }

    client.databases.query.side_effect = fake_db_query
    return client


def test_requires_token_or_client():
    with pytest.raises(ValueError):
        NotionConnector(token="", page_ids=["x"])


def test_page_title_from_title_property():
    page_id = "page-1"
    page = {
        "id": page_id,
        "url": "https://notion.so/page-1",
        "last_edited_time": "2026-04-20T10:00:00.000Z",
        "properties": {
            "Name": {
                "type": "title",
                "title": [_rt("My Page Title")],
            }
        },
    }
    blocks = [
        _text_block("heading_1", "Welcome", block_id="h1"),
        _text_block("paragraph", "Some body text.", block_id="p1"),
    ]
    client = _make_client(
        pages={page_id: page},
        blocks_by_parent={page_id: [blocks]},
    )
    conn = NotionConnector(token="ignored", page_ids=[page_id], client=client)
    docs = list(conn.iter_documents())
    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == "notion:page:page-1"
    assert doc.source_type == "notion"
    assert doc.title == "My Page Title"
    assert "Welcome" in doc.content
    assert "Some body text." in doc.content
    assert doc.extra_metadata["url"] == "https://notion.so/page-1"
    assert doc.last_modified is not None
    assert doc.last_modified.year == 2026


def test_page_title_falls_back_to_first_line_when_property_empty():
    page_id = "page-2"
    page = {
        "id": page_id,
        "url": "https://notion.so/page-2",
        "last_edited_time": "2026-04-20T10:00:00.000Z",
        "properties": {
            "Name": {"type": "title", "title": []},
        },
    }
    blocks = [
        _text_block("heading_1", "Fallback Heading", block_id="h1"),
        _text_block("paragraph", "body", block_id="p1"),
    ]
    client = _make_client(
        pages={page_id: page},
        blocks_by_parent={page_id: [blocks]},
    )
    conn = NotionConnector(token="ignored", page_ids=[page_id], client=client)
    docs = list(conn.iter_documents())
    assert docs[0].title == "Fallback Heading"


def test_page_title_defaults_to_untitled_when_no_content():
    page_id = "page-3"
    page = {
        "id": page_id,
        "url": "",
        "last_edited_time": None,
        "properties": {},
    }
    client = _make_client(
        pages={page_id: page},
        blocks_by_parent={page_id: [[]]},
    )
    conn = NotionConnector(token="ignored", page_ids=[page_id], client=client)
    docs = list(conn.iter_documents())
    assert docs[0].title == "Untitled"
    assert docs[0].content == ""
    assert docs[0].last_modified is None


def test_database_row_uses_title_property():
    db_id = "db-1"
    row_id = "row-1"
    row = {
        "id": row_id,
        "url": "https://notion.so/row-1",
        "last_edited_time": "2026-04-20T10:00:00.000Z",
        "properties": {
            "Name": {
                "type": "title",
                "title": [_rt("Row Title")],
            },
            "Status": {
                "type": "select",
                "select": {"name": "Open"},
            },
        },
    }
    blocks = [_text_block("paragraph", "row body.", block_id="rp1")]
    client = _make_client(
        blocks_by_parent={row_id: [blocks]},
        db_rows=[row],
    )
    conn = NotionConnector(token="ignored", database_ids=[db_id], client=client)
    docs = list(conn.iter_documents())
    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == f"notion:db:{db_id}:{row_id}"
    assert doc.title == "Row Title"
    assert "row body." in doc.content
    assert doc.extra_metadata["database_id"] == db_id


def test_blocks_pagination_is_followed():
    page_id = "page-p"
    page = {
        "id": page_id,
        "url": "",
        "last_edited_time": None,
        "properties": {
            "Name": {"type": "title", "title": [_rt("Paginated")]},
        },
    }
    # Two pages of blocks: first has 2 blocks, second has 1
    first_page = [
        _text_block("paragraph", "first page block one", block_id="b1"),
        _text_block("paragraph", "first page block two", block_id="b2"),
    ]
    second_page = [
        _text_block("paragraph", "second page block one", block_id="b3"),
    ]
    client = _make_client(
        pages={page_id: page},
        blocks_by_parent={page_id: [first_page, second_page]},
    )
    conn = NotionConnector(token="ignored", page_ids=[page_id], client=client)
    docs = list(conn.iter_documents())
    assert len(docs) == 1
    content = docs[0].content
    assert "first page block one" in content
    assert "first page block two" in content
    assert "second page block one" in content


def test_child_pages_become_separate_documents():
    parent_id = "parent"
    child_id = "child"
    parent_page = {
        "id": parent_id,
        "url": "",
        "last_edited_time": None,
        "properties": {"Name": {"type": "title", "title": [_rt("Parent")]}},
    }
    child_page = {
        "id": child_id,
        "url": "",
        "last_edited_time": None,
        "properties": {"Name": {"type": "title", "title": [_rt("Child")]}},
    }
    parent_blocks = [
        _text_block("paragraph", "parent body", block_id="pb1"),
        _child_page_block(child_id, title="Child"),
    ]
    child_blocks = [_text_block("paragraph", "child body", block_id="cb1")]
    client = _make_client(
        pages={parent_id: parent_page, child_id: child_page},
        blocks_by_parent={
            parent_id: [parent_blocks],
            child_id: [child_blocks],
        },
    )
    conn = NotionConnector(token="ignored", page_ids=[parent_id], client=client)
    docs = list(conn.iter_documents())
    assert len(docs) == 2
    ids = {d.id for d in docs}
    assert ids == {"notion:page:parent", "notion:page:child"}

    parent_doc = next(d for d in docs if d.id == "notion:page:parent")
    child_doc = next(d for d in docs if d.id == "notion:page:child")
    # Parent body should NOT contain child body (no duplication)
    assert "parent body" in parent_doc.content
    assert "child body" not in parent_doc.content
    assert "child body" in child_doc.content


def test_nested_blocks_walked_via_has_children():
    page_id = "page-n"
    page = {
        "id": page_id,
        "url": "",
        "last_edited_time": None,
        "properties": {"Name": {"type": "title", "title": [_rt("Nested")]}},
    }
    parent_block_id = "toggle1"
    parent_block = _text_block(
        "paragraph", "toggle header", block_id=parent_block_id, has_children=True
    )
    nested_block = _text_block("paragraph", "nested content", block_id="nc1")
    client = _make_client(
        pages={page_id: page},
        blocks_by_parent={
            page_id: [[parent_block]],
            parent_block_id: [[nested_block]],
        },
    )
    conn = NotionConnector(token="ignored", page_ids=[page_id], client=client)
    docs = list(conn.iter_documents())
    content = docs[0].content
    assert "toggle header" in content
    assert "nested content" in content


def test_page_fetch_failure_logs_and_continues():
    good_id = "good"
    bad_id = "bad"
    good_page = {
        "id": good_id,
        "url": "",
        "last_edited_time": None,
        "properties": {"Name": {"type": "title", "title": [_rt("Good")]}},
    }
    client = _make_client(
        pages={good_id: good_page},
        blocks_by_parent={good_id: [[_text_block("paragraph", "ok", block_id="x")]]},
    )
    # Force pages.retrieve to raise for bad_id
    original = client.pages.retrieve.side_effect

    def maybe_raise(*, page_id):
        if page_id == bad_id:
            raise RuntimeError("notion 404")
        return original(page_id=page_id)

    client.pages.retrieve.side_effect = maybe_raise

    conn = NotionConnector(
        token="ignored", page_ids=[bad_id, good_id], client=client
    )
    docs = list(conn.iter_documents())
    # Bad page skipped, good page kept
    assert len(docs) == 1
    assert docs[0].id == "notion:page:good"
