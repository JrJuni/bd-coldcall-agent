"""Phase 10 — /rag namespace + document management endpoints.

P10-2a: `GET /rag/namespaces` (list).
P10-3:
  - `POST /rag/namespaces` — create empty namespace
  - `DELETE /rag/namespaces/{namespace}` — remove (guards: no `default`,
    non-empty refused unless `?force=true`)
  - `GET    /rag/namespaces/{namespace}/documents` — list source files
  - `POST   /rag/namespaces/{namespace}/documents` — multipart upload
  - `DELETE /rag/namespaces/{namespace}/documents/{filename:path}` — remove
    a single source file (does NOT delete chunks from ChromaDB; user must
    re-index to evict — `indexer.py` deletion-pass handles this)

P10-3+ folder UX:
  - `GET    /rag/namespaces/{namespace}/tree?path=` — non-recursive listing
  - `POST   /rag/namespaces/{namespace}/folders` — create empty folder
  - `DELETE /rag/namespaces/{namespace}/folders/{path:path}` — recursive
  - `POST   /rag/namespaces/{namespace}/open?path=` — launch OS file
    explorer (localhost only; same trust model as the rest of the API)
  - `POST /documents` now accepts a `path` form field (subpath inside the
    namespace root). Leaf filename still rejects slashes.

Module-level access only — `from src.config import loader as _config_loader`
follows the DO NOT rule. Tests can monkeypatch `_company_docs_root` to
redirect uploads/deletes into a tmp directory.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from src.api import db as _db
from src.api.schemas import (
    RagDocumentListResponse,
    RagDocumentSummary,
    RagDocumentUploadResponse,
    RagFolderActionResponse,
    RagFolderCreate,
    RagNamespaceCreate,
    RagNamespaceDeleteResponse,
    RagNamespaceListResponse,
    RagNamespaceSummary,
    RagOpenFolderResponse,
    RagRootFileListResponse,
    RagRootOpenResponse,
    RagSummaryCachedResponse,
    RagSummaryRequest,
    RagSummaryResponse,
    RagTreeEntry,
    RagTreeResponse,
)
from src.config import loader as _config_loader
from src.llm import claude_client as _claude_client
from src.rag import retriever as _retriever
from src.rag.namespace import (
    DEFAULT_NAMESPACE,
    MANIFEST_FILENAME,
    company_docs_root_for,
    ensure_namespace,
    list_namespaces,
    vectorstore_root_for,
)


_LOGGER = logging.getLogger(__name__)


# Mirrors `src.rag.connectors.local_file.DEFAULT_EXTENSIONS` — keep aligned
# with the indexer so an uploaded file is actually pickup-able.
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".md", ".txt", ".pdf"})

# 25 MB upload cap per file — generous for PDFs, prevents accidental OOM
# from the `await file.read()` pattern below.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


router = APIRouter()


# ── Path helpers (monkeypatchable) ──────────────────────────────────────


def _vectorstore_root(ws_slug: str = "default") -> Path:
    """Per-workspace ChromaDB persist root.

    Phase 11 P11-1: defaulted to the built-in `default` workspace so call
    sites that haven't migrated to ws-prefixed routing yet still resolve
    to the legacy single-root path.
    """
    from src.rag.workspaces import workspace_paths

    try:
        vs_root, _cd_root = workspace_paths(ws_slug)
        return vs_root
    except KeyError:
        # Workspaces table not yet seeded (early lifespan / tests that
        # bypass init_db). Fall back to the bare project layout.
        settings = _config_loader.get_settings()
        root = Path(settings.rag.vectorstore_path)
        if not root.is_absolute():
            root = _config_loader.PROJECT_ROOT / root
        return root / ws_slug


def _company_docs_root(ws_slug: str = "default") -> Path:
    """Where source files live before indexing, per workspace.

    Tests override this via monkeypatch to redirect into tmp_path.
    """
    from src.rag.workspaces import workspace_paths

    try:
        _vs_root, cd_root = workspace_paths(ws_slug)
        return cd_root
    except KeyError:
        # Same fallback as _vectorstore_root above.
        return _config_loader.PROJECT_ROOT / "data" / "company_docs"


def _validate_namespace_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="namespace name is required")
    if not all(c.isalnum() or c in ("-", "_") for c in name):
        raise HTTPException(
            status_code=422,
            detail=(
                f"namespace {name!r} contains invalid characters; "
                "use only [A-Za-z0-9_-]"
            ),
        )
    return name


def _validate_upload_filename(filename: str) -> str:
    """Validate the LEAF name only — reject path separators, ensure extension.

    Subdirectory placement is conveyed via a separate `path` form field on
    the upload endpoint and validated by `_validate_subpath`.
    """
    if not filename:
        raise HTTPException(status_code=422, detail="filename is required")
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(
            status_code=422, detail=f"invalid filename: {filename!r}"
        )
    if Path(filename).name != filename:
        raise HTTPException(
            status_code=422, detail=f"invalid filename: {filename!r}"
        )
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"unsupported extension {ext!r}; "
                f"allowed: {sorted(_ALLOWED_EXTENSIONS)}"
            ),
        )
    return filename


_SUBPATH_SEGMENT_EXTRA = frozenset({"-", "_", ".", " "})


def _validate_subpath(subpath: str) -> str:
    """Validate a posix relative subpath inside the namespace root.

    Rules: empty allowed (= root); reject leading slash, backslash, drive
    letter (`:`), empty segment, `.`/`..` segments, or any non-alphanumeric
    char outside `{- _ . space}`. Also forbids segments that resolve to
    the empty string after trimming.
    """
    if subpath is None:
        return ""
    s = subpath.strip().replace("\\", "/")
    if not s:
        return ""
    if s.startswith("/"):
        raise HTTPException(status_code=422, detail=f"invalid path: {subpath!r}")
    if ":" in s:
        # Block Windows drive letters / scheme-like prefixes.
        raise HTTPException(status_code=422, detail=f"invalid path: {subpath!r}")
    parts = s.split("/")
    for seg in parts:
        seg_stripped = seg.strip()
        if not seg_stripped or seg_stripped in (".", ".."):
            raise HTTPException(
                status_code=422, detail=f"invalid path: {subpath!r}"
            )
        for ch in seg_stripped:
            if not (ch.isalnum() or ch in _SUBPATH_SEGMENT_EXTRA):
                raise HTTPException(
                    status_code=422,
                    detail=f"invalid path: {subpath!r}",
                )
    return "/".join(p.strip() for p in parts)


def _resolve_inside(root: Path, rel: str) -> Path:
    """Resolve a relative path, refusing escape outside `root`.

    Empty rel is rejected here (callers expecting "root may be empty"
    should branch before calling). This guards the file-delete endpoint.
    """
    if not rel:
        raise HTTPException(status_code=422, detail="filename is required")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"path escapes namespace root: {rel!r}"
        )
    return candidate


def _resolve_subpath(root: Path, subpath: str) -> Path:
    """Like `_resolve_inside` but accepts empty subpath (= root)."""
    if not subpath:
        return root.resolve()
    return _resolve_inside(root, subpath)


# ── Manifest read helpers ───────────────────────────────────────────────


def _read_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("rag: failed to read %s: %s", manifest_path, exc)
        return {}


class _IndexedDoc(NamedTuple):
    """Per-document state lifted from `manifest.json` for local files."""

    chunk_count: int
    indexed_at: str | None


def _summarize(
    vs_root: Path, namespace: str, *, cd_root: Path | None = None
) -> RagNamespaceSummary:
    manifest = vectorstore_root_for(vs_root, namespace) / MANIFEST_FILENAME
    summary = RagNamespaceSummary(
        name=namespace,
        is_default=(namespace == DEFAULT_NAMESPACE),
    )
    raw = _read_manifest(manifest)
    if raw:
        documents = raw.get("documents") or {}
        by_type: dict[str, int] = {}
        chunk_total = 0
        for entry in documents.values():
            st = entry.get("source_type") or "unknown"
            by_type[st] = by_type.get(st, 0) + 1
            chunk_total += int(entry.get("chunk_count") or 0)

        summary.document_count = len(documents)
        summary.chunk_count = chunk_total
        summary.updated_at = raw.get("updated_at")
        summary.by_source_type = by_type

    # Stale check: cd_root provided → walk this namespace's docs root and
    # mark the namespace as needing Re-index when a file is newer than its
    # manifest indexed_at (or absent from the manifest entirely).
    if cd_root is not None:
        cd_dir = company_docs_root_for(cd_root, namespace)
        if cd_dir.exists():
            indexed = _indexed_local_files(vs_root, namespace)
            summary.needs_reindex = _folder_needs_reindex(
                cd_dir, cd_dir, indexed
            )
    return summary


def _indexed_local_files(
    vs_root: Path, namespace: str
) -> dict[str, _IndexedDoc]:
    """Return relative path → (chunk_count, indexed_at) for `local:` entries."""
    manifest = vectorstore_root_for(vs_root, namespace) / MANIFEST_FILENAME
    raw = _read_manifest(manifest)
    out: dict[str, _IndexedDoc] = {}
    for doc_id, entry in (raw.get("documents") or {}).items():
        if not isinstance(doc_id, str) or not doc_id.startswith("local:"):
            continue
        rel = doc_id.split(":", 1)[1]
        out[rel] = _IndexedDoc(
            chunk_count=int(entry.get("chunk_count") or 0),
            indexed_at=(entry.get("indexed_at") or None),
        )
    return out


def _file_mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError:
        return None


def _folder_needs_reindex(
    folder_abs: Path,
    ns_root: Path,
    indexed_lookup: dict[str, _IndexedDoc],
) -> bool:
    """True if any descendant indexable file is missing from the manifest
    or has been modified after its `indexed_at`.

    Both ISO timestamps are produced by `datetime.isoformat(tz=utc)` so a
    string comparison is order-preserving.
    """
    if not folder_abs.exists() or not folder_abs.is_dir():
        return False
    try:
        ns_root_resolved = ns_root.resolve()
    except OSError:
        return False
    for child in folder_abs.rglob("*"):
        if not child.is_file():
            continue
        if child.suffix.lower() not in _ALLOWED_EXTENSIONS:
            continue
        try:
            rel = child.resolve().relative_to(ns_root_resolved).as_posix()
        except (ValueError, OSError):
            continue
        entry = indexed_lookup.get(rel)
        if entry is None or not entry.indexed_at:
            return True  # never indexed (or manifest missing the timestamp)
        mtime_iso = _file_mtime_iso(child)
        if mtime_iso is None:
            continue
        if mtime_iso > entry.indexed_at:
            return True
    return False


def _folder_last_indexed_at(
    folder_rel: str, indexed_lookup: dict[str, _IndexedDoc]
) -> str | None:
    """MAX of `indexed_at` across all manifest docs under `folder_rel`.

    `folder_rel == ""` covers the whole namespace.
    """
    prefix = "" if not folder_rel else folder_rel.rstrip("/") + "/"
    best: str | None = None
    for rel, entry in indexed_lookup.items():
        if not entry.indexed_at:
            continue
        if prefix and not (rel == folder_rel or rel.startswith(prefix)):
            continue
        if best is None or entry.indexed_at > best:
            best = entry.indexed_at
    return best


# ── Summary cache (SQLite) ──────────────────────────────────────────────


def _app_db_path() -> Path:
    """Resolve the app DB path lazily — kept as a tiny accessor so tests
    that override `API_APP_DB` get a fresh path on each call."""
    from src.api.config import get_api_settings

    return Path(get_api_settings().app_db)


def _row_to_summary(row) -> RagSummaryResponse:
    usage_raw = row["usage_json"] or "{}"
    try:
        usage = json.loads(usage_raw)
    except (TypeError, json.JSONDecodeError):
        usage = {}
    return RagSummaryResponse(
        namespace=row["namespace"],
        path=row["path"],
        chunk_count=int(row["chunk_count"] or 0),
        chunks_in_namespace=int(row["chunks_in_namespace"] or 0),
        summary=row["summary"] or "",
        model=row["model"],
        usage=usage if isinstance(usage, dict) else {},
        generated_at=row["generated_at"],
    )


def _get_cached_summary(
    ws_slug: str, namespace: str, path: str
) -> tuple[RagSummaryResponse | None, str | None]:
    """Return (cached summary, indexed_at_at_generation) for the row, or (None, None)."""
    with _db.connect(_app_db_path()) as conn:
        row = conn.execute(
            "SELECT * FROM rag_summaries"
            " WHERE ws_slug = ? AND namespace = ? AND path = ?",
            (ws_slug, namespace, path),
        ).fetchone()
    if row is None:
        return None, None
    return _row_to_summary(row), row["indexed_at_at_generation"]


def _upsert_summary(
    ws_slug: str,
    summary: RagSummaryResponse,
    *,
    lang: str,
    indexed_at_at_generation: str | None,
) -> None:
    with _db.connect(_app_db_path()) as conn:
        # First DELETE the existing row (if any) — INSERT OR REPLACE
        # would honor the original (namespace, path) PK on databases
        # that pre-date the ws_slug column, accidentally clobbering
        # another workspace's row with the same (ns, path).
        conn.execute(
            "DELETE FROM rag_summaries"
            " WHERE ws_slug = ? AND namespace = ? AND path = ?",
            (ws_slug, summary.namespace, summary.path),
        )
        conn.execute(
            """
            INSERT INTO rag_summaries (
                ws_slug, namespace, path, summary, lang, model, usage_json,
                chunk_count, chunks_in_namespace,
                indexed_at_at_generation, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ws_slug,
                summary.namespace,
                summary.path,
                summary.summary,
                lang,
                summary.model,
                json.dumps(summary.usage or {}, ensure_ascii=False),
                summary.chunk_count,
                summary.chunks_in_namespace,
                indexed_at_at_generation,
                summary.generated_at,
            ),
        )


