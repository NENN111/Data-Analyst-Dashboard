import unittest
from unittest.mock import patch

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import (
    city_options,
    experience_options,
    filter_data,
    format_rubles,
    normalize_experience,
    read_sql,
    split_cities,
    top_skills,
)


class DashboardHelpersTest(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame(
            [
                {
                    "title": "Data Analyst",
                    "city": "Москва",
                    "schedule": "Удаленная работа",
                    "experience": "1–3 года",
                    "skills": ["SQL", "Python"],
                    "median_salary": 150000,
                },
                {
                    "title": "BI-аналитик",
                    "city": "Город Москва, Санкт-петербург, Казань",
                    "schedule": "Полный день",
                    "experience": "Нет опыта",
                    "skills": ["SQL", "Power BI"],
                    "median_salary": None,
                },
            ]
        )

    def test_empty_filter_values_keep_all_rows(self):
        self.assertEqual(len(filter_data(self.data)), 2)

    def test_search_covers_title_and_skills(self):
        self.assertEqual(filter_data(self.data, query="python").iloc[0]["city"], "Москва")
        self.assertEqual(
            filter_data(self.data, query="BI-аналитик").iloc[0]["city"],
            "Город Москва, Санкт-петербург, Казань",
        )

    def test_combined_filters_and_salary_flag(self):
        result = filter_data(
            self.data,
            cities=["Москва"],
            schedules=["Удаленная работа"],
            salary_only=True,
        )
        self.assertEqual(result["title"].tolist(), ["Data Analyst"])

    def test_top_skills_and_salary_format(self):
        self.assertEqual(top_skills(self.data).iloc[0].to_dict(), {"Навык": "SQL", "Вакансий": 2})
        self.assertEqual(format_rubles(150000), "150 000 ₽")
        self.assertEqual(format_rubles(None), "—")

    def test_multi_city_values_are_normalized_and_filterable(self):
        self.assertEqual(
            split_cities("Город Москва, Санкт-петербург, Москва"),
            ["Москва", "Санкт-Петербург"],
        )
        self.assertEqual(city_options(self.data), ["Казань", "Москва", "Санкт-Петербург"])
        self.assertEqual(
            filter_data(self.data, cities=["Санкт-Петербург"])["title"].tolist(),
            ["BI-аналитик"],
        )

    def test_experience_grades_and_years_share_ordered_groups(self):
        values = {
            "Без опыта": "Без опыта / Intern",
            "Intern": "Без опыта / Intern",
            "От 1 года": "1–2 года / Junior",
            "Middle": "3–4 года / Middle",
            "От 4 лет": "3–4 года / Middle",
            "Senior": "5+ лет / Senior",
            "От 6 лет": "5+ лет / Senior",
            None: "Не указан",
        }
        for value, expected in values.items():
            self.assertEqual(normalize_experience(value), expected)

        self.assertEqual(
            experience_options(self.data),
            ["Без опыта / Intern", "1–2 года / Junior"],
        )
        self.assertEqual(
            filter_data(self.data, experiences=["Без опыта / Intern"])["title"].tolist(),
            ["BI-аналитик"],
        )


class DashboardDatabaseTest(unittest.TestCase):
    def setUp(self):
        # Эти проверки относятся к обычному PostgreSQL; Neon использует HTTPS.
        patcher = patch("app.neon_http_endpoint", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def wrapped_connection_error():
        error = pd.errors.DatabaseError("Connection interrupted")
        error.__cause__ = OperationalError("SELECT 1", None, ConnectionError())
        return error

    def test_pandas_wrapped_connection_error_is_retried(self):
        expected = pd.DataFrame({"total": [28]})
        with (
            patch("app.pd.read_sql_query", side_effect=[self.wrapped_connection_error(), expected]) as query,
            patch("app.engine.dispose") as dispose,
            patch("app.time.sleep"),
        ):
            self.assertIs(read_sql(text("SELECT COUNT(*) AS total FROM vacancies")), expected)
        self.assertEqual(query.call_count, 2)
        dispose.assert_called_once()

    def test_unrelated_database_error_is_not_retried(self):
        error = pd.errors.DatabaseError("Undefined table")
        with (
            patch("app.pd.read_sql_query", side_effect=error) as query,
            patch("app.engine.dispose") as dispose,
            patch("app.time.sleep") as sleep,
        ):
            with self.assertRaises(pd.errors.DatabaseError):
                read_sql(text("SELECT * FROM missing_table"))
        query.assert_called_once()
        dispose.assert_not_called()
        sleep.assert_not_called()

    def test_persistent_connection_failure_stops_after_three_attempts(self):
        with (
            patch("app.pd.read_sql_query", side_effect=self.wrapped_connection_error()) as query,
            patch("app.engine.dispose"),
            patch("app.time.sleep"),
        ):
            with self.assertRaises(pd.errors.DatabaseError):
                read_sql(text("SELECT 1"))
        self.assertEqual(query.call_count, 3)


if __name__ == "__main__":
    unittest.main()
