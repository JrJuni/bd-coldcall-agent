"""Phase 9 — Target Discovery (RAG-only reverse matching, MVP).

Pure function entry point for "given our knowledge base, who should we sell
to". Reads the local Chroma index seeded by `data/company_docs`, asks Sonnet
to propose `n_industries × n_per_industry` candidate companies grouped into
tiered industries, and writes two artifacts under
`outputs/discovery_{YYYYMMDD}/`:

  - `candidates.yaml` — flat schema for the (future) editable web UI
  - `report.md` — industry-grouped human review document

Single Sonnet call + one retry on schema/JSON failure (synthesize.py pattern).
No factual verification — rough hallucinations are accepted on the assumption
that a human reviewer prunes the output before targets are committed.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from src.config.loader import PROJECT_ROOT, get_settings, load_sector_leaders
from src.config.schemas import SectorLeader
from src.core import scoring as _scoring
from src.core.discover_types import (
    Candidate,
    DiscoveryResult,
    parse_discovery,
)
from src.llm.claude_client import USAGE_KEYS, chat_cached
from src.rag import indexer as _indexer
from src.rag import retriever as _retriever
from src.rag.types import RetrievedChunk


_LOGGER = logging.getLogger(__name__)
_SYSTEM_TASK_SEPARATOR = "---TASK---"
_DEFAULT_SEED_QUERY = "core capabilities and target use cases"


def _load_prompt(lang: Literal["en", "ko"]) -> tuple[str, str]:
    path = PROJECT_ROOT / "src" / "prompts" / lang / "discover.txt"
    content = path.read_text(encoding="utf-8")
    parts = content.split(_SYSTEM_TASK_SEPARATOR, 1)
    if len(parts) != 2:
        raise ValueError(
            f"discover.txt ({lang}) must contain the "
            f"{_SYSTEM_TASK_SEPARATOR!r} delimiter between system and task sections"
        )
    return parts[0].strip(), parts[1].strip()


def _render_seed(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "<knowledge_base>\n(empty — RAG index was empty at retrieval time)\n</knowledge_base>"
    parts = ["<knowledge_base>"]
    for rc in chunks:
        c = rc.chunk
        title = c.title or "untitled"
        source = c.source_type or "?"
        parts.append(f'  <chunk title="{title}" source="{source}">')
        parts.append(f"  {c.text.strip()}")
        parts.append("  </chunk>")
    parts.append("</knowledge_base>")
    return "\n".join(parts)


def _filter_sector_leaders(
    leaders: list[SectorLeader],
    region: str,
) -> list[SectorLeader]:
    """Apply --region filter to the seed list.

    region="any" → no filter, all seeds visible.
    region in {ko,us,eu} → keep that region PLUS "global" entries (a global
        company is still a useful hint when a regional pass runs).
    region="global" → keep only "global" entries (rare, but supported).
    """
    if region == "any":
        return list(leaders)
    if region == "global":
        return [l for l in leaders if l.region == "global"]
    return [l for l in leaders if l.region == region or l.region == "global"]


def _render_sector_leaders(leaders: list[SectorLeader], region: str) -> str:
    if not leaders:
        return ""
    parts = [f'<sector_leader_seeds region="{region}">']
    parts.append(
        "Use these as inspiration. You may pick from this list OR pick other "
        "well-known companies, but aim to include at least 1 mid-market or "
        "regionally strong company per industry where fit allows. If region "
        "is set, prioritize companies in that region."
    )
    for s in leaders:
        note_attr = f' notes="{s.notes}"' if s.notes else ""
        parts.append(
            f'  <company name="{s.name}" industry_hint="{s.industry_hint}" '
            f'region="{s.region}"{note_attr} />'
        )
    parts.append("</sector_leader_seeds>")
    return "\n".join(parts)


def _render_volatile(
    seed_summary: str | None,
    sector_leaders_block: str = "",
    region: str = "any",
) -> str:
    parts: list[str] = []
    if seed_summary and seed_summary.strip():
        parts.append(f"<product_summary>\n{seed_summary.strip()}\n</product_summary>")
    if region != "any":
        parts.append(
            f"<region_constraint>{region}</region_constraint>"
        )
    if sector_leaders_block:
        parts.append(sector_leaders_block)
    return "\n\n".join(parts)


def _read_seed_meta() -> tuple[int, int]:
    """Return `(doc_count, chunk_count)` from the indexer manifest.

    Missing or corrupt manifest → (0, 0) + warn. The function still proceeds
    so a developer running on a fresh checkout sees a discovery report
    annotated with `seed_doc_count=0` rather than a crash.
    """
    settings = get_settings()
    vectorstore_path = Path(settings.rag.vectorstore_path)
    if not vectorstore_path.is_absolute():
        vectorstore_path = PROJECT_ROOT / vectorstore_path
    manifest_path = _indexer.manifest_path_for(vectorstore_path)
    manifest = _indexer.load_manifest(manifest_path)
    docs = manifest.get("documents", {}) or {}
    doc_count = len(docs)
    chunk_count = sum(int(d.get("chunk_count", 0) or 0) for d in docs.values())
    return doc_count, chunk_count


def _candidates_to_yaml(result: DiscoveryResult) -> str:
    payload: dict[str, Any] = {
        "generated_at": result.generated_at.isoformat(),
        "seed": {
            "doc_count": result.seed_doc_count,
            "chunk_count": result.seed_chunk_count,
            "summary": result.seed_summary,
        },
        "industry_meta": dict(result.industry_meta),
        "candidates": [
            {
                "name": c.name,
                "industry": c.industry,
                "scores": dict(c.scores),
                "final_score": round(c.final_score, 3),
                "tier": c.tier,
                "rationale": c.rationale,
            }
            for c in result.candidates
        ],
        "usage": dict(result.usage),
    }
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


_TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}


def _top_dimensions(scores: dict[str, int], n: int = 2) -> str:
    """Pick the top-N highest-scoring dimensions for the report Signals column.

    Ties broken by WEIGHT_DIMENSIONS order so output is deterministic.
    """
    ordered = sorted(
        _scoring.WEIGHT_DIMENSIONS,
        key=lambda d: (-int(scores.get(d, 0)), _scoring.WEIGHT_DIMENSIONS.index(d)),
    )
    picks = ordered[:n]
    return ", ".join(f"{d}={scores.get(d, 0)}" for d in picks)


def _candidate_row(c: Candidate) -> str:
    rationale_cell = c.rationale.replace("|", "\\|").replace("\n", " ")
    return (
        f"| {c.tier} | {c.name} | {c.final_score:.2f} | "
        f"{_top_dimensions(c.scores)} | {rationale_cell} |"
    )


def _render_report(result: DiscoveryResult) -> str:
    lines: list[str] = []
    date_str = result.generated_at.strftime("%Y-%m-%d")
    lines.append(f"# Target Discovery — {date_str}")
    lines.append("")
    lines.append(
        f"**Seed RAG**: {result.seed_doc_count} document(s), "
        f"{result.seed_chunk_count} chunk(s)"
    )
    if result.seed_summary:
        lines.append("")
        lines.append(f"**Seed summary**: {result.seed_summary}")
    lines.append("")

    by_industry: dict[str, list[Candidate]] = {k: [] for k in result.industry_meta}
    for c in result.candidates:
        by_industry.setdefault(c.industry, []).append(c)

    # Main industry-grouped section excludes C-tier — those go to Strategic Edge
    # below so the BD reviewer can scan landable candidates first without the
    # competitor / hyperscaler / lock-in cases polluting per-industry tables.
    edge_cases: list[Candidate] = []
    for industry, rationale in result.industry_meta.items():
        rows = [
            c for c in by_industry.get(industry, [])
            if c.tier != "C"
        ]
        edge_cases.extend(c for c in by_industry.get(industry, []) if c.tier == "C")

        lines.append(f"## {industry}")
        lines.append("")
        lines.append(f"> {rationale}")
        lines.append("")
        rows.sort(key=lambda x: (_TIER_RANK.get(x.tier, 99), -x.final_score))
        if rows:
            lines.append("| Tier | Company | Final | Signals | Rationale |")
            lines.append("|---|---|---|---|---|")
            for c in rows:
                lines.append(_candidate_row(c))
        else:
            lines.append("_(all candidates routed to Strategic Edge below)_")
        lines.append("")

    if edge_cases:
        lines.append("## ⚠️ Strategic Edge Cases (C tier — separate motion)")
        lines.append("")
        lines.append(
            "These candidates score below the main-list threshold and likely require "
            "non-standard outreach (partner motion, events, executive intro). "
            "Common causes: direct competitor, hyperscaler core ops, strong "
            "internal-platform lock-in."
        )
        lines.append("")
        edge_cases.sort(key=lambda x: (-x.final_score, x.industry, x.name))
        lines.append("| Tier | Company | Industry | Final | Signals | Rationale |")
        lines.append("|---|---|---|---|---|---|")
        for c in edge_cases:
            rationale_cell = c.rationale.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {c.tier} | {c.name} | {c.industry} | {c.final_score:.2f} | "
                f"{_top_dimensions(c.scores)} | {rationale_cell} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    usage = result.usage or {}
    parts = [f"{k}={int(usage.get(k, 0))}" for k in USAGE_KEYS]
    lines.append("**Tokens**: " + ", ".join(parts))
    lines.append("")
    return "\n".join(lines)


def discover_targets(
    *,
    lang: Literal["en", "ko"] = "en",
    n_industries: int = 5,
    n_per_industry: int = 5,
    seed_summary: str | None = None,
    seed_query: str = _DEFAULT_SEED_QUERY,
    product: str = "databricks",
    region: Literal["any", "ko", "us", "eu", "global"] = "any",
    include_sector_leaders: bool = True,
    output_root: Path | None = None,
    top_k: int = 20,
    client: Any | None = None,
    write_artifacts: bool = True,
) -> DiscoveryResult:
    """Generate a tiered candidate-company list from the RAG index alone.

    Single Sonnet call + one retry on schema failure. LLM emits 0-10 scores
    per dimension; this function computes `final_score` and `tier` from
    `config/weights.yaml` + `config/tier_rules.yaml`. Writes `candidates.yaml`
    and `report.md` under `outputs/discovery_{YYYYMMDD}/` when
    `write_artifacts=True` (the default — set False in unit tests).
    """
    if n_industries <= 0 or n_per_industry <= 0:
        raise ValueError(
            f"n_industries and n_per_industry must be positive "
            f"(got {n_industries}, {n_per_industry})"
        )

    settings = get_settings()
    system_template, task_template = _load_prompt(lang)
    fmt_kwargs = {
        "n_industries": n_industries,
        "n_per_industry": n_per_industry,
        "expected_total": n_industries * n_per_industry,
    }
    system = system_template.format(**fmt_kwargs)
    task = task_template.format(**fmt_kwargs)

    chunks = _retriever.retrieve(seed_query, top_k=top_k)
    if not chunks:
        _LOGGER.warning(
            "discover: RAG retrieve returned 0 chunks for query %r — "
            "Sonnet output will be unreliable. Run `python -m src.rag.indexer` "
            "and check `data/company_docs/`.",
            seed_query,
        )

    cached_context = _render_seed(chunks)

    sector_leaders_block = ""
    if include_sector_leaders:
        cfg = load_sector_leaders()
        filtered = _filter_sector_leaders(cfg.companies, region)
        if filtered:
            sector_leaders_block = _render_sector_leaders(filtered, region)
    volatile_context = _render_volatile(
        seed_summary,
        sector_leaders_block=sector_leaders_block,
        region=region,
    )

    seed_doc_count, seed_chunk_count = _read_seed_meta()

    base_temp = settings.llm.claude_temperature
    temperatures = [base_temp, min(base_temp + 0.1, 1.0)]
    max_tokens = settings.llm.claude_max_tokens_discover

    total_usage: dict[str, int] = {k: 0 for k in USAGE_KEYS}
    last_error: Exception | None = None
    industry_meta: dict[str, str] = {}
    candidates: list[Candidate] = []
    succeeded = False
    for attempt, temp in enumerate(temperatures, start=1):
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
            industry_meta, candidates = parse_discovery(
                resp["text"],
                n_industries=n_industries,
                n_per_industry=n_per_industry,
            )
            succeeded = True
            break
        except Exception as e:
            last_error = e
            _LOGGER.warning(
                "discover: parse failed on attempt %d (temp=%.2f): %s",
                attempt,
                temp,
                e,
            )
            continue

    if not succeeded:
        raise ValueError(
            f"discover_targets failed after {len(temperatures)} attempts: {last_error}"
        ) from last_error

    # Score + tier are computed deterministically from yaml — LLM only judged
    # the per-dimension 0-10 scores. Re-running with different weights costs $0.
    weights = _scoring.load_weights(product)
    rules = _scoring.load_tier_rules()
    for c in candidates:
        c.final_score = _scoring.calc_final_score(c.scores, weights)
        c.tier = _scoring.decide_tier(c.final_score, rules)

    now = datetime.now(timezone.utc)
    result = DiscoveryResult(
        generated_at=now,
        seed_doc_count=seed_doc_count,
        seed_chunk_count=seed_chunk_count,
        seed_summary=(seed_summary or "").strip(),
        industry_meta=industry_meta,
        candidates=candidates,
        usage=total_usage,
    )

    if write_artifacts:
        root = Path(output_root or settings.output.dir)
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        date_dir = root / f"discovery_{now.strftime('%Y%m%d')}"
        date_dir.mkdir(parents=True, exist_ok=True)
        (date_dir / "candidates.yaml").write_text(
            _candidates_to_yaml(result), encoding="utf-8"
        )
        (date_dir / "report.md").write_text(
            _render_report(result), encoding="utf-8"
        )
        _LOGGER.info(
            "discover: wrote %s and %s",
            date_dir / "candidates.yaml",
            date_dir / "report.md",
        )

    return result
