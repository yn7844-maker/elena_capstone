import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests


SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

DEFAULT_LANGUAGE = "es"
DEFAULT_REGION = "ES"

DEFAULT_TEXT_QUERIES = [
    "supermercado en Madrid",
    "grocery store in Madrid",
    "Carrefour Express Madrid",
    "Mercadona Madrid",
    "Dia Madrid",
    "Lidl Madrid",
    "Alcampo Madrid",
    "El Corte Ingles supermercado Madrid",
    "Sanchez Romero Madrid",
    "Mercado de la Paz Madrid",
]

DEFAULT_NEARBY_POINTS = [
    {"label": "sol", "latitude": 40.4168, "longitude": -3.7038, "radius": 2200},
    {"label": "salamanca", "latitude": 40.4302, "longitude": -3.6835, "radius": 2200},
    {"label": "chamartin", "latitude": 40.4637, "longitude": -3.6890, "radius": 2200},
    {"label": "arganzuela", "latitude": 40.3982, "longitude": -3.6981, "radius": 2200},
    {"label": "tetuan", "latitude": 40.4605, "longitude": -3.6998, "radius": 2200},
]

SEARCH_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.primaryType",
        "places.types",
        "places.googleMapsUri",
        "places.businessStatus",
    ]
)

DETAIL_FIELD_MASK = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "primaryType",
        "types",
        "rating",
        "userRatingCount",
        "regularOpeningHours",
        "currentOpeningHours",
        "internationalPhoneNumber",
        "nationalPhoneNumber",
        "websiteUri",
        "priceLevel",
        "businessStatus",
        "googleMapsUri",
        "reviews",
        "photos",
    ]
)


def load_json_file(path_str: str):
    if not path_str:
        return None
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_queries(path_str: str):
    if not path_str:
        return DEFAULT_TEXT_QUERIES
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Query file not found: {path}")
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def request_json(method: str, url: str, api_key: str, field_mask: str, payload=None, params=None):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }
    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        json=payload,
        params=params,
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{response.status_code} {response.text}")
    return response.json()


def search_by_text(api_key: str, queries: list[str], max_results: int, sleep_seconds: float):
    results = []
    for query in queries:
        payload = {
            "textQuery": query,
            "languageCode": DEFAULT_LANGUAGE,
            "regionCode": DEFAULT_REGION,
            "maxResultCount": max_results,
        }
        data = request_json("POST", SEARCH_TEXT_URL, api_key, SEARCH_FIELD_MASK, payload=payload)
        for place in data.get("places", []):
            place["_search_mode"] = "text"
            place["_search_query"] = query
            results.append(place)
        time.sleep(sleep_seconds)
    return results


def search_by_nearby(api_key: str, points: list[dict], included_types: list[str], max_results: int, sleep_seconds: float):
    results = []
    for point in points:
        payload = {
            "includedTypes": included_types,
            "maxResultCount": max_results,
            "rankPreference": "DISTANCE",
            "languageCode": DEFAULT_LANGUAGE,
            "regionCode": DEFAULT_REGION,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": point["latitude"],
                        "longitude": point["longitude"],
                    },
                    "radius": float(point["radius"]),
                }
            },
        }
        data = request_json("POST", SEARCH_NEARBY_URL, api_key, SEARCH_FIELD_MASK, payload=payload)
        for place in data.get("places", []):
            place["_search_mode"] = "nearby"
            place["_search_query"] = point["label"]
            results.append(place)
        time.sleep(sleep_seconds)
    return results


def dedupe_places(places: list[dict]):
    deduped = {}
    for place in places:
        place_id = place.get("id")
        if not place_id:
            continue
        if place_id not in deduped:
            deduped[place_id] = place
            deduped[place_id]["_matched_by"] = [place.get("_search_query")]
        else:
            deduped[place_id]["_matched_by"].append(place.get("_search_query"))
    return list(deduped.values())


def fetch_place_details(api_key: str, place_id: str):
    url = PLACE_DETAILS_URL.format(place_id=place_id)
    return request_json("GET", url, api_key, DETAIL_FIELD_MASK)


def normalize_reviews(reviews: list[dict], limit: int):
    normalized = []
    for review in (reviews or [])[:limit]:
        normalized.append(
            {
                "rating": review.get("rating"),
                "publishTime": review.get("publishTime"),
                "relativePublishTimeDescription": review.get("relativePublishTimeDescription"),
                "text": (review.get("text") or {}).get("text"),
                "originalText": (review.get("originalText") or {}).get("text"),
                "authorName": (review.get("authorAttribution") or {}).get("displayName"),
                "authorUri": (review.get("authorAttribution") or {}).get("uri"),
            }
        )
    return normalized


