from datetime import datetime

import httpx

from .base import Article, Kind, Lang, SearchProvider


class BraveSearch(SearchProvider):
    """Brave Search API client (news and web endpoints)."""

    BASE_URL = "https://api.search.brave.com/res/v1"

    def __init__(self, api_key: str, *, timeout: float = 15.0):
        if not api_key:
            raise ValueError("Brave Search API key is required")
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BraveSearch":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def search(
        self,
        query: str,
        *,
        lang: Lang,
        days: int,
        kind: Kind = "news",
        count: int = 10,
    ) -> list[Article]:
        path = "/news/search" if kind == "news" else "/web/search"
        params = {
            "q": query,
            "count": min(count, 20),
            "search_lang": lang,
            "freshness": _freshness(days),
            "country": "KR" if lang == "ko" else "US",
        }
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return self._parse(resp.json(), kind=kind, lang=lang)

    @staticmethod
    def _parse(data: dict, *, kind: Kind, lang: Lang) -> list[Article]:
        if kind == "news":
            items = data.get("results", [])
        else:
            items = (data.get("web") or {}).get("results", [])

        out: list[Article] = []
        for item in items:
            url = item.get("url") or ""
            if not url:
                continue
            out.append(
                Article(
                    title=(item.get("title") or "").strip(),
                    url=url,
                    snippet=(item.get("description") or "").strip(),
                    source=_hostname(item),
                    lang=lang,
                    published_at=_parse_iso(item.get("page_age")),
                    metadata={"kind": kind, "age": item.get("age")},
                )
            )
        return out


def _freshness(days: int) -> str:
    # Brave freshness codes: pd (past day), pw (past week), pm (past month), py (past year)
    if days <= 1:
        return "pd"
    if days <= 7:
        return "pw"
    if days <= 31:
        return "pm"
    return "py"


def _hostname(item: dict) -> str:
    meta = item.get("meta_url") or {}
    return meta.get("hostname") or item.get("source") or ""


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from dataclasses import asdict
    from datetime import datetime
    from pathlib import Path

    # Windows default stdout codec is cp949/cp1252 — force UTF-8 so non-ASCII
    # (e.g. Korean) output renders correctly when piped or written to file.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    from src.config.loader import PROJECT_ROOT, get_secrets, get_settings
    from src.search.bilingual import bilingual_news_search

    parser = argparse.ArgumentParser(description="Probe the Brave Search API")
    parser.add_argument("--query", required=True)
    parser.add_argument("--lang", default="en", choices=["en", "ko"])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--kind", default="news", choices=["news", "web"])
    parser.add_argument(
        "--bilingual",
        dest="bilingual",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override bilingual mode (default: auto — on when --lang ko and settings.search.bilingual_on_ko)",
    )
    parser.add_argument(
        "--foreign-ratio",
        dest="foreign_ratio",
        type=float,
        default=None,
        help="Override min_foreign_ratio for bilingual blending (0.0-1.0). "
             "Default: settings.search.min_foreign_ratio.",
    )
    parser.add_argument(
        "--fetch-bodies",
        dest="fetch_bodies",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Fetch full article bodies via trafilatura (opt-in; slower, 5~15s more).",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Also write results as JSON + Markdown to outputs/search/",
    )
    args = parser.parse_args()

    secrets = get_secrets()
    if not secrets.brave_search_api_key:
        raise SystemExit("BRAVE_SEARCH_API_KEY is not set in .env")

    settings = get_settings()
    use_bilingual = (
        args.bilingual
        if args.bilingual is not None
        else (args.lang == "ko" and settings.search.bilingual_on_ko)
    )
    foreign_ratio = (
        args.foreign_ratio
        if args.foreign_ratio is not None
        else settings.search.min_foreign_ratio
    )

    meta: dict = {"mode": "monolingual"}
    with BraveSearch(secrets.brave_search_api_key) as client:
        if use_bilingual:
            articles, meta = bilingual_news_search(
                client,
                args.query,
                primary_lang=args.lang,
                translations_ko_to_en=settings.search.translations_ko_to_en,
                days=args.days,
                total_count=args.count,
                min_foreign_ratio=foreign_ratio,
                kind=args.kind,
            )
            print(
                f"[bilingual] ko='{meta.get('ko_query')}' "
                f"en='{meta.get('en_query')}' "
                f"en/ko={meta.get('en_returned')}/{meta.get('ko_returned')} "
                f"foreign_ratio={meta.get('foreign_ratio'):.2f}",
                file=sys.stderr,
            )
            if not meta.get("translation_found"):
                print(
                    "[bilingual] WARN: no translation mapping matched; "
                    "English search skipped. Add terms to "
                    "config/settings.yaml → search.translations_ko_to_en",
                    file=sys.stderr,
                )
        else:
            articles = client.search(
                args.query,
                lang=args.lang,
                days=args.days,
                kind=args.kind,
                count=args.count,
            )

    if args.fetch_bodies:
        from src.search.fetcher import body_stats, fetch_bodies_parallel

        articles = fetch_bodies_parallel(articles)
        stats = body_stats(articles)
        meta["body_stats"] = stats
        print(
            f"[fetch] total={stats['total']} full={stats['full']} "
            f"snippet_fallback={stats['snippet']} empty={stats['empty']} "
            f"avg_body_length={stats['avg_body_length']}",
            file=sys.stderr,
        )

    for i, article in enumerate(articles, 1):
        body_marker = (
            f"[{article.body_source[:4]}{len(article.body)}]"
            if args.fetch_bodies
            else ""
        )
        print(
            f"{i}. [{article.lang}][{article.source}]{body_marker} {article.title}"
        )
        print(f"   {article.url}")
        if article.published_at:
            print(f"   published: {article.published_at.isoformat()}")
        preview_source = article.body if (args.fetch_bodies and article.body) else article.snippet
        if preview_source:
            preview = preview_source[:140]
            if len(preview_source) > 140:
                preview += "…"
            print(f"   {preview}")
        print()

    if args.save:
        out_dir = PROJECT_ROOT / "outputs" / "search"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_q = "".join(c if c.isalnum() else "_" for c in args.query).strip("_")[:40]
        base = out_dir / f"{stamp}_{args.lang}_{safe_q}"

        def _to_dict(a):
            d = asdict(a)
            if d.get("published_at") is not None:
                d["published_at"] = d["published_at"].isoformat()
            return d

        json_path = base.with_suffix(".json")
        json_path.write_text(
            json.dumps(
                {
                    "query": args.query,
                    "lang": args.lang,
                    "days": args.days,
                    "kind": args.kind,
                    "count": args.count,
                    "meta": meta,
                    "articles": [_to_dict(a) for a in articles],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        md_lines = [f"# Brave search — `{args.query}` ({args.lang}, {args.days}d)", ""]
        for i, a in enumerate(articles, 1):
            md_lines.append(f"### {i}. {a.title}")
            md_lines.append(f"- source: `{a.source}`")
            md_lines.append(f"- url: {a.url}")
            if a.published_at:
                md_lines.append(f"- published: {a.published_at.isoformat()}")
            if a.snippet:
                md_lines.append(f"- snippet: {a.snippet}")
            md_lines.append("")
        md_path = base.with_suffix(".md")
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        print(f"Saved: {json_path.relative_to(PROJECT_ROOT)}")
        print(f"Saved: {md_path.relative_to(PROJECT_ROOT)}")
