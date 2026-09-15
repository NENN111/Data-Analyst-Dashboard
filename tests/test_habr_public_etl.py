import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from habr_public_etl import card_to_record, fetch_public_vacancies, parse_salary


CARD_HTML = """
<div class="vacancy-card">
  <time class="basic-date" datetime="2026-09-08T16:46:21+03:00">8 сентября</time>
  <a class="vacancy-card__title-link" href="/vacancies/1000166668">Аналитик данных</a>
  <div class="vacancy-card__salary"><div class="basic-salary">от 250 000 до 270 000 ₽</div></div>
  <div class="vacancy-meta">
    <div class="basic-chip"><svg><use xlink:href="/icons.svg#grade"></use></svg><div class="chip-with-icon__text">Middle</div></div>
    <div class="basic-chip"><svg><use xlink:href="/icons.svg#format"></use></svg><div class="chip-with-icon__text">Можно удалённо</div></div>
    <div class="basic-chip"><svg><use xlink:href="/icons.svg#placemark"></use></svg><div class="chip-with-icon__text">Москва</div></div>
  </div>
  <div class="vacancy-card__skills">
    <a class="vacancy-card__skills-chip"><div class="basic-chip__text">SQL</div></a>
    <a class="vacancy-card__skills-chip"><div class="basic-chip__text">Python</div></a>
  </div>
</div>
"""


class HabrPublicEtlTests(unittest.TestCase):
    def test_parse_salary_ranges(self):
        self.assertEqual(parse_salary("от 250 000 до 270 000 ₽"), (250000, 270000, "RUR"))
        self.assertEqual(parse_salary("от 3 000 $"), (3000, None, "USD"))
        self.assertEqual(parse_salary("до 5 000 €"), (None, 5000, "EUR"))

    def test_card_mapping(self):
        card = BeautifulSoup(CARD_HTML, "html.parser").select_one(".vacancy-card")
        record = card_to_record(card)

        self.assertEqual(record["title"], "Аналитик данных")
        self.assertEqual(record["salary_from"], 250000)
        self.assertEqual(record["salary_to"], 270000)
        self.assertEqual(record["currency"], "RUR")
        self.assertEqual(record["experience"], "Middle")
        self.assertEqual(record["schedule"], "Удаленная работа")
        self.assertEqual(record["city"], "Москва")
        self.assertEqual(record["skills"], ["Python", "SQL"])
        self.assertEqual(
            record["url"], "https://career.habr.com/vacancies/1000166668"
        )

    def test_fetches_pagination_as_html(self):
        class FakeResponse:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.headers = {}
                self.pages = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def get(self, _url, params, timeout):
                self.pages.append(params.get("page", 1))
                next_link = '<a rel="next" href="?page=2">next</a>'
                return FakeResponse(CARD_HTML + (next_link if len(self.pages) == 1 else ""))

        session = FakeSession()
        with patch("habr_public_etl.build_session", return_value=session), patch(
            "habr_public_etl.time.sleep"
        ):
            records = fetch_public_vacancies(max_pages=2)

        self.assertEqual(session.pages, [1, 2])
        self.assertTrue(session.headers["Accept"].startswith("text/html"))
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
