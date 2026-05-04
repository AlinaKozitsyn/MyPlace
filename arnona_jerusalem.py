from __future__ import annotations

import csv
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
FINAL_CSV_PATH = ROOT_DIR / "data" / "arnona_jerusalem_neighborhoods_final.csv"
ROOM_TO_SQM = {
    3: 75,
    4: 100,
    5: 125,
}


def normalize_neighborhood(text: str) -> str:
    value = text.strip().lower().replace("-", " ").replace("'", "").replace('"', "")
    while "  " in value:
        value = value.replace("  ", " ")
    return value


def get_arnona_price(city: str, neighborhood: str, desired_rooms: int) -> dict:
    if desired_rooms not in ROOM_TO_SQM:
        raise ValueError("desired_rooms must be one of: 3, 4, 5")

    if not FINAL_CSV_PATH.exists():
        raise FileNotFoundError(
            f"Final arnona dataset not found: {FINAL_CSV_PATH}. "
            "Run etl/etl_arnona_jerusalem.py first."
        )

    desired_city = city.strip()
    desired_neighborhood = normalize_neighborhood(neighborhood)

    with FINAL_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row["city"].strip() != desired_city:
                continue
            if normalize_neighborhood(row["normalized_neighborhood"]) != desired_neighborhood:
                continue

            estimated_sqm = ROOM_TO_SQM[desired_rooms]
            price = float(row["price_per_sqm_yearly"])
            yearly = round(price * estimated_sqm, 2)
            monthly = round(yearly / 12, 2)

            return {
                "city": row["city"],
                "neighborhood": row["neighborhood"],
                "arnona_zone": row["arnona_zone"],
                "building_type": int(row["building_type"]),
                "price_per_sqm_yearly": price,
                "estimated_sqm": estimated_sqm,
                "arnona_yearly": yearly,
                "arnona_monthly": monthly,
                "source_year": int(row["source_year"]),
                "note": "Estimated using average apartment size and standard residential building type.",
            }

    raise ValueError(
        f"No arnona record found for city={city!r}, neighborhood={neighborhood!r}."
    )
