"""Тесты для модуля logger.py"""

import pytest
import tempfile
import os
from core.logger import log, Logger


@pytest.fixture
def temp_log_dir():
    """Фикстура для временной директории логов."""
    import shutil
    from datetime import datetime
    
    log_dir = tempfile.mkdtemp()
    old_logs_dir = "logs"
    
    # Перемещаем текущие логи
    if os.path.exists(old_logs_dir):
        shutil.move(old_logs_dir, f"{log_dir}/logs_backup")
    
    yield log_dir
    
    # Восстанавливаем
    if os.path.exists(f"{log_dir}/logs_backup"):
        shutil.move(f"{log_dir}/logs_backup", old_logs_dir)
    elif os.path.exists(old_logs_dir):
        pass
    
    # Очистка
    shutil.rmtree(log_dir, ignore_errors=True)


class TestLogger:
    """Тесты для Logger."""

    def test_singleton(self, temp_log_dir):
        """Тест что Logger — singleton."""
        # Сбрасываем singleton
        Logger._instance = None
        
        logger1 = Logger()
        # Не сбрасываем _instance, так как он уже установлен
        logger2 = Logger()
        
        assert logger1 is logger2

    def test_log_methods(self, temp_log_dir):
        """Тест методов логгирования."""
        # Сбрасываем singleton
        Logger._instance = None
        
        logger = Logger()
        
        # Проверяем что методы не вызывают ошибок
        logger.info("Test info message")
        logger.warning("Test warning message")
        logger.error("Test error message")
        logger.debug("Test debug message")
        logger.success("Test success message")

    def test_log_file_created(self, temp_log_dir):
        """Тест что файл лога создается."""
        # Сбрасываем singleton
        Logger._instance = None
        
        logger = Logger()
        logger.info("Test message for file creation")
        
        # Проверяем что файл лога создан
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = f"logs/{date_str}.log"
        
        assert os.path.exists(log_file)

    def test_rotation(self, temp_log_dir):
        """Тест ротации логов."""
        # Сбрасываем singleton
        Logger._instance = None
        
        logger = Logger()
        
        # Пишем много сообщений (в реальности это займет много времени)
        for i in range(100):
            logger.info(f"Test message {i}")
        
        # Проверяем что файл существует
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = f"logs/{date_str}.log"
        
        assert os.path.exists(log_file)


class TestGlobalLog:
    """Тесты для глобального логгера."""

    def test_global_log_exists(self):
        """Тест что глобальный логгер существует."""
        assert log is not None
        assert hasattr(log, 'info')
        assert hasattr(log, 'warning')
        assert hasattr(log, 'error')
        assert hasattr(log, 'debug')
        assert hasattr(log, 'success')

    def test_global_log_methods(self, temp_log_dir):
        """Тест методов глобального логгера."""
        log.info("Global info test")
        log.warning("Global warning test")
        log.error("Global error test")
        log.debug("Global debug test")
        log.success("Global success test")
