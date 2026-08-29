"""
Модуль конфигурации.
Загрузка и управление YAML-конфигом.
"""

import yaml
import os
from typing import Any, Optional


class Config:
    """Загрузка и управление конфигурацией."""

    def __init__(self, path: str = "config.yaml"):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        """
        Загрузить конфиг из файла.

        Raises:
            FileNotFoundError: если файл не найден
        """
        if not os.path.exists(self.path):
            raise FileNotFoundError(
                f"Файл конфигурации '{self.path}' не найден.\n"
                f"Создайте config.yaml на основе шаблона."
            )

        with open(self.path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get(self, key: str, default: Any = None) -> Any:
        """
        Получить значение по ключу через точку.

        Пример:
            config.get("sms.api_key")
            config.get("worker.threads", 10)
        """
        keys = key.split(".")
        value = self.data

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

            if value is None:
                return default

        return value

    def set(self, key: str, value: Any):
        """
        Установить значение по ключу.

        Пример:
            config.set("sms.api_key", "abc123")
        """
        keys = key.split(".")
        data = self.data

        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            data = data[k]

        data[keys[-1]] = value

    def save(self):
        """Сохранить конфиг в файл."""
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(self.data, f, default_flow_style=False, allow_unicode=True)

    def reload(self):
        """Перезагрузить из файла."""
        self.data = self._load()

    def __repr__(self):
        return f"Config({self.path})"