def _delete_namespace_summaries(ws_slug: str, namespace: str) -> None:
    with _db.connect(_app_db_path()) as conn:
        conn.execute(
            "DELETE FROM rag_summaries WHERE ws_slug = ? AND namespace = ?",
            (ws_slug, namespace),
        )


# ── Namespace endpoints ─────────────────────────────────────────────────


@router.get(
    "/rag/workspaces/{ws_slug}/namespaces",
    response_model=RagNamespaceListResponse,
)
async def get_rag_namespaces(ws_slug: str) -> RagNamespaceListResponse:
    vs_root = _vectorstore_root(ws_slug)
    cd_root = _company_docs_root(ws_slug)
    names = list_namespaces(vs_root)
    # Always surface DEFAULT_NAMESPACE so the dropdown is never empty
    # even before the first index pass.
    if DEFAULT_NAMESPACE not in names:
        names.insert(0, DEFAULT_NAMESPACE)
    summaries = [_summarize(vs_root, n, cd_root=cd_root) for n in names]
    return RagNamespaceListResponse(
        namespaces=summaries, default=DEFAULT_NAMESPACE
    )


@router.post(
    "/rag/workspaces/{ws_slug}/namespaces",
    response_model=RagNamespaceSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_rag_namespace(
    ws_slug: str, payload: RagNamespaceCreate,
) -> RagNamespaceSummary:
    name = _validate_namespace_name(payload.name)
    vs_root = _vectorstore_root(ws_slug)
    cd_root = _company_docs_root(ws_slug)

    vs_dir = vectorstore_root_for(vs_root, name)
    cd_dir = company_docs_root_for(cd_root, name)
    if vs_dir.exists() or cd_dir.exists():
        raise HTTPException(
            status_code=409, detail=f"namespace {name!r} already exists"
        )

    ensure_namespace(
        vectorstore_root=vs_root, company_docs_root=cd_root, namespace=name
    )
    return _summarize(vs_root, name, cd_root=cd_root)


@router.delete(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}",
    response_model=RagNamespaceDeleteResponse,
)
async def delete_rag_namespace(
    ws_slug: str, namespace: str, force: bool = False
) -> RagNamespaceDeleteResponse:
    name = _validate_namespace_name(namespace)
    if name == DEFAULT_NAMESPACE:
        raise HTTPException(
            status_code=400,
            detail="the default namespace cannot be deleted",
        )

    vs_root = _vectorstore_root(ws_slug)
    cd_root = _company_docs_root(ws_slug)
    vs_dir = vectorstore_root_for(vs_root, name)
    cd_dir = company_docs_root_for(cd_root, name)

    if not vs_dir.exists() and not cd_dir.exists():
        raise HTTPException(
            status_code=404, detail=f"namespace {name!r} not found"
        )

    if not force:
        # Refuse if either side has user data.
        manifest = vs_dir / MANIFEST_FILENAME
        manifest_data = _read_manifest(manifest)
        has_indexed = bool(manifest_data.get("documents") or {})
        has_files = (
            cd_dir.exists()
            and any(
                p.is_file() and p.suffix.lower() in _ALLOWED_EXTENSIONS
                for p in cd_dir.rglob("*")
            )
        )
        if has_indexed or has_files:
            raise HTTPException(
                status_code=409,
                detail=(
                    "namespace not empty; pass ?force=true to remove "
                    "indexed chunks and source files"
                ),
            )

    if vs_dir.exists():
        shutil.rmtree(vs_dir, ignore_errors=True)
    if cd_dir.exists():
        shutil.rmtree(cd_dir, ignore_errors=True)
    # Drop any cached summaries — orphan rows would mislead the UI after
    # someone recreates a namespace with the same name.
    _delete_namespace_summaries(ws_slug, name)
    return RagNamespaceDeleteResponse(name=name, removed=True)


