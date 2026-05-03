from __future__ import annotations

import asyncio
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from getpass import getpass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    RPCError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "telegram_config.json"
USERNAMES_PATH = BASE_DIR / "usernames.txt"
MESSAGE_PATH = BASE_DIR / "message.txt"
SESSIONS_DIR = BASE_DIR / "sessions"
LOGS_DIR = BASE_DIR / "logs"
SESSION_PATH = SESSIONS_DIR / "telegram_user.session"
SENT_LOG_PATH = LOGS_DIR / "sent_log.csv"
FAILED_LOG_PATH = LOGS_DIR / "failed_log.csv"

SEND_INTERVAL_SECONDS = 60
FLOOD_WAIT_EXTRA_SECONDS = 5
CSV_HEADER = ["datetime", "username", "status", "details"]


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    phone: str


class PeerFloodStop(RuntimeError):
    """Internal signal to stop the whole script after Telegram peer flood response."""


def ensure_local_dirs() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def load_or_create_config() -> TelegramConfig:
    if not CONFIG_PATH.exists():
        print("Файл telegram_config.json не найден. Введите данные Telegram API.")
        api_id_raw = input("api_id: ").strip()
        api_hash = input("api_hash: ").strip()
        phone = input("phone: ").strip()

        try:
            api_id = int(api_id_raw)
        except ValueError as exc:
            raise ValueError("api_id должен быть числом.") from exc

        if not api_hash:
            raise ValueError("api_hash не должен быть пустым.")
        if not phone:
            raise ValueError("phone не должен быть пустым.")

        data = {"api_id": api_id, "api_hash": api_hash, "phone": phone}
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("Создан telegram_config.json. Коды подтверждения и пароль 2FA не сохраняются.")
        return TelegramConfig(api_id=api_id, api_hash=api_hash, phone=phone)

    try:
        data: dict[str, Any] = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("telegram_config.json содержит некорректный JSON.") from exc

    try:
        api_id = int(data["api_id"])
        api_hash = str(data["api_hash"]).strip()
        phone = str(data["phone"]).strip()
    except KeyError as exc:
        raise ValueError(f"В telegram_config.json отсутствует поле: {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError("В telegram_config.json поле api_id должно быть числом.") from exc

    if not api_hash:
        raise ValueError("В telegram_config.json поле api_hash пустое.")
    if not phone:
        raise ValueError("В telegram_config.json поле phone пустое.")

    return TelegramConfig(api_id=api_id, api_hash=api_hash, phone=phone)


def normalize_username(raw_username: str) -> str:
    username = raw_username.strip()

    if username.startswith(("https://t.me/", "http://t.me/")):
        parsed = urlparse(username)
        username = parsed.path.strip("/").split("/", maxsplit=1)[0]
    elif username.startswith("t.me/"):
        parsed = urlparse(f"https://{username}")
        username = parsed.path.strip("/").split("/", maxsplit=1)[0]

    username = username.strip().lstrip("@").strip()
    username = username.split("?", maxsplit=1)[0].split("#", maxsplit=1)[0].strip("/")
    return username


def create_example_usernames_file() -> None:
    USERNAMES_PATH.write_text(
        "# Один username на строку\n"
        "# Поддерживаются форматы: username, @username, https://t.me/username\n"
        "example_user\n",
        encoding="utf-8",
    )


def read_usernames() -> list[str]:
    if not USERNAMES_PATH.exists():
        create_example_usernames_file()
        raise FileNotFoundError(
            "Файл usernames.txt не найден. Создан пример usernames.txt; заполните его и запустите скрипт снова."
        )

    usernames: list[str] = []
    seen: set[str] = set()

    for line in USERNAMES_PATH.read_text(encoding="utf-8-sig").splitlines():
        raw_line = line.strip()
        if not raw_line or raw_line.startswith("#"):
            continue

        username = normalize_username(raw_line)
        if not username:
            continue

        username_key = username.casefold()
        if username_key in seen:
            continue

        seen.add(username_key)
        usernames.append(username)

    if not usernames:
        raise ValueError("Файл usernames.txt пустой или не содержит username для отправки.")

    return usernames


def create_example_message_file() -> None:
    MESSAGE_PATH.write_text(
        "Здравствуйте!\n\n"
        "Это пример сообщения. Замените текст перед запуском рассылки.\n",
        encoding="utf-8",
    )


def read_message() -> str:
    if not MESSAGE_PATH.exists():
        create_example_message_file()
        raise FileNotFoundError(
            "Файл message.txt не найден. Создан пример message.txt; заполните его и запустите скрипт снова."
        )

    message = MESSAGE_PATH.read_text(encoding="utf-8-sig").strip()
    if not message:
        raise ValueError("Файл message.txt пустой. Добавьте текст сообщения и запустите скрипт снова.")

    return message


def append_csv_log(path: Path, row: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        if needs_header:
            writer.writerow(CSV_HEADER)
        writer.writerow(row)


def utc_now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_error_details(error: BaseException) -> str:
    details = str(error).replace("\r", " ").replace("\n", " ").strip()
    if not details:
        return error.__class__.__name__
    return f"{error.__class__.__name__}: {details}"


def log_sent(username: str, status: str, details: str = "") -> None:
    append_csv_log(SENT_LOG_PATH, [utc_now_iso(), username, status, details])


def log_failed(username: str, status: str, details: str) -> None:
    append_csv_log(FAILED_LOG_PATH, [utc_now_iso(), username, status, details])


async def send_once(client: TelegramClient, username: str, message: str) -> None:
    await client.send_message(username, message)


async def wait_after_flood(error: FloodWaitError) -> int:
    wait_seconds = int(error.seconds) + FLOOD_WAIT_EXTRA_SECONDS
    print(f"Telegram вернул FloodWaitError. Ожидание {wait_seconds} секунд.")
    await asyncio.sleep(wait_seconds)
    return wait_seconds


async def send_message_to_user(client: TelegramClient, username: str, message: str) -> None:
    flood_wait_total_seconds = 0

    while True:
        try:
            await send_once(client, username, message)
        except FloodWaitError as error:
            flood_wait_total_seconds += await wait_after_flood(error)
            continue
        except PeerFloodError as retry_error:
            details = safe_error_details(retry_error)
            log_failed(username, "peer_flood_stop", details)
            print("[STOP] Telegram ограничил отправку похожих сообщений. Скрипт остановлен.")
            raise PeerFloodStop(details) from retry_error
        except Exception as retry_error:  # noqa: BLE001 - all retry failures have one CSV status by requirement.
            status = classify_failure_status(retry_error, flood_wait_total_seconds > 0)
            details = safe_error_details(retry_error)
            log_failed(username, status, details)
            print_failure(username, status, details, flood_wait_total_seconds)
            return

        if flood_wait_total_seconds > 0:
            log_sent(username, "sent_after_flood_wait", f"waited_seconds={flood_wait_total_seconds}")
            print("[OK] Отправлено после ожидания FloodWait.")
        else:
            log_sent(username, "sent")
            print("[OK]")
        return


def classify_failure_status(error: BaseException, after_flood_wait: bool) -> str:
    if after_flood_wait:
        return "failed_after_flood_wait"
    if isinstance(error, UsernameInvalidError):
        return "username_invalid"
    if isinstance(error, UsernameNotOccupiedError):
        return "username_not_occupied"
    if isinstance(error, UserPrivacyRestrictedError):
        return "privacy_restricted"
    if isinstance(error, RPCError):
        return "rpc_error"
    return "unexpected_error"


def print_failure(username: str, status: str, details: str, flood_wait_total_seconds: int) -> None:
    if status == "failed_after_flood_wait":
        print(
            f"[FAIL] Не удалось отправить @{username} после ожидания FloodWait "
            f"({flood_wait_total_seconds} секунд): {details}"
        )
    elif status == "username_invalid":
        print(f"[FAIL] Некорректный username: {details}")
    elif status == "username_not_occupied":
        print(f"[FAIL] Username не найден: {details}")
    elif status == "privacy_restricted":
        print(f"[FAIL] Пользователь ограничил получение сообщений: {details}")
    elif status == "rpc_error":
        print(f"[FAIL] Ошибка Telegram RPC: {details}")
    else:
        print(f"[FAIL] Неожиданная ошибка: {details}")


async def main() -> None:
    ensure_local_dirs()
    config = load_or_create_config()
    usernames = read_usernames()
    message = read_message()

    client = TelegramClient(str(SESSION_PATH), config.api_id, config.api_hash)

    await client.start(
        phone=config.phone,
        code_callback=lambda: input("Введите код Telegram: "),
        password=lambda: getpass("Введите пароль 2FA: "),
    )
    print("Вход в Telegram выполнен.")

    try:
        total = len(usernames)
        for index, username in enumerate(usernames, start=1):
            print(f"[{index}/{total}] Отправка пользователю @{username}")
            await send_message_to_user(client, username, message)

            if index < total:
                print(f"Пауза {SEND_INTERVAL_SECONDS} секунд перед следующей отправкой.")
                await asyncio.sleep(SEND_INTERVAL_SECONDS)
    except PeerFloodStop:
        return
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (FileNotFoundError, ValueError) as error:
        print(f"Ошибка: {error}")
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
