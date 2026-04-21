"""Error taxonomy for Phase 5 LangGraph retry routing.

Two exception classes let us configure `RetryPolicy(retry_on=...)` at the
node level so only network/transient failures trigger graph-level retry.
Schema / validation failures are Fatal because the inner synthesize/draft
functions already retry once with a temperature bump — a second graph-level
retry would just waste tokens.

StageError is the serializable record written into `AgentState.errors` by
the safe-execute wrapper in `nodes.py`. It never carries a traceback — only
type name + message — because the state is JSON-dumped into the run summary
and must be loss-tolerant.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


class TransientError(Exception):
    """Retryable at the graph level (network, timeout, rate limit)."""


class FatalError(Exception):
    """Not retryable at the graph level.

    Synthesize/draft already retry once internally with a temperature bump;
    a second graph-level retry on schema failures burns tokens without
    changing the outcome.
    """


@dataclass
class StageError:
    stage: str
    error_type: str
    message: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_exception(cls, stage: str, exc: BaseException) -> "StageError":
        return cls(
            stage=stage,
            error_type=type(exc).__name__,
            message=str(exc),
        )
