from __future__ import annotations

import json
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from urllib import request

import pytest

import run_dashboard as dashboard


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            return response.status, data
    except request.HTTPError as exc:
        data = json.loads(exc.read().decode("utf-8"))
        return exc.code, data


@pytest.fixture
def api_server(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    normalized_dir = data_dir / "normalized"
    raw_dir = data_dir / "raw"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(dashboard, "DATA_DIR", data_dir)
    monkeypatch.setattr(dashboard, "LATEST_JSON_PATH", normalized_dir / "latest_offers.json")
    monkeypatch.setattr(dashboard, "HISTORY_CSV_PATH", normalized_dir / "offers_history.csv")
    monkeypatch.setattr(dashboard, "NODE_ROLE", "main")
    monkeypatch.setattr(dashboard, "SATELLITE_ENABLED", False)

    with dashboard.SCRAPE_STATE_LOCK:
        dashboard.SCRAPE_STATE.clear()
        dashboard.SCRAPE_STATE.update(dashboard.build_idle_scrape_state())
    with dashboard.SATELLITE_TASK_LOCK:
        dashboard.SATELLITE_TASK_STATE.clear()
        dashboard.SATELLITE_TASK_STATE.update(dashboard.build_idle_satellite_task_state())

    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        with dashboard.SCRAPE_STATE_LOCK:
            dashboard.SCRAPE_STATE.clear()
            dashboard.SCRAPE_STATE.update(dashboard.build_idle_scrape_state())
        with dashboard.SATELLITE_TASK_LOCK:
            dashboard.SATELLITE_TASK_STATE.clear()
            dashboard.SATELLITE_TASK_STATE.update(dashboard.build_idle_satellite_task_state())


def test_healthz_returns_200(api_server) -> None:
    status, payload = request_json(f"{api_server}/api/healthz")
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["scrape_running"] is False
    assert payload["node_role"] == "main"


def test_prefixed_healthz_returns_200(api_server) -> None:
    status, payload = request_json(f"{api_server}/scrapper/api/healthz")
    assert status == 200
    assert payload["status"] == "ok"


def test_scrape_start_returns_202(api_server, monkeypatch) -> None:
    expected_state = {"running": True, "job_id": "job-1"}

    def fake_start_scrape_job(**kwargs):
        assert kwargs["all_pages"] is True
        assert kwargs["all_prices"] is True
        return True, expected_state

    monkeypatch.setattr(dashboard, "start_scrape_job", fake_start_scrape_job)

    status, payload = request_json(f"{api_server}/api/scrape", method="POST", payload={})
    assert status == 202
    assert payload["status"] == "started"
    assert payload["scrape_state"] == expected_state


def test_scrape_second_launch_returns_409(api_server, monkeypatch) -> None:
    busy_state = {"running": True, "job_id": "already-running"}
    monkeypatch.setattr(dashboard, "start_scrape_job", lambda **kwargs: (False, busy_state))

    status, payload = request_json(f"{api_server}/api/scrape", method="POST", payload={})
    assert status == 409
    assert payload["status"] == "busy"
    assert payload["scrape_state"] == busy_state


def test_clear_results_rejected_while_running(api_server) -> None:
    with dashboard.SCRAPE_STATE_LOCK:
        dashboard.SCRAPE_STATE.update({"running": True, "job_id": "job-2"})

    status, payload = request_json(f"{api_server}/api/clear-results", method="POST", payload={})
    assert status == 409
    assert payload["status"] == "busy"


def test_split_pages_between_nodes() -> None:
    local_pages, satellite_pages = dashboard.split_pages_between_nodes([2, 3, 4, 5, 6])
    assert local_pages == [5, 6]
    assert satellite_pages == [2, 3, 4]


def test_listing_overview_returns_counts(api_server, monkeypatch) -> None:
    class FakeScraper:
        def __init__(self, impersonate: str, timeout: int) -> None:
            self.impersonate = impersonate
            self.timeout = timeout

        def scrape_listing(self, listing_url, overrides):
            assert listing_url
            assert overrides["pageIndex"] == "1"
            assert overrides["lowestPrice"] is None
            assert overrides["highestPrice"] is None
            return SimpleNamespace(
                fetched_at_utc="2026-03-10T12:00:00+00:00",
                raw_payload={"totalPages": 985, "recordCount": 123456},
                normalized_rows=[{"offer_id": "a"}],
            )

    monkeypatch.setattr(dashboard, "EldoradoPriceScraper", FakeScraper)

    status, payload = request_json(f"{api_server}/api/listing-overview")
    assert status == 200
    assert payload["max_pages"] == 985
    assert payload["announcement_count"] == 123456
    assert payload["all_prices"] is True


def test_satellite_endpoint_rejected_on_main_node(api_server) -> None:
    status, payload = request_json(
        f"{api_server}/api/satellite/scrape-pages",
        method="POST",
        payload={"page_indexes": [2, 4]},
    )
    assert status == 403
    assert "only available on satellite" in payload["error"]


def test_satellite_endpoint_scrapes_pages(api_server, monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "NODE_ROLE", "satellite")

    class FakeScraper:
        def __init__(self, impersonate: str, timeout: int) -> None:
            self.impersonate = impersonate
            self.timeout = timeout

        def scrape_selected_pages(self, listing_url, page_indexes, overrides, progress_callback=None):
            assert listing_url
            assert page_indexes == [2, 4]
            assert overrides["lowestPrice"] is None
            if progress_callback:
                progress_callback({"pages_done": 1})
                progress_callback({"pages_done": 2})
            return SimpleNamespace(
                fetched_at_utc="2026-03-09T12:53:03+00:00",
                raw_payload={"pagesScraped": 2, "recordCount": 100},
                normalized_rows=[{"offer_id": "a"}, {"offer_id": "b"}],
            )

    monkeypatch.setattr(dashboard, "EldoradoPriceScraper", FakeScraper)

    status, payload = request_json(
        f"{api_server}/api/satellite/scrape-pages",
        method="POST",
        payload={
            "listing_url": "https://www.eldorado.gg/fr/steal-a-brainrot-brainrots/i/259",
            "page_indexes": [2, 4],
            "all_prices": True,
            "overrides": {"highestPrice": "20"},
        },
    )
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["pages_scraped"] == 2
    assert len(payload["normalized_rows"]) == 2

    status_health, payload_health = request_json(f"{api_server}/api/healthz")
    assert status_health == 200
    assert payload_health["node_role"] == "satellite"
    assert payload_health["satellite_task"]["pages_total"] == 2
    assert payload_health["satellite_task"]["pages_done"] == 2


def test_prefixed_static_file_served(api_server) -> None:
    req = request.Request(f"{api_server}/scrapper/styles.css", method="GET")
    with request.urlopen(req, timeout=5) as response:
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert ":root" in body
