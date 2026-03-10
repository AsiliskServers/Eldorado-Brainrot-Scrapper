from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from eldorado_tracker.scraper import EldoradoPriceScraper  # noqa: E402
from eldorado_tracker.settings import (  # noqa: E402
    get_data_dir,
    get_host,
    get_listing_url,
    get_node_role,
    get_port,
    get_satellite_base_url,
    get_satellite_enabled,
    get_satellite_timeout,
    get_scrape_impersonate,
    get_scrape_timeout,
)
from eldorado_tracker.storage import clear_persisted_results, persist_result  # noqa: E402


DEFAULT_LISTING_URL = get_listing_url()
SCRAPE_IMPERSONATE = get_scrape_impersonate()
SCRAPE_TIMEOUT = get_scrape_timeout()
NODE_ROLE = get_node_role()
SATELLITE_BASE_URL = get_satellite_base_url()
SATELLITE_ENABLED = get_satellite_enabled()
SATELLITE_TIMEOUT = get_satellite_timeout()
DATA_DIR = get_data_dir(PROJECT_ROOT)
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
LATEST_JSON_PATH = DATA_DIR / "normalized" / "latest_offers.json"
HISTORY_CSV_PATH = DATA_DIR / "normalized" / "offers_history.csv"
SCRAPE_STATE_LOCK = Lock()
SATELLITE_STATUS_LOCK = Lock()
SATELLITE_STATUS_CACHE: dict[str, Any] = {"checked_at_monotonic": 0.0, "value": None}


def build_idle_scrape_state(clear_summary: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "running": False,
        "job_id": None,
        "mode": None,
        "progress_percent": 0.0,
        "current_page": 0,
        "total_pages": 0,
        "rows_collected": 0,
        "record_count": None,
        "started_at_utc": None,
        "finished_at_utc": None,
        "error": None,
        "last_result": None,
        "clear_summary": clear_summary,
        "satellite_assigned_pages": 0,
        "satellite_completed_pages": 0,
        "satellite_working": False,
        "satellite_error": None,
    }


SCRAPE_STATE: dict[str, Any] = build_idle_scrape_state()


def load_latest_rows() -> list[dict[str, Any]]:
    if not LATEST_JSON_PATH.exists():
        return []
    return json.loads(LATEST_JSON_PATH.read_text(encoding="utf-8"))


def utc_iso(timestamp: float | None = None) -> str:
    if timestamp is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat()


def build_latest_payload() -> dict[str, Any]:
    rows = load_latest_rows()
    updated_at = utc_iso(LATEST_JSON_PATH.stat().st_mtime) if LATEST_JSON_PATH.exists() else None
    prices = [row.get("price_amount") for row in rows if isinstance(row.get("price_amount"), (int, float))]

    return {
        "updated_at_utc": updated_at,
        "row_count": len(rows),
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "rows": rows,
    }


def read_history_rows(limit: int = 200) -> list[dict[str, Any]]:
    if not HISTORY_CSV_PATH.exists():
        return []
    with HISTORY_CSV_PATH.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
    if limit <= 0:
        return rows
    return rows[-limit:]


