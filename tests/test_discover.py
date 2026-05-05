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
        lambda query, ws_slug="default", namespace="default", top_k=None: [
            _retrieved(0),
            _retrieved(1),
        ],
    )
    monkeypatch.setattr(
        _discover_mod,
        "_read_seed_meta",
        lambda ws_slug="default", namespace="default": (1, 64),
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


def test_region_constraint_emitted_when_single_country(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        regions=["kr"], write_artifacts=False,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    blob = "\n".join(b["text"] for b in user_content)
    assert "<region_constraint>kr</region_constraint>" in blob


def test_region_constraint_joins_multi_country(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        regions=["kr", "jp"], write_artifacts=False,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    blob = "\n".join(b["text"] for b in user_content)
    assert "<region_constraint>kr,jp</region_constraint>" in blob


def test_region_empty_list_emits_no_constraint(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        regions=[], write_artifacts=False,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    blob = "\n".join(b["text"] for b in user_content)
    assert "<region_constraint>" not in blob


def test_region_none_emits_no_constraint(patched_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        regions=None, write_artifacts=False,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    blob = "\n".join(b["text"] for b in user_content)
    assert "<region_constraint>" not in blob


# ---- Phase 12 — multi seed_queries -------------------------------------


@pytest.fixture
def recording_rag(monkeypatch):
    """Record the queries passed to retrieve and return per-query stub chunks.

    Each call returns one chunk whose id is `f"q{n}-c{idx}"`, so the
    `_multi_retrieve` union by chunk_id has something to merge on. The
    fixture exposes the captured query list via `.queries` for assertions.
    """

    class Recorder:
        queries: list[str] = []

    def fake_retrieve(query, ws_slug="default", namespace="default", top_k=None):
        Recorder.queries.append(query)
        # Two chunks per query — one shared across queries (id="shared"),
        # one unique per query so dedup vs. union behavior is observable.
        return [
            RetrievedChunk(
                chunk=Chunk(
                    id="shared",
                    doc_id="local:doc:shared",
                    chunk_index=0,
                    text=f"shared chunk for {query}",
                    title="Shared",
                    source_type="local",
                    source_ref="data/company_docs/shared.md",
                    last_modified=None,
                    mime_type="text/markdown",
                ),
                similarity_score=0.5 + 0.1 * len(Recorder.queries),
            ),
            RetrievedChunk(
                chunk=Chunk(
                    id=f"unique-{query}",
                    doc_id=f"local:doc:{query}",
                    chunk_index=0,
                    text=f"unique chunk for {query}",
                    title=f"Unique {query}",
                    source_type="local",
                    source_ref="data/company_docs/u.md",
                    last_modified=None,
                    mime_type="text/markdown",
                ),
                similarity_score=0.4,
            ),
        ]

    monkeypatch.setattr(_discover_mod._retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(
        _discover_mod,
        "_read_seed_meta",
        lambda ws_slug="default", namespace="default": (1, 32),
    )
    Recorder.queries = []
    return Recorder


def test_seed_queries_empty_falls_back_to_default(recording_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        seed_queries=[], write_artifacts=False,
    )
    assert recording_rag.queries == ["core capabilities and target use cases"]


def test_seed_queries_single_keyword(recording_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        seed_queries=["lakehouse"], write_artifacts=False,
    )
    assert recording_rag.queries == ["lakehouse"]


def test_seed_queries_multi_keyword_unions_chunks(recording_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        seed_queries=["lakehouse", "governance"], write_artifacts=False,
    )
    # retrieve called once per query
    assert recording_rag.queries == ["lakehouse", "governance"]
    # Knowledge base block in the prompt should contain BOTH unique chunks
    # plus the shared one (deduped to a single entry).
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    kb_text = user_content[0]["text"]
    assert "unique chunk for lakehouse" in kb_text
    assert "unique chunk for governance" in kb_text
    # `shared` appears exactly once despite being returned by both queries.
    assert kb_text.count("shared chunk for") == 1


def test_seed_queries_dedupes_case_insensitive(recording_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        seed_queries=["Lakehouse", "lakehouse", "  lakehouse  "],
        write_artifacts=False,
    )
    # All three collapse to one retrieve call.
    assert recording_rag.queries == ["Lakehouse"]


def test_legacy_seed_query_still_works(recording_rag, tmp_path: Path):
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        seed_query="legacy keyword", write_artifacts=False,
    )
    assert recording_rag.queries == ["legacy keyword"]


# ---- Phase 12 (B4a): yaml-driven dimensions in prompt ------------------


def test_dimensions_block_injected_into_system_prompt(patched_rag, tmp_path: Path):
    """The default 6-dim list flows through `{dimensions_block}` substitution
    so the LLM sees per-dimension descriptions, not the old hardcoded text."""
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        write_artifacts=False,
    )
    system_sent = fake.messages.calls[0]["system"]
    # Each dimension key should appear as a backticked bullet in the block.
    for key in (
        "pain_severity", "data_complexity", "governance_need",
        "ai_maturity", "buying_trigger", "displacement_ease",
    ):
        assert f"`{key}`" in system_sent
    # The "exactly N integer keys" line should mention all six.
    assert "EXACTLY these 6 integer keys" in system_sent
    # No leftover format-string placeholders.
    assert "{dimensions_block}" not in system_sent
    assert "{dimension_keys_csv}" not in system_sent
    assert "{n_dimensions}" not in system_sent


def test_dimensions_block_with_custom_dim(patched_rag, tmp_path: Path, monkeypatch):
    """Swapping the dimension list reflects in the prompt + parser accepts the new keys."""
    from src.config.schemas import Dimension
    from src.core import scoring as _scoring

    custom_dims = [
        Dimension(key="pain_severity", label="Pain", description="Pain desc."),
        Dimension(
            key="budget_authority",
            label="Budget",
            description="Has signing authority.",
        ),
    ]
    monkeypatch.setattr(_scoring, "load_dimensions", lambda: list(custom_dims))
    # load_weights must also reflect the new dimension set so calc_final_score
    # downstream doesn't blow up.
    monkeypatch.setattr(
        _scoring, "load_weights",
        lambda product=None: {"pain_severity": 0.5, "budget_authority": 0.5},
    )
    monkeypatch.setattr(
        _scoring, "load_tier_rules",
        lambda: [("S", 8.0), ("A", 7.0), ("B", 6.0), ("C", 5.0)],
    )
    monkeypatch.setattr(
        _scoring, "get_dimension_keys",
        lambda: ("pain_severity", "budget_authority"),
    )

    payload = json.dumps({
        "industry_meta": {"a": "ra", "b": "rb"},
        "candidates": [
            {"name": "X1", "industry": "a",
             "scores": {"pain_severity": 8, "budget_authority": 7},
             "rationale": "ok"},
            {"name": "X2", "industry": "a",
             "scores": {"pain_severity": 7, "budget_authority": 6},
             "rationale": "ok"},
            {"name": "Y1", "industry": "b",
             "scores": {"pain_severity": 6, "budget_authority": 5},
             "rationale": "ok"},
            {"name": "Y2", "industry": "b",
             "scores": {"pain_severity": 5, "budget_authority": 4},
             "rationale": "ok"},
        ],
    })
    fake = _FakeClient([payload])
    result = discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        write_artifacts=False,
    )
    system_sent = fake.messages.calls[0]["system"]
    assert "`budget_authority`" in system_sent
    # Old hardcoded keys must NOT leak in once the yaml swaps.
    assert "data_complexity" not in system_sent
    assert "EXACTLY these 2 integer keys" in system_sent
    # Parser accepted the 2-key score dicts.
    assert all(set(c.scores.keys()) == {"pain_severity", "budget_authority"}
               for c in result.candidates)


def test_dimensions_block_escapes_curly_braces(patched_rag, tmp_path: Path, monkeypatch):
    """A description containing `{` / `}` must not break str.format on the prompt."""
    from src.config.schemas import Dimension
    from src.core import scoring as _scoring

    custom_dims = [
        Dimension(
            key="pain_severity",
            label="Pain",
            description="Has {curly} braces and {nested {inside}} too.",
        ),
        Dimension(
            key="data_complexity",
            label="Data",
            description="Plain.",
        ),
        Dimension(key="governance_need", label="Gov", description="Plain."),
        Dimension(key="ai_maturity", label="AI", description="Plain."),
        Dimension(key="buying_trigger", label="Trig", description="Plain."),
        Dimension(key="displacement_ease", label="Disp", description="Plain."),
    ]
    monkeypatch.setattr(_scoring, "load_dimensions", lambda: list(custom_dims))
    fake = _FakeClient([_payload()])
    discover_targets(
        lang="en", n_industries=2, n_per_industry=2,
        seed_summary="x", output_root=tmp_path, client=fake,
        write_artifacts=False,
    )
    system_sent = fake.messages.calls[0]["system"]
    # Curly braces in description survive escaping (single braces in output).
    assert "{curly}" in system_sent
