"""Phase 13A - Sonnet RFP-answer LLM call.

Parallel to `src/llm/synthesize.py`. Takes a question + retrieved chunks,
returns one validated `RfpAnswerDraft` plus the usage dict.

Prompt-cache structure: the retrieved chunks form the cached block (they
change per question but if multiple RFP questions hit a similar topic
the cache may still help), the question + task is the volatile block.
Single retry with temperature bumped +0.1 on JSON / schema failure,
same policy as synthesize_proposal_points.
"""
from __future__ import annotations

from typing import Any, Literal

from src.config.loader import PROJECT_ROOT, get_settings
from src.llm.claude_client import USAGE_KEYS, chat_cached
from src.llm.rfp_schemas import RfpAnswerDraft, parse_rfp_answer
from src.rag.types import RetrievedChunk


_SYSTEM_TASK_SEPARATOR = "---TASK---"

# Versioned identifiers so each rfp_answers row records which model
# family + prompt revision produced it. Bump PROMPT_VERSION whenever the
# prompt files materially change.
PROMPT_VERSION = "rfp_answer.v1"


def _load_prompt(lang: Literal["en", "ko"]) -> tuple[str, str]:
    path = PROJECT_ROOT / "src" / "prompts" / lang / "rfp_answer.txt"
    content = path.read_text(encoding="utf-8")
    parts = content.split(_SYSTEM_TASK_SEPARATOR, 1)
    if len(parts) != 2:
        raise ValueError(
            f"rfp_answer.txt ({lang}) must contain the "
            f"{_SYSTEM_TASK_SEPARATOR!r} delimiter."
        )
    return parts[0].strip(), parts[1].strip()


def _render_chunks_block(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no chunks retrieved)"
    lines: list[str] = []
    for i, rc in enumerate(chunks):
        c = rc.chunk
        chunk_id = f"{c.doc_id}::{c.chunk_index}"
        lines.append(
            f'  <chunk id="{chunk_id}" title="{c.title}" source="{c.source_ref}" '
            f'similarity="{rc.similarity_score:.3f}">'
        )
        lines.append(c.text.strip())
        lines.append("  </chunk>")
    return "\n".join(lines)


def synthesize_rfp_answer(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    lang: Literal["en", "ko"] = "en",
    client: Any | None = None,
) -> tuple[RfpAnswerDraft, dict[str, int], str]:
    """Produce one validated RfpAnswerDraft + accumulated usage + model id.

    Returns `(draft, usage, model_id)`. `model_id` is whichever Sonnet
    version chat_cached actually used, so the caller can stamp it onto
    the `rfp_answers.model_version` column.

    Raises ValueError after the second attempt fails.
    """
    if not question or not question.strip():
        raise ValueError("question must be non-empty")

    settings = get_settings()
    system, task_template = _load_prompt(lang)

    chunks_block = _render_chunks_block(chunks)
    # The task template uses {chunks_block} and {question}; substitute
    # before chat_cached splits caching boundaries.
    task = task_template.format(chunks_block=chunks_block, question=question)

    # Reuse the synthesize max_tokens knob - RFP answers are typically
    # shorter than full proposals, but the budget headroom is harmless.
    max_tokens = settings.llm.claude_max_tokens_synthesize
    base_temp = settings.llm.claude_temperature
    temperatures = [base_temp, min(base_temp + 0.1, 1.0)]

    total_usage: dict[str, int] = {k: 0 for k in USAGE_KEYS}
    last_model = settings.llm.claude_model
    last_error: Exception | None = None

    for temp in temperatures:
        resp = chat_cached(
            system=system,
            cached_context=chunks_block,
            volatile_context="",
            task=task,
            max_tokens=max_tokens,
            temperature=temp,
            client=client,
        )
        resp_usage = resp.get("usage", {}) or {}
        for k in USAGE_KEYS:
            total_usage[k] += int(resp_usage.get(k, 0) or 0)
        last_model = resp.get("model") or last_model
        try:
            return parse_rfp_answer(resp["text"]), total_usage, last_model
        except Exception as e:
            last_error = e
            continue

    raise ValueError(
        f"synthesize_rfp_answer failed after {len(temperatures)} attempts: {last_error}"
    ) from last_error
