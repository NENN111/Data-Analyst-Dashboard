import os
import unittest
from unittest.mock import patch

from hh_etl import application_token, fetch_vacancies, vacancy_to_record
from trudvsem_etl import stable_numeric_id


VACANCY = {
    "id": "12345",
    "name": "Аналитик данных",
    "salary": {"from": 150000, "to": 200000, "currency": "RUR", "gross": True},
    "published_at": "2026-09-21T12:30:00+0300",
    "area": {"id": "1", "name": "Москва"},
    "experience": {"id": "between1And3", "name": "От 1 года до 3 лет"},
    "employment": {"id": "full", "name": "Полная занятость"},
    "schedule": {"id": "remote", "name": "Удаленная работа"},
    "snippet": {
        "requirement": "Уверенное знание SQL и Python, опыт с Power BI",
        "responsibility": "Подготовка аналитических отчетов",
    },
    "alternate_url": "https://hh.ru/vacancy/12345",
}


class HhEtlTests(unittest.TestCase):
    def test_vacancy_mapping(self):
        record = vacancy_to_record(VACANCY)
        self.assertEqual(record["id"], stable_numeric_id("hh:12345"))
        self.assertEqual(record["title"], "Аналитик данных")
        self.assertEqual(record["salary_from"], 150000)
        self.assertEqual(record["salary_to"], 200000)
        self.assertTrue(record["salary_gross"])
        self.assertEqual(record["city"], "Москва")
        self.assertEqual(record["schedule"], "Удаленная работа")
        self.assertEqual(record["skills"], ["Power BI", "Python", "SQL"])
        self.assertIsNotNone(record["published_at"])

    def test_fetches_pages_and_deduplicates_queries(self):
        class FakeResponse:
            ok = True
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

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
                return FakeResponse({"items": [VACANCY], "pages": 2})

        session = FakeSession()
        with patch("hh_etl.build_session", return_value=session), patch("hh_etl.time.sleep"):
            records = fetch_vacancies(
                queries=["аналитик данных", "data analyst"],
                max_pages=2,
                per_page=100,
                access_token="test-token",
            )

        self.assertEqual(len(session.calls), 4)
        self.assertEqual(len(records), 1)
        self.assertEqual(session.calls[0]["area"], 113)
        self.assertEqual(session.calls[1]["page"], 1)

    def test_uses_configured_access_token(self):
        with patch.dict(os.environ, {"HH_ACCESS_TOKEN": " configured-token "}, clear=True):
            self.assertEqual(application_token(), "configured-token")

    def test_requests_application_token_without_exposing_credentials(self):
        class FakeResponse:
            ok = True
            status_code = 200

            def json(self):
                return {"access_token": "new-token"}

        with patch.dict(os.environ, {}, clear=True), patch(
            "hh_etl.requests.post", return_value=FakeResponse()
        ) as post:
            token = application_token("client-id", "client-secret")

        self.assertEqual(token, "new-token")
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "client_credentials")
        self.assertEqual(post.call_args.kwargs["data"]["client_id"], "client-id")

    def test_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            fetch_vacancies(max_pages=21, access_token="test-token")
        with self.assertRaises(ValueError):
            fetch_vacancies(per_page=101, access_token="test-token")


if __name__ == "__main__":
    unittest.main()
