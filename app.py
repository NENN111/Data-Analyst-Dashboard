"""Streamlit-дашборд вакансий аналитиков из PostgreSQL."""

from pathlib import Path
import time

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.elements import TextClause

from db import read_engine as engine


REMOTE_SCHEDULE = "Удаленная работа"
MEDIAN_SALARY_SQL = """CASE
    WHEN salary_from IS NOT NULL AND salary_to IS NOT NULL THEN (salary_from + salary_to) / 2.0
    ELSE COALESCE(salary_from, salary_to)
END"""
FILTER_KEYS = ("search_query", "cities", "schedules", "experiences", "salary_only")
CITY_NAMES = {
    "москва": "Москва",
    "санкт-петербург": "Санкт-Петербург",
}


def read_sql(query: TextClause) -> pd.DataFrame:
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
    """Кэшированно загружает данные страницами из PostgreSQL."""
    frames: list[pd.DataFrame] = []
    # Короткие ответы устойчивее проходят через внешнее соединение Render.
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
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def filter_data(
    data: pd.DataFrame,
    query: str = "",
    cities: list[str] | None = None,
    schedules: list[str] | None = None,
    experiences: list[str] | None = None,
    salary_only: bool = False,
) -> pd.DataFrame:
    """Фильтрует выборку; пустой список означает отсутствие ограничения."""
    result = data.copy()
    query = query.strip()
    if query:
        title_match = result["title"].fillna("").str.contains(query, case=False, regex=False)
        skills_match = result["skills"].apply(
            lambda values: query.casefold() in " ".join(values).casefold()
            if isinstance(values, list)
            else False
        )
        result = result[title_match | skills_match]
    if cities:
        selected_cities = set(cities)
        result = result[
            result["city"].apply(
                lambda value: bool(selected_cities.intersection(split_cities(value)))
            )
        ]
    for column, selected in (("schedule", schedules), ("experience", experiences)):
        if selected:
            result = result[result[column].isin(selected)]
    if salary_only:
        result = result[result["median_salary"].notna()]
    return result.copy()


def normalize_city_name(value: str) -> str:
    """Приводит вариант названия города к единому отображению."""
    city = " ".join(value.strip().split())
    if city.casefold().startswith("город "):
        city = city[6:].strip()
    return CITY_NAMES.get(city.casefold(), city or "Не указан")


def split_cities(value: object) -> list[str]:
    """Разделяет перечисление городов и удаляет дубликаты с сохранением порядка."""
    if not isinstance(value, str) or not value.strip():
        return ["Не указан"]
    cities = [normalize_city_name(part) for part in value.split(",")]
    return list(dict.fromkeys(cities))


def city_options(data: pd.DataFrame) -> list[str]:
    """Возвращает отдельные нормализованные города для фильтра."""
    return sorted(
        {city for value in data["city"] for city in split_cities(value)},
        key=str.casefold,
    )


def top_skills(data: pd.DataFrame) -> pd.DataFrame:
    """Разворачивает массив навыков и считает десять самых частых."""
    if data.empty:
        return pd.DataFrame(columns=["Навык", "Вакансий"])
    skills = data["skills"].apply(
        lambda value: value if isinstance(value, list) else []
    ).explode()
    return (
        skills.dropna()
        .value_counts()
        .head(10)
        .rename_axis("Навык")
        .reset_index(name="Вакансий")
    )


def format_rubles(value: float | None) -> str:
    return "—" if pd.isna(value) else f"{value:,.0f} ₽".replace(",", " ")


def load_styles() -> None:
    css_path = Path(__file__).with_name("dashboard.css")
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def reset_filters() -> None:
    for key in FILTER_KEYS:
        st.session_state.pop(key, None)


