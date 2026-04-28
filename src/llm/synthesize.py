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
from src.llm.claude_client import USAGE_KEYS, chat_cached
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
    """Pre-Phase-8 single-block renderer. Retained for callers that don't
    care about the channel split (notably older tests). Phase 8 callers
    use `_render_articles_by_channel` instead."""
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


def _article_attrs(a: Article) -> str:
    tags_str = ",".join(a.tags) if a.tags else ""
    pub = a.published_at.isoformat() if a.published_at else ""
    return (
        f'url="{a.url}" source="{a.source}" lang="{a.lang}" '
        f'tags="{tags_str}" published_at="{pub}"'
    )


def _render_target_block(articles: list[Article]) -> str:
    """Target channel — full tag-tier policy (body for high-tag, snippet for low)."""
    lines = ["<target_articles>"]
    for i, a in enumerate(articles):
        tier = "high" if has_high_value_tag(a) else "low"
        body = select_body_or_snippet(a)
        lines.append(
            f'  <article id="target_{i}" {_article_attrs(a)} tier="{tier}">'
        )
        lines.append(f"    <title>{a.title}</title>")
        lines.append(f"    <body>{body}</body>")
        lines.append("  </article>")
    lines.append("</target_articles>")
    return "\n".join(lines)


def _render_related_block(articles: list[Article]) -> str:
    """Related channel — always snippet (talking-point support, not direct evidence)."""
    lines = ["<related_articles>"]
    for i, a in enumerate(articles):
        intent = a.metadata.get("intent_label", "")
        intent_tier = a.metadata.get("intent_tier", "")
        body = a.snippet or a.translated_body[:300] if a.translated_body else (a.snippet or "")
        lines.append(
            f'  <article id="rel_{i}" {_article_attrs(a)} '
            f'intent="{intent}" intent_tier="{intent_tier}">'
        )
        lines.append(f"    <title>{a.title}</title>")
        lines.append(f"    <body>{body}</body>")
        lines.append("  </article>")
    lines.append("</related_articles>")
    return "\n".join(lines)


def _render_competitor_block(articles: list[Article]) -> str:
    """Competitor channel — snippet only, intended ONLY for differentiation framing."""
    lines = ["<competitor_news>"]
    for i, a in enumerate(articles):
        comp = a.metadata.get("competitor_name", "")
        relation = a.metadata.get("competitor_relation", "")
        body = a.snippet or ""
        lines.append(
            f'  <article id="comp_{i}" {_article_attrs(a)} '
            f'competitor="{comp}" relation="{relation}">'
        )
        lines.append(f"    <title>{a.title}</title>")
        lines.append(f"    <body>{body}</body>")
        lines.append("  </article>")
    lines.append("</competitor_news>")
    return "\n".join(lines)


def _render_articles_by_channel(articles: list[Article]) -> str:
    """Phase 8 — split articles into target/related/competitor blocks.

    Each channel applies its own tier policy. Empty channels are skipped
    so the prompt only carries blocks Sonnet should actually read.
    """
    by_channel: dict[str, list[Article]] = {
        "target": [], "related": [], "competitor": []
    }
    for a in articles:
        ch = getattr(a, "channel", "target")
        by_channel.setdefault(ch, []).append(a)

    parts: list[str] = []
    if by_channel["target"]:
        parts.append(_render_target_block(by_channel["target"]))
    if by_channel["related"]:
        parts.append(_render_related_block(by_channel["related"]))
    if by_channel["competitor"]:
        parts.append(_render_competitor_block(by_channel["competitor"]))

    if not parts:
        return "<articles>\n(no articles provided)\n</articles>"
    return "\n\n".join(parts)


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
) -> tuple[list[ProposalPoint], dict[str, int]]:
    """Produce 3~5 validated ProposalPoints + the accumulated Anthropic usage.

    Returns `(points, usage)` where `usage` sums token counts across all
    attempts (initial + retry) so the orchestrator's run_summary reflects
    actual spend, not just the successful call.

    On JSON parse or schema validation failure, retries exactly once with
    temperature bumped by +0.1 (capped at 1.0). A second failure raises
    ValueError with the last error chained.
    """
    settings = get_settings()
    system, task = _load_prompt(lang)

    cached_context = _render_tech_docs(tech_chunks)
    volatile_context = (
        _render_articles_by_channel(articles)
        + "\n\n"
        + _render_target(target_company, industry)
    )

    max_tokens = settings.llm.claude_max_tokens_synthesize
    base_temp = settings.llm.claude_temperature
    temperatures = [base_temp, min(base_temp + 0.1, 1.0)]

    total_usage: dict[str, int] = {k: 0 for k in USAGE_KEYS}
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
        resp_usage = resp.get("usage", {}) or {}
        for k in USAGE_KEYS:
            total_usage[k] += int(resp_usage.get(k, 0) or 0)
        try:
            return parse_proposal_points(resp["text"]), total_usage
        except Exception as e:
            last_error = e
            continue

    raise ValueError(
        f"synthesize_proposal_points failed after {len(temperatures)} attempts: {last_error}"
    ) from last_error
