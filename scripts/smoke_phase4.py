"""Phase 4 end-to-end smoke — retrieve → synthesize → draft → save.

Minimal orchestration (Phase 5 will replace this with a LangGraph). Loads a
preprocessed article JSON, retrieves tech chunks against the target, hits
Sonnet twice, writes the Markdown brief + intermediate points JSON, and
prints a token/latency report.

Run:

    ~/miniconda3/envs/bd-coldcall/python.exe -m scripts.smoke_phase4 \
        --preprocess-json outputs/preprocess/20260420-163433_en.json \
        --company NVIDIA --industry semiconductor --lang en

Cost: 2 Sonnet calls, expected < $0.50 for typical inputs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.loader import PROJECT_ROOT, get_settings
from src.llm.draft import draft_proposal
from src.llm.synthesize import synthesize_proposal_points
from src.rag.retriever import retrieve
from src.search.base import Article


def _load_articles(path: Path) -> list[Article]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    articles: list[Article] = []
    for a in data["articles"]:
        pub = a.get("published_at")
        if isinstance(pub, str) and pub:
            try:
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except ValueError:
                pub_dt = None
        else:
            pub_dt = None
        articles.append(
            Article(
                title=a["title"],
                url=a["url"],
                snippet=a.get("snippet", ""),
                source=a.get("source", ""),
                lang=a.get("lang", "en"),
                published_at=pub_dt,
                metadata=a.get("metadata") or {},
                body=a.get("body", ""),
                body_source=a.get("body_source", "empty"),
                translated_body=a.get("translated_body", ""),
                tags=a.get("tags") or [],
                dedup_group_id=a.get("dedup_group_id", -1),
            )
        )
    return articles


def _point_to_dict(p: Any) -> dict[str, Any]:
    if hasattr(p, "model_dump"):
        return p.model_dump()
    if is_dataclass(p):
        return asdict(p)
    return dict(p)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="Phase 4 synthesize+draft smoke")
    ap.add_argument("--preprocess-json", required=True, type=Path)
    ap.add_argument("--company", required=True)
    ap.add_argument("--industry", required=True)
    ap.add_argument("--lang", choices=["en", "ko"], default="en")
    ap.add_argument("--top-k", type=int, default=None, help="retriever top_k override")
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "outputs",
        help="Where to write the .md + intermediate JSON",
    )
    args = ap.parse_args(argv)

    settings = get_settings()
    top_k = args.top_k or settings.llm.claude_rag_top_k

    print(f"→ loading articles from {args.preprocess_json}")
    articles = _load_articles(args.preprocess_json)
    print(f"  loaded {len(articles)} articles")

    print(f"→ retrieving top-{top_k} tech chunks for '{args.company}'")
    t0 = time.perf_counter()
    chunks = retrieve(args.company, top_k=top_k)
    retrieval_ms = (time.perf_counter() - t0) * 1000
    print(f"  retrieved {len(chunks)} chunks in {retrieval_ms:.0f}ms")
    for rc in chunks:
        print(
            f"    [{rc.similarity_score:.3f}] "
            f"{rc.chunk.doc_id}::{rc.chunk.chunk_index}"
        )

    print("→ synthesizing proposal points (Sonnet call #1)")
    t0 = time.perf_counter()
    points = synthesize_proposal_points(
        articles,
        chunks,
        target_company=args.company,
        industry=args.industry,
        lang=args.lang,
    )
    synth_ms = (time.perf_counter() - t0) * 1000
    print(f"  got {len(points)} points in {synth_ms:.0f}ms")
    for p in points:
        print(f"    [{p.angle}] {p.title}")

    print("→ drafting proposal (Sonnet call #2)")
    t0 = time.perf_counter()
    draft = draft_proposal(
        points,
        articles,
        target_company=args.company,
        lang=args.lang,
    )
    draft_ms = (time.perf_counter() - t0) * 1000
    print(f"  drafted {len(draft.markdown.split())} words in {draft_ms:.0f}ms")

    # ---- persist -----------------------------------------------------
    args.output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir = args.output_dir / "intermediate"
    intermediate_dir.mkdir(exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    md_path = args.output_dir / f"{args.company}_{today}.md"
    md_path.write_text(draft.markdown, encoding="utf-8")

    points_path = intermediate_dir / f"{args.company}_{today}_points.json"
    points_path.write_text(
        json.dumps(
            [_point_to_dict(p) for p in points],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 60)
    print(f"✅ Markdown brief → {md_path}")
    print(f"✅ Points JSON   → {points_path}")
    print(
        f"⏱  total: {(retrieval_ms + synth_ms + draft_ms)/1000:.2f}s "
        f"(retrieve {retrieval_ms:.0f}ms, synth {synth_ms:.0f}ms, draft {draft_ms:.0f}ms)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
