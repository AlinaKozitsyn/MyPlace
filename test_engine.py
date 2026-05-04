import unittest
from unittest.mock import patch

from engine import (
    DataRepo,
    build_compare_response,
    calculate_average_cars_per_household,
    calculate_parent_commute,
)


class EngineResponseTests(unittest.TestCase):
    def test_average_cars_per_household_preserves_fractional_value(self):
        self.assertEqual(
            calculate_average_cars_per_household(
                {"private_cars_num": 1237},
                {"households": 1000},
            ),
            1.24,
        )

    def test_average_cars_per_household_keeps_values_below_one(self):
        self.assertEqual(
            calculate_average_cars_per_household(
                {"private_cars_num": 98},
                {"households": 100},
            ),
            0.98,
        )

    def test_query_match_variants_keep_progressive_prefixes_before_single_tokens(self):
        self.assertEqual(
            DataRepo._query_match_variants("טנא עומרים מרכז"),
            [
                (0, "טנא עומרים מרכז"),
                (1, "טנא עומרים"),
                (1, "טנא"),
                (2, "עומרים"),
                (2, "מרכז"),
            ],
        )

    def test_search_settlements_returns_alias_match_once_with_display_name(self):
        repo = DataRepo.__new__(DataRepo)

        class FakeCursor:
            def execute(self, *_args, **_kwargs):
                return None

            def fetchall(self):
                return [
                    {
                        "settlement_id": 3745,
                        "settlement_name": "בית יתיר",
                        "population_total": 987,
                    }
                ]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("engine.get_connection", return_value=FakeConnection()):
            results = repo.search_settlements("מצודות יהודה")

        self.assertEqual(results, [{
            "id": 3745,
            "name": "בית יתיר (מצדות יהודה)",
            "population": 987,
        }])

    def test_settlement_alias_registry_resolves_all_supported_spellings(self):
        self.assertEqual(DataRepo._resolve_alias_settlement_id("בית יתיר"), 3745)
        self.assertEqual(DataRepo._resolve_alias_settlement_id("מצדות יהודה"), 3745)
        self.assertEqual(DataRepo._resolve_alias_settlement_id("מצודות יהודה"), 3745)
        self.assertEqual(DataRepo._resolve_alias_settlement_id("  מצודות   יהודה  "), 3745)

    def test_search_settlements_keeps_prefix_match_when_extra_words_are_added(self):
        repo = DataRepo.__new__(DataRepo)

        class FakeCursor:
            def execute(self, *_args, **_kwargs):
                return None

            def fetchall(self):
                return [
                    {
                        "settlement_id": 1,
                        "settlement_name": "טנא",
                        "population_total": 500,
                    },
                    {
                        "settlement_id": 2,
                        "settlement_name": "עומר",
                        "population_total": 1000,
                    },
                ]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("engine.get_connection", return_value=FakeConnection()):
            results = repo.search_settlements("טנא עומרים")

        self.assertEqual(results[0]["name"], "טנא")
        self.assertEqual(results[0]["id"], 1)
        self.assertEqual(len(results), 1)

    def test_exact_matches_stay_ranked_above_partial_prefix_fallbacks(self):
        repo = DataRepo.__new__(DataRepo)

        class FakeCursor:
            def execute(self, *_args, **_kwargs):
                return None

            def fetchall(self):
                return [
                    {
                        "settlement_id": 1,
                        "settlement_name": "טנא",
                        "population_total": 500,
                    },
                    {
                        "settlement_id": 2,
                        "settlement_name": "טנא עומרים",
                        "population_total": 100,
                    },
                ]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("engine.get_connection", return_value=FakeConnection()):
            results = repo.search_settlements("טנא עומרים")

        self.assertEqual(
            [item["name"] for item in results],
            ["טנא עומרים", "טנא"],
        )

    def test_settlement_display_name_override_is_stable_and_unique(self):
        self.assertEqual(
            DataRepo._get_display_name(3745, "בית יתיר"),
            "בית יתיר (מצדות יהודה)",
        )
        self.assertEqual(
            DataRepo._get_search_names(3745, "בית יתיר"),
            [
                "בית יתיר",
                "בית יתיר (מצדות יהודה)",
                "מצדות יהודה",
                "מצודות יהודה",
            ],
        )

    @patch("engine.get_commute")
    def test_calculate_parent_commute_returns_partial_result_when_distance_is_missing(self, mock_get_drive_commute):
        mock_get_drive_commute.return_value = {
            "status": "NO_API_KEY",
            "duration_min": None,
            "distance_km": None,
        }

        result = calculate_parent_commute(
            city_name="Tel Aviv",
            parent={
                "work_address": "Begin 132, Tel Aviv",
                "commute_mode": "private_car",
                "departure_time": "08:30",
                "work_days_per_week": 5,
            },
            departure_date="2026-03-22",
        )

        self.assertEqual(result["commute"]["status"], "NO_API_KEY")
        self.assertIsNone(result["cost"]["daily_cost"])
        self.assertIsNone(result["cost"]["monthly_cost"])

    @patch("engine.get_commute")
    def test_calculate_parent_commute_passes_selected_mode_to_commute_lookup(self, mock_get_commute):
        mock_get_commute.return_value = {
            "status": "OK",
            "duration_min": 40,
            "distance_km": 18.0,
        }

        result = calculate_parent_commute(
            city_name="Beer Sheva",
            parent={
                "work_address": "Begin 132, Tel Aviv",
                "commute_mode": "public_transport",
                "departure_time": "08:30",
                "work_days_per_week": 5,
            },
            departure_date="2026-03-22",
        )

        self.assertEqual(result["commute"]["status"], "OK")
        mock_get_commute.assert_called_once()
        self.assertEqual(mock_get_commute.call_args.kwargs["commute_mode"], "public_transport")

    def test_build_compare_response_maps_raw_engine_data_to_schema_shape(self):
        response = build_compare_response(
            cities=["בית יתיר"],
            family={
                "parent1_income": 12000,
                "parent2_income": 9000,
                "desired_rooms": 4,
                "children": [{"age": 3}, {"age": 7}],
            },
            raw_results=[
                {
                    "city": "בית יתיר (מצדות יהודה)",
                    "family": {
                        "parent1_income": 12000,
                        "parent2_income": 9000,
                        "desired_rooms": 4,
                        "children": [{"age": 3}, {"age": 7}],
                    },
                    "parent1_commute": {
                        "commute_mode": "private_car",
                        "commute": {
                            "status": "OK",
                            "duration_min": 35,
                            "distance_km": 22.5,
                        },
                        "cost": {
                            "daily_cost": 31.5,
                            "monthly_cost": 681.45,
                        },
                    },
                    "parent2_commute": None,
                    "age_and_religion": [
                        {
                            "religion": "Jewish",
                            "age0_19_pcnt": 28.0,
                            "age20_64_pcnt": 58.0,
                            "age65_pcnt": 14.0,
                            "age_median": 36.5,
                        }
                    ],
                    "education": {
                        "schools_total": 12,
                        "schools_elementary": 5,
                        "schools_middle_schools": 3,
                        "schools_high_schools": 2,
                        "avg_students_per_class_elementary": 27.5,
                        "avg_students_per_class_secondary": 30.1,
                        "avg_students_per_class_middle_schools": 29.0,
                        "avg_students_per_class_high_schools": 31.2,
                        "dropout_rate_total": 2.4,
                        "bagrut_eligibility_rate": 84.2,
                        "higher_education_entry_rate_8_years": 61.3,
                        "avg_students_per_teacher": 13.7,
                    },
                    "periphery": {
                        "potential_accessibility_rank": {
                            "rank": 14,
                            "out_of": 255,
                            "display_place": 242,
                            "percentile": 5.5,
                            "summary": "place 242 out of 255",
                        },
                        "peripherality_rank_2020": {
                            "rank": 88,
                            "out_of": 255,
                            "display_place": 168,
                            "percentile": 34.5,
                            "summary": "place 168 out of 255",
                        },
                    },
                    "social_economic": {
                        "cluster_2021": 7,
                        "max_grade": 10,
                        "summary": "grade 7 out of 10",
                    },
                    "crime_statistics": {
                        "cluster_1": {"per_1000_residents": 2.1},
                        "cluster_2": {"per_1000_residents": 4.2},
                        "cluster_3": {"per_1000_residents": 1.8},
                    },
                    "average_cars_per_household": 1,
                    "total_commute_cost_monthly": 681.45,
                    "family_tax_benefit": {
                        "tax_rate_2026": 0.07,
                        "tax_ceiling_2026": 180000.0,
                        "total_benefit_annual": 5040.0,
                        "total_benefit_monthly_estimated": 420.0,
                    },
                }
            ],
        )

        self.assertEqual(response.input_summary.family.children_count, 2)
        self.assertEqual(response.input_summary.cities, ["בית יתיר (מצדות יהודה)"])
        self.assertEqual(response.results[0].city, "בית יתיר (מצדות יהודה)")
        self.assertEqual(response.results[0].costs.commute_monthly, 681.45)
        self.assertEqual(response.results[0].transport.parent1_work_commute.status, "OK")
        self.assertIsNone(response.results[0].transport.parent2_work_commute)
        self.assertEqual(response.results[0].quality_of_life.potential_accessibility_rank.display_place, 242)
        self.assertEqual(response.results[0].quality_of_life.potential_accessibility_rank.out_of, 255)
        self.assertEqual(response.results[0].quality_of_life.social_economic_cluster_2021.value, 7)
        self.assertEqual(response.results[0].quality_of_life.social_economic_cluster_2021.out_of, 10)
        self.assertEqual(response.results[0].quality_of_life.religion, "Jewish")
        self.assertEqual(response.results[0].taxes.total_family_income_monthly, 21000.0)
        self.assertEqual(response.results[0].taxes.tax_ceiling_annual, 180000.0)
        self.assertEqual(response.results[0].taxes.tax_benefit_annual, 5040.0)
        self.assertEqual(response.results[0].taxes.tax_benefit_percent, 0.07)
        self.assertEqual(response.results[0].taxes.tax_benefit_monthly, 420.0)
        self.assertEqual(response.results[0].safety.crime_index, 8.1)
        self.assertEqual(response.results[0].data_completeness.completion_percent, 83.3)


if __name__ == "__main__":
    unittest.main()
