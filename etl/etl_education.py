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
SOURCE_YEAR = 2023
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
    "בתי ספר סה\"כ תשפ\"ג 2022/23": "schools_total",
    "בתי ספר יסודיים תשפ\"ג 2022/23": "schools_elementary",
    "בתי ספר על-יסודיים תשפ\"ג 2022/23": "schools_secondary",
    "בתי ספר חטיבות ביניים תשפ\"ג 2022/23": "schools_middle_schools",
    "בתי ספר תיכוניים תשפ\"ג 2022/23": "schools_high_schools",
    "כיתות סה\"כ תשפ\"ג 2022/23": "classes_total",
    "כיתות בבתי ספר יסודיים תשפ\"ג 2022/23": "classes_elementary",
    "כיתות בבתי ספר על-יסודיים תשפ\"ג 2022/23": "classes_secondary",
    "כיתות בחטיבות ביניים תשפ\"ג 2022/23": "classes_middle_schools",
    "כיתות בבתי ספר תיכוניים תשפ\"ג 2022/23": "classes_high_schools",
    "תלמידים סה\"כ תשפ\"ג 2022/23": "students_total",
    "תלמידים בבתי ספר יסודיים תשפ\"ג 2022/23": "students_elementary",
    "תלמידים בבתי ספר על-יסודיים תשפ\"ג 2022/23": "students_secondary",
    "תלמידים בחטיבות ביניים תשפ\"ג 2022/23": "students_middle_schools",
    "תלמידים בבתי ספר תיכוניים תשפ\"ג 2022/23": "students_high_schools",
    "אחוז תלמידים נושרים סה\"כ תשפ\"ג 2022/23": "dropout_rate_total",
    "אחוז זכאים לתעודת בגרות מבין תלמידי כיתות יב תשפ\"ג 2022/23": "bagrut_eligibility_rate",
    "השכלה גבוהה אחוז הנכנסים להשכלה גבוהה בתוך 8 שנים בקרב תלמידי יב תשפ\"ד 2023/24": "higher_education_entry_rate_8_years",
    "עובדי הוראה ממוצע תלמידים למורה": "avg_students_per_teacher",
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
        "subject": "LAHinuh",
    }


def fetch_page(session: requests.Session, page_number: int) -> Dict[str, Any]:
    response = session.get(API_BASE_URL, params=build_params(page_number), timeout=60)
    response.raise_for_status()
    return response.json()


