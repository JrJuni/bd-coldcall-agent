"""Phase 11 P11-1 — workspace_paths + list_workspace_slugs unit tests.

Covers the slug → (vectorstore_root, company_docs_root) resolution and
the asymmetric default-ws layout that preserves pre-P11 namespaces.

DO NOT rule: `src.rag.workspaces` accesses `src.config.loader` and
`src.api.store` via module attrs so tests can monkeypatch through them.
"""
from __future__ import annotations

import os

os.environ["API_SKIP_WARMUP"] = "1"

import pytest

from src.api import store as _store
from src.api.config import reset_api_settings_cache
from src.api.db import init_db
from src.rag import workspaces as _ws


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch, tmp_path):
    monkeypatch.setenv("API_SKIP_WARMUP", "1")
    monkeypatch.setenv("API_CHECKPOINT_DB", str(tmp_path / "ck.db"))
    monkeypatch.setenv("API_APP_DB", str(tmp_path / "app.db"))
    reset_api_settings_cache()
    _store.reset_stores()
    init_db(tmp_path / "app.db")
    yield
    reset_api_settings_cache()
    _store.reset_stores()


def test_workspace_paths_default_keeps_legacy_layout(monkeypatch, tmp_path):
    # Redirect vectorstore_path to tmp; default ws's cd_root is whatever
    # the seed wrote (real <PROJECT_ROOT>/data/company_docs is fine).
    from src.config import loader as _loader

    original = _loader.get_settings()

    class _FakeRag:
        vectorstore_path = tmp_path / "vs"
        collection_name = "x"
        chunk_size = 1
        chunk_overlap = 0
        top_k = 1
        min_document_chars = 1
        notion_page_ids: list[str] = []
        notion_database_ids: list[str] = []
        embedding_model = "test"

    class _FakeSettings:
        rag = _FakeRag()
        llm = original.llm
        search = original.search
        output = original.output

    monkeypatch.setattr(
        _ws._config_loader, "get_settings", lambda: _FakeSettings()
    )

    vs_root, cd_root = _ws.workspace_paths("default")
    # default ws: NO ws-slug suffix on vs_root (legacy layout preserved)
    assert vs_root == tmp_path / "vs"
    # cd_root is the seeded value (built-in points to data/company_docs)
    assert cd_root.name == "company_docs"


def test_workspace_paths_external_uses_per_slug_prefix(monkeypatch, tmp_path):
    # Register an external ws via the store
    ext = tmp_path / "external"
    ext.mkdir()
    store = _store.get_workspace_store()
    row = store.create(label="My Docs", abs_path=str(ext))
    assert row["slug"] == "my-docs"

    from src.config import loader as _loader

    original = _loader.get_settings()

    class _FakeRag:
        vectorstore_path = tmp_path / "vs"
        collection_name = "x"
        chunk_size = 1
        chunk_overlap = 0
        top_k = 1
        min_document_chars = 1
        notion_page_ids: list[str] = []
        notion_database_ids: list[str] = []
        embedding_model = "test"

    class _FakeSettings:
        rag = _FakeRag()
        llm = original.llm
        search = original.search
        output = original.output

    monkeypatch.setattr(
        _ws._config_loader, "get_settings", lambda: _FakeSettings()
    )

    vs_root, cd_root = _ws.workspace_paths("my-docs")
    assert vs_root == tmp_path / "vs" / "my-docs"
    assert cd_root == ext.resolve()


def test_workspace_paths_unknown_slug_raises_keyerror():
    with pytest.raises(KeyError) as excinfo:
        _ws.workspace_paths("ghost")
    assert "ghost" in str(excinfo.value)


def test_list_workspace_slugs_default_first_then_alpha_then_bravo(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    store = _store.get_workspace_store()
    store.create(label="Alpha", abs_path=str(a))
    store.create(label="Bravo", abs_path=str(b))
    assert _ws.list_workspace_slugs() == ["default", "alpha", "bravo"]


def test_list_workspace_slugs_only_default_when_no_external():
    assert _ws.list_workspace_slugs() == ["default"]


def test_workspace_paths_resolved_path_normalized_for_external(
    monkeypatch, tmp_path
):
    # User registers a path with .. components — the store stores it
    # already resolved.
    real = tmp_path / "real"
    real.mkdir()
    weird = (tmp_path / "real" / ".." / "real").as_posix()
    store = _store.get_workspace_store()
    row = store.create(label="Weird", abs_path=str(weird))
    # WorkspaceStore.create resolves before insert
    assert row["abs_path"] == str(real.resolve())
    _, cd_root = _ws.workspace_paths(row["slug"])
    assert cd_root == real.resolve()
