from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .scraper import ScrapeResult


def persist_result(result: ScrapeResult, output_dir: Path) -> dict[str, Path]:
    raw_dir = output_dir / "raw"
    normalized_dir = output_dir / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    stamp = result.fetched_at_utc.replace(":", "-").replace("+00:00", "Z")
    raw_path = raw_dir / f"flexible_offers_{stamp}.json"
    latest_path = normalized_dir / "latest_offers.json"
    history_csv_path = normalized_dir / "offers_history.csv"

    raw_payload_with_meta = {
        "meta": {
            "fetched_at_utc": result.fetched_at_utc,
            "source_listing_url": result.listing_target.listing_url,
            "api_url": "https://www.eldorado.gg/api/flexibleOffers",
            "params": result.params,
        },
        "payload": result.raw_payload,
    }
    raw_path.write_text(
        json.dumps(raw_payload_with_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    latest_path.write_text(
        json.dumps(result.normalized_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    append_rows_to_csv(history_csv_path, result.normalized_rows)
    return {"raw_snapshot": raw_path, "latest_json": latest_path, "history_csv": history_csv_path}


def append_rows_to_csv(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    file_exists = csv_path.exists()
    if file_exists:
        with csv_path.open("r", newline="", encoding="utf-8") as existing:
            reader = csv.reader(existing)
            header = next(reader, None)
        fieldnames = header if header else list(rows[0].keys())
    else:
        fieldnames = list(rows[0].keys())

    with csv_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def clear_persisted_results(output_dir: Path) -> dict[str, int]:
    raw_dir = output_dir / "raw"
    normalized_dir = output_dir / "normalized"

    removed_raw = 0
    removed_normalized = 0

    if raw_dir.exists():
        for path in raw_dir.glob("*.json"):
            path.unlink(missing_ok=True)
            removed_raw += 1

    if normalized_dir.exists():
        for filename in ("latest_offers.json", "offers_history.csv"):
            path = normalized_dir / filename
            if path.exists():
                path.unlink()
                removed_normalized += 1

    return {"raw_files_removed": removed_raw, "normalized_files_removed": removed_normalized}
