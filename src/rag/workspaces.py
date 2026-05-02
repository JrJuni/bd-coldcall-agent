"""Phase 11 P11-1 — workspace path resolution.

Maps a workspace slug → (vectorstore_root, company_docs_root) by reading
the `workspaces` table in `data/app.db` (via `WorkspaceStore`).

  workspace_paths('default')  →
      (<repo>/data/vectorstore/default, <repo>/data/company_docs)
  workspace_paths('my-docs')  →
      (<repo>/data/vectorstore/my-docs, <user-registered abs_path>)

External workspaces store their *source* files in the registered
abs_path (anywhere on disk), but their *index* (Chroma + manifest) always
lives under the project's `data/vectorstore/<slug>/` so backups and
operations stay centralized.

Why live in `src/rag/` and not `src/api/`: the indexer is a standalone
CLI that should not require importing the FastAPI application. It does
need to read the workspaces table though, so this module lazy-imports
`src.api.store` from inside the function body.
"""
from __future__ import annotations

from pathlib import Path

from src.config import loader as _config_loader


def _resolve_vectorstore_root() -> Path:
    """Project's vectorstore root, absolute. Same logic as routes/rag.py.

    Module-attr access (`_config_loader.get_settings`) so tests that
    monkeypatch `src.config.loader.get_settings` (or any module-attr
    alias of it) flow through here unchanged.
    """
    p = Path(_config_loader.get_settings().rag.vectorstore_path)
    if not p.is_absolute():
        p = _config_loader.PROJECT_ROOT / p
    return p


def workspace_paths(ws_slug: str) -> tuple[Path, Path]:
    """Return (vectorstore_root, company_docs_root) for the workspace.

    Asymmetric default-ws handling (intentional, transitional):
      - default → (settings.rag.vectorstore_path, data/company_docs)
        i.e. the legacy single-root layout. Pre-P11 namespaces already
        live at data/vectorstore/<ns>/ and we don't relocate them.
      - external → (settings.rag.vectorstore_path / <slug>,
                     row.abs_path)
        per-workspace prefix so multiple external workspaces don't
        collide and source files stay at their registered location.

    Phase 11 P11-2 may normalize these once the route layer is
    workspace-prefixed. Until then, this asymmetry preserves all
    existing tests + on-disk layouts.

    Raises KeyError if the slug is not a registered workspace.
    """
    from src.api import store as _store

    row = _store.get_workspace_store().get_by_slug(ws_slug)
    if row is None:
        raise KeyError(f"workspace not found: slug={ws_slug!r}")
    if ws_slug == "default":
        vs_root = _resolve_vectorstore_root()
    else:
        vs_root = _resolve_vectorstore_root() / ws_slug
    cd_root = Path(row["abs_path"])
    return vs_root, cd_root


def list_workspace_slugs() -> list[str]:
    """Return all registered workspace slugs (default first, then user-added)."""
    from src.api import store as _store

    return [row["slug"] for row in _store.get_workspace_store().list()]
