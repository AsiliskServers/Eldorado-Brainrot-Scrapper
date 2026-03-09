from __future__ import annotations

import os
from pathlib import Path


DEFAULT_LISTING_URL = (
    "https://www.eldorado.gg/fr/steal-a-brainrot-brainrots/i/259?"
    "lowestPrice=0&highestPrice=50&offerSortingCriterion=Price&isAscending=true&"
    "gamePageOfferIndex=1&gamePageOfferSize=50"
)
DEFAULT_SCRAPE_IMPERSONATE = "chrome"
DEFAULT_SCRAPE_TIMEOUT = 30
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def get_listing_url(default: str = DEFAULT_LISTING_URL) -> str:
    return os.environ.get("LISTING_URL", default)


def get_data_dir(project_root: Path, default_name: str = "data") -> Path:
    configured = os.environ.get("DATA_DIR")
    if configured:
        candidate = Path(configured)
        return candidate if candidate.is_absolute() else (project_root / candidate)
    return project_root / default_name


def get_scrape_timeout(default: int = DEFAULT_SCRAPE_TIMEOUT) -> int:
    raw = os.environ.get("SCRAPE_TIMEOUT")
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def get_scrape_impersonate(default: str = DEFAULT_SCRAPE_IMPERSONATE) -> str:
    value = os.environ.get("SCRAPE_IMPERSONATE", default).strip()
    return value or default


def get_host(default: str = DEFAULT_HOST) -> str:
    value = os.environ.get("HOST", default).strip()
    return value or default


def get_port(default: int = DEFAULT_PORT) -> int:
    raw = os.environ.get("PORT")
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
