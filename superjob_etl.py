"""Загрузка вакансий аналитиков из официального API SuperJob."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
import re
import time
from typing import Any, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from db import init_db, upsert_vacancies
from trudvsem_etl import SKILL_PATTERNS, TITLE_PATTERN, stable_numeric_id


API_URL = "https://api.superjob.ru/2.0/vacancies/"
DEFAULT_QUERIES = ("аналитик данных", "data analyst", "продуктовый аналитик")
CURRENCY_CODES = {
    "rub": "RUR",
    "rur": "RUR",
    "usd": "USD",
    "eur": "EUR",
    "uah": "UAH",
}


def api_key() -> str:
    """Возвращает ключ зарегистрированного приложения SuperJob."""
    value = os.getenv("SUPERJOB_API_KEY", "").strip()
    if not value:
        raise RuntimeError(
            "Не задан SUPERJOB_API_KEY. Зарегистрируйте приложение на api.superjob.ru."
        )
    return value


def build_session(key: str) -> requests.Session:
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update(
        {
            "X-Api-App-Id": key,
            "Accept": "application/json",
            "User-Agent": (
                "DataAnalystDashboard/2.0 "
                "(+https://github.com/NENN111/Data-Analyst-Dashboard)"
            ),
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def nested_title(value: Any, default: str = "Не указан") -> str:
    if isinstance(value, dict):
        title = value.get("title")
        if title:
            return str(title).strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def extract_skills(vacancy: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(vacancy.get(field) or "")
        for field in ("profession", "candidat", "work", "compensation")
    )
    return sorted(
        {
            name
            for name, pattern in SKILL_PATTERNS.items()
            if re.search(pattern, text, flags=re.IGNORECASE)
        },
        key=str.casefold,
    )


def vacancy_to_record(vacancy: dict[str, Any]) -> dict[str, Any]:
    source_id = vacancy.get("id")
    if source_id is None:
        raise ValueError("Вакансия SuperJob не содержит ID")
    salary_from = vacancy.get("payment_from") or None
    salary_to = vacancy.get("payment_to") or None
    currency = CURRENCY_CODES.get(str(vacancy.get("currency") or "").casefold())
    if not salary_from and not salary_to:
        currency = None
    timestamp = vacancy.get("date_published")
    published_at = (
        datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        if timestamp is not None
        else None
    )
    schedule = nested_title(vacancy.get("place_of_work"))
    if "удален" in schedule.casefold():
        schedule = "Удаленная работа"
    return {
        "id": stable_numeric_id(f"superjob:{source_id}"),
        "title": str(vacancy.get("profession") or "Без названия").strip(),
        "salary_from": salary_from,
        "salary_to": salary_to,
        "salary_gross": None,
        "currency": currency,
        "experience": nested_title(vacancy.get("experience")),
        "employment": nested_title(vacancy.get("type_of_work")),
        "schedule": schedule,
        "city": nested_title(vacancy.get("town")),
        "skills": extract_skills(vacancy),
        "url": vacancy.get("link"),
        "published_at": published_at,
    }


def fetch_vacancies(
    queries: Iterable[str] = DEFAULT_QUERIES,
    max_pages: int = 20,
    per_page: int = 100,
    delay: float = 0.25,
    key: str | None = None,
) -> list[dict[str, Any]]:
    normalized_queries = [query.strip() for query in queries]
    if not normalized_queries or any(not query for query in normalized_queries):
        raise ValueError("Поисковый запрос не может быть пустым")
    if not 1 <= max_pages <= 100:
        raise ValueError("max_pages должен быть в диапазоне от 1 до 100")
    if not 1 <= per_page <= 100:
        raise ValueError("per_page должен быть в диапазоне от 1 до 100")
    if not 0 <= delay <= 30:
        raise ValueError("delay должен быть в диапазоне от 0 до 30 секунд")

    records: dict[int, dict[str, Any]] = {}
    with build_session(key or api_key()) as session:
        for query in normalized_queries:
            for page in range(max_pages):
                response = session.get(
                    API_URL,
                    params={"keyword": query, "page": page, "count": per_page},
                    timeout=(10, 60),
                )
                response.raise_for_status()
                payload = response.json()
                items = payload.get("objects") or []
                for vacancy in items:
                    if not TITLE_PATTERN.search(vacancy.get("profession") or ""):
                        continue
                    record = vacancy_to_record(vacancy)
                    records[record["id"]] = record
                if not payload.get("more"):
                    break
                if page + 1 == max_pages:
                    raise RuntimeError(
                        f"Достигнут лимит страниц для запроса {query!r}; "
                        "увеличьте --max-pages"
                    )
                time.sleep(delay)
    return list(records.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Загрузить вакансии аналитиков из API SuperJob"
    )
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()

    records = fetch_vacancies(
        queries=args.queries or DEFAULT_QUERIES,
        max_pages=args.max_pages,
        per_page=args.per_page,
        delay=args.delay,
    )
    if not records:
        raise RuntimeError("SuperJob не вернул подходящих вакансий аналитиков")
    init_db()
    upsert_vacancies(records)
    print(f"Загружено и обновлено вакансий SuperJob: {len(records)}")


if __name__ == "__main__":
    main()
