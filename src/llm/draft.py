"""Phase 4 Stream 2 — Sonnet 4.6 draft generation of the Markdown brief.

Takes a validated `list[ProposalPoint]` (from Stream 1) and produces a
`ProposalDraft` whose `markdown` field is a 4-section cold-call brief:
Overview / Key Points / Why Our Product / Next Steps.

Footnote handling splits responsibility:
  - This module pre-assigns footnote numbers (1..N) per unique evidence URL
    across all points, in first-appearance order.
  - The prompt tells Sonnet which `[^N]` to use for which URL.
  - After generation we renumber inline markers from 1 to handle the case
    where Sonnet skipped or reordered numbers, and we append a fresh
    `[^N]: URL` definition block ourselves (the prompt forbids Sonnet from
    writing one).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal

from src.config.loader import PROJECT_ROOT, get_settings
from src.llm.claude_client import USAGE_KEYS, chat_once
from src.llm.proposal_schemas import ProposalDraft, ProposalPoint
from src.search.base import Article


_LOGGER = logging.getLogger(__name__)

_FOOTNOTE_REF_RE = re.compile(r"\[\^(\d+)\]")
_FOOTNOTE_DEF_RE = re.compile(r"^\s*\[\^\d+\]:\s*.+$", re.MULTILINE)

_LENGTH_WARN_THRESHOLD_WORDS = 1200


def _load_system_prompt(lang: Literal["en", "ko"]) -> str:
    path = PROJECT_ROOT / "src" / "prompts" / lang / "draft.txt"
    return path.read_text(encoding="utf-8").strip()


def _collect_cited_urls(points: list[ProposalPoint]) -> list[str]:
    """Ordered, deduplicated list of evidence URLs across all points."""
    seen: set[str] = set()
    ordered: list[str] = []
    for p in points:
        for url in p.evidence_article_urls:
            if url and url not in seen:
                seen.add(url)
                ordered.append(url)
    return ordered


def _render_user_content(
    points: list[ProposalPoint],
    url_to_footnote: dict[str, int],
    articles: list[Article],
    target_company: str,
) -> str:
    """Build the volatile user-side prompt with points + citation map."""
    # Map URL → article title so Sonnet has context for each citation.
    url_to_title: dict[str, str] = {a.url: a.title for a in articles if a.url}

    lines: list[str] = [f"<target_company>{target_company}</target_company>"]

    lines.append("<citation_map>")
    if url_to_footnote:
        for url, n in url_to_footnote.items():
            title = url_to_title.get(url, "")
            title_attr = f' title="{title}"' if title else ""
            lines.append(f'  <cite footnote="[^{n}]" url="{url}"{title_attr} />')
    else:
        lines.append("  (no citations)")
    lines.append("</citation_map>")

    lines.append("<proposal_points>")
    for i, p in enumerate(points):
        cited = [
            f"[^{url_to_footnote[u]}]"
            for u in p.evidence_article_urls
            if u in url_to_footnote
        ]
        cited_str = " ".join(cited) if cited else "(none)"
        lines.append(f'  <point index="{i}" angle="{p.angle}">')
        lines.append(f"    <title>{p.title}</title>")
        lines.append(f"    <rationale>{p.rationale}</rationale>")
        lines.append(f"    <cite>{cited_str}</cite>")
        lines.append("  </point>")
    lines.append("</proposal_points>")

    lines.append(
        "Write the Markdown brief now. Use only the sections specified in the "
        "system prompt and the exact footnote numbers from the citation map."
    )
    return "\n".join(lines)


def _renumber_footnote_refs(
    markdown: str, url_by_number: dict[int, str]
) -> tuple[str, list[str]]:
    """Renumber inline `[^N]` markers to a contiguous 1..K sequence.

    Matching policy (from the Stream 2 plan — "off-by-one 재번호" leniency):
      1. If `N` is in the pre-assigned map, use its URL.
      2. Otherwise fall back to the next unused URL in the pre-assigned
         order — this rescues Sonnet outputs that numbered the citation
         wrong but still cited *some* pre-assigned URL.
      3. If no unused URL remains, drop the marker entirely.

    Returns (new_markdown, ordered_urls) where `ordered_urls[i]` is the URL
    that the renumbered `[^(i+1)]` now points to.
    """
    old_to_new: dict[int, int] = {}
    ordered_urls: list[str] = []
    unused_pool: list[str] = list(url_by_number.values())

    def repl(m: re.Match[str]) -> str:
        old = int(m.group(1))
        if old not in old_to_new:
            if old in url_by_number:
                url = url_by_number[old]
                if url in unused_pool:
                    unused_pool.remove(url)
            elif unused_pool:
                url = unused_pool.pop(0)
            else:
                return ""  # exhausted — drop
            old_to_new[old] = len(old_to_new) + 1
            ordered_urls.append(url)
        return f"[^{old_to_new[old]}]"

    new_md = _FOOTNOTE_REF_RE.sub(repl, markdown)
    return new_md, ordered_urls


def _build_footnote_block(urls: list[str]) -> str:
    if not urls:
        return ""
    lines = ["", "---", ""]
    for i, url in enumerate(urls, start=1):
        lines.append(f"[^{i}]: {url}")
    return "\n".join(lines)


def _finalize_markdown(raw: str, url_by_footnote: dict[int, str]) -> str:
    # Strip any footnote-definition lines Sonnet wrote despite the prompt.
    stripped = _FOOTNOTE_DEF_RE.sub("", raw).rstrip()
    renumbered, ordered_urls = _renumber_footnote_refs(stripped, url_by_footnote)
    footer = _build_footnote_block(ordered_urls)
    return (renumbered.rstrip() + "\n" + footer).rstrip() + "\n"


def draft_proposal(
    points: list[ProposalPoint],
    articles: list[Article],
    *,
    target_company: str,
    lang: Literal["en", "ko"],
    client: Any | None = None,
) -> tuple[ProposalDraft, dict[str, int]]:
    """Generate the final Markdown brief + the Anthropic usage for this call.

    Returns `(draft, usage)`. The usage dict has the same four token keys as
    `src.llm.claude_client.USAGE_KEYS` so the orchestrator can fold it into
    the run-level total via `src.graph.state.merge_usage`.
    """
    if not points:
        raise ValueError("draft_proposal requires at least one ProposalPoint")

    settings = get_settings()
    system = _load_system_prompt(lang)

    cited_urls = _collect_cited_urls(points)
    url_to_footnote: dict[str, int] = {
        url: i + 1 for i, url in enumerate(cited_urls)
    }
    footnote_to_url: dict[int, str] = {
        n: url for url, n in url_to_footnote.items()
    }

    user_text = _render_user_content(
        points=points,
        url_to_footnote=url_to_footnote,
        articles=articles,
        target_company=target_company,
    )

    resp = chat_once(
        system=system,
        user=user_text,
        max_tokens=settings.llm.claude_max_tokens_draft,
        temperature=settings.llm.claude_temperature,
        client=client,
    )
    raw = resp.get("text", "").strip()
    if not raw:
        raise ValueError("draft_proposal: Sonnet returned empty text")

    markdown = _finalize_markdown(raw, footnote_to_url)

    word_count = len(markdown.split())
    if word_count > _LENGTH_WARN_THRESHOLD_WORDS:
        _LOGGER.warning(
            "draft_proposal: markdown is %d words (>%d); returning as-is",
            word_count,
            _LENGTH_WARN_THRESHOLD_WORDS,
        )

    resp_usage = resp.get("usage", {}) or {}
    usage: dict[str, int] = {
        k: int(resp_usage.get(k, 0) or 0) for k in USAGE_KEYS
    }

    draft = ProposalDraft(
        language=lang,
        target_company=target_company,
        generated_at=datetime.now(timezone.utc),
        points=points,
        markdown=markdown,
    )
    return draft, usage
