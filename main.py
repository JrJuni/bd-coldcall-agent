"""BD Cold-Call Agent — top-level CLI.

Two subcommands:

  main.py run     — full pipeline for one target (search → … → persist)
  main.py ingest  — index local + Notion docs into the RAG vector store

Both are thin wrappers:
  run     → src.core.orchestrator.run()
  ingest  → src.rag.indexer.main() (argparse-based, forwarded via argv)

Windows-safe: stdout/stderr are reconfigured to UTF-8 before any Korean text
is printed. Pass `--verbose` on `run` for stage-by-stage INFO logs.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

# Reconfigure stdio to UTF-8 before Typer/Rich render any help text —
# Windows cp949 console trips on em-dash/Korean otherwise. Safe no-op on
# streams that already support reconfigure (Python 3.7+ std streams).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (ValueError, AttributeError):
            pass

import typer

from src.config.loader import PROJECT_ROOT


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="BD Cold-Call Agent — search, summarize, and draft proposals for target companies.",
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command("run")
def run_cmd(
    company: str = typer.Option(..., "--company", help="Target company name (used as search + retrieve query)."),
    industry: str = typer.Option(..., "--industry", help="Industry label forwarded to the Sonnet synthesis prompt."),
    lang: str = typer.Option("en", "--lang", help="Output language: 'en' or 'ko'."),
    top_k: Optional[int] = typer.Option(None, "--top-k", help="Override settings.llm.claude_rag_top_k."),
    output_root: Optional[Path] = typer.Option(
        None,
        "--output-root",
        help="Parent directory for per-run outputs. Defaults to settings.output.dir.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable INFO logs for stage-by-stage progress."),
) -> None:
    """Run the full 6-stage pipeline for one target company."""
    if lang not in ("en", "ko"):
        raise typer.BadParameter("--lang must be 'en' or 'ko'", param_hint="--lang")

    _setup_logging(verbose)
    from src.core.orchestrator import run as run_pipeline

    typer.echo(
        f"→ run: company={company!r} industry={industry!r} lang={lang}"
    )
    result = run_pipeline(
        company=company,
        industry=industry,
        lang=lang,  # type: ignore[arg-type]
        output_root=output_root,
        top_k=top_k,
    )

    output_dir = Path(result["output_dir"])
    summary_path = output_dir / "intermediate" / "run_summary.json"

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(f"stages completed : {', '.join(result.get('stages_completed') or [])}")
    typer.echo(f"failed_stage     : {result.get('failed_stage')}")
    typer.echo(
        f"articles         : searched={len(result.get('searched_articles') or [])} "
        f"fetched={len(result.get('fetched_articles') or [])} "
        f"processed={len(result.get('processed_articles') or [])}"
    )
    typer.echo(f"tech chunks      : {len(result.get('tech_chunks') or [])}")
    typer.echo(f"proposal points  : {len(result.get('proposal_points') or [])}")
    usage = result.get("usage") or {}
    typer.echo(
        "sonnet usage     : "
        f"in={usage.get('input_tokens', 0)} "
        f"out={usage.get('output_tokens', 0)} "
        f"cache_read={usage.get('cache_read_input_tokens', 0)} "
        f"cache_write={usage.get('cache_creation_input_tokens', 0)}"
    )
    errors = result.get("errors") or []
    if errors:
        typer.echo(f"errors           : {len(errors)}")
        for err in errors:
            typer.echo(f"  - [{err.get('stage')}] {err.get('error_type')}: {err.get('message')}")

    typer.echo("")
    md_path = output_dir / "proposal.md"
    try:
        md_rel = md_path.relative_to(PROJECT_ROOT)
        summary_rel = summary_path.relative_to(PROJECT_ROOT)
    except ValueError:
        md_rel = md_path
        summary_rel = summary_path
    if md_path.exists():
        typer.echo(f"[OK] proposal.md   -> {md_rel}")
    else:
        typer.echo("[-]  proposal.md   -> (not written; pipeline failed before draft)")
    typer.echo(f"[OK] run_summary   -> {summary_rel}")

    if result.get("failed_stage"):
        raise typer.Exit(code=1)


@app.command("discover")
def discover_cmd(
    lang: str = typer.Option("en", "--lang", help="Output language: 'en' or 'ko'."),
    n_industries: int = typer.Option(5, "--n-industries", help="Number of industries to propose."),
    n_per_industry: int = typer.Option(5, "--n-per-industry", help="Number of companies per industry."),
    seed_summary: Optional[str] = typer.Option(
        None,
        "--seed-summary",
        help="One-paragraph product summary injected as volatile context.",
    ),
    seed_query: str = typer.Option(
        "core capabilities and target use cases",
        "--seed-query",
        help="RAG retrieval query that picks the chunks Sonnet sees.",
    ),
    top_k: int = typer.Option(20, "--top-k", help="Number of RAG chunks to seed."),
    output_root: Optional[Path] = typer.Option(
        None,
        "--output-root",
        help="Parent directory for the discovery_<date>/ folder. Defaults to settings.output.dir.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable INFO logs."),
) -> None:
    """Phase 9 — propose tiered candidate companies from the RAG index alone."""
    if lang not in ("en", "ko"):
        raise typer.BadParameter("--lang must be 'en' or 'ko'", param_hint="--lang")
    if n_industries <= 0 or n_per_industry <= 0:
        raise typer.BadParameter("--n-industries and --n-per-industry must be positive")

    _setup_logging(verbose)
    from src.core.discover import discover_targets

    typer.echo(
        f"→ discover: lang={lang} {n_industries} industries × {n_per_industry} companies"
    )
    result = discover_targets(
        lang=lang,  # type: ignore[arg-type]
        n_industries=n_industries,
        n_per_industry=n_per_industry,
        seed_summary=seed_summary,
        seed_query=seed_query,
        output_root=output_root,
        top_k=top_k,
    )

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(
        f"seed             : {result.seed_doc_count} doc(s), "
        f"{result.seed_chunk_count} chunk(s)"
    )
    typer.echo(f"industries       : {len(result.industry_meta)}")
    typer.echo(f"candidates       : {len(result.candidates)}")
    usage = result.usage or {}
    typer.echo(
        "sonnet usage     : "
        f"in={usage.get('input_tokens', 0)} "
        f"out={usage.get('output_tokens', 0)} "
        f"cache_read={usage.get('cache_read_input_tokens', 0)} "
        f"cache_write={usage.get('cache_creation_input_tokens', 0)}"
    )

    date_str = result.generated_at.strftime("%Y%m%d")
    from src.config.loader import get_settings as _get_settings

    settings = _get_settings()
    root = Path(output_root or settings.output.dir)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    date_dir = root / f"discovery_{date_str}"
    yaml_path = date_dir / "candidates.yaml"
    md_path = date_dir / "report.md"
    try:
        yaml_rel = yaml_path.relative_to(PROJECT_ROOT)
        md_rel = md_path.relative_to(PROJECT_ROOT)
    except ValueError:
        yaml_rel = yaml_path
        md_rel = md_path
    typer.echo("")
    typer.echo(f"[OK] candidates    -> {yaml_rel}")
    typer.echo(f"[OK] report        -> {md_rel}")


@app.command("ingest")
def ingest_cmd(
    local_dir: Optional[Path] = typer.Option(
        None,
        "--local-dir",
        help="Root for the local connector (default: data/company_docs).",
    ),
    no_local: bool = typer.Option(False, "--no-local", help="Disable the local connector entirely."),
    notion: bool = typer.Option(False, "--notion", help="Enable the Notion connector."),
    force: bool = typer.Option(False, "--force", help="Bypass hash comparison and reindex every document."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Scan + hash + chunk but don't embed or write."),
    verify: bool = typer.Option(False, "--verify", help="Report manifest/store drift and exit."),
) -> None:
    """Index local + Notion docs into ChromaDB with incremental hashing."""
    from src.rag.indexer import main as indexer_main

    argv: list[str] = []
    if local_dir is not None:
        argv += ["--local-dir", str(local_dir)]
    if no_local:
        argv.append("--no-local")
    if notion:
        argv.append("--notion")
    if force:
        argv.append("--force")
    if dry_run:
        argv.append("--dry-run")
    if verify:
        argv.append("--verify")

    code = indexer_main(argv)
    if code:
        raise typer.Exit(code=code)


if __name__ == "__main__":
    app()
