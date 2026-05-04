from __future__ import annotations

import csv
import re
from pathlib import Path

import fitz

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PDF_PATH = DATA_DIR / "rishon_lezion_tax_order_2026.pdf"
RAW_CSV_PATH = DATA_DIR / "arnona_rishon_lezion_raw.csv"
FINAL_CSV_PATH = DATA_DIR / "arnona_rishon_lezion_final.csv"

CITY = "ראשון לציון"
SOURCE_YEAR = 2026
SOURCE_DOCUMENT = "Rishon LeZion tax order 2026"
BUILDING_TYPE = "א"

ZONE_RATES = {
    "א": 69.69,
    "ב": 52.58,
    "ג": 69.69,
    "ד": 69.69,
}

RAW_COLUMNS = [
    "city",
    "raw_area_name",
    "normalized_area_name",
    "arnona_zone",
    "match_type",
    "source_page",
    "raw_text",
    "notes",
]

FINAL_COLUMNS = [
    "city",
    "area_name",
    "normalized_area_name",
    "arnona_zone",
    "building_type",
    "price_per_sqm_yearly",
    "source_year",
    "source_document",
    "is_default",
    "notes",
]

ZONE_B_ENTRIES = [
    {
        "raw_area_name": "שיכון המזרח לרבות כפר אריה",
        "normalized_area_name": "המזרח",
        "match_type": "neighborhood",
        "notes": "Zone B residential exception.",
    },
    {
        "raw_area_name": "שיכון המזרח",
        "normalized_area_name": "המזרח",
        "match_type": "neighborhood",
        "notes": "Alias from 'שיכון המזרח לרבות כפר אריה'.",
    },
    {
        "raw_area_name": "כפר אריה",
        "normalized_area_name": "כפר אריה",
        "match_type": "neighborhood",
        "notes": "Alias from 'שיכון המזרח לרבות כפר אריה'.",
    },
    {
        "raw_area_name": "שיכון גורדון",
        "normalized_area_name": "גורדון",
        "match_type": "neighborhood",
        "notes": "Zone B residential exception.",
    },
    {
        "raw_area_name": "שכונת רמת אליהו (למעט אזור תעשייה)",
        "normalized_area_name": "רמת אליהו",
        "match_type": "neighborhood",
        "notes": "Zone B residential exception; industrial area excluded by source.",
    },
    {
        "raw_area_name": "מתחמי המגורונים ברחבי העיר",
        "normalized_area_name": "מתחמי המגורונים ברחבי העיר",
        "match_type": "area",
        "notes": "Zone B residential exception.",
    },
    {
        "raw_area_name": "קריית קאליב",
        "normalized_area_name": "קרית קאליב",
        "match_type": "neighborhood",
        "notes": "All properties on Kaliv Street are Zone B.",
    },
    {
        "raw_area_name": "רחוב קאליב",
        "normalized_area_name": "קאליב",
        "match_type": "street",
        "notes": "All properties on Kaliv Street are Zone B.",
    },
    {
        "raw_area_name": "שכונת צמרות",
        "normalized_area_name": "צמרות",
        "match_type": "neighborhood",
        "notes": "Zone B residential exception.",
    },
    {
        "raw_area_name": "שיכון סלע חדש",
        "normalized_area_name": "סלע חדש",
        "match_type": "neighborhood",
        "notes": "Zone B residential exception.",
    },
    {
        "raw_area_name": "רחוב גוש עציון",
        "normalized_area_name": "גוש עציון",
        "match_type": "street",
        "notes": "Properties on this street are Zone B.",
    },
    {
        "raw_area_name": "רחוב עטרות",
        "normalized_area_name": "עטרות",
        "match_type": "street",
        "notes": "Properties on this street are Zone B.",
    },
    {
        "raw_area_name": "רחוב נהריים",
        "normalized_area_name": "נהריים",
        "match_type": "street",
        "notes": "Properties on this street are Zone B.",
    },
    {
        "raw_area_name": "רחוב חיש 1 עד חיש 8",
        "normalized_area_name": "חיש 1 עד חיש 8",
        "match_type": "street_range",
        "notes": "Properties on Hish 1-8 inclusive are Zone B.",
    },
    {
        "raw_area_name": "רחוב גבעתי 1,3,5,7,9,11,13",
        "normalized_area_name": "גבעתי 1,3,5,7,9,11,13",
        "match_type": "street_numbers",
        "notes": "Properties at listed numbers are Zone B.",
    },
    {
        "raw_area_name": "שיכון סלע ישן (נוה זאב)",
        "normalized_area_name": "סלע ישן נוה זאב",
        "match_type": "neighborhood",
        "notes": "Specific parcels in this area are Zone B.",
    },
    {
        "raw_area_name": "רחוב ירושלים 89 / קלוזנר 3",
        "match_type": "street_numbers",
        "notes": "Specific Zone B properties from parcel listing.",
    },
    {
        "raw_area_name": "רחוב ירושלים 87 / קלוזנר 5",
        "match_type": "street_numbers",
        "notes": "Specific Zone B properties from parcel listing.",
    },
    {
        "raw_area_name": "רחוב ירושלים 85 / קלוזנר 7",
        "match_type": "street_numbers",
        "notes": "Specific Zone B properties from parcel listing.",
    },
    {
        "raw_area_name": "רחוב ירושלים 83 / קלוזנר 9",
        "match_type": "street_numbers",
        "notes": "Specific Zone B properties from parcel listing.",
    },
    {
        "raw_area_name": "רחוב ירושלים 81 / קלוזנר 11",
        "match_type": "street_numbers",
        "notes": "Specific Zone B properties from parcel listing.",
    },
    {
        "raw_area_name": "רחוב אלרואי",
        "normalized_area_name": "אלרואי",
        "match_type": "street",
        "notes": "Only listed properties on Elroi Street are Zone B.",
    },
    {
        "raw_area_name": "נחלת יהודה ב (צפון)",
        "normalized_area_name": "נחלת יהודה ב צפון",
        "match_type": "neighborhood",
        "notes": "All parcels within listed blocks are Zone B.",
    },
]

