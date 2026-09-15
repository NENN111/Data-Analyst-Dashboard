import unittest
from unittest.mock import patch

from habr_career_etl import fetch_vacancies, vacancy_to_record


class FakeResponse:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.requested_pages = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get(self, _url, params, timeout):
        self.requested_pages.append(params["page"])
        return FakeResponse(next(self.pages))


class HabrCareerEtlTests(unittest.TestCase):
    def test_vacancy_mapping(self):
        record = vacancy_to_record(
            {
                "id": 42,
                "title": "Data Analyst",
                "published_at": "2026-09-12T10:00:00+03:00",
                "url": "https://career.habr.com/vacancies/42",
                "qualification": {"title": {"ru": "Средний"}},
                "city": "Москва",
                "employment_type": "Полный рабочий день",
                "remote": True,
                "expanded_salary": {
                    "from": 100000,
                    "to": 150000,
                    "currency": "rub",
                },
                "skills": [{"title": "SQL"}, {"title": "Python"}],
            }
        )

        self.assertEqual(record["currency"], "RUR")
        self.assertEqual(record["schedule"], "Удаленная работа")
        self.assertEqual(record["experience"], "Средний")
        self.assertEqual(record["skills"], ["Python", "SQL"])

    def test_fetches_pages_and_filters_unpublished_or_irrelevant_jobs(self):
        first = {
            "vacancies": [
                {"id": 1, "title": "Data Analyst", "published": True},
                {"id": 2, "title": "Backend Developer", "published": True},
            ],
            "pagination": {"total": 3, "page": 0, "per": 2},
        }
        second = {
            "vacancies": [
                {"id": 3, "title": "Продуктовый аналитик", "published": False}
            ],
            "pagination": {"total": 3, "page": 1, "per": 2},
        }
        session = FakeSession([first, second])

        with patch("habr_career_etl.build_session", return_value=session):
            records = fetch_vacancies("secret")

        self.assertEqual(session.requested_pages, [0, 1])
        self.assertEqual([record["title"] for record in records], ["Data Analyst"])


if __name__ == "__main__":
    unittest.main()