def build_column_id_map(columns: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Builds mapping:
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
            "User-Agent": "etl-education/1.0",
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

def transform_row(row: Dict[str, Any], column_id_map: Dict[str, str]) -> Tuple[
    int,
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    int,
]:
    settlement_id = clean_integer(row.get(column_id_map["סמל היישוב"]))

    if settlement_id is None:
        raise ValueError(f"Missing settlement_id in row: {row}")

    return (
        settlement_id,
        clean_integer(row.get(column_id_map["בתי ספר סה\"כ תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["בתי ספר יסודיים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["בתי ספר על-יסודיים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["בתי ספר חטיבות ביניים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["בתי ספר תיכוניים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["כיתות סה\"כ תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["כיתות בבתי ספר יסודיים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["כיתות בבתי ספר על-יסודיים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["כיתות בחטיבות ביניים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["כיתות בבתי ספר תיכוניים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["תלמידים סה\"כ תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["תלמידים בבתי ספר יסודיים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["תלמידים בבתי ספר על-יסודיים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["תלמידים בחטיבות ביניים תשפ\"ג 2022/23"])),
        clean_integer(row.get(column_id_map["תלמידים בבתי ספר תיכוניים תשפ\"ג 2022/23"])),
        clean_number(row.get(column_id_map["אחוז תלמידים נושרים סה\"כ תשפ\"ג 2022/23"])),
        clean_number(row.get(column_id_map["אחוז זכאים לתעודת בגרות מבין תלמידי כיתות יב תשפ\"ג 2022/23"])),
        clean_number(row.get(column_id_map["השכלה גבוהה אחוז הנכנסים להשכלה גבוהה בתוך 8 שנים בקרב תלמידי יב תשפ\"ד 2023/24"])),
        clean_number(row.get(column_id_map["עובדי הוראה ממוצע תלמידים למורה"])),
        SOURCE_YEAR,
    )


def transform_rows(
    rows: List[Dict[str, Any]],
    column_id_map: Dict[str, str],
) -> List[Tuple]:
    transformed = []
    errors = []

    for row in rows:
        try:
            transformed.append(transform_row(row, column_id_map))
        except Exception as exc:
            errors.append((row, str(exc)))

    if errors:
        print(f"[WARN] {len(errors)} rows failed transformation.")
        for bad_row, err in errors[:10]:
            print(f"[WARN] Error: {err} | Row: {bad_row}")

    print(f"[INFO] Successfully transformed {len(transformed)} rows.")
    return transformed


# =====================================
# SQL
# =====================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS education (
    settlement_id INTEGER PRIMARY KEY,
    schools_total INTEGER,
    schools_elementary INTEGER,
    schools_secondary INTEGER,
    schools_middle_schools INTEGER,
    schools_high_schools INTEGER,
    classes_total INTEGER,
    classes_elementary INTEGER,
    classes_secondary INTEGER,
    classes_middle_schools INTEGER,
    classes_high_schools INTEGER,
    students_total INTEGER,
    students_elementary INTEGER,
    students_secondary INTEGER,
    students_middle_schools INTEGER,
    students_high_schools INTEGER,
    dropout_rate_total NUMERIC,
    bagrut_eligibility_rate NUMERIC,
    higher_education_entry_rate_8_years NUMERIC,
    avg_students_per_teacher NUMERIC,
    source_year INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

UPSERT_SQL = """
INSERT INTO education (
    settlement_id,
    schools_total,
    schools_elementary,
    schools_secondary,
    schools_middle_schools,
    schools_high_schools,
    classes_total,
    classes_elementary,
    classes_secondary,
    classes_middle_schools,
    classes_high_schools,
    students_total,
    students_elementary,
    students_secondary,
    students_middle_schools,
    students_high_schools,
    dropout_rate_total,
    bagrut_eligibility_rate,
    higher_education_entry_rate_8_years,
    avg_students_per_teacher,
    source_year
)
VALUES %s
ON CONFLICT (settlement_id)
DO UPDATE SET
    schools_total = EXCLUDED.schools_total,
    schools_elementary = EXCLUDED.schools_elementary,
    schools_secondary = EXCLUDED.schools_secondary,
    schools_middle_schools = EXCLUDED.schools_middle_schools,
    schools_high_schools = EXCLUDED.schools_high_schools,
    classes_total = EXCLUDED.classes_total,
    classes_elementary = EXCLUDED.classes_elementary,
    classes_secondary = EXCLUDED.classes_secondary,
    classes_middle_schools = EXCLUDED.classes_middle_schools,
    classes_high_schools = EXCLUDED.classes_high_schools,
    students_total = EXCLUDED.students_total,
    students_elementary = EXCLUDED.students_elementary,
    students_secondary = EXCLUDED.students_secondary,
    students_middle_schools = EXCLUDED.students_middle_schools,
    students_high_schools = EXCLUDED.students_high_schools,
    dropout_rate_total = EXCLUDED.dropout_rate_total,
    bagrut_eligibility_rate = EXCLUDED.bagrut_eligibility_rate,
    higher_education_entry_rate_8_years = EXCLUDED.higher_education_entry_rate_8_years,
    avg_students_per_teacher = EXCLUDED.avg_students_per_teacher,
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


def load_rows(conn, rows: List[Tuple]) -> None:
    if not rows:
        print("[INFO] No rows to load.")
        return

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=500)

    conn.commit()
    print(f"[INFO] Loaded {len(rows)} rows into education.")


# =====================================
# MAIN
# =====================================

def main() -> None:
    try:
        print("[INFO] starting ETL education")

        raw_rows, column_id_map = fetch_all_records()
        print(f"[INFO] raw rows {len(raw_rows)}")

        transformed_rows = transform_rows(raw_rows, column_id_map)
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