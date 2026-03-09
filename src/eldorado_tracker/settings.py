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
DEFAULT_NODE_ROLE = "main"
DEFAULT_MAIN_HOST = "192.168.1.170"
DEFAULT_MAIN_PORT = 8787
DEFAULT_SATELLITE_HOST = "0.0.0.0"
DEFAULT_SATELLITE_PORT = 30080
DEFAULT_SATELLITE_BASE_URL = "http://82.67.180.129:30080"
DEFAULT_SATELLITE_TIMEOUT = 900


def get_listing_url(default: str = DEFAULT_LISTING_URL) -> str:
    return os.environ.get("LISTING_URL", default)


def get_node_role(default: str = DEFAULT_NODE_ROLE) -> str:
    value = os.environ.get("NODE_ROLE", default).strip().lower()
    if value in {"main", "satellite"}:
        return value
    return default


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


def get_host(default: str | None = None) -> str:
    if default is None:
        default = DEFAULT_SATELLITE_HOST if get_node_role() == "satellite" else DEFAULT_MAIN_HOST
    value = os.environ.get("HOST", default).strip()
    return value or default


def get_port(default: int | None = None) -> int:
    if default is None:
        default = DEFAULT_SATELLITE_PORT if get_node_role() == "satellite" else DEFAULT_MAIN_PORT
    raw = os.environ.get("PORT")
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def get_satellite_base_url(default: str = DEFAULT_SATELLITE_BASE_URL) -> str:
    value = os.environ.get("SATELLITE_BASE_URL", default).strip()
    return value.rstrip("/") if value else default


def get_satellite_enabled(default: bool = True) -> bool:
    value = os.environ.get("SATELLITE_ENABLED")
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def get_satellite_timeout(default: int = DEFAULT_SATELLITE_TIMEOUT) -> int:
    raw = os.environ.get("SATELLITE_TIMEOUT")
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
