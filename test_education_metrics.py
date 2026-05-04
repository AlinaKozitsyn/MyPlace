import unittest

from engine import (
    build_age_and_religion_summary,
    build_crime_statistics_summary,
    build_education_summary,
    build_periphery_summary,
    build_social_economic_summary,
    calculate_average_cars_per_household,
    calculate_rate_per_1000,
    format_rank_place,
    safe_divide,
)


class EducationMetricsTests(unittest.TestCase):
    def test_safe_divide_returns_zero_when_numerator_is_zero(self):
        self.assertEqual(safe_divide(0, 12), 0.0)

    def test_safe_divide_returns_zero_when_denominator_is_zero(self):
        self.assertEqual(safe_divide(120, 0), 0.0)

    def test_safe_divide_returns_rounded_ratio(self):
        self.assertEqual(safe_divide(125, 5), 25.0)

    def test_build_education_summary_includes_requested_fields(self):
        summary = build_education_summary(
            {
                "schools_total": 10,
                "schools_elementary": 4,
                "schools_secondary": 3,
                "schools_middle_schools": 2,
                "schools_high_schools": 1,
                "students_elementary": 400,
                "classes_elementary": 20,
                "students_secondary": 330,
                "classes_secondary": 15,
                "students_middle_schools": 0,
                "classes_middle_schools": 7,
                "students_high_schools": 240,
                "classes_high_schools": 0,
                "dropout_rate_total": 3.2,
                "bagrut_eligibility_rate": 81.5,
                "higher_education_entry_rate_8_years": 58.4,
                "avg_students_per_teacher": 14.1,
                "source_year": 2023,
            }
        )

        self.assertEqual(summary["schools_total"], 10)
        self.assertEqual(summary["schools_elementary"], 4)
        self.assertEqual(summary["schools_secondary"], 3)
        self.assertEqual(summary["schools_middle_schools"], 2)
        self.assertEqual(summary["schools_high_schools"], 1)
        self.assertEqual(summary["avg_students_per_class_elementary"], 20.0)
        self.assertEqual(summary["avg_students_per_class_secondary"], 22.0)
        self.assertEqual(summary["avg_students_per_class_middle_schools"], 0.0)
        self.assertEqual(summary["avg_students_per_class_high_schools"], 0.0)
        self.assertEqual(summary["dropout_rate_total"], 3.2)
        self.assertEqual(summary["bagrut_eligibility_rate"], 81.5)
        self.assertEqual(summary["higher_education_entry_rate_8_years"], 58.4)
        self.assertEqual(summary["avg_students_per_teacher"], 14.1)
        self.assertEqual(summary["source_year"], 2023)

    def test_build_age_and_religion_summary_returns_requested_fields(self):
        summary = build_age_and_religion_summary(
            [
                {
                    "religion": "יהודי",
                    "age0_19_pcnt": 30.1,
                    "age20_64_pcnt": 55.4,
                    "age65_pcnt": 14.5,
                    "age_median": 33.8,
                    "source_year": 2023,
                }
            ]
        )

        self.assertEqual(
            summary,
            [
                {
                    "religion": "יהודי",
                    "age0_19_pcnt": 30.1,
                    "age20_64_pcnt": 55.4,
                    "age65_pcnt": 14.5,
                    "age_median": 33.8,
                    "source_year": 2023,
                }
            ],
        )

    def test_build_age_and_religion_summary_returns_empty_list_when_missing(self):
        self.assertEqual(build_age_and_religion_summary([]), [])
        self.assertEqual(build_age_and_religion_summary(None), [])

    def test_calculate_average_cars_per_household_rounds_regularly_above_one(self):
        result = calculate_average_cars_per_household(
            {"private_cars_num": 2500},
            {"households": 1000},
        )

        self.assertEqual(result, 2)

    def test_calculate_average_cars_per_household_rounds_up_to_one_below_one(self):
        result = calculate_average_cars_per_household(
            {"private_cars_num": 400},
            {"households": 1000},
        )

        self.assertEqual(result, 1)

    def test_calculate_average_cars_per_household_returns_zero_when_missing_or_zero(self):
        self.assertEqual(
            calculate_average_cars_per_household(
                {"private_cars_num": 2500},
                {"households": 0},
            ),
            0.0,
        )
        self.assertEqual(
            calculate_average_cars_per_household(None, {"households": 1000}),
            0.0,
        )

    def test_format_rank_place_returns_readable_place(self):
        self.assertEqual(
            format_rank_place(12, 255),
            {
                "rank": 12,
                "out_of": 255,
                "display_place": 244,
                "percentile": 4.7,
                "summary": "place 244 out of 255",
            },
        )

    def test_build_periphery_summary_returns_requested_fields(self):
        summary = build_periphery_summary(
            {
                "potential_accessibility_rank": 12,
                "peripherality_rank_2020": 88,
                "source_year": 2023,
            },
            255,
        )

        self.assertEqual(
            summary,
            {
                "potential_accessibility_rank": {
                    "rank": 12,
                    "out_of": 255,
                    "display_place": 244,
                    "percentile": 4.7,
                    "summary": "place 244 out of 255",
                },
                "peripherality_rank_2020": {
                    "rank": 88,
                    "out_of": 255,
                    "display_place": 168,
                    "percentile": 34.5,
                    "summary": "place 168 out of 255",
                },
                "source_year": 2023,
            },
        )

    def test_build_periphery_summary_returns_none_when_missing(self):
        self.assertIsNone(build_periphery_summary(None, 255))

    def test_build_social_economic_summary_returns_grade_message(self):
        summary = build_social_economic_summary(
            {
                "cluster_2021": 7,
                "source_year": 2021,
            }
        )

        self.assertEqual(
            summary,
            {
                "cluster_2021": 7,
                "max_grade": 10,
                "summary": "grade 7 out of 10",
                "source_year": 2021,
            },
        )

    def test_build_social_economic_summary_returns_none_when_missing(self):
        self.assertIsNone(build_social_economic_summary(None))

    def test_build_crime_statistics_summary_returns_cluster_counts_and_rates(self):
        summary = build_crime_statistics_summary(
            {
                "cluster_1_count": 366,
                "cluster_2_count": 530,
                "cluster_3_count": 507,
            },
            37000,
        )

        self.assertEqual(
            summary,
            {
                "cluster_1": {
                    "count": 366,
                    "per_1000_residents": 9.89,
                },
                "cluster_2": {
                    "count": 530,
                    "per_1000_residents": 14.32,
                },
                "cluster_3": {
                    "count": 507,
                    "per_1000_residents": 13.7,
                },
            },
        )

    def test_build_crime_statistics_summary_returns_zero_when_missing(self):
        summary = build_crime_statistics_summary(None, 0)

        self.assertEqual(
            summary,
            {
                "cluster_1": {
                    "count": 0,
                    "per_1000_residents": 0.0,
                },
                "cluster_2": {
                    "count": 0,
                    "per_1000_residents": 0.0,
                },
                "cluster_3": {
                    "count": 0,
                    "per_1000_residents": 0.0,
                },
            },
        )

    def test_calculate_rate_per_1000_uses_100_for_population_below_1000(self):
        self.assertEqual(calculate_rate_per_1000(25, 500), 5.0)

    def test_calculate_rate_per_1000_uses_1000_for_population_1000_or_more(self):
        self.assertEqual(calculate_rate_per_1000(25, 5000), 5.0)


if __name__ == "__main__":
    unittest.main()