# ── Document endpoints ──────────────────────────────────────────────────


@router.get(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}/documents",
    response_model=RagDocumentListResponse,
)
async def list_rag_documents(
    ws_slug: str, namespace: str
) -> RagDocumentListResponse:
    name = _validate_namespace_name(namespace)
    vs_root = _vectorstore_root(ws_slug)
    cd_root = _company_docs_root(ws_slug)
    cd_dir = company_docs_root_for(cd_root, name)

    indexed = _indexed_local_files(vs_root, name)

    docs: list[RagDocumentSummary] = []
    if cd_dir.exists():
        for path in sorted(cd_dir.rglob("*")):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext not in _ALLOWED_EXTENSIONS:
                continue
            try:
                rel = path.relative_to(cd_dir).as_posix()
            except ValueError:
                rel = path.name
            try:
                stat = path.stat()
                size = stat.st_size
                modified = datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(timespec="seconds")
            except OSError:
                size = 0
                modified = None
            indexed_entry = indexed.get(rel)
            docs.append(
                RagDocumentSummary(
                    filename=rel,
                    size_bytes=size,
                    modified_at=modified,
                    extension=ext,
                    indexed=indexed_entry is not None,
                    chunk_count=indexed_entry.chunk_count if indexed_entry else 0,
                )
            )
    return RagDocumentListResponse(
        namespace=name,
        documents=docs,
        indexed_doc_count=sum(1 for d in docs if d.indexed),
    )


