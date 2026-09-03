# HH.ru Data Analyst Dashboard

Streamlit-дашборд анализирует вакансии `Data Analyst` из HH.ru. Вакансии и
навыки хранятся в PostgreSQL; повторная загрузка обновляет записи по ID HH.ru.

## Локальный запуск

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
