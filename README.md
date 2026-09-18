# MassReg - Массовая регистрация аккаунтов

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

**MassReg** — инструмент для массовой регистрации аккаунтов Microsoft (Outlook) с использованием:
- **SMS-Activate** для получения номеров телефонов и SMS-кодов
- **Proxy** (IPRoyal, статические прокси, rotation URL) для обхода блокировок
- **Camoufox + Playwright** для антидетект браузера и автоматизации
- **SQLite/PostgreSQL** для хранения аккаунтов

## 🚀 Возможности

- ✅ Массовая регистрация аккаунтов Microsoft/Outlook
- ✅ Автоматическая аренда номеров через SMS-Activate
- ✅ Поддержка прокси (IPRoyal, статические, rotation URL)
- ✅ Обработка CAPTCHA (обнаружение и уведомление)
- ✅ Хранение аккаунтов в SQLite или PostgreSQL
- ✅ Многопоточная работа
- ✅ CLI и GUI интерфейсы
- ✅ Асинхронная поддержка
- ✅ Логгирование с ротацией файлов
- ✅ Проверка баланса перед регистрацией
- ✅ Проверка на дубликаты email

## 📋 Требования

### Системные требования
- Python 3.11+
- Linux/Windows/macOS
- Минимально 2GB ОЗУ
- 1GB свободного места на диске

### Python зависимости
```bash
pip install -r requirements.txt
```

Для разработки:
```bash
pip install -r requirements-dev.txt
```

### Установка Playwright и Camoufox
```bash
playwright install chromium
camoufox fetch
```

Если Camoufox ещё не скачан, приложение автоматически попытается выполнить `camoufox fetch` при запуске и, при необходимости, откатится на обычный Chromium.

## 🛠 Установка

### 1. Клонирование репозитория
```bash
git clone https://github.com/pilligrim28/login.git
cd login
```

### 2. Установка зависимостей
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Настройка конфигурации
Скопируйте и отредактируйте `.env`:
```bash
cp .env.example .env
nano .env  # или используйте любой редактор
```

Пример переменных:
```dotenv
SMS__API_KEY=your-api-key
SMS__SERVICE=Microsoft
PROXY__ENABLED=false
PROXY__PROXIES=[]
WORKER__THREADS=5
WORKER__TOTAL_REGISTRATIONS=50
```

## 🏃‍♂️ Запуск

### CLI интерфейс
```bash
# Показать справку
python main.py --help

# Создать .env из шаблона, если файла ещё нет
python main.py setup

# Проверить настройки
python main.py check --config .env

# Показать краткий статус проекта
python main.py status --config .env

# Полная диагностика окружения и браузера
python main.py doctor --config .env

# Посмотреть последние логи
python main.py logs --lines 100

# Запустить регистрацию (синхронно)
python main.py run --config .env

# Запустить регистрацию через Camoufox
python main.py run --config .env --browser camoufox

# Запустить регистрацию через обычный Chromium
python main.py run --config .env --browser chromium

# Запустить регистрацию (асинхронно)
python main.py run --config .env --async

# Сгенерировать рекомендации ML
python main.py ml-suggest --config .env
```

### GUI интерфейс (через единый entrypoint)
```bash
python main.py desktop
# или короткая версия
python main.py gui
```

Для совместимости всё ещё работает старый запуск:
```bash
python desktop/run_desktop.py
```

