import os
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

from commute import get_commute
from config import load_env_file
from schemas import (
    CityCompareResultOut,
    CompareResponseOut,
    CostsOut,
    DataCompletenessOut,
    EducationOut,
    InputFamilySummary,
    InputSummaryOut,
    MetaOut,
    QualityOfLifeOut,
    RankDisplayOut,
    SafetyOut,
    SummaryOut,
    TaxesOut,
    TransportOut,
    WorkCommuteOut,
)

load_env_file()

LOCAL_TZ = ZoneInfo("Asia/Jerusalem")

DB_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "family_project"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", "2009"),
}

PRIVATE_CAR_COST_PER_KM = 0.70
ELECTRIC_CAR_COST_PER_KM = 0.30

PUBLIC_TRANSPORT_MONTHLY_0_40 = 255
PUBLIC_TRANSPORT_MONTHLY_40_74 = 410
PUBLIC_TRANSPORT_MONTHLY_75_PLUS = 610

AVERAGE_WEEKS_PER_MONTH = 4.33


def get_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def next_departure_timestamp(
    departure_hhmm: str,
    departure_date: str | None = None
) -> int:
    hh, mm = departure_hhmm.split(":")
    hour = int(hh)
    minute = int(mm)

    now = datetime.now(LOCAL_TZ)

    if departure_date:
        base_date = datetime.strptime(departure_date, "%Y-%m-%d").date()
        dt = datetime(
            year=base_date.year,
            month=base_date.month,
            day=base_date.day,
            hour=hour,
            minute=minute,
            tzinfo=LOCAL_TZ,
        )
    else:
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt < now:
            dt += timedelta(days=1)

    return int(dt.timestamp())


