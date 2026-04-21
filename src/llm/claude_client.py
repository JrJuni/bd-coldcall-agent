"""Anthropic Claude client — singleton + prompt-cache-aware wrapper.

The BD pipeline hits Sonnet 4.6 twice per target (synthesize → draft). Both
calls share the same tech-docs context via `cache_control: ephemeral` so
running multiple targets against one knowledge base stays near-free on the
cached portion.

Prompt layout this module assumes (caller's responsibility to assemble):

    system:   role + strict constraints (cacheable)
    user:     <tech_docs>   ← cache_control goes HERE as a separate content block
              <articles>
              <task>

The `chat_cached` helper takes pre-split pieces and attaches
`cache_control={"type":"ephemeral"}` to the tech_docs block only. Articles
and task change per target, so they remain uncached.
"""
from __future__ import annotations

import threading
from typing import Any

from src.config.loader import get_secrets, get_settings


USAGE_KEYS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


_LOCK = threading.Lock()
_CLIENT = None


def get_claude():
    """Lazy-load the Anthropic SDK client as a process-wide singleton."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    with _LOCK:
        if _CLIENT is not None:
            return _CLIENT
        import anthropic

        secrets = get_secrets()
        if not secrets.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set in .env — required for Phase 4"
            )
        _CLIENT = anthropic.Anthropic(api_key=secrets.anthropic_api_key)
        return _CLIENT


def reset_client_singleton() -> None:
    """Drop the cached client — test hook only."""
    global _CLIENT
    with _LOCK:
        _CLIENT = None


def chat_cached(
    *,
    system: str,
    cached_context: str,
    volatile_context: str,
    task: str,
    max_tokens: int,
    temperature: float | None = None,
    model: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Single Sonnet call with prompt caching on the shared context block.

    Returns a dict with `text`, `usage` (input/output/cache_read/cache_write
    token counts if provided), `stop_reason`, `model`. The two-block user
    layout is what triggers ephemeral caching: the tech-docs block must be
    the first user content so subsequent calls hit the cache prefix.
    """
    settings = get_settings()
    chosen_model = model or settings.llm.claude_model
    temp = (
        temperature
        if temperature is not None
        else settings.llm.claude_temperature
    )
    c = client if client is not None else get_claude()

    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": cached_context,
            "cache_control": {"type": "ephemeral"},
        },
    ]
    if volatile_context:
        user_content.append({"type": "text", "text": volatile_context})
    user_content.append({"type": "text", "text": task})

    resp = c.messages.create(
        model=chosen_model,
        max_tokens=max_tokens,
        temperature=temp,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    # Flatten text from content blocks
    text = "".join(
        getattr(block, "text", "") for block in resp.content
    ) if resp.content else ""

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_input_tokens": getattr(
            resp.usage, "cache_read_input_tokens", 0
        ),
        "cache_creation_input_tokens": getattr(
            resp.usage, "cache_creation_input_tokens", 0
        ),
    }

    return {
        "text": text,
        "usage": usage,
        "stop_reason": getattr(resp, "stop_reason", None),
        "model": getattr(resp, "model", chosen_model),
    }


def chat_once(
    *,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float | None = None,
    model: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Single uncached Sonnet call — used where the prompt is unique per call.

    Draft generation falls into this bucket: every target produces its own
    ProposalPoint list, so there's no prefix worth caching across calls.
    Same return shape as `chat_cached`.
    """
    settings = get_settings()
    chosen_model = model or settings.llm.claude_model
    temp = (
        temperature
        if temperature is not None
        else settings.llm.claude_temperature
    )
    c = client if client is not None else get_claude()

    resp = c.messages.create(
        model=chosen_model,
        max_tokens=max_tokens,
        temperature=temp,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    text = "".join(
        getattr(block, "text", "") for block in resp.content
    ) if resp.content else ""

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_input_tokens": getattr(
            resp.usage, "cache_read_input_tokens", 0
        ),
        "cache_creation_input_tokens": getattr(
            resp.usage, "cache_creation_input_tokens", 0
        ),
    }

    return {
        "text": text,
        "usage": usage,
        "stop_reason": getattr(resp, "stop_reason", None),
        "model": getattr(resp, "model", chosen_model),
    }