ZONE_PLAN_ENTRIES = [
    {
        "raw_area_name": "תכנית רצ1000/1 | גוש 3946 | חלקות בשלמות 227,228 | חלקות בחלקן 95,229,360,363",
        "match_type": "plan_block",
        "arnona_zone": "ג",
    },
    {
        "raw_area_name": "תכנית רצ1000/1 | גוש 3947 | חלקות בשלמות 10,11,65 | חלקות בחלקן 7,12,66,67,72,74",
        "match_type": "plan_block",
        "arnona_zone": "ג",
    },
    {
        "raw_area_name": "תכנית רצ1000/1 | גוש 5030 | חלקות בחלקן 166",
        "match_type": "plan_block",
        "arnona_zone": "ג",
    },
    {
        "raw_area_name": "תכנית רצ1000/1 | גוש 5032 | חלקות בחלקן 38,40,47",
        "match_type": "plan_block",
        "arnona_zone": "ג",
    },
    {
        "raw_area_name": "תכנית רצ1000/1 | גוש 5033 | חלקות בחלקן 67",
        "match_type": "plan_block",
        "arnona_zone": "ג",
    },
    {
        "raw_area_name": "תכנית רצ8/21/1 | גוש 3946 | חלקות בשלמות 359,360,363,364,365 | חלקות בחלקן 227,229,357,361",
        "match_type": "plan_block",
        "arnona_zone": "ג",
    },
    {
        "raw_area_name": "תכנית רצ8/21/1 | גוש 3947 | חלקות בחלקן 3,7",
        "match_type": "plan_block",
        "arnona_zone": "ג",
    },
    {
        "raw_area_name": "תכנית רצ/מק1/15/170 | גוש 5030 | חלקות בחלקן 166",
        "match_type": "plan_block",
        "arnona_zone": "ג",
    },
    {
        "raw_area_name": "תכנית רצ/מק1/15/170 | גוש 5032 | חלקות בשלמות 29,36,38,43 | חלקות בחלקן 42",
        "match_type": "plan_block",
        "arnona_zone": "ג",
    },
    {
        "raw_area_name": "תכנית רצ1/70/1 | גוש 3946 | חלקות בחלקן 235,357",
        "match_type": "plan_block",
        "arnona_zone": "ד",
    },
    {
        "raw_area_name": "תכנית רצ1/70/1 | גוש 5467 | חלקות בחלקן 2",
        "match_type": "plan_block",
        "arnona_zone": "ד",
    },
]