class DataRepo:
    ROOM_COLUMNS = {
        3: "rent_3_rooms",
        4: "rent_4_rooms",
        5: "rent_5_rooms",
    }
    SETTLEMENT_DISPLAY_NAMES = {
        3745: "בית יתיר (מצדות יהודה)",
    }
    SETTLEMENT_ALIASES = {
        3745: (
            "בית יתיר",
            "מצדות יהודה",
            "מצודות יהודה",
        ),
    }

    def __init__(self):
        self.tax_benefits_df = self._load_tax_benefits()
        self.crime_cluster_counts_df = self._load_crime_cluster_counts()
        self.rental_nadlan_df = self._load_rental_csv("rental_data_nadlan_2025.csv")
        self.rental_district_df = self._load_rental_csv("rental_data_2025.csv")

    @staticmethod
    def _normalize_hebrew(text: str) -> str:
        """Normalize common Hebrew spelling variations for fuzzy matching."""
        import re
        t = text.strip()
        # Remove maqaf (Hebrew hyphen) and regular hyphen
        t = t.replace("\u05BE", " ").replace("-", " ")
        # Collapse multiple spaces
        t = re.sub(r"\s+", " ", t)
        # Normalize double-yod spelling in Hebrew place names
        t = t.replace("יי", "י")
        return t

    @staticmethod
    def _normalize_hebrew(text: str) -> str:
        """Normalize common Hebrew spelling variations for fuzzy matching."""
        t = unicodedata.normalize("NFKD", text.strip().lower())
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        t = t.replace("\u05BE", " ").replace("-", " ").replace("'", " ").replace('"', " ")
        t = re.sub(
            r"(^|\s)\u05e7\u05e8\u05d9\u05ea(?=\s|$)",
            lambda match: f"{match.group(1)}\u05e7\u05e8\u05d9\u05d9\u05ea",
            t,
        )
        t = re.sub(r"\s+", " ", t)
        return t.strip()

    @classmethod
    def _fuzzy_hebrew_key(cls, text: str) -> str:
        """Build a looser key to tolerate missing or extra yod characters."""
        return cls._normalize_hebrew(text).replace("\u05d9", "")

    @classmethod
    def _query_match_variants(cls, query: str) -> list[tuple[int, str]]:
        normalized_query = cls._normalize_hebrew(query)
        if not normalized_query:
            return []

        variants: list[tuple[int, str]] = [(0, normalized_query)]
        seen = {normalized_query}

        tokens = normalized_query.split()
        for size in range(len(tokens) - 1, 0, -1):
            phrase = " ".join(tokens[:size])
            if phrase not in seen:
                seen.add(phrase)
                variants.append((1, phrase))

        for token in tokens:
            if token not in seen:
                seen.add(token)
                variants.append((2, token))

        return variants

    @classmethod
    def _get_display_name(cls, settlement_id: int, settlement_name: str | None = None) -> str:
        return cls.SETTLEMENT_DISPLAY_NAMES.get(settlement_id, settlement_name or "")

    @classmethod
    def _get_search_names(cls, settlement_id: int, settlement_name: str | None = None) -> list[str]:
        names: list[str] = []
        if settlement_name:
            names.append(settlement_name)

        display_name = cls.SETTLEMENT_DISPLAY_NAMES.get(settlement_id)
        if display_name:
            names.append(display_name)

        names.extend(cls.SETTLEMENT_ALIASES.get(settlement_id, ()))

        seen: set[str] = set()
        unique_names: list[str] = []
        for name in names:
            normalized = cls._normalize_hebrew(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_names.append(name)

        return unique_names

    @classmethod
    def _resolve_alias_settlement_id(cls, query: str) -> int | None:
        normalized_query = cls._normalize_hebrew(query)
        fuzzy_query = cls._fuzzy_hebrew_key(query)
        if not normalized_query:
            return None

        for settlement_id, aliases in cls.SETTLEMENT_ALIASES.items():
            for alias in aliases:
                if cls._normalize_hebrew(alias) == normalized_query:
                    return settlement_id
                if fuzzy_query and cls._fuzzy_hebrew_key(alias) == fuzzy_query:
                    return settlement_id

        return None

    @classmethod
    def _settlement_match_rank(cls, query: str, settlement_name: str) -> tuple[int, int] | None:
        normalized_name = cls._normalize_hebrew(settlement_name)
        if not normalized_name:
            return None

        best_rank: tuple[int, int] | None = None
        fuzzy_name = cls._fuzzy_hebrew_key(settlement_name)

        for variant_kind, variant in cls._query_match_variants(query):
            if normalized_name == variant:
                rank = (variant_kind * 10, 0)
            elif normalized_name.startswith(variant):
                rank = (variant_kind * 10 + 1, 0)
            else:
                token_index = normalized_name.find(f" {variant}")
                if token_index >= 0:
                    rank = (variant_kind * 10 + 2, token_index)
                else:
                    contains_index = normalized_name.find(variant)
                    if contains_index >= 0:
                        rank = (variant_kind * 10 + 3, contains_index)
                    else:
                        fuzzy_variant = cls._fuzzy_hebrew_key(variant)
                        if not fuzzy_variant or not fuzzy_name:
                            continue
                        if fuzzy_name == fuzzy_variant:
                            rank = (variant_kind * 10 + 4, 0)
                        elif fuzzy_name.startswith(fuzzy_variant):
                            rank = (variant_kind * 10 + 5, 0)
                        else:
                            fuzzy_index = fuzzy_name.find(fuzzy_variant)
                            if fuzzy_index < 0:
                                continue
                            rank = (variant_kind * 10 + 6, fuzzy_index)

            if best_rank is None or rank < best_rank:
                best_rank = rank

        return best_rank

    def search_settlements(self, query: str, limit: int = 15) -> list[dict]:
        """Return settlements whose name matches a substring with normalization-aware ranking."""
        normalized = self._normalize_hebrew(query)
        if not normalized:
            return []

        sql = """
            SELECT
                s.settlement_id,
                s.settlement_name,
                gi.population_total
            FROM settlements AS s
            LEFT JOIN general_info AS gi
                ON gi.settlement_id = s.settlement_id
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        results = []
        for row in rows:
            settlement_id = row["settlement_id"]
            search_names = self._get_search_names(settlement_id, row["settlement_name"])
            ranked_candidates = [
                rank
                for candidate_name in search_names
                if (rank := self._settlement_match_rank(normalized, candidate_name)) is not None
            ]
            if not ranked_candidates:
                continue
            rank = min(ranked_candidates)

            population = row["population_total"]
            display_name = self._get_display_name(settlement_id, row["settlement_name"])
            results.append((
                rank[0],
                rank[1],
                len(display_name),
                -(int(population) if population is not None else 0),
                display_name,
                {
                    "id": settlement_id,
                    "name": display_name,
                    "population": population,
                }
            ))

        results.sort(key=lambda item: item[:-1])
        return [item[-1] for item in results[:limit]]

    def get_general_info_by_city_name(self, city_name: str) -> dict | None:
        alias_match_settlement_id = self._resolve_alias_settlement_id(city_name)
        if alias_match_settlement_id is not None:
            alias_query = """
                SELECT
                    gi.settlement_id,
                    gi.settlement_name_he,
                    gi.population_total,
                    gi.population_jewish,
                    gi.district,
                    gi.source_year
                FROM general_info AS gi
                WHERE gi.settlement_id = %s
                LIMIT 1;
            """
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(alias_query, (alias_match_settlement_id,))
                    row = cur.fetchone()
                    if row:
                        result = dict(row)
                        result["display_name"] = self._get_display_name(
                            result["settlement_id"],
                            result["settlement_name_he"],
                        )
                        return result

        query = """
            SELECT
                gi.settlement_id,
                gi.settlement_name_he,
                gi.population_total,
                gi.population_jewish,
                gi.district,
                gi.source_year
            FROM general_info AS gi
            LEFT JOIN settlements AS s
                ON s.settlement_id = gi.settlement_id
            WHERE gi.settlement_name_he = %s
               OR s.settlement_name = %s
            LIMIT 1;
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (city_name, city_name))
                row = cur.fetchone()
                if row:
                    result = dict(row)
                    result["display_name"] = self._get_display_name(
                        result["settlement_id"],
                        result["settlement_name_he"],
                    )
                    return result

                normalized = self._normalize_hebrew(city_name)
                fuzzy = self._fuzzy_hebrew_key(city_name)
                if not normalized:
                    return None

                cur.execute(
                    """
                    SELECT
                        gi.settlement_id,
                        gi.settlement_name_he,
                        gi.population_total,
                        gi.population_jewish,
                        gi.district,
                        gi.source_year,
                        s.settlement_name
                    FROM general_info AS gi
                    LEFT JOIN settlements AS s
                        ON s.settlement_id = gi.settlement_id
                    """
                )
                rows = cur.fetchall()

        ranked_rows = []
        for candidate in rows:
            rank = self._settlement_match_rank(city_name, candidate["settlement_name_he"])
            if rank is None and candidate.get("settlement_name"):
                rank = self._settlement_match_rank(city_name, candidate["settlement_name"])

            if rank is None:
                candidate_fuzzy = self._fuzzy_hebrew_key(candidate["settlement_name_he"])
                settlement_fuzzy = self._fuzzy_hebrew_key(candidate.get("settlement_name") or "")
                if candidate_fuzzy == fuzzy or settlement_fuzzy == fuzzy:
                    rank = (6, 0)

            if rank is None:
                continue

            ranked_rows.append((
                rank[0],
                rank[1],
                len(candidate["settlement_name_he"]),
                candidate["settlement_name_he"],
                dict(candidate),
            ))

        if not ranked_rows:
            return None

        ranked_rows.sort(key=lambda item: item[:-1])
        result = ranked_rows[0][-1]
        result.pop("settlement_name", None)
        result["display_name"] = self._get_display_name(
            result["settlement_id"],
            result["settlement_name_he"],
        )
        return result

    def get_transport_by_settlement_id(self, settlement_id: int) -> dict | None:
        query = """
            SELECT
                settlement_id,
                private_cars_num,
                source_year
            FROM transport
            WHERE settlement_id = %s
            LIMIT 1;
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (settlement_id,))
                row = cur.fetchone()
        return dict(row) if row else None

    def get_households_by_settlement_id(self, settlement_id: int) -> dict | None:
        query = """
            SELECT
                settlement_id,
                total_population,
                households,
                source_year
            FROM households
            WHERE settlement_id = %s
            LIMIT 1;
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (settlement_id,))
                row = cur.fetchone()
        return dict(row) if row else None

    def get_age_and_religion_by_settlement_id(self, settlement_id: int) -> list[dict]:
        query = """
            SELECT
                settlement_id,
                religion,
                age0_19_pcnt,
                age20_64_pcnt,
                age65_pcnt,
                age_median,
                source_year
            FROM age_and_religion
            WHERE settlement_id = %s
            ORDER BY religion;
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (settlement_id,))
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_settlement_by_name(self, settlement_name: str) -> dict | None:
        alias_match_settlement_id = self._resolve_alias_settlement_id(settlement_name)
        if alias_match_settlement_id is not None:
            query = """
                    SELECT settlement_id,
                           settlement_name,
                           district,
                           source_year
                    FROM settlements
                    WHERE settlement_id = %s
                    LIMIT 1;
                    """
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (alias_match_settlement_id,))
                    row = cur.fetchone()

            if row:
                result = dict(row)
                result["settlement_name"] = self._get_display_name(
                    result["settlement_id"],
                    result["settlement_name"],
                )
                return result

        query = """
                SELECT settlement_id,
                       settlement_name,
                       district,
                       source_year
                FROM settlements
                WHERE settlement_name = %s
                LIMIT 1;
                """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (settlement_name,))
                row = cur.fetchone()

        if not row:
            return None

        result = dict(row)
        result["settlement_name"] = self._get_display_name(
            result["settlement_id"],
            result["settlement_name"],
        )
        return result

    def get_education_by_settlement_id(self, settlement_id: int) -> dict | None:
        query = """
            SELECT
                settlement_id,
                schools_total,
                schools_elementary,
                schools_secondary,
                schools_middle_schools,
                schools_high_schools,
                classes_elementary,
                classes_secondary,
                classes_middle_schools,
                classes_high_schools,
                students_elementary,
                students_secondary,
                students_middle_schools,
                students_high_schools,
                dropout_rate_total,
                bagrut_eligibility_rate,
                higher_education_entry_rate_8_years,
                avg_students_per_teacher,
                source_year
            FROM education
            WHERE settlement_id = %s
            LIMIT 1;
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (settlement_id,))
                row = cur.fetchone()

        return dict(row) if row else None

    def get_periphery_by_settlement_id(self, settlement_id: int) -> dict | None:
        query = """
            SELECT
                settlement_id,
                potential_accessibility_rank,
                peripherality_rank_2020,
                source_year
            FROM periphery
            WHERE settlement_id = %s
            LIMIT 1;
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (settlement_id,))
                row = cur.fetchone()

        return dict(row) if row else None

    def get_periphery_settlements_count(self) -> int:
        query = """
            SELECT COUNT(*) AS settlements_count
            FROM periphery;
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()

        return int(row["settlements_count"]) if row and row["settlements_count"] is not None else 0

    def get_social_economic_by_settlement_id(self, settlement_id: int) -> dict | None:
        query = """
            SELECT
                settlement_id,
                cluster_2021,
                source_year
            FROM social_economic
            WHERE settlement_id = %s
            LIMIT 1;
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (settlement_id,))
                row = cur.fetchone()

        return dict(row) if row else None

    def _load_crime_cluster_counts(self) -> pd.DataFrame:
        base_dir = Path(__file__).resolve().parent
        file_path = base_dir / "data" / "crime_statistics.csv"

        if not file_path.exists():
            return pd.DataFrame(
                columns=[
                    "settlement_id",
                    "cluster_1_count",
                    "cluster_2_count",
                    "cluster_3_count",
                ]
            )

        df = pd.read_csv(
            file_path,
            dtype={
                "YeshuvKod": "string",
                "StatisticGroupCluster": "Int64",
            },
        )

        required_columns = {"YeshuvKod", "StatisticGroupCluster"}
        missing = required_columns - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns in crime statistics file: {sorted(missing)}")

        df = df.copy()
        df["YeshuvKod"] = pd.to_numeric(df["YeshuvKod"], errors="coerce")
        df["StatisticGroupCluster"] = pd.to_numeric(df["StatisticGroupCluster"], errors="coerce")
        df = df.dropna(subset=["YeshuvKod", "StatisticGroupCluster"])
        df["YeshuvKod"] = df["YeshuvKod"].astype(int)
        df["StatisticGroupCluster"] = df["StatisticGroupCluster"].astype(int)

        counts_df = (
            df.groupby(["YeshuvKod", "StatisticGroupCluster"])
            .size()
            .unstack(fill_value=0)
            .rename_axis(index="settlement_id", columns="cluster")
            .reset_index()
        )

        for cluster in (1, 2, 3):
            if cluster not in counts_df.columns:
                counts_df[cluster] = 0

        return counts_df.rename(
            columns={
                1: "cluster_1_count",
                2: "cluster_2_count",
                3: "cluster_3_count",
            }
        )[
            ["settlement_id", "cluster_1_count", "cluster_2_count", "cluster_3_count"]
        ]

    def get_crime_cluster_counts_by_settlement_id(self, settlement_id: int) -> dict | None:
        match = self.crime_cluster_counts_df[
            self.crime_cluster_counts_df["settlement_id"] == settlement_id
        ]

        if match.empty:
            return None

        row = match.iloc[0]

        return {
            "settlement_id": int(row["settlement_id"]),
            "cluster_1_count": int(row["cluster_1_count"]),
            "cluster_2_count": int(row["cluster_2_count"]),
            "cluster_3_count": int(row["cluster_3_count"]),
        }

    def _load_tax_benefits(self) -> pd.DataFrame:
        base_dir = Path(__file__).resolve().parent
        file_path = base_dir / "data" / "mas_2026.xlsx"

        if not file_path.exists():
            return pd.DataFrame(
                columns=[
                    "settlement_id",
                    "settlement_name",
                    "tax_rate_2026",
                    "tax_ceiling_2026",
                ]
            )

        df = pd.read_excel(file_path)

        required_columns = {
            "settlement_id",
            "settlement_name",
            "tax_rate_2026",
            "tax_ceiling_2026",
        }

        missing = required_columns - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns in tax benefits file: {sorted(missing)}")

        df = df.copy()
        df["settlement_id"] = pd.to_numeric(df["settlement_id"], errors="coerce")
        df["tax_rate_2026"] = pd.to_numeric(df["tax_rate_2026"], errors="coerce")
        df["tax_ceiling_2026"] = pd.to_numeric(df["tax_ceiling_2026"], errors="coerce")
        df = df.dropna(subset=["settlement_id"])
        df["settlement_id"] = df["settlement_id"].astype(int)

        return df

    def get_tax_benefit_by_settlement_id(self, settlement_id: int) -> dict | None:
        match = self.tax_benefits_df[
            self.tax_benefits_df["settlement_id"] == settlement_id
            ]

        if match.empty:
            return None

        row = match.iloc[0]

        return {
            "settlement_id": int(row["settlement_id"]),
            "settlement_name": row["settlement_name"],
            "tax_rate_2026": None if pd.isna(row["tax_rate_2026"]) else float(row["tax_rate_2026"]),
            "tax_ceiling_2026": None if pd.isna(row["tax_ceiling_2026"]) else float(row["tax_ceiling_2026"]),
        }

    @staticmethod
    def _load_rental_csv(filename: str) -> pd.DataFrame:
        base_dir = Path(__file__).resolve().parent
        file_path = base_dir / "data" / filename

        if not file_path.exists():
            return pd.DataFrame(columns=["settlement_id", "rent_3_rooms", "rent_4_rooms", "rent_5_rooms"])

        df = pd.read_csv(file_path)
        df["settlement_id"] = pd.to_numeric(df["settlement_id"], errors="coerce")
        for col in ("rent_3_rooms", "rent_4_rooms", "rent_5_rooms"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["settlement_id"])
        df["settlement_id"] = df["settlement_id"].astype(int)
        return df

    def _lookup_rent(self, df: pd.DataFrame, lookup_id: int, room_col: str) -> float | None:
        match = df[df["settlement_id"] == lookup_id]
        if match.empty:
            return None
        value = match.iloc[0].get(room_col)
        if value is None or pd.isna(value):
            return None
        return float(value)

    def get_rent_for_settlement(
        self,
        settlement_id: int,
        district_code: int | None,
        desired_rooms: int,
    ) -> dict:
        room_col = self.ROOM_COLUMNS.get(desired_rooms)
        if not room_col:
            return {"rent": None, "source": None}

        nadlan_rent = self._lookup_rent(self.rental_nadlan_df, settlement_id, room_col)
        district_rent = None
        if district_code is not None:
            district_rent = self._lookup_rent(self.rental_district_df, district_code, room_col)

        if nadlan_rent is not None and district_rent is not None:
            chosen = max(nadlan_rent, district_rent)
            return {"rent": round(chosen, 2), "source": "both"}
        if nadlan_rent is not None:
            return {"rent": round(nadlan_rent, 2), "source": "rental_data_nadlan_2025"}
        if district_rent is not None:
            return {"rent": round(district_rent, 2), "source": "rental_data_2025"}
        return {"rent": None, "source": None}


def calculate_monthly_work_days(work_days_per_week: int) -> float:
    return round(work_days_per_week * AVERAGE_WEEKS_PER_MONTH, 2)


def safe_divide(numerator: int | float | None, denominator: int | float | None) -> float:
    if not numerator or not denominator:
        return 0.0

    return round(float(numerator) / float(denominator), 2)


def calculate_rate_per_1000(
    count: int | float | None,
    population_total: int | float | None,
) -> float:
    if not count or not population_total:
        return 0.0

    multiplier = 100 if float(population_total) < 1000 else 1000
    return round((float(count) / float(population_total)) * multiplier, 2)


def build_education_summary(education: dict | None) -> dict | None:
    if not education:
        return None

    return {
        "schools_total": education.get("schools_total"),
        "schools_elementary": education.get("schools_elementary"),
        "schools_secondary": education.get("schools_secondary"),
        "schools_middle_schools": education.get("schools_middle_schools"),
        "schools_high_schools": education.get("schools_high_schools"),
        "avg_students_per_class_elementary": safe_divide(
            education.get("students_elementary"),
            education.get("classes_elementary"),
        ),
        "avg_students_per_class_secondary": safe_divide(
            education.get("students_secondary"),
            education.get("classes_secondary"),
        ),
        "avg_students_per_class_middle_schools": safe_divide(
            education.get("students_middle_schools"),
            education.get("classes_middle_schools"),
        ),
        "avg_students_per_class_high_schools": safe_divide(
            education.get("students_high_schools"),
            education.get("classes_high_schools"),
        ),
        "dropout_rate_total": education.get("dropout_rate_total"),
        "bagrut_eligibility_rate": education.get("bagrut_eligibility_rate"),
        "higher_education_entry_rate_8_years": education.get("higher_education_entry_rate_8_years"),
        "avg_students_per_teacher": education.get("avg_students_per_teacher"),
        "source_year": education.get("source_year"),
    }


def build_age_and_religion_summary(age_and_religion_rows: list[dict] | None) -> list[dict]:
    if not age_and_religion_rows:
        return []

    return [
        {
            "religion": row.get("religion"),
            "age0_19_pcnt": row.get("age0_19_pcnt"),
            "age20_64_pcnt": row.get("age20_64_pcnt"),
            "age65_pcnt": row.get("age65_pcnt"),
            "age_median": row.get("age_median"),
            "source_year": row.get("source_year"),
        }
        for row in age_and_religion_rows
    ]


def calculate_average_cars_per_household(
    transport: dict | None,
    households_data: dict | None,
) -> float:
    average = safe_divide(
        transport.get("private_cars_num") if transport else None,
        households_data.get("households") if households_data else None,
    )

    if average <= 0:
        return 0

    return round(float(average), 2)


def format_rank_place(rank: int | None, total_settlements: int) -> dict | None:
    if rank is None:
        return None

    display_place = None
    percentile = 0
    if total_settlements > 0:
        display_place = total_settlements - rank + 1
        percentile = round((rank / total_settlements) * 100, 1)

    return {
        "rank": rank,
        "out_of": total_settlements,
        "display_place": display_place,
        "percentile": percentile,
        "summary": (
            f"place {display_place} out of {total_settlements}"
            if total_settlements > 0 else
            f"rank {rank}"
        ),
    }


def build_periphery_summary(
    periphery: dict | None,
    total_settlements: int,
) -> dict | None:
    if not periphery:
        return None

    return {
        "potential_accessibility_rank": format_rank_place(
            periphery.get("potential_accessibility_rank"),
            total_settlements,
        ),
        "peripherality_rank_2020": format_rank_place(
            periphery.get("peripherality_rank_2020"),
            total_settlements,
        ),
        "source_year": periphery.get("source_year"),
    }


def build_social_economic_summary(social_economic: dict | None) -> dict | None:
    if not social_economic:
        return None

    cluster_2021 = social_economic.get("cluster_2021")

    return {
        "cluster_2021": cluster_2021,
        "max_grade": 10,
        "summary": f"grade {cluster_2021} out of 10" if cluster_2021 is not None else None,
        "source_year": social_economic.get("source_year"),
    }


def build_crime_statistics_summary(
    crime_cluster_counts: dict | None,
    population_total: int | float | None,
) -> dict:
    crime_cluster_counts = crime_cluster_counts or {}

    cluster_1_count = crime_cluster_counts.get("cluster_1_count", 0)
    cluster_2_count = crime_cluster_counts.get("cluster_2_count", 0)
    cluster_3_count = crime_cluster_counts.get("cluster_3_count", 0)

    return {
        "cluster_1": {
            "count": cluster_1_count,
            "per_1000_residents": calculate_rate_per_1000(cluster_1_count, population_total),
        },
        "cluster_2": {
            "count": cluster_2_count,
            "per_1000_residents": calculate_rate_per_1000(cluster_2_count, population_total),
        },
        "cluster_3": {
            "count": cluster_3_count,
            "per_1000_residents": calculate_rate_per_1000(cluster_3_count, population_total),
        },
    }


def calculate_private_car_cost(distance_km: float, cost_per_km: float) -> dict:
    daily_cost = round(distance_km * 2 * cost_per_km, 2)
    return {
        "daily_cost": daily_cost,
    }


def calculate_public_transport_monthly_cost(distance_km: float) -> float:
    if distance_km < 0:
        raise ValueError("distance_km must be >= 0")

    if distance_km <= 40:
        return float(PUBLIC_TRANSPORT_MONTHLY_0_40)

    if distance_km <= 74:
        return float(PUBLIC_TRANSPORT_MONTHLY_40_74)

    return float(PUBLIC_TRANSPORT_MONTHLY_75_PLUS)


def calculate_commute_cost(
    commute_mode: str,
    distance_km: float,
    work_days_per_week: int,
) -> dict:
    monthly_work_days = calculate_monthly_work_days(work_days_per_week)

    if commute_mode == "private_car":
        base = calculate_private_car_cost(distance_km, PRIVATE_CAR_COST_PER_KM)
        monthly_cost = round(base["daily_cost"] * monthly_work_days, 2)
        return {
            "daily_cost": base["daily_cost"],
            "monthly_cost": monthly_cost,
        }

    if commute_mode == "electric_car":
        base = calculate_private_car_cost(distance_km, ELECTRIC_CAR_COST_PER_KM)
        monthly_cost = round(base["daily_cost"] * monthly_work_days, 2)
        return {
            "daily_cost": base["daily_cost"],
            "monthly_cost": monthly_cost,
        }

    if commute_mode == "work_car":
        return {
            "daily_cost": 0.0,
            "monthly_cost": 0.0,
        }

    if commute_mode == "public_transport":
        monthly_cost = calculate_public_transport_monthly_cost(distance_km)
        daily_cost = round(monthly_cost / monthly_work_days, 2) if monthly_work_days > 0 else 0.0
        return {
            "daily_cost": daily_cost,
            "monthly_cost": monthly_cost,
        }

    raise ValueError(f"Unsupported commute mode: {commute_mode}")

def normalize_tax_rate(rate_value: float | None) -> float:
    if rate_value is None:
        return 0.0

    # Source files sometimes store 11 instead of 0.11
    if rate_value > 1:
        return rate_value / 100

    return rate_value


def calculate_tax_benefit_for_income(
    monthly_income: float | None,
    tax_rate: float | None,
    tax_ceiling: float | None,
) -> dict:
    if monthly_income is None or monthly_income <= 0:
        return {
            "monthly_income": monthly_income,
            "annual_income": 0.0,
            "eligible_income": 0.0,
            "benefit_annual": 0.0,
            "benefit_monthly_estimated": 0.0,
        }

    annual_income = float(monthly_income) * 12
    normalized_rate = normalize_tax_rate(tax_rate)

    if tax_ceiling is None or tax_ceiling <= 0:
        eligible_income = annual_income
    else:
        eligible_income = min(annual_income, float(tax_ceiling))

    benefit_annual = eligible_income * normalized_rate

    return {
        "monthly_income": round(float(monthly_income), 2),
        "annual_income": round(annual_income, 2),
        "eligible_income": round(eligible_income, 2),
        "benefit_annual": round(benefit_annual, 2),
        "benefit_monthly_estimated": round(benefit_annual / 12, 2),
    }


def calculate_family_tax_benefit(
    family: dict,
    tax_benefit_info: dict | None,
) -> dict:
    if not tax_benefit_info:
        return {
            "tax_rate_2026": None,
            "tax_ceiling_2026": None,
            "parent1": calculate_tax_benefit_for_income(None, None, None),
            "parent2": calculate_tax_benefit_for_income(None, None, None),
            "total_benefit_annual": 0.0,
            "total_benefit_monthly_estimated": 0.0,
        }

    tax_rate = tax_benefit_info.get("tax_rate_2026")
    tax_ceiling = tax_benefit_info.get("tax_ceiling_2026")

    parent1_result = calculate_tax_benefit_for_income(
        monthly_income=family.get("parent1_income"),
        tax_rate=tax_rate,
        tax_ceiling=tax_ceiling,
    )

    parent2_result = calculate_tax_benefit_for_income(
        monthly_income=family.get("parent2_income"),
        tax_rate=tax_rate,
        tax_ceiling=tax_ceiling,
    )

    total_benefit_annual = (
        parent1_result["benefit_annual"] + parent2_result["benefit_annual"]
    )

    return {
        "tax_rate_2026": tax_rate,
        "tax_ceiling_2026": tax_ceiling,
        "parent1": parent1_result,
        "parent2": parent2_result,
        "total_benefit_annual": round(total_benefit_annual, 2),
        "total_benefit_monthly_estimated": round(total_benefit_annual / 12, 2),
    }

def calculate_parent_commute(
    city_name: str,
    parent: dict,
    departure_date: str | None = None,
) -> dict:
    departure_ts = None

    if parent.get("departure_time"):
        departure_ts = next_departure_timestamp(
            parent["departure_time"],
            departure_date=departure_date,
        )

    commute = get_commute(
        city_name,
        parent["work_address"],
        commute_mode=parent["commute_mode"],
        departure_time=departure_ts,
    )

    distance_km = commute.get("distance_km")
    cost = {
        "daily_cost": None,
        "monthly_cost": None,
    }
    if distance_km is not None:
        cost = calculate_commute_cost(
            commute_mode=parent["commute_mode"],
            distance_km=distance_km,
            work_days_per_week=parent["work_days_per_week"],
        )


    return {
        "work_address": parent["work_address"],
        "commute_mode": parent.get("commute_mode"),
        "departure_time": parent.get("departure_time"),
        "work_days_per_week": parent.get("work_days_per_week"),
        "commute": commute,
        "cost": cost,
    }

def calculate_city_data(
    city: str,
    family: dict,
    parent1: dict,
    repo: DataRepo,
    parent2: dict | None = None,
    departure_date: str | None = None,
) -> dict:
    general_info = repo.get_general_info_by_city_name(city)
    if not general_info:
        raise ValueError(f"City '{city}' not found in general_info table")

    settlement_id = general_info["settlement_id"]

    parent1_commute = calculate_parent_commute(
        city_name=general_info["settlement_name_he"],
        parent=parent1,
        departure_date=departure_date,
    )

    parent2_commute = None
    if parent2:
        parent2_commute = calculate_parent_commute(
            city_name=general_info["settlement_name_he"],
            parent=parent2,
            departure_date=departure_date,
        )

    total_daily_cost = parent1_commute["cost"]["daily_cost"]
    total_monthly_cost = parent1_commute["cost"]["monthly_cost"]

    if parent2_commute:
        if total_daily_cost is None or parent2_commute["cost"]["daily_cost"] is None:
            total_daily_cost = None
        else:
            total_daily_cost += parent2_commute["cost"]["daily_cost"]

        if total_monthly_cost is None or parent2_commute["cost"]["monthly_cost"] is None:
            total_monthly_cost = None
        else:
            total_monthly_cost += parent2_commute["cost"]["monthly_cost"]

    transport = repo.get_transport_by_settlement_id(settlement_id)
    households_data = repo.get_households_by_settlement_id(settlement_id)
    age_and_religion_rows = repo.get_age_and_religion_by_settlement_id(settlement_id)
    education = repo.get_education_by_settlement_id(settlement_id)
    periphery = repo.get_periphery_by_settlement_id(settlement_id)
    periphery_settlements_count = repo.get_periphery_settlements_count()
    social_economic = repo.get_social_economic_by_settlement_id(settlement_id)
    crime_cluster_counts = repo.get_crime_cluster_counts_by_settlement_id(settlement_id)
    tax_benefit_info = repo.get_tax_benefit_by_settlement_id(settlement_id)
    family_tax_benefit = calculate_family_tax_benefit(
        family=family,
        tax_benefit_info=tax_benefit_info,
    )

    desired_rooms = family.get("desired_rooms")
    district_code = general_info.get("district")
    rent_result = {"rent": None, "source": None}
    if desired_rooms is not None:
        rent_result = repo.get_rent_for_settlement(
            settlement_id=settlement_id,
            district_code=district_code,
            desired_rooms=desired_rooms,
        )

    rent_monthly = rent_result["rent"]

    total_monthly_expenses = 0.0
    has_any_cost = False

    if total_monthly_cost is not None:
        total_monthly_expenses += total_monthly_cost
        has_any_cost = True
    if rent_monthly is not None:
        total_monthly_expenses += rent_monthly
        has_any_cost = True

    return {
        "city": general_info.get("display_name") or general_info["settlement_name_he"],
        "settlement_id": settlement_id,
        "district_code": district_code,
        "family": {
            "parent1_income": family.get("parent1_income"),
            "parent2_income": family.get("parent2_income"),
            "desired_rooms": desired_rooms,
            "children": family.get("children", []),
        },
        "rent_monthly": rent_monthly,
        "rent_source": rent_result["source"],
        "parent1_commute": parent1_commute,
        "parent2_commute": parent2_commute,
        "age_and_religion": build_age_and_religion_summary(age_and_religion_rows),
        "education": build_education_summary(education),
        "periphery": build_periphery_summary(periphery, periphery_settlements_count),
        "social_economic": build_social_economic_summary(social_economic),
        "crime_statistics": build_crime_statistics_summary(
            crime_cluster_counts,
            general_info.get("population_total"),
        ),
        "average_cars_per_household": calculate_average_cars_per_household(
            transport,
            households_data,
        ),
        "total_commute_cost_daily": round(total_daily_cost, 2) if total_daily_cost is not None else None,
        "total_commute_cost_monthly": round(total_monthly_cost, 2) if total_monthly_cost is not None else None,
        "total_monthly_expenses": round(total_monthly_expenses, 2) if has_any_cost else None,
        "family_tax_benefit": family_tax_benefit
    }


def build_work_commute_output(parent_commute: dict | None) -> WorkCommuteOut:
    if not parent_commute:
        return WorkCommuteOut()

    commute = parent_commute.get("commute") or {}
    return WorkCommuteOut(
        duration_min=commute.get("duration_min"),
        distance_km=commute.get("distance_km"),
        mode=parent_commute.get("commute_mode"),
        monthly_cost=(parent_commute.get("cost") or {}).get("monthly_cost"),
        status=commute.get("status") or "missing",
    )


def pick_primary_age_group(age_and_religion: list[dict] | None) -> dict:
    if not age_and_religion:
        return {}

    return age_and_religion[0]


def build_summary_output(city_data: dict) -> SummaryOut:
    highlights: list[str] = []
    warnings: list[str] = []

    parent1_status = ((city_data.get("parent1_commute") or {}).get("commute") or {}).get("status")
    parent2_status = ((city_data.get("parent2_commute") or {}).get("commute") or {}).get("status")
    commute_ok = parent1_status == "OK" or parent2_status == "OK"
    if commute_ok:
        monthly_cost = city_data.get("total_commute_cost_monthly")
        if monthly_cost is not None:
            highlights.append(f"Monthly commute estimate: {monthly_cost} ILS")
    else:
        warnings.append("Commute data is partial or unavailable.")

    rent_monthly = city_data.get("rent_monthly")
    if rent_monthly is not None:
        highlights.append(f"Monthly rent estimate: {rent_monthly} ILS")
    else:
        warnings.append("Rent data is unavailable for this city.")

    tax_benefit = ((city_data.get("family_tax_benefit") or {}).get("total_benefit_monthly_estimated"))
    if tax_benefit:
        highlights.append(f"Estimated monthly tax benefit: {tax_benefit} ILS")
    else:
        warnings.append("Tax benefit data is unavailable or zero for the provided income.")

    if not city_data.get("education"):
        warnings.append("Education data is missing.")

    return SummaryOut(highlights=highlights, warnings=warnings)


def build_data_completeness_output(city_data: dict) -> DataCompletenessOut:
    categories = {
        "rent": city_data.get("rent_monthly") is not None,
        "commute": city_data.get("total_commute_cost_monthly") is not None,
        "education": city_data.get("education") is not None,
        "quality_of_life": any(
            [
                city_data.get("periphery") is not None,
                city_data.get("social_economic") is not None,
                bool(city_data.get("age_and_religion")),
                city_data.get("average_cars_per_household") is not None,
            ]
        ),
        "taxes": city_data.get("family_tax_benefit") is not None,
        "safety": city_data.get("crime_statistics") is not None,
    }
    ready_fields = sum(1 for ready in categories.values() if ready)
    missing_categories = [name for name, ready in categories.items() if not ready]
    missing_fields = len(categories) - ready_fields
    completion_percent = round((ready_fields / len(categories)) * 100, 1) if categories else 0.0

    return DataCompletenessOut(
        ready_fields=ready_fields,
        missing_fields=missing_fields,
        completion_percent=completion_percent,
        missing_categories=missing_categories,
    )


def map_rank_display(rank_data: dict | None) -> RankDisplayOut | None:
    if not rank_data:
        return None

    return RankDisplayOut(
        value=rank_data.get("rank", rank_data.get("cluster_2021")),
        out_of=rank_data.get("out_of", rank_data.get("max_grade")),
        display_place=rank_data.get("display_place"),
        percentile=rank_data.get("percentile"),
        summary=rank_data.get("summary"),
    )


def map_city_result(city_data: dict) -> CityCompareResultOut:
    primary_age_group = pick_primary_age_group(city_data.get("age_and_religion"))
    periphery = city_data.get("periphery") or {}
    social_economic = city_data.get("social_economic") or {}
    crime_statistics = city_data.get("crime_statistics") or {}
    family_tax_benefit = city_data.get("family_tax_benefit") or {}

    parent1_commute = build_work_commute_output(city_data.get("parent1_commute"))
    parent2_commute = build_work_commute_output(city_data.get("parent2_commute"))

    cluster_1 = (crime_statistics.get("cluster_1") or {}).get("per_1000_residents")
    cluster_2 = (crime_statistics.get("cluster_2") or {}).get("per_1000_residents")
    cluster_3 = (crime_statistics.get("cluster_3") or {}).get("per_1000_residents")
    cluster_values = [value for value in [cluster_1, cluster_2, cluster_3] if value is not None]
    parent1_income = city_data.get("family", {}).get("parent1_income") or 0.0
    parent2_income = city_data.get("family", {}).get("parent2_income") or 0.0

    return CityCompareResultOut(
        city=city_data["city"],
        settlement_id=city_data.get("settlement_id"),
        district_code=city_data.get("district_code"),
        desired_rooms=city_data.get("family", {}).get("desired_rooms"),
        rent_source=city_data.get("rent_source"),
        costs=CostsOut(
            rent_monthly=city_data.get("rent_monthly"),
            commute_monthly=city_data.get("total_commute_cost_monthly"),
            total_monthly=city_data.get("total_monthly_expenses"),
        ),
        transport=TransportOut(
            parent1_work_commute=parent1_commute,
            parent2_work_commute=parent2_commute if city_data.get("parent2_commute") else None,
            govmap_available=False,
        ),
        education=EducationOut(**(city_data.get("education") or {})),
        quality_of_life=QualityOfLifeOut(
            potential_accessibility_rank=map_rank_display(periphery.get("potential_accessibility_rank")),
            peripherality_rank_2020=map_rank_display(periphery.get("peripherality_rank_2020")),
            social_economic_cluster_2021=map_rank_display(social_economic),
            average_cars_per_household=city_data.get("average_cars_per_household"),
            religion=primary_age_group.get("religion"),
            age0_19_pcnt=primary_age_group.get("age0_19_pcnt"),
            age20_64_pcnt=primary_age_group.get("age20_64_pcnt"),
            age65_pcnt=primary_age_group.get("age65_pcnt"),
            age_median=primary_age_group.get("age_median"),
        ),
        taxes=TaxesOut(
            total_family_income_monthly=round(parent1_income + parent2_income, 2),
            tax_ceiling_annual=family_tax_benefit.get("tax_ceiling_2026"),
            tax_benefit_annual=family_tax_benefit.get("total_benefit_annual"),
            tax_benefit_monthly=family_tax_benefit.get("total_benefit_monthly_estimated"),
            tax_benefit_percent=normalize_tax_rate(family_tax_benefit.get("tax_rate_2026")),
        ),
        safety=SafetyOut(
            crime_index=round(sum(cluster_values), 2) if cluster_values else None,
            cluster_1_per_1000=cluster_1,
            cluster_2_per_1000=cluster_2,
            cluster_3_per_1000=cluster_3,
        ),
        summary=build_summary_output(city_data),
        data_completeness=build_data_completeness_output(city_data),
    )


def build_compare_response(
    cities: list[str],
    family: dict,
    raw_results: list[dict],
) -> CompareResponseOut:
    display_cities = [city_data.get("city") or city for city_data, city in zip(raw_results, cities)]
    if len(raw_results) < len(cities):
        display_cities.extend(cities[len(raw_results):])

    return CompareResponseOut(
        meta=MetaOut(
            comparison_type="city_compare",
            generated_at=datetime.now(LOCAL_TZ).isoformat(),
        ),
        input_summary=InputSummaryOut(
            cities=display_cities,
            family=InputFamilySummary(
                parent1_income=family.get("parent1_income"),
                parent2_income=family.get("parent2_income"),
                desired_rooms=family.get("desired_rooms"),
                children_count=len(family.get("children", [])),
            ),
        ),
        results=[map_city_result(city_data) for city_data in raw_results],
    )


def compare_cities(
    cities: list[str],
    family: dict,
    parent1: dict,
    repo: DataRepo,
    parent2: dict | None = None,
    departure_date: str | None = None,
) -> dict:
    results = [
        calculate_city_data(
            city=c,
            family=family,
            parent1=parent1,
            parent2=parent2,
            repo=repo,
            departure_date=departure_date,
        )
        for c in cities
    ]

    return build_compare_response(
        cities=cities,
        family=family,
        raw_results=results,
    ).model_dump()
