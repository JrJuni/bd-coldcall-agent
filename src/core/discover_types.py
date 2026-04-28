"""Phase 9 — Target Discovery schemas + JSON parser.

Sonnet emits a single JSON object with two top-level keys:
`industry_meta` (mapping of industry → 1-line rationale) and
`candidates` (flat list of `{name, industry, tier, rationale}`).

Validation is strict so the discover_targets() retry loop can decide on
schema misses. Count constraints (`n_industries × n_per_industry`) are
enforced here too — anything off-spec raises so the caller retries with
+0.1 temperature exactly once before giving up. Defensive JSON extraction
matches the four-stage strategy in `src/llm/proposal_schemas.py`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, field_validator


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_object(raw: str) -> Any | None:
    """Pull the first valid JSON *object* out of arbitrary LLM output.

    Object-first variant — `parse_discovery` requires a dict at the top level
    (`industry_meta` + `candidates`). The shared `proposal_schemas._extract_json`
    tries arrays before objects, which can spuriously match the inner
    `candidates` list when the model emits prose around the JSON. Order here:
        1. full string as JSON
        2. fenced block body
        3. widest {...} object span
    Returns parsed value or None — never raises.
    """
    if not raw or not raw.strip():
        return None
    candidates: list[str] = [raw.strip()]
    fence = _FENCE_RE.search(raw)
    if fence:
        candidates.append(fence.group(1).strip())
    obj = _OBJECT_RE.search(raw)
    if obj:
        candidates.append(obj.group(0))
    for c in candidates:
        if not c:
            continue
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


Tier = Literal["S", "A", "B", "C"]
TIER_VALUES: tuple[str, ...] = ("S", "A", "B", "C")


class Candidate(BaseModel):
    name: str
    industry: str
    tier: Tier
    rationale: str

    @field_validator("name", "industry", "rationale")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field must be non-empty")
        return v.strip()


@dataclass
class DiscoveryResult:
    generated_at: datetime
    seed_doc_count: int
    seed_chunk_count: int
    seed_summary: str
    industry_meta: dict[str, str]
    candidates: list[Candidate]
    usage: dict[str, int] = field(default_factory=dict)


def parse_discovery(
    raw: str,
    *,
    n_industries: int,
    n_per_industry: int,
) -> tuple[dict[str, str], list[Candidate]]:
    """Parse Sonnet output into `(industry_meta, candidates)`.

    Raises ValueError on any of:
      - no JSON found
      - missing top-level keys
      - industry_meta count != n_industries
      - candidates count != n_industries × n_per_industry
      - any candidate.industry not in industry_meta keys
      - per-industry candidate count != n_per_industry
      - Candidate field validation (empty / bad tier)
    """
    parsed = _extract_json_object(raw)
    if parsed is None:
        raise ValueError("no JSON found in discovery output")
    if not isinstance(parsed, dict):
        raise ValueError(
            f"expected JSON object with industry_meta + candidates, got {type(parsed).__name__}"
        )

    meta_raw = parsed.get("industry_meta")
    cands_raw = parsed.get("candidates")
    if not isinstance(meta_raw, dict):
        raise ValueError("industry_meta must be an object mapping industry → rationale")
    if not isinstance(cands_raw, list):
        raise ValueError("candidates must be a list")

    industry_meta: dict[str, str] = {}
    for k, v in meta_raw.items():
        if not isinstance(k, str) or not k.strip():
            raise ValueError(f"industry_meta key must be non-empty string, got {k!r}")
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"industry_meta[{k!r}] rationale must be non-empty string")
        industry_meta[k.strip()] = v.strip()

    if len(industry_meta) != n_industries:
        raise ValueError(
            f"industry_meta has {len(industry_meta)} entries, expected {n_industries}"
        )

    candidates: list[Candidate] = [Candidate(**item) for item in cands_raw]
    expected_total = n_industries * n_per_industry
    if len(candidates) != expected_total:
        raise ValueError(
            f"candidates has {len(candidates)} entries, expected {expected_total} "
            f"({n_industries} × {n_per_industry})"
        )

    counts: dict[str, int] = {k: 0 for k in industry_meta}
    for c in candidates:
        if c.industry not in industry_meta:
            raise ValueError(
                f"candidate {c.name!r} references unknown industry {c.industry!r} "
                f"(known: {list(industry_meta)})"
            )
        counts[c.industry] += 1

    for ind in industry_meta:
        n = counts[ind]
        if n != n_per_industry:
            raise ValueError(
                f"industry {ind!r} has {n} candidates, expected {n_per_industry}"
            )

    return industry_meta, candidates
