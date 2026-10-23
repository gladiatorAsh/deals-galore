from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# Gift profiles describe real family members, so they never live in the public
# config. They are read from the GIFT_PROFILES env var (a GitHub secret) or a
# local, git-ignored file.
LOCAL_GIFT_FILES = ("gifts.local.yaml", "gifts.yaml")


@dataclass
class WatchItem:
    item: str
    max_price: float | None = None
    match: list[str] = field(default_factory=list)
    query: str | None = None  # search phrase for sources that support search

    def __post_init__(self) -> None:
        if not self.match:
            self.match = [w for w in self.item.lower().split() if len(w) > 1]
        if not self.query:
            self.query = self.item


@dataclass
class GiftProfile:
    name: str
    interests: list[str] = field(default_factory=list)
    budget: tuple[float, float] | None = None
    keywords: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class LLMProvider:
    name: str
    base_url: str
    model: str
    api_key_env: str

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


@dataclass
class Settings:
    max_age_hours: float = 48
    instant_threshold: float = 0.8
    digest_threshold: float = 0.5
    max_llm_batches_per_run: int = 6
    batch_size: int = 15
    history_days: int = 90
    retention_days: int = 60
    request_timeout: float = 20
    user_agent: str = "deals-galore/0.1"
    exclude_keywords: list[str] = field(default_factory=list)


@dataclass
class Config:
    settings: Settings
    sources: list[dict[str, Any]]
    watchlist: list[WatchItem]
    gift_profiles: list[GiftProfile]
    llm_providers: list[LLMProvider]
    dashboard: dict[str, Any]


def _parse_profiles(raw: Any) -> list[GiftProfile]:
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = raw.get("gift_profiles", [])
    profiles = []
    for p in raw:
        budget = p.get("budget")
        profiles.append(
            GiftProfile(
                name=str(p["name"]),
                interests=[str(i) for i in p.get("interests", [])],
                budget=(float(budget[0]), float(budget[1])) if budget else None,
                keywords=[str(k) for k in p.get("keywords", [])],
                notes=str(p.get("notes", "")),
            )
        )
    return profiles


def load_gift_profiles(base_dir: Path) -> list[GiftProfile]:
    env = os.environ.get("GIFT_PROFILES")
    if env and env.strip():
        return _parse_profiles(yaml.safe_load(env))
    for name in LOCAL_GIFT_FILES:
        path = base_dir / name
        if path.exists():
            return _parse_profiles(yaml.safe_load(path.read_text()))
    log.info("No gift profiles found (set GIFT_PROFILES or create gifts.local.yaml)")
    return []


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}
    settings = Settings(**(data.get("settings") or {}))
    watchlist = [WatchItem(**w) for w in data.get("watchlist") or []]
    providers = [LLMProvider(**p) for p in (data.get("llm") or {}).get("providers", [])]
    dashboard = {"enabled": True, "min_score": 0.5, "max_items": 100, "output": "docs/index.html"}
    dashboard.update(data.get("dashboard") or {})
    return Config(
        settings=settings,
        sources=data.get("sources") or [],
        watchlist=watchlist,
        gift_profiles=load_gift_profiles(path.parent),
        llm_providers=providers,
        dashboard=dashboard,
    )