@router.post(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}/documents",
    response_model=RagDocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_rag_document(
    ws_slug: str,
    namespace: str,
    file: UploadFile = File(...),
    path: str = Form(""),
) -> RagDocumentUploadResponse:
    name = _validate_namespace_name(namespace)
    filename = _validate_upload_filename(file.filename or "")
    subpath = _validate_subpath(path)

    cd_root = _company_docs_root(ws_slug)
    cd_dir = company_docs_root_for(cd_root, name)
    cd_dir.mkdir(parents=True, exist_ok=True)

    target_dir = _resolve_subpath(cd_dir, subpath)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename

    # Stream to disk in chunks, enforcing the size cap.
    written = 0
    with target.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)  # 1MB chunks
            if not chunk:
                break
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"file exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB cap"
                    ),
                )
            out.write(chunk)
    await file.close()

    rel = (
        target.relative_to(cd_dir).as_posix() if subpath else filename
    )
    return RagDocumentUploadResponse(
        namespace=name, filename=rel, size_bytes=written
    )


@router.delete(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}/documents/{filename:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rag_document(
    ws_slug: str, namespace: str, filename: str
) -> None:
    name = _validate_namespace_name(namespace)
    cd_root = _company_docs_root(ws_slug)
    cd_dir = company_docs_root_for(cd_root, name)
    if not cd_dir.exists():
        raise HTTPException(status_code=404, detail="namespace not found")

    target = _resolve_inside(cd_dir, filename)
    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=404, detail=f"document not found: {filename!r}"
        )
    target.unlink()


