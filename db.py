"""Подключение к PostgreSQL и ORM-модель вакансии."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, String, Text, create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

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


# pool_pre_ping проверяет соединение перед использованием, а pool_recycle
# предотвращает работу с простаивающим соединением после таймаута облачного хоста.
engine = create_engine(database_url(), pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# Запросы дашборда независимы и не требуют общей транзакции. Отдельный
# engine сохраняет транзакции ETL и не запускает лишнюю проверку hstore:
# навыки в этом проекте хранятся в JSON, а не в hstore.
read_engine = create_engine(
    database_url(),
    isolation_level="AUTOCOMMIT",
    use_native_hstore=False,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"connect_timeout": 15},
)


class Base(DeclarativeBase):
    """Базовый класс SQLAlchemy ORM-моделей."""


class Vacancy(Base):
    """Вакансия HH.ru; ID HH используется как первичный ключ."""

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
    """Вставляет вакансии или обновляет запись при совпадении ID HH.ru."""
    if not vacancies_data:
        return
    statement = insert(Vacancy).values(vacancies_data)
    update_columns = {
        column.name: getattr(statement.excluded, column.name)
        for column in Vacancy.__table__.columns
        if column.name != "id"
    }
    statement = statement.on_conflict_do_update(index_elements=[Vacancy.id], set_=update_columns)
    with SessionLocal.begin() as session:
        session.execute(statement)
