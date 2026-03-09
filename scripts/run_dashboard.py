from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Any
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
    get_port,
    get_scrape_impersonate,
    get_scrape_timeout,
)
from eldorado_tracker.storage import clear_persisted_results, persist_result  # noqa: E402


DEFAULT_LISTING_URL = get_listing_url()
SCRAPE_IMPERSONATE = get_scrape_impersonate()
SCRAPE_TIMEOUT = get_scrape_timeout()
DATA_DIR = get_data_dir(PROJECT_ROOT)
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
LATEST_JSON_PATH = DATA_DIR / "normalized" / "latest_offers.json"
HISTORY_CSV_PATH = DATA_DIR / "normalized" / "offers_history.csv"
SCRAPE_STATE_LOCK = Lock()


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


def get_scrape_state() -> dict[str, Any]:
    with SCRAPE_STATE_LOCK:
        return dict(SCRAPE_STATE)


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

    try:
        if all_pages:
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
                    "error": str(exc),
                }
            )


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "EldoradoDashboard/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self.serve_file("index.html", "text/html; charset=utf-8")
        if parsed.path == "/styles.css":
            return self.serve_file("styles.css", "text/css; charset=utf-8")
        if parsed.path == "/app.js":
            return self.serve_file("app.js", "application/javascript; charset=utf-8")
        if parsed.path == "/api/healthz":
            return self.send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "timestamp_utc": utc_iso(),
                    "scrape_running": bool(get_scrape_state().get("running")),
                },
            )
        if parsed.path == "/api/latest":
            payload = build_latest_payload()
            payload["scrape_state"] = get_scrape_state()
            return self.send_json(HTTPStatus.OK, payload)
        if parsed.path == "/api/history":
            query = parse_qs(parsed.query)
            limit = parse_int(query.get("limit", ["200"])[0], 200)
            rows = read_history_rows(limit=max(1, min(limit, 5000)))
            return self.send_json(HTTPStatus.OK, {"limit": limit, "row_count": len(rows), "rows": rows})
        if parsed.path == "/api/scrape-status":
            return self.send_json(HTTPStatus.OK, get_scrape_state())

        return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/clear-results":
            return self.clear_results()
        if parsed.path != "/api/scrape":
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


def run_server(host: str = get_host(), port: int = get_port()) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard running at http://{host}:{port}")
    server.serve_forever()


def parse_server_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Eldorado dashboard API + frontend server.")
    parser.add_argument("--host", default=get_host())
    parser.add_argument("--port", type=int, default=get_port())
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_server_args()
    run_server(host=args.host, port=args.port)
