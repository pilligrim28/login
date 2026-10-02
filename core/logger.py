import logging
import os
from datetime import datetime

from core.log_handlers import SafeRotatingFileHandler, ThreadSafeStreamHandler


class Logger:
    """
    Централизованное логирование.
    Поддержка ротации логов (макс. 5 файлов по 10MB).

    Используются защищённые хендлеры (core/log_handlers.py):
    - SafeRotatingFileHandler — не падает с "--- Logging error --- /
      OSError: [Errno 22]" при ротации на Windows;
    - ThreadSafeStreamHandler — корректная запись из многих потоков.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_logger()
        return cls._instance

    def _init_logger(self):
        """Инициализация логгера с ротацией файлов."""
        os.makedirs("logs", exist_ok=True)

        self.logger = logging.getLogger("MassReg")
        self.logger.setLevel(logging.INFO)
        # Не всплываем в root-логгер (Textual/сторонние библиотеки могут
        # повесить на root свои хендлеры и дублировать вывод).
        self.logger.propagate = False

        # Очистка повторной инициализации (например, после reload в тестах)
        for h in list(self.logger.handlers):
            self.logger.removeHandler(h)

        # Файловый handler с ротацией (безопасный для Windows)
        date_str = datetime.now().strftime("%Y-%m-%d")
        fh = SafeRotatingFileHandler(
            f"logs/{date_str}.log",
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,              # 5 резервных файлов
            encoding="utf-8",
        )
        fh.setLevel(logging.INFO)

        # Консольный handler (потокобезопасный)
        ch = ThreadSafeStreamHandler()
        ch.setLevel(logging.INFO)

        # Формат
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

    def info(self, message: str):
        self.logger.info(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)

    def debug(self, message: str):
        self.logger.debug(message)

    def success(self, message: str):
        self.logger.info(message)


# Глобальный экземпляр
log = Logger()
