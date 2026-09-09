"""Подключение к PostgreSQL и ORM-модель вакансии."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, String, Text, create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

load_dotenv()  # .env не коммитится и позволяет хранить пароль вне исходного кода.


def database_url() -> str:
    """Возвращает URL PostgreSQL из окружения, совместимый с SQLAlchemy.

    Render выдаёт строку ``postgres://...``, а современные версии SQLAlchemy
    используют схему ``postgresql://...``. Преобразование выполняется только
    для устаревшего префикса и не меняет остальные параметры URL.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Не задана переменная окружения DATABASE_URL")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


# Render закрывает внешние соединения агрессивнее локального PostgreSQL. NullPool
# создаёт свежее соединение для каждого запроса и не возвращает закрытое в пул.
engine = create_engine(
    database_url(),
    isolation_level="AUTOCOMMIT",
    use_native_hstore=False,
    poolclass=NullPool,
    connect_args={"connect_timeout": 15},
)

# Запросы дашборда независимы и не требуют общей транзакции. Отдельный
# engine сохраняет транзакции ETL и не запускает лишнюю проверку hstore:
# навыки в этом проекте хранятся в JSON, а не в hstore.
read_engine = engine


class Base(DeclarativeBase):
    """Базовый класс SQLAlchemy ORM-моделей."""


class Vacancy(Base):
    """Вакансия из внешнего источника со стабильным числовым ID."""

    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    salary_from: Mapped[int | None] = mapped_column(Integer)
    salary_to: Mapped[int | None] = mapped_column(Integer)
    salary_gross: Mapped[bool | None] = mapped_column(Boolean)
    currency: Mapped[str | None] = mapped_column(String(10))
    experience: Mapped[str | None] = mapped_column(String(100))
    employment: Mapped[str | None] = mapped_column(String(100))
    # Сохраняем график для фильтров и расчёта доли удалённой работы.
    schedule: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(150))
    skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def init_db() -> None:
    """Создаёт таблицы проекта, если они ещё не существуют."""
    Base.metadata.create_all(bind=engine)


def upsert_vacancies(vacancies_data: list[dict[str, Any]]) -> None:
    """Вставляет вакансии или обновляет запись при совпадении ID источника."""
    if not vacancies_data:
        return
    unique_rows = list({row["id"]: row for row in vacancies_data}.values())
    # Небольшие отдельные выражения не перегружают внешний PostgreSQL Render.
    # При сетевом разрыве повторяем только текущую запись через новое соединение.
    connection = None
    try:
        for row in unique_rows:
            statement = insert(Vacancy).values(row)
            update_columns = {
                column.name: getattr(statement.excluded, column.name)
                for column in Vacancy.__table__.columns
                if column.name != "id"
            }
            upsert = statement.on_conflict_do_update(
                index_elements=[Vacancy.id], set_=update_columns
            )
            for attempt in range(3):
                try:
                    if connection is None:
                        connection = engine.connect()
                    connection.execute(upsert)
                    break
                except OperationalError:
                    if connection is not None:
                        connection.close()
                    connection = None
                    engine.dispose()
                    if attempt == 2:
                        raise
                    time.sleep(2**attempt)
    finally:
        if connection is not None:
            connection.close()
