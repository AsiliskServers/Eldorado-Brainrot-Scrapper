from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse


LISTING_KIND_TO_CATEGORY = {
    "i": "CustomItem",
    "g": "Currency",
    "a": "Account",
    "b": "Boosting",
    "t": "TopUp",
    "v": "GiftCard",
}


@dataclass(frozen=True)
class ListingTarget:
    listing_url: str
    locale: str
    seo_alias: str
    listing_kind: str
    game_id: str
    category: str
    query: dict[str, str]


def parse_listing_target(listing_url: str) -> ListingTarget:
    parsed = urlparse(listing_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4:
        raise ValueError(
            "Listing URL format is not supported. Expected '/<locale>/<seo-alias>/<kind>/<id>'."
        )

    locale, seo_alias, listing_kind, game_id = parts[:4]
    category = LISTING_KIND_TO_CATEGORY.get(listing_kind)
    if category is None:
        raise ValueError(
            f"Listing kind '{listing_kind}' is not supported. Supported values: {sorted(LISTING_KIND_TO_CATEGORY)}"
        )

    raw_query = parse_qs(parsed.query, keep_blank_values=False)
    query: dict[str, str] = {key: values[-1] for key, values in raw_query.items() if values}

    return ListingTarget(
        listing_url=listing_url,
        locale=locale,
        seo_alias=seo_alias,
        listing_kind=listing_kind,
        game_id=game_id,
        category=category,
        query=query,
    )


def build_flexible_offers_params(
    target: ListingTarget, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    query = target.query
    params: dict[str, Any] = {
        "gameId": target.game_id,
        "category": target.category,
        "pageIndex": query.get("gamePageOfferIndex", "1"),
        "pageSize": query.get("gamePageOfferSize", "20"),
    }

    maybe_copy(query, params, "searchQuery")
    maybe_copy(query, params, "deliveryTime")
    maybe_copy(query, params, "lowestPrice")
    maybe_copy(query, params, "highestPrice")
    maybe_copy(query, params, "offerSortingCriterion")
    maybe_copy(query, params, "te_v0", target_key="tradeEnvironmentValue0")
    maybe_copy(query, params, "te_v1", target_key="tradeEnvironmentValue1")
    maybe_copy(query, params, "te_v2", target_key="tradeEnvironmentValue2")
    maybe_copy(query, params, "attr_ids", target_key="offerAttributeIdsCsv")

    if "isAscending" in query:
        params["isAscending"] = str(query["isAscending"]).lower()

    if overrides:
        for key, value in overrides.items():
            if value is None:
                params.pop(key, None)
                continue
            params[key] = value

    return params


def maybe_copy(source: dict[str, Any], target: dict[str, Any], key: str, target_key: str | None = None) -> None:
    if key in source and source[key] not in ("", None):
        target[target_key or key] = source[key]
