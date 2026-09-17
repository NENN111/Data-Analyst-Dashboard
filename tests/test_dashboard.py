import unittest

import pandas as pd

from app import filter_data, format_rubles, top_skills


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
                    "city": "Казань",
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
        self.assertEqual(filter_data(self.data, query="BI-аналитик").iloc[0]["city"], "Казань")

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


if __name__ == "__main__":
    unittest.main()
