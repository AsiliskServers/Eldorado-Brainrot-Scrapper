from __future__ import annotations

from eldorado_tracker.scraper import (
    convert_to_mps,
    extract_bucket_bounds,
    extract_exact_speed_from_title,
    normalize_results,
)


def test_extract_exact_speed_from_title_mps() -> None:
    raw, value, unit = extract_exact_speed_from_title("67 | Secret | 7.5 M/s")
    assert raw == "7.5 M/s"
    assert value == 7.5
    assert unit == "M/s"


def test_extract_exact_speed_from_title_bps() -> None:
    raw, value, unit = extract_exact_speed_from_title("Offer 2 B/s")
    assert raw == "2 B/s"
    assert value == 2.0
    assert unit == "B/s"
    assert convert_to_mps(value, unit) == 2000.0


def test_extract_bucket_bounds_mps_range() -> None:
    minimum, maximum, unit = extract_bucket_bounds("250-499 M/s")
    assert minimum == 250.0
    assert maximum == 499.0
    assert unit == "M/s"


def test_normalize_results_builds_offer_url_and_speed() -> None:
    payload = {
        "pageIndex": 1,
        "totalPages": 1,
        "recordCount": 1,
        "results": [
            {
                "offer": {
                    "id": "offer-123",
                    "gameSeoAlias": "steal-a-brainrot-brainrots",
                    "offerTitle": "Admin Lucky Block 7.5 M/s",
                    "tradeEnvironmentValues": [
                        {"name": "Rarity", "value": "Admin"},
                        {"name": "Brainrot", "value": "Admin Lucky Block"},
                    ],
                    "offerAttributeIdValues": [{"name": "Speed M/s", "value": "0-24 M/s"}],
                    "pricePerUnit": {"amount": 1.25, "currency": "EUR"},
                    "pricePerUnitInUSD": {"amount": 1.35},
                    "quantity": 7,
                },
                "user": {
                    "id": "seller-1",
                    "username": "Vendor",
                    "isVerifiedSeller": True,
                },
                "userOrderInfo": {
                    "positiveCount": 10,
                    "negativeCount": 1,
                    "feedbackScore": 90.9,
                },
            }
        ],
    }

    rows = normalize_results(
        payload=payload,
        listing_url="https://www.eldorado.gg/fr/steal-a-brainrot-brainrots/i/259",
        fetched_at_utc="2026-03-09T12:53:03+00:00",
        game_id="259",
        category="CustomItem",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["offer_url"] == "https://www.eldorado.gg/fr/steal-a-brainrot-brainrots/oi/offer-123"
    assert row["speed_bucket_min"] == 0.0
    assert row["speed_bucket_max"] == 24.0
    assert row["speed_exact_value"] == 7.5
    assert row["speed_exact_mps"] == 7.5
