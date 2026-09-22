"""Загрузка вакансий аналитиков из официального API hh.ru."""

from __future__ import annotations

import argparse
import os
import re
import time
from typing import Any, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from db import init_db, upsert_vacancies
from trudvsem_etl import (
    SKILL_PATTERNS,
    TITLE_PATTERN,
    parse_published_at,
    stable_numeric_id,
)


API_URL = "https://api.hh.ru/vacancies"
TOKEN_URL = "https://api.hh.ru/token"
DEFAULT_QUERIES = ("аналитик данных", "data analyst", "продуктовый аналитик")
USER_AGENT = (
    "DataAnalystDashboard/1.0 "
    "(+https://github.com/NENN111/Data-Analyst-Dashboard)"
)


def application_token(
    client_id: str | None = None,
    client_secret: str | None = None,
) -> str:
    """Возвращает готовый токен или получает токен приложения по OAuth2."""
    configured_token = os.getenv("HH_ACCESS_TOKEN", "").strip()
    if configured_token:
        return configured_token

    client_id = (client_id or os.getenv("HH_CLIENT_ID", "")).strip()
    client_secret = (client_secret or os.getenv("HH_CLIENT_SECRET", "")).strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Не задан доступ к hh.ru. Укажите HH_ACCESS_TOKEN или пару "
            "HH_CLIENT_ID и HH_CLIENT_SECRET."
        )

    response = requests.post(
        TOKEN_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=(10, 30),
    )
    if not response.ok:
        # Не включаем тело ответа и параметры запроса: в них могут быть секреты.
        raise RuntimeError(
            f"Не удалось получить токен hh.ru: HTTP {response.status_code}"
        )
    token = str(response.json().get("access_token") or "").strip()
    if not token:
        raise RuntimeError("API hh.ru не вернул access_token")
    return token


def build_session(access_token: str) -> requests.Session:
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
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def nested_name(value: Any, default: str = "Не указан") -> str:
    if isinstance(value, dict):
        name = value.get("name")
        if name:
            return str(name).strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def extract_skills(vacancy: dict[str, Any]) -> list[str]:
    skills = {
        str(skill.get("name")).strip()
        for skill in vacancy.get("key_skills") or []
        if isinstance(skill, dict)
        and skill.get("name")
        and len(str(skill["name"]).strip()) <= 80
    }
    snippet = vacancy.get("snippet") or {}
    text = " ".join(
        str(value or "")
        for value in (
            vacancy.get("name"),
            snippet.get("requirement"),
            snippet.get("responsibility"),
        )
    )
    for name, pattern in SKILL_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            skills.add(name)
    return sorted(skills, key=str.casefold)


def schedule_label(vacancy: dict[str, Any]) -> str:
    schedule = vacancy.get("schedule") or {}
    work_formats = vacancy.get("work_format") or []
    if any(
        "remote" in str(item.get("id") or "").casefold()
        or "удален" in str(item.get("name") or "").casefold()
        for item in [schedule, *work_formats]
        if isinstance(item, dict)
    ):
        return "Удаленная работа"
    return nested_name(schedule)


def vacancy_to_record(vacancy: dict[str, Any]) -> dict[str, Any]:
    source_id = vacancy.get("id")
    if source_id is None:
        raise ValueError("Вакансия hh.ru не содержит id")
    salary = vacancy.get("salary") or vacancy.get("salary_range") or {}
    salary_from = salary.get("from")
    salary_to = salary.get("to")
    currency = salary.get("currency") if salary_from or salary_to else None
    if str(currency or "").upper() == "RUB":
        currency = "RUR"
    return {
        "id": stable_numeric_id(f"hh:{source_id}"),
        "title": str(vacancy.get("name") or "Без названия").strip(),
        "salary_from": salary_from,
        "salary_to": salary_to,
        "salary_gross": salary.get("gross") if salary_from or salary_to else None,
        "currency": currency,
        "experience": nested_name(vacancy.get("experience")),
        "employment": nested_name(vacancy.get("employment")),
        "schedule": schedule_label(vacancy),
        "city": nested_name(vacancy.get("area")),
        "skills": extract_skills(vacancy),
        "url": vacancy.get("alternate_url") or vacancy.get("url"),
        "published_at": parse_published_at(vacancy.get("published_at")),
    }


def fetch_vacancies(
    queries: Iterable[str] = DEFAULT_QUERIES,
    max_pages: int = 20,
    per_page: int = 100,
    delay: float = 0.25,
    access_token: str | None = None,
) -> list[dict[str, Any]]:
    normalized_queries = [query.strip() for query in queries]
    if not normalized_queries or any(not query for query in normalized_queries):
        raise ValueError("Поисковый запрос не может быть пустым")
    if not 1 <= max_pages <= 20:
        raise ValueError("max_pages должен быть в диапазоне от 1 до 20")
    if not 1 <= per_page <= 100:
        raise ValueError("per_page должен быть в диапазоне от 1 до 100")
    if max_pages * per_page > 2000:
        raise ValueError("Глубина выдачи hh.ru не может превышать 2000 вакансий")
    if not 0 <= delay <= 30:
        raise ValueError("delay должен быть в диапазоне от 0 до 30 секунд")

    records: dict[int, dict[str, Any]] = {}
    with build_session(access_token or application_token()) as session:
        for query in normalized_queries:
            for page in range(max_pages):
                response = session.get(
                    API_URL,
                    params={
                        "text": query,
                        "search_field": "name",
                        "area": 113,
                        "order_by": "publication_time",
                        "page": page,
                        "per_page": per_page,
                    },
                    timeout=(10, 60),
                )
                if not response.ok:
                    raise RuntimeError(
                        f"Поиск вакансий hh.ru вернул HTTP {response.status_code}"
                    )
                payload = response.json()
                items = payload.get("items") or []
                for vacancy in items:
                    if not TITLE_PATTERN.search(vacancy.get("name") or ""):
                        continue
                    record = vacancy_to_record(vacancy)
                    records[record["id"]] = record

                total_pages = min(int(payload.get("pages") or 0), max_pages)
                if not items or page + 1 >= total_pages:
                    break
                time.sleep(delay)
    return list(records.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Загрузить вакансии аналитиков из официального API hh.ru"
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
        raise RuntimeError("hh.ru не вернул подходящих вакансий аналитиков")
    init_db()
    upsert_vacancies(records)
    print(f"Загружено и обновлено вакансий hh.ru: {len(records)}")


if __name__ == "__main__":
    main()