# ── Folder browsing ─────────────────────────────────────────────────────


def _format_file_entry(
    path: Path, rel_to_ns: str, indexed_lookup: dict[str, _IndexedDoc]
) -> RagTreeEntry:
    ext = path.suffix.lower()
    try:
        stat = path.stat()
        size = stat.st_size
        modified = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds")
    except OSError:
        size = 0
        modified = None
    entry = indexed_lookup.get(rel_to_ns)
    return RagTreeEntry(
        type="file",
        name=path.name,
        size_bytes=size,
        modified_at=modified,
        extension=ext,
        indexed=entry is not None,
        chunk_count=entry.chunk_count if entry else 0,
    )


def _format_folder_entry(
    path: Path,
    *,
    ns_root: Path | None = None,
    indexed_lookup: dict[str, _IndexedDoc] | None = None,
) -> RagTreeEntry:
    try:
        child_count = sum(1 for _ in path.iterdir())
    except OSError:
        child_count = 0
    needs_reindex: bool | None = None
    if ns_root is not None and indexed_lookup is not None:
        needs_reindex = _folder_needs_reindex(path, ns_root, indexed_lookup)
    return RagTreeEntry(
        type="folder",
        name=path.name,
        child_count=child_count,
        needs_reindex=needs_reindex,
    )


