from __future__ import annotations

from email.utils import format_datetime
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dealsgalore.config import Config, GiftProfile, Settings, WatchItem

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def feed_xml() -> str:
    now = format_datetime(datetime.now(timezone.utc))
    return (FIXTURES / "slickdeals.xml").read_text().replace("{now}", now)


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        settings=Settings(instant_threshold=0.8, digest_threshold=0.5),
        sources=[],
        watchlist=[WatchItem(item="Dyson V15 Detect", match=["dyson", "v15"], max_price=500)],
        gift_profiles=[
            GiftProfile(name="Niece", interests=["lego", "art supplies"], budget=(25, 60))
        ],
        llm_providers=[],
        dashboard={"enabled": True, "min_score": 0.5, "max_items": 50,
                   "output": str(tmp_path / "docs" / "index.html")},
    )
