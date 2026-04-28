"""bge-m3 embeddings + batch dedup.

Loads the embedding model once (shared with Phase 3 RAG). The dedup routine is
conservative — it only merges pairs whose cosine similarity is at or above
`threshold`, and stops merging early if continuing would drop the survivor
count below `min_articles_after_dedup`. This protects against the pathological
case where every article in the batch is a reprint of the same press release.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np

from src.config.loader import get_settings
from src.search.base import Article


_LOCK = threading.Lock()
_MODEL = None


def get_embedder():
    """Lazy-load the sentence-transformers bge-m3 model."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _LOCK:
        if _MODEL is not None:
            return _MODEL
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        # Force safetensors — some HF snapshots still ship `.bin` which
        # transformers refuses to load on torch < 2.6 (CVE-2025-32434).
        _MODEL = SentenceTransformer(
            settings.rag.embedding_model,
            model_kwargs={"use_safetensors": True},
        )
        return _MODEL


def embed_texts(texts: list[str], *, batch_size: int = 8) -> np.ndarray:
    """Return a (N, D) L2-normalized embedding matrix (cosine-ready).

    `batch_size` defaults to 8 — small enough that Exaone 4bit (~6GB) and
    bge-m3 (~2.5GB) co-exist in 16GB GPU memory even when dedup runs on
    ~40 long article bodies. Increase only if running on a bigger card.
    """
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    model = get_embedder()
    emb = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        batch_size=batch_size,
    )
    return np.asarray(emb, dtype=np.float32)


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        # Deterministic: attach larger root to smaller so group rep index is lowest.
        if ra < rb:
            self.parent[rb] = ra
        else:
            self.parent[ra] = rb
        return True

    def num_groups(self) -> int:
        return len({self.find(i) for i in range(len(self.parent))})


@dataclass
class DedupReport:
    n_input: int
    n_output: int
    n_groups_merged: int
    threshold_used: float
    min_floor: int
    pairs_considered: int
    pairs_merged: int
    stopped_by_floor: bool

    def describe(self) -> str:
        return (
            f"dedup: {self.n_input} -> {self.n_output} "
            f"(merged {self.pairs_merged} pairs, {self.n_groups_merged} multi-article groups, "
            f"threshold={self.threshold_used:.2f}, floor={self.min_floor}"
            f"{', floor-clamped' if self.stopped_by_floor else ''})"
        )


_CHANNEL_RANK = {"target": 0, "related": 1, "competitor": 2}


def _pick_representative(indices: list[int], articles: list[Article]) -> int:
    """Deterministic rep across a dedup group.

    Sort key (lower wins): channel rank → -body length → -timestamp → index.
    Phase 8: channel rank ensures `target` survives over `related` /
    `competitor` when the same story surfaces from multiple channels.
    """
    def sort_key(i: int):
        a = articles[i]
        ch_rank = _CHANNEL_RANK.get(getattr(a, "channel", "target"), 99)
        body_len = len(a.translated_body or a.body or a.snippet)
        ts = a.published_at.timestamp() if a.published_at else 0.0
        return (ch_rank, -body_len, -ts, i)
    return min(indices, key=sort_key)


def dedup_articles(
    articles: list[Article],
    *,
    threshold: Optional[float] = None,
    min_articles: Optional[int] = None,
) -> tuple[list[Article], DedupReport]:
    """Return (kept_articles, report). Also writes `dedup_group_id` on all inputs."""
    settings = get_settings()
    thr = threshold if threshold is not None else settings.search.dedup_similarity_threshold
    floor = min_articles if min_articles is not None else settings.search.min_articles_after_dedup

    n = len(articles)
    if n <= 1:
        for a in articles:
            a.dedup_group_id = -1
        return list(articles), DedupReport(
            n_input=n, n_output=n, n_groups_merged=0,
            threshold_used=thr, min_floor=floor,
            pairs_considered=0, pairs_merged=0, stopped_by_floor=False,
        )

    # Truncate to keep peak GPU memory bounded — dedup similarity at ≥0.90
    # is dominated by lede / first paragraphs, so 3000 chars is plenty.
    # Without this, ~40 articles × ~3500 chars each can OOM bge-m3 on a
    # 16GB card while Exaone is still resident.
    texts = [
        (a.translated_body or a.body or a.snippet or a.title or "")[:3000]
        for a in articles
    ]
    # Free any cached GPU blocks Exaone left behind so bge-m3's batch
    # allocation has contiguous room.
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 — defensive, never fail dedup over cleanup
        pass

    embs = embed_texts(texts)
    sim = embs @ embs.T  # cosine, since rows are unit-norm

    pairs: list[tuple[float, int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            s = float(sim[i, j])
            if s >= thr:
                pairs.append((s, i, j))
    pairs.sort(reverse=True)  # highest similarity first

    uf = _UnionFind(n)
    merged = 0
    stopped = False
    for s, i, j in pairs:
        if uf.find(i) == uf.find(j):
            continue
        if uf.num_groups() <= floor:
            stopped = True
            break
        uf.union(i, j)
        merged += 1

    # Group indices → members
    groups: dict[int, list[int]] = {}
    for idx in range(n):
        groups.setdefault(uf.find(idx), []).append(idx)

    kept_indices: list[int] = []
    group_id_for_article: dict[int, int] = {}
    multi_groups = 0
    for gid_counter, members in enumerate(groups.values()):
        rep = _pick_representative(members, articles)
        kept_indices.append(rep)
        assigned_gid = gid_counter if len(members) > 1 else -1
        if len(members) > 1:
            multi_groups += 1
        for m in members:
            group_id_for_article[m] = assigned_gid

    for idx in range(n):
        articles[idx].dedup_group_id = group_id_for_article.get(idx, -1)

    # Preserve original order in output.
    kept_indices.sort()
    kept = [articles[i] for i in kept_indices]
    report = DedupReport(
        n_input=n,
        n_output=len(kept),
        n_groups_merged=multi_groups,
        threshold_used=thr,
        min_floor=floor,
        pairs_considered=len(pairs),
        pairs_merged=merged,
        stopped_by_floor=stopped,
    )
    return kept, report
