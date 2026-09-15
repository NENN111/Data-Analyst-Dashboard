"""Загрузка вакансий аналитиков из официального API «Хабр Карьеры»."""

from __future__ import annotations

import argparse
import os
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from db import init_db, upsert_vacancies
from trudvsem_etl import TITLE_PATTERN, parse_published_at, stable_numeric_id


API_URL = "https://career.habr.com/api/v1/integrations/vacancies"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "DataAnalystDashboard/2.0 "
        "(+https://github.com/NENN111/Data-Analyst-Dashboard)"
    ),
}


def build_session() -> requests.Session:
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def normalize_currency(value: str | None) -> str | None:
    if not value:
        return None
    currency = value.upper()
    return "RUR" if currency in {"RUB", "RUR"} else currency


def experience_label(vacancy: dict[str, Any]) -> str:
    qualification = vacancy.get("qualification") or {}
    title = qualification.get("title") or {}
    return title.get("ru") or title.get("en") or "Не указан"


def city_label(vacancy: dict[str, Any]) -> str:
    if vacancy.get("city"):
        return str(vacancy["city"])
    locations = vacancy.get("locations") or []
    cities = [
        location.get("title")
        for location in locations
        if location.get("title")
    ]
    return ", ".join(cities) or "Не указан"


def vacancy_to_record(vacancy: dict[str, Any]) -> dict[str, Any]:
    salary = vacancy.get("expanded_salary") or {}
    remote = bool(vacancy.get("remote"))
    skills = {
        str(skill.get("title")).strip()
        for skill in vacancy.get("skills") or []
        if skill.get("title") and len(str(skill["title"]).strip()) <= 80
    }
    source_id = vacancy.get("id")
    if source_id is None:
        raise ValueError("Вакансия Хабр Карьеры не содержит id")
    return {
        # Префикс источника исключает пересечение с ID «Работы России».
        "id": stable_numeric_id(f"habr-career:{source_id}"),
        "title": vacancy.get("title") or "Без названия",
        "salary_from": salary.get("from"),
        "salary_to": salary.get("to"),
        "salary_gross": None,
        "currency": normalize_currency(salary.get("currency")),
        "experience": experience_label(vacancy),
        "employment": vacancy.get("employment_type"),
        "schedule": "Удаленная работа" if remote else "Не удаленная работа",
        "city": city_label(vacancy),
        "skills": sorted(skills, key=str.casefold),
        "url": vacancy.get("url"),
        "published_at": parse_published_at(vacancy.get("published_at")),
    }


def fetch_vacancies(access_token: str, max_pages: int = 100) -> list[dict[str, Any]]:
    """Загружает все страницы активных опубликованных вакансий пользователя."""
    if not access_token:
        raise ValueError("Не задан access token Хабр Карьеры")
    if not 1 <= max_pages <= 1000:
        raise ValueError("max_pages должен быть в диапазоне от 1 до 1000")

    records: dict[int, dict[str, Any]] = {}
    with build_session() as session:
        for page in range(max_pages):
            response = session.get(
                API_URL,
                params={"access_token": access_token, "page": page},
                timeout=(10, 60),
            )
            if not response.ok:
                # Не включаем URL запроса: API требует токен в query string.
                raise RuntimeError(
                    f"API Хабр Карьеры вернул HTTP {response.status_code}"
                )
            payload = response.json()
            items = payload.get("vacancies") or []
            for vacancy in items:
                title = vacancy.get("title") or ""
                if not vacancy.get("published") or not TITLE_PATTERN.search(title):
                    continue
                record = vacancy_to_record(vacancy)
                records[record["id"]] = record

            pagination = payload.get("pagination") or {}
            per_page = int(pagination.get("per") or len(items) or 1)
            total = int(pagination.get("total") or 0)
            if not items or (page + 1) * per_page >= total:
                break
        else:
            raise RuntimeError(
                "Достигнут лимит страниц Хабр Карьеры; увеличьте --max-pages"
            )
    return list(records.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Загрузить вакансии аналитиков из API Хабр Карьеры"
    )
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()

    access_token = os.getenv("HABR_CAREER_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise RuntimeError(
            "Не задан HABR_CAREER_ACCESS_TOKEN. Зарегистрируйте и активируйте "
            "приложение Хабр Карьеры, затем сохраните access token в окружении."
        )

    init_db()
    records = fetch_vacancies(access_token, args.max_pages)
    upsert_vacancies(records)
    print(f"Загружено и обновлено вакансий из Хабр Карьеры: {len(records)}")


if __name__ == "__main__":
    main()
