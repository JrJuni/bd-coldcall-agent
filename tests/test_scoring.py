"""Phase 9.1 — scoring engine tests.

Cover the deterministic decision layer separately from the LLM call:
- weight load + product override merge + auto-normalize
- tier rules: descending sort, missing tier rejection
- final_score weighted sum with epsilon tolerance
- decide_tier boundary cases (8.0 exactly, 4.99 → C clamp)
- C-clamp on below-lowest scores
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.config import loader as _loader
from src.core import scoring
from src.core.scoring import (
    TIER_VALUES,
    WEIGHT_DIMENSIONS,
    calc_final_score,
    decide_tier,
    get_dimension_keys,
    load_dimensions,
    load_tier_rules,
    load_weights,
)


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def _patch_yaml(monkeypatch, tmp_path, *, weights_body: str | None = None, rules_body: str | None = None):
    """Redirect loader to read tmp yaml files. Caller passes only the bodies they care about."""
    if weights_body is not None:
        wpath = tmp_path / "weights.yaml"
        _write_yaml(wpath, weights_body)
        monkeypatch.setattr(
            _loader, "load_weights_config",
            lambda path=None: _loader.WeightsConfig(**__import__("yaml").safe_load(wpath.read_text(encoding="utf-8"))),
        )
    if rules_body is not None:
        rpath = tmp_path / "tier_rules.yaml"
        _write_yaml(rpath, rules_body)
        monkeypatch.setattr(
            _loader, "load_tier_rules_config",
            lambda path=None: _loader.TierRulesConfig(**__import__("yaml").safe_load(rpath.read_text(encoding="utf-8"))),
        )


# ---- load_weights --------------------------------------------------------


def test_load_weights_default_only_no_product(monkeypatch, tmp_path):
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        default:
          pain_severity: 0.25
          data_complexity: 0.20
          governance_need: 0.15
          ai_maturity: 0.15
          buying_trigger: 0.15
          displacement_ease: 0.10
        products: {}
    """)
    w = load_weights()
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(w.keys()) == set(WEIGHT_DIMENSIONS)
    assert w["pain_severity"] == 0.25


def test_load_weights_product_override_merges_and_normalizes(monkeypatch, tmp_path):
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        default:
          pain_severity: 0.25
          data_complexity: 0.20
          governance_need: 0.15
          ai_maturity: 0.15
          buying_trigger: 0.15
          displacement_ease: 0.10
        products:
          databricks:
            data_complexity: 0.25
            governance_need: 0.20
            displacement_ease: 0.10
    """)
    w_default = load_weights()
    w_db = load_weights("databricks")
    # Pre-normalize sum was 1.10 (override raises data_complexity, governance_need;
    # displacement_ease unchanged). After auto-normalize total is 1.0.
    assert sum(w_db.values()) == pytest.approx(1.0, abs=1e-9)
    # Override actually changed something: data_complexity weight is RELATIVELY
    # higher in databricks (vs default). We compare ratios because both vectors
    # are normalized.
    db_ratio = w_db["data_complexity"] / w_db["pain_severity"]
    default_ratio = w_default["data_complexity"] / w_default["pain_severity"]
    assert db_ratio > default_ratio  # override pulled data_complexity up


def test_load_weights_unknown_product_falls_back_to_default(monkeypatch, tmp_path):
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        default:
          pain_severity: 0.25
          data_complexity: 0.20
          governance_need: 0.15
          ai_maturity: 0.15
          buying_trigger: 0.15
          displacement_ease: 0.10
        products:
          databricks:
            data_complexity: 0.30
    """)
    w = load_weights("not_in_yaml")
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-9)
    assert w["data_complexity"] == 0.20  # default, not databricks override


def test_load_weights_missing_dimension_raises(monkeypatch, tmp_path):
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        default:
          pain_severity: 0.5
          data_complexity: 0.5
        products: {}
    """)
    with pytest.raises(ValueError, match="missing dimensions"):
        load_weights()


def test_load_weights_zero_sum_raises(monkeypatch, tmp_path):
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        default:
          pain_severity: 0.0
          data_complexity: 0.0
          governance_need: 0.0
          ai_maturity: 0.0
          buying_trigger: 0.0
          displacement_ease: 0.0
        products: {}
    """)
    with pytest.raises(ValueError, match="must be positive"):
        load_weights()


# ---- load_tier_rules ----------------------------------------------------


def test_load_tier_rules_descending_order(monkeypatch, tmp_path):
    _patch_yaml(monkeypatch, tmp_path, rules_body="""\
        version: 1
        tiers:
          C: 5.0
          A: 7.0
          S: 8.0
          B: 6.0
    """)
    rules = load_tier_rules()
    # Sorted descending by threshold
    assert [t for t, _ in rules] == ["S", "A", "B", "C"]
    assert [thr for _, thr in rules] == [8.0, 7.0, 6.0, 5.0]


def test_load_tier_rules_missing_tier_raises(monkeypatch, tmp_path):
    _patch_yaml(monkeypatch, tmp_path, rules_body="""\
        version: 1
        tiers:
          S: 8.0
          A: 7.0
          B: 6.0
    """)
    with pytest.raises(ValueError, match="missing tiers"):
        load_tier_rules()


# ---- calc_final_score ---------------------------------------------------


