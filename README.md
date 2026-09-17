# Data Analyst Vacancies Dashboard

Streamlit-дашборд анализирует вакансии аналитиков из открытых данных
[«Работа России»](https://trudvsem.ru/), официального API
[SuperJob](https://api.superjob.ru/) и публичного каталога
[«Хабр Карьеры»](https://career.habr.com/). Вакансии и навыки хранятся в
PostgreSQL; повторная загрузка обновляет записи по стабильному ID источника.

## Возможности дашборда

Интерфейс состоит из трёх вкладок:

- **Обзор рынка** — число вакансий, медианная зарплата, доля удалённой работы,
  полнота зарплатных данных, востребованные навыки, распределение зарплат по
  опыту и география вакансий.
- **Вакансии** — таблица текущей выборки с должностью, городом, опытом, форматом
  работы, оценкой зарплаты, навыками и ссылкой на источник.
- **Методика** — правила расчёта показателей и агрегированная зарплата по опыту.

В боковой панели доступны поиск по названию и навыкам, фильтры по городу,
формату работы и опыту, а также отбор вакансий с указанной зарплатой. Пустой
список в фильтре означает «показать все значения». Кнопка «Сбросить фильтры»
возвращает исходную выборку, а «Обновить данные» перечитывает PostgreSQL,
минуя пятиминутный кэш.

Названия городов нормализуются при отображении: варианты `Город Москва` и
`Москва` объединяются, а перечисления вроде `Москва, Санкт-Петербург`
разделяются для фильтра и географического графика. Такая вакансия остаётся одной
строкой в каталоге, но учитывается в статистике каждого указанного города.

Требования к опыту из разных источников также приводятся к общей шкале:
`Без опыта / Intern`, `1–2 года / Junior`, `3–4 года / Middle`,
`5+ лет / Senior`, `Не указан`. Например, `Senior`, `От 5 лет` и `От 6 лет`
отображаются одной группой. Эта шкала используется в фильтре, зарплатном
boxplot и таблицах.

Оценка зарплаты рассчитывается как середина вилки. Если указана только одна
граница, используется она. В зарплатных показателях учитываются только вакансии
с валютой `RUR`.

## Структура проекта

| Путь | Назначение |
| --- | --- |
| `app.py` | Загрузка данных, фильтрация и компоненты Streamlit |
| `dashboard.css` | Визуальные стили дашборда |
| `.streamlit/config.toml` | Тема и минимальный режим панели Streamlit |
| `db.py` | Подключение к PostgreSQL, модель и UPSERT |
| `trudvsem_etl.py` | Загрузка открытых данных «Работы России» |
| `superjob_etl.py` | Загрузка открытых вакансий через API SuperJob |
| `habr_public_etl.py` | Загрузка публичного каталога «Хабр Карьеры» |
| `habr_career_etl.py` | Дополнительная загрузка через OAuth API |
| `tests/` | Модульные тесты ETL и расчётов дашборда |

Минимальный режим панели в `.streamlit/config.toml` скрывает служебное меню
зрителя, включая запись экрана. Подробности исключений также не показываются в
браузере; полная ошибка остаётся в консоли процесса.

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

Запуск дашборда сам по себе не загружает вакансии: для этого служит ETL.
Чтобы обновить базу вручную, выполните:

```powershell
.\.venv\Scripts\python.exe trudvsem_etl.py --pages 5
.\.venv\Scripts\python.exe superjob_etl.py
.\.venv\Scripts\python.exe habr_public_etl.py
.\.venv\Scripts\python.exe habr_career_etl.py
```

Для SuperJob зарегистрируйте приложение в [официальном кабинете
API](https://api.superjob.ru/register/) и сохраните выданный **Secret key** в
`.env`:

```dotenv
SUPERJOB_API_KEY=ваш_secret_key
```

Загрузчик запрашивает открытые вакансии по трём направлениям: аналитик данных,
data analyst и продуктовый аналитик. Он обходит страницы ответа, отбрасывает
нерелевантные заголовки, нормализует основные поля и выполняет UPSERT по
стабильному ID `superjob:<id>`. Повторный запуск обновляет существующие записи,
а не создаёт копии. Дополнительные запросы можно передать несколько раз:

```powershell
.\.venv\Scripts\python.exe superjob_etl.py `
  --query "аналитик данных" `
  --query "продуктовый аналитик" `
  --max-pages 20
```

`habr_public_etl.py` собирает публичные карточки вакансий аналитиков, соблюдает
разрешения `robots.txt`, обходит пагинацию с паузой между запросами и не касается
профилей, откликов или других персональных данных.

Перед запуском третьего скрипта задайте `HABR_CAREER_ACCESS_TOKEN` в `.env`.
Официальный API Хабр Карьеры предназначен для интеграции с CRM и отдаёт только
оплаченные вакансии пользователя, разрешившего доступ приложению, а не весь
публичный каталог. Этот дополнительный загрузчик сохраняет вакансии аналитиков
авторизованного аккаунта, а публичный каталог загружает предыдущая команда.
Загрузчик API сохраняет опубликованные вакансии аналитиков этого
аккаунта, обходит все страницы ответа, нормализует зарплаты, города, грейды и
навыки, а затем выполняет UPSERT в ту же таблицу PostgreSQL.

Чтобы получить токен, зарегистрируйте и активируйте приложение на странице
[приложений Хабр Карьеры](https://career.habr.com/profile/applications), пройдите
OAuth 2.0 по [официальной документации](https://career.habr.com/info/api) и
сохраните полученный `access_token` только в `.env` или секрете GitHub.
Для Redirect URI `http://localhost:8501/` токен можно получить локально:

```powershell
.\.venv\Scripts\python.exe habr_oauth.py
```

Помощник запросит Client ID и Client Secret без сохранения, откроет браузер и
запишет полученный access token в игнорируемый файл `.env`.

## Проверка

Запустите все тесты из корня проекта:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Быстрая проверка синтаксиса:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py db.py tests
```

## Подключение к PostgreSQL

Если дашборд показывает сообщение «Не удалось подключиться к базе данных»:

1. Проверьте, что в `.env` указан полный внешний URL PostgreSQL без кавычек.
2. Для Render используйте шифрование `sslmode=require`.
3. Убедитесь, что экземпляр PostgreSQL запущен и принимает внешние подключения.
4. Проверьте соединение из обычного терминала. Ошибка Windows `10013 Permission
   denied` обычно означает, что исходящее подключение заблокировано локальной
   политикой, антивирусом или сетевой песочницей.

Дашборд читает данные небольшими страницами и повторяет запрос до трёх раз после
операционной ошибки соединения. Пользователю показывается безопасное сообщение,
без строки подключения и внутреннего стека.

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
4. Добавьте в GitHub секрет `HABR_CAREER_ACCESS_TOKEN` с OAuth2 access token
   активированного приложения Хабр Карьеры.
5. Добавьте секрет `SUPERJOB_API_KEY` с Secret key приложения SuperJob. Пока
   секрет не задан, соответствующий шаг workflow будет безопасно пропущен.
6. Запустите workflow **Daily Vacancies ETL** вручную один раз в разделе Actions либо
   дождитесь ежедневного запуска в 03:00 UTC. Скрипт создаст таблицу и выполнит
   UPSERT данных из источников, поэтому его безопасно запускать ежедневно.

Для локального окружения используйте URL вида
`postgresql+psycopg2://user:password@host:5432/database`. URL Render с
префиксом `postgres://` также поддерживается: приложение заменит его на
`postgresql://` перед созданием SQLAlchemy engine.

## Имена инфраструктурных ресурсов

Новые локальные окружения используют нейтральные имена `data-analyst-postgres` и
`vacancies_analytics`. Исторические имена в `render.yaml` намеренно сохранены: они
идентифицируют уже существующие ресурсы Render. Простая замена этих значений в Blueprint может
создать новые ресурсы, а `databaseName` и `user` существующей Render Postgres
изменить нельзя. Полное переименование требует создания новой базы, переноса
данных, переключения `DATABASE_URL` и только затем удаления старой базы.
