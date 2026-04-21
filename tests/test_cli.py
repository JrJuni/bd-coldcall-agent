"""Phase 6 — CLI wiring tests.

`main.py` is a thin Typer wrapper: these tests assert the subcommands
translate flags into the right calls to `orchestrator.run()` and
`indexer.main()`, without touching Brave, ChromaDB, or Sonnet.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import main as cli


runner = CliRunner()


def _fake_result(tmp_path: Path) -> dict:
    return {
        "company": "X",
        "industry": "Y",
        "lang": "en",
        "output_dir": tmp_path,
        "searched_articles": [],
        "fetched_articles": [],
        "processed_articles": [],
        "tech_chunks": [],
        "proposal_points": [],
        "proposal_md": "",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 2,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
        "errors": [],
        "failed_stage": None,
        "stages_completed": ["search", "fetch", "preprocess", "retrieve", "synthesize", "draft", "persist"],
    }


def test_run_forwards_required_args(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def _fake_run(**kwargs):
        captured.update(kwargs)
        return _fake_result(tmp_path)

    monkeypatch.setattr("src.core.orchestrator.run", _fake_run)

    result = runner.invoke(
        cli.app,
        ["run", "--company", "NVIDIA", "--industry", "semiconductor"],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["company"] == "NVIDIA"
    assert captured["industry"] == "semiconductor"
    assert captured["lang"] == "en"  # default
    assert captured["top_k"] is None
    assert captured["output_root"] is None


def test_run_passes_top_k_and_output_root(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def _fake_run(**kwargs):
        captured.update(kwargs)
        return _fake_result(tmp_path)

    monkeypatch.setattr("src.core.orchestrator.run", _fake_run)

    result = runner.invoke(
        cli.app,
        [
            "run",
            "--company", "Samsung",
            "--industry", "semiconductor",
            "--lang", "ko",
            "--top-k", "12",
            "--output-root", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["lang"] == "ko"
    assert captured["top_k"] == 12
    assert captured["output_root"] == tmp_path


def test_run_rejects_invalid_lang(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "src.core.orchestrator.run",
        lambda **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    result = runner.invoke(
        cli.app,
        ["run", "--company", "X", "--industry", "Y", "--lang", "fr"],
    )
    assert result.exit_code != 0


def test_run_nonzero_exit_on_failed_stage(monkeypatch, tmp_path: Path):
    def _fake_run(**kwargs):
        r = _fake_result(tmp_path)
        r["failed_stage"] = "search"
        r["errors"] = [{"stage": "search", "error_type": "RuntimeError", "message": "boom", "ts": "t"}]
        return r

    monkeypatch.setattr("src.core.orchestrator.run", _fake_run)

    result = runner.invoke(
        cli.app,
        ["run", "--company", "X", "--industry", "Y"],
    )
    assert result.exit_code == 1
    assert "failed_stage" in result.stdout


def test_ingest_forwards_flags_to_indexer_main(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def _fake_indexer_main(argv):
        captured["argv"] = list(argv)
        return 0

    monkeypatch.setattr("src.rag.indexer.main", _fake_indexer_main)

    result = runner.invoke(
        cli.app,
        ["ingest", "--notion", "--dry-run", "--local-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout
    argv = captured["argv"]
    assert "--notion" in argv
    assert "--dry-run" in argv
    assert "--local-dir" in argv
    assert str(tmp_path) in argv
    # Unpassed flags must not appear
    assert "--force" not in argv
    assert "--verify" not in argv
    assert "--no-local" not in argv


def test_ingest_propagates_nonzero_exit(monkeypatch):
    monkeypatch.setattr("src.rag.indexer.main", lambda argv: 2)

    result = runner.invoke(cli.app, ["ingest", "--verify"])
    assert result.exit_code == 2
