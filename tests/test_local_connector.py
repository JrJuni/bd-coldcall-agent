from src.rag.connectors.local_file import LocalFileConnector


def test_missing_root_yields_nothing(tmp_path):
    conn = LocalFileConnector(tmp_path / "does-not-exist")
    assert list(conn.iter_documents()) == []


def test_reads_markdown_and_txt(tmp_path):
    (tmp_path / "a.md").write_text("# Title A\n\nbody", encoding="utf-8")
    (tmp_path / "b.txt").write_text("plain text here", encoding="utf-8")

    conn = LocalFileConnector(tmp_path)
    docs = sorted(conn.iter_documents(), key=lambda d: d.source_ref)
    assert len(docs) == 2

    md = docs[0]
    assert md.id == "local:a.md"
    assert md.source_type == "local"
    assert md.source_ref == "a.md"
    assert md.mime_type == "text/markdown"
    assert md.title == "a"
    assert "body" in md.content
    assert "size_bytes" in md.extra_metadata

    txt = docs[1]
    assert txt.id == "local:b.txt"
    assert txt.mime_type == "text/plain"
    assert txt.content == "plain text here"


def test_recursive_scan(tmp_path):
    nested = tmp_path / "sub" / "deeper"
    nested.mkdir(parents=True)
    (nested / "note.md").write_text("nested", encoding="utf-8")
    conn = LocalFileConnector(tmp_path)
    docs = list(conn.iter_documents())
    assert len(docs) == 1
    assert docs[0].source_ref == "sub/deeper/note.md"
    assert docs[0].id == "local:sub/deeper/note.md"


def test_empty_file_skipped(tmp_path):
    (tmp_path / "empty.md").write_text("", encoding="utf-8")
    (tmp_path / "whitespace.txt").write_text("   \n\n  \n", encoding="utf-8")
    (tmp_path / "good.md").write_text("content", encoding="utf-8")
    conn = LocalFileConnector(tmp_path)
    docs = list(conn.iter_documents())
    assert [d.source_ref for d in docs] == ["good.md"]


def test_unsupported_extension_ignored(tmp_path):
    (tmp_path / "skip.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
    conn = LocalFileConnector(tmp_path)
    docs = list(conn.iter_documents())
    assert [d.source_ref for d in docs] == ["keep.md"]


def test_custom_extensions(tmp_path):
    (tmp_path / "a.md").write_text("md", encoding="utf-8")
    (tmp_path / "b.txt").write_text("txt", encoding="utf-8")
    conn = LocalFileConnector(tmp_path, extensions=(".md",))
    docs = list(conn.iter_documents())
    assert [d.source_ref for d in docs] == ["a.md"]


def test_last_modified_populated(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("content", encoding="utf-8")
    conn = LocalFileConnector(tmp_path)
    doc = next(iter(conn.iter_documents()))
    assert doc.last_modified is not None
    assert doc.last_modified.tzinfo is not None


def test_pdf_extraction_inserts_page_separators(tmp_path, monkeypatch):
    # Create a placeholder file so the glob picks it up; content bytes
    # don't matter because we stub PdfReader.
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 stub")

    _install_fake_pdf_reader(monkeypatch, ["Page one body.", "Page two body."])

    conn = LocalFileConnector(tmp_path)
    docs = list(conn.iter_documents())
    assert len(docs) == 1
    doc = docs[0]
    assert doc.mime_type == "application/pdf"
    assert doc.extra_metadata.get("page_count") == 2
    assert "[Page 1]" in doc.content
    assert "[Page 2]" in doc.content
    assert "Page one body." in doc.content
    assert "Page two body." in doc.content
    assert doc.content.index("[Page 1]") < doc.content.index("[Page 2]")


def test_empty_pdf_skipped(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 stub")

    _install_fake_pdf_reader(monkeypatch, ["", ""])

    conn = LocalFileConnector(tmp_path)
    assert list(conn.iter_documents()) == []


def test_partial_empty_pdf_kept(tmp_path, monkeypatch):
    """If some pages have text and others are empty, keep the document."""
    pdf_path = tmp_path / "mixed.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 stub")

    _install_fake_pdf_reader(monkeypatch, ["", "real text here", ""])

    conn = LocalFileConnector(tmp_path)
    docs = list(conn.iter_documents())
    assert len(docs) == 1
    assert "real text here" in docs[0].content
    assert docs[0].extra_metadata["page_count"] == 3


def _install_fake_pdf_reader(monkeypatch, page_texts):
    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakeReader:
        def __init__(self, path):
            self.pages = [_FakePage(t) for t in page_texts]

    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", _FakeReader)
