"""Draft `config/intent_tiers.yaml` from the RAG index — Phase 8 (A) seed tool.

Run once per knowledge-base refresh. Output is intentionally a *draft*:
review the labels, prune what doesn't match the product, adjust tiers
based on real search-result quality, then commit.

Usage:
    python -m scripts.draft_intent_tiers \\
        --product-summary "Lakehouse + AI platform for the enterprise" \\
        --query "core capabilities" \\
        --top-k 20 \\
        --output config/intent_tiers.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.llm.claude_client import chat_cached
from src.rag.retriever import retrieve


SYSTEM_PROMPT = """You are a B2B sales-research analyst.

Given (a) a product description and (b) excerpts from the product's
internal knowledge base, propose **4-6 search intents** a BD analyst
should run for any prospective customer to find news that justifies a
sales conversation.

Each intent must:
- have a short snake_case label
- carry a tier S / A / B / C (S = direct trigger, A = strong fit,
  B = adjacent signal, C = long-shot)
- include 2-3 English keywords AND 2-3 Korean keywords usable as
  Brave Search query suffixes (the runtime joins each keyword with the
  target company name).

Return strictly valid YAML — no commentary outside the YAML body.
Schema:

intents:
  - label: <snake_case>
    tier: S|A|B|C
    description: <one sentence in English>
    keywords_en: [<keyword>, ...]
    keywords_ko: [<keyword>, ...]
"""


TASK_TEMPLATE = """Product summary: {product_summary}

Generate the intent_tiers.yaml draft now.
"""


def _render_chunks(chunks) -> str:
    """Serialize RetrievedChunk list into a single context block."""
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
        "--query",
        default="our product core capabilities and differentiators",
        help="RAG seed query — picks the top-k chunks Sonnet sees.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Number of RAG chunks to seed (default 20).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write yaml to this path (default: stdout).",
    )
    parser.add_argument("--max-tokens", type=int, default=2000)
    args = parser.parse_args(argv)

    chunks = retrieve(args.query, top_k=args.top_k)
    if not chunks:
        print(
            "WARNING: RAG index empty — Sonnet will produce a generic draft. "
            "Run `python -m src.rag.indexer` first.",
            file=sys.stderr,
        )

    cached_context = _render_chunks(chunks)
    task = TASK_TEMPLATE.format(product_summary=args.product_summary.strip())

    response = chat_cached(
        system=SYSTEM_PROMPT,
        cached_context=cached_context,
        volatile_context="",
        task=task,
        max_tokens=args.max_tokens,
    )
    yaml_text = response["text"].strip()
    # Strip markdown code fences if Sonnet wrapped the YAML.
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
