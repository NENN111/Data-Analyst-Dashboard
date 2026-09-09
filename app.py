"""Streamlit-дашборд вакансий Data Analyst из PostgreSQL."""

import time

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from db import read_engine as engine


REMOTE_SCHEDULE = "Удаленная работа"
MEDIAN_SALARY_SQL = """CASE
    WHEN salary_from IS NOT NULL AND salary_to IS NOT NULL THEN (salary_from + salary_to) / 2.0
    ELSE COALESCE(salary_from, salary_to)
END"""


def read_sql(query) -> pd.DataFrame:
    """Повторяет SELECT после кратковременного разрыва внешнего соединения."""
    for attempt in range(3):
        try:
            return pd.read_sql_query(query, engine)
        except OperationalError:
            engine.dispose()
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Не удалось выполнить SQL-запрос")


@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    """Кэшированно загружает данные небольшими страницами из PostgreSQL."""
    frames: list[pd.DataFrame] = []
    page_size = 5
    offset = 0
    while True:
        query = text(f"""
            SELECT id, title, salary_from, salary_to, salary_gross, currency,
                   experience, employment, schedule, city, skills, url, published_at,
                   {MEDIAN_SALARY_SQL} AS median_salary
            FROM vacancies
            ORDER BY published_at DESC NULLS LAST, id
            LIMIT {page_size} OFFSET {offset}
        """)
        page = read_sql(query)
        frames.append(page)
        if len(page) < page_size:
            break
        offset += page_size
    return pd.concat(frames, ignore_index=True)


@st.cache_data(ttl=300)
def load_salary_by_experience() -> pd.DataFrame:
    """Агрегирующий SQL-запрос для вкладки SQL Playground."""
    query = text(f"""
        SELECT COALESCE(experience, 'Не указан') AS experience,
               COUNT(*) AS vacancies_count,
               ROUND(AVG({MEDIAN_SALARY_SQL})) AS average_salary_rub
        FROM vacancies
        WHERE currency = 'RUR' AND COALESCE(salary_from, salary_to) IS NOT NULL
        GROUP BY experience
        ORDER BY average_salary_rub DESC NULLS LAST
    """)
    return read_sql(query)


def apply_filters(data: pd.DataFrame) -> pd.DataFrame:
    """Отображает фильтры в боковой панели и возвращает результат."""
    st.sidebar.header("Фильтры")
    cities = sorted(data["city"].dropna().unique())
    schedules = sorted(data["schedule"].dropna().unique())
    experiences = sorted(data["experience"].dropna().unique())
    selected_cities = st.sidebar.multiselect("Город", cities, default=cities)
    selected_schedules = st.sidebar.multiselect("График работы", schedules, default=schedules)
    selected_experience = st.sidebar.multiselect("Опыт", experiences, default=experiences)
    return data[
        data["city"].isin(selected_cities)
        & data["schedule"].isin(selected_schedules)
        & data["experience"].isin(selected_experience)
    ].copy()


def top_skills(data: pd.DataFrame) -> pd.DataFrame:
    """Разворачивает JSON-массив навыков и считает десять самых частых."""
    skills = data["skills"].apply(lambda value: value if isinstance(value, list) else []).explode()
    return skills.dropna().value_counts().head(10).rename_axis("Навык").reset_index(name="Вакансий")


def format_rubles(value: float | None) -> str:
    return "—" if pd.isna(value) else f"{value:,.0f} ₽".replace(",", " ")


st.set_page_config(page_title="Вакансии аналитиков", page_icon="📊", layout="wide")
st.title("Вакансии аналитиков данных")
st.caption(
    "Источник: открытые данные [«Работа России»](https://trudvsem.ru/). "
    "Хранилище: PostgreSQL."
)

if st.button("Обновить данные"):
    load_data.clear()
    load_salary_by_experience.clear()

try:
    df = load_data()
except Exception as error:
    st.error(f"Не удалось прочитать PostgreSQL: {error}")
    st.info("Проверьте DATABASE_URL в .env и доступность PostgreSQL.")
    st.stop()

if df.empty:
    st.info("В базе пока нет вакансий. После загрузки нажмите «Обновить данные».")
else:
    published = pd.to_datetime(df["published_at"], errors="coerce")
    if published.notna().any():
        st.caption(
            "Период публикации данных: "
            f"{published.min():%d.%m.%Y} — {published.max():%d.%m.%Y}"
        )

dashboard_tab, sql_tab = st.tabs(["Дашборд", "SQL Playground"])
with dashboard_tab:
    filtered_df = apply_filters(df)
    rub_salary = filtered_df.loc[filtered_df["currency"].eq("RUR") & filtered_df["median_salary"].notna()]
    remote_share = filtered_df["schedule"].eq(REMOTE_SCHEDULE).mean() * 100 if len(filtered_df) else 0

    total, salary, remote = st.columns(3)
    total.metric("Всего вакансий", f"{len(filtered_df):,}".replace(",", " "))
    salary.metric("Медианная зарплата", format_rubles(rub_salary["median_salary"].median()))
    remote.metric("Доля удалёнки", f"{remote_share:.1f}%")
    st.caption("Зарплатные показатели рассчитаны по вакансиям с зарплатой в рублях.")

    left, right = st.columns(2)
    with left:
        skills_chart = px.bar(top_skills(filtered_df), x="Вакансий", y="Навык", orientation="h", title="Топ-10 навыков")
        skills_chart.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(skills_chart, width="stretch")
    with right:
        salary_chart = px.box(rub_salary, x="experience", y="median_salary", points="outliers", title="Зарплата по уровню опыта", labels={"experience": "Опыт", "median_salary": "Зарплата, ₽"})
        st.plotly_chart(salary_chart, width="stretch")

    st.subheader("Вакансии")
    table = filtered_df.rename(columns={"title": "Название", "city": "Город", "experience": "Опыт", "schedule": "График", "salary_from": "Зарплата от", "salary_to": "Зарплата до", "currency": "Валюта", "skills": "Навыки", "url": "Ссылка"})
    st.dataframe(table[["Название", "Город", "Опыт", "График", "Зарплата от", "Зарплата до", "Валюта", "Навыки", "Ссылка"]], hide_index=True, width="stretch", column_config={"Ссылка": st.column_config.LinkColumn("Ссылка", display_text="Открыть вакансию")})

with sql_tab:
    st.subheader("Средняя зарплата по грейдам")
    st.caption("Результат SQL-запроса с GROUP BY experience; учитываются только рублёвые зарплаты.")
    try:
        st.dataframe(load_salary_by_experience(), hide_index=True, width="stretch")
    except Exception as error:
        st.error(f"Не удалось выполнить агрегирующий запрос: {error}")
