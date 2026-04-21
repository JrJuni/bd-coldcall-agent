"""Unit tests for `src/graph/state.py` and `src/graph/errors.py`."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.graph.errors import FatalError, StageError, TransientError
from src.graph.state import USAGE_KEYS, empty_usage, merge_usage, new_state


def test_empty_usage_has_all_keys_zero():
    u = empty_usage()
    assert set(u.keys()) == set(USAGE_KEYS)
    assert all(v == 0 for v in u.values())


def test_merge_usage_none_inputs_return_zero_dict():
    u = merge_usage(None, None)
    assert u == {k: 0 for k in USAGE_KEYS}


def test_merge_usage_accumulates_known_keys():
    a = {
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_input_tokens": 5,
        "cache_creation_input_tokens": 1,
    }
    b = {
        "input_tokens": 3,
        "output_tokens": 4,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 2,
    }
    out = merge_usage(a, b)
    assert out["input_tokens"] == 13
    assert out["output_tokens"] == 24
    assert out["cache_read_input_tokens"] == 5
    assert out["cache_creation_input_tokens"] == 3


def test_merge_usage_ignores_extra_keys_and_none_values():
    a = {"input_tokens": 5, "extra": 999}
    b = {"output_tokens": None}  # type: ignore[dict-item]
    out = merge_usage(a, b)
    assert out["input_tokens"] == 5
    assert out["output_tokens"] == 0
    assert "extra" not in out


def test_new_state_initializes_required_fields(tmp_path: Path):
    s = new_state(
        company="NVIDIA",
        industry="semiconductor",
        lang="en",
        output_dir=tmp_path,
        run_id="20260421-NVIDIA",
        top_k=8,
    )
    assert s["company"] == "NVIDIA"
    assert s["industry"] == "semiconductor"
    assert s["lang"] == "en"
    assert s["top_k"] == 8
    assert s["output_dir"] == tmp_path
    assert s["run_id"] == "20260421-NVIDIA"
    assert s["articles"] == []
    assert s["proposal_points"] == []
    assert s["errors"] == []
    assert s["stages_completed"] == []
    assert s["usage"] == empty_usage()


def test_new_state_omits_top_k_when_not_given(tmp_path: Path):
    s = new_state(
        company="X",
        industry="y",
        lang="ko",
        output_dir=tmp_path,
        run_id="r",
    )
    assert "top_k" not in s
    assert "started_at" not in s


def test_new_state_initializes_status_running_and_no_current_stage(tmp_path: Path):
    s = new_state(
        company="X",
        industry="y",
        lang="en",
        output_dir=tmp_path,
        run_id="r",
    )
    assert s["status"] == "running"
    assert s["current_stage"] is None
    # ended_at is not stamped until persist
    assert "ended_at" not in s


def test_stage_error_from_exception_captures_type_and_message():
    try:
        raise ValueError("boom")
    except ValueError as e:
        err = StageError.from_exception("synthesize", e)
    assert err.stage == "synthesize"
    assert err.error_type == "ValueError"
    assert err.message == "boom"
    assert err.ts  # ISO timestamp set


def test_stage_error_to_dict_is_json_safe():
    err = StageError.from_exception("draft", RuntimeError("x"))
    d = err.to_dict()
    import json
    assert json.loads(json.dumps(d)) == d


def test_transient_and_fatal_are_distinct_exception_classes():
    assert issubclass(TransientError, Exception)
    assert issubclass(FatalError, Exception)
    assert not issubclass(TransientError, FatalError)
    assert not issubclass(FatalError, TransientError)


def test_stage_error_ts_is_iso_format():
    err = StageError(stage="s", error_type="E", message="m")
    from datetime import datetime
    # Should round-trip via fromisoformat without raising
    datetime.fromisoformat(err.ts)
