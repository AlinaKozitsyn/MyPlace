import os

import psycopg2
from psycopg2.extras import RealDictCursor


DB_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "family_project"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", "2009"),
}


QUERIES = [
    (
        "Distinct StatisticType count",
        """
        SELECT COUNT(DISTINCT "StatisticType") AS distinct_statistic_type_count
        FROM crime_statistics;
        """,
    ),
    (
        "Distinct StatisticType list",
        """
        SELECT DISTINCT "StatisticType"
        FROM crime_statistics
        ORDER BY "StatisticType";
        """,
    ),
    (
        "Combined summary",
        """
        SELECT
            COUNT(DISTINCT "StatisticType") AS distinct_statistic_type_count,
            ARRAY_AGG(DISTINCT "StatisticType" ORDER BY "StatisticType") AS statistic_types
        FROM crime_statistics;
        """,
    ),
]


def main() -> None:
    with psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            for title, query in QUERIES:
                print(f"\n=== {title} ===")
                cur.execute(query)
                rows = cur.fetchall()
                for row in rows:
                    print(dict(row))


if __name__ == "__main__":
    main()
