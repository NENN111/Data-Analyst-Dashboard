"""Загрузка вакансий аналитиков из публичного каталога «Хабр Карьеры»."""

from __future__ import annotations

import argparse
import re
import time
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from db import init_db, upsert_vacancies
from habr_career_etl import build_session
from trudvsem_etl import TITLE_PATTERN, parse_published_at, stable_numeric_id


CATALOG_URL = "https://career.habr.com/vacancies"
DEFAULT_QUERIES: tuple[str | None, ...] = (None,)
CURRENCY_SYMBOLS = {"₽": "RUR", "$": "USD", "€": "EUR", "₸": "KZT"}


def parse_salary(text: str | None) -> tuple[int | None, int | None, str | None]:
    if not text:
        return None, None, None
    normalized = text.replace("\xa0", " ").strip()
    currency = next(
        (code for symbol, code in CURRENCY_SYMBOLS.items() if symbol in normalized),
        None,
    )
    numbers = [int(value.replace(" ", "")) for value in re.findall(r"\d[\d ]*", normalized)]
    if not numbers:
        return None, None, currency
    if "от" in normalized.casefold() and "до" in normalized.casefold() and len(numbers) >= 2:
        return numbers[0], numbers[1], currency
    if "от" in normalized.casefold():
        return numbers[0], None, currency
    if "до" in normalized.casefold():
        return None, numbers[0], currency
    return numbers[0], numbers[0], currency


def meta_fields(card: Tag) -> tuple[str, str, str]:
    experience = "Не указан"
    schedule = "Не указан"
    cities: list[str] = []
    for chip in card.select(".vacancy-meta .basic-chip"):
        icon = chip.select_one("use")
        icon_ref = str(icon.get("xlink:href", "")) if icon else ""
        value_element = chip.select_one(".chip-with-icon__text")
        value = value_element.get_text(" ", strip=True) if value_element else ""
        if not value:
            continue
        if icon_ref.endswith("#grade"):
            experience = value
        elif icon_ref.endswith("#format"):
            schedule = "Удаленная работа" if "удал" in value.casefold() else value
        elif icon_ref.endswith("#placemark"):
            cities.append(value)
    return experience, schedule, ", ".join(cities) or "Не указан"


def card_to_record(card: Tag) -> dict[str, Any]:
    title_link = card.select_one("a.vacancy-card__title-link")
    if not title_link:
        raise ValueError("Карточка вакансии не содержит заголовок")
    relative_url = str(title_link.get("href") or "")
    match = re.fullmatch(r"/vacancies/(\d+)", relative_url)
    if not match:
        raise ValueError("Карточка вакансии содержит неизвестный URL")

    salary_element = card.select_one(".vacancy-card__salary .basic-salary")
    salary_text = salary_element.get_text(" ", strip=True) if salary_element else None
    salary_from, salary_to, currency = parse_salary(salary_text)
    experience, schedule, city = meta_fields(card)
    published_element = card.select_one("time.basic-date")
    published_at = (
        parse_published_at(str(published_element.get("datetime")))
        if published_element and published_element.get("datetime")
        else None
    )
    skills = {
        element.get_text(" ", strip=True)
        for element in card.select(".vacancy-card__skills-chip .basic-chip__text")
        if element.get_text(" ", strip=True)
    }
    return {
        "id": stable_numeric_id(f"habr-career:{match.group(1)}"),
        "title": title_link.get_text(" ", strip=True),
        "salary_from": salary_from,
        "salary_to": salary_to,
        "salary_gross": None,
        "currency": currency,
        "experience": experience,
        "employment": None,
        "schedule": schedule,
        "city": city,
        "skills": sorted(skills, key=str.casefold),
        "url": urljoin(CATALOG_URL, relative_url),
        "published_at": published_at,
    }


def fetch_public_vacancies(
    queries: list[str] | tuple[str | None, ...] = DEFAULT_QUERIES,
    max_pages: int = 60,
    delay: float = 1.0,
) -> list[dict[str, Any]]:
    if not queries or any(query is not None and not query.strip() for query in queries):
        raise ValueError("Поисковый запрос не может быть пустой строкой")
    if not 1 <= max_pages <= 100:
        raise ValueError("max_pages должен быть в диапазоне от 1 до 100")
    if not 0 <= delay <= 30:
        raise ValueError("delay должен быть в диапазоне от 0 до 30 секунд")

    records: dict[int, dict[str, Any]] = {}
    with build_session() as session:
        # API-сессия по умолчанию запрашивает JSON, а публичный каталог
        # маршрутизирует запросы по HTML-заголовку Accept.
        session.headers["Accept"] = "text/html,application/xhtml+xml"
        for query in queries:
            for page in range(1, max_pages + 1):
                params: dict[str, str | int] = {"type": "all"}
                if query:
                    params["q"] = query
                if page > 1:
                    params["page"] = page
                response = session.get(CATALOG_URL, params=params, timeout=(10, 60))
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                cards = soup.select(".vacancy-card")
                for card in cards:
                    title_element = card.select_one("a.vacancy-card__title-link")
                    title = title_element.get_text(" ", strip=True) if title_element else ""
                    if not TITLE_PATTERN.search(title):
                        continue
                    record = card_to_record(card)
                    records[record["id"]] = record

                if not soup.select_one('a[rel="next"]'):
                    break
                if page == max_pages:
                    scope = repr(query) if query else "публичного каталога"
                    raise RuntimeError(
                        f"Достигнут лимит страниц для {scope}; "
                        "увеличьте --max-pages"
                    )
                time.sleep(delay)
    return list(records.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Загрузить вакансии аналитиков из публичного каталога Хабр Карьеры"
    )
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--max-pages", type=int, default=60)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    records = fetch_public_vacancies(
        queries=args.queries or DEFAULT_QUERIES,
        max_pages=args.max_pages,
        delay=args.delay,
    )
    if not records:
        raise RuntimeError(
            "Публичный каталог не вернул вакансий аналитиков; проверьте разметку сайта"
        )
    init_db()
    upsert_vacancies(records)
    print(f"Загружено и обновлено публичных вакансий Хабр Карьеры: {len(records)}")


if __name__ == "__main__":
    main()
