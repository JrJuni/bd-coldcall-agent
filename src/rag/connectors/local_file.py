"""LocalFileConnector — recursive MD / TXT / PDF → Document stream.

PDF extraction preserves page boundaries with `\n\n[Page N]\n\n` separators
so chunker output can still map back to a page if needed downstream. Scan
PDFs that yield empty text per page are skipped with a warn — OCR is a
Phase 9+ backlog item.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Iterator

from src.rag.connectors.base import SourceConnector
from src.rag.types import Document


_LOGGER = logging.getLogger(__name__)


DEFAULT_EXTENSIONS = (".md", ".txt", ".pdf")


_MIME_BY_EXT = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
}


class LocalFileConnector(SourceConnector):
    source_type: ClassVar[str] = "local"

    def __init__(
        self,
        root_dir: Path,
        extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    ):
        self.root_dir = Path(root_dir)
        self.extensions = tuple(e.lower() for e in extensions)

    def iter_documents(self) -> Iterator[Document]:
        if not self.root_dir.exists():
            _LOGGER.warning(
                "local_connector: root_dir %s missing, skipping", self.root_dir
            )
            return
        for path in sorted(self.root_dir.rglob("*")):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext not in self.extensions:
                continue
            doc = self._build_document(path, ext)
            if doc is not None:
                yield doc

    def _build_document(self, path: Path, ext: str) -> Document | None:
        try:
            rel = path.relative_to(self.root_dir).as_posix()
        except ValueError:
            rel = path.name
        doc_id = f"local:{rel}"
        try:
            stat = path.stat()
            last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        except OSError as exc:
            _LOGGER.warning("local_connector: stat failed for %s: %s", path, exc)
            return None

        if ext == ".pdf":
            content, extra = _read_pdf(path)
        else:
            content, extra = _read_text(path, stat.st_size)

        if content is None:
            return None
        if not content.strip():
            _LOGGER.warning(
                "local_connector: empty content for %s, skipping", path
            )
            return None

        title = path.stem or "Untitled"
        return Document(
            id=doc_id,
            source_type="local",
            source_ref=rel,
            title=title,
            content=content,
            last_modified=last_modified,
            mime_type=_MIME_BY_EXT.get(ext, "application/octet-stream"),
            extra_metadata=extra,
        )


def _read_text(path: Path, size_bytes: int) -> tuple[str | None, dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _LOGGER.warning("local_connector: read failed for %s: %s", path, exc)
        return None, {}
    return text, {"size_bytes": size_bytes}


def _read_pdf(path: Path) -> tuple[str | None, dict]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        _LOGGER.warning(
            "local_connector: pypdf missing for %s: %s", path, exc
        )
        return None, {}
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        _LOGGER.warning("local_connector: PdfReader failed for %s: %s", path, exc)
        return None, {}

    page_count = len(reader.pages)
    page_texts: list[str] = []
    non_empty = 0
    for idx, page in enumerate(reader.pages, start=1):
        try:
            raw = (page.extract_text() or "").strip()
        except Exception as exc:
            _LOGGER.warning(
                "local_connector: page %d extract failed for %s: %s",
                idx,
                path,
                exc,
            )
            raw = ""
        if raw:
            non_empty += 1
        page_texts.append(f"[Page {idx}]\n{raw}")

    extra = {"page_count": page_count}
    if non_empty == 0:
        _LOGGER.warning(
            "local_connector: no extractable text in %s (scan PDF?), skipping",
            path,
        )
        return None, extra
    content = "\n\n".join(page_texts).strip()
    return content, extra
