import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests
import psycopg2
from psycopg2.extras import execute_values

API_URL = "https://data.gov.il/api/3/action/datastore_search"
RESOURCE_ID = "9a9e085f-3bc8-41df-b15f-be0daaf99e30"
SOURCE_YEAR = 2022

DB_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "family_project"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", "2009"),
}


def clean_number(value: Any) -> Optional[float]:
    if value is None:
        return None

    text = str(value).strip()

    if text == "" or text == "-":
        return None

    text = text.replace(",", "")

    try:
        return float(text)
    except ValueError:
        return None


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


def fetch_all_records() -> List[Dict[str, Any]]:
    records = []
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


def transform_row(row: Dict[str, Any]) -> Tuple[int, str, Optional[float], Optional[float], Optional[float], Optional[float], int]:
    settlement_id = clean_integer(row.get("LocalityCode"))

    if settlement_id is None:
        raise ValueError("Missing settlement_id")

    religion = row.get("religion")
    if religion is None or str(religion).strip() == "":
        raise ValueError("Missing religion")

    age0_19 = clean_number(row.get("age0_19_pcnt"))
    age20_64 = clean_number(row.get("age20_64_pcnt"))
    age65 = clean_number(row.get("age65_pcnt"))
    age_median = clean_number(row.get("age_median"))

    return (
        settlement_id,
        str(religion).strip(),
        age0_19,
        age20_64,
        age65,
        age_median,
        SOURCE_YEAR,
    )


def transform_rows(rows):
    deduped = {}
    errors = []

    for row in rows:
        try:
            transformed = transform_row(row)

            settlement_id = transformed[0]
            religion = transformed[1]

            key = (settlement_id, religion)

            # Keep the latest occurrence if the key repeats
            deduped[key] = transformed

        except Exception as exc:
            errors.append(str(exc))

    if errors:
        print(f"[WARN] skipped {len(errors)} bad rows")
        for err in errors[:10]:
            print(f"[WARN] {err}")

    print(f"[INFO] unique transformed rows {len(deduped)}")

    return list(deduped.values())


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS age_and_religion (
    settlement_id INTEGER NOT NULL,
    religion TEXT NOT NULL,
    age0_19_pcnt NUMERIC,
    age20_64_pcnt NUMERIC,
    age65_pcnt NUMERIC,
    age_median NUMERIC,
    source_year INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (settlement_id, religion)
);
"""

UPSERT_SQL = """
INSERT INTO age_and_religion (
    settlement_id,
    religion,
    age0_19_pcnt,
    age20_64_pcnt,
    age65_pcnt,
    age_median,
    source_year
)
VALUES %s
ON CONFLICT (settlement_id, religion)
DO UPDATE SET
    age0_19_pcnt = EXCLUDED.age0_19_pcnt,
    age20_64_pcnt = EXCLUDED.age20_64_pcnt,
    age65_pcnt = EXCLUDED.age65_pcnt,
    age_median = EXCLUDED.age_median,
    source_year = EXCLUDED.source_year,
    updated_at = CURRENT_TIMESTAMP;
"""


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def create_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


def load_rows(conn, rows: List[Tuple[int, str, Optional[float], Optional[float], Optional[float], Optional[float], int]]) -> None:
    if not rows:
        return

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=500)

    conn.commit()


def main() -> None:
    try:
        print("[INFO] starting ETL age_and_religion")

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