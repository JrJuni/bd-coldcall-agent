"""Phase 10 P10-2a — RAG namespace path/name builders + migration.

A "namespace" is a workspace-like grouping of reference docs:
  data/company_docs/<namespace>/...   (source files)
  data/vectorstore/<namespace>/...    (Chroma persist dir + manifest.json)

Each namespace gets its own ChromaDB persist directory, so collections
are physically isolated. The collection name itself stays the base
prefix (`bd_tech_docs`) — namespace separation is by directory, not by
collection-name suffix. Future P10-3 builds folder/file management UI
on top of this layout.

Backwards compatibility: the very first runtime sees a flat
`data/company_docs/*.pdf` and `data/vectorstore/{chroma.sqlite3,manifest.json}`
layout from before P10-2a. `migrate_flat_layout()` moves those into
`<root>/default/` once and is a no-op afterwards.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path


_LOGGER = logging.getLogger(__name__)


DEFAULT_NAMESPACE = "default"
MANIFEST_FILENAME = "manifest.json"
# Schema version of manifest.json — single source of truth, imported by
# `src.rag.indexer`. Bump when the manifest dict shape changes.
MANIFEST_VERSION = 1

# File extensions that the local connector indexes — used to decide which
# flat files to migrate into <root>/default/.
_DOC_EXTENSIONS = {".md", ".txt", ".pdf"}

# Files / directories at the vectorstore root that are part of an
# already-flat ChromaDB layout (created before P10-2a).
_CHROMA_DB_FILE = "chroma.sqlite3"


def vectorstore_root_for(vectorstore_root: Path | str, namespace: str) -> Path:
    """Per-namespace ChromaDB persist directory."""
    return Path(vectorstore_root) / _safe(namespace)


def company_docs_root_for(company_docs_root: Path | str, namespace: str) -> Path:
    """Per-namespace local source-doc directory."""
    return Path(company_docs_root) / _safe(namespace)


def manifest_path_for_namespace(
    vectorstore_root: Path | str, namespace: str
) -> Path:
    return vectorstore_root_for(vectorstore_root, namespace) / MANIFEST_FILENAME


def list_namespaces(vectorstore_root: Path | str) -> list[str]:
    """Discover namespaces by scanning <vectorstore_root>/<name>/manifest.json.

    A directory counts as a namespace iff it contains a manifest.json
    (so migration-in-progress / empty subdirectories don't appear).
    """
    root = Path(vectorstore_root)
    if not root.exists():
        return []
    out: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / MANIFEST_FILENAME).exists():
            out.append(child.name)
    return out


def ensure_namespace(
    *,
    vectorstore_root: Path | str,
    company_docs_root: Path | str,
    namespace: str,
) -> tuple[Path, Path]:
    """Idempotently create the namespace's vectorstore + company_docs dirs.

    Also writes a seed `manifest.json` when one is missing, so the
    namespace is immediately discoverable by `list_namespaces` (which
    keys off manifest presence). Without this, a freshly-created empty
    namespace stays invisible until the first indexer pass writes a
    manifest of its own.
    """
    vs = vectorstore_root_for(vectorstore_root, namespace)
    cd = company_docs_root_for(company_docs_root, namespace)
    vs.mkdir(parents=True, exist_ok=True)
    cd.mkdir(parents=True, exist_ok=True)

    manifest = vs / MANIFEST_FILENAME
    if not manifest.exists():
        seed = {
            "version": MANIFEST_VERSION,
            "updated_at": None,
            "documents": {},
        }
        tmp = manifest.with_suffix(manifest.suffix + ".tmp")
        tmp.write_text(
            json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(manifest)  # os.replace — atomic within a filesystem
    return vs, cd


def migrate_flat_layout(
    *,
    vectorstore_root: Path | str,
    company_docs_root: Path | str,
    target_namespace: str = DEFAULT_NAMESPACE,
) -> dict[str, int]:
    """Move legacy flat data into `<root>/<target_namespace>/`.

    Best-effort: on any single-file failure, log a warning and continue.
    Returns a small report dict suitable for INFO logging.

    Detection rules:
      - Vectorstore root has flat `chroma.sqlite3` or `manifest.json` →
        move ALL files at the root level (except subdirectories that
        already look like namespaces) into `<root>/<target>/`.
      - Company-docs root has flat doc files (.md/.txt/.pdf) → move them
        into `<root>/<target>/`. `.gitkeep` is left in place.

    Idempotent: if `<root>/<target>/` already has the moved files (or the
    flat files don't exist), the function does nothing.
    """
    report = {
        "vectorstore_files_moved": 0,
        "vectorstore_dirs_moved": 0,
        "company_docs_files_moved": 0,
        "errors": 0,
    }

    vs_root = Path(vectorstore_root)
    cd_root = Path(company_docs_root)

    # ── vectorstore migration ──────────────────────────────────────────
    if vs_root.exists():
        flat_chroma = vs_root / _CHROMA_DB_FILE
        flat_manifest = vs_root / MANIFEST_FILENAME
        needs_vs_migration = flat_chroma.exists() or flat_manifest.exists()
        if needs_vs_migration:
            target_vs = vectorstore_root_for(vs_root, target_namespace)
            target_vs.mkdir(parents=True, exist_ok=True)
            for child in list(vs_root.iterdir()):
                # Skip the target namespace (and any other already-namespaced
                # directory that lives at the root).
                if child.is_dir() and (child / MANIFEST_FILENAME).exists():
                    continue
                # Skip the target itself even if its manifest hasn't moved yet.
                if child.resolve() == target_vs.resolve():
                    continue
                dest = target_vs / child.name
                try:
                    if dest.exists():
                        # Don't clobber existing files in the target — the
                        # second migration call must be a no-op.
                        continue
                    was_dir = child.is_dir()  # capture before move (path goes away)
                    shutil.move(str(child), str(dest))
                    if was_dir:
                        report["vectorstore_dirs_moved"] += 1
                    else:
                        report["vectorstore_files_moved"] += 1
                except Exception as exc:
                    _LOGGER.warning(
                        "namespace migrate: vs %s -> %s failed: %s",
                        child,
                        dest,
                        exc,
                    )
                    report["errors"] += 1

    # ── company_docs migration ─────────────────────────────────────────
    if cd_root.exists():
        flat_docs = [
            p
            for p in cd_root.iterdir()
            if p.is_file() and p.suffix.lower() in _DOC_EXTENSIONS
        ]
        if flat_docs:
            target_cd = company_docs_root_for(cd_root, target_namespace)
            target_cd.mkdir(parents=True, exist_ok=True)
            for src in flat_docs:
                dest = target_cd / src.name
                try:
                    if dest.exists():
                        continue
                    shutil.move(str(src), str(dest))
                    report["company_docs_files_moved"] += 1
                except Exception as exc:
                    _LOGGER.warning(
                        "namespace migrate: docs %s -> %s failed: %s",
                        src,
                        dest,
                        exc,
                    )
                    report["errors"] += 1

    return report


def _safe(namespace: str) -> str:
    """Validate a namespace string — letters, digits, dashes, underscores."""
    if not namespace:
        raise ValueError("namespace must be non-empty")
    if not all(c.isalnum() or c in ("-", "_") for c in namespace):
        raise ValueError(
            f"namespace {namespace!r} contains invalid characters; "
            "use only [A-Za-z0-9_-]"
        )
    return namespace
