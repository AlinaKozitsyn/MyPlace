import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
import psycopg2
from psycopg2.extras import execute_values

API_BASE_URL = "https://boardsgenerator.cbs.gov.il/Handlers/WebParts/YishuvimHandler.ashx/"
SOURCE_YEAR = 2024
REQUEST_DELAY_SECONDS = 0.15

DISTRICT_MAPPING = {
    "ירושלים": 1,
    "הצפון": 2,
    "חיפה": 3,
    "המרכז": 4,
    "תל אביב": 5,
    "הדרום": 6,
    "יהודה ושומרון": 7,
    "יהודה והשומרון": 7,
}

DB_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "family_project"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", "2009"),
}


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text == "-":
        return None
    return text


def clean_integer(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text == "-":
        return None
    text = text.replace(",", "")
    try:
        return int(text)
    except ValueError:
        return None


def build_params(page_number: int) -> Dict[str, Any]:
    return {
        "dataMode": "Yeshuv",
        "filters": f'{{"Years":{SOURCE_YEAR}}}',
        "filtersearch": "",
        "language": "Hebrew",
        "mode": "GridData",
        "pageNumber": page_number,
        "search": "",
        "subject": "BaseData",
    }


def fetch_page(session: requests.Session, page_number: int) -> Dict[str, Any]:
    response = session.get(API_BASE_URL, params=build_params(page_number), timeout=60)
    response.raise_for_status()
    return response.json()


def fetch_all_records() -> List[Dict[str, Any]]:
    all_rows: List[Dict[str, Any]] = []

    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "etl-general-info/1.0",
            "Accept": "application/json",
        })

        first_payload = fetch_page(session, 1)
        total_pages = first_payload.get("TotalPages", 1)
        first_rows = first_payload.get("Table", [])

        all_rows.extend(first_rows)

        for page in range(2, total_pages + 1):
            payload = fetch_page(session, page)
            rows = payload.get("Table", [])
            all_rows.extend(rows)
            time.sleep(REQUEST_DELAY_SECONDS)

    return all_rows


def transform_row(row: Dict[str, Any]) -> Tuple[int, str, Optional[int], Optional[int], Optional[int], int]:
    settlement_id = clean_integer(row.get("SemelYishuv"))
    settlement_name_he = clean_text(row.get("Name"))
    population_total = clean_integer(row.get("PepoleNumber"))
    population_jewish = clean_integer(row.get("PepoleNumberJewishWithOther"))
    machoz = clean_text(row.get("Machoz"))
    district = DISTRICT_MAPPING.get(machoz) if machoz else None

    if settlement_id is None:
        raise ValueError(f"Missing settlement_id in row: {row}")

    if settlement_name_he is None:
        raise ValueError(f"Missing settlement_name_he for settlement_id={settlement_id}")

    return (
        settlement_id,
        settlement_name_he,
        population_total,
        population_jewish,
        district,
        SOURCE_YEAR,
    )


def transform_rows(rows: List[Dict[str, Any]]) -> List[Tuple[int, str, Optional[int], Optional[int], Optional[int], int]]:
    transformed_rows = []
    for row in rows:
        try:
            transformed_rows.append(transform_row(row))
        except Exception as exc:
            print(f"[WARN] Skipping row בגלל שגיאה: {exc}")
    return transformed_rows


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS general_info (
    settlement_id        INTEGER PRIMARY KEY,
    settlement_name_he   VARCHAR(150) NOT NULL,
    population_total     INTEGER NULL,
    population_jewish    INTEGER NULL,
    district             INTEGER NULL,
    source_year          INTEGER NOT NULL,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

UPSERT_SQL = """
INSERT INTO general_info (
    settlement_id,
    settlement_name_he,
    population_total,
    population_jewish,
    district,
    source_year
)
VALUES %s
ON CONFLICT (settlement_id)
DO UPDATE SET
    settlement_name_he = EXCLUDED.settlement_name_he,
    population_total   = EXCLUDED.population_total,
    population_jewish  = EXCLUDED.population_jewish,
    district           = EXCLUDED.district,
    source_year        = EXCLUDED.source_year,
    updated_at         = CURRENT_TIMESTAMP;
"""


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def create_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


def load_rows(conn, rows: List[Tuple[int, str, Optional[int], Optional[int], Optional[int], int]]) -> None:
    if not rows:
        print("[INFO] No rows to load.")
        return

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=500)
    conn.commit()


def main() -> None:
    try:
        print("[INFO] Starting ETL for general_info...")
        raw_rows = fetch_all_records()
        print(f"[INFO] Raw rows fetched: {len(raw_rows)}")

        transformed_rows = transform_rows(raw_rows)
        print(f"[INFO] Transformed rows: {len(transformed_rows)}")

        conn = get_connection()
        try:
            create_table(conn)
            load_rows(conn, transformed_rows)
        finally:
            conn.close()

        print("[INFO] ETL finished successfully.")

    except requests.HTTPError as exc:
        print(f"[ERROR] HTTP error: {exc}")
        sys.exit(1)
    except psycopg2.Error as exc:
        print(f"[ERROR] Database error: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] Unexpected error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()