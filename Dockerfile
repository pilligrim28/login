# Dockerfile для MassReg
# Многостадийная сборка для уменьшения размера образа

# Первая стадия: сборка зависимостей
FROM python:3.11-slim as builder

WORKDIR /app

# Устанавливаем системные зависимости для Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Для Chromium
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    # Для сборки Python-пакетов
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем требования и устанавливаем Python-пакеты
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Вторая стадия: финальный образ
FROM python:3.11-slim

WORKDIR /app

# Копируем системные библиотеки из builder
COPY --from=builder /usr/lib /usr/lib
COPY --from=builder /usr/share /usr/share

# Копируем Python-пакеты
COPY --from=builder /root/.local /root/.local

# Устанавливаем Playwright и браузеры
ENV PATH=/root/.local/bin:$PATH
RUN playwright install chromium

# Копируем исходный код
COPY . .

# Создаем необходимые директории
RUN mkdir -p logs cookies

# Устанавливаем переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Порт по умолчанию
EXPOSE 8000

# Запуск
CMD ["python", "main.py"]
