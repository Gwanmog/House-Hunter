#!/usr/bin/env python3
"""Investment property recommender.

Loads active home listings from CSV or API, estimates monthly rental economics,
and outputs only homes with positive cashflow.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


STATE_PROPERTY_TAX_RATES = {
    "AL": 0.0040,
    "AK": 0.0119,
    "AZ": 0.0063,
    "AR": 0.0064,
    "CA": 0.0075,
    "CO": 0.0049,
    "CT": 0.0185,
    "DE": 0.0055,
    "FL": 0.0090,
    "GA": 0.0092,
    "HI": 0.0031,
    "ID": 0.0067,
    "IL": 0.0215,
    "IN": 0.0085,
    "IA": 0.0157,
    "KS": 0.0141,
    "KY": 0.0083,
    "LA": 0.0051,
    "ME": 0.0119,
    "MD": 0.0106,
    "MA": 0.0117,
    "MI": 0.0154,
    "MN": 0.0110,
    "MS": 0.0081,
    "MO": 0.0099,
    "MT": 0.0083,
    "NE": 0.0161,
    "NV": 0.0060,
    "NH": 0.0186,
    "NJ": 0.0223,
    "NM": 0.0067,
    "NY": 0.0172,
    "NC": 0.0081,
    "ND": 0.0100,
    "OH": 0.0156,
    "OK": 0.0090,
    "OR": 0.0100,
    "PA": 0.0149,
    "RI": 0.0137,
    "SC": 0.0056,
    "SD": 0.0122,
    "TN": 0.0064,
    "TX": 0.0180,
    "UT": 0.0056,
    "VT": 0.0178,
    "VA": 0.0082,
    "WA": 0.0092,
    "WV": 0.0059,
    "WI": 0.0176,
    "WY": 0.0058,
}

STATE_INSURANCE_FACTORS = {
    "CA": 1.15,
    "FL": 1.35,
    "TX": 1.25,
    "LA": 1.3,
    "CO": 1.15,
    "OK": 1.2,
    "NY": 1.1,
}


@dataclass
class Listing:
    listing_id: str
    address: str
    city: str
    state: str
    zip_code: str
    price: float
    sqft: float
    bedrooms: float
    bathrooms: float
    year_built: int
    lot_size_sqft: float
    hoa_monthly: float
    property_type: str = "unknown"
    listing_url: str = ""


@dataclass
class Analysis:
    listing: Listing
    score: float
    estimated_rent: float
    rent_estimation_method: str
    comp_count: int
    monthly_mortgage_pi: float
    monthly_taxes: float
    monthly_insurance: float
    monthly_maintenance: float
    monthly_management: float
    monthly_vacancy: float
    monthly_hoa: float
    monthly_total_costs: float
    monthly_net_cashflow: float
    annual_cash_on_cash_return: float
    down_payment: float
    down_payment_pct: float
    monthly_pmi: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recommend investment houses with positive cashflow.")
    parser.add_argument("--source", choices=["csv", "rapidapi-realtor"], default="csv")
    parser.add_argument("--listings-csv", help="CSV file with active home listings (required for --source csv).")
    parser.add_argument("--location", required=True, help="State abbreviation (e.g. TX) or ZIP code.")
    parser.add_argument("--max-price", type=float, required=True, help="Maximum purchase price.")
    parser.add_argument("--max-down-payment", type=float, required=True, help="Maximum available down payment.")
    parser.add_argument("--interest-rate", type=float, default=6.75, help="Annual mortgage rate percentage.")
    parser.add_argument("--loan-years", type=int, default=30, help="Mortgage term in years.")

    parser.add_argument("--target-sqft", type=float, default=1800)
    parser.add_argument("--target-bedrooms", type=float, default=3)
    parser.add_argument("--target-bathrooms", type=float, default=2)
    parser.add_argument("--target-year-built", type=float, default=1995)
    parser.add_argument("--target-lot-size", type=float, default=7000)

    parser.add_argument("--weight-sqft", type=float, default=3)
    parser.add_argument("--weight-bedrooms", type=float, default=2)
    parser.add_argument("--weight-bathrooms", type=float, default=2)
    parser.add_argument("--weight-year-built", type=float, default=1.5)
    parser.add_argument("--weight-lot-size", type=float, default=1)

    parser.add_argument("--insurance-rate", type=float, default=0.0035, help="Annual insurance as pct of price.")
    parser.add_argument("--maintenance-rate", type=float, default=0.08, help="Monthly maintenance as pct of rent.")
    parser.add_argument("--management-rate", type=float, default=0.10, help="Monthly management fee as pct of rent.")
    parser.add_argument("--vacancy-rate", type=float, default=0.05, help="Monthly vacancy reserve as pct of rent.")
    parser.add_argument("--pmi-rate", type=float, default=0.008, help="Annual PMI rate applied when down payment is below 20%.")
    parser.add_argument("--landlord-insurance-multiplier", type=float, default=1.15, help="Multiplier to adjust homeowners insurance toward landlord policy estimates.")
    parser.add_argument("--results", type=int, default=10, help="Max recommendations returned.")

    parser.add_argument("--rapidapi-key", help="RapidAPI key (CLI override).")
    parser.add_argument("--config-file", default=".house_hunter.env", help="Optional KEY=VALUE config file (default: .house_hunter.env).")
    parser.add_argument("--rapidapi-host", default="realtor-search.p.rapidapi.com")
    parser.add_argument("--rapidapi-endpoint", default="/properties/v3/list", help="API path for homes-for-sale search.")
    parser.add_argument("--rapidapi-limit", type=int, default=42, help="Max for-sale API listings to fetch.")
    parser.add_argument("--rapidapi-method", choices=["GET", "POST"], default="GET", help="HTTP method for for-sale endpoint.")
    parser.add_argument("--rapidapi-location-param", default="zip", help="Location parameter key (e.g. zip, postal_code).")

    parser.add_argument("--rent-source", choices=["heuristic", "csv", "rapidapi-realtor", "hybrid"], default="hybrid")
    parser.add_argument("--rental-comps-csv", help="CSV of local rental comps (used when --rent-source csv|hybrid).")
    parser.add_argument("--rapidapi-rent-endpoint", default="/properties/v3/list-for-rent", help="API path for rental comps.")
    parser.add_argument("--rapidapi-rent-limit", type=int, default=40, help="Max rental comps to fetch by ZIP.")
    parser.add_argument("--rapidapi-rent-method", choices=["GET", "POST"], default="GET", help="HTTP method for rental comp endpoint.")
    parser.add_argument("--rapidapi-rent-location-param", default="zip", help="Rental comp location parameter key.")
    parser.add_argument("--min-rent-comps", type=int, default=3, help="Minimum comps required before using comp-based rent.")
    parser.add_argument("--property-types", default="", help="Comma-separated property types to include (e.g. condo,single_family).")
    parser.add_argument("--min-bedrooms", type=float, default=0, help="Minimum bedrooms filter.")
    parser.add_argument("--min-bathrooms", type=float, default=0, help="Minimum bathrooms filter.")

    args = parser.parse_args()
    if args.source == "csv" and not args.listings_csv:
        parser.error("--listings-csv is required when --source csv")
    if args.rent_source == "csv" and not args.rental_comps_csv:
        parser.error("--rental-comps-csv is required when --rent-source csv")
    return args


def load_config_file(path: str) -> Dict[str, str]:
    file_path = Path(path)
    if not file_path.exists():
        return {}

    config: Dict[str, str] = {}
    for raw in file_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip().strip('"').strip("'")
    return config


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def pick_first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def matches_location(listing: Listing, location: str) -> bool:
    location_type, city, state, zip_code = parse_location(location)
    if location_type == "state":
        return listing.state == state
    if location_type == "city":
        city_match = listing.city.strip().upper() == city
        if state:
            return city_match and listing.state == state
        return city_match
    return listing.zip_code == zip_code


def parse_location(location: str) -> tuple[str, str, str, str]:
    normalized = location.strip().upper()
    if re.fullmatch(r"\d{5}", normalized):
        return "zip", "", "", normalized
    if len(normalized) == 2 and normalized.isalpha():
        return "state", "", normalized, ""

    city = normalized
    state = ""
    if "," in normalized:
        city, state = [part.strip() for part in normalized.split(",", 1)]
        state = state[:2]
    return "city", city, state, ""


def similarity_weight(subject: Listing, comp: Listing) -> float:
    score = 0.0
    score += bounded_similarity(comp.bedrooms, subject.bedrooms, 2.0) * 2.0
    score += bounded_similarity(comp.bathrooms, subject.bathrooms, 2.0) * 2.0
    score += bounded_similarity(comp.sqft, subject.sqft if subject.sqft > 0 else 1500, max(subject.sqft * 0.5, 500)) * 3.0
    score += bounded_similarity(comp.year_built, subject.year_built, 40.0) * 1.0
    score += bounded_similarity(comp.lot_size_sqft, subject.lot_size_sqft if subject.lot_size_sqft > 0 else 6000, max(subject.lot_size_sqft, 2000)) * 0.5
    return max(score, 0.0)


def weighted_median(values_with_weights: List[tuple[float, float]]) -> float:
    if not values_with_weights:
        return 0.0
    total = sum(w for _, w in values_with_weights)
    if total <= 0:
        return sum(v for v, _ in values_with_weights) / len(values_with_weights)
    ordered = sorted(values_with_weights, key=lambda x: x[0])
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= total / 2:
            return value
    return ordered[-1][0]


def load_listings_from_csv(csv_path: Path) -> List[Listing]:
    listings: List[Listing] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            listings.append(
                Listing(
                    listing_id=str(row.get("listing_id", "")),
                    address=str(row.get("address", "Unknown Address")),
                    city=str(row.get("city", "Unknown City")),
                    state=str(row.get("state", "NA")).upper(),
                    zip_code=str(row.get("zip_code", "00000")),
                    price=safe_float(row.get("price")),
                    sqft=safe_float(row.get("sqft")),
                    bedrooms=safe_float(row.get("bedrooms")),
                    bathrooms=safe_float(row.get("bathrooms")),
                    year_built=safe_int(row.get("year_built"), 1980),
                    lot_size_sqft=safe_float(row.get("lot_size_sqft")),
                    hoa_monthly=safe_float(row.get("hoa_monthly"), 0),
                    property_type=str(row.get("property_type") or row.get("prop_type") or "unknown"),
                    listing_url=str(row.get("listing_url") or row.get("url") or ""),
                )
            )
    return listings


def extract_hoa_monthly(item: Dict[str, Any], description: Dict[str, Any]) -> float:
    """Best-effort extraction of HOA monthly amount from variant API fields."""
    candidates = [
        item.get("hoa_fee"),
        item.get("hoa"),
        item.get("monthly_hoa_fee"),
        item.get("hoa_monthly"),
        description.get("hoa_fee"),
        description.get("hoa"),
        description.get("monthly_hoa_fee"),
        description.get("hoa_monthly"),
        item.get("hoa_fee_per_month"),
        description.get("hoa_fee_per_month"),
    ]

    for value in candidates:
        amount = safe_float(value, 0)
        if amount > 0:
            return amount

    # Some providers send HOA in nested structures and/or annual totals.
    nested_hoa = pick_first(
        item.get("hoa"),
        description.get("hoa"),
        item.get("association"),
        description.get("association"),
        default={},
    )
    if isinstance(nested_hoa, dict):
        periodic = safe_float(
            pick_first(
                nested_hoa.get("monthly_fee"),
                nested_hoa.get("fee_monthly"),
                nested_hoa.get("hoa_fee"),
                nested_hoa.get("fee"),
                default=0,
            ),
            0,
        )
        if periodic > 0:
            return periodic

        annual = safe_float(
            pick_first(
                nested_hoa.get("annual_fee"),
                nested_hoa.get("yearly_fee"),
                nested_hoa.get("fee_annual"),
                default=0,
            ),
            0,
        )
        if annual > 0:
            return annual / 12

    text_blob = " ".join(
        [
            str(item.get("remarks") or ""),
            str(description.get("text") or ""),
            str(description.get("description") or ""),
        ]
    )
    match = re.search(r"hoa[^$\d]{0,24}\$?([\d,]{2,7})(?:\s*/\s*(mo|month|yr|year))?", text_blob, re.IGNORECASE)
    if match:
        amount = safe_float(match.group(1).replace(",", ""), 0)
        cadence = (match.group(2) or "mo").lower()
        if amount > 0:
            return amount / 12 if cadence in {"yr", "year"} else amount

    return 0.0


def listing_from_realtor(item: Dict[str, Any]) -> Optional[Listing]:
    location = item.get("location", {})
    address = location.get("address", {})
    description = item.get("description", {})

    list_price = pick_first(item.get("list_price"), description.get("price"), item.get("price"), default=0)
    if safe_float(list_price) <= 0:
        return None

    line = pick_first(address.get("line"), address.get("street_name"), item.get("address"), default="Unknown Address")
    city = pick_first(address.get("city"), item.get("city"), default="Unknown City")
    state = str(pick_first(address.get("state_code"), address.get("state"), item.get("state"), default="NA")).upper()
    zip_code = str(pick_first(address.get("postal_code"), item.get("postal_code"), item.get("zip_code"), default="00000"))

    return Listing(
        listing_id=str(pick_first(item.get("property_id"), item.get("listing_id"), default=f"{line}-{zip_code}")),
        address=str(line),
        city=str(city),
        state=state,
        zip_code=zip_code,
        price=safe_float(list_price),
        sqft=safe_float(pick_first(description.get("sqft"), item.get("sqft"), default=0)),
        bedrooms=safe_float(pick_first(description.get("beds"), item.get("beds"), default=0)),
        bathrooms=safe_float(pick_first(description.get("baths"), item.get("baths"), default=0)),
        year_built=safe_int(pick_first(description.get("year_built"), item.get("year_built"), default=1980), 1980),
        lot_size_sqft=safe_float(pick_first(description.get("lot_sqft"), item.get("lot_sqft"), default=0)),
        hoa_monthly=extract_hoa_monthly(item, description),
        property_type=str(pick_first(description.get("type"), description.get("property_type"), item.get("prop_type"), default="unknown")),
        listing_url=str(pick_first(item.get("href"), item.get("permalink"), item.get("rdc_web_url"), default="")),
    )


def _build_api_request(
    host: str,
    endpoint: str,
    location_param: str,
    location_value: str,
    limit: int,
    key: str,
    method: str = "GET",
    purpose: str = "sale",
    extra_filters: Optional[Dict[str, Any]] = None,
) -> urllib.request.Request:
    normalized_endpoint = endpoint.strip()
    if not normalized_endpoint.startswith("/"):
        normalized_endpoint = f"/{normalized_endpoint}"

    method = method.upper()
    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": host,
        "X-API-Host": host,
        "Accept": "application/json",
    }

    if method == "POST":
        status = ["for_rent"] if purpose == "rent" else ["for_sale", "ready_to_build"]
        payload = {
            "limit": limit,
            "offset": 0,
            location_param: location_value,
            "status": status,
            "sort": {"direction": "desc", "field": "list_date"},
        }
        if extra_filters:
            payload.update(extra_filters)
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        url = f"https://{host}{normalized_endpoint}"
        return urllib.request.Request(url, headers=headers, method="POST", data=body)

    query_params: Dict[str, Any] = {location_param: location_value, "offset": 0, "limit": limit, "sort": "relevance"}
    if extra_filters:
        query_params.update(extra_filters)
    query = urllib.parse.urlencode(query_params)
    url = f"https://{host}{normalized_endpoint}?{query}"
    return urllib.request.Request(url, headers=headers, method="GET")


def _read_api_payload(req: urllib.request.Request) -> Dict[str, Any]:
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_results(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = (
        payload.get("data", {}).get("home_search", {}).get("results")
        or payload.get("data", {}).get("results")
        or payload.get("properties")
        or payload.get("results")
        or []
    )
    return [c for c in candidates if isinstance(c, dict)]


def get_rapidapi_key(args: argparse.Namespace) -> str:
    config = load_config_file(args.config_file)
    key = args.rapidapi_key or os.environ.get("RAPIDAPI_KEY") or config.get("RAPIDAPI_KEY")
    if not key:
        raise ValueError(
            "RapidAPI key is required. Use --rapidapi-key, RAPIDAPI_KEY env var, or set RAPIDAPI_KEY in config file."
        )
    return key


def build_sale_api_filters(args: argparse.Namespace) -> Dict[str, Any]:
    # Keep API responses aligned with underwriting constraints to reduce noise.
    filters: Dict[str, Any] = {
        "list_price": {"max": args.max_price},
        "beds": {"min": max(args.min_bedrooms, int(args.target_bedrooms) - 1)},
        "baths": {"min": max(args.min_bathrooms, int(args.target_bathrooms) - 1)},
        "sqft": {"min": max(500, int(args.target_sqft * 0.6))},
    }
    property_types = [p.strip() for p in str(args.property_types).split(",") if p.strip()]
    if property_types:
        filters["prop_type"] = property_types
    return filters


def load_listings_from_rapidapi_realtor(args: argparse.Namespace) -> List[Listing]:
    key = get_rapidapi_key(args)

    location_type, city, state, zip_code = parse_location(args.location)
    location_param = args.rapidapi_location_param
    location_value = args.location
    filters = build_sale_api_filters(args)
    if location_type == "city":
        location_param = "city"
        location_value = city.title()
        if state:
            filters["state_code"] = state
    elif location_type == "state":
        location_param = "state_code"
        location_value = state
    elif location_type == "zip":
        location_value = zip_code

    req = _build_api_request(
        host=args.rapidapi_host,
        endpoint=args.rapidapi_endpoint,
        location_param=location_param,
        location_value=location_value,
        limit=args.rapidapi_limit,
        key=key,
        method=args.rapidapi_method,
        purpose="sale",
        extra_filters=filters,
    )
    try:
        payload = _read_api_payload(req)
    except Exception as exc:
        raise RuntimeError(
            "RapidAPI for-sale request failed. Verify host/endpoint, subscription status, API key, and network access."
        ) from exc

    listings = [listing_from_realtor(item) for item in _extract_results(payload)]
    return [l for l in listings if l is not None]


def load_listings(args: argparse.Namespace) -> List[Listing]:
    if args.source == "csv":
        return load_listings_from_csv(Path(args.listings_csv))
    if args.source == "rapidapi-realtor":
        return load_listings_from_rapidapi_realtor(args)
    raise ValueError(f"Unsupported source: {args.source}")


def bounded_similarity(actual: float, target: float, tolerance: float) -> float:
    if tolerance <= 0:
        return 0
    distance = abs(actual - target)
    return max(0.0, 1.0 - (distance / tolerance))


def score_listing(listing: Listing, args: argparse.Namespace) -> float:
    components = [
        bounded_similarity(listing.sqft, args.target_sqft, max(args.target_sqft, 1)),
        bounded_similarity(listing.bedrooms, args.target_bedrooms, 3),
        bounded_similarity(listing.bathrooms, args.target_bathrooms, 3),
        bounded_similarity(listing.year_built, args.target_year_built, 80),
        bounded_similarity(listing.lot_size_sqft, args.target_lot_size, max(args.target_lot_size, 1)),
    ]
    weights = [
        args.weight_sqft,
        args.weight_bedrooms,
        args.weight_bathrooms,
        args.weight_year_built,
        args.weight_lot_size,
    ]
    weighted_sum = sum(c * w for c, w in zip(components, weights))
    max_score = sum(weights)
    return (weighted_sum / max_score) * 100 if max_score else 0


def estimate_rent_heuristic(listing: Listing) -> float:
    state_multiplier = {
        "CA": 1.45,
        "NY": 1.4,
        "WA": 1.25,
        "MA": 1.3,
        "TX": 1.0,
        "FL": 1.05,
        "GA": 0.95,
        "OH": 0.85,
        "PA": 0.9,
    }.get(listing.state, 1.0)

    sqft = listing.sqft if listing.sqft > 0 else 1200
    base_per_sqft = 1.2 * state_multiplier
    bedroom_boost = listing.bedrooms * 85
    bathroom_boost = listing.bathrooms * 60
    year_adjust = max(-120, min(180, (listing.year_built - 1980) * 2.0))

    rent = (sqft * base_per_sqft) + bedroom_boost + bathroom_boost + year_adjust
    return max(900, rent)


def _rent_from_comps(subject: Listing, comps: List[Listing], min_count: int) -> tuple[Optional[float], int]:
    same_zip = [c for c in comps if c.zip_code == subject.zip_code and c.price > 0]
    if not same_zip:
        return None, 0

    values_with_weights: List[tuple[float, float]] = []
    for comp in same_zip:
        weight = similarity_weight(subject, comp)
        if weight <= 0:
            continue
        values_with_weights.append((comp.price, weight))

    if len(values_with_weights) < min_count:
        return None, len(values_with_weights)

    return weighted_median(values_with_weights), len(values_with_weights)


def _load_rental_comps_csv(path: Path) -> List[Listing]:
    comps: List[Listing] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            comps.append(
                Listing(
                    listing_id=str(row.get("comp_id") or row.get("listing_id") or "rent-comp"),
                    address=str(row.get("address", "Rental Comp")),
                    city=str(row.get("city", "Unknown City")),
                    state=str(row.get("state", "NA")).upper(),
                    zip_code=str(row.get("zip_code", "00000")),
                    price=safe_float(row.get("monthly_rent") or row.get("rent") or row.get("price")),
                    sqft=safe_float(row.get("sqft")),
                    bedrooms=safe_float(row.get("bedrooms")),
                    bathrooms=safe_float(row.get("bathrooms")),
                    year_built=safe_int(row.get("year_built"), 1980),
                    lot_size_sqft=safe_float(row.get("lot_size_sqft")),
                    hoa_monthly=0.0,
                    property_type=str(row.get("property_type") or "rental"),
                    listing_url=str(row.get("listing_url") or row.get("url") or ""),
                )
            )
    return comps


class RentEstimator:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.csv_comps: List[Listing] = []
        self.api_comp_cache: Dict[str, List[Listing]] = {}
        self.api_failed = False

        if args.rent_source in {"csv", "hybrid"} and args.rental_comps_csv:
            self.csv_comps = _load_rental_comps_csv(Path(args.rental_comps_csv))

    def _load_rental_comps_api(self, zip_code: str) -> List[Listing]:
        if zip_code in self.api_comp_cache:
            return self.api_comp_cache[zip_code]

        key = get_rapidapi_key(self.args)
        req = _build_api_request(
            host=self.args.rapidapi_host,
            endpoint=self.args.rapidapi_rent_endpoint,
            location_param=self.args.rapidapi_rent_location_param,
            location_value=zip_code,
            limit=self.args.rapidapi_rent_limit,
            key=key,
            method=self.args.rapidapi_rent_method,
            purpose="rent",
            extra_filters=None,
        )
        payload = _read_api_payload(req)
        comps = [listing_from_realtor(item) for item in _extract_results(payload)]
        rentals = [c for c in comps if c is not None]
        self.api_comp_cache[zip_code] = rentals
        return rentals

    def estimate(self, listing: Listing) -> tuple[float, str, int]:
        if self.args.rent_source == "heuristic":
            return estimate_rent_heuristic(listing), "heuristic", 0

        if self.args.rent_source in {"csv", "hybrid"} and self.csv_comps:
            comp_rent, count = _rent_from_comps(listing, self.csv_comps, self.args.min_rent_comps)
            if comp_rent is not None:
                return max(comp_rent, 500), "csv-comps", count

        if self.args.rent_source in {"rapidapi-realtor", "hybrid"}:
            try:
                api_comps = self._load_rental_comps_api(listing.zip_code)
                comp_rent, count = _rent_from_comps(listing, api_comps, self.args.min_rent_comps)
                if comp_rent is not None:
                    return max(comp_rent, 500), "api-comps", count
            except Exception as exc:
                if not self.api_failed:
                    self.api_failed = True
                    print(
                        f"WARN: Rental comp API unavailable ({exc}); falling back to heuristic rent model.",
                        file=sys.stderr,
                    )

        return estimate_rent_heuristic(listing), "heuristic-fallback", 0


def mortgage_payment(principal: float, annual_rate_pct: float, years: int) -> float:
    if principal <= 0:
        return 0.0
    r = (annual_rate_pct / 100) / 12
    n = years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def analyze_listing(listing: Listing, args: argparse.Namespace, rent_estimator: RentEstimator) -> Analysis:
    down_payment = min(args.max_down_payment, listing.price)
    principal = listing.price - down_payment

    estimated_rent, rent_method, comp_count = rent_estimator.estimate(listing)
    monthly_mortgage_pi = mortgage_payment(principal, args.interest_rate, args.loan_years)

    property_tax_rate = STATE_PROPERTY_TAX_RATES.get(listing.state, 0.011)
    monthly_taxes = listing.price * property_tax_rate / 12
    insurance_factor = STATE_INSURANCE_FACTORS.get(listing.state, 1.0)
    monthly_insurance = listing.price * args.insurance_rate * args.landlord_insurance_multiplier * insurance_factor / 12
    down_payment_pct = (down_payment / listing.price) if listing.price > 0 else 1.0
    monthly_pmi = 0.0
    if down_payment_pct < 0.2 and principal > 0:
        monthly_pmi = principal * args.pmi_rate / 12

    monthly_maintenance = estimated_rent * args.maintenance_rate
    monthly_management = estimated_rent * args.management_rate
    monthly_vacancy = estimated_rent * args.vacancy_rate

    monthly_total_costs = (
        monthly_mortgage_pi
        + monthly_taxes
        + monthly_insurance
        + monthly_maintenance
        + monthly_management
        + monthly_vacancy
        + monthly_pmi
        + listing.hoa_monthly
    )
    monthly_net_cashflow = estimated_rent - monthly_total_costs

    annual_cashflow = monthly_net_cashflow * 12
    annual_cash_on_cash_return = (annual_cashflow / down_payment * 100) if down_payment > 0 else math.inf

    return Analysis(
        listing=listing,
        score=score_listing(listing, args),
        estimated_rent=estimated_rent,
        rent_estimation_method=rent_method,
        comp_count=comp_count,
        monthly_mortgage_pi=monthly_mortgage_pi,
        monthly_taxes=monthly_taxes,
        monthly_insurance=monthly_insurance,
        monthly_maintenance=monthly_maintenance,
        monthly_management=monthly_management,
        monthly_vacancy=monthly_vacancy,
        monthly_hoa=listing.hoa_monthly,
        monthly_total_costs=monthly_total_costs,
        monthly_net_cashflow=monthly_net_cashflow,
        annual_cash_on_cash_return=annual_cash_on_cash_return,
        down_payment=down_payment,
        down_payment_pct=down_payment_pct * 100,
        monthly_pmi=monthly_pmi,
    )



def normalize_address_key(address: str) -> str:
    normalized = (address or "").lower()
    replacements = {
        "street": "st",
        "st.": "st",
        "road": "rd",
        "rd.": "rd",
        "drive": "dr",
        "dr.": "dr",
        "avenue": "ave",
        "ave.": "ave",
        "lane": "ln",
        "ln.": "ln",
        "boulevard": "blvd",
        "blvd.": "blvd",
        "court": "ct",
        "ct.": "ct",
        "trail": "trl",
        "trl.": "trl",
        "place": "pl",
        "pl.": "pl",
        "way": "wy",
        "wy.": "wy",
    }
    for src, dst in replacements.items():
        normalized = re.sub(rf"\b{re.escape(src)}\b", dst, normalized)

    normalized = re.sub(r"[^a-z0-9]", "", normalized)
    return normalized


def deduplicate_analyses(analyses: List[Analysis]) -> List[Analysis]:
    """Keep one recommendation per normalized address+ZIP, choosing best cashflow."""
    best_by_property: Dict[str, Analysis] = {}
    for analysis in analyses:
        key = f"{normalize_address_key(analysis.listing.address)}|{analysis.listing.zip_code}"
        existing = best_by_property.get(key)
        if existing is None:
            best_by_property[key] = analysis
            continue

        if analysis.monthly_net_cashflow > existing.monthly_net_cashflow:
            best_by_property[key] = analysis
        elif analysis.monthly_net_cashflow == existing.monthly_net_cashflow and analysis.listing.price < existing.listing.price:
            best_by_property[key] = analysis

    return list(best_by_property.values())

def recommend(listings: Iterable[Listing], args: argparse.Namespace, rent_estimator: RentEstimator) -> List[Analysis]:
    property_types = {p.strip().lower() for p in str(args.property_types).split(",") if p.strip()}
    filtered = [
        l
        for l in listings
        if matches_location(l, args.location)
        and l.price <= args.max_price
        and l.bedrooms >= args.min_bedrooms
        and l.bathrooms >= args.min_bathrooms
        and (not property_types or l.property_type.lower() in property_types)
        and min(args.max_down_payment, l.price) > 0
    ]

    analyzed = [analyze_listing(l, args, rent_estimator) for l in filtered]
    positive = [a for a in analyzed if a.monthly_net_cashflow > 0]
    deduplicated = deduplicate_analyses(positive)

    deduplicated.sort(
        key=lambda a: (
            a.monthly_net_cashflow,
            a.annual_cash_on_cash_return,
            a.score,
        ),
        reverse=True,
    )
    return deduplicated[: args.results]


def render(recommendations: List[Analysis], args: argparse.Namespace) -> None:
    if not recommendations:
        print("No positive-cashflow houses found with current constraints.")
        print("Try one or more adjustments: increase --max-down-payment, lower --max-price, or reduce maintenance/management/vacancy assumptions.")
        return

    print(
        f"Found {len(recommendations)} recommended investment properties in {args.location.upper()} "
        f"under ${args.max_price:,.0f}."
    )
    print("=" * 120)

    for i, rec in enumerate(recommendations, start=1):
        l = rec.listing
        print(f"#{i} | {l.address}, {l.city}, {l.state} {l.zip_code} | List ${l.price:,.0f}")
        print(
            f"    Specs: {l.bedrooms:.0f}bd/{l.bathrooms:.1f}ba | {l.sqft:,.0f} sqft | "
            f"Built {l.year_built} | Lot {l.lot_size_sqft:,.0f} sqft"
        )
        print(
            f"    Score: {rec.score:.1f}/100 | Est. Rent ${rec.estimated_rent:,.0f}/mo "
            f"({rec.rent_estimation_method}, comps={rec.comp_count}) | Down Payment Used ${rec.down_payment:,.0f}"
        )
        print(
            "    Costs/mo: "
            f"P&I ${rec.monthly_mortgage_pi:,.0f}, Tax ${rec.monthly_taxes:,.0f}, "
            f"Ins ${rec.monthly_insurance:,.0f}, Maint ${rec.monthly_maintenance:,.0f}, "
            f"Mgmt ${rec.monthly_management:,.0f}, Vacancy ${rec.monthly_vacancy:,.0f}, PMI ${rec.monthly_pmi:,.0f}, "
            f"HOA ${rec.monthly_hoa:,.0f}"
        )
        print(
            f"    Net: ${rec.monthly_net_cashflow:,.0f}/mo | "
            f"Cash-on-Cash: {rec.annual_cash_on_cash_return:.2f}%/yr"
        )
        print("-" * 120)


def main() -> None:
    try:
        args = parse_args()
        listings = load_listings(args)
        rent_estimator = RentEstimator(args)
        recommendations = recommend(listings, args, rent_estimator)
        render(recommendations, args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