def build_satellite_runtime_status(force_refresh: bool = False) -> dict[str, Any]:
    if not is_main_node():
        return {
            "enabled": False,
            "configured_url": None,
            "ok": None,
            "working": None,
            "error": None,
            "checked_at_utc": utc_iso(),
        }
    if not SATELLITE_ENABLED:
        return {
            "enabled": False,
            "configured_url": SATELLITE_BASE_URL,
            "ok": False,
            "working": False,
            "error": "disabled",
            "checked_at_utc": utc_iso(),
        }

    now = time.monotonic()
    with SATELLITE_STATUS_LOCK:
        cached = SATELLITE_STATUS_CACHE.get("value")
        checked_at = float(SATELLITE_STATUS_CACHE.get("checked_at_monotonic") or 0.0)
        if not force_refresh and cached and (now - checked_at) < 3:
            return dict(cached)

    url = f"{SATELLITE_BASE_URL}/api/healthz"
    req = urlrequest.Request(url=url, method="GET")
    result: dict[str, Any]
    try:
        with urlrequest.urlopen(req, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = {
            "enabled": True,
            "configured_url": SATELLITE_BASE_URL,
            "ok": bool(payload.get("status") == "ok"),
            "working": bool(payload.get("scrape_running")),
            "error": None,
            "checked_at_utc": utc_iso(),
        }
    except Exception as exc:
        result = {
            "enabled": True,
            "configured_url": SATELLITE_BASE_URL,
            "ok": False,
            "working": False,
            "error": str(exc),
            "checked_at_utc": utc_iso(),
        }

    with SATELLITE_STATUS_LOCK:
        SATELLITE_STATUS_CACHE["checked_at_monotonic"] = now
        SATELLITE_STATUS_CACHE["value"] = dict(result)
    return result


def get_scrape_state(force_satellite_refresh: bool = False) -> dict[str, Any]:
    with SCRAPE_STATE_LOCK:
        state = dict(SCRAPE_STATE)
    state["satellite_runtime"] = build_satellite_runtime_status(force_refresh=force_satellite_refresh)
    return state


def is_main_node() -> bool:
    return NODE_ROLE == "main"


def split_pages_between_nodes(page_indexes: list[int]) -> tuple[list[int], list[int]]:
    satellite_pages = page_indexes[::2]
    local_pages = page_indexes[1::2]
    return local_pages, satellite_pages


def request_satellite_pages(
    listing_url: str,
    overrides: dict[str, Any] | None,
    page_indexes: list[int],
    all_prices: bool,
) -> list[dict[str, Any]]:
    if not page_indexes:
        return []

    payload = {
        "listing_url": listing_url,
        "overrides": overrides or {},
        "page_indexes": page_indexes,
        "all_prices": all_prices,
    }
    url = f"{SATELLITE_BASE_URL}/api/satellite/scrape-pages"
    req = urlrequest.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=SATELLITE_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Satellite HTTP error {exc.code}: {detail}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"Satellite request failed: {exc}") from exc

    if not isinstance(body, dict) or body.get("status") != "ok":
        raise RuntimeError(f"Satellite invalid response: {body}")
    rows = body.get("normalized_rows")
    if not isinstance(rows, list):
        raise RuntimeError("Satellite response missing normalized_rows")
    return rows


