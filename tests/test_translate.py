from src.llm.translate import _strip_prompt_echo


def test_strips_leading_article_tag():
    raw = "<article>\nHello world.\n"
    assert _strip_prompt_echo(raw) == "Hello world."


def test_strips_trailing_close_tag():
    raw = "Translated body.\n</article>"
    assert _strip_prompt_echo(raw) == "Translated body."


def test_strips_both_tags():
    raw = "<article>\nBody line 1.\nBody line 2.\n</article>\n"
    assert _strip_prompt_echo(raw) == "Body line 1.\nBody line 2."


def test_case_insensitive_and_whitespace_tolerant():
    raw = "< Article >\nText.\n</ ARTICLE >"
    assert _strip_prompt_echo(raw) == "Text."


def test_passthrough_when_no_tags():
    assert _strip_prompt_echo("Plain translation.") == "Plain translation."


def test_empty_string():
    assert _strip_prompt_echo("") == ""
    assert _strip_prompt_echo("   \n  ") == ""
