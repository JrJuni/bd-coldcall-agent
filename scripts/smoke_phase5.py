"""Phase 5 end-to-end smoke — full 6-stage pipeline in one invocation.

Replaces `scripts/smoke_phase4.py` (which starts from a preprocess JSON) with
a real Brave → fetch → Exaone preprocess → RAG retrieve → Sonnet synthesize
→ Sonnet draft → persist chain. Expected runtime: ~90-120s (bge-m3 load,
Exaone 4bit on GPU, two Sonnet calls). Expected spend: ~$0.30-0.60 for
typical 20-article batches.

Run:

    ~/miniconda3/envs/bd-coldcall/python.exe -m scripts.smoke_phase5 \\
        --company NVIDIA --industry semiconductor --lang en

Outputs:
  outputs/{company}_{YYYYMMDD}/proposal.md
  outputs/{company}_{YYYYMMDD}/intermediate/{articles_after_preprocess,
                                             tech_chunks,
                                             points,
                                             run_summary}.json
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config.loader import PROJECT_ROOT
from src.core.orchestrator import run as run_pipeline


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="Phase 5 full pipeline smoke")
    ap.add_argument("--company", required=True)
    ap.add_argument("--industry", required=True)
    ap.add_argument("--lang", choices=["en", "ko"], default="en")
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Parent directory for per-run outputs. Defaults to settings.output.dir",
    )
    ap.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable INFO logs from node adapters (stage-by-stage progress).",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print(
        f"→ Phase 5 pipeline: company={args.company!r} industry={args.industry!r} "
        f"lang={args.lang}"
    )
    result = run_pipeline(
        company=args.company,
        industry=args.industry,
        lang=args.lang,
        output_root=args.output_root,
        top_k=args.top_k,
    )

    output_dir = Path(result["output_dir"])
    summary_path = output_dir / "intermediate" / "run_summary.json"

    print()
    print("=" * 60)
    print(f"stages completed : {', '.join(result.get('stages_completed') or [])}")
    print(f"failed_stage     : {result.get('failed_stage')}")
    print(f"articles         : {len(result.get('articles') or [])}")
    print(f"tech chunks      : {len(result.get('tech_chunks') or [])}")
    print(f"proposal points  : {len(result.get('proposal_points') or [])}")
    usage = result.get("usage") or {}
    print(
        "sonnet usage     : "
        f"in={usage.get('input_tokens', 0)} "
        f"out={usage.get('output_tokens', 0)} "
        f"cache_read={usage.get('cache_read_input_tokens', 0)} "
        f"cache_write={usage.get('cache_creation_input_tokens', 0)}"
    )
    errors = result.get("errors") or []
    if errors:
        print(f"errors           : {len(errors)}")
        for err in errors:
            print(f"  - [{err.get('stage')}] {err.get('error_type')}: {err.get('message')}")

    try:
        md_rel = (output_dir / "proposal.md").relative_to(PROJECT_ROOT)
    except ValueError:
        md_rel = output_dir / "proposal.md"
    try:
        summary_rel = summary_path.relative_to(PROJECT_ROOT)
    except ValueError:
        summary_rel = summary_path
    print()
    if (output_dir / "proposal.md").exists():
        print(f"[OK] proposal.md   -> {md_rel}")
    else:
        print("[-]  proposal.md   -> (not written; pipeline failed before draft)")
    print(f"[OK] run_summary   -> {summary_rel}")

    return 0 if not result.get("failed_stage") else 1


if __name__ == "__main__":
    raise SystemExit(main())
