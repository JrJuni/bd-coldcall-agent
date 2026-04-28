"""Phase 8 Stream 3 — multi-channel registry / fan-out integration."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from src.config.schemas import (
    CompetitorsConfig,
    IntentTierEntry,
    IntentTiersConfig,
    LLMSettings,
    OutputSettings,
    RAGSettings,
    SearchSettings,
    Settings,
)
from src.search import channels as channels_module
from src.search.base import Article


def _settings() -> Settings:
    return Settings(
        llm=LLMSettings(
            local_model="x", quantization="4bit", claude_model="y",
        ),
        search=SearchSettings(
            default_lang="en",
            days=30,
            max_articles_per_channel={"target": 20, "related": 15, "competitor": 5},
        ),
        rag=RAGSettings(embedding_model="z"),
        output=OutputSettings(),
    )


def _article(url: str, channel: str = "target") -> Article:
    a = Article(
        title=f"T-{url}",
        url=url,
        snippet="snip",
        source="src",
        lang="en",
        published_at=datetime(2026, 4, 20),
    )
    a.channel = channel
    return a


@pytest.fixture
def fake_brave(monkeypatch):
    """Replace BraveSearch ctx-manager with a no-op stub."""
    class _Ctx:
        def __init__(self, _key): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(channels_module, "BraveSearch", _Ctx)


def test_run_all_channels_merges_three_channels(monkeypatch, fake_brave):
    """Each of target/related/competitor returns articles → merged."""
    monkeypatch.setattr(
        channels_module._config_loader,
        "load_intent_tiers",
        lambda: IntentTiersConfig(),
    )
    monkeypatch.setattr(
        channels_module._config_loader,
        "load_competitors",
        lambda: CompetitorsConfig(),
    )

    monkeypatch.setattr(
        channels_module,
        "run_target",
        lambda *a, **kw: ([_article("https://t.com/1", "target")], {"returned": 1}),
    )
    monkeypatch.setattr(
        channels_module,
        "run_related",
        lambda *a, **kw: ([_article("https://r.com/1", "related")], {"returned": 1}),
    )
    monkeypatch.setattr(
        channels_module,
        "run_competitor",
        lambda *a, **kw: ([_article("https://c.com/1", "competitor")], {"returned": 1}),
    )

    arts, meta = channels_module.run_all_channels(
        company="X",
        primary_lang="en",
        settings=_settings(),
        brave_api_key="stub",
    )
    assert {a.channel for a in arts} == {"target", "related", "competitor"}
    assert meta["total_after_xchannel_dedup"] == 3
    assert meta["channel_errors"] == {}


def test_run_all_channels_xchannel_dedup_target_wins(monkeypatch, fake_brave):
    """If target and competitor return the same URL, target keeps it."""
    monkeypatch.setattr(channels_module._config_loader, "load_intent_tiers", lambda: IntentTiersConfig())
    monkeypatch.setattr(channels_module._config_loader, "load_competitors", lambda: CompetitorsConfig())

    shared = "https://news.com/shared"
    monkeypatch.setattr(
        channels_module,
        "run_target",
        lambda *a, **kw: ([_article(shared, "target")], {"returned": 1}),
    )
    monkeypatch.setattr(
        channels_module,
        "run_related",
        lambda *a, **kw: ([], {"returned": 0}),
    )
    monkeypatch.setattr(
        channels_module,
        "run_competitor",
        lambda *a, **kw: ([_article(shared, "competitor")], {"returned": 1}),
    )

    arts, _ = channels_module.run_all_channels(
        company="X",
        primary_lang="en",
        settings=_settings(),
        brave_api_key="stub",
    )
    assert len(arts) == 1
    assert arts[0].channel == "target"


def test_run_all_channels_partial_failure_isolated(monkeypatch, fake_brave):
    """One channel raising doesn't kill the others."""
    monkeypatch.setattr(channels_module._config_loader, "load_intent_tiers", lambda: IntentTiersConfig())
    monkeypatch.setattr(channels_module._config_loader, "load_competitors", lambda: CompetitorsConfig())

    monkeypatch.setattr(
        channels_module,
        "run_target",
        lambda *a, **kw: ([_article("https://t.com/1", "target")], {"returned": 1}),
    )

    def _boom(*a, **kw):
        raise RuntimeError("brave 5xx")

    monkeypatch.setattr(channels_module, "run_related", _boom)
    monkeypatch.setattr(
        channels_module,
        "run_competitor",
        lambda *a, **kw: ([_article("https://c.com/1", "competitor")], {"returned": 1}),
    )

    arts, meta = channels_module.run_all_channels(
        company="X",
        primary_lang="en",
        settings=_settings(),
        brave_api_key="stub",
    )
    assert len(arts) == 2
    assert "related" in meta["channel_errors"]
    assert meta["channel_errors"]["related"] == "brave 5xx"


def test_run_all_channels_per_channel_caps_from_settings(monkeypatch, fake_brave):
    """Cap dict from settings is forwarded to each channel function."""
    captured: dict[str, int] = {}

    monkeypatch.setattr(channels_module._config_loader, "load_intent_tiers", lambda: IntentTiersConfig())
    monkeypatch.setattr(channels_module._config_loader, "load_competitors", lambda: CompetitorsConfig())

    def _cap_target(*a, **kw):
        captured["target"] = kw["cap"]
        return [], {"returned": 0}

    def _cap_related(*a, **kw):
        captured["related"] = kw["cap"]
        return [], {"returned": 0}

    def _cap_competitor(*a, **kw):
        captured["competitor"] = kw["cap"]
        return [], {"returned": 0}

    monkeypatch.setattr(channels_module, "run_target", _cap_target)
    monkeypatch.setattr(channels_module, "run_related", _cap_related)
    monkeypatch.setattr(channels_module, "run_competitor", _cap_competitor)

    s = _settings()
    s.search.max_articles_per_channel = {"target": 11, "related": 7, "competitor": 3}
    channels_module.run_all_channels(
        company="X",
        primary_lang="en",
        settings=s,
        brave_api_key="stub",
    )
    assert captured == {"target": 11, "related": 7, "competitor": 3}


def test_dedup_pick_representative_prefers_target_channel():
    """Stream 3 — `_pick_representative` orders by channel rank."""
    from src.rag.embeddings import _pick_representative

    target_art = _article("https://news.com/x", "target")
    related_art = _article("https://news.com/x", "related")
    competitor_art = _article("https://news.com/x", "competitor")

    # Make competitor's body longer so the body-length tiebreak would
    # prefer it — channel rank should still win.
    competitor_art.body = "x" * 1000
    competitor_art.translated_body = "x" * 1000

    arts = [competitor_art, related_art, target_art]
    rep = _pick_representative([0, 1, 2], arts)
    assert arts[rep].channel == "target"
