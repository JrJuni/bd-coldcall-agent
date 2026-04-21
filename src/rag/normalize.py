"""Content normalization — stable input for content hashing.

The hash that drives incremental indexing (manifest.json) must not flip just
because a Notion block round-tripped with extra trailing whitespace or the
PDF extractor emitted three blank lines instead of two. This function caps
those sources of variance without touching meaningful internal structure
(code indentation, table spacing, single-space runs).

Rules (applied in order):
1. Trailing whitespace on each line removed
2. Runs of 3+ consecutive newlines collapsed to exactly 2
3. Leading/trailing whitespace of the whole string stripped

Inline consecutive spaces are preserved — tables, code blocks, and ASCII art
survive. Only end-of-line and inter-paragraph whitespace is normalized.
"""
from __future__ import annotations

import re


_BLANK_RUN_RE = re.compile(r"\n{3,}")


def normalize_content(text: str) -> str:
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    joined = "\n".join(lines)
    joined = _BLANK_RUN_RE.sub("\n\n", joined)
    return joined.strip()
