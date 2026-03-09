from __future__ import annotations

import json
from http.server import ThreadingHTTPServer
from threading import Thread
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

    with dashboard.SCRAPE_STATE_LOCK:
        dashboard.SCRAPE_STATE.clear()
        dashboard.SCRAPE_STATE.update(dashboard.build_idle_scrape_state())

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


def test_healthz_returns_200(api_server) -> None:
    status, payload = request_json(f"{api_server}/api/healthz")
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["scrape_running"] is False


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