def scrape_all_pages_distributed(
    scraper: EldoradoPriceScraper,
    listing_url: str,
    overrides: dict[str, Any] | None,
    max_pages: int | None,
    all_prices: bool,
    progress_callback: Any | None = None,
) -> tuple[Any, dict[str, Any]]:
    first_overrides = dict(overrides or {})
    first_overrides["pageIndex"] = "1"
    first_result = scraper.scrape_listing(listing_url=listing_url, overrides=first_overrides)

    total_pages_raw = int(first_result.raw_payload.get("totalPages") or 1)
    total_pages_effective = min(total_pages_raw, max_pages) if max_pages else total_pages_raw
    record_count = int(first_result.raw_payload.get("recordCount") or len(first_result.normalized_rows))
    all_rows = list(first_result.normalized_rows)

    completed_pages = 1
    local_rows_collected = 0
    satellite_rows_collected = 0
    satellite_assigned_pages = 0
    satellite_completed_pages = 0
    satellite_working = False
    satellite_error: str | None = None

    def emit_progress() -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "current_page": completed_pages,
                "total_pages": total_pages_effective,
                "rows_collected": len(first_result.normalized_rows)
                + local_rows_collected
                + satellite_rows_collected,
                "record_count": record_count,
                "progress_percent": round((completed_pages / max(total_pages_effective, 1)) * 100, 2),
                "satellite_assigned_pages": satellite_assigned_pages,
                "satellite_completed_pages": satellite_completed_pages,
                "satellite_working": satellite_working,
                "satellite_error": satellite_error,
            }
        )

    emit_progress()
    if total_pages_effective <= 1:
        summary = {
            "mode": "distributed",
            "distributed": False,
            "pageIndex": 1,
            "totalPages": total_pages_effective,
            "totalPagesRaw": total_pages_raw,
            "recordCount": record_count,
            "pagesScraped": 1,
            "satellitePages": [],
            "localPages": [1],
            "satelliteError": None,
        }
        first_result.raw_payload = summary
        return first_result, summary

    remaining_pages = list(range(2, total_pages_effective + 1))
    local_pages, satellite_pages = split_pages_between_nodes(remaining_pages)
    satellite_assigned_pages = len(satellite_pages)
    satellite_working = satellite_assigned_pages > 0
    emit_progress()

    def on_local_progress(progress: dict[str, Any]) -> None:
        nonlocal completed_pages, local_rows_collected
        local_rows_collected = int(progress.get("rows_collected", 0))
        completed_pages = 1 + int(progress.get("pages_done", 0))
        emit_progress()

    with ThreadPoolExecutor(max_workers=2) as pool:
        local_future = pool.submit(
            scraper.scrape_selected_pages,
            listing_url,
            local_pages,
            overrides,
            first_result.fetched_at_utc,
            on_local_progress,
        )
        satellite_future = pool.submit(
            request_satellite_pages,
            listing_url,
            overrides,
            satellite_pages,
            all_prices,
        )

        local_result = local_future.result()
        all_rows.extend(local_result.normalized_rows)

        try:
            satellite_rows = satellite_future.result()
            satellite_rows_collected = len(satellite_rows)
            satellite_completed_pages = len(satellite_pages)
            satellite_working = False
            all_rows.extend(satellite_rows)
            completed_pages = 1 + len(local_pages) + len(satellite_pages)
            emit_progress()
        except Exception as exc:
            satellite_error = str(exc)
            fallback_result = scraper.scrape_selected_pages(
                listing_url=listing_url,
                page_indexes=satellite_pages,
                overrides=overrides,
                fetched_at_utc=first_result.fetched_at_utc,
            )
            satellite_rows_collected = len(fallback_result.normalized_rows)
            satellite_completed_pages = len(satellite_pages)
            satellite_working = False
            all_rows.extend(fallback_result.normalized_rows)
            completed_pages = 1 + len(local_pages) + len(satellite_pages)
            emit_progress()

    summary = {
        "mode": "distributed",
        "distributed": True,
        "pageIndex": 1,
        "totalPages": total_pages_effective,
        "totalPagesRaw": total_pages_raw,
        "recordCount": record_count,
        "pagesScraped": 1 + len(local_pages) + len(satellite_pages),
        "satellitePages": satellite_pages,
        "localPages": [1, *local_pages],
        "satelliteError": satellite_error,
    }

    first_result.raw_payload = summary
    first_result.normalized_rows = all_rows
    first_result.params["pageIndex"] = "1"
    return first_result, summary


def start_scrape_job(
    listing_url: str,
    overrides: dict[str, Any] | None,
    all_pages: bool,
    max_pages: int | None,
    all_prices: bool,
) -> tuple[bool, dict[str, Any]]:
    with SCRAPE_STATE_LOCK:
        if SCRAPE_STATE["running"]:
            return False, dict(SCRAPE_STATE)

        clear_summary = clear_persisted_results(DATA_DIR)
        job_id = utc_iso()
        SCRAPE_STATE.update(
            {
                "running": True,
                "job_id": job_id,
                "mode": "all_pages" if all_pages else "single_page",
                "progress_percent": 0.0,
                "current_page": 0,
                "total_pages": 0,
                "rows_collected": 0,
                "record_count": None,
                "started_at_utc": job_id,
                "finished_at_utc": None,
                "error": None,
                "last_result": None,
                "clear_summary": clear_summary,
                "satellite_assigned_pages": 0,
                "satellite_completed_pages": 0,
                "satellite_working": False,
                "satellite_error": None,
            }
        )

    worker = Thread(
        target=run_scrape_job,
        kwargs={
            "job_id": job_id,
            "listing_url": listing_url,
            "overrides": overrides,
            "all_pages": all_pages,
            "max_pages": max_pages,
            "all_prices": all_prices,
        },
        daemon=True,
    )
    worker.start()
    return True, get_scrape_state()


