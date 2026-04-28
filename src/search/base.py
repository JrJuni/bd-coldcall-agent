from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


Lang = Literal["en", "ko"]
Kind = Literal["news", "web"]
Channel = Literal["target", "related", "competitor"]


@dataclass
class Article:
    title: str
    url: str
    snippet: str
    source: str
    lang: Lang
    published_at: datetime | None = None
    metadata: dict = field(default_factory=dict)
    body: str = ""
    body_source: Literal["full", "snippet", "empty"] = "empty"
    # Phase 2 outputs
    translated_body: str = ""
    tags: list[str] = field(default_factory=list)
    dedup_group_id: int = -1  # -1 = solo; otherwise group index
    # Phase 8 — collection channel. "target" = the company itself,
    # "related" = our-product ↔ company intent matches, "competitor" =
    # competitor product/project news. Default keeps pre-Phase-8 outputs
    # JSON-loadable.
    channel: Channel = "target"


class SearchProvider(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        *,
        lang: Lang,
        days: int,
        kind: Kind = "news",
        count: int = 10,
    ) -> list[Article]:
        ...