@router.get(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}/tree",
    response_model=RagTreeResponse,
)
async def get_rag_tree(
    ws_slug: str, namespace: str, path: str = ""
) -> RagTreeResponse:
    name = _validate_namespace_name(namespace)
    subpath = _validate_subpath(path)
    vs_root = _vectorstore_root(ws_slug)
    cd_root = _company_docs_root(ws_slug)
    cd_dir = company_docs_root_for(cd_root, name)
    if not cd_dir.exists():
        # Empty tree for a namespace that has no docs root yet.
        return RagTreeResponse(
            namespace=name, path="", parent=None, entries=[]
        )

    target = _resolve_subpath(cd_dir, subpath)
    if not target.exists() or not target.is_dir():
        raise HTTPException(
            status_code=404, detail=f"folder not found: {subpath!r}"
        )

    indexed = _indexed_local_files(vs_root, name)
    folders: list[RagTreeEntry] = []
    files: list[RagTreeEntry] = []
    for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir():
            folders.append(
                _format_folder_entry(
                    child, ns_root=cd_dir, indexed_lookup=indexed
                )
            )
        elif child.is_file():
            ext = child.suffix.lower()
            if ext not in _ALLOWED_EXTENSIONS:
                continue
            try:
                rel = child.relative_to(cd_dir).as_posix()
            except ValueError:
                rel = child.name
            files.append(_format_file_entry(child, rel, indexed))

    parent: str | None = None
    if subpath:
        parts = subpath.split("/")
        parent = "/".join(parts[:-1]) if len(parts) > 1 else ""

    return RagTreeResponse(
        namespace=name,
        path=subpath,
        parent=parent,
        entries=folders + files,
    )


@router.post(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}/folders",
    response_model=RagFolderActionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rag_folder(
    ws_slug: str, namespace: str, payload: RagFolderCreate
) -> RagFolderActionResponse:
    name = _validate_namespace_name(namespace)
    subpath = _validate_subpath(payload.path)
    if not subpath:
        raise HTTPException(status_code=422, detail="folder path is required")

    cd_root = _company_docs_root(ws_slug)
    cd_dir = company_docs_root_for(cd_root, name)
    cd_dir.mkdir(parents=True, exist_ok=True)

    target = _resolve_inside(cd_dir, subpath)
    if target.exists():
        raise HTTPException(
            status_code=409, detail=f"folder already exists: {subpath!r}"
        )
    target.mkdir(parents=True, exist_ok=False)
    return RagFolderActionResponse(
        namespace=name, path=subpath, created=True
    )


@router.delete(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}/folders/{path:path}",
    response_model=RagFolderActionResponse,
)
async def delete_rag_folder(
    ws_slug: str, namespace: str, path: str
) -> RagFolderActionResponse:
    name = _validate_namespace_name(namespace)
    subpath = _validate_subpath(path)
    if not subpath:
        # Refusing root delete — that's the namespace DELETE's job.
        raise HTTPException(
            status_code=422,
            detail="folder path is required (use namespace DELETE for root)",
        )

    cd_root = _company_docs_root(ws_slug)
    cd_dir = company_docs_root_for(cd_root, name)
    if not cd_dir.exists():
        raise HTTPException(status_code=404, detail="namespace not found")

    target = _resolve_inside(cd_dir, subpath)
    if not target.exists() or not target.is_dir():
        raise HTTPException(
            status_code=404, detail=f"folder not found: {subpath!r}"
        )
    shutil.rmtree(target)
    return RagFolderActionResponse(
        namespace=name, path=subpath, removed=True
    )


def _launch_file_manager(abs_path: str) -> bool:
    """Open the OS file manager at the given absolute path.

    Wrapped in a function so tests can monkeypatch it cheaply.
    Windows uses `os.startfile`, the canonical API; Popen("explorer", ...)
    is unreliable when the FastAPI server is launched without an attached
    console. macOS uses `open`, Linux uses `xdg-open`.
    """
    try:
        if sys.platform.startswith("win"):
            os.startfile(abs_path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", abs_path])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", abs_path])  # noqa: S603,S607
        return True
    except (OSError, FileNotFoundError, AttributeError) as exc:
        _LOGGER.warning("rag: open folder failed: %s", exc)
        return False


@router.post(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}/open",
    response_model=RagOpenFolderResponse,
)
async def open_rag_folder(
    ws_slug: str, namespace: str, path: str = ""
) -> RagOpenFolderResponse:
    """Launch the OS file explorer at the namespace folder (localhost only).

    The API is meant to run on the user's own machine alongside the web UI;
    this is the same trust model as everything else in `/rag/*`.
    """
    name = _validate_namespace_name(namespace)
    subpath = _validate_subpath(path)
    cd_root = _company_docs_root(ws_slug)
    cd_dir = company_docs_root_for(cd_root, name)
    cd_dir.mkdir(parents=True, exist_ok=True)
    target = _resolve_subpath(cd_dir, subpath)
    if not target.exists() or not target.is_dir():
        raise HTTPException(
            status_code=404, detail=f"folder not found: {subpath!r}"
        )

    abs_path = str(target)
    opened = _launch_file_manager(abs_path)
    return RagOpenFolderResponse(
        namespace=name, path=subpath, abs_path=abs_path, opened=opened
    )


