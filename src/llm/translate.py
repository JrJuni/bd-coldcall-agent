"""Article body translation via the local LLM.

Design:
- Passthrough when article.lang == target_lang (no LLM call, no token spend).
- Uses prompt templates in src/prompts/{en,ko}/translate.txt.
- On generation failure falls back to the original body so the pipeline never
  stalls on a single article.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.config.loader import PROJECT_ROOT
from src.llm import local_exaone
from src.search.base import Article, Lang


# Exaone 7.8B occasionally echoes the prompt wrapper tags (<article> ... </article>)
# into its output. Strip any leaked tags before storing translated_body.
_ARTICLE_TAG_RE = re.compile(r"</?\s*article\s*>", re.IGNORECASE)


def _load_template(target_lang: Lang) -> str:
    path = PROJECT_ROOT / "src" / "prompts" / target_lang / "translate.txt"
    return path.read_text(encoding="utf-8")


def _strip_prompt_echo(text: str) -> str:
    return _ARTICLE_TAG_RE.sub("", text).strip()


def translate_article(article: Article, target_lang: Lang) -> Article:
    """Populate article.translated_body. Mutates in place and returns the article."""
    source = article.body or article.snippet
    if not source:
        article.translated_body = ""
        return article

    if article.lang == target_lang:
        # Same language — no translation needed.
        article.translated_body = source
        return article

    template = _load_template(target_lang)
    prompt = template.replace("{body}", source)
    try:
        translated = local_exaone.generate(
            prompt,
            max_new_tokens=min(2048, max(256, len(source) // 2)),
            temperature=0.0,
        )
    except Exception:
        translated = source  # safe fallback — keep pipeline moving
    article.translated_body = _strip_prompt_echo(translated) or source
    return article


def translate_articles(articles: list[Article], target_lang: Lang) -> list[Article]:
    for a in articles:
        translate_article(a, target_lang)
    return articles
