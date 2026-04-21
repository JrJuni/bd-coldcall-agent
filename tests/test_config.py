from src.config.schemas import CollectionOverride, Industry, Targets


def test_collection_override_new_fields_default_to_none():
    co = CollectionOverride()
    assert co.bilingual is None
    assert co.foreign_ratio is None


def test_collection_override_accepts_bilingual_and_ratio():
    co = CollectionOverride(bilingual=False, foreign_ratio=0.0)
    assert co.bilingual is False
    assert co.foreign_ratio == 0.0


def test_industry_has_default_empty_collection_override():
    ind = Industry(keywords_ko=["공공기관 AI"])
    # No override specified — inherit from global settings.
    assert ind.collection.bilingual is None
    assert ind.collection.foreign_ratio is None


def test_industry_accepts_per_industry_override():
    ind = Industry(
        keywords_ko=["공공기관 AI"],
        collection={"bilingual": False, "foreign_ratio": 0.0},
    )
    assert ind.collection.bilingual is False
    assert ind.collection.foreign_ratio == 0.0


def test_targets_parses_per_industry_collection_override():
    raw = {
        "industries": {
            "semiconductor": {
                "keywords_en": ["semiconductor"],
                "keywords_ko": ["반도체"],
            },
            "public_sector_kr": {
                "keywords_ko": ["공공기관 AI"],
                "collection": {"bilingual": False, "foreign_ratio": 0.0},
            },
        },
        "targets": [
            {"name": "NVIDIA", "industry": "semiconductor"},
        ],
    }
    parsed = Targets(**raw)
    assert parsed.industries["semiconductor"].collection.bilingual is None
    assert parsed.industries["public_sector_kr"].collection.bilingual is False
    assert parsed.industries["public_sector_kr"].collection.foreign_ratio == 0.0
    # Global collection block is independent and stays at defaults.
    assert parsed.collection.bilingual is None
