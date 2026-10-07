"""Чтение PostgreSQL Neon через его HTTPS SQL endpoint с тайм-аутами."""

import json
import time
from datetime import datetime

import pandas as pd
import requests
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.sql.elements import TextClause

from db import database_url


def neon_http_endpoint() -> str | None:
    host = make_url(database_url()).host or ""
    if not host.startswith("ep-") or not host.endswith(".neon.tech"):
        return None
    # Та же схема адресации, что в официальном @neondatabase/serverless.
    return "https://api." + host.split(".", 1)[1] + "/sql"


def read_neon_sql(query: TextClause) -> pd.DataFrame:
    """Возвращает типизированную страницу, повторяя только сетевые ошибки."""
    endpoint = neon_http_endpoint()
    if endpoint is None:
        raise ValueError("HTTPS SQL доступен только для подключения Neon")
    url = make_url(database_url()).set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    compiled = query.compile(dialect=postgresql.dialect(paramstyle="numeric_dollar"))
    params = []
    for name in compiled.positiontup or ():
        value = compiled.params[name]
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, bool):
            value = "true" if value else "false"
        elif value is not None:
            value = str(value)
        params.append(value)
    for attempt in range(2):
        try:
            with requests.post(
                endpoint,
                headers={
                    "Neon-Connection-String": url,
                    "Neon-Raw-Text-Output": "true",
                    "Neon-Array-Mode": "true",
                },
                json={"query": str(compiled), "params": params},
                timeout=(5, 15),
                # Строка с паролем никогда не пересылается другому хосту.
                allow_redirects=False,
            ) as response:
                if response.status_code in (429, 502, 503, 504) and attempt == 0:
                    time.sleep(1)
                    continue
                if response.status_code != 200:
                    # Не включаем тело ответа/заголовки с секретами в исключение.
                    raise RuntimeError(f"Neon SQL HTTP: {response.status_code}")
                result = response.json()
            break
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 1:
                raise RuntimeError("Neon не ответил вовремя. Повторите загрузку.") from None
            time.sleep(1)

    fields = result["fields"]
    frame = pd.DataFrame(result["rows"], columns=[field["name"] for field in fields])
    for field in fields:
        column, oid = field["name"], field["dataTypeID"]
        if oid in (20, 21, 23, 700, 701, 1700):
            frame[column] = pd.to_numeric(frame[column])
        elif oid == 16:
            frame[column] = frame[column].map({"t": True, "f": False}).astype("boolean")
        elif oid in (114, 3802):
            frame[column] = frame[column].map(
                lambda value: None if pd.isna(value) else json.loads(value)
            )
        elif oid in (1114, 1184):
            frame[column] = pd.to_datetime(frame[column], format="mixed", utc=True)
    return frame
