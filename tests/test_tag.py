from src.llm.tag import TAG_ENUM, parse_tags


def test_valid_tags_parsed():
    assert parse_tags('{"tags": ["earnings", "m_and_a"]}') == ["earnings", "m_and_a"]


def test_garbage_input_falls_back():
    assert parse_tags("nonsense") == ["other"]
    assert parse_tags("") == ["other"]


def test_unknown_tags_filtered_out():
    assert parse_tags('{"tags": ["banana", "earnings"]}') == ["earnings"]


def test_all_unknown_falls_back_to_other():
    assert parse_tags('{"tags": ["banana", "apple"]}') == ["other"]


def test_m_and_a_alias_variants():
    assert parse_tags('{"tags": ["M&A"]}') == ["m_and_a"]
    assert parse_tags('{"tags": ["ma"]}') == ["m_and_a"]


def test_dash_normalization():
    assert parse_tags('{"tags": ["product-launch"]}') == ["product_launch"]


def test_extra_prose_around_json():
    assert parse_tags('Sure: {"tags": ["earnings"]} done.') == ["earnings"]


def test_max_three_tags():
    out = parse_tags('{"tags": ["earnings", "m_and_a", "partnership", "funding"]}')
    assert len(out) == 3


def test_enum_is_frozen_at_nine_tags():
    # If this fails, update prompts + downstream tier logic accordingly.
    assert len(TAG_ENUM) == 9
    assert set(TAG_ENUM) == {
        "earnings", "product_launch", "partnership", "leadership",
        "regulatory", "funding", "m_and_a", "tech_launch", "other",
    }
