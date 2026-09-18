"""Application settings loaded from environment variables and ``.env``."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsSection(BaseModel):
    """Base model for sections that may receive deployment-specific options."""

    model_config = ConfigDict(extra="allow")


class SmsSettings(SettingsSection):
    api_key: str = ""
    api_url: str = ""
    partner_url: str = ""
    service: str = "Microsoft"
    services: list[str] = Field(default_factory=list)
    country: str = "all"
    max_price: float = 0
    timeout: float = 30
    max_sms_wait: int = 300


class ProxySettings(SettingsSection):
    enabled: bool = False
    mode: str = "static"
    type: str = "http"
    proxies: list[str] = Field(default_factory=list)
    rotation_url: str = ""
    dead_timeout: int = 300


class WorkerSettings(SettingsSection):
    threads: int = 10
    total_registrations: int = 100
    headless: bool = True
    retry_count: int = 3
    min_balance: float = 20


class DatabaseSettings(SettingsSection):
    type: str = "sqlite"
    sqlite_path: str = "accounts.db"
    postgres_url: str = ""


class MlSettings(SettingsSection):
    enabled: bool = True
    model_path: str = "ml_model.json"
    min_samples: int = 10


class BrowserSettings(SettingsSection):
    backend: str = "camoufox"


class CamoufoxSettings(SettingsSection):
    enabled: bool = True
    headless: bool = True
    locale: str = "ru-RU"
    timezone_id: str = "Europe/Moscow"
    viewport_width: int = 1366
    viewport_height: int = 768
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    persistent_context: bool = False
    debug: bool = False


class Settings(BaseSettings):
    """Validated application settings with nested ``__`` environment keys."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="allow",
    )

    sms: SmsSettings = Field(default_factory=SmsSettings)
    proxy: ProxySettings = Field(default_factory=ProxySettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    ml: MlSettings = Field(default_factory=MlSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    camoufox: CamoufoxSettings = Field(default_factory=CamoufoxSettings)


class Config:
    """
    Compatibility facade for existing callers using dotted keys.

    Configuration is read from ``.env`` and process environment variables.
    Nested variables use the ``SECTION__FIELD`` form, for example
    ``SMS__API_KEY``.
    """

    def __init__(self, path: str = ".env"):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path != ".env" and not os.path.exists(self.path):
            raise FileNotFoundError(
                f"Файл конфигурации '{self.path}' не найден. "
                "Создайте .env на основе .env.example."
            )

        env_file = self.path if os.path.exists(self.path) else ".env"
        settings = Settings(_env_file=env_file if os.path.exists(env_file) else None)
        return settings.model_dump()

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
            "browser.backend": (str, "browser.backend должен быть строковым значением"),
            "camoufox.enabled": (bool, "camoufox.enabled должен быть булевым значением"),
            "camoufox.headless": (bool, "camoufox.headless должен быть булевым значением"),
            "camoufox.debug": (bool, "camoufox.debug должен быть булевым значением"),
            "camoufox.viewport_width": (int, "camoufox.viewport_width должен быть целым числом"),
            "camoufox.viewport_height": (int, "camoufox.viewport_height должен быть целым числом"),
            "camoufox.persistent_context": (bool, "camoufox.persistent_context должен быть булевым значением"),
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
        """Save current values as dotenv-compatible environment variables."""
        path = self.path if Path(self.path).suffix == ".env" else ".env"
        lines = []
        for section, values in self.data.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                env_key = f"{section.upper()}__{key.upper()}"
                if isinstance(value, list):
                    value = json.dumps(value)
                lines.append(f"{env_key}={value}")
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def reload(self):
        """Reload settings from the environment and dotenv file."""
        self.data = self._load()

    def __repr__(self):
        return f"Config({self.path})"
