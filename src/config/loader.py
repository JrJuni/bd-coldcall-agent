from functools import lru_cache
from pathlib import Path

import yaml

from .schemas import Secrets, Settings, Targets


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


@lru_cache(maxsize=1)
def get_secrets() -> Secrets:
    return Secrets()


@lru_cache(maxsize=1)
def get_settings(path: Path | None = None) -> Settings:
    path = path or (CONFIG_DIR / "settings.yaml")
    with open(path, encoding="utf-8") as f:
        return Settings(**yaml.safe_load(f))


def get_targets(path: Path | None = None) -> Targets:
    path = path or (CONFIG_DIR / "targets.yaml")
    if not path.exists():
        example = CONFIG_DIR / "targets.example.yaml"
        raise FileNotFoundError(
            f"{path} not found. Copy {example.name} to {path.name} and edit your targets."
        )
    with open(path, encoding="utf-8") as f:
        return Targets(**yaml.safe_load(f))
