from src.rag.normalize import normalize_content


def test_empty_returns_empty():
    assert normalize_content("") == ""
    assert normalize_content("   \n  \n\n") == ""


def test_strips_trailing_whitespace_per_line():
    raw = "hello   \nworld\t\t\n"
    assert normalize_content(raw) == "hello\nworld"


def test_caps_blank_lines_to_two():
    raw = "a\n\n\n\n\nb"
    assert normalize_content(raw) == "a\n\nb"


def test_preserves_double_newline_paragraph_break():
    raw = "para1\n\npara2"
    assert normalize_content(raw) == "para1\n\npara2"


def test_preserves_internal_multiple_spaces():
    # Tables / code / ASCII art depend on internal runs of spaces.
    raw = "col1    col2    col3"
    assert normalize_content(raw) == "col1    col2    col3"


def test_preserves_leading_indent():
    raw = "def foo():\n    return 1\n"
    assert normalize_content(raw) == "def foo():\n    return 1"


def test_strips_outer_whitespace():
    raw = "\n\n  hello\n"
    assert normalize_content(raw) == "hello"


def test_idempotent():
    raw = "mixed  \n\n\n\ncontent  \n"
    once = normalize_content(raw)
    assert normalize_content(once) == once


def test_korean_text_preserved():
    raw = "한글 테스트   \n\n\n\n두번째 단락"
    assert normalize_content(raw) == "한글 테스트\n\n두번째 단락"
