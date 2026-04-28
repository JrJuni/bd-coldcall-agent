"""Draft `config/sector_leaders.yaml` — Phase 9.1 mega-cap bias mitigation seed.

Run once per product / market expansion. Output is a *draft* — review the
companies, swap in regional names you actually care about, drop ones that
duplicate competitors.yaml, then commit.

Usage:
    python -m scripts.draft_sector_leaders \\
        --product-summary "Lakehouse + AI platform for enterprise" \\
        --industries "Financial Services, Manufacturing, Healthcare" \\
        --regions "ko, us, eu" \\
        --per-industry 4 \\
        --output config/sector_leaders.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.llm.claude_client import chat_cached
from src.rag.retriever import retrieve


SYSTEM_PROMPT = """You are a B2B sales-research analyst.

Given (a) a product summary and (b) excerpts from the product's internal
knowledge base, produce a YAML seed list of mid-market and regional
sector-leader companies a BD analyst should keep on a discovery shortlist
beyond Fortune-500 mega-caps.

Each entry must:
- have a real, well-known company name (no inventions)
- pick `region` from: ko, us, eu, global
- pick `industry_hint` from the user-provided industry list (verbatim)
- include a 1-line `notes` describing why this company is a relevant seed

Return strictly valid YAML — no commentary outside the YAML body.
Schema:

version: 1
companies:
  - name: <company>
    industry_hint: <one of the user's industries>
    region: ko|us|eu|global
    notes: <one-line>
"""


TASK_TEMPLATE = """Product summary: {product_summary}

Industries to cover (list exactly {per_industry} companies for each, mixed across the requested regions):
{industries}

Regions to mix across: {regions}

Generate the sector_leaders.yaml draft now.
"""


def _render_chunks(chunks) -> str:
    if not chunks:
        return "<knowledge_base>(empty)</knowledge_base>"
    parts = ["<knowledge_base>"]
    for rc in chunks:
        c = rc.chunk
        title = c.title or "untitled"
        source = c.source_type or "?"
        parts.append(
            f'  <chunk title="{title}" source="{source}">\n  {c.text.strip()}\n  </chunk>'
        )
    parts.append("</knowledge_base>")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--product-summary",
        required=True,
        help="One-paragraph description of what the product does.",
    )
    parser.add_argument(
        "--industries",
        required=True,
        help="Comma-separated industry list (verbatim, will appear in industry_hint).",
    )
    parser.add_argument(
        "--regions",
        default="ko, us, eu",
        help="Comma-separated region codes to mix (default: 'ko, us, eu'). Use 'global' for non-regional logos.",
    )
    parser.add_argument(
        "--per-industry",
        type=int,
        default=4,
        help="Companies per industry (default 4).",
    )
    parser.add_argument(
        "--query",
        default="our product core capabilities and differentiators",
        help="RAG seed query — picks the top-k chunks Sonnet sees.",
    )
    parser.add_argument(
        "--top-k", type=int, default=20, help="Number of RAG chunks to seed (default 20).",
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Write yaml to this path (default: stdout).",
    )
    parser.add_argument("--max-tokens", type=int, default=2500)
    args = parser.parse_args(argv)

    chunks = retrieve(args.query, top_k=args.top_k)
    if not chunks:
        print(
            "WARNING: RAG index empty — Sonnet will produce a generic draft. "
            "Run `python -m src.rag.indexer` first.",
            file=sys.stderr,
        )

    cached_context = _render_chunks(chunks)
    industries_text = "\n".join(f"  - {ind.strip()}" for ind in args.industries.split(",") if ind.strip())
    task = TASK_TEMPLATE.format(
        product_summary=args.product_summary.strip(),
        per_industry=args.per_industry,
        industries=industries_text,
        regions=args.regions.strip(),
    )

    response = chat_cached(
        system=SYSTEM_PROMPT,
        cached_context=cached_context,
        volatile_context="",
        task=task,
        max_tokens=args.max_tokens,
    )
    yaml_text = response["text"].strip()
    if yaml_text.startswith("```"):
        lines = yaml_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        yaml_text = "\n".join(lines).strip()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(yaml_text + "\n", encoding="utf-8")
        print(
            f"Draft written to {args.output} "
            f"(tokens: input={response['usage']['input_tokens']} "
            f"output={response['usage']['output_tokens']}). "
            "Review and edit before committing.",
            file=sys.stderr,
        )
    else:
        print(yaml_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
