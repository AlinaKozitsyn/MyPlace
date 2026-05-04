from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
JERUSALEM_FINAL_CSV_PATH = DATA_DIR / "arnona_jerusalem_neighborhoods_final.csv"
RISHON_FINAL_CSV_PATH = DATA_DIR / "arnona_rishon_lezion_final.csv"

ROOM_TO_SQM = {
    3: 75,
    4: 100,
    5: 125,
}


def normalize_area_name(text: str) -> str:
    value = text.strip().lower()
    value = value.replace("\u05be", " ").replace("-", " ")
    value = value.replace('"', "").replace("'", "")
    value = value.replace("(", " ").replace(")", " ")
    value = value.replace("/", " ")
    value = value.replace("קריית", "קרית")
    value = re.sub(r"למעט אזור\s+תעשייה", "", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^שכונת\s+", "", value)
    value = re.sub(r"^שיכון\s+", "", value)
    value = re.sub(r"^רחוב\s+", "", value)
    value = re.sub(r"^רח\s+", "", value)
    value = re.sub(r"^רח׳\s+", "", value)
    value = re.sub(r"^רח'\s+", "", value)
    value = re.sub(r"\s+לרבות\s+", " ", value)
    return value.strip()
def calculate_arnona(city: str, neighborhood_or_area: str, desired_rooms: int) -> dict:
    if desired_rooms not in ROOM_TO_SQM:
        raise ValueError("desired_rooms must be one of: 3, 4, 5")

    normalized_city = city.strip()
    normalized_query = normalize_area_name(neighborhood_or_area)
    estimated_sqm = ROOM_TO_SQM[desired_rooms]

    if normalized_city == "ראשון לציון":
        if not RISHON_FINAL_CSV_PATH.exists():
            raise FileNotFoundError(
                f"Final arnona dataset not found: {RISHON_FINAL_CSV_PATH}. "
                "Run etl/etl_arnona_rishon_lezion.py first."
            )

        default_row: dict | None = None
        matched_row: dict | None = None
        with RISHON_FINAL_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["is_default"] == "true":
                    default_row = row
                    continue
                if normalize_area_name(row["normalized_area_name"]) == normalized_query:
                    matched_row = row
                    break

        row = matched_row or default_row
        if row is None:
            raise ValueError("DEFAULT Zone A row is missing from Rishon LeZion arnona mapping.")

        price = float(row["price_per_sqm_yearly"])
        yearly = round(price * estimated_sqm, 2)
        monthly = round(yearly / 12, 2)
        return {
            "city": row["city"],
            "selected_area": neighborhood_or_area,
            "arnona_zone": row["arnona_zone"],
            "building_type": row["building_type"],
            "price_per_sqm_yearly": price,
            "estimated_sqm": estimated_sqm,
            "arnona_yearly": yearly,
            "arnona_monthly": monthly,
            "source_year": int(row["source_year"]),
            "note": "Estimated using average apartment size and standard residential building type.",
        }

    if normalized_city == "ירושלים":
        if not JERUSALEM_FINAL_CSV_PATH.exists():
            raise FileNotFoundError(
                f"Final arnona dataset not found: {JERUSALEM_FINAL_CSV_PATH}. "
                "Run etl/etl_arnona_jerusalem.py first."
            )

        with JERUSALEM_FINAL_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if normalize_area_name(row["normalized_neighborhood"]) != normalized_query:
                    continue
                price = float(row["price_per_sqm_yearly"])
                yearly = round(price * estimated_sqm, 2)
                monthly = round(yearly / 12, 2)
                return {
                    "city": row["city"],
                    "selected_area": neighborhood_or_area,
                    "arnona_zone": row["arnona_zone"],
                    "building_type": row["building_type"],
                    "price_per_sqm_yearly": price,
                    "estimated_sqm": estimated_sqm,
                    "arnona_yearly": yearly,
                    "arnona_monthly": monthly,
                    "source_year": int(row["source_year"]),
                    "note": "Estimated using average apartment size and standard residential building type.",
                }

        raise ValueError(
            f"No arnona record found for city={city!r}, neighborhood_or_area={neighborhood_or_area!r}."
        )

    raise ValueError(f"Unsupported city: {city!r}")
