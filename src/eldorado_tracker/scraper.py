from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse

from scrapling.fetchers import FetcherSession

from .config import ListingTarget, build_flexible_offers_params, parse_listing_target


API_BASE_URL = "https://www.eldorado.gg/api/flexibleOffers"


@dataclass
class ScrapeResult:
    fetched_at_utc: str
    listing_target: ListingTarget
    params: dict[str, Any]
    raw_payload: dict[str, Any]
    normalized_rows: list[dict[str, Any]]


class EldoradoPriceScraper:
    def __init__(self, impersonate: str = "chrome", timeout: int = 30) -> None:
        self.impersonate = impersonate
        self.timeout = timeout

    def scrape_listing(self, listing_url: str, overrides: dict[str, Any] | None = None) -> ScrapeResult:
        target = parse_listing_target(listing_url)
        params = build_flexible_offers_params(target, overrides)
        fetched_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        with FetcherSession(impersonate=self.impersonate, timeout=self.timeout) as session:
            response = session.get(API_BASE_URL, params=params, stealthy_headers=True)
            payload = response.json()

        normalized_rows = normalize_results(
            payload=payload,
            listing_url=listing_url,
            fetched_at_utc=fetched_at_utc,
            game_id=str(params.get("gameId", target.game_id)),
            category=str(params.get("category", target.category)),
        )

        return ScrapeResult(
            fetched_at_utc=fetched_at_utc,
            listing_target=target,
            params=params,
            raw_payload=payload,
            normalized_rows=normalized_rows,
        )

    def scrape_all_pages(
        self,
        listing_url: str,
        overrides: dict[str, Any] | None = None,
        progress_callback: Any | None = None,
        max_pages: int | None = None,
    ) -> ScrapeResult:
        target = parse_listing_target(listing_url)
        base_params = build_flexible_offers_params(target, overrides)
        base_params["pageIndex"] = "1"
        fetched_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        pages_scraped = 0
        pages_limit = max_pages if isinstance(max_pages, int) and max_pages > 0 else None

        all_rows: list[dict[str, Any]] = []
        record_count: int | None = None
        total_pages_raw: int | None = None
        total_pages_effective: int | None = None

        with FetcherSession(impersonate=self.impersonate, timeout=self.timeout) as session:
            first_payload = self._fetch_payload(session, base_params)
            total_pages_raw = int(first_payload.get("totalPages") or 1)
            total_pages_effective = min(total_pages_raw, pages_limit) if pages_limit else total_pages_raw
            record_count = int(first_payload.get("recordCount") or 0)

            first_rows = normalize_results(
                payload=first_payload,
                listing_url=listing_url,
                fetched_at_utc=fetched_at_utc,
                game_id=str(base_params.get("gameId", target.game_id)),
                category=str(base_params.get("category", target.category)),
            )
            all_rows.extend(first_rows)
            pages_scraped = 1
            self._notify_progress(
                progress_callback,
                current_page=1,
                total_pages=total_pages_effective,
                rows_collected=len(all_rows),
                record_count=record_count,
            )

            for page_index in range(2, total_pages_effective + 1):
                params = dict(base_params)
                params["pageIndex"] = str(page_index)
                payload = self._fetch_payload(session, params)
                rows = normalize_results(
                    payload=payload,
                    listing_url=listing_url,
                    fetched_at_utc=fetched_at_utc,
                    game_id=str(base_params.get("gameId", target.game_id)),
                    category=str(base_params.get("category", target.category)),
                )
                all_rows.extend(rows)
                pages_scraped = page_index
                self._notify_progress(
                    progress_callback,
                    current_page=page_index,
                    total_pages=total_pages_effective,
                    rows_collected=len(all_rows),
                    record_count=record_count,
                )

        summary_payload = {
            "pageIndex": 1,
            "totalPages": total_pages_effective or 1,
            "totalPagesRaw": total_pages_raw or 1,
            "recordCount": record_count or len(all_rows),
            "pageSize": base_params.get("pageSize"),
            "pagesScraped": pages_scraped,
            "mode": "all_pages",
        }

        return ScrapeResult(
            fetched_at_utc=fetched_at_utc,
            listing_target=target,
            params=base_params,
            raw_payload=summary_payload,
            normalized_rows=all_rows,
        )

    def scrape_selected_pages(
        self,
        listing_url: str,
        page_indexes: list[int],
        overrides: dict[str, Any] | None = None,
        fetched_at_utc: str | None = None,
        progress_callback: Any | None = None,
    ) -> ScrapeResult:
        target = parse_listing_target(listing_url)
        base_params = build_flexible_offers_params(target, overrides)
        selected_pages = sorted({int(page) for page in page_indexes if int(page) > 0})
        fetched_at = fetched_at_utc or datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        if not selected_pages:
            return ScrapeResult(
                fetched_at_utc=fetched_at,
                listing_target=target,
                params=base_params,
                raw_payload={
                    "mode": "selected_pages",
                    "pagesRequested": [],
                    "pagesScraped": 0,
                    "recordCount": 0,
                    "totalPagesRaw": 0,
                },
                normalized_rows=[],
            )

        all_rows: list[dict[str, Any]] = []
        record_count: int | None = None
        total_pages_raw: int | None = None

        with FetcherSession(impersonate=self.impersonate, timeout=self.timeout) as session:
            for done, page_index in enumerate(selected_pages, start=1):
                params = dict(base_params)
                params["pageIndex"] = str(page_index)
                payload = self._fetch_payload(session, params)

                if record_count is None:
                    record_count = int(payload.get("recordCount") or 0)
                if total_pages_raw is None:
                    total_pages_raw = int(payload.get("totalPages") or 1)

                rows = normalize_results(
                    payload=payload,
                    listing_url=listing_url,
                    fetched_at_utc=fetched_at,
                    game_id=str(base_params.get("gameId", target.game_id)),
                    category=str(base_params.get("category", target.category)),
                )
                all_rows.extend(rows)

                if progress_callback is not None:
                    progress_callback(
                        {
                            "page_index": page_index,
                            "pages_done": done,
                            "pages_total": len(selected_pages),
                            "rows_collected": len(all_rows),
                            "record_count": record_count,
                        }
                    )

        summary_payload = {
            "mode": "selected_pages",
            "pageIndex": selected_pages[0],
            "pagesRequested": selected_pages,
            "pagesScraped": len(selected_pages),
            "recordCount": record_count or len(all_rows),
            "totalPagesRaw": total_pages_raw or len(selected_pages),
            "totalPages": total_pages_raw or len(selected_pages),
        }

        return ScrapeResult(
            fetched_at_utc=fetched_at,
            listing_target=target,
            params=base_params,
            raw_payload=summary_payload,
            normalized_rows=all_rows,
        )

    def _fetch_payload(self, session: FetcherSession, params: dict[str, Any]) -> dict[str, Any]:
        response = session.get(API_BASE_URL, params=params, stealthy_headers=True)
        return response.json()

    @staticmethod
    def _notify_progress(
        callback: Any | None,
        current_page: int,
        total_pages: int,
        rows_collected: int,
        record_count: int | None,
    ) -> None:
        if callback is None:
            return
        callback(
            {
                "current_page": current_page,
                "total_pages": total_pages,
                "rows_collected": rows_collected,
                "record_count": record_count,
                "progress_percent": round((current_page / max(total_pages, 1)) * 100, 2),
            }
        )


