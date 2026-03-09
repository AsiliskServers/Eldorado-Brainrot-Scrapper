from __future__ import annotations

import csv
import json

from eldorado_tracker.config import parse_listing_target
from eldorado_tracker.scraper import ScrapeResult
from eldorado_tracker.storage import clear_persisted_results, persist_result


def build_result() -> ScrapeResult:
    target = parse_listing_target("https://www.eldorado.gg/fr/steal-a-brainrot-brainrots/i/259")
    rows = [
        {
            "fetched_at_utc": "2026-03-09T12:53:03+00:00",
            "offer_id": "offer-1",
            "offer_title": "Title 1",
            "price_amount": 1.0,
        },
        {
            "fetched_at_utc": "2026-03-09T12:53:03+00:00",
            "offer_id": "offer-2",
            "offer_title": "Title 2",
            "price_amount": 2.0,
        },
    ]
    return ScrapeResult(
        fetched_at_utc="2026-03-09T12:53:03+00:00",
        listing_target=target,
        params={"gameId": "259", "category": "CustomItem"},
        raw_payload={"pageIndex": 1, "totalPages": 1, "recordCount": 2},
        normalized_rows=rows,
    )


def test_persist_result_writes_json_and_csv(tmp_path) -> None:
    result = build_result()

    output = persist_result(result, tmp_path)

    raw_content = json.loads(output["raw_snapshot"].read_text(encoding="utf-8"))
    latest_content = json.loads(output["latest_json"].read_text(encoding="utf-8"))
    with output["history_csv"].open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert raw_content["meta"]["params"]["gameId"] == "259"
    assert len(latest_content) == 2
    assert len(rows) == 2


def test_persist_result_appends_csv_and_clear_removes(tmp_path) -> None:
    result = build_result()

    first = persist_result(result, tmp_path)
    second = persist_result(result, tmp_path)

    with second["history_csv"].open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4

    summary = clear_persisted_results(tmp_path)
    assert summary["raw_files_removed"] == 1
    assert summary["normalized_files_removed"] == 2
    assert not first["latest_json"].exists()
    assert not first["history_csv"].exists()