@router.post(
    "/rag/workspaces/{ws_slug}/root/open",
    response_model=RagRootOpenResponse,
)
async def open_rag_root(ws_slug: str) -> RagRootOpenResponse:
    """Launch the OS file explorer at the workspace's docs root."""
    cd_root = _company_docs_root(ws_slug)
    cd_root.mkdir(parents=True, exist_ok=True)
    abs_path = str(cd_root.resolve())
    opened = _launch_file_manager(abs_path)
    return RagRootOpenResponse(abs_path=abs_path, opened=opened)


# ── Root-level files (for filesystem-mirror UX) ─────────────────────────


@router.get(
    "/rag/workspaces/{ws_slug}/root/files",
    response_model=RagRootFileListResponse,
)
async def list_rag_root_files(ws_slug: str) -> RagRootFileListResponse:
    """List files directly under the workspace's docs root (top-level).

    Subdirectories (= namespaces) are NOT included — those are surfaced
    via `GET /rag/workspaces/{ws_slug}/namespaces`. The RAG tab combines
    both client-side.
    """
    cd_root = _company_docs_root(ws_slug)
    if not cd_root.exists():
        return RagRootFileListResponse(files=[])
    files: list[RagDocumentSummary] = []
    for path in sorted(cd_root.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            continue
        try:
            stat = path.stat()
            size = stat.st_size
            modified = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds")
        except OSError:
            size = 0
            modified = None
        files.append(
            RagDocumentSummary(
                filename=path.name,
                size_bytes=size,
                modified_at=modified,
                extension=ext,
                indexed=False,  # root files aren't indexed by any namespace
                chunk_count=0,
            )
        )
    return RagRootFileListResponse(files=files)


@router.post(
    "/rag/workspaces/{ws_slug}/root/files",
    response_model=RagDocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_rag_root_file(
    ws_slug: str,
    file: UploadFile = File(...),
) -> RagDocumentUploadResponse:
    """Upload a file directly under the workspace's docs root (top-level)."""
    filename = _validate_upload_filename(file.filename or "")
    cd_root = _company_docs_root(ws_slug)
    cd_root.mkdir(parents=True, exist_ok=True)
    target = _resolve_inside(cd_root, filename)

    written = 0
    with target.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"file exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB cap"
                    ),
                )
            out.write(chunk)
    await file.close()

    return RagDocumentUploadResponse(
        namespace="", filename=filename, size_bytes=written
    )


@router.delete(
    "/rag/workspaces/{ws_slug}/root/files/{filename:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rag_root_file(ws_slug: str, filename: str) -> None:
    cd_root = _company_docs_root(ws_slug)
    if not cd_root.exists():
        raise HTTPException(status_code=404, detail="root not found")
    # leaf-only — no slashes / traversal
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise HTTPException(
            status_code=422, detail=f"invalid filename: {filename!r}"
        )
    target = _resolve_inside(cd_root, filename)
    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=404, detail=f"document not found: {filename!r}"
        )
    target.unlink()


# ── AI Summary ──────────────────────────────────────────────────────────


_SYSTEM_TASK_SEPARATOR = "---TASK---"


def _load_summary_prompt(lang: str) -> tuple[str, str]:
    lang_dir = lang if lang in ("en", "ko") else "ko"
    path = (
        _config_loader.PROJECT_ROOT
        / "src"
        / "prompts"
        / lang_dir
        / "namespace_summary.txt"
    )
    content = path.read_text(encoding="utf-8")
    parts = content.split(_SYSTEM_TASK_SEPARATOR, 1)
    if len(parts) != 2:
        raise RuntimeError(
            f"namespace_summary.txt ({lang_dir}) missing "
            f"{_SYSTEM_TASK_SEPARATOR!r} delimiter"
        )
    return parts[0].strip(), parts[1].strip()


def _build_chunks_block(chunks: list, max_chars_per_chunk: int = 1200) -> str:
    """Render sampled chunks for the prompt.

    Truncates each chunk to keep the prompt under control. We surface
    title + source_ref so the model can mention concrete documents.
    """
    if not chunks:
        return "(corpus is empty)"
    lines: list[str] = []
    for i, c in enumerate(chunks, 1):
        text = (c.text or "").strip().replace("\r", "")
        if len(text) > max_chars_per_chunk:
            text = text[:max_chars_per_chunk].rstrip() + "…"
        title = (c.title or c.source_ref or c.doc_id or "").strip()
        lines.append(f'<chunk i="{i}" title="{title}">')
        lines.append(text)
        lines.append("</chunk>")
    return "\n".join(lines)


