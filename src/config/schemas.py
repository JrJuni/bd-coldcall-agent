from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Secrets(BaseSettings):
    """API keys loaded from .env at the project root."""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: str = ""
    brave_search_api_key: str = ""
    notion_token: str = ""


class LLMSettings(BaseModel):
    local_model: str
    quantization: Literal["4bit", "fp16"] = "4bit"
    claude_model: str
    claude_max_tokens_synthesize: int = 2000
    claude_max_tokens_draft: int = 4000
    # Phase 9 — discover emits 5 industries + 25 candidates with rationales,
    # which routinely overflows 2000 tokens. Phase 9.1 raised to 6000 because
    # the per-candidate scores dict (6 keys) + region/sector_leaders prompt
    # context push output past 4000.
    claude_max_tokens_discover: int = 6000
    claude_temperature: float = 0.3
    claude_rag_top_k: int = 8


class SearchSettings(BaseModel):
    default_lang: Literal["en", "ko"] = "en"
    days: int = 30
    max_results_per_query: int = 10
    max_articles: int = 20
    min_article_length: int = 200
    # When primary query is Korean, also run an English search with a
    # translated query and blend results so foreign (en) media ≥ min_foreign_ratio.
    bilingual_on_ko: bool = True
    min_foreign_ratio: float = 0.5
    dedup_similarity_threshold: float = 0.90
    min_articles_after_dedup: int = 10
    translations_ko_to_en: dict[str, str] = Field(default_factory=dict)
    # Phase 8 — per-channel article cap applied at preprocess time.
    # Keys: "target", "related", "competitor". Total ~40 keeps Exaone 4bit
    # within RTX 4070 16GB headroom.
    max_articles_per_channel: dict[str, int] = Field(
        default_factory=lambda: {"target": 20, "related": 15, "competitor": 5}
    )
    # Phase 8 — fetch_bodies_parallel worker count (raise as channel volume grows).
    fetch_workers: int = 5


class CompetitorsConfig(BaseModel):
    """Shape of `config/competitors.yaml` — Phase 8 (B) channel."""

    direct: list[str] = Field(default_factory=list)
    adjacent: list[str] = Field(default_factory=list)


class IntentTierEntry(BaseModel):
    label: str
    tier: Literal["S", "A", "B", "C"]
    description: str = ""
    keywords_en: list[str] = Field(default_factory=list)
    keywords_ko: list[str] = Field(default_factory=list)


class IntentTiersConfig(BaseModel):
    """Shape of `config/intent_tiers.yaml` — Phase 8 (A) Related channel."""

    intents: list[IntentTierEntry] = Field(default_factory=list)


class WeightsConfig(BaseModel):
    """Shape of `config/weights.yaml` — Phase 9.1 scoring engine.

    `default` carries the base weight per dimension. `products[<name>]` is a
    partial override — only the dimensions you want to bend need to appear.
    The runtime merges default + override, then auto-normalizes so the
    weighted sum of 0-10 scores stays in 0-10.
    """

    version: int = 1
    default: dict[str, float] = Field(default_factory=dict)
    products: dict[str, dict[str, float]] = Field(default_factory=dict)


class TierRulesConfig(BaseModel):
    """Shape of `config/tier_rules.yaml` — Phase 9.1 tier threshold rules."""

    version: int = 1
    tiers: dict[str, float] = Field(default_factory=dict)


class SectorLeader(BaseModel):
    """One row of `config/sector_leaders.yaml` — Phase 9.1 mega-cap bias mitigation."""

    name: str
    industry_hint: str
    region: Literal["ko", "us", "eu", "global"]
    notes: str = ""


class SectorLeadersConfig(BaseModel):
    """Shape of `config/sector_leaders.yaml`."""

    version: int = 1
    companies: list[SectorLeader] = Field(default_factory=list)


class RAGSettings(BaseModel):
    embedding_model: str
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k: int = 5
    vectorstore_path: Path = Path("data/vectorstore")
    collection_name: str = "bd_tech_docs"
    # Documents whose normalized content length is below this get a single
    # chunk (with warn). Below 1 they are skipped entirely.
    min_document_chars: int = 40


class OutputSettings(BaseModel):
    dir: Path = Path("outputs")
    intermediate: bool = True


class Settings(BaseModel):
    """Runtime defaults loaded from config/settings.yaml."""

    llm: LLMSettings
    search: SearchSettings
    rag: RAGSettings
    output: OutputSettings


class CollectionOverride(BaseModel):
    days: int | None = None
    max_results_per_query: int | None = None
    exclude_domains: list[str] = Field(default_factory=list)
    # Per-industry (or global) overrides for bilingual blending. None = inherit
    # from settings.search.{bilingual_on_ko, min_foreign_ratio}. Set bilingual=False
    # + foreign_ratio=0.0 for domains where foreign media is unnatural
    # (e.g. Korean public-sector procurement).
    bilingual: bool | None = None
    foreign_ratio: float | None = None


class Industry(BaseModel):
    keywords_en: list[str] = Field(default_factory=list)
    keywords_ko: list[str] = Field(default_factory=list)
    collection: CollectionOverride = Field(default_factory=CollectionOverride)


class Target(BaseModel):
    name: str
    industry: str
    aliases: list[str] = Field(default_factory=list)
    notes: str = ""


class RAGSources(BaseModel):
    notion_page_ids: list[str] = Field(default_factory=list)
    notion_database_ids: list[str] = Field(default_factory=list)


class Targets(BaseModel):
    """User data loaded from config/targets.yaml."""

    industries: dict[str, Industry]
    targets: list[Target]
    collection: CollectionOverride = Field(default_factory=CollectionOverride)
    rag: RAGSources = Field(default_factory=RAGSources)
