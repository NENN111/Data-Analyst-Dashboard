# Техническое руководство

Инструкция для тех, кто хочет запустить дашборд, загрузить вакансии или проверить данные. Краткое описание проекта находится в [README](../README.md).

## Локальный запуск

### С локальной PostgreSQL в Docker

Для команд ниже нужны Python 3.11+, Docker и PowerShell.

1. Создайте `.env` из шаблона. В шаблоне уже указана строка подключения к контейнеру:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Поднимите базу, создайте окружение и установите зависимости:

   ```powershell
   docker compose up -d
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Загрузите вакансии и запустите интерфейс:

   ```powershell
   .\.venv\Scripts\python.exe trudvsem_etl.py --pages 5
   .\.venv\Scripts\python.exe -m streamlit run app.py
   ```

### На своём ПК с базой в Neon

Локальный PostgreSQL и Docker для этого варианта не нужны.

1. Создайте окружение и установите зависимости:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. В Neon откройте **Connect → Connection string**, включите **Connection pooling**
   и скопируйте полный PostgreSQL URL. В корне проекта создайте `.env` и укажите
   его как `DATABASE_URL`, сохранив параметры `sslmode=require&channel_binding=require`.
   Адрес REST API с `/rest/v1` для приложения не подходит. `.env` и `.venv` исключены из Git.

   Если база новая, сначала создайте таблицы:

   ```powershell
   .\.venv\Scripts\python.exe -c "from db import init_db; init_db()"
   ```

   Затем перенесите старые данные либо запустите загрузчики из раздела ниже.

3. Запустите `start-dashboard.cmd` двойным щелчком либо из PowerShell:

   ```powershell
   .\start-dashboard.cmd
   ```

   Дашборд доступен по адресу http://localhost:8501. Чтобы остановить его,
   нажмите Ctrl+C в окне запуска. Следующий запуск — той же командой.

Локальный скрипт читает базу страницами по 50 вакансий в одном потоке. Для Neon чтение идёт через HTTPS с тайм-аутами и ограниченным повтором сетевых запросов. Результат кэшируется на час; кнопка «Обновить данные» загружает его повторно. При запуске приложения напрямую также используются страницы по 50 вакансий, а кэш хранится пять минут.

## Загрузка вакансий

Запуск интерфейса сам по себе не обновляет данные в базе. Запускайте загрузчики нужных источников отдельно; для hh.ru, SuperJob и API «Хабр Карьеры» предварительно настройте доступ:

```powershell
.\.venv\Scripts\python.exe trudvsem_etl.py --pages 5
.\.venv\Scripts\python.exe hh_etl.py
.\.venv\Scripts\python.exe superjob_etl.py
.\.venv\Scripts\python.exe habr_public_etl.py
.\.venv\Scripts\python.exe habr_career_etl.py
```

### hh.ru

Для hh.ru сохраните в `.env` Client ID и Client Secret зарегистрированного
приложения (либо готовый токен приложения):

```dotenv
HH_CLIENT_ID=ваш_client_id
HH_CLIENT_SECRET=ваш_client_secret
# Альтернатива двум строкам выше:
# HH_ACCESS_TOKEN=готовый_access_token
```

`hh_etl.py` получает OAuth2-токен приложения, ищет вакансии аналитиков по России,
обходит выдачу в пределах установленного API лимита 2000 результатов, приводит
зарплату, опыт, занятость, формат работы, город и навыки к общей схеме и выполняет
UPSERT по стабильному ID `hh:<id>`. Client Secret и токен не записываются в код и
не выводятся в сообщения об ошибках.

### SuperJob

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

### Публичный каталог «Хабр Карьеры»

`habr_public_etl.py` собирает публичные карточки вакансий аналитиков, соблюдает
разрешения `robots.txt`, обходит пагинацию с паузой между запросами и не касается
профилей, откликов или других персональных данных.

### API «Хабр Карьеры»

Перед запуском `habr_career_etl.py` задайте `HABR_CAREER_ACCESS_TOKEN` в `.env`.
Официальный API Хабр Карьеры предназначен для интеграции с CRM и отдаёт только
оплаченные вакансии пользователя, разрешившего доступ приложению, а не весь
публичный каталог. Этот дополнительный загрузчик сохраняет опубликованные вакансии аналитиков авторизованного аккаунта, обходит страницы ответа, нормализует зарплаты, города, грейды и навыки, а затем выполняет UPSERT в ту же таблицу PostgreSQL.

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
2. Для Neon сохраните параметры шифрования из выданной строки подключения; для Render используйте `sslmode=require`.
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

## Деплой на Render

1. Создайте PostgreSQL в Neon и скопируйте pooled connection string из **Connect**.
   Загрузите проект в GitHub и в Render выберите **New → Blueprint**, указав
   репозиторий. Render применит [render.yaml](../render.yaml): создаст веб-сервис.
   Укажите строку Neon как `DATABASE_URL` при создании Blueprint. В Blueprint
   задан план `0.5c-512mb`, чтобы сервис не приостанавливался в отсутствие трафика;
   перед деплоем проверьте стоимость плана в своём аккаунте Render.
2. Для существующего сервиса замените `DATABASE_URL` в **Environment** на строку
   Neon и перезапустите деплой. `sync: false` не обновляет значение автоматически
   при синхронизации существующего Blueprint. После первого деплоя новой базы
   создайте таблицы и загрузите вакансии; интерфейс сам таблицы не создаёт.
3. В GitHub добавьте или обновите секрет репозитория `DATABASE_URL` той же строкой
   Neon: **Settings → Secrets and variables → Actions**. Пароль храните только
   в `.env`, Render Environment и GitHub Secrets.
4. Добавьте секреты `HH_CLIENT_ID` и `HH_CLIENT_SECRET` приложения hh.ru либо
   один секрет `HH_ACCESS_TOKEN` с готовым токеном приложения.
5. Добавьте в GitHub секрет `HABR_CAREER_ACCESS_TOKEN` с OAuth2 access token
   активированного приложения Хабр Карьеры.
6. Добавьте секрет `SUPERJOB_API_KEY` с Secret key приложения SuperJob. Пока
   секрет не задан, соответствующий шаг workflow будет безопасно пропущен.
7. Запустите workflow **Daily Vacancies ETL** вручную один раз в разделе Actions либо
   дождитесь ежедневного запуска в 03:00 UTC. Скрипт создаст таблицу и выполнит
   UPSERT данных из источников, поэтому его безопасно запускать ежедневно.
   Ошибка одного источника не останавливает остальные шаги, но весь запуск
   отмечается как неуспешный. Если не задан доступ к hh.ru, его шаг явно падает:
   проверьте секреты `HH_ACCESS_TOKEN` либо `HH_CLIENT_ID` и `HH_CLIENT_SECRET`.

Для локального окружения используйте URL вида
`postgresql+psycopg2://user:password@host:5432/database`. URL Render с
префиксом `postgres://` также поддерживается: приложение заменит его на
`postgresql://` перед созданием SQLAlchemy engine.

Дашборд читает Neon через HTTPS SQL endpoint: это соединение с той же базой
и теми же учётными данными из `DATABASE_URL`, без отдельного ключа REST API.
Страницы по 50 строк ограничивают размер ответа; каждый HTTP-запрос имеет
тайм-аут подключения 5 секунд и ожидания данных 15 секунд, сетевой сбой
повторяется один раз. Для остальных PostgreSQL используется SQLAlchemy.
Локальный запуск `start-dashboard.cmd` использует один загрузчик и кэш на час;
кнопка обновления в боковой панели сбрасывает кэш.

## Имена инфраструктурных ресурсов

Новые локальные окружения используют нейтральные имена `data-analyst-postgres` и
`vacancies_analytics`. Историческое имя веб-сервиса в `render.yaml` сохранено:
оно идентифицирует существующий ресурс Render. База управляется отдельно в Neon.
Перед удалением старой Render Postgres перенесите нужные данные и проверьте,
что веб-сервис и GitHub Actions используют новую строку подключения.