def test_calc_final_score_weighted_sum_exact():
    weights = {d: 1.0 / len(WEIGHT_DIMENSIONS) for d in WEIGHT_DIMENSIONS}
    scores = dict.fromkeys(WEIGHT_DIMENSIONS, 5)
    assert calc_final_score(scores, weights) == pytest.approx(5.0, abs=1e-9)


def test_calc_final_score_missing_dim_raises():
    weights = {d: 0.166 for d in WEIGHT_DIMENSIONS}
    scores = {WEIGHT_DIMENSIONS[0]: 5}
    with pytest.raises(ValueError, match="missing dimensions"):
        calc_final_score(scores, weights)


# ---- decide_tier --------------------------------------------------------


def _rules():
    return [("S", 8.0), ("A", 7.0), ("B", 6.0), ("C", 5.0)]


def test_decide_tier_boundary_S():
    assert decide_tier(8.0, _rules()) == "S"
    assert decide_tier(7.99, _rules()) == "A"


def test_decide_tier_all_thresholds():
    rules = _rules()
    assert decide_tier(9.5, rules) == "S"
    assert decide_tier(7.5, rules) == "A"
    assert decide_tier(6.5, rules) == "B"
    assert decide_tier(5.5, rules) == "C"


def test_decide_tier_below_lowest_is_C():
    assert decide_tier(4.99, _rules()) == "C"
    assert decide_tier(0.0, _rules()) == "C"


def test_decide_tier_epsilon_absorbs_normalize_drift():
    """7×normalized-weights can land at 6.99999... — that should still be A,
    not B (the user wrote scores=[7,7,7,7,7,7] expecting A)."""
    drifted = 7.0 - 1e-9
    assert decide_tier(drifted, _rules()) == "A"


# ---- Phase 12 (B4a): yaml-driven dimensions ----------------------------


def test_load_dimensions_from_yaml(monkeypatch, tmp_path):
    """An explicit `dimensions:` block returns the listed entries verbatim."""
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        dimensions:
          - key: pain_severity
            label: Pain
            description: How much it hurts.
          - key: budget_authority
            label: Budget authority
            description: Decision maker has signing authority.
        default:
          pain_severity: 0.6
          budget_authority: 0.4
        products: {}
    """)
    dims = load_dimensions()
    assert [d.key for d in dims] == ["pain_severity", "budget_authority"]
    assert dims[0].label == "Pain"
    assert dims[1].description.startswith("Decision maker")


def test_load_dimensions_fallback_when_block_absent(monkeypatch, tmp_path):
    """A legacy yaml without `dimensions:` falls back to the hardcoded six."""
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        default:
          pain_severity: 0.25
          data_complexity: 0.20
          governance_need: 0.15
          ai_maturity: 0.15
          buying_trigger: 0.15
          displacement_ease: 0.10
        products: {}
    """)
    dims = load_dimensions()
    keys = [d.key for d in dims]
    assert keys == [
        "pain_severity", "data_complexity", "governance_need",
        "ai_maturity", "buying_trigger", "displacement_ease",
    ]
    assert get_dimension_keys() == tuple(keys)


def test_load_weights_with_custom_dimension(monkeypatch, tmp_path):
    """Adding a brand-new dimension via yaml wires through load_weights."""
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        dimensions:
          - key: pain_severity
            label: Pain
            description: ""
          - key: budget_authority
            label: Budget
            description: ""
        default:
          pain_severity: 0.5
          budget_authority: 0.5
        products:
          enterprise:
            description: Enterprise tilt
            weights:
              budget_authority: 0.7
    """)
    w_default = load_weights()
    w_ent = load_weights("enterprise")
    assert set(w_default.keys()) == {"pain_severity", "budget_authority"}
    assert sum(w_default.values()) == pytest.approx(1.0, abs=1e-9)
    # enterprise tilt raises budget_authority relative weight
    assert w_ent["budget_authority"] / w_ent["pain_severity"] > (
        w_default["budget_authority"] / w_default["pain_severity"]
    )


def test_load_weights_missing_custom_dimension_raises(monkeypatch, tmp_path):
    """If yaml declares a dimension but `default` omits it, load fails loud."""
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        dimensions:
          - key: pain_severity
            label: Pain
            description: ""
          - key: budget_authority
            label: Budget
            description: ""
        default:
          pain_severity: 1.0
        products: {}
    """)
    with pytest.raises(ValueError, match="missing dimensions.*budget_authority"):
        load_weights()


def test_calc_final_score_uses_yaml_dimensions(monkeypatch, tmp_path):
    """`calc_final_score` walks the yaml-declared dimension set, not the legacy 6."""
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        dimensions:
          - key: pain_severity
            label: Pain
            description: ""
          - key: budget_authority
            label: Budget
            description: ""
        default:
          pain_severity: 0.5
          budget_authority: 0.5
        products: {}
    """)
    weights = {"pain_severity": 0.5, "budget_authority": 0.5}
    scores = {"pain_severity": 8, "budget_authority": 6}
    assert calc_final_score(scores, weights) == pytest.approx(7.0, abs=1e-9)


def test_dimensions_yaml_rejects_duplicate_keys(monkeypatch, tmp_path):
    _patch_yaml(monkeypatch, tmp_path, weights_body="""\
        version: 1
        dimensions:
          - key: pain_severity
            label: Pain
            description: ""
          - key: pain_severity
            label: Other
            description: ""
        default:
          pain_severity: 1.0
        products: {}
    """)
    with pytest.raises(ValueError, match="duplicate dimension key"):
        load_dimensions()
