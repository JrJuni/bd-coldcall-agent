"""Phase 11 P11-0 — /workspaces CRUD tests.

Exercises the SQLite-backed `WorkspaceStore` end-to-end via the FastAPI
TestClient. Uses tmp_path for the app DB so each test starts with the
auto-seeded `default` workspace + nothing else.

DO NOT rule: routes import `src.api.store as _store`, never bind
WorkspaceStore directly.
"""
from __future__ import annotations

import os

os.environ["API_SKIP_WARMUP"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.api import store as _store
from src.api.config import reset_api_settings_cache
from src.config.loader import PROJECT_ROOT


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch, tmp_path):
    monkeypatch.setenv("API_SKIP_WARMUP", "1")
    monkeypatch.setenv("API_CHECKPOINT_DB", str(tmp_path / "ck.db"))
    monkeypatch.setenv("API_APP_DB", str(tmp_path / "app.db"))
    reset_api_settings_cache()
    _store.reset_stores()
    yield
    reset_api_settings_cache()
    _store.reset_stores()


@pytest.fixture
def client():
    from src.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_default_workspace_seeded_on_boot(client):
    r = client.get("/workspaces")
    assert r.status_code == 200
    rows = r.json()["workspaces"]
    # default seed always present
    defaults = [w for w in rows if w["slug"] == "default"]
    assert len(defaults) == 1
    d = defaults[0]
    assert d["label"] == "Project Docs"
    assert d["is_builtin"] is True
    assert d["abs_path"].endswith("company_docs") or "company_docs" in d["abs_path"]


