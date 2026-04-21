"""Phase 4 Stream 1 — Sonnet 4.6 synthesis of ProposalPoint list.

Given a target company's recent articles (already translated + tagged) and a
set of retrieved tech-doc chunks, Sonnet produces 3~5 `ProposalPoint`s that a
BD rep can raise on a cold call. The prompt is split into a cached tech_docs
block (shared across targets for the same knowledge base) and a volatile
articles+target block so re-running against the same tech corpus benefits
from ephemeral prompt caching.

Tag-tier is applied before prompt assembly: high-value tags get the full
translated body, low-value tags get only the snippet (~35% input token
savings). A single retry with temperature +0.1 handles JSON / schema
misses; a second failure raises so Phase 5's retry edge can decide what's
next.
"""
from __future__ import annotations

from typing import Any, Literal

from src.config.loader import PROJECT_ROOT, get_settings
from src.llm.claude_client import chat_cached
from src.llm.proposal_schemas import ProposalPoint, parse_proposal_points
from src.llm.tag_tier import has_high_value_tag, select_body_or_snippet
from src.rag.types import RetrievedChunk
from src.search.base import Article


_SYSTEM_TASK_SEPARATOR = "---TASK---"


def _load_prompt(lang: Literal["en", "ko"]) -> tuple[str, str]:
    path = PROJECT_ROOT / "src" / "prompts" / lang / "synthesize.txt"
    content = path.read_text(encoding="utf-8")
    parts = content.split(_SYSTEM_TASK_SEPARATOR, 1)
    if len(parts) != 2:
        raise ValueError(
            f"synthesize.txt ({lang}) must contain the "
            f"{_SYSTEM_TASK_SEPARATOR!r} delimiter between system and task sections"
        )
    return parts[0].strip(), parts[1].strip()


def _render_tech_docs(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "<tech_docs>\n(no tech docs retrieved)\n</tech_docs>"
    lines = ["<tech_docs>"]
    for rc in chunks:
        c = rc.chunk
        chunk_id = f"{c.doc_id}::{c.chunk_index}"
        lines.append(
            f'  <chunk id="{chunk_id}" title="{c.title}" source="{c.source_type}">'
        )
        lines.append(c.text.strip())
        lines.append("  </chunk>")
    lines.append("</tech_docs>")
    return "\n".join(lines)


def _render_articles(articles: list[Article]) -> str:
    if not articles:
        return "<articles>\n(no articles provided)\n</articles>"
    lines = ["<articles>"]
    for i, a in enumerate(articles):
        art_id = f"art_{i}"
        tier = "high" if has_high_value_tag(a) else "low"
        body = select_body_or_snippet(a)
        tags_str = ",".join(a.tags) if a.tags else ""
        pub = a.published_at.isoformat() if a.published_at else ""
        lines.append(
            f'  <article id="{art_id}" url="{a.url}" source="{a.source}" '
            f'lang="{a.lang}" tags="{tags_str}" published_at="{pub}" tier="{tier}">'
        )
        lines.append(f"    <title>{a.title}</title>")
        lines.append(f"    <body>{body}</body>")
        lines.append("  </article>")
    lines.append("</articles>")
    return "\n".join(lines)


def _render_target(target_company: str, industry: str) -> str:
    return (
        "<target>\n"
        f"  <company>{target_company}</company>\n"
        f"  <industry>{industry}</industry>\n"
        "</target>"
    )


def synthesize_proposal_points(
    articles: list[Article],
    tech_chunks: list[RetrievedChunk],
    *,
    target_company: str,
    industry: str,
    lang: Literal["en", "ko"],
    client: Any | None = None,
) -> list[ProposalPoint]:
    """Produce 3~5 validated ProposalPoints for a target.

    On JSON parse or schema validation failure, retries exactly once with
    temperature bumped by +0.1 (capped at 1.0). A second failure raises
    ValueError with the last error chained.
    """
    settings = get_settings()
    system, task = _load_prompt(lang)

    cached_context = _render_tech_docs(tech_chunks)
    volatile_context = (
        _render_articles(articles)
        + "\n\n"
        + _render_target(target_company, industry)
    )

    max_tokens = settings.llm.claude_max_tokens_synthesize
    base_temp = settings.llm.claude_temperature
    temperatures = [base_temp, min(base_temp + 0.1, 1.0)]

    last_error: Exception | None = None
    for temp in temperatures:
        resp = chat_cached(
            system=system,
            cached_context=cached_context,
            volatile_context=volatile_context,
            task=task,
            max_tokens=max_tokens,
            temperature=temp,
            client=client,
        )
        try:
            return parse_proposal_points(resp["text"])
        except Exception as e:
            last_error = e
            continue

    raise ValueError(
        f"synthesize_proposal_points failed after {len(temperatures)} attempts: {last_error}"
    ) from last_error
