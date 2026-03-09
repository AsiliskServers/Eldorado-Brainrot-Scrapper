from __future__ import annotations

import pytest

from eldorado_tracker.config import build_flexible_offers_params, parse_listing_target


def test_parse_listing_target_valid_url() -> None:
    target = parse_listing_target(
        "https://www.eldorado.gg/fr/steal-a-brainrot-brainrots/i/259?"
        "lowestPrice=0&highestPrice=50&gamePageOfferIndex=2&gamePageOfferSize=80"
    )

    assert target.locale == "fr"
    assert target.seo_alias == "steal-a-brainrot-brainrots"
    assert target.listing_kind == "i"
    assert target.game_id == "259"
    assert target.category == "CustomItem"
    assert target.query["lowestPrice"] == "0"
    assert target.query["gamePageOfferSize"] == "80"


def test_parse_listing_target_invalid_kind() -> None:
    with pytest.raises(ValueError):
        parse_listing_target("https://www.eldorado.gg/fr/alias/x/259")


def test_build_flexible_offers_params_with_overrides() -> None:
    target = parse_listing_target(
        "https://www.eldorado.gg/fr/steal-a-brainrot-brainrots/i/259?"
        "lowestPrice=0&highestPrice=50&isAscending=true&offerSortingCriterion=Price&"
        "gamePageOfferIndex=1&gamePageOfferSize=50"
    )

    params = build_flexible_offers_params(
        target,
        overrides={
            "pageIndex": "3",
            "pageSize": "100",
            "lowestPrice": None,
        },
    )

    assert params["gameId"] == "259"
    assert params["category"] == "CustomItem"
    assert params["pageIndex"] == "3"
    assert params["pageSize"] == "100"
    assert params["isAscending"] == "true"
    assert "lowestPrice" not in params
    assert params["highestPrice"] == "50"
