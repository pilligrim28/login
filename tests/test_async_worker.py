"""Тесты для асинхронного воркера"""

import pytest
import asyncio
import tempfile
import os
import yaml
from unittest.mock import AsyncMock, MagicMock, patch
from workers.async_worker import AsyncWorker
from core.config import Config
from core.database import Database


@pytest.fixture
def temp_config():
    """Фикстура для временного конфига."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        config_data = {
            "sms": {
                "api_key": "test_key_123",
                "service": "Microsoft",
                "country": "all",
                "max_price": 0
            },
            "proxy": {
                "enabled": False,
                "type": "http",
                "proxies": []
            },
            "worker": {
                "threads": 5,
                "total_registrations": 10,
                "headless": True
            },
            "database": {
                "type": "sqlite",
                "sqlite_path": "test_worker.db"
            }
        }
        yaml.dump(config_data, f)
        config_path = f.name
    
    config = Config(config_path)
    yield config
    
    if os.path.exists(config_path):
        os.unlink(config_path)
    if os.path.exists("test_worker.db"):
        os.unlink("test_worker.db")


@pytest.fixture
def temp_db():
    """Фикстура для временной базы данных."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as config_file:
        config_data = {
            "database": {
                "type": "sqlite",
                "sqlite_path": db_path
            },
            "sms": {"api_key": ""},
            "proxy": {"enabled": False},
            "worker": {"threads": 5}
        }
        yaml.dump(config_data, config_file)
        config_path = config_file.name
    
    config = Config(config_path)
    db = Database(config)
    yield db
    
    if os.path.exists(db_path):
        os.unlink(db_path)
    if os.path.exists(config_path):
        os.unlink(config_path)


class TestAsyncWorkerInit:
    """Тесты инициализации AsyncWorker."""

    def test_init(self, temp_config):
        """Тест инициализации воркера."""
        worker = AsyncWorker(temp_config)
        
        assert worker.config == temp_config
        assert worker.db is not None
        assert worker.proxy_manager is not None
        assert worker.api_key == temp_config.get("sms.api_key")
        assert worker._stop_flag is False

    def test_init_with_custom_values(self, temp_config):
        """Тест инициализации с кастомными значениями."""
        temp_config.set("sms.api_key", "custom_key")
        temp_config.set("sms.service", "Google")
        temp_config.set("sms.country", "US")
        temp_config.set("sms.max_price", 50)
        
        worker = AsyncWorker(temp_config)
        
        assert worker.api_key == "custom_key"
        assert worker.service == "Google"
        assert worker.country == "US"
        assert worker.max_price == 50


class TestAsyncWorkerStop:
    """Тесты остановки воркера."""

    def test_stop(self, temp_config):
        """Тест остановки воркера."""
        worker = AsyncWorker(temp_config)
        
        # Проверяем что флаг остановки изначально False
        assert worker._stop_flag is False
        
        # Останавливаем воркер
        worker.stop()
        
        # Проверяем что флаг стал True
        assert worker._stop_flag is True


class TestAsyncWorkerCallbacks:
    """Тесты колбэков воркера."""

    def test_callbacks_init(self, temp_config):
        """Тест инициализации колбэков."""
        worker = AsyncWorker(temp_config)
        
        assert worker.on_progress is None
        assert worker.on_account is None
        assert worker.on_log is None
        assert worker.on_finished is None

    def test_callbacks_set(self, temp_config):
        """Тест установки колбэков."""
        worker = AsyncWorker(temp_config)
        
        progress_cb = lambda d, t, s, f: None
        account_cb = lambda a: None
        log_cb = lambda m: None
        finished_cb = lambda: None
        
        worker.on_progress = progress_cb
        worker.on_account = account_cb
        worker.on_log = log_cb
        worker.on_finished = finished_cb
        
        assert worker.on_progress == progress_cb
        assert worker.on_account == account_cb
        assert worker.on_log == log_cb
        assert worker.on_finished == finished_cb


class TestAsyncWorkerHandleStatus:
    """Тесты обработки статуса."""

    def test_handle_status_success(self, temp_config):
        """Тест обработки статуса success."""
        worker = AsyncWorker(temp_config)
        
        log_messages = []
        worker.on_log = lambda msg: log_messages.append(msg)
        
        worker._handle_status(1, 10, "success", {"email": "test@example.com"})
        
        assert len(log_messages) == 1
        assert "✅ test@example.com" in log_messages[0]

    def test_handle_status_failed(self, temp_config):
        """Тест обработки статуса failed."""
        worker = AsyncWorker(temp_config)
        
        log_messages = []
        worker.on_log = lambda msg: log_messages.append(msg)
        
        worker._handle_status(1, 10, "failed", {"email": "test@example.com", "error": "timeout"})
        
        assert len(log_messages) == 1
        assert "❌ test@example.com: timeout" in log_messages[0]

    def test_handle_status_starting(self, temp_config):
        """Тест обработки статуса starting."""
        worker = AsyncWorker(temp_config)
        
        log_messages = []
        worker.on_log = lambda msg: log_messages.append(msg)
        
        worker._handle_status(1, 10, "starting", {"email": "test@example.com"})
        
        assert len(log_messages) == 1
        assert "▶️ Начало: test@example.com" in log_messages[0]


class TestAsyncWorkerHandleLog:
    """Тесты обработки логов."""

    def test_handle_log(self, temp_config):
        """Тест обработки лога."""
        worker = AsyncWorker(temp_config)
        
        log_messages = []
        worker.on_log = lambda msg: log_messages.append(msg)
        
        worker._handle_log("Test message")
        
        assert len(log_messages) == 1
        assert "Test message" in log_messages[0]

    def test_handle_log_no_callback(self, temp_config):
        """Тест обработки лога без колбэка."""
        worker = AsyncWorker(temp_config)
        
        # Не устанавливаем колбэк
        worker._handle_log("Test message")
        
        # Не должно быть ошибок
        assert True


class TestAsyncWorkerWithDatabase:
    """Тесты взаимодействия с базой данных."""

    def test_worker_with_db(self, temp_db):
        """Тест воркера с базой данных."""
        # Создаем конфиг с этой базой
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_data = {
                "sms": {
                    "api_key": "test_key",
                    "service": "Microsoft",
                    "country": "all",
                    "max_price": 0
                },
                "proxy": {
                    "enabled": False,
                    "type": "http",
                    "proxies": []
                },
                "worker": {
                    "threads": 5,
                    "total_registrations": 10,
                    "headless": True
                },
                "database": {
                    "type": "sqlite",
                    "sqlite_path": temp_db.sqlite_path
                }
            }
            yaml.dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config(config_path)
            worker = AsyncWorker(config)
            
            # Проверяем что база данных та же самая
            assert worker.db.sqlite_path == temp_db.sqlite_path
            
            # Добавляем аккаунт через воркер
            worker.db.add_account(
                email="worker@example.com",
                password="password123"
            )
            
            # Проверяем что аккаунт добавился
            account = worker.db.get_account_by_email("worker@example.com")
            assert account is not None
            assert account["email"] == "worker@example.com"
        finally:
            if os.path.exists(config_path):
                os.unlink(config_path)