```

**Получить статистику:**
```bash
curl -H "Authorization: Bearer ВАШ_API_КЛЮЧ" http://localhost:8000/stats
```

## 📊 Конфигурация

### Параметры SMS-Activate

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| `api_key` | API-ключ от SMS-Activate | `""` |
| `api_url` | Кастомный URL API | `""` (используется стандартный) |
| `service` | Сервис для регистрации | `"Microsoft"` |
| `country` | Код страны | `"all"` |
| `max_price` | Максимальная цена за номер | `0` (без лимита) |
| `max_sms_wait` | Максимальное время ожидания SMS | `300` (5 минут) |

### Параметры прокси

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| `enabled` | Включить прокси | `false` |
| `type` | Тип прокси | `"http"` |
| `mode` | Режим работы | `"static"` |
| `proxies` | Список прокси | `[]` |
| `rotation_url` | URL для rotation прокси | `""` |
| `iproyal_api_key` | API-ключ IPRoyal | `""` |
| `iproyal_country` | Страна для IPRoyal | `"all"` |
| `iproyal_length` | Длина сессии IPRoyal | `30` (минуты) |

### Параметры Camoufox

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| `enabled` | Использовать Camoufox вместо стандартного Chromium | `true` |
| `headless` | Запускать браузер в headless режиме | `true` |
| `locale` | Локаль браузера | `"ru-RU"` |
| `timezone_id` | Часовой пояс | `"Europe/Moscow"` |
| `viewport_width` | Ширина окна | `1366` |
| `viewport_height` | Высота окна | `768` |
| `persistent_context` | Переиспользовать persistent context | `false` |
| `debug` | Включить debug режим Camoufox | `false` |

### Параметры воркера

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| `threads` | Количество потоков | `5` |
| `total_registrations` | Общее количество регистраций | `50` |
| `headless` | Режим без графического интерфейса | `true` |
| `retry_count` | Количество повторных попыток | `3` |

### Параметры базы данных

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| `type` | Тип БД | `"sqlite"` |
| `sqlite_path` | Путь к файлу SQLite | `"accounts.db"` |
| `postgres_url` | URL для PostgreSQL | `""` |

## 🔧 Решение проблем

### Ошибка: "API-ключ не настроен"
Убедитесь, что вы указали правильный API-ключ от SMS-Activate в `.env`:
```dotenv
SMS__API_KEY=ВАШ_API_КЛЮЧ
```

### Ошибка: "Недостаточно средств"
Пополните баланс на SMS-Activate. Минимальный баланс для одной регистрации — ~20₽.

### Ошибка: "Обнаружена CAPTCHA"
Microsoft может требовать ввод CAPTCHA. В текущей версии CAPTCHA обнаруживается, но не решается автоматически.

### Ошибка: "Прокси не работают"
Проверьте:
1. Прокси доступны и работают
2. Формат прокси правильный: `host:port:user:pass` или `host:port`
3. Прокси не заблокированы

### Ошибка: "Нет номеров"
Попробуйте:
1. Подождать несколько минут и повторить
2. Изменить страну в настройках
3. Увеличить максимальную цену

## 📈 Примеры использования

### Массовая регистрация 100 аккаунтов
```bash
python main.py --config .env
```

С конфигурацией:
```dotenv
WORKER__TOTAL_REGISTRATIONS=100
WORKER__THREADS=10
```

### Проверка настройки
```bash
python main.py --check
```

### Запуск с асинхронным режимом
```bash
python main_async.py
```

### Запуск GUI
```bash
python desktop/run_desktop.py
```

## 🐳 Docker

### Сборка образа
```bash
docker build -t massreg .
```

### Запуск контейнера
```bash
docker run -it --rm \
  -v $(pwd)/.env:/app/.env \
  -v $(pwd)/accounts.db:/app/accounts.db \
  massreg python main.py --check
```

## 📜 Лицензия

MIT License — см. файл [LICENSE](LICENSE) для деталей.

## 🤝 Вклад

Приветствуются pull request'ы! Перед отправкой:
1. Запустите тесты: `pytest tests/`
2. Проверьте линтинг: `flake8 core/ workers/ server/`
3. Отформатируйте код: `black core/ workers/ server/`

## 📞 Поддержка

Если у вас есть вопросы или проблемы:
1. Проверьте раздел "Решение проблем"
2. Убедитесь, что все зависимости установлены
3. Проверьте логи в директории `logs/`
4. Создайте issue в репозитории

---

**MassReg** — проект с открытым исходным кодом для автоматизации регистрации аккаунтов.
