"""Streamlit-дашборд вакансий Data Analyst из PostgreSQL."""

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import text

from db import engine


REMOTE_SCHEDULE = "Удаленная работа"
MEDIAN_SALARY_SQL = """CASE
    WHEN salary_from IS NOT NULL AND salary_to IS NOT NULL THEN (salary_from + salary_to) / 2.0
    ELSE COALESCE(salary_from, salary_to)
END"""


@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    """Кэшированно загружает данные PostgreSQL для всех визуализаций."""
    query = text(f"""
        SELECT id, title, salary_from, salary_to, salary_gross, currency,
               experience, employment, schedule, city, skills, url, published_at,
               {MEDIAN_SALARY_SQL} AS median_salary
        FROM vacancies
        ORDER BY published_at DESC NULLS LAST
    """)
    return pd.read_sql_query(query, engine)


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
    return pd.read_sql_query(query, engine)


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


st.set_page_config(page_title="HH.ru: Data Analyst", page_icon="📊", layout="wide")
st.title("Вакансии Data Analyst на HH.ru")
st.caption("Источник: API HH.ru. Данные хранятся в PostgreSQL.")

try:
    df = load_data()
except Exception as error:
    st.error(f"Не удалось прочитать PostgreSQL: {error}")
    st.info("Проверьте .env, запустите PostgreSQL и выполните `python etl.py`.")
    st.stop()

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
        st.plotly_chart(skills_chart, use_container_width=True)
    with right:
        salary_chart = px.box(rub_salary, x="experience", y="median_salary", points="outliers", title="Зарплата по уровню опыта", labels={"experience": "Опыт", "median_salary": "Зарплата, ₽"})
        st.plotly_chart(salary_chart, use_container_width=True)

    st.subheader("Вакансии")
    table = filtered_df.rename(columns={"title": "Название", "city": "Город", "experience": "Опыт", "schedule": "График", "salary_from": "Зарплата от", "salary_to": "Зарплата до", "currency": "Валюта", "skills": "Навыки", "url": "Ссылка"})
    st.dataframe(table[["Название", "Город", "Опыт", "График", "Зарплата от", "Зарплата до", "Валюта", "Навыки", "Ссылка"]], hide_index=True, use_container_width=True, column_config={"Ссылка": st.column_config.LinkColumn("Ссылка", display_text="Открыть вакансию")})

with sql_tab:
    st.subheader("Средняя зарплата по грейдам")
    st.caption("Результат SQL-запроса с GROUP BY experience; учитываются только рублёвые зарплаты.")
    try:
        st.dataframe(load_salary_by_experience(), hide_index=True, use_container_width=True)
    except Exception as error:
        st.error(f"Не удалось выполнить агрегирующий запрос: {error}")
