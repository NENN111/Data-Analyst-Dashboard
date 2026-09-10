# Data Analyst Vacancies Dashboard

Streamlit-дашборд анализирует вакансии аналитиков из открытых данных
[«Работа России»](https://trudvsem.ru/). Вакансии и навыки хранятся в
PostgreSQL; повторная загрузка обновляет записи по стабильному ID источника.

## Локальный запуск

### На своём ПК с базой на Render

Локальный PostgreSQL и Docker для этого варианта не нужны.

1. Создайте окружение и установите зависимости:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. В корне проекта создайте `.env` и укажите `DATABASE_URL`: полный **External Database URL**
   из Render. Для шифрования добавьте `?sslmode=require` (или `&sslmode=require`,
   если в URL уже есть параметры). `.env` и `.venv` исключены из Git.

3. Запустите `start-dashboard.cmd` двойным щелчком либо из PowerShell:

   ```powershell
   .\start-dashboard.cmd
   ```

   Дашборд доступен по адресу http://localhost:8501. Чтобы остановить его,
   нажмите Ctrl+C в окне запуска. Следующий запуск — той же командой.

Кнопка «Обновить данные» перечитывает базу, минуя пятиминутный кэш.
Запуск дашборда сам по себе не загружает вакансии: для этого служит ETL.
Чтобы обновить базу вручную, выполните:

```powershell
.\.venv\Scripts\python.exe trudvsem_etl.py --pages 5
```

ETL обращается к открытому API, нормализует зарплаты, регионы, графики и навыки,
а затем обновляет PostgreSQL. Для независимых запросов используется AUTOCOMMIT.

## Полезные SELECT-запросы

Запросы можно выполнять в Render Shell, `psql`, DBeaver или другом клиенте,
подключённом к той же базе. Они только читают таблицу `vacancies`.

Общее состояние данных:

```sql
SELECT
    COUNT(*) AS vacancies_total,
    COUNT(*) FILTER (
        WHERE salary_from IS NOT NULL OR salary_to IS NOT NULL
    ) AS vacancies_with_salary,
    COUNT(DISTINCT city) AS cities_total,
    MIN(published_at) AS oldest_publication,
    MAX(published_at) AS newest_publication
FROM vacancies;
```

Последние опубликованные вакансии:

```sql
SELECT title, city, salary_from, salary_to, currency, published_at, url
FROM vacancies
ORDER BY published_at DESC NULLS LAST
LIMIT 20;
```

Средняя оценка зарплаты по требуемому опыту:

```sql
SELECT
    COALESCE(experience, 'Не указан') AS experience,
    COUNT(*) AS vacancies_count,
    ROUND(AVG(
        CASE
            WHEN salary_from IS NOT NULL AND salary_to IS NOT NULL
                THEN (salary_from + salary_to) / 2.0
            ELSE COALESCE(salary_from, salary_to)
        END
    )) AS average_salary_rub
FROM vacancies
WHERE currency = 'RUR'
  AND COALESCE(salary_from, salary_to) IS NOT NULL
GROUP BY experience
ORDER BY average_salary_rub DESC NULLS LAST;
```

Десять самых частых навыков из JSON-массивов:

```sql
SELECT skill, COUNT(*) AS vacancies_count
FROM vacancies
CROSS JOIN LATERAL json_array_elements_text(skills) AS skill
GROUP BY skill
ORDER BY vacancies_count DESC, skill
LIMIT 10;
```

Распределение вакансий по регионам:

```sql
SELECT city, COUNT(*) AS vacancies_count
FROM vacancies
GROUP BY city
ORDER BY vacancies_count DESC, city;
```

### С локальной PostgreSQL в Docker

1. Создайте `.env` из шаблона и укажите строку подключения PostgreSQL:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Поднимите базу и установите зависимости:

   ```powershell
   docker compose up -d
   pip install -r requirements.txt
   ```

3. Загрузите вакансии и запустите интерфейс:

   ```powershell
   python trudvsem_etl.py --pages 5
   streamlit run app.py
   ```

## Деплой на Render

1. Загрузите проект в GitHub и в Render выберите **New → Blueprint**, указав
   репозиторий. Render применит [render.yaml](render.yaml): создаст PostgreSQL
   и веб-сервис, а `DATABASE_URL` передаст приложению автоматически. В Blueprint
   задан план `0.5c-512mb`, чтобы сервис не приостанавливался в отсутствие трафика;
   перед деплоем проверьте стоимость плана в своём аккаунте Render.
2. После первого деплоя откройте веб-сервис. База в этот момент будет пустой.
3. В настройках PostgreSQL Render скопируйте **External Database URL** и в
   GitHub добавьте секрет репозитория `DATABASE_URL` со скопированным значением.
   Внешний URL нужен, потому что GitHub Actions подключается не из сети Render.
4. Запустите workflow **Daily Vacancies ETL** вручную один раз в разделе Actions либо
   дождитесь ежедневного запуска в 03:00 UTC. Скрипт создаст таблицу и выполнит
   UPSERT, поэтому его безопасно запускать ежедневно.

Для локального окружения используйте URL вида
`postgresql+psycopg2://user:password@host:5432/database`. URL Render с
префиксом `postgres://` также поддерживается: приложение заменит его на
`postgresql://` перед созданием SQLAlchemy engine.

## Имена инфраструктурных ресурсов

Новые локальные окружения используют нейтральные имена `data-analyst-postgres` и
`vacancies_analytics`. Имена `hh-vacancies-dashboard`, `hh-vacancies-postgres`,
`hh_analytics` и `hh_user` в `render.yaml` намеренно сохранены: они идентифицируют
уже существующие ресурсы Render. Простая замена этих значений в Blueprint может
создать новые ресурсы, а `databaseName` и `user` существующей Render Postgres
изменить нельзя. Полное переименование требует создания новой базы, переноса
данных, переключения `DATABASE_URL` и только затем удаления старой базы.
