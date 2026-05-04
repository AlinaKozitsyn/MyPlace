import os
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values


DB_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "family_project"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", "2009"),
}

EXCLUDED_STATISTIC_TYPE_CODES = {
    "407", "1106", "10035", "10015", "10014", "10030", "10019", "10020", "10012",
    "10021", "10004", "10009", "10022", "201", "802", "801", "727", "10029", "1005",
    "10006", "10037", "10039", "10010", "10001", "10002", "1103", "726", "804",
    "10034", "10028", "10018", "1300", "222", "207", "211", "1003", "10033", "900",
    "600", "1000", "1002", "220", "902", "1100", "10031", "1107", "10003", "10013",
    "1102", "903", "1200", "-1", "10026",
}

STATISTIC_GROUP_CLUSTER_MAP = {
    "500": 1,
    "100": 1,
    "300": 1,
    "400": 1,
    "900": 2,
    "700": 2,
    "800": 2,
    "600": 3,
    "200": 3,
    "1100": 3,
    "10000": 3,
}


def load_and_filter_crime_statistics(csv_path: Path) -> tuple[pd.DataFrame, int, int]:
    df = pd.read_csv(
        csv_path,
        dtype={
            "StatisticTypeKod": "string",
            "StatisticGroupKod": "string",
        },
    )
    statistic_type_kod_column = "StatisticTypeKod"
    statistic_group_kod_column = "StatisticGroupKod"
    cluster_column = "StatisticGroupCluster"
    required_columns = ["StatisticTypeKod", "StatisticGroupKod", "Yeshuv", "YeshuvKod"]

    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    before_count = int(df.shape[0])
    filtered_df = df.copy()
    filtered_df["Yeshuv"] = filtered_df["Yeshuv"].fillna("").astype(str).str.strip()
    filtered_df["YeshuvKod"] = filtered_df["YeshuvKod"].fillna("").astype(str).str.strip()
    filtered_df[statistic_group_kod_column] = (
        filtered_df[statistic_group_kod_column].fillna("").astype(str).str.strip()
    )

    filtered_df = filtered_df.loc[
        ~filtered_df[statistic_type_kod_column].fillna("").isin(EXCLUDED_STATISTIC_TYPE_CODES)
    ]
    filtered_df = filtered_df.loc[filtered_df["Yeshuv"] != ""]
    filtered_df = filtered_df.loc[filtered_df["YeshuvKod"] != ""]
    filtered_df = filtered_df.copy()
    filtered_df[cluster_column] = (
        filtered_df[statistic_group_kod_column]
        .map(STATISTIC_GROUP_CLUSTER_MAP)
        .astype("Int64")
    )
    after_count = int(filtered_df.shape[0])

    filtered_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    return filtered_df, before_count, after_count


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    csv_path = base_dir / "data" / "crime_statistics.csv"

    df, before_count, after_count = load_and_filter_crime_statistics(csv_path)
    statistic_type_column = "StatisticType"

    if statistic_type_column not in df.columns:
        raise ValueError(f"Missing required column: {statistic_type_column}")

    distinct_series = (
        df[statistic_type_column]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: s != ""]
        .drop_duplicates()
        .sort_values()
        .reset_index(drop=True)
    )
    distinct_df = distinct_series.to_frame(name=statistic_type_column)
    summary_count = int(distinct_df.shape[0])

    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS crime_statistics_statistic_types (
                    statistic_type TEXT PRIMARY KEY
                );
                """,
            )
            cur.execute("TRUNCATE TABLE crime_statistics_statistic_types;")
            if not distinct_df.empty:
                execute_values(
                    cur,
                    """
                    INSERT INTO crime_statistics_statistic_types (statistic_type)
                    VALUES %s
                    """,
                    [(value,) for value in distinct_df[statistic_type_column].tolist()],
                )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS crime_statistics_statistic_type_summary (
                    id INTEGER PRIMARY KEY,
                    distinct_statistic_type_count INTEGER NOT NULL
                );
                """
            )
            cur.execute(
                """
                INSERT INTO crime_statistics_statistic_type_summary (id, distinct_statistic_type_count)
                VALUES (1, %s)
                ON CONFLICT (id) DO UPDATE SET
                    distinct_statistic_type_count = EXCLUDED.distinct_statistic_type_count;
                """,
                (summary_count,),
            )

        conn.commit()

    print("=== Distinct StatisticType count ===")
    print(summary_count)

    print("\n=== CSV filter summary ===")
    print(f"rows before filter: {before_count}")
    print(f"rows after filter: {after_count}")
    print(f"rows removed: {before_count - after_count}")

    print("\n=== Distinct StatisticType list ===")
    for value in distinct_series.tolist():
        print(value)

    print("\n=== Tables updated ===")
    print("crime_statistics_statistic_types")
    print("crime_statistics_statistic_type_summary")


if __name__ == "__main__":
    main()