@router.get(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}/summary",
    response_model=RagSummaryCachedResponse,
)
async def get_cached_rag_summary(
    ws_slug: str, namespace: str, path: str = ""
) -> RagSummaryCachedResponse:
    """Return the cached AI summary for `(ws_slug, namespace, path)` or `null`.

    `is_stale` flips to True when the folder's current `last_indexed_at`
    is greater than the value captured at generation time — i.e. the
    user re-indexed since the summary was written.
    """
    name = _validate_namespace_name(namespace)
    subpath = _validate_subpath(path)
    cached, indexed_at_at_gen = _get_cached_summary(ws_slug, name, subpath)
    if cached is None:
        return RagSummaryCachedResponse(summary=None)

    vs_root = _vectorstore_root(ws_slug)
    indexed = _indexed_local_files(vs_root, name)
    current = _folder_last_indexed_at(subpath, indexed)
    is_stale = bool(
        current and (indexed_at_at_gen is None or current > indexed_at_at_gen)
    )
    cached.is_stale = is_stale
    return RagSummaryCachedResponse(summary=cached)


@router.post(
    "/rag/workspaces/{ws_slug}/namespaces/{namespace}/summary",
    response_model=RagSummaryResponse,
)
async def generate_rag_summary(
    ws_slug: str, namespace: str, payload: RagSummaryRequest
) -> RagSummaryResponse:
    name = _validate_namespace_name(namespace)
    subpath = _validate_subpath(payload.path)

    store = _retriever._store(ws_slug, name)
    total = store.count()
    if total == 0:
        return RagSummaryResponse(
            namespace=name,
            path=subpath,
            chunk_count=0,
            chunks_in_namespace=0,
            summary=(
                "_이 namespace 에는 인덱싱된 청크가 없습니다. 파일 업로드 후"
                " Re-index 를 실행하세요._"
            ),
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    # Path filter — chunks store source_ref as a relative path in the
    # namespace's company_docs root. We use a $contains-style filter only
    # if the user is scoped to a sub-path; ChromaDB doesn't support
    # prefix matching directly, so we sample broader and filter client-side
    # when a sub-path is given.
    sample_n = max(payload.sample_size, 1)
    chunks = store.sample(
        limit=min(sample_n * 4 if subpath else sample_n, max(total, 1))
    )
    if subpath:
        chunks = [
            c for c in chunks
            if c.source_ref and (
                c.source_ref == subpath
                or c.source_ref.startswith(subpath + "/")
            )
        ][:sample_n]
    else:
        chunks = chunks[:sample_n]

    if not chunks:
        return RagSummaryResponse(
            namespace=name,
            path=subpath,
            chunk_count=0,
            chunks_in_namespace=total,
            summary=(
                "_이 경로에 해당하는 인덱싱된 청크를 찾지 못했습니다."
                " path 가 정확한지 또는 Re-index 가 필요한지 확인하세요._"
            ),
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    # Render the prompt.
    system_tpl, task_tpl = _load_summary_prompt(payload.lang)
    path_clause = (
        f", scoped to path {subpath!r}" if subpath else " (full namespace)"
    )
    chunks_block = _build_chunks_block(chunks)
    fmt = {
        "namespace": name,
        "path_clause": path_clause,
        "chunk_count": len(chunks),
        "chunks_block": chunks_block,
    }
    system = system_tpl.format(**fmt)
    user = task_tpl.format(**fmt)

    try:
        result = _claude_client.chat_once(
            system=system,
            user=user,
            max_tokens=payload.max_tokens,
            temperature=0.2,
        )
    except RuntimeError as exc:
        # Most likely missing ANTHROPIC_API_KEY.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    response = RagSummaryResponse(
        namespace=name,
        path=subpath,
        chunk_count=len(chunks),
        chunks_in_namespace=total,
        summary=(result.get("text") or "").strip(),
        model=result.get("model"),
        usage=result.get("usage") or {},
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    # Persist for reload + stale detection. The folder's last_indexed_at
    # at generation time becomes the staleness baseline for future GETs.
    vs_root = _vectorstore_root(ws_slug)
    indexed = _indexed_local_files(vs_root, name)
    indexed_at_now = _folder_last_indexed_at(subpath, indexed)
    try:
        _upsert_summary(
            ws_slug,
            response,
            lang=payload.lang,
            indexed_at_at_generation=indexed_at_now,
        )
    except Exception as exc:  # noqa: BLE001 — cache is best-effort
        _LOGGER.warning("rag: summary cache write failed: %s", exc)
    return response