def normalize_results(
    payload: dict[str, Any],
    listing_url: str,
    fetched_at_utc: str,
    game_id: str,
    category: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    locale, seo_alias = extract_listing_parts(listing_url)
    for result in payload.get("results", []):
        offer = result.get("offer", {}) or {}
        user = result.get("user", {}) or {}
        user_order_info = result.get("userOrderInfo", {}) or {}
        trade_values = offer.get("tradeEnvironmentValues", []) or []
        speed_info = extract_speed_info(offer)
        offer_id = offer.get("id")
        offer_url = build_offer_url(locale, offer.get("gameSeoAlias") or seo_alias, offer_id)

        rows.append(
            {
                "fetched_at_utc": fetched_at_utc,
                "source_listing_url": listing_url,
                "game_id": game_id,
                "category": category,
                "page_index": payload.get("pageIndex"),
                "total_pages": payload.get("totalPages"),
                "record_count": payload.get("recordCount"),
                "offer_id": offer.get("id"),
                "offer_url": offer_url,
                "offer_title": offer.get("offerTitle"),
                "item_type": get_trade_value(trade_values, "Item type"),
                "rarity": get_trade_value(trade_values, "Rarity"),
                "item_name": get_trade_value(trade_values, "Brainrot"),
                "speed_bucket_raw": speed_info.get("bucket_raw"),
                "speed_bucket_unit": speed_info.get("bucket_unit"),
                "speed_bucket_min": speed_info.get("bucket_min"),
                "speed_bucket_max": speed_info.get("bucket_max"),
                "speed_bucket_min_mps": speed_info.get("bucket_min_mps"),
                "speed_bucket_max_mps": speed_info.get("bucket_max_mps"),
                "speed_exact_raw": speed_info.get("exact_raw"),
                "speed_exact_unit": speed_info.get("exact_unit"),
                "speed_exact_value": speed_info.get("exact_value"),
                "speed_exact_mps": speed_info.get("exact_mps"),
                "price_amount": nested_get(offer, "pricePerUnit", "amount"),
                "price_currency": nested_get(offer, "pricePerUnit", "currency"),
                "price_amount_usd": nested_get(offer, "pricePerUnitInUSD", "amount"),
                "quantity": offer.get("quantity"),
                "delivery_time_median": nested_get(result, "deliveryTime", "deliveryTimeMedian"),
                "delivery_time_expected": nested_get(result, "deliveryTime", "expectedTime"),
                "seller_id": user.get("id"),
                "seller_username": user.get("username"),
                "seller_verified": user.get("isVerifiedSeller"),
                "positive_count": user_order_info.get("positiveCount"),
                "negative_count": user_order_info.get("negativeCount"),
                "feedback_score": user_order_info.get("feedbackScore"),
            }
        )

    return rows


def nested_get(source: dict[str, Any], *keys: str) -> Any:
    current: Any = source
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def get_trade_value(trade_values: list[dict[str, Any]], name: str) -> str | None:
    for entry in trade_values:
        if entry.get("name") == name:
            value = entry.get("value")
            return str(value) if value is not None else None
    return None


def extract_speed_info(offer: dict[str, Any]) -> dict[str, Any]:
    attrs = offer.get("offerAttributeIdValues", []) or []
    bucket_raw = None
    bucket_unit_hint = None
    for attr in attrs:
        name = str(attr.get("name") or "")
        if "/s" in name:
            value = attr.get("value")
            bucket_raw = str(value) if value is not None else None
            bucket_unit_hint = normalize_speed_unit(name)
            break

    exact_raw, exact_value, exact_unit = extract_exact_speed_from_title(str(offer.get("offerTitle") or ""))
    bucket_min, bucket_max, bucket_unit = extract_bucket_bounds(bucket_raw, bucket_unit_hint)

    return {
        "bucket_raw": bucket_raw,
        "bucket_unit": bucket_unit,
        "bucket_min": bucket_min,
        "bucket_max": bucket_max,
        "bucket_min_mps": convert_to_mps(bucket_min, bucket_unit),
        "bucket_max_mps": convert_to_mps(bucket_max, bucket_unit),
        "exact_raw": exact_raw,
        "exact_unit": exact_unit,
        "exact_value": exact_value,
        "exact_mps": convert_to_mps(exact_value, exact_unit),
    }


def extract_exact_speed_from_title(title: str) -> tuple[str | None, float | None, str | None]:
    normalized = title.replace(",", ".")

    direct_match = re.search(r"(?i)(\d+(?:\.\d+)?)\s*([mb])\s*/\s*s", normalized)
    if direct_match:
        value = safe_float(direct_match.group(1))
        unit = "B/s" if direct_match.group(2).upper() == "B" else "M/s"
        return direct_match.group(0), value, unit

    compact_match = re.search(r"(?i)(\d+)\s*B\s*(\d+)\s*M(?:\s*PER\s*SECOND)?", normalized)
    if compact_match:
        b_part = safe_float(compact_match.group(1))
        m_part = safe_float(compact_match.group(2))
        if b_part is not None and m_part is not None:
            value_b = b_part + (m_part / 1000)
            return compact_match.group(0), value_b, "B/s"

    return None, None, None


def extract_bucket_bounds(
    bucket_raw: str | None, unit_hint: str | None = None
) -> tuple[float | None, float | None, str | None]:
    if not bucket_raw:
        return None, None, None
    normalized = bucket_raw.replace(",", ".")

    range_match = re.search(r"(?i)(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*([mb])\s*/\s*s", normalized)
    if range_match:
        min_value = safe_float(range_match.group(1))
        max_value = safe_float(range_match.group(2))
        unit = "B/s" if range_match.group(3).upper() == "B" else "M/s"
        return min_value, max_value, unit

    plus_match = re.search(r"(?i)(\d+(?:\.\d+)?)\+\s*([mb])\s*/\s*s", normalized)
    if plus_match:
        min_value = safe_float(plus_match.group(1))
        unit = "B/s" if plus_match.group(2).upper() == "B" else "M/s"
        return min_value, None, unit

    plain_number = safe_float(normalized)
    if plain_number is not None and unit_hint in {"M/s", "B/s"}:
        return plain_number, plain_number, unit_hint

    return None, None, None


def convert_to_mps(value: float | None, unit: str | None) -> float | None:
    if value is None or unit is None:
        return None
    if unit == "M/s":
        return value
    if unit == "B/s":
        return value * 1000
    return None


def safe_float(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_speed_unit(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower()
    if "b/s" in lowered:
        return "B/s"
    if "m/s" in lowered:
        return "M/s"
    return None


def extract_listing_parts(listing_url: str) -> tuple[str, str]:
    parsed = urlparse(listing_url)
    parts = [part for part in parsed.path.split("/") if part]
    locale = parts[0] if len(parts) >= 1 else "fr"
    seo_alias = parts[1] if len(parts) >= 2 else ""
    return locale, seo_alias


def build_offer_url(locale: str, seo_alias: str, offer_id: str | None) -> str | None:
    if not offer_id or not seo_alias:
        return None
    return f"https://www.eldorado.gg/{locale}/{seo_alias}/oi/{offer_id}"
