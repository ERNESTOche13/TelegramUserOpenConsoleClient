# Telegram Sender

Аккуратная Python-программа для отправки сообщения пользователям Telegram через MTProto с использованием Telethon. Скрипт авторизуется как пользователь Telegram, сохраняет локальную session-сессию и повторно использует ее при следующих запусках.

Программа предназначена только для отправки сообщений пользователям, которым разрешено вам писать. Не используйте ее для спама, обхода ограничений Telegram или скрытой массовой отправки.

## Что используется

- Python 3
- asyncio
- Telethon
- MTProto

## Получение api_id и api_hash

1. Откройте https://my.telegram.org.
2. Войдите под своим номером Telegram.
3. Откройте раздел API development tools.
4. Создайте приложение и получите `api_id` и `api_hash`.

Не публикуйте `api_hash`, `telegram_config.json` и session-файлы.

## Установка на Windows PowerShell

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Настройка

При первом запуске, если `telegram_config.json` отсутствует, скрипт спросит:

- `api_id`
- `api_hash`
- `phone`

После этого он создаст локальный `telegram_config.json`. Код подтверждения Telegram и пароль 2FA не сохраняются. Пароль 2FA вводится через скрытый ввод.

Можно заранее скопировать пример из `telegram_config.example.json` в `telegram_config.json` и заменить значения на свои.

## usernames.txt

В `usernames.txt` укажите пользователей, которым нужно отправить сообщение. Один username на одной строке.

Поддерживаемые форматы:

```text
username
@username
https://t.me/username
http://t.me/username
t.me/username
```

Пустые строки и строки, начинающиеся с `#`, игнорируются. Дубли удаляются без учета регистра.

## message.txt

В `message.txt` укажите текст сообщения. Сообщение может быть многострочным.

## Запуск

```powershell
python main.py
```

При первом входе Telegram запросит код подтверждения. Если включена двухфакторная аутентификация, скрипт запросит пароль 2FA скрытым вводом.

## Сессия и безопасность

Session-файл хранится в `sessions/telegram_user.session`. Его нельзя публиковать, отправлять другим людям или коммитить. Этот файл дает доступ к пользовательской Telegram-сессии.

`telegram_config.json` тоже нельзя публиковать или коммитить, потому что он содержит `api_hash` и номер телефона. Эти пути добавлены в `.gitignore`.

Скрипт не выводит в консоль `api_hash`, код подтверждения, пароль 2FA, session string или содержимое session-файла.

## Ограничения Telegram

Между отправками установлена пауза 60 секунд.

Если Telegram возвращает `FloodWaitError`, скрипт ждет указанное Telegram количество секунд плюс небольшой запас и затем пробует отправить сообщение этому пользователю еще раз.

Если Telegram возвращает `PeerFloodError`, скрипт записывает ошибку в `logs/failed_log.csv` и останавливает выполнение. Обход PeerFlood, FloodWait, антиспам-ограничений, прокси-ротация, мультиаккаунты и другие агрессивные механики не реализованы.

## Логи

Логи создаются локально в папке `logs/`:

- `sent_log.csv`
- `failed_log.csv`

Формат CSV:

```text
datetime,username,status,details
```

Папка `logs/` добавлена в `.gitignore`.
