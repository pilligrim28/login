"""Интеграционные тесты для асинхронных модулей"""

import pytest
import asyncio
import tempfile
import os
import yaml
from unittest.mock import AsyncMock, MagicMock, patch
from core.sms_async import AsyncSMSActivate
from core.config import Config
from core.database import Database
from core.proxy_manager import ProxyManager


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
                "total_registrations": 50,
                "headless": True
            },
            "database": {
                "type": "sqlite",
                "sqlite_path": "test.db"
            }
        }
        yaml.dump(config_data, f)
        config_path = f.name
    
    config = Config(config_path)
    yield config
    
    if os.path.exists(config_path):
        os.unlink(config_path)


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


class TestAsyncSMSActivate:
    """Тесты для AsyncSMSActivate."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Тест контекстного менеджера."""
        async with AsyncSMSActivate(api_key="test_key") as sms:
            assert sms.api_key == "test_key"
            assert sms._client is not None
        
        # После выхода из контекста клиент должен быть закрыт
        assert sms._client is None

    @pytest.mark.asyncio
    async def test_get_balance(self):
        """Тест получения баланса."""
        mock_response = MagicMock()
        mock_response.text = "ACCESS_BALANCE:100.5"
        mock_response.raise_for_status = MagicMock()
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            async with AsyncSMSActivate(api_key="test_key") as sms:
                sms._client = mock_client
                balance = await sms.get_balance()
                assert balance == 100.5

    @pytest.mark.asyncio
    async def test_rent_number(self):
        """Тест аренды номера."""
        mock_response = MagicMock()
        mock_response.text = "ACCESS_NUMBER:12345:79991234567"
        mock_response.raise_for_status = MagicMock()
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            async with AsyncSMSActivate(api_key="test_key") as sms:
                sms._client = mock_client
                result = await sms.rent_number()
                assert result == {"id": "12345", "number": "79991234567"}

    @pytest.mark.asyncio
    async def test_wait_code(self):
        """Тест ожидания кода."""
        mock_response = MagicMock()
        mock_response.text = "STATUS_OK:123456"
        mock_response.raise_for_status = MagicMock()
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            with patch('time.time', return_value=0):
                async with AsyncSMSActivate(api_key="test_key") as sms:
                    sms._client = mock_client
                    code = await sms.wait_code("12345", timeout=10, poll_interval=1)
                    assert code == "123456"


class TestAsyncIntegration:
    """Интеграционные тесты."""

    @pytest.mark.asyncio
    async def test_sms_with_proxy(self):
        """Тест SMS-клиента с прокси."""
        mock_response = MagicMock()
        mock_response.text = "ACCESS_BALANCE:50.0"
        mock_response.raise_for_status = MagicMock()
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            async with AsyncSMSActivate(
                api_key="test_key",
                proxy="http://proxy.example.com:8080"
            ) as sms:
                sms._client = mock_client
                balance = await sms.get_balance()
                assert balance == 50.0
                # Проверяем что прокси передан клиенту
                mock_client_class.assert_called_once()
                call_kwargs = mock_client_class.call_args[1]
                assert call_kwargs['proxy'] == "http://proxy.example.com:8080"

    @pytest.mark.asyncio
    async def test_database_with_async_sms(self, temp_db):
        """Тест взаимодействия базы данных и асинхронного SMS."""
        # Добавляем аккаунт в базу
        temp_db.add_account(
            email="test@example.com",
            password="password123",
            status="pending"
        )
        
        # Проверяем что аккаунт есть в базе
        account = temp_db.get_account_by_email("test@example.com")
        assert account is not None
        assert account["status"] == "pending"
        
        # Обновляем статус
        temp_db.update_status(account["id"], "success")
        
        # Проверяем обновление
        updated_account = temp_db.get_account_by_email("test@example.com")
        assert updated_account["status"] == "success"

    @pytest.mark.asyncio
    async def test_proxy_manager_with_config(self, temp_config):
        """Тест менеджера прокси с конфигурацией."""
        pm = ProxyManager(temp_config)
        
        # Проверяем что прокси не загружены (enabled: false)
        assert pm.has_proxies() is False
        
        # Изменяем конфигурацию
        temp_config.set("proxy.enabled", True)
        temp_config.set("proxy.proxies", ["proxy1:8080", "proxy2:8080"])
        
        # Перезагружаем прокси
        pm.reload()
        
        # Теперь прокси должны быть загружены
        assert pm.has_proxies() is True
        assert pm.count() == 2


class TestAsyncWorkerIntegration:
    """Тесты для интеграции асинхронного воркера."""

    @pytest.mark.asyncio
    async def test_worker_initialization(self, temp_config):
        """Тест инициализации асинхронного воркера."""
        from workers.async_worker import AsyncWorker
        
        worker = AsyncWorker(temp_config)
        
        assert worker.config == temp_config
        assert worker.db is not None
        assert worker.proxy_manager is not None
        assert worker.api_key == temp_config.get("sms.api_key")

    @pytest.mark.asyncio
    async def test_worker_stop(self, temp_config):
        """Тест остановки воркера."""
        from workers.async_worker import AsyncWorker
        
        worker = AsyncWorker(temp_config)
        
        # Проверяем что флаг остановки изначально False
        assert worker._stop_flag is False
        
        # Останавливаем воркер
        worker.stop()
        
        # Проверяем что флаг стал True
        assert worker._stop_flag is True


class TestConfigValidation:
    """Тесты валидации конфигурации."""

    def test_valid_config(self, temp_config):
        """Тест валидной конфигурации."""
        # Проверяем что все значения валидны
        threads = temp_config.get("worker.threads")
        assert isinstance(threads, int)
        
        total = temp_config.get("worker.total_registrations")
        assert isinstance(total, int)

    def test_invalid_threads(self, temp_config):
        """Тест невалидного значения threads."""
        temp_config.set("worker.threads", "not_an_integer")
        
        with pytest.raises(ValueError) as exc_info:
            temp_config.get("worker.threads")
        
        assert "worker.threads должен быть целым числом" in str(exc_info.value)

    def test_invalid_max_price(self, temp_config):
        """Тест невалидного значения max_price."""
        temp_config.set("sms.max_price", "not_a_number")
        
        with pytest.raises(ValueError) as exc_info:
            temp_config.get("sms.max_price")
        
        assert "sms.max_price должен быть числом" in str(exc_info.value)
