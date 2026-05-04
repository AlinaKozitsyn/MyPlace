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
RESOURCE_ID = "38207cf8-afe2-48ed-a3b0-c8f70c796015"

SOURCE_YEAR = 2022


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


# =========================================
# FETCH DATA
# =========================================

def fetch_all_records() -> List[Dict[str, Any]]:

    records = []
    offset = 0
    limit = 1000

    while True:

        params = {
            "resource_id": RESOURCE_ID,
            "limit": limit,
            "offset": offset
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

def transform_row(row):

    settlement_id = clean_integer(row.get("LocalityCode"))
    total_population = clean_integer(row.get("Total_Population"))
    households = clean_integer(row.get("Households"))

    if settlement_id is None:
        raise ValueError("Missing settlement_id")

    return (
        settlement_id,
        total_population,
        households,
        SOURCE_YEAR
    )


def transform_rows(rows):

    transformed = []

    for row in rows:
        try:
            transformed.append(transform_row(row))
        except Exception as exc:
            print(f"[WARN] skipping row: {exc}")

    return transformed


# =========================================
# SQL
# =========================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS households (
    settlement_id INTEGER PRIMARY KEY,
    total_population INTEGER,
    households INTEGER,
    source_year INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


UPSERT_SQL = """
INSERT INTO households (
    settlement_id,
    total_population,
    households,
    source_year
)
VALUES %s
ON CONFLICT (settlement_id)
DO UPDATE SET
    total_population = EXCLUDED.total_population,
    households = EXCLUDED.households,
    source_year = EXCLUDED.source_year,
    updated_at = CURRENT_TIMESTAMP;
"""


# =========================================
# DATABASE
# =========================================

def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def create_table(conn):

    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)

    conn.commit()


def load_rows(conn, rows):

    if not rows:
        return

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=500)

    conn.commit()


# =========================================
# MAIN
# =========================================

def main():

    print("[INFO] starting ETL households")

    raw_rows = fetch_all_records()

    print(f"[INFO] raw rows {len(raw_rows)}")

    transformed_rows = transform_rows(raw_rows)

    print(f"[INFO] transformed rows {len(transformed_rows)}")

    conn = get_connection()

    try:
        create_table(conn)
        load_rows(conn, transformed_rows)
    finally:
        conn.close()

    print("[INFO] done")


if __name__ == "__main__":
    main()