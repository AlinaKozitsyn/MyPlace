import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests
import psycopg2
from psycopg2.extras import execute_values

# =========================================
# CONFIG
# =========================================

API_URL = "https://data.gov.il/api/3/action/datastore_search"
RESOURCE_ID = "5c78e9fa-c2e2-4771-93ff-7f400a12f7ba"
SOURCE_YEAR = 2026  # Year used for the load tag; adjust as needed

DB_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "family_project"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", "2009"),
}


# =========================================
# CLEANING
# =========================================

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


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()

    if text == "" or text == "-":
        return None

    return text


# =========================================
# FETCH
# =========================================

def fetch_all_records() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    offset = 0
    limit = 1000

    while True:
        params = {
            "resource_id": RESOURCE_ID,
            "limit": limit,
            "offset": offset,
        }

        response = requests.get(API_URL, params=params, timeout=60)
        response.raise_for_status()

        data = response.json()
        batch = data["result"]["records"]

        if not batch:
            break

        records.extend(batch)
        offset += limit

        print(f"[INFO] fetched {len(records)} rows")

    return records


# =========================================
# TRANSFORM
# =========================================

def transform_row(row: Dict[str, Any]) -> Tuple[int, str, Optional[str], int]:
    settlement_id = clean_integer(row.get("סמל_ישוב"))
    settlement_name = clean_text(row.get("שם_ישוב"))
    district = clean_text(row.get("שם_נפה"))

    if settlement_id is None:
        raise ValueError("Missing settlement_id")

    if settlement_name is None:
        raise ValueError(f"Missing settlement_name for settlement_id={settlement_id}")

    return (
        settlement_id,
        settlement_name,
        district,
        SOURCE_YEAR,
    )


def transform_rows(rows: List[Dict[str, Any]]) -> List[Tuple[int, str, Optional[str], int]]:
    deduped: Dict[int, Tuple[int, str, Optional[str], int]] = {}
    errors: List[str] = []
    duplicate_count = 0

    for row in rows:
        try:
            transformed = transform_row(row)
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


# =========================================
# SQL
# =========================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS settlements (
    settlement_id INTEGER PRIMARY KEY,
    settlement_name VARCHAR(150) NOT NULL,
    district VARCHAR(100),
    source_year INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

UPSERT_SQL = """
INSERT INTO settlements (
    settlement_id,
    settlement_name,
    district,
    source_year
)
VALUES %s
ON CONFLICT (settlement_id)
DO UPDATE SET
    settlement_name = EXCLUDED.settlement_name,
    district = EXCLUDED.district,
    source_year = EXCLUDED.source_year,
    updated_at = CURRENT_TIMESTAMP;
"""


# =========================================
# DATABASE
# =========================================

def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def create_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


def load_rows(conn, rows: List[Tuple[int, str, Optional[str], int]]) -> None:
    if not rows:
        print("[INFO] no rows to load")
        return

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=500)

    conn.commit()
    print(f"[INFO] loaded {len(rows)} rows into settlements")


# =========================================
# MAIN
# =========================================

def main() -> None:
    try:
        print("[INFO] starting ETL settlements")

        raw_rows = fetch_all_records()
        print(f"[INFO] raw rows {len(raw_rows)}")

        transformed_rows = transform_rows(raw_rows)

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