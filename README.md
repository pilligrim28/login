# MassReg - Массовая регистрация аккаунтов

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

**MassReg** — инструмент для массовой регистрации аккаунтов Microsoft (Outlook) с использованием:
- **SMS-Activate** для получения номеров телефонов и SMS-кодов
- **Proxy** (IPRoyal, статические прокси, rotation URL) для обхода блокировок
- **Playwright** для автоматизации браузера
- **SQLite/PostgreSQL** для хранения аккаунтов

## 🚀 Возможности

- ✅ Массовая регистрация аккаунтов Microsoft/Outlook
- ✅ Автоматическая аренда номеров через SMS-Activate
- ✅ Поддержка прокси (IPRoyal, статические, rotation URL)
- ✅ Обработка CAPTCHA (обнаружение и уведомление)
- ✅ Хранение аккаунтов в SQLite или PostgreSQL
- ✅ Многопоточная работа
- ✅ CLI, GUI и REST API интерфейсы
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

### Установка Playwright
```bash
playwright install chromium
```

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
Скопируйте и отредактируйте `config.yaml`:
```bash
cp config.yaml config.yaml
nano config.yaml  # или используйте любой редактор
```

Пример конфигурации:
```yaml
sms:
  api_key: "VAШ_API_КЛЮЧ_OT_SMS_ACTIVATE"
  service: "Microsoft"
  country: "all"
  max_price: 0

proxy:
  enabled: true
  type: "http"
  proxies:
    - "host:port:username:password"
    - "host2:port2"

worker:
  threads: 5
  total_registrations: 50
  headless: true

database:
  type: "sqlite"
  sqlite_path: "accounts.db"
```

## 🏃‍♂️ Запуск

### CLI интерфейс
```bash
# Проверить настройки
python main.py --check

# Запустить регистрацию (синхронно)
python main.py

# Запустить регистрацию (асинхронно)
python main_async.py
```

### GUI интерфейс
```bash
python desktop/run_desktop.py
```

### REST API сервер
```bash
python server/run_server.py
```

API будет доступен на `http://localhost:8000`

## 📡 REST API

### Аутентификация
Все запросы требуют API-ключ в заголовке:
```
Authorization: Bearer ВАШ_API_КЛЮЧ
```

Настройте ключ в `config.yaml`:
```yaml
server:
  api_key: "ВАШ_СЕКРЕТНЫЙ_КЛЮЧ"
```

### Эндпоинты

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| GET | `/` | Статус сервера |
| GET | `/health` | Проверка здоровья |
| GET | `/balance` | Получить баланс SMS-Activate |
| GET | `/stats` | Статистика аккаунтов |
| GET | `/accounts` | Список аккаунтов |
| GET | `/accounts/{email}` | Получить аккаунт по email |
| POST | `/start` | Запустить регистрацию |
| POST | `/stop` | Остановить регистрацию |
| GET | `/progress` | Прогресс регистрации |
| POST | `/config/sms` | Настроить SMS |
| POST | `/config/server` | Настроить сервер |
| DELETE | `/accounts/{id}` | Удалить аккаунт |
| POST | `/clear-accounts` | Очистить все аккаунты |

### Примеры запросов

**Получить баланс:**
```bash
curl -H "Authorization: Bearer ВАШ_API_КЛЮЧ" http://localhost:8000/balance
```

**Запустить регистрацию:**
```bash
curl -X POST -H "Authorization: Bearer ВАШ_API_КЛЮЧ" \
  -H "Content-Type: application/json" \
  -d '{"total": 100, "threads": 10}' \
  http://localhost:8000/start
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
Убедитесь, что вы указали правильный API-ключ от SMS-Activate в `config.yaml`:
```yaml
sms:
  api_key: "ВАШ_API_КЛЮЧ"
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
python main.py --config config.yaml
```

С конфигурацией:
```yaml
worker:
  total_registrations: 100
  threads: 10
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

### Запуск REST API сервера
```bash
python server/run_server.py
```

## 🐳 Docker

### Сборка образа
```bash
docker build -t massreg .
```

### Запуск контейнера
```bash
docker run -it --rm \
  -v $(pwd)/config.yaml:/app/config.yaml \
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
