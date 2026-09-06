"""
Модуль конфигурации.
Загрузка и управление конфигурацией из YAML-файла.
Добавлена валидация типов данных.
"""

import yaml
import os
from typing import Any, Optional


class Config:
    """
    Загрузка и управление конфигурацией.
    Поддерживает вложенные ключи (например, "sms.api_key").
    """

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
                f"Скопируйте config.example.yaml в config.yaml и заполните значения."
            )

        with open(self.path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get(self, key: str, default: Any = None) -> Any:
        """
        Получить значение по ключу с валидацией.

        Пример:
            config.get("sms.api_key")
            config.get("worker.threads", 10)

        Args:
            key: Ключ (может быть вложенным через точку)
            default: Значение по умолчанию

        Returns:
            Значение или default

        Raises:
            ValueError: Если значение не прошло валидацию
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

        # Валидация типов
        self._validate(key, value)

        return value

    def _validate(self, key: str, value: Any):
        """Валидация значения по ключу."""
        validation_rules = {
            "worker.threads": (int, "worker.threads должен быть целым числом"),
            "worker.total_registrations": (int, "worker.total_registrations должен быть целым числом"),
            "worker.retry_count": (int, "worker.retry_count должен быть целым числом"),
            "sms.max_price": ((int, float), "sms.max_price должен быть числом"),
            "sms.max_sms_wait": (int, "sms.max_sms_wait должен быть целым числом"),
            "sms.timeout": ((int, float), "sms.timeout должен быть числом"),
            "proxy.enabled": (bool, "proxy.enabled должен быть булевым значением"),
        }

        if key in validation_rules:
            expected_types, error_msg = validation_rules[key]
            if not isinstance(value, expected_types):
                raise ValueError(error_msg)

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
        """Перезагрузить конфиг из файла."""
        self.data = self._load()

    def __repr__(self):
        return f"Config({self.path})"
