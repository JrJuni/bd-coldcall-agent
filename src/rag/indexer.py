"""Incremental indexer — connectors → normalize → hash → embed → store + manifest.

Documents whose normalized content hash matches the manifest are skipped. The
delete-detection pass is scoped to source types that actually ran, so a local-
only or notion-only invocation never evicts documents from the other source.

Atomicity: embeddings must succeed before the store is mutated. If `embed_fn`
or the chunker raises for a doc, neither `VectorStore` nor `manifest.json`
are touched for that doc — the error is logged and counted, and the next
run detects the doc as `updated` again.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from src.rag.chunker import chunk_document
from src.rag.connectors.base import SourceConnector
from src.rag.embeddings import embed_texts
from src.rag.namespace import (
    DEFAULT_NAMESPACE,
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    company_docs_root_for,
    ensure_namespace,
    list_namespaces,
    migrate_flat_layout,
    vectorstore_root_for,
)
from src.rag.normalize import normalize_content
from src.rag.store import VectorStore
from src.rag.types import Document
from src.rag.workspaces import list_workspace_slugs, workspace_paths


_LOGGER = logging.getLogger(__name__)


EmbedFn = Callable[[list[str]], np.ndarray]


@dataclass
class IndexReport:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    errors: int = 0
    chunks_total: int = 0
    elapsed_seconds: float = 0.0

    def describe(self) -> str:
        return (
            f"added={self.added} updated={self.updated} "
            f"skipped={self.skipped} deleted={self.deleted} "
            f"errors={self.errors} chunks_total={self.chunks_total} "
            f"elapsed={self.elapsed_seconds:.2f}s"
        )


def manifest_path_for(vectorstore_path: Path) -> Path:
    return Path(vectorstore_path) / MANIFEST_FILENAME


def _fresh_manifest() -> dict:
    return {"version": MANIFEST_VERSION, "updated_at": None, "documents": {}}


def load_manifest(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return _fresh_manifest()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning(
            "manifest: failed to read %s (%s) — starting fresh", path, exc
        )
        return _fresh_manifest()
    if data.get("version") != MANIFEST_VERSION:
        _LOGGER.warning(
            "manifest: version %s != %s — treating as fresh",
            data.get("version"),
            MANIFEST_VERSION,
        )
        return _fresh_manifest()
    data.setdefault("documents", {})
    return data


def save_manifest(path: Path, manifest: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)  # os.replace — atomic within a filesystem


def _hash_normalized(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def run_indexer(
    connectors: Iterable[SourceConnector],
    *,
    store: VectorStore,
    manifest_path: Path,
    chunk_size: int,
    chunk_overlap: int,
    min_document_chars: int,
    embed_fn: EmbedFn = embed_texts,
    force: bool = False,
    dry_run: bool = False,
) -> IndexReport:
    start = time.perf_counter()
    report = IndexReport()

    connectors = list(connectors)
    active_source_types = {c.source_type for c in connectors}

    manifest = load_manifest(manifest_path)
    documents_state: dict = manifest["documents"]
    seen: set[str] = set()

    for connector in connectors:
        try:
            iterator = connector.iter_documents()
        except Exception as exc:
            _LOGGER.error(
                "indexer: connector %s init failed: %s",
                connector.source_type,
                exc,
            )
            report.errors += 1
            continue
        for doc in iterator:
            try:
                _process_document(
                    doc,
                    documents_state=documents_state,
                    seen=seen,
                    store=store,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    min_document_chars=min_document_chars,
                    embed_fn=embed_fn,
                    force=force,
                    dry_run=dry_run,
                    report=report,
                )
            except Exception as exc:
                _LOGGER.warning("indexer: doc %s failed: %s", doc.id, exc)
                report.errors += 1

    stale_ids = [
        doc_id
        for doc_id, entry in documents_state.items()
        if entry.get("source_type") in active_source_types
        and doc_id not in seen
    ]
    for doc_id in stale_ids:
        try:
            if not dry_run:
                store.delete_document(doc_id)
                documents_state.pop(doc_id, None)
            report.deleted += 1
        except Exception as exc:
            _LOGGER.warning("indexer: delete %s failed: %s", doc_id, exc)
            report.errors += 1

    if not dry_run:
        save_manifest(manifest_path, manifest)

    report.elapsed_seconds = time.perf_counter() - start
    return report


def _process_document(
    doc: Document,
    *,
    documents_state: dict,
    seen: set[str],
    store: VectorStore,
    chunk_size: int,
    chunk_overlap: int,
    min_document_chars: int,
    embed_fn: EmbedFn,
    force: bool,
    dry_run: bool,
    report: IndexReport,
) -> None:
    seen.add(doc.id)

    norm = normalize_content(doc.content)
    if not norm:
        _LOGGER.warning(
            "indexer: empty normalized content for %s, skipping", doc.id
        )
        return

    if len(norm) < min_document_chars:
        _LOGGER.warning(
            "indexer: short_document %s (%d chars < %d), indexing anyway",
            doc.id,
            len(norm),
            min_document_chars,
        )

    content_hash = _hash_normalized(norm)
    prior = documents_state.get(doc.id)
    if prior and not force and prior.get("content_hash") == content_hash:
        report.skipped += 1
        return

    chunks = chunk_document(
        doc, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    if not chunks:
        _LOGGER.warning(
            "indexer: chunker produced no chunks for %s, skipping", doc.id
        )
        return

    if dry_run:
        if prior is None:
            report.added += 1
        else:
            report.updated += 1
        report.chunks_total += len(chunks)
        return

    texts = [c.text for c in chunks]
    embeddings = embed_fn(texts)
    if len(embeddings) != len(chunks):
        raise ValueError(
            f"embed returned {len(embeddings)} vectors for {len(chunks)} chunks"
        )

    store.delete_document(doc.id)
    store.upsert_chunks(chunks, embeddings)

    documents_state[doc.id] = {
        "content_hash": content_hash,
        "last_modified": _iso(doc.last_modified),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "chunk_count": len(chunks),
        "source_type": doc.source_type,
    }
    if prior is None:
        report.added += 1
    else:
        report.updated += 1
    report.chunks_total += len(chunks)


def verify(store: VectorStore, manifest_path: Path) -> dict:
    manifest = load_manifest(manifest_path)
    manifest_ids = set(manifest.get("documents", {}).keys())
    store_ids = store.all_doc_ids()
    return {
        "manifest_only": sorted(manifest_ids - store_ids),
        "store_only": sorted(store_ids - manifest_ids),
        "matched": len(manifest_ids & store_ids),
    }


# ---- CLI ---------------------------------------------------------------


def _build_connectors(
    *,
    local_dir: Path | None,
    use_notion: bool,
) -> list[SourceConnector]:
    from src.config.loader import get_secrets, get_targets

    connectors: list[SourceConnector] = []
    if local_dir is not None:
        from src.rag.connectors.local_file import LocalFileConnector

        if not local_dir.exists():
            _LOGGER.warning(
                "indexer: --local-dir %s missing, skipping local", local_dir
            )
        else:
            connectors.append(LocalFileConnector(local_dir))
    if use_notion:
        secrets = get_secrets()
        if not secrets.notion_token:
            raise SystemExit("--notion requires NOTION_TOKEN in .env")
        targets = get_targets()
        if not (targets.rag.notion_page_ids or targets.rag.notion_database_ids):
            raise SystemExit(
                "--notion set but targets.yaml.rag has no page_ids "
                "or database_ids"
            )
        from src.rag.connectors.notion import NotionConnector

        connectors.append(
            NotionConnector(
                token=secrets.notion_token,
                page_ids=targets.rag.notion_page_ids,
                database_ids=targets.rag.notion_database_ids,
            )
        )
    return connectors


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from src.config.loader import get_settings

    parser = argparse.ArgumentParser(
        description="Index local + Notion docs into ChromaDB with incremental hashing"
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default="default",
        help=(
            "Workspace slug — picks the source root + per-ws vectorstore "
            "(default: 'default' which maps to data/company_docs)"
        ),
    )
    parser.add_argument(
        "--all-workspaces",
        action="store_true",
        help=(
            "Index every registered workspace in turn. Overrides --workspace. "
            "Only the local connector is run per workspace; --notion still "
            "applies on top of whatever workspace is currently being indexed."
        ),
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default=DEFAULT_NAMESPACE,
        help=(
            "Sub-namespace inside the workspace — separates ChromaDB persist "
            f"dir + manifest per sub-folder (default: {DEFAULT_NAMESPACE!r})"
        ),
    )
    parser.add_argument(
        "--list-namespaces",
        action="store_true",
        help="List available namespaces (those with a manifest.json) and exit",
    )
    parser.add_argument(
        "--create-namespace",
        type=str,
        default=None,
        help="Create empty workspace dirs for the given namespace and exit",
    )
    parser.add_argument(
        "--local-dir",
        type=Path,
        default=None,
        help=(
            "Root for the local connector (default: "
            "data/company_docs/<namespace>)"
        ),
    )
    parser.add_argument(
        "--no-local",
        action="store_true",
        help="Disable the local connector entirely",
    )
    parser.add_argument(
        "--notion",
        action="store_true",
        help="Enable the Notion connector (requires NOTION_TOKEN + targets.yaml ids)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass hash comparison and reindex every document",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan + hash + chunk but don't embed, upsert, or write manifest",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Report manifest/store drift and exit without mutating anything",
    )
    args = parser.parse_args(argv)

    settings = get_settings()

    def _run_one_workspace(ws_slug: str) -> int:
        try:
            ws_vs_root, ws_cd_root = workspace_paths(ws_slug)
        except KeyError:
            print(f"workspace not found: {ws_slug!r}", file=sys.stderr)
            return 1

        # Best-effort migration for legacy flat layout — only meaningful for
        # the default workspace, where Phase 10 P10-2a left flat data behind.
        if ws_slug == "default":
            mig = migrate_flat_layout(
                vectorstore_root=ws_vs_root,
                company_docs_root=ws_cd_root,
            )
            if any(v for k, v in mig.items() if k != "errors"):
                _LOGGER.info("namespace migration: %s", mig)

        # ── Maintenance commands (no indexing) ─────────────────────────
        if args.list_namespaces:
            for name in list_namespaces(ws_vs_root):
                print(f"{ws_slug}: {name}" if args.all_workspaces else name)
            return 0
        if args.create_namespace is not None:
            vs_dir, cd_dir = ensure_namespace(
                vectorstore_root=ws_vs_root,
                company_docs_root=ws_cd_root,
                namespace=args.create_namespace,
            )
            print(f"[{ws_slug}] created vectorstore: {vs_dir}")
            print(f"[{ws_slug}] created docs:        {cd_dir}")
            return 0

        # ── Resolve namespace-scoped paths ─────────────────────────────
        namespace = args.namespace
        ns_vs_path = vectorstore_root_for(ws_vs_root, namespace)
        ns_vs_path.mkdir(parents=True, exist_ok=True)
        mpath = manifest_path_for(ns_vs_path)

        if args.local_dir is None:
            local_dir_default = company_docs_root_for(ws_cd_root, namespace)
        else:
            local_dir_default = args.local_dir

        store = VectorStore(
            persist_path=ns_vs_path,
            collection_name=settings.rag.collection_name,
        )

        if args.verify:
            result = verify(store, mpath)
            print(
                f"verify [{ws_slug}/{namespace}]: matched={result['matched']} "
                f"manifest_only={len(result['manifest_only'])} "
                f"store_only={len(result['store_only'])}"
            )
            for doc_id in result["manifest_only"]:
                print(f"  manifest_only: {doc_id}")
            for doc_id in result["store_only"]:
                print(f"  store_only:    {doc_id}")
            return 0

        local_dir = None if args.no_local else local_dir_default
        connectors = _build_connectors(
            local_dir=local_dir, use_notion=args.notion
        )
        if not connectors:
            print(
                f"[{ws_slug}] No connectors enabled — pass --notion or supply "
                "--local-dir pointing at an existing directory.",
                file=sys.stderr,
            )
            return 1

        report = run_indexer(
            connectors,
            store=store,
            manifest_path=mpath,
            chunk_size=settings.rag.chunk_size,
            chunk_overlap=settings.rag.chunk_overlap,
            min_document_chars=settings.rag.min_document_chars,
            force=args.force,
            dry_run=args.dry_run,
        )
        tag = " (dry-run)" if args.dry_run else ""
        print(f"indexer{tag} [{ws_slug}/{namespace}]: {report.describe()}")
        return 0

    if args.all_workspaces:
        slugs = list_workspace_slugs() or ["default"]
    else:
        slugs = [args.workspace]

    final_rc = 0
    for slug in slugs:
        rc = _run_one_workspace(slug)
        if rc != 0:
            final_rc = rc
    return final_rc


if __name__ == "__main__":
    raise SystemExit(main())
