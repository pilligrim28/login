import logging
import os
from datetime import datetime


class Logger:
    """Централизованное логирование."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_logger()
        return cls._instance

    def _init_logger(self):
        """Инициализация логгера."""
        os.makedirs("logs", exist_ok=True)

        self.logger = logging.getLogger("MassReg")
        self.logger.setLevel(logging.INFO)

        # Файловый handler
        date_str = datetime.now().strftime("%Y-%m-%d")
        fh = logging.FileHandler(f"logs/{date_str}.log", encoding="utf-8")
        fh.setLevel(logging.INFO)

        # Консольный handler
        ch = logging.StreamHandler()
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