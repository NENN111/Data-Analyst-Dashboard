"""Загрузка вакансий Data Analyst из API HH.ru в PostgreSQL.

Пример запуска: python etl.py --pages 5

Повторный запуск безопасен: ``upsert_vacancies`` использует PostgreSQL
``ON CONFLICT DO UPDATE`` по ID вакансии, поэтому записи не дублируются.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import time
from typing import Any

import requests

from db import init_db, upsert_vacancies


API_URL = "https://api.hh.ru/vacancies"
DETAIL_URL = "https://api.hh.ru/vacancies/{vacancy_id}"
HEADERS = {"User-Agent": "HHDataAnalystPortfolio/1.0 (portfolio@example.com)"}


def request_json(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Выполняет запрос к API и возвращает JSON, либо выбрасывает HTTP-ошибку."""
    response = session.get(url, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_published_at(value: str | None) -> datetime | None:
    """Преобразует ISO-дату HH в datetime с временной зоной."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def vacancy_to_record(vacancy: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    """Объединяет краткий и детальный ответы API в запись для ORM-модели."""
    salary = vacancy.get("salary") or {}
    return {
        "id": int(vacancy["id"]), "title": vacancy["name"],
        "salary_from": salary.get("from"), "salary_to": salary.get("to"),
        "salary_gross": salary.get("gross"), "currency": salary.get("currency"),
        "experience": (vacancy.get("experience") or {}).get("name"),
        "employment": (vacancy.get("employment") or {}).get("name"),
        "schedule": (vacancy.get("schedule") or {}).get("name"),
        "city": (vacancy.get("area") or {}).get("name"),
        "skills": [skill["name"] for skill in details.get("key_skills", [])],
        "url": vacancy.get("alternate_url"), "published_at": parse_published_at(vacancy.get("published_at")),
    }


def fetch_vacancies(query: str = "Data Analyst", pages: int = 5, per_page: int = 100) -> list[dict[str, Any]]:
    """Загружает вакансии и ключевые навыки; возвращает записи для БД."""
    if not 1 <= pages <= 20:
        raise ValueError("pages должен быть в диапазоне от 1 до 20")
    if not 1 <= per_page <= 100:
        raise ValueError("per_page должен быть в диапазоне от 1 до 100")
    records: list[dict[str, Any]] = []
    with requests.Session() as session:
        for page in range(pages):
            payload = request_json(session, API_URL, {"text": query, "page": page, "per_page": per_page})
            for vacancy in payload.get("items", []):
                try:
                    details = request_json(session, DETAIL_URL.format(vacancy_id=vacancy["id"]))
                    records.append(vacancy_to_record(vacancy, details))
                except requests.RequestException as error:
                    print(f"Не удалось загрузить вакансию {vacancy['id']}: {error}")
                time.sleep(0.1)  # Не превышаем разумную частоту запросов к API.
            if page >= payload.get("pages", 0) - 1:
                break
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузить вакансии Data Analyst с HH.ru в PostgreSQL")
    parser.add_argument("--query", default="Data Analyst", help="Текст поискового запроса")
    parser.add_argument("--pages", type=int, default=5, help="Количество страниц: от 1 до 20")
    parser.add_argument("--per-page", type=int, default=100, help="Вакансий на странице: от 1 до 100")
    args = parser.parse_args()
    init_db()
    records = fetch_vacancies(args.query, args.pages, args.per_page)
    upsert_vacancies(records)
    print(f"Загружено и обновлено вакансий: {len(records)}")


if __name__ == "__main__":
    main()
