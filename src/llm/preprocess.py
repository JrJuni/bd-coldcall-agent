"""Phase 2 preprocessor: translate → tag → dedup.

Composes the three deterministic local-LLM steps over a batch of articles.
Returns (kept_articles, meta) where `meta` includes the dedup report and
per-stage counts for logging/intermediate artifacts.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from src.config.loader import get_settings
from src.llm.tag import tag_articles
from src.llm.translate import translate_articles
from src.rag.embeddings import dedup_articles
from src.search.base import Article, Lang


def preprocess_articles(
    articles: list[Article],
    *,
    target_lang: Optional[Lang] = None,
    run_translate: bool = True,
    run_tag: bool = True,
    run_dedup: bool = True,
) -> tuple[list[Article], dict]:
    """Translate → tag → dedup. Each stage can be skipped via flag (useful for tests)."""
    settings = get_settings()
    lang = target_lang or settings.search.default_lang

    n_in = len(articles)
    translated = 0
    tagged = 0

    if run_translate:
        for a in articles:
            before = a.translated_body
            translate_articles([a], lang)
            if a.translated_body != before:
                translated += 1

    if run_tag:
        tag_articles(articles, lang)
        tagged = sum(1 for a in articles if a.tags)

    if run_dedup:
        kept, report = dedup_articles(articles)
        dedup_meta = asdict(report)
    else:
        kept = list(articles)
        dedup_meta = None

    max_n = settings.search.max_articles
    if len(kept) > max_n:
        kept = kept[:max_n]

    meta = {
        "target_lang": lang,
        "n_input": n_in,
        "n_translated": translated,
        "n_tagged": tagged,
        "n_output": len(kept),
        "dedup": dedup_meta,
    }
    return kept, meta


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from datetime import datetime
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    from src.config.loader import PROJECT_ROOT

    parser = argparse.ArgumentParser(
        description="Phase 2 preprocess (translate + tag + dedup) on a saved Brave JSON."
    )
    parser.add_argument("--input", required=True, help="Path to outputs/search/*.json")
    parser.add_argument("--lang", default=None, choices=["en", "ko"],
                        help="Target language (defaults to settings.search.default_lang)")
    parser.add_argument("--no-translate", dest="run_translate", action="store_false")
    parser.add_argument("--no-tag", dest="run_tag", action="store_false")
    parser.add_argument("--no-dedup", dest="run_dedup", action="store_false")
    parser.add_argument("--save", action="store_true",
                        help="Write enriched batch to outputs/preprocess/")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    def _load_article(d: dict) -> Article:
        pub = d.get("published_at")
        return Article(
            title=d.get("title", ""),
            url=d.get("url", ""),
            snippet=d.get("snippet", ""),
            source=d.get("source", ""),
            lang=d.get("lang", "en"),
            published_at=datetime.fromisoformat(pub) if pub else None,
            metadata=d.get("metadata", {}) or {},
            body=d.get("body", "") or "",
            body_source=d.get("body_source", "empty"),
        )

    articles = [_load_article(a) for a in data.get("articles", [])]
    print(f"[preprocess] input={len(articles)} lang={args.lang or '(default)'}",
          file=sys.stderr)

    kept, meta = preprocess_articles(
        articles,
        target_lang=args.lang,
        run_translate=args.run_translate,
        run_tag=args.run_tag,
        run_dedup=args.run_dedup,
    )
    if meta.get("dedup"):
        from src.rag.embeddings import DedupReport
        report = DedupReport(**meta["dedup"])
        print(f"[preprocess] {report.describe()}", file=sys.stderr)
    print(f"[preprocess] translated={meta['n_translated']} tagged={meta['n_tagged']} "
          f"kept={meta['n_output']}", file=sys.stderr)

    for i, a in enumerate(kept, 1):
        print(f"{i}. [{','.join(a.tags) or '-'}] {a.title} ({a.source})")
        preview = (a.translated_body or a.body)[:120].replace("\n", " ")
        if preview:
            print(f"   {preview}{'…' if len(a.translated_body or a.body) > 120 else ''}")
        print()

    if args.save:
        out_dir = PROJECT_ROOT / "outputs" / "preprocess"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"{stamp}_{meta['target_lang']}.json"

        def _dump(a: Article) -> dict:
            d = asdict(a)
            if d.get("published_at") is not None:
                d["published_at"] = d["published_at"].isoformat()
            return d

        out_path.write_text(
            json.dumps(
                {"meta": meta, "articles": [_dump(a) for a in kept]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Saved: {out_path.relative_to(PROJECT_ROOT)}", file=sys.stderr)
