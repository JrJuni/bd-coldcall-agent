"""Phase 9 — discover_targets + parse_discovery coverage.

Hand-rolled fake Anthropic client mirrors `tests/test_synthesize.py`. RAG
retrieval + manifest read are monkeypatched off so the tests don't load
bge-m3 / Chroma. Asserts:
  - JSON / fenced extraction
  - schema-violation retry + temperature bump
  - two failures → ValueError, no third call
  - usage accumulated across retry
  - cache_control: ephemeral only on the knowledge_base block
  - lang=ko loads the Korean prompt
  - count enforcement (n_industries × n_per_industry)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.core import discover as _discover_mod
from src.core.discover import discover_targets
from src.core.discover_types import parse_discovery
from src.rag.types import Chunk, RetrievedChunk


# ---- Fakes ----------------------------------------------------------------


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeUsage:
    def __init__(
        self,
        *,
        in_tok: int = 100,
        out_tok: int = 50,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> None:
        self.input_tokens = in_tok
        self.output_tokens = out_tok
        self.cache_read_input_tokens = cache_read
        self.cache_creation_input_tokens = cache_write


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]
        self.usage = _FakeUsage()
        self.stop_reason = "end_turn"
        self.model = "claude-sonnet-fake"


class _FakeMessages:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if not self._outputs:
            raise AssertionError("Fake client out of scripted outputs")
        return _FakeResponse(self._outputs.pop(0))


class _FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.messages = _FakeMessages(outputs)


# ---- Fixtures -------------------------------------------------------------


def _retrieved(idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id=f"local:doc:overview::{idx}",
            doc_id="local:doc:overview",
            chunk_index=idx,
            text="Lakehouse fuses data warehouse + data lake on open formats.",
            title="Product Overview",
            source_type="local",
            source_ref="data/company_docs/product_overview.md",
            last_modified=None,
            mime_type="text/markdown",
        ),
        similarity_score=0.9,
    )


_DIM_KEYS = (
    "pain_severity",
    "data_complexity",
    "governance_need",
    "ai_maturity",
    "buying_trigger",
    "displacement_ease",
)


def _scores(values=None):
    """Default 6-dim scores, override by passing 6-tuple."""
    if values is None:
        values = (7, 7, 7, 7, 7, 7)
    return dict(zip(_DIM_KEYS, values))


def _payload(*, n_industries: int = 2, n_per_industry: int = 2) -> str:
    industries = [f"ind_{i}" for i in range(n_industries)]
    meta = {ind: f"rationale for {ind}" for ind in industries}
    cands = []
    for ind in industries:
        for j in range(n_per_industry):
            cands.append(
                {
                    "name": f"Co_{ind}_{j}",
                    "industry": ind,
                    "scores": _scores(),
                    "rationale": "Fits because reasons.",
                }
            )
    return json.dumps({"industry_meta": meta, "candidates": cands})


@pytest.fixture
def patched_rag(monkeypatch):
    """Replace retriever + manifest read with deterministic stubs."""
    monkeypatch.setattr(
        _discover_mod._retriever,
        "retrieve",
        lambda query, namespace="default", top_k=None: [
            _retrieved(0),
            _retrieved(1),
        ],
    )
    monkeypatch.setattr(
        _discover_mod, "_read_seed_meta", lambda namespace="default": (1, 64)
    )
    return None


# ---- Happy path ----------------------------------------------------------


def test_returns_discovery_result_on_clean_json(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    result = discover_targets(
        lang="en",
        n_industries=2,
        n_per_industry=2,
        seed_summary="Lakehouse + AI platform.",
        output_root=tmp_path,
        top_k=5,
        client=fake,
    )
    assert len(result.candidates) == 4
    assert set(result.industry_meta.keys()) == {"ind_0", "ind_1"}
    assert len(fake.messages.calls) == 1
    assert result.seed_doc_count == 1
    assert result.seed_chunk_count == 64
    assert result.usage["input_tokens"] == 100
    assert result.usage["output_tokens"] == 50


def test_writes_yaml_and_md_artifacts(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    result = discover_targets(
        lang="en",
        n_industries=2,
        n_per_industry=2,
        seed_summary="x",
        output_root=tmp_path,
        client=fake,
    )
    date_dir = next(tmp_path.glob("discovery_*"))
    yaml_text = (date_dir / "candidates.yaml").read_text(encoding="utf-8")
    md_text = (date_dir / "report.md").read_text(encoding="utf-8")
    # yaml has flat candidates list with all four required keys
    assert "candidates:" in yaml_text
    assert "industry_meta:" in yaml_text
    for c in result.candidates:
        assert c.name in yaml_text
    # md groups by industry with tier table
    assert "ind_0" in md_text and "ind_1" in md_text
    assert "| Tier |" in md_text


def test_handles_fenced_json(patched_rag, tmp_path: Path):
    raw = _payload()
    fenced = "```json\n" + raw + "\n```"
    fake = _FakeClient([fenced])
    result = discover_targets(
        lang="en",
        n_industries=2,
        n_per_industry=2,
        seed_summary=None,
        output_root=tmp_path,
        client=fake,
        write_artifacts=False,
    )
    assert len(result.candidates) == 4
    assert len(fake.messages.calls) == 1


# ---- Retry + failure -----------------------------------------------------


def test_retries_once_on_schema_violation_then_succeeds(
    patched_rag, tmp_path: Path
):
    # First response has wrong total count → parse_discovery raises → retry.
    bad = json.dumps(
        {
            "industry_meta": {"a": "r", "b": "r"},
            "candidates": [
                {"name": "X", "industry": "a", "scores": _scores(), "rationale": "r"}
            ],
        }
    )
    fake = _FakeClient([bad, _payload()])
    result = discover_targets(
        lang="en",
        n_industries=2,
        n_per_industry=2,
        output_root=tmp_path,
        client=fake,
        write_artifacts=False,
    )
    assert len(result.candidates) == 4
    assert len(fake.messages.calls) == 2
    t1 = fake.messages.calls[0]["temperature"]
    t2 = fake.messages.calls[1]["temperature"]
    assert t2 == pytest.approx(t1 + 0.1, abs=1e-6)
    # Usage summed across both calls (each FakeUsage = 100 in / 50 out).
    assert result.usage["input_tokens"] == 200
    assert result.usage["output_tokens"] == 100


def test_raises_valueerror_after_two_failures(patched_rag, tmp_path: Path):
    fake = _FakeClient(["no json", "still not json"])
    with pytest.raises(ValueError):
        discover_targets(
            lang="en",
            n_industries=2,
            n_per_industry=2,
            output_root=tmp_path,
            client=fake,
            write_artifacts=False,
        )
    assert len(fake.messages.calls) == 2


# ---- Prompt assembly -----------------------------------------------------


def test_cache_control_only_on_knowledge_base_block(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en",
        n_industries=2,
        n_per_industry=2,
        seed_summary="My product summary.",
        output_root=tmp_path,
        client=fake,
        write_artifacts=False,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    assert user_content[0].get("cache_control") == {"type": "ephemeral"}
    assert "<knowledge_base>" in user_content[0]["text"]
    for block in user_content[1:]:
        assert "cache_control" not in block
    # product_summary lands in the volatile (uncached) block, not the cached one.
    assembled_volatile = "\n".join(b["text"] for b in user_content[1:])
    assert "My product summary." in assembled_volatile
    assert "<knowledge_base>" not in assembled_volatile


def test_ko_lang_loads_korean_prompt(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="ko",
        n_industries=2,
        n_per_industry=2,
        output_root=tmp_path,
        client=fake,
        write_artifacts=False,
    )
    system_sent = fake.messages.calls[0]["system"]
    assert any("가" <= ch <= "힣" for ch in system_sent)


def test_count_constants_substituted_in_prompt(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload(n_industries=3, n_per_industry=2)])
    discover_targets(
        lang="en",
        n_industries=3,
        n_per_industry=2,
        output_root=tmp_path,
        client=fake,
        write_artifacts=False,
    )
    system_sent = fake.messages.calls[0]["system"]
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    task_block = user_content[-1]["text"]
    # Both system and task should carry the formatted counts.
    assert "exactly 3 distinct industries" in system_sent
    assert "(3 industries" in task_block
    assert "= 6 total candidates" in task_block


# ---- parse_discovery direct ----------------------------------------------


def test_parse_discovery_rejects_uneven_industry_distribution():
    bad = json.dumps(
        {
            "industry_meta": {"a": "r", "b": "r"},
            "candidates": [
                {"name": "X1", "industry": "a", "scores": _scores(), "rationale": "r"},
                {"name": "X2", "industry": "a", "scores": _scores(), "rationale": "r"},
                {"name": "X3", "industry": "a", "scores": _scores(), "rationale": "r"},
                {"name": "Y1", "industry": "b", "scores": _scores(), "rationale": "r"},
            ],
        }
    )
    with pytest.raises(ValueError, match="industry 'a' has 3"):
        parse_discovery(bad, n_industries=2, n_per_industry=2)


# ---- Phase 9.1 — scoring + sector_leaders + region ----------------------


def test_llm_emitted_tier_is_dropped(patched_rag, tmp_path: Path):
    """If the LLM ignores the prompt and emits a tier field, runtime must drop it."""
    payload = json.dumps(
        {
            "industry_meta": {"a": "r", "b": "r"},
            "candidates": [
                {"name": "X1", "industry": "a", "scores": _scores((9, 9, 9, 9, 9, 9)),
                 "rationale": "r", "tier": "C"},  # LLM tries to force C
                {"name": "X2", "industry": "a", "scores": _scores((9, 9, 9, 9, 9, 9)),
                 "rationale": "r", "tier": "C"},
                {"name": "Y1", "industry": "b", "scores": _scores((2, 2, 2, 2, 2, 2)),
                 "rationale": "r", "tier": "S"},  # LLM tries to force S
                {"name": "Y2", "industry": "b", "scores": _scores((2, 2, 2, 2, 2, 2)),
                 "rationale": "r", "tier": "S"},
            ],
        }
    )
    fake = _FakeClient([payload])
    result = discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        output_root=tmp_path, client=fake, write_artifacts=False,
    )
    # all-9 → S (regardless of LLM-asserted "C"), all-2 → C (regardless of "S")
    by_name = {c.name: c for c in result.candidates}
    assert by_name["X1"].tier == "S"
    assert by_name["Y1"].tier == "C"
    # final_score also computed by code
    assert by_name["X1"].final_score > 8.0
    assert by_name["Y1"].final_score < 5.0


def test_scores_field_validation_rejects_out_of_range(patched_rag, tmp_path: Path):
    """LLM emitting score=15 should fail Candidate validation → retry."""
    bad = json.dumps(
        {
            "industry_meta": {"a": "r", "b": "r"},
            "candidates": [
                {"name": "X1", "industry": "a",
                 "scores": _scores((15, 7, 7, 7, 7, 7)),  # 15 out of range
                 "rationale": "r"},
                {"name": "X2", "industry": "a", "scores": _scores(), "rationale": "r"},
                {"name": "Y1", "industry": "b", "scores": _scores(), "rationale": "r"},
                {"name": "Y2", "industry": "b", "scores": _scores(), "rationale": "r"},
            ],
        }
    )
    fake = _FakeClient([bad, _payload()])
    result = discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        output_root=tmp_path, client=fake, write_artifacts=False,
    )
    assert len(result.candidates) == 4
    assert len(fake.messages.calls) == 2  # bad → retry → good


def test_sector_leaders_block_injected_when_enabled(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        include_sector_leaders=True, write_artifacts=False,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    blob = "\n".join(b["text"] for b in user_content)
    assert "<sector_leader_seeds" in blob


def test_no_sector_leaders_skips_block(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        include_sector_leaders=False, write_artifacts=False,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    blob = "\n".join(b["text"] for b in user_content)
    assert "<sector_leader_seeds" not in blob


def test_region_constraint_emitted_when_not_any(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        region="ko", write_artifacts=False,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    blob = "\n".join(b["text"] for b in user_content)
    assert "<region_constraint>ko</region_constraint>" in blob


def test_region_any_emits_no_constraint(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        region="any", write_artifacts=False,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    blob = "\n".join(b["text"] for b in user_content)
    assert "<region_constraint>" not in blob
