# HH.ru Data Analyst Dashboard

Streamlit-дашборд анализирует вакансии `Data Analyst` из HH.ru. Вакансии и
навыки хранятся в PostgreSQL; повторная загрузка обновляет записи по ID HH.ru.

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
Запуск дашборда сам по себе не загружает вакансии из HH.ru: для этого служит ETL.
Для независимых SELECT дашборд использует отдельное соединение с AUTOCOMMIT
без проверки hstore; транзакционное соединение ETL остаётся отдельным.

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
   python etl.py --pages 5
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
4. Запустите workflow **Daily HH ETL** вручную один раз в разделе Actions либо
   дождитесь ежедневного запуска в 03:00 UTC. Скрипт создаст таблицу и выполнит
   UPSERT, поэтому его безопасно запускать ежедневно.

Для локального окружения используйте URL вида
`postgresql+psycopg2://user:password@host:5432/database`. URL Render с
префиксом `postgres://` также поддерживается: приложение заменит его на
`postgresql://` перед созданием SQLAlchemy engine.
