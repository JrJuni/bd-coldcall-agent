"""9-tag classification for articles via the local LLM.

Fixed ENUM; anything off-list collapses to ["other"]. Output is strict JSON and
parsed defensively — any parse failure also collapses to ["other"]."""
from __future__ import annotations

import json
import re
from typing import Iterable

from src.config.loader import PROJECT_ROOT
from src.llm import local_exaone
from src.search.base import Article, Lang


TAG_ENUM: tuple[str, ...] = (
    "earnings",
    "product_launch",
    "partnership",
    "leadership",
    "regulatory",
    "funding",
    "m_and_a",
    "tech_launch",
    "other",
)

_TAG_SET = set(TAG_ENUM)
_JSON_OBJ_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _load_template(target_lang: Lang) -> str:
    path = PROJECT_ROOT / "src" / "prompts" / target_lang / "tag.txt"
    return path.read_text(encoding="utf-8")


def parse_tags(raw: str) -> list[str]:
    """Extract a tag list from arbitrary LLM output.

    Tolerates: extra prose around the JSON, trailing commas, unknown tags.
    Always returns a non-empty list — falls back to ["other"] on any trouble.
    """
    if not raw:
        return ["other"]
    match = _JSON_OBJ_RE.search(raw)
    if not match:
        return ["other"]
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ["other"]
    tags = obj.get("tags") if isinstance(obj, dict) else None
    if not isinstance(tags, list):
        return ["other"]
    cleaned: list[str] = []
    seen: set[str] = set()
    for t in tags:
        if not isinstance(t, str):
            continue
        norm = t.strip().lower().replace("-", "_").replace(" ", "_")
        if norm == "ma" or norm == "m&a":
            norm = "m_and_a"
        if norm in _TAG_SET and norm not in seen:
            cleaned.append(norm)
            seen.add(norm)
        if len(cleaned) >= 3:
            break
    return cleaned or ["other"]


def tag_article(article: Article, target_lang: Lang) -> Article:
    source = article.translated_body or article.body or article.snippet
    if not source:
        article.tags = ["other"]
        return article
    template = _load_template(target_lang)
    prompt = template.replace("{title}", article.title).replace("{body}", source[:4000])
    try:
        raw = local_exaone.generate(
            prompt,
            max_new_tokens=64,
            temperature=0.0,
        )
    except Exception:
        article.tags = ["other"]
        return article
    article.tags = parse_tags(raw)
    return article


def tag_articles(articles: Iterable[Article], target_lang: Lang) -> list[Article]:
    out: list[Article] = []
    for a in articles:
        tag_article(a, target_lang)
        out.append(a)
    return out
