from datetime import datetime, timezone

from src.rag.chunker import chunk_document
from src.rag.types import Document


def _doc(content: str, *, doc_id: str = "local:sample.md") -> Document:
    return Document(
        id=doc_id,
        source_type="local",
        source_ref="sample.md",
        title="Sample",
        content=content,
        last_modified=datetime(2026, 4, 20, tzinfo=timezone.utc),
        mime_type="text/markdown",
        extra_metadata={"size_bytes": 42},
    )


def test_empty_returns_no_chunks():
    assert chunk_document(_doc(""), chunk_size=100, chunk_overlap=20) == []
    assert chunk_document(_doc("   \n\n  \n"), chunk_size=100, chunk_overlap=20) == []


def test_short_document_becomes_single_chunk():
    chunks = chunk_document(_doc("Hello world."), chunk_size=500, chunk_overlap=50)
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].chunk_index == 0
    assert chunks[0].id == "local:sample.md::0"


def test_multiple_sentences_pack_into_one_chunk_when_fit():
    text = "First sentence. Second sentence. Third sentence."
    chunks = chunk_document(_doc(text), chunk_size=200, chunk_overlap=20)
    assert len(chunks) == 1
    assert "First sentence." in chunks[0].text
    assert "Third sentence." in chunks[0].text


def test_splits_when_exceeds_chunk_size():
    # Each sentence ~20 chars; chunk_size=50 forces a break
    text = "Sentence one here. Sentence two here. Sentence three here. Sentence four here."
    chunks = chunk_document(_doc(text), chunk_size=50, chunk_overlap=0)
    assert len(chunks) >= 2
    # Each chunk stays within size limit
    assert all(len(c.text) <= 50 for c in chunks)


def test_sentence_level_overlap_carries_previous_sentence():
    # Three sentences of ~30 chars each; chunk_size=70 fits two per chunk.
    # With overlap=30, the second chunk should start with the last sentence of
    # the first chunk.
    s1 = "Alpha beta gamma delta epsilon."      # 31 chars
    s2 = "Zeta eta theta iota kappa."           # 26
    s3 = "Lambda mu nu xi omicron."             # 24
    text = " ".join([s1, s2, s3])
    chunks = chunk_document(_doc(text), chunk_size=60, chunk_overlap=30)
    assert len(chunks) >= 2
    # First chunk should contain s1. Second should begin with a prior sentence
    # (either s1 or s2) to provide overlap context.
    first = chunks[0].text
    second = chunks[1].text
    assert s1 in first or s2 in first
    # Overlap: second chunk shares at least one full sentence with first.
    shared = any(s in first and s in second for s in (s1, s2, s3))
    assert shared, f"expected sentence-level overlap between chunks: {chunks}"


def test_no_overlap_when_chunk_overlap_zero():
    s1 = "Alpha beta gamma delta epsilon."
    s2 = "Zeta eta theta iota kappa lambda."
    s3 = "Mu nu xi omicron pi rho sigma."
    text = " ".join([s1, s2, s3])
    chunks = chunk_document(_doc(text), chunk_size=40, chunk_overlap=0)
    assert len(chunks) >= 2
    # No sentence should appear in more than one chunk
    for s in (s1, s2, s3):
        hits = sum(1 for c in chunks if s in c.text)
        assert hits <= 1


def test_long_single_sentence_hard_splits_by_chars():
    # A single sentence with no internal boundary longer than chunk_size
    # must fall back to character-level splitting.
    long_sentence = "A" * 500 + "."  # 501 chars, no whitespace/period in middle
    chunks = chunk_document(_doc(long_sentence), chunk_size=100, chunk_overlap=20)
    assert len(chunks) >= 5
    assert all(len(c.text) <= 100 for c in chunks)


def test_hard_split_applies_char_overlap():
    long_sentence = "X" * 300
    chunks = chunk_document(_doc(long_sentence), chunk_size=100, chunk_overlap=30)
    # step = size - overlap = 70; starts at [0, 70, 140, 210]; last slice is 90 chars
    assert len(chunks) == 4
    assert len(chunks[-1].text) <= 100
    for i in range(len(chunks) - 1):
        # Adjacent chunks share the overlap window at the boundary
        assert chunks[i].text[-30:] == chunks[i + 1].text[:30]


def test_paragraph_boundary_acts_as_unit_boundary():
    # No sentence punctuation, just paragraph breaks
    text = "paragraph one here\n\nparagraph two here\n\nparagraph three here"
    chunks = chunk_document(_doc(text), chunk_size=25, chunk_overlap=0)
    # Each paragraph is a unit; with chunk_size=25 each becomes its own chunk
    assert len(chunks) == 3
    assert chunks[0].text == "paragraph one here"
    assert chunks[1].text == "paragraph two here"
    assert chunks[2].text == "paragraph three here"


def test_chunk_inherits_document_fields():
    chunks = chunk_document(_doc("Alpha beta gamma."), chunk_size=100, chunk_overlap=0)
    c = chunks[0]
    assert c.doc_id == "local:sample.md"
    assert c.title == "Sample"
    assert c.source_type == "local"
    assert c.source_ref == "sample.md"
    assert c.mime_type == "text/markdown"
    assert c.last_modified is not None
    assert c.extra_metadata == {"size_bytes": 42}


def test_korean_sentences_split_on_paragraph_breaks():
    text = (
        "한국어 첫 번째 문장입니다\n\n"
        "두 번째 문단 내용이 들어갑니다\n\n"
        "세 번째 문단도 별도로 분리되어야 합니다"
    )
    # Lens: [14, 17, 22]; chunk_size=25 forces each paragraph into its own chunk
    chunks = chunk_document(_doc(text), chunk_size=25, chunk_overlap=0)
    assert len(chunks) == 3
    assert "첫 번째" in chunks[0].text
    assert "두 번째" in chunks[1].text
    assert "세 번째" in chunks[2].text


def test_chunk_ids_are_sequential_and_unique():
    text = ". ".join(f"sentence {i} filler content here" for i in range(20)) + "."
    chunks = chunk_document(_doc(text), chunk_size=80, chunk_overlap=20)
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    for idx, c in enumerate(chunks):
        assert c.chunk_index == idx
        assert c.id.endswith(f"::{idx}")
