import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
import psycopg2
from psycopg2.extras import execute_values

# =====================================
# CONFIG
# =====================================

API_BASE_URL = "https://boardsgenerator.cbs.gov.il/Handlers/WebParts/YishuvimHandler.ashx/"
SOURCE_YEAR = 2020
REQUEST_DELAY_SECONDS = 0.15

DB_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "family_project"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", "2009"),
}

# Map Hebrew API column names to DB field names
TARGET_FIELDS = {
    "סמל היישוב": "settlement_id",
    "מדד נגישות פוטנציאלית (דירוג)": "potential_accessibility_rank",
    "מדד פריפריאליות 2020 (דירוג)": "peripherality_rank_2020",
}


# =====================================
# CLEAN HELPERS
# =====================================

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


# =====================================
# API
# =====================================

def build_params(page_number: int) -> Dict[str, Any]:
    return {
        "dataMode": "Yeshuv",
        "filters": f'{{"Years":{SOURCE_YEAR}}}',
        "filtersearch": "",
        "language": "Hebrew",
        "mode": "GridData",
        "pageNumber": page_number,
        "search": "",
        "subject": "Periferialiyut",
    }


def fetch_page(session: requests.Session, page_number: int) -> Dict[str, Any]:
    response = session.get(API_BASE_URL, params=build_params(page_number), timeout=60)
    response.raise_for_status()
    return response.json()


def build_column_id_map(columns: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Hebrew column name -> API internal column id
    """
    column_id_map: Dict[str, str] = {}

    for col in columns:
        col_name = clean_text(col.get("Name"))
        col_id = clean_text(col.get("Id"))

        if col_name and col_id:
            column_id_map[col_name] = col_id

    return column_id_map


def validate_required_columns(column_id_map: Dict[str, str]) -> None:
    missing = [he_name for he_name in TARGET_FIELDS.keys() if he_name not in column_id_map]

    if missing:
        raise ValueError(
            "Missing required columns in API response: " + ", ".join(missing)
        )


def fetch_all_records() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    all_rows: List[Dict[str, Any]] = []

    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "etl-periphery/1.0",
            "Accept": "application/json",
        })

        first_payload = fetch_page(session, 1)

        columns = first_payload.get("Columns", [])
        column_id_map = build_column_id_map(columns)
        validate_required_columns(column_id_map)

        total_pages = first_payload.get("TotalPages", 1)
        first_rows = first_payload.get("Table", [])

        all_rows.extend(first_rows)

        for page in range(2, total_pages + 1):
            payload = fetch_page(session, page)
            rows = payload.get("Table", [])
            all_rows.extend(rows)
            time.sleep(REQUEST_DELAY_SECONDS)

    return all_rows, column_id_map


# =====================================
# TRANSFORM
# =====================================

def transform_row(
    row: Dict[str, Any],
    column_id_map: Dict[str, str],
) -> Tuple[int, Optional[int], Optional[int], int]:
    settlement_id = clean_integer(row.get(column_id_map["סמל היישוב"]))

    if settlement_id is None:
        raise ValueError(f"Missing settlement_id in row: {row}")

    potential_accessibility_rank = clean_integer(
        row.get(column_id_map["מדד נגישות פוטנציאלית (דירוג)"])
    )

    peripherality_rank_2020 = clean_integer(
        row.get(column_id_map["מדד פריפריאליות 2020 (דירוג)"])
    )

    return (
        settlement_id,
        potential_accessibility_rank,
        peripherality_rank_2020,
        SOURCE_YEAR,
    )


def transform_rows(
    rows: List[Dict[str, Any]],
    column_id_map: Dict[str, str],
) -> List[Tuple[int, Optional[int], Optional[int], int]]:
    deduped: Dict[int, Tuple[int, Optional[int], Optional[int], int]] = {}
    errors: List[str] = []
    duplicate_count = 0

    for row in rows:
        try:
            transformed = transform_row(row, column_id_map)
            settlement_id = transformed[0]

            if settlement_id in deduped:
                duplicate_count += 1

            deduped[settlement_id] = transformed

        except Exception as exc:
            errors.append(str(exc))

    if errors:
        print(f"[WARN] skipped {len(errors)} bad rows")
        for err in errors[:10]:
            print(f"[WARN] {err}")

    print(f"[INFO] duplicate settlement_id rows: {duplicate_count}")
    print(f"[INFO] unique transformed rows: {len(deduped)}")

    return list(deduped.values())


# =====================================
# SQL
# =====================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS periphery (
    settlement_id INTEGER PRIMARY KEY,
    potential_accessibility_rank INTEGER,
    peripherality_rank_2020 INTEGER,
    source_year INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

UPSERT_SQL = """
INSERT INTO periphery (
    settlement_id,
    potential_accessibility_rank,
    peripherality_rank_2020,
    source_year
)
VALUES %s
ON CONFLICT (settlement_id)
DO UPDATE SET
    potential_accessibility_rank = EXCLUDED.potential_accessibility_rank,
    peripherality_rank_2020 = EXCLUDED.peripherality_rank_2020,
    source_year = EXCLUDED.source_year,
    updated_at = CURRENT_TIMESTAMP;
"""


# =====================================
# DATABASE
# =====================================

def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def create_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


def load_rows(conn, rows: List[Tuple[int, Optional[int], Optional[int], int]]) -> None:
    if not rows:
        print("[INFO] no rows to load")
        return

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=500)

    conn.commit()
    print(f"[INFO] loaded {len(rows)} rows into periphery")


# =====================================
# MAIN
# =====================================

def main() -> None:
    try:
        print("[INFO] starting ETL periphery")

        raw_rows, column_id_map = fetch_all_records()
        print(f"[INFO] raw rows {len(raw_rows)}")

        transformed_rows = transform_rows(raw_rows, column_id_map)

        conn = get_connection()
        try:
            create_table(conn)
            load_rows(conn, transformed_rows)
        finally:
            conn.close()

        print("[INFO] done")

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