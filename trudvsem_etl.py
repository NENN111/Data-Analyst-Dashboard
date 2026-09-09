"""Загрузка вакансий аналитиков из открытого API «Работа России»."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import re
from typing import Any
from uuid import UUID

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from db import init_db, upsert_vacancies


API_URL = "https://opendata.trudvsem.ru/api/v1/vacancies"
HEADERS = {
    "User-Agent": (
        "DataAnalystDashboard/2.0 "
        "(+https://github.com/NENN111/Data-Analyst-Dashboard)"
    )
}
SKILL_PATTERNS = {
    "SQL": r"\bsql\b",
    "Python": r"\bpython\b",
    "R": r"(?:^|\W)r(?:$|\W)",
    "Excel": r"\bexcel\b",
    "Power BI": r"\bpower\s*bi\b",
    "Tableau": r"\btableau\b",
    "ClickHouse": r"\bclickhouse\b",
    "PostgreSQL": r"\bpostgres(?:ql)?\b",
    "Oracle": r"\boracle\b",
    "Spark": r"\bspark\b",
    "Hadoop": r"\bhadoop\b",
    "ETL": r"\betl\b",
    "Google Analytics": r"\bgoogle analytics\b",
}
TITLE_PATTERN = re.compile(
    r"аналитик(?:а|ом|у|и)?\s+(?:больших\s+)?данных|data\s+analyst|"
    r"product\s+analyst|продуктов(?:ый|ого)\s+аналитик",
    flags=re.IGNORECASE,
)


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


def stable_numeric_id(source_id: str) -> int:
    """Преобразует строковый ID источника в стабильный положительный BIGINT."""
    try:
        value = UUID(source_id).int
    except ValueError:
        value = int.from_bytes(
            hashlib.blake2b(source_id.encode("utf-8"), digest_size=8).digest(),
            "big",
        )
    return value & ((1 << 63) - 1)


def parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def extract_skills(vacancy: dict[str, Any]) -> list[str]:
    """Берёт явные навыки и дополняет их технологиями из требований."""
    skills: set[str] = set()
    for skill in vacancy.get("skills") or []:
        name = skill.get("name") if isinstance(skill, dict) else str(skill)
        if name and len(name.strip()) <= 80:
            skills.add(name.strip())

    text = " ".join(
        str(vacancy.get(field) or "")
        for field in ("requirements", "qualification", "duty")
    )
    for name, pattern in SKILL_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            skills.add(name)
    return sorted(skills, key=str.casefold)


def experience_label(vacancy: dict[str, Any]) -> str:
    years = (vacancy.get("requirement") or {}).get("experience")
    if not years:
        return "Не указан"
    years = int(years)
    suffix = "года" if years == 1 else "лет"
    return f"От {years} {suffix}"


def vacancy_to_record(vacancy: dict[str, Any]) -> dict[str, Any]:
    salary_from = vacancy.get("salary_min") or None
    salary_to = vacancy.get("salary_max") or None
    employment = vacancy.get("employment")
    schedule = vacancy.get("schedule")
    if employment and "удален" in employment.casefold():
        schedule = "Удаленная работа"
    return {
        "id": stable_numeric_id(vacancy["id"]),
        "title": vacancy.get("job-name") or "Без названия",
        "salary_from": salary_from,
        "salary_to": salary_to,
        "salary_gross": None,
        "currency": "RUR" if salary_from or salary_to else None,
        "experience": experience_label(vacancy),
        "employment": employment,
        "schedule": schedule or "Не указан",
        "city": (vacancy.get("region") or {}).get("name") or "Не указан",
        "skills": extract_skills(vacancy),
        "url": vacancy.get("vac_url"),
        "published_at": parse_published_at(
            vacancy.get("creation-date") or vacancy.get("date_modify")
        ),
    }


def fetch_vacancies(
    query: str = "аналитик данных", pages: int = 5, per_page: int = 100
) -> list[dict[str, Any]]:
    if not 1 <= pages <= 100:
        raise ValueError("pages должен быть в диапазоне от 1 до 100")
    if not 1 <= per_page <= 100:
        raise ValueError("per_page должен быть в диапазоне от 1 до 100")

    records: dict[int, dict[str, Any]] = {}
    with build_session() as session:
        for page in range(pages):
            response = session.get(
                API_URL,
                params={"text": query, "offset": page, "limit": per_page},
                timeout=(10, 60),
            )
            response.raise_for_status()
            items = response.json().get("results", {}).get("vacancies", [])
            for item in items:
                vacancy = item.get("vacancy", item)
                if not TITLE_PATTERN.search(vacancy.get("job-name") or ""):
                    continue
                record = vacancy_to_record(vacancy)
                records[record["id"]] = record
            if len(items) < per_page:
                break
    return list(records.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Загрузить вакансии аналитиков из API «Работа России»"
    )
    parser.add_argument("--query", default="аналитик данных")
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--per-page", type=int, default=100)
    args = parser.parse_args()

    init_db()
    records = fetch_vacancies(args.query, args.pages, args.per_page)
    if not records:
        raise RuntimeError("Источник не вернул ни одной вакансии")
    upsert_vacancies(records)
    print(f"Загружено и обновлено вакансий: {len(records)}")


if __name__ == "__main__":
    main()