def normalize_photos(photos: list[dict], limit: int):
    normalized = []
    for photo in (photos or [])[:limit]:
        normalized.append(
            {
                "name": photo.get("name"),
                "widthPx": photo.get("widthPx"),
                "heightPx": photo.get("heightPx"),
                "authorAttributions": photo.get("authorAttributions", []),
            }
        )
    return normalized


def flatten_place(detail: dict, seed: dict, review_limit: int, photo_limit: int):
    display_name = (detail.get("displayName") or {}).get("text")
    location = detail.get("location") or {}
    opening_hours = detail.get("currentOpeningHours") or {}
    regular_hours = detail.get("regularOpeningHours") or {}

    return {
        "place_id": detail.get("id"),
        "name": display_name,
        "address": detail.get("formattedAddress"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "primary_type": detail.get("primaryType"),
        "types": "|".join(detail.get("types", [])),
        "rating": detail.get("rating"),
        "review_count": detail.get("userRatingCount"),
        "price_level": detail.get("priceLevel"),
        "business_status": detail.get("businessStatus"),
        "is_open_now": opening_hours.get("openNow"),
        "current_opening_hours_json": json.dumps(opening_hours, ensure_ascii=False),
        "regular_opening_hours_json": json.dumps(regular_hours, ensure_ascii=False),
        "phone_international": detail.get("internationalPhoneNumber"),
        "phone_national": detail.get("nationalPhoneNumber"),
        "website": detail.get("websiteUri"),
        "google_maps_uri": detail.get("googleMapsUri"),
        "matched_by": "|".join(seed.get("_matched_by", [])),
        "seed_search_mode": seed.get("_search_mode"),
        "reviews_json": json.dumps(normalize_reviews(detail.get("reviews"), review_limit), ensure_ascii=False),
        "photos_json": json.dumps(normalize_photos(detail.get("photos"), photo_limit), ensure_ascii=False),
        "raw_json": json.dumps(detail, ensure_ascii=False),
    }


def write_csv(rows: list[dict], path: Path):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Extract Madrid grocery places from Google Places API.")
    parser.add_argument("--api-key", default=os.getenv("GOOGLE_MAPS_API_KEY"))
    parser.add_argument("--query-file", help="Path to a text file with one text search query per line.")
    parser.add_argument("--nearby-points-json", help="Path to JSON array of nearby search center points.")
    parser.add_argument("--search-modes", nargs="+", choices=["text", "nearby"], default=["text", "nearby"])
    parser.add_argument("--included-types", nargs="+", default=["supermarket", "grocery_store", "convenience_store"])
    parser.add_argument("--max-results-per-search", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--review-limit", type=int, default=3)
    parser.add_argument("--photo-limit", type=int, default=5)
    parser.add_argument("--output-csv", default="outputs/madrid_grocery_places.csv")
    parser.add_argument("--output-json", default="outputs/madrid_grocery_places.json")
    args = parser.parse_args()

    if not args.api_key:
        print("Missing API key. Use --api-key or set GOOGLE_MAPS_API_KEY.", file=sys.stderr)
        sys.exit(1)

    queries = load_queries(args.query_file)
    nearby_points = load_json_file(args.nearby_points_json) if args.nearby_points_json else DEFAULT_NEARBY_POINTS

    all_seed_places = []

    if "text" in args.search_modes:
        print(f"[1/3] Running text searches: {len(queries)} queries")
        all_seed_places.extend(
            search_by_text(
                api_key=args.api_key,
                queries=queries,
                max_results=args.max_results_per_search,
                sleep_seconds=args.sleep_seconds,
            )
        )

    if "nearby" in args.search_modes:
        print(f"[2/3] Running nearby searches: {len(nearby_points)} zones")
        all_seed_places.extend(
            search_by_nearby(
                api_key=args.api_key,
                points=nearby_points,
                included_types=args.included_types,
                max_results=args.max_results_per_search,
                sleep_seconds=args.sleep_seconds,
            )
        )

    deduped = dedupe_places(all_seed_places)
    print(f"Found {len(all_seed_places)} raw candidates, {len(deduped)} unique place IDs")

    enriched_rows = []
    total = len(deduped)
    for index, seed in enumerate(deduped, start=1):
        place_id = seed["id"]
        try:
            detail = fetch_place_details(args.api_key, place_id)
            enriched_rows.append(flatten_place(detail, seed, args.review_limit, args.photo_limit))
            print(f"[3/3] ({index}/{total}) fetched details for {place_id}")
        except Exception as exc:
            print(f"Failed to fetch details for {place_id}: {exc}", file=sys.stderr)
        time.sleep(args.sleep_seconds)

    csv_path = Path(args.output_csv)
    json_path = Path(args.output_json)
    write_csv(enriched_rows, csv_path)
    write_json(enriched_rows, json_path)

    print(f"Saved CSV: {csv_path.resolve()}")
    print(f"Saved JSON: {json_path.resolve()}")
    print(f"Final place count: {len(enriched_rows)}")


if __name__ == "__main__":
    main()
