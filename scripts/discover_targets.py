"""Phase 9 — argparse adapter for `src.core.discover.discover_targets`.

Operational entry point. Mirrors `main.py discover` flag set so a non-Typer
runner can drive the same pure function (e.g. cron jobs or `python -m`
invocations on machines without rich terminal support).

Usage:
    python -m scripts.discover_targets \\
        --lang en \\
        --seed-summary "Lakehouse + AI platform for the enterprise" \\
        [--n-industries 5 --n-per-industry 5 --top-k 20]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.core.discover import discover_targets


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lang", choices=("en", "ko"), default="en", help="Output language."
    )
    parser.add_argument(
        "--n-industries", type=int, default=5, help="Number of industries."
    )
    parser.add_argument(
        "--n-per-industry", type=int, default=5, help="Companies per industry."
    )
    parser.add_argument(
        "--seed-summary",
        default=None,
        help="One-paragraph product summary injected as volatile context.",
    )
    parser.add_argument(
        "--seed-query",
        default="core capabilities and target use cases",
        help="RAG query that picks the chunks Sonnet sees.",
    )
    parser.add_argument(
        "--product",
        default="databricks",
        help="Weight profile key from config/weights.yaml::products.",
    )
    parser.add_argument(
        "--region",
        choices=("any", "ko", "us", "eu", "global"),
        default="any",
        help="Region filter for sector_leaders seeds.",
    )
    parser.add_argument(
        "--no-sector-leaders",
        dest="sector_leaders",
        action="store_false",
        help="Disable sector_leaders.yaml seed injection.",
    )
    parser.set_defaults(sector_leaders=True)
    parser.add_argument(
        "--top-k", type=int, default=20, help="Number of RAG chunks to seed."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Parent directory for the discovery_<date>/ folder.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    if args.n_industries <= 0 or args.n_per_industry <= 0:
        parser.error("--n-industries and --n-per-industry must be positive")

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    result = discover_targets(
        lang=args.lang,
        n_industries=args.n_industries,
        n_per_industry=args.n_per_industry,
        seed_summary=args.seed_summary,
        seed_query=args.seed_query,
        product=args.product,
        region=args.region,
        include_sector_leaders=args.sector_leaders,
        output_root=args.output_root,
        top_k=args.top_k,
    )

    print(
        f"discover: {len(result.industry_meta)} industries, "
        f"{len(result.candidates)} candidates "
        f"(seed: {result.seed_doc_count} doc / {result.seed_chunk_count} chunk; "
        f"in={result.usage.get('input_tokens', 0)} "
        f"out={result.usage.get('output_tokens', 0)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