def run_scrape_job(
    job_id: str,
    listing_url: str,
    overrides: dict[str, Any] | None,
    all_pages: bool,
    max_pages: int | None,
    all_prices: bool,
) -> None:
    scraper = EldoradoPriceScraper(impersonate=SCRAPE_IMPERSONATE, timeout=SCRAPE_TIMEOUT)
    effective_overrides = dict(overrides or {})
    if all_prices:
        effective_overrides["lowestPrice"] = None
        effective_overrides["highestPrice"] = None

    def on_progress(progress: dict[str, Any]) -> None:
        with SCRAPE_STATE_LOCK:
            if SCRAPE_STATE.get("job_id") != job_id:
                return
            SCRAPE_STATE["current_page"] = int(progress.get("current_page", 0))
            SCRAPE_STATE["total_pages"] = int(progress.get("total_pages", 0))
            SCRAPE_STATE["rows_collected"] = int(progress.get("rows_collected", 0))
            SCRAPE_STATE["record_count"] = progress.get("record_count")
            SCRAPE_STATE["progress_percent"] = float(progress.get("progress_percent", 0.0))
            if "satellite_assigned_pages" in progress:
                SCRAPE_STATE["satellite_assigned_pages"] = int(progress.get("satellite_assigned_pages", 0))
            if "satellite_completed_pages" in progress:
                SCRAPE_STATE["satellite_completed_pages"] = int(progress.get("satellite_completed_pages", 0))
            if "satellite_working" in progress:
                SCRAPE_STATE["satellite_working"] = bool(progress.get("satellite_working"))
            if "satellite_error" in progress:
                SCRAPE_STATE["satellite_error"] = progress.get("satellite_error")

    try:
        if all_pages:
            if is_main_node() and SATELLITE_ENABLED:
                result, distributed_summary = scrape_all_pages_distributed(
                    scraper=scraper,
                    listing_url=listing_url,
                    overrides=effective_overrides,
                    max_pages=max_pages,
                    all_prices=all_prices,
                    progress_callback=on_progress,
                )
                if distributed_summary.get("satelliteError"):
                    print(f"[dashboard] satellite fallback triggered: {distributed_summary['satelliteError']}")
            else:
                result = scraper.scrape_all_pages(
                    listing_url=listing_url,
                    overrides=effective_overrides,
                    progress_callback=on_progress,
                    max_pages=max_pages,
                )
        else:
            result = scraper.scrape_listing(listing_url=listing_url, overrides=effective_overrides)
            on_progress(
                {
                    "current_page": 1,
                    "total_pages": 1,
                    "rows_collected": len(result.normalized_rows),
                    "record_count": result.raw_payload.get("recordCount"),
                    "progress_percent": 100.0,
                }
            )

        output_paths = persist_result(result, DATA_DIR)
        latest_payload = build_latest_payload()

        with SCRAPE_STATE_LOCK:
            if SCRAPE_STATE.get("job_id") != job_id:
                return
            SCRAPE_STATE.update(
                {
                    **build_idle_scrape_state(clear_summary=SCRAPE_STATE.get("clear_summary")),
                    "job_id": job_id,
                    "mode": "all_pages" if all_pages else "single_page",
                    "started_at_utc": SCRAPE_STATE.get("started_at_utc"),
                    "finished_at_utc": utc_iso(),
                    "progress_percent": 100.0,
                    "current_page": SCRAPE_STATE.get("current_page"),
                    "total_pages": SCRAPE_STATE.get("total_pages"),
                    "rows_collected": SCRAPE_STATE.get("rows_collected"),
                    "record_count": SCRAPE_STATE.get("record_count"),
                    "satellite_assigned_pages": SCRAPE_STATE.get("satellite_assigned_pages", 0),
                    "satellite_completed_pages": SCRAPE_STATE.get("satellite_completed_pages", 0),
                    "satellite_working": False,
                    "satellite_error": SCRAPE_STATE.get("satellite_error"),
                    "last_result": {
                        "fetched_at_utc": result.fetched_at_utc,
                        "record_count": result.raw_payload.get("recordCount"),
                        "offers_collected": len(result.normalized_rows),
                        "output_files": {key: str(value) for key, value in output_paths.items()},
                        "latest_updated_at_utc": latest_payload.get("updated_at_utc"),
                    },
                }
            )
    except Exception as exc:  # pragma: no cover
        with SCRAPE_STATE_LOCK:
            if SCRAPE_STATE.get("job_id") != job_id:
                return
            SCRAPE_STATE.update(
                {
                    **build_idle_scrape_state(clear_summary=SCRAPE_STATE.get("clear_summary")),
                    "job_id": job_id,
                    "mode": "all_pages" if all_pages else "single_page",
                    "started_at_utc": SCRAPE_STATE.get("started_at_utc"),
                    "finished_at_utc": utc_iso(),
                    "current_page": SCRAPE_STATE.get("current_page"),
                    "total_pages": SCRAPE_STATE.get("total_pages"),
                    "rows_collected": SCRAPE_STATE.get("rows_collected"),
                    "record_count": SCRAPE_STATE.get("record_count"),
                    "satellite_assigned_pages": SCRAPE_STATE.get("satellite_assigned_pages", 0),
                    "satellite_completed_pages": SCRAPE_STATE.get("satellite_completed_pages", 0),
                    "satellite_working": False,
                    "satellite_error": SCRAPE_STATE.get("satellite_error"),
                    "error": str(exc),
                }
            )


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "EldoradoDashboard/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path_matches(path, "/favicon.ico"):
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        if NODE_ROLE == "satellite" and (
            is_index_like_path(path) or path_matches(path, "/styles.css") or path_matches(path, "/app.js")
        ):
            return self.send_json(
                HTTPStatus.FORBIDDEN,
                {"error": "Satellite node does not serve dashboard UI"},
            )

        if is_index_like_path(path):
            return self.serve_file("index.html", "text/html; charset=utf-8")
        if path_matches(path, "/styles.css"):
            return self.serve_file("styles.css", "text/css; charset=utf-8")
        if path_matches(path, "/app.js"):
            return self.serve_file("app.js", "application/javascript; charset=utf-8")
        if path_matches(path, "/api/healthz"):
            return self.send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "timestamp_utc": utc_iso(),
                    "scrape_running": bool(get_scrape_state().get("running")),
                    "node_role": NODE_ROLE,
                    "satellite_enabled": bool(SATELLITE_ENABLED),
                    "satellite_base_url": SATELLITE_BASE_URL if is_main_node() else None,
                },
            )
        if path_matches(path, "/api/latest"):
            payload = build_latest_payload()
            payload["scrape_state"] = get_scrape_state(force_satellite_refresh=True)
            return self.send_json(HTTPStatus.OK, payload)
        if path_matches(path, "/api/history"):
            query = parse_qs(parsed.query)
            limit = parse_int(query.get("limit", ["200"])[0], 200)
            rows = read_history_rows(limit=max(1, min(limit, 5000)))
            return self.send_json(HTTPStatus.OK, {"limit": limit, "row_count": len(rows), "rows": rows})
        if path_matches(path, "/api/scrape-status"):
            return self.send_json(HTTPStatus.OK, get_scrape_state(force_satellite_refresh=True))

        return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path_matches(path, "/api/satellite/scrape-pages"):
            return self.satellite_scrape_pages()

        if NODE_ROLE == "satellite":
            return self.send_json(
                HTTPStatus.FORBIDDEN,
                {"error": "Satellite node only accepts '/api/satellite/scrape-pages'"},
            )

        if path_matches(path, "/api/clear-results"):
            return self.clear_results()
        if not path_matches(path, "/api/scrape"):
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        body = self.read_json_body()
        listing_url = str(body.get("listing_url") or DEFAULT_LISTING_URL)
        overrides = body.get("overrides")
        if overrides is not None and not isinstance(overrides, dict):
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "'overrides' must be an object"})

        all_pages = parse_bool(body.get("all_pages"), True)
        all_prices = parse_bool(body.get("all_prices"), True)
        max_pages = parse_int_or_none(body.get("max_pages"))

        started, state = start_scrape_job(
            listing_url=listing_url,
            overrides=overrides,
            all_pages=all_pages,
            max_pages=max_pages,
            all_prices=all_prices,
        )
        if not started:
            return self.send_json(
                HTTPStatus.CONFLICT,
                {
                    "status": "busy",
                    "error": "A scrape is already running",
                    "scrape_state": state,
                },
            )

        return self.send_json(
            HTTPStatus.ACCEPTED,
            {"status": "started", "scrape_state": state},
        )

    def satellite_scrape_pages(self) -> None:
        if NODE_ROLE != "satellite":
            self.send_json(
                HTTPStatus.FORBIDDEN,
                {"error": "This endpoint is only available on satellite node"},
            )
            return

        body = self.read_json_body()
        listing_url = str(body.get("listing_url") or DEFAULT_LISTING_URL)
        overrides = body.get("overrides")
        if overrides is not None and not isinstance(overrides, dict):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "'overrides' must be an object"})
            return

        raw_pages = body.get("page_indexes")
        if not isinstance(raw_pages, list) or not raw_pages:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "'page_indexes' must be a non-empty array"})
            return

        page_indexes: list[int] = []
        for value in raw_pages:
            parsed = parse_int_or_none(value)
            if parsed is None:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "All page indexes must be positive integers"})
                return
            page_indexes.append(parsed)

        all_prices = parse_bool(body.get("all_prices"), True)
        effective_overrides = dict(overrides or {})
        if all_prices:
            effective_overrides["lowestPrice"] = None
            effective_overrides["highestPrice"] = None

        scraper = EldoradoPriceScraper(impersonate=SCRAPE_IMPERSONATE, timeout=SCRAPE_TIMEOUT)
        result = scraper.scrape_selected_pages(
            listing_url=listing_url,
            page_indexes=page_indexes,
            overrides=effective_overrides,
        )
        self.send_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "fetched_at_utc": result.fetched_at_utc,
                "pages_scraped": result.raw_payload.get("pagesScraped"),
                "record_count": result.raw_payload.get("recordCount"),
                "normalized_rows": result.normalized_rows,
            },
        )

    def clear_results(self) -> None:
        with SCRAPE_STATE_LOCK:
            if SCRAPE_STATE.get("running"):
                self.send_json(
                    HTTPStatus.CONFLICT,
                    {
                        "status": "busy",
                        "error": "Cannot clear while scrape is running",
                        "scrape_state": dict(SCRAPE_STATE),
                    },
                )
                return

        summary = clear_persisted_results(DATA_DIR)
        with SCRAPE_STATE_LOCK:
            SCRAPE_STATE.update(build_idle_scrape_state(clear_summary=summary))
            state = dict(SCRAPE_STATE)

        self.send_json(
            HTTPStatus.OK,
            {
                "status": "cleared",
                "clear_summary": summary,
                "latest": build_latest_payload(),
                "scrape_state": state,
            },
        )

    def read_json_body(self) -> dict[str, Any]:
        length = parse_int(self.headers.get("Content-Length", "0"), 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def serve_file(self, relative_path: str, content_type: str) -> None:
        file_path = DASHBOARD_DIR / relative_path
        if not file_path.exists():
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "File not found"})
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        print(f"[dashboard] {self.address_string()} - {format % args}")


def parse_int(value: str | None, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def path_matches(path: str, target: str) -> bool:
    return path == target or path.endswith(target)


def is_index_like_path(path: str) -> bool:
    if path in {"", "/"}:
        return True
    stripped = path.strip("/")
    if not stripped:
        return True
    if "/" in stripped:
        return False
    if "." in stripped:
        return False
    return not stripped.startswith("api")


def run_server(host: str = get_host(), port: int = get_port()) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Node role: {NODE_ROLE}")
    if is_main_node():
        print(f"Dashboard running at http://{host}:{port}")
        print(f"Satellite enabled: {SATELLITE_ENABLED} ({SATELLITE_BASE_URL})")
    else:
        print(f"Satellite API running at http://{host}:{port}/api/satellite/scrape-pages")
    server.serve_forever()


def parse_server_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Eldorado dashboard API + frontend server.")
    parser.add_argument("--host", default=get_host())
    parser.add_argument("--port", type=int, default=get_port())
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_server_args()
    run_server(host=args.host, port=args.port)
