"""Подключение к PostgreSQL и ORM-модель вакансии."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

load_dotenv()  # Локальные секреты читаются из игнорируемого Git файла .env.


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


# Для Neon повторно используем соединения, чтобы чтение страниц не требовало
# отдельного TLS-подключения каждый раз. Проверка перед запросом восстанавливает
# соединение после простоя базы. Для остальных окружений сохраняем NullPool.
connection_url = database_url()
connection_host = make_url(connection_url).host or ""
pool_options: dict[str, Any] = (
    {"pool_size": 4, "max_overflow": 0, "pool_pre_ping": True, "pool_recycle": 300}
    if connection_host.endswith(".neon.tech")
    else {"poolclass": NullPool}
)
engine = create_engine(
    connection_url,
    isolation_level="AUTOCOMMIT",
    use_native_hstore=False,
    connect_args={"connect_timeout": 15},
    **pool_options,
)

# Для обычного PostgreSQL дашборд использует этот engine; Neon читается по HTTPS.
# Навыки хранятся в JSON, поэтому определение PostgreSQL hstore отключено выше.
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
    # Пакеты сокращают число сетевых запросов к PostgreSQL.
    # При разрыве повторяем текущий пакет; UPSERT не создаёт дубликатов.
    connection = None
    try:
        for offset in range(0, len(unique_rows), 5):
            statement = insert(Vacancy).values(unique_rows[offset : offset + 5])
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