def test_create_workspace_with_valid_path(client, tmp_path):
    ext = tmp_path / "external_docs"
    ext.mkdir()
    r = client.post(
        "/workspaces",
        json={"label": "My Docs", "abs_path": str(ext)},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "my-docs"
    assert body["label"] == "My Docs"
    assert body["is_builtin"] is False
    assert body["abs_path"] == str(ext.resolve())


def test_slug_collision_appends_suffix(client, tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    r1 = client.post(
        "/workspaces", json={"label": "Notes", "abs_path": str(a)}
    )
    assert r1.status_code == 201
    assert r1.json()["slug"] == "notes"
    r2 = client.post(
        "/workspaces", json={"label": "Notes", "abs_path": str(b)}
    )
    assert r2.status_code == 201
    assert r2.json()["slug"] == "notes-2"


def test_create_rejects_nonexistent_path(client, tmp_path):
    r = client.post(
        "/workspaces",
        json={"label": "Ghost", "abs_path": str(tmp_path / "nope")},
    )
    assert r.status_code == 422
    assert "does not exist" in r.json()["detail"]


def test_create_rejects_file_not_directory(client, tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hi", encoding="utf-8")
    r = client.post(
        "/workspaces", json={"label": "File", "abs_path": str(f)}
    )
    assert r.status_code == 422
    assert "directory" in r.json()["detail"]


def test_create_rejects_relative_path(client):
    r = client.post(
        "/workspaces", json={"label": "Rel", "abs_path": "./relative"}
    )
    assert r.status_code == 422
    assert "absolute" in r.json()["detail"]


def test_create_rejects_path_inside_data(client):
    # data/company_docs is the default workspace; registering anywhere
    # inside data/ would collide with it (and with the vectorstore).
    inside = (PROJECT_ROOT / "data" / "company_docs").resolve()
    if not inside.exists():
        pytest.skip("data/company_docs missing — repo layout drifted")
    r = client.post(
        "/workspaces",
        json={"label": "Inside", "abs_path": str(inside)},
    )
    assert r.status_code == 422
    assert "data/" in r.json()["detail"]


def test_create_rejects_duplicate_abs_path(client, tmp_path):
    ext = tmp_path / "dup"
    ext.mkdir()
    r1 = client.post(
        "/workspaces", json={"label": "First", "abs_path": str(ext)}
    )
    assert r1.status_code == 201
    r2 = client.post(
        "/workspaces", json={"label": "Second", "abs_path": str(ext)}
    )
    assert r2.status_code == 422
    assert "already registered" in r2.json()["detail"]


def test_create_workspace_slug_avoids_default_ws_namespace_dir(
    client, monkeypatch, tmp_path
):
    """An external workspace's slug claims data/vectorstore/<slug>/ as
    its root. If the default workspace already has a namespace named
    `research` (i.e. data/vectorstore/research/), a new external ws with
    label 'Research' must not get slug 'research' — auto-suffix to
    'research-2' instead, mirroring the slug-vs-slug collision UX.
    """
    # Redirect the vectorstore root to tmp_path/vs and seed a default-ws
    # namespace dir 'research'. Patch via module-attr access so the
    # WorkspaceStore lookup in `_default_ws_namespace_names` flows through.
    vs_root = tmp_path / "vs"
    (vs_root / "research").mkdir(parents=True)
    (vs_root / "research" / "manifest.json").write_text(
        '{"version": 1, "updated_at": null, "documents": {}}',
        encoding="utf-8",
    )

    from src.config import loader as _loader

    original = _loader.get_settings()

    class _FakeRag:
        vectorstore_path = vs_root
        collection_name = "x"
        min_document_chars = 1
        chunk_size = 1
        chunk_overlap = 0
        top_k = 1
        notion_page_ids: list[str] = []
        notion_database_ids: list[str] = []
        embedding_model = "test"

    class _FakeSettings:
        rag = _FakeRag()
        llm = original.llm
        search = original.search
        output = original.output

    monkeypatch.setattr(_loader, "get_settings", lambda: _FakeSettings())

    ext = tmp_path / "external_research"
    ext.mkdir()
    r = client.post(
        "/workspaces",
        json={"label": "Research", "abs_path": str(ext)},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # Auto-suffixed because 'research' is reserved by a default-ws ns dir
    assert body["slug"] == "research-2"


def test_list_returns_default_first_then_user_added_in_creation_order(
    client, tmp_path
):
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    client.post("/workspaces", json={"label": "Alpha", "abs_path": str(a)})
    client.post("/workspaces", json={"label": "Bravo", "abs_path": str(b)})
    rows = client.get("/workspaces").json()["workspaces"]
    slugs = [w["slug"] for w in rows]
    assert slugs[0] == "default"
    assert slugs[1:] == ["alpha", "bravo"]


def test_patch_label_only(client, tmp_path):
    ext = tmp_path / "p"
    ext.mkdir()
    created = client.post(
        "/workspaces", json={"label": "Old", "abs_path": str(ext)}
    ).json()
    wid = created["id"]
    r = client.patch(f"/workspaces/{wid}", json={"label": "New"})
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "New"
    # slug + abs_path unchanged
    assert body["slug"] == created["slug"]
    assert body["abs_path"] == created["abs_path"]


def test_patch_ignores_unknown_abs_path_field(client, tmp_path):
    ext = tmp_path / "p2"
    ext.mkdir()
    created = client.post(
        "/workspaces", json={"label": "Keep", "abs_path": str(ext)}
    ).json()
    wid = created["id"]
    # Schema doesn't have abs_path on update — extra field is ignored
    # (pydantic default), and abs_path remains immutable.
    r = client.patch(
        f"/workspaces/{wid}",
        json={"abs_path": "C:/somewhere/else"},
    )
    assert r.status_code == 200
    assert r.json()["abs_path"] == created["abs_path"]


def test_delete_builtin_blocked(client):
    rows = client.get("/workspaces").json()["workspaces"]
    default = next(w for w in rows if w["slug"] == "default")
    r = client.delete(f"/workspaces/{default['id']}")
    assert r.status_code == 400
    assert "default" in r.json()["detail"]


def test_delete_external_workspace(client, tmp_path):
    ext = tmp_path / "x"
    ext.mkdir()
    created = client.post(
        "/workspaces", json={"label": "Del", "abs_path": str(ext)}
    ).json()
    wid = created["id"]
    r = client.delete(f"/workspaces/{wid}")
    assert r.status_code == 204
    r2 = client.get(f"/workspaces/{wid}")
    assert r2.status_code == 404


def test_delete_does_not_touch_source_folder(client, tmp_path):
    ext = tmp_path / "src"
    ext.mkdir()
    (ext / "file.md").write_text("keep me", encoding="utf-8")
    created = client.post(
        "/workspaces", json={"label": "Keep", "abs_path": str(ext)}
    ).json()
    r = client.delete(f"/workspaces/{created['id']}")
    assert r.status_code == 204
    # Source folder + file untouched.
    assert ext.exists()
    assert (ext / "file.md").read_text(encoding="utf-8") == "keep me"


def test_delete_wipe_index_removes_vectorstore(client, tmp_path, monkeypatch):
    # Stub vectorstore root → tmp so we can verify the rmtree runs.
    from src.rag import workspaces as _rag_ws

    vs_root = tmp_path / "vs"
    vs_root.mkdir()
    monkeypatch.setattr(
        _rag_ws, "_resolve_vectorstore_root", lambda: vs_root
    )

    ext = tmp_path / "src"
    ext.mkdir()
    created = client.post(
        "/workspaces", json={"label": "Wipe", "abs_path": str(ext)}
    ).json()
    slug = created["slug"]
    # Pre-seed a fake vectorstore directory for this slug.
    ws_vs = vs_root / slug
    ws_vs.mkdir()
    (ws_vs / "chroma.sqlite3").write_text("fake", encoding="utf-8")

    r = client.delete(f"/workspaces/{created['id']}?wipe_index=true")
    assert r.status_code == 204
    # Source folder still there
    assert ext.exists()
    # Vectorstore wiped
    assert not ws_vs.exists()


def test_delete_without_wipe_keeps_vectorstore(client, tmp_path, monkeypatch):
    from src.rag import workspaces as _rag_ws

    vs_root = tmp_path / "vs"
    vs_root.mkdir()
    monkeypatch.setattr(
        _rag_ws, "_resolve_vectorstore_root", lambda: vs_root
    )

    ext = tmp_path / "src"
    ext.mkdir()
    created = client.post(
        "/workspaces", json={"label": "Keep idx", "abs_path": str(ext)}
    ).json()
    slug = created["slug"]
    ws_vs = vs_root / slug
    ws_vs.mkdir()
    (ws_vs / "chroma.sqlite3").write_text("fake", encoding="utf-8")

    r = client.delete(f"/workspaces/{created['id']}")
    assert r.status_code == 204
    # Vectorstore preserved (default wipe_index=false)
    assert ws_vs.exists()
    assert (ws_vs / "chroma.sqlite3").exists()


def test_get_404_for_unknown(client):
    r = client.get("/workspaces/99999")
    assert r.status_code == 404


def test_patch_404_for_unknown(client):
    r = client.patch("/workspaces/99999", json={"label": "x"})
    assert r.status_code == 404
