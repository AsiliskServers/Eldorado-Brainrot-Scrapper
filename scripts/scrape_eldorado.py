from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from eldorado_tracker.scraper import EldoradoPriceScraper  # noqa: E402
from eldorado_tracker.settings import (  # noqa: E402
    get_data_dir,
    get_listing_url,
    get_scrape_impersonate,
    get_scrape_timeout,
)
from eldorado_tracker.storage import persist_result  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Eldorado offers and persist snapshots for price tracking."
    )
    parser.add_argument("--listing-url", default=get_listing_url(), help="Eldorado listing URL")
    parser.add_argument(
        "--output-dir",
        default=str(get_data_dir(PROJECT_ROOT)),
        help="Output directory for raw snapshots and normalized files",
    )
    parser.add_argument(
        "--impersonate",
        default=get_scrape_impersonate(),
        help="Browser fingerprint for Scrapling",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=get_scrape_timeout(),
        help="HTTP timeout in seconds",
    )

    parser.add_argument("--page-index", type=int, help="Override pageIndex")
    parser.add_argument("--page-size", type=int, help="Override pageSize")
    parser.add_argument("--lowest-price", type=float, help="Override lowestPrice")
    parser.add_argument("--highest-price", type=float, help="Override highestPrice")
    parser.add_argument("--sort", choices=["Price", "Recommended"], help="Override offerSortingCriterion")
    parser.add_argument("--ascending", choices=["true", "false"], help="Override isAscending")
    return parser.parse_args()


def build_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.page_index is not None:
        overrides["pageIndex"] = str(args.page_index)
    if args.page_size is not None:
        overrides["pageSize"] = str(args.page_size)
    if args.lowest_price is not None:
        overrides["lowestPrice"] = str(args.lowest_price)
    if args.highest_price is not None:
        overrides["highestPrice"] = str(args.highest_price)
    if args.sort is not None:
        overrides["offerSortingCriterion"] = args.sort
    if args.ascending is not None:
        overrides["isAscending"] = args.ascending
    return overrides


def main() -> int:
    args = parse_args()
    overrides = build_overrides(args)
    scraper = EldoradoPriceScraper(impersonate=args.impersonate, timeout=args.timeout)
    result = scraper.scrape_listing(args.listing_url, overrides=overrides or None)

    output_paths = persist_result(result, Path(args.output_dir))
    print(
        json.dumps(
            {
                "fetched_at_utc": result.fetched_at_utc,
                "offers_in_page": len(result.normalized_rows),
                "record_count": result.raw_payload.get("recordCount"),
                "page_index": result.raw_payload.get("pageIndex"),
                "total_pages": result.raw_payload.get("totalPages"),
                "output_files": {key: str(value) for key, value in output_paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
