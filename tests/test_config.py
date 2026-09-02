"""Тесты для модуля config.py"""

import pytest
import tempfile
import os
import yaml
from core.config import Config


@pytest.fixture
def temp_config_file():
    """Фикстура для временного файла конфигурации."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        config_data = {
            "sms": {
                "api_key": "test_key_123",
                "service": "Microsoft",
                "max_price": 10.5
            },
            "worker": {
                "threads": 5,
                "total_registrations": 100
            },
            "proxy": {
                "enabled": True
            }
        }
        yaml.dump(config_data, f)
        config_path = f.name
    
    yield config_path
    
    if os.path.exists(config_path):
        os.unlink(config_path)


class TestConfig:
    """Тесты для Config."""

    def test_load_config(self, temp_config_file):
        """Тест загрузки конфигурации."""
        config = Config(temp_config_file)
        assert config.path == temp_config_file
        assert config.data is not None

    def test_get_value(self, temp_config_file):
        """Тест получения значений."""
        config = Config(temp_config_file)
        
        assert config.get("sms.api_key") == "test_key_123"
        assert config.get("sms.service") == "Microsoft"
        assert config.get("worker.threads") == 5
        assert config.get("worker.total_registrations") == 100
        assert config.get("proxy.enabled") is True

    def test_get_default_value(self, temp_config_file):
        """Тест получения значения по умолчанию."""
        config = Config(temp_config_file)
        
        # Несуществующий ключ
        assert config.get("nonexistent.key") is None
        assert config.get("nonexistent.key", "default") == "default"

    def test_get_nested_value(self, temp_config_file):
        """Тест получения вложенных значений."""
        config = Config(temp_config_file)
        
        assert config.get("sms.max_price") == 10.5

    def test_set_value(self, temp_config_file):
        """Тест установки значений."""
        config = Config(temp_config_file)
        
        config.set("sms.api_key", "new_key_456")
        assert config.get("sms.api_key") == "new_key_456"
        
        config.set("new.section.key", "new_value")
        assert config.get("new.section.key") == "new_value"

    def test_save_config(self, temp_config_file):
        """Тест сохранения конфигурации."""
        config = Config(temp_config_file)
        
        config.set("sms.api_key", "saved_key")
        config.save()
        
        # Перезагружаем и проверяем
        config2 = Config(temp_config_file)
        assert config2.get("sms.api_key") == "saved_key"

    def test_reload_config(self, temp_config_file):
        """Тест перезагрузки конфигурации."""
        config = Config(temp_config_file)
        
        # Изменяем файл вручную
        with open(temp_config_file, 'r') as f:
            data = yaml.safe_load(f)
        data["sms"]["api_key"] = "reloaded_key"
        with open(temp_config_file, 'w') as f:
            yaml.dump(data, f)
        
        config.reload()
        assert config.get("sms.api_key") == "reloaded_key"

    def test_validation_threads(self, temp_config_file):
        """Тест валидации worker.threads."""
        config = Config(temp_config_file)
        
        # Проверяем существующее значение
        assert isinstance(config.get("worker.threads"), int)
        
        # Устанавливаем невалидное значение
        config.set("worker.threads", "not_an_integer")
        
        with pytest.raises(ValueError) as exc_info:
            config.get("worker.threads")
        
        assert "worker.threads должен быть целым числом" in str(exc_info.value)

    def test_validation_max_price(self, temp_config_file):
        """Тест валидации sms.max_price."""
        config = Config(temp_config_file)
        
        # Устанавливаем невалидное значение
        config.set("sms.max_price", "not_a_number")
        
        with pytest.raises(ValueError) as exc_info:
            config.get("sms.max_price")
        
        assert "sms.max_price должен быть числом" in str(exc_info.value)

    def test_validation_proxy_enabled(self, temp_config_file):
        """Тест валидации proxy.enabled."""
        config = Config(temp_config_file)
        
        # Устанавливаем невалидное значение
        config.set("proxy.enabled", "not_a_boolean")
        
        with pytest.raises(ValueError) as exc_info:
            config.get("proxy.enabled")
        
        assert "proxy.enabled должен быть булевым значением" in str(exc_info.value)

    def test_file_not_found(self):
        """Тест обработки отсутствующего файла."""
        with pytest.raises(FileNotFoundError):
            Config("/nonexistent/path/config.yaml")


class TestConfigRepr:
    """Тесты для __repr__."""

    def test_repr(self, temp_config_file):
        """Тест представления объекта."""
        config = Config(temp_config_file)
        assert repr(config) == f"Config({temp_config_file})"
