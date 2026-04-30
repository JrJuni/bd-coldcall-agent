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

Module-level access only — `from src.config import loader as _config_loader`
follows the DO NOT rule. Tests can monkeypatch `_company_docs_root` to
redirect uploads/deletes into a tmp directory.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from src.api.schemas import (
    RagDocumentListResponse,
    RagDocumentSummary,
    RagDocumentUploadResponse,
    RagNamespaceCreate,
    RagNamespaceDeleteResponse,
    RagNamespaceListResponse,
    RagNamespaceSummary,
)
from src.config import loader as _config_loader
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


def _vectorstore_root() -> Path:
    settings = _config_loader.get_settings()
    root = Path(settings.rag.vectorstore_path)
    if not root.is_absolute():
        root = _config_loader.PROJECT_ROOT / root
    return root


def _company_docs_root() -> Path:
    """Where source files live before indexing.

    Tests override this via monkeypatch to redirect into tmp_path.
    """
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
    """Allow flat filenames only on upload — reject path separators / traversal.

    Subdirectory layout is supported by the indexer (rglob), but creating
    nested paths from the UI is out of scope for P10-3 (P10-3+ folder UX).
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


def _resolve_inside(root: Path, rel: str) -> Path:
    """Resolve a relative path, refusing escape outside `root`."""
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


# ── Manifest read helpers ───────────────────────────────────────────────


def _read_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("rag: failed to read %s: %s", manifest_path, exc)
        return {}


def _summarize(vs_root: Path, namespace: str) -> RagNamespaceSummary:
    manifest = vectorstore_root_for(vs_root, namespace) / MANIFEST_FILENAME
    summary = RagNamespaceSummary(
        name=namespace,
        is_default=(namespace == DEFAULT_NAMESPACE),
    )
    raw = _read_manifest(manifest)
    if not raw:
        return summary

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
    return summary


def _indexed_local_files(vs_root: Path, namespace: str) -> dict[str, int]:
    """Return relative path → chunk_count for `local:`-prefixed manifest entries."""
    manifest = vectorstore_root_for(vs_root, namespace) / MANIFEST_FILENAME
    raw = _read_manifest(manifest)
    out: dict[str, int] = {}
    for doc_id, entry in (raw.get("documents") or {}).items():
        if not isinstance(doc_id, str) or not doc_id.startswith("local:"):
            continue
        rel = doc_id.split(":", 1)[1]
        out[rel] = int(entry.get("chunk_count") or 0)
    return out


# ── Namespace endpoints ─────────────────────────────────────────────────


@router.get("/rag/namespaces", response_model=RagNamespaceListResponse)
async def get_rag_namespaces() -> RagNamespaceListResponse:
    vs_root = _vectorstore_root()
    names = list_namespaces(vs_root)
    # Always surface DEFAULT_NAMESPACE so the dropdown is never empty
    # even before the first index pass.
    if DEFAULT_NAMESPACE not in names:
        names.insert(0, DEFAULT_NAMESPACE)
    summaries = [_summarize(vs_root, n) for n in names]
    return RagNamespaceListResponse(
        namespaces=summaries, default=DEFAULT_NAMESPACE
    )


@router.post(
    "/rag/namespaces",
    response_model=RagNamespaceSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_rag_namespace(
    payload: RagNamespaceCreate,
) -> RagNamespaceSummary:
    name = _validate_namespace_name(payload.name)
    vs_root = _vectorstore_root()
    cd_root = _company_docs_root()

    vs_dir = vectorstore_root_for(vs_root, name)
    cd_dir = company_docs_root_for(cd_root, name)
    if vs_dir.exists() or cd_dir.exists():
        raise HTTPException(
            status_code=409, detail=f"namespace {name!r} already exists"
        )

    ensure_namespace(
        vectorstore_root=vs_root, company_docs_root=cd_root, namespace=name
    )
    return _summarize(vs_root, name)


@router.delete(
    "/rag/namespaces/{namespace}",
    response_model=RagNamespaceDeleteResponse,
)
async def delete_rag_namespace(
    namespace: str, force: bool = False
) -> RagNamespaceDeleteResponse:
    name = _validate_namespace_name(namespace)
    if name == DEFAULT_NAMESPACE:
        raise HTTPException(
            status_code=400,
            detail="the default namespace cannot be deleted",
        )

    vs_root = _vectorstore_root()
    cd_root = _company_docs_root()
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
    return RagNamespaceDeleteResponse(name=name, removed=True)


# ── Document endpoints ──────────────────────────────────────────────────


@router.get(
    "/rag/namespaces/{namespace}/documents",
    response_model=RagDocumentListResponse,
)
async def list_rag_documents(namespace: str) -> RagDocumentListResponse:
    name = _validate_namespace_name(namespace)
    vs_root = _vectorstore_root()
    cd_root = _company_docs_root()
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
            chunk_count = indexed.get(rel, 0)
            docs.append(
                RagDocumentSummary(
                    filename=rel,
                    size_bytes=size,
                    modified_at=modified,
                    extension=ext,
                    indexed=rel in indexed,
                    chunk_count=chunk_count,
                )
            )
    return RagDocumentListResponse(
        namespace=name,
        documents=docs,
        indexed_doc_count=sum(1 for d in docs if d.indexed),
    )


@router.post(
    "/rag/namespaces/{namespace}/documents",
    response_model=RagDocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_rag_document(
    namespace: str, file: UploadFile = File(...)
) -> RagDocumentUploadResponse:
    name = _validate_namespace_name(namespace)
    filename = _validate_upload_filename(file.filename or "")

    cd_root = _company_docs_root()
    cd_dir = company_docs_root_for(cd_root, name)
    cd_dir.mkdir(parents=True, exist_ok=True)
    target = cd_dir / filename

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

    return RagDocumentUploadResponse(
        namespace=name, filename=filename, size_bytes=written
    )


@router.delete(
    "/rag/namespaces/{namespace}/documents/{filename:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rag_document(namespace: str, filename: str) -> None:
    name = _validate_namespace_name(namespace)
    cd_root = _company_docs_root()
    cd_dir = company_docs_root_for(cd_root, name)
    if not cd_dir.exists():
        raise HTTPException(status_code=404, detail="namespace not found")

    target = _resolve_inside(cd_dir, filename)
    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=404, detail=f"document not found: {filename!r}"
        )
    target.unlink()
