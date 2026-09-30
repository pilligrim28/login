# MassReg

Массовая регистрация аккаунтов (Microsoft/Outlook, Snapchat). Единый вход —
**CLI с терминальным интерфейсом [Textual](https://textual.textualize.io/)**.

## Установка

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py setup          # создать .env из .env.example
# отредактируйте .env: SMS__API_KEY, PROXY__*, BROWSER__BACKEND
python -m playwright install chromium   # только если используете chromium-backend
```

## Запуск

```bash
python main.py                       # TUI (Textual): логи породно, автозапуск
python main.py --no-autostart        # TUI, старт вручную (клавиша r)
python main.py run --no-tui          # обычный консольный вывод логов
python main.py check                 # проверить конфигурацию (баланс, прокси, БД)
python main.py doctor                # диагностика окружения (пакеты, браузеры)
python main.py status                # краткий статус
python main.py logs -n 100           # последние строки лога
python main.py reset --confirm --all # очистить локальные данные
```

Клавиши TUI: `r` запуск · `s` стоп · `c` очистить логи · `q` выход.
Внизу — строка команд: `run | stop | clear | quit`.

## Архитектура

```
main.py            CLI (typer): команды запуска/диагностики, точка входа в TUI
core/tui.py        Textual TUI: очередь логов -> построчный вывод, статистика
workers/worker.py  Единый воркер: asyncio + Semaphore (параллельность)
core/services.py   Реестр сервисов -> классы регистраторов
core/registrator.py      Тонкие обёртки (sync/async клиенты равноправны)
core/registrator_async.py Ядро регистрации (Playwright/Camoufox)
core/sms*.py, partner_api.py  Клиенты SMS-провайдеров
core/proxy_manager.py    Пул прокси
core/database.py         SQLite/PostgreSQL учётных записей
core/config.py           Настройки из .env (SECTION__FIELD) + pydantic
```

Настройки читаются из `.env` (см. `.env.example`). Логи пишутся в `logs/<дата>.log`.
