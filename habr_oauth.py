"""Одноразовое получение OAuth2 access token для API «Хабр Карьеры»."""

from __future__ import annotations

import argparse
from getpass import getpass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import requests


AUTHORIZE_URL = "https://career.habr.com/integrations/oauth/authorize"
TOKEN_URL = "https://career.habr.com/integrations/oauth/token"
DEFAULT_REDIRECT_URI = "http://localhost:8501/"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    query: dict[str, list[str]] = {}

    def do_GET(self) -> None:  # noqa: N802 - имя задаётся BaseHTTPRequestHandler
        type(self).query = parse_qs(urlparse(self.path).query)
        body = (
            "<html><body><h2>Код OAuth получен.</h2>"
            "<p>Можно вернуться в терминал.</p></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def save_access_token(token: str, env_path: Path = Path(".env")) -> None:
    """Обновляет только access token, сохраняя остальные параметры .env."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    setting = f"HABR_CAREER_ACCESS_TOKEN={token}"
    result: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("HABR_CAREER_ACCESS_TOKEN="):
            result.append(setting)
            replaced = True
        else:
            result.append(line)
    if not replaced:
        if result and result[-1]:
            result.append("")
        result.append(setting)
    env_path.write_text("\n".join(result) + "\n", encoding="utf-8")


def receive_authorization_code(
    client_id: str, redirect_uri: str, timeout: int = 300
) -> str:
    parsed_redirect = urlparse(redirect_uri)
    if parsed_redirect.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("OAuth-помощник поддерживает только локальный Redirect URI")
    if parsed_redirect.path not in {"", "/"}:
        raise ValueError("Для OAuth-помощника Redirect URI должен оканчиваться на /")

    state = secrets.token_urlsafe(32)
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
    )
    authorization_url = f"{AUTHORIZE_URL}?{query}"
    server = HTTPServer(
        (parsed_redirect.hostname or "localhost", parsed_redirect.port or 80),
        OAuthCallbackHandler,
    )
    server.timeout = timeout
    print("Открываю страницу авторизации Хабр Карьеры в браузере...")
    if not webbrowser.open(authorization_url):
        print(f"Откройте ссылку вручную:\n{authorization_url}")
    server.handle_request()
    server.server_close()

    callback = OAuthCallbackHandler.query
    if callback.get("error"):
        raise RuntimeError(f"Авторизация отклонена: {callback['error'][0]}")
    if callback.get("state", [None])[0] != state:
        raise RuntimeError("Некорректный state в OAuth callback")
    code = (callback.get("code") or callback.get("authorization_code") or [None])[0]
    if not code:
        raise RuntimeError("Хабр Карьера не вернула authorization code")
    return code


def exchange_code(
    client_id: str, client_secret: str, redirect_uri: str, code: str
) -> str:
    response = requests.post(
        TOKEN_URL,
        params={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code": code,
        },
        timeout=(10, 60),
    )
    if not response.ok:
        raise RuntimeError(f"Обмен OAuth-кода завершился HTTP {response.status_code}")
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Ответ OAuth не содержит access_token")
    return str(token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Получить токен API Хабр Карьеры")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    args = parser.parse_args()

    client_id = input("Client ID: ").strip()
    client_secret = getpass("Client Secret: ").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Client ID и Client Secret обязательны")

    code = receive_authorization_code(client_id, args.redirect_uri)
    token = exchange_code(client_id, client_secret, args.redirect_uri, code)
    save_access_token(token)
    print("Access token сохранён в .env как HABR_CAREER_ACCESS_TOKEN.")


if __name__ == "__main__":
    main()