def render_sidebar(data: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.markdown("### Параметры выборки")
        st.caption("Оставьте список пустым, чтобы видеть все значения.")
        query = st.text_input("Поиск", placeholder="Должность или навык", key="search_query")
        cities = st.multiselect("Город", city_options(data), placeholder="Все города", key="cities")
        schedules = st.multiselect("Формат работы", sorted(data["schedule"].dropna().unique()), placeholder="Все форматы", key="schedules")
        experiences = st.multiselect("Опыт", sorted(data["experience"].dropna().unique()), placeholder="Любой опыт", key="experiences")
        salary_only = st.checkbox("Только с указанной зарплатой", key="salary_only")
        st.button("Сбросить фильтры", width="stretch", on_click=reset_filters)
        st.divider()
        if st.button("Обновить данные", width="stretch", type="primary"):
            load_data.clear()
            st.rerun()
        st.caption("Данные кэшируются на 5 минут.")
    return filter_data(data, query, cities, schedules, experiences, salary_only)


def render_metrics(data: pd.DataFrame) -> None:
    rub_salary = data.loc[data["currency"].eq("RUR") & data["median_salary"].notna()]
    remote_share = data["schedule"].eq(REMOTE_SCHEDULE).mean() * 100 if len(data) else 0
    salary_share = data["median_salary"].notna().mean() * 100 if len(data) else 0
    columns = st.columns(4)
    columns[0].metric("Вакансий", f"{len(data):,}".replace(",", " "))
    columns[1].metric("Медианная зарплата", format_rubles(rub_salary["median_salary"].median()))
    columns[2].metric("Удалённый формат", f"{remote_share:.0f}%")
    columns[3].metric("С указанной зарплатой", f"{salary_share:.0f}%")


def render_overview(data: pd.DataFrame) -> None:
    render_metrics(data)
    st.caption("Зарплатные показатели рассчитаны только для вакансий в рублях.")
    skills_data = top_skills(data)
    rub_salary = data.loc[data["currency"].eq("RUR") & data["median_salary"].notna()]
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Востребованные навыки")
        if skills_data.empty:
            st.info("Для выбранных вакансий навыки не указаны.")
        else:
            chart = px.bar(skills_data, x="Вакансий", y="Навык", orientation="h", color_discrete_sequence=["#0F766E"])
            chart.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})
    with right:
        st.markdown("#### Зарплата по опыту")
        if rub_salary.empty:
            st.info("В выборке нет зарплат в рублях.")
        else:
            chart = px.box(
                rub_salary,
                x="experience",
                y="median_salary",
                points="outliers",
                labels={"experience": "Опыт", "median_salary": "Зарплата, ₽"},
                color_discrete_sequence=["#0F766E"],
            )
            st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})
    st.markdown("#### География вакансий")
    city_data = (
        data["city"]
        .apply(split_cities)
        .explode()
        .value_counts()
        .head(10)
        .rename_axis("Город")
        .reset_index(name="Вакансий")
    )
    city_chart = px.bar(city_data, x="Город", y="Вакансий", color_discrete_sequence=["#5E8078"])
    st.plotly_chart(city_chart, width="stretch", config={"displayModeBar": False})
    st.caption("Вакансия с несколькими локациями учитывается отдельно в каждом указанном городе.")


def render_vacancies(data: pd.DataFrame) -> None:
    st.markdown(f"#### Найдено вакансий: {len(data):,}".replace(",", " "))
    table = data.copy()
    table["city"] = table["city"].apply(lambda value: ", ".join(split_cities(value)))
    table["skills"] = table["skills"].apply(lambda value: ", ".join(value) if isinstance(value, list) else "")
    table = table.rename(columns={"title": "Вакансия", "city": "Город", "experience": "Опыт", "schedule": "Формат", "median_salary": "Оценка зарплаты", "skills": "Навыки", "url": "Ссылка"})
    st.dataframe(
        table[["Вакансия", "Город", "Опыт", "Формат", "Оценка зарплаты", "Навыки", "Ссылка"]],
        hide_index=True,
        width="stretch",
        column_config={
            "Оценка зарплаты": st.column_config.NumberColumn(format="%.0f ₽"),
            "Ссылка": st.column_config.LinkColumn("Источник", display_text="Открыть ↗"),
        },
    )


def render_methodology(data: pd.DataFrame) -> None:
    st.markdown("#### Как читать показатели")
    st.markdown(
        """
        - Если указаны обе границы зарплаты, используется середина вилки; если одна — её значение.
        - В зарплатных графиках учитываются только значения в рублях.
        - Навыки считаются по числу вакансий, в которых они указаны.
        - Данные поступают из открытых источников и могут не отражать весь рынок.
        """
    )
    with st.expander("Средняя зарплата по требуемому опыту"):
        salaries = data.loc[data["currency"].eq("RUR") & data["median_salary"].notna()].copy()
        salaries["experience"] = salaries["experience"].fillna("Не указан")
        summary = (
            salaries.groupby("experience", as_index=False)
            .agg(
                vacancies_count=("id", "count"),
                average_salary_rub=("median_salary", "mean"),
            )
            .sort_values("average_salary_rub", ascending=False)
            .rename(columns={"experience": "Опыт", "vacancies_count": "Вакансий", "average_salary_rub": "Средняя зарплата, ₽"})
        )
        st.dataframe(
            summary,
            hide_index=True,
            width="stretch",
            column_config={"Средняя зарплата, ₽": st.column_config.NumberColumn(format="%.0f ₽")},
        )


def main() -> None:
    st.set_page_config(page_title="Рынок вакансий аналитиков", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
    load_styles()
    st.title("Рынок вакансий аналитиков")
    st.caption("Интерактивный срез открытых вакансий из «Работы России» и «Хабр Карьеры».")
    try:
        with st.spinner("Загружаем актуальную выборку…"):
            data = load_data()
    except Exception:
        st.error("Не удалось подключиться к базе данных.")
        st.info("Проверьте DATABASE_URL и доступность PostgreSQL, затем обновите страницу.")
        st.stop()
    if data.empty:
        st.info("В базе пока нет вакансий. Сначала запустите загрузку данных, затем обновите страницу.")
        st.stop()
    filtered = render_sidebar(data)
    published = pd.to_datetime(data["published_at"], errors="coerce")
    if published.notna().any():
        st.caption(f"Публикации в базе: {published.min():%d.%m.%Y} — {published.max():%d.%m.%Y}")
    if filtered.empty:
        st.warning("По выбранным условиям вакансий нет. Измените параметры или сбросьте фильтры.")
        st.stop()
    overview_tab, vacancies_tab, methodology_tab = st.tabs(["Обзор рынка", "Вакансии", "Методика"])
    with overview_tab:
        render_overview(filtered)
    with vacancies_tab:
        render_vacancies(filtered)
    with methodology_tab:
        render_methodology(filtered)


if __name__ == "__main__":
    main()