def normalize_text(text: str) -> str:
    value = text.strip().lower()
    value = value.replace("\u05be", " ").replace("-", " ")
    value = value.replace('"', "").replace("'", "")
    value = value.replace("(", " ").replace(")", " ")
    value = value.replace("/", " ")
    value = re.sub(r"למעט אזור\s+תעשייה", "", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^רחוב\s+", "", value)
    value = re.sub(r"^רח\s+", "", value)
    value = re.sub(r"^רח׳\s+", "", value)
    value = re.sub(r"^רח'\s+", "", value)
    value = re.sub(r"^שכונת\s+", "", value)
    value = re.sub(r"^שיכון\s+", "", value)
    value = value.replace("קריית ", "קרית ")
    value = re.sub(r"\s+לרבות\s+", " ", value)
    value = re.sub(r"^כל הנכסים ב", "", value)
    value = re.sub(r"^כל הנכסים\s+", "", value)
    return value.strip()


def read_source_pages() -> tuple[str, str]:
    pdf = fitz.open(stream=PDF_PATH.read_bytes(), filetype="pdf")
    zone_page_text = pdf.load_page(2).get_text()
    rates_page_text = pdf.load_page(3).get_text()
    return zone_page_text, rates_page_text


def ensure_source_matches(zone_page_text: str, rates_page_text: str) -> None:
    normalized_zone_page = re.sub(r"\s+", " ", zone_page_text)
    normalized_rates_page = re.sub(r"\s+", " ", rates_page_text)

    required_zone_snippets = [
        "שיכון המזרח לרבות כפר אריה",
        "שיכון גורדון",
        "שכונת רמת אליהו",
        "מתחמי המגורונים ברחבי העיר",
        "קריית קאליב",
        "שכונת צמרות",
        "שיכון סלע חדש",
        "רח' גוש עציון",
        "רח' עטרות",
        "רח' נהריים",
        "רח' חיש1",
        "רח' גבעתי1",
        "שיכון סלע ישן",
        "נחלת יהודה ב",
        "/רצ1000/1",
        "/רצ8/21/1",
        "/רצ/מק1/15/170",
        "/רצ1/70/1",
    ]
    for snippet in required_zone_snippets:
        if snippet not in normalized_zone_page:
            raise ValueError(f"Expected zone definition snippet not found: {snippet}")

    for expected_rate in ("69.69", "52.58"):
        if expected_rate not in normalized_rates_page:
            raise ValueError(f"Expected residential rate not found: {expected_rate}")


def build_raw_rows() -> list[dict]:
    rows: list[dict] = []
    for entry in ZONE_B_ENTRIES:
        rows.append(
            {
                "city": CITY,
                "raw_area_name": entry["raw_area_name"],
                "normalized_area_name": entry.get(
                    "normalized_area_name",
                    normalize_text(entry["raw_area_name"]),
                ),
                "arnona_zone": "ב",
                "match_type": entry["match_type"],
                "source_page": 3,
                "raw_text": entry["raw_area_name"],
                "notes": entry["notes"],
            }
        )

    for entry in ZONE_PLAN_ENTRIES:
        rows.append(
            {
                "city": CITY,
                "raw_area_name": entry["raw_area_name"],
                "normalized_area_name": normalize_text(entry["raw_area_name"]),
                "arnona_zone": entry["arnona_zone"],
                "match_type": entry["match_type"],
                "source_page": 3,
                "raw_text": entry["raw_area_name"],
                "notes": "Plan/block residential exception.",
            }
        )

    return rows


def build_final_rows(raw_rows: list[dict]) -> list[dict]:
    final_rows: list[dict] = []
    seen: set[str] = set()

    for row in raw_rows:
        key = (row["normalized_area_name"], row["arnona_zone"])
        if key in seen:
            continue
        seen.add(key)
        final_rows.append(
            {
                "city": CITY,
                "area_name": row["raw_area_name"],
                "normalized_area_name": row["normalized_area_name"],
                "arnona_zone": row["arnona_zone"],
                "building_type": BUILDING_TYPE,
                "price_per_sqm_yearly": ZONE_RATES[row["arnona_zone"]],
                "source_year": SOURCE_YEAR,
                "source_document": SOURCE_DOCUMENT,
                "is_default": "false",
                "notes": row["notes"],
            }
        )

    final_rows.append(
        {
            "city": CITY,
            "area_name": "DEFAULT",
            "normalized_area_name": "__default__",
            "arnona_zone": "א",
            "building_type": BUILDING_TYPE,
            "price_per_sqm_yearly": ZONE_RATES["א"],
            "source_year": SOURCE_YEAR,
            "source_document": SOURCE_DOCUMENT,
            "is_default": "true",
            "notes": "Default residential zone for the entire city except explicit zones B/C/D.",
        }
    )
    return final_rows


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def build_outputs() -> tuple[list[dict], list[dict]]:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"Source PDF not found: {PDF_PATH}")

    zone_page_text, rates_page_text = read_source_pages()
    ensure_source_matches(zone_page_text, rates_page_text)

    raw_rows = build_raw_rows()
    final_rows = build_final_rows(raw_rows)
    write_csv(RAW_CSV_PATH, RAW_COLUMNS, raw_rows)
    write_csv(FINAL_CSV_PATH, FINAL_COLUMNS, final_rows)
    return raw_rows, final_rows


def main() -> None:
    raw_rows, final_rows = build_outputs()
    print("Extracted Zone B areas:")
    for row in raw_rows:
        if row["arnona_zone"] == "ב":
            print(f"  - {row['raw_area_name']}")
    print(f"Final mapping count: {len(final_rows)}")
    print(
        "DEFAULT Zone A exists:",
        any(row["is_default"] == "true" and row["arnona_zone"] == "א" for row in final_rows),
    )


if __name__ == "__main__":
    main()
