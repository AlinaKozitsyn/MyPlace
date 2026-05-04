import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
import psycopg2
from psycopg2.extras import execute_values

# =========================================================
# CONFIG
# =========================================================

API_BASE_URL = "https://boardsgenerator.cbs.gov.il/Handlers/WebParts/YishuvimHandler.ashx/"
# Year of data being fetched; must match the upstream URL
SOURCE_YEAR = 2022
REQUEST_DELAY_SECONDS = 0.15

DB_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "family_project"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", "2009"),
}


# =========================================================
# CLEANING HELPERS
# =========================================================

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
    # Strip thousands separators
    text = text.replace(",", "")
    try:
        return int(text)
    except ValueError:
        return None


# =========================================================
# API FUNCTIONS
# =========================================================

def build_params(page_number: int) -> Dict[str, Any]:
    """
    Build query parameters for the CBS API request for Transport data.
    """
    return {
        "dataMode": "Yeshuv",
        "filters": f'{{"Years":{SOURCE_YEAR},"Subjects":"1"}}',
        "filtersearch": "",
        "language": "Hebrew",
        "mode": "GridData",
        "pageNumber": page_number,
        "search": "",
        "subject": "Transport",
    }


def fetch_page(session: requests.Session, page_number: int) -> Dict[str, Any]:
    response = session.get(
        API_BASE_URL,
        params=build_params(page_number),
        timeout=60
    )
    response.raise_for_status()
    return response.json()


def fetch_all_records() -> List[Dict[str, Any]]:
    all_rows: List[Dict[str, Any]] = []

    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "etl-transport/1.0",
            "Accept": "application/json",
        })

        # fetch first page to know how many pages there are
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


# =========================================================
# TRANSFORM FUNCTIONS
# =========================================================

def transform_row(row: Dict[str, Any]) -> Tuple[int, Optional[int], int]:
    """
    Transform one raw API row into tuple for the transport table.
    Expected fields:
      - Semel          -> settlement_id
      - 1020           -> private cars
    """
    settlement_id = clean_integer(row.get("Semel"))
    private_cars_num = clean_integer(row.get("1020"))

    if settlement_id is None:
        raise ValueError(f"Missing settlement_id in row: {row}")

    # private_cars_num may be None; missing values are acceptable
    return settlement_id, private_cars_num, SOURCE_YEAR


def transform_rows(rows: List[Dict[str, Any]]) -> List[Tuple[int, Optional[int], int]]:
    transformed = []
    errors = []
    for row in rows:
        try:
            transformed.append(transform_row(row))
        except Exception as exc:
            errors.append((row, str(exc)))

    if errors:
        print(f"[WARN] {len(errors)} rows failed transformation.")
        for bad_row, err in errors[:10]:
            print(f"[WARN] Error: {err} | Row: {bad_row}")

    print(f"[INFO] Successfully transformed {len(transformed)} rows.")
    return transformed


# =========================================================
# DATABASE SQL
# =========================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS transport (
    settlement_id      INTEGER PRIMARY KEY,
    private_cars_num   INTEGER NULL,
    source_year        INTEGER NOT NULL,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

UPSERT_SQL = """
INSERT INTO transport (
    settlement_id,
    private_cars_num,
    source_year
)
VALUES %s
ON CONFLICT (settlement_id)
DO UPDATE SET
    private_cars_num = EXCLUDED.private_cars_num,
    source_year      = EXCLUDED.source_year,
    updated_at       = CURRENT_TIMESTAMP;
"""


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def create_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print("[INFO] Table transport is ready.")


def load_rows(conn, rows: List[Tuple[int, Optional[int], int]]) -> None:
    if not rows:
        print("[INFO] No rows to load.")
        return
    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=500)
    conn.commit()
    print(f"[INFO] Loaded {len(rows)} rows into transport.")


# =========================================================
# MAIN
# =========================================================

def main() -> None:
    try:
        print("[INFO] Starting ETL for transport...")
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