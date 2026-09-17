import unittest
from unittest.mock import patch

from superjob_etl import fetch_vacancies, vacancy_to_record
from trudvsem_etl import stable_numeric_id


VACANCY = {
    "id": 12345,
    "profession": "Аналитик данных",
    "payment_from": 150000,
    "payment_to": 200000,
    "currency": "rub",
    "date_published": 1789420800,
    "town": {"title": "Москва"},
    "experience": {"title": "Опыт от 1 года"},
    "type_of_work": {"title": "Полный рабочий день"},
    "place_of_work": {"title": "Удаленная работа"},
    "candidat": "Уверенное знание SQL и Python, опыт с Power BI",
    "work": "Подготовка аналитических отчетов",
    "compensation": None,
    "link": "https://www.superjob.ru/vakansii/analitik-dannyh-12345.html",
}


class SuperJobEtlTests(unittest.TestCase):
    def test_vacancy_mapping(self):
        record = vacancy_to_record(VACANCY)
        self.assertEqual(record["id"], stable_numeric_id("superjob:12345"))
        self.assertEqual(record["title"], "Аналитик данных")
        self.assertEqual(record["salary_from"], 150000)
        self.assertEqual(record["salary_to"], 200000)
        self.assertEqual(record["currency"], "RUR")
        self.assertEqual(record["city"], "Москва")
        self.assertEqual(record["schedule"], "Удаленная работа")
        self.assertEqual(record["skills"], ["Power BI", "Python", "SQL"])
        self.assertIsNotNone(record["published_at"])

    def test_fetches_pages_and_deduplicates_queries(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeSession:
            def __init__(self):
                self.calls = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def get(self, _url, params, timeout):
                self.calls.append(params.copy())
                page = params["page"]
                return FakeResponse({"objects": [VACANCY], "more": page == 0})

        session = FakeSession()
        with patch("superjob_etl.build_session", return_value=session), patch(
            "superjob_etl.time.sleep"
        ):
            records = fetch_vacancies(
                queries=["аналитик данных", "data analyst"],
                max_pages=2,
                per_page=100,
                key="test-key",
            )

        self.assertEqual(len(session.calls), 4)
        self.assertEqual(len(records), 1)
        self.assertEqual(session.calls[0]["page"], 0)
        self.assertEqual(session.calls[1]["page"], 1)

    def test_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            fetch_vacancies(max_pages=0, key="test-key")
        with self.assertRaises(ValueError):
            fetch_vacancies(per_page=101, key="test-key")


if __name__ == "__main__":
    unittest.main()
