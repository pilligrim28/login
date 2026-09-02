"""Тесты для модуля database.py"""

import pytest
import tempfile
import os
import yaml
from core.database import Database
from core.config import Config


@pytest.fixture
def temp_db():
    """Фикстура для временной базы данных SQLite."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    # Создаем временный конфиг
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
    
    # Очистка
    if os.path.exists(db_path):
        os.unlink(db_path)
    if os.path.exists(config_path):
        os.unlink(config_path)


@pytest.fixture
def temp_config():
    """Фикстура для временного конфига."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        config_data = {
            "sms": {"api_key": ""},
            "proxy": {"enabled": False},
            "worker": {"threads": 5},
            "database": {"type": "sqlite"}
        }
        yaml.dump(config_data, f)
        config_path = f.name
    
    config = Config(config_path)
    yield config
    
    if os.path.exists(config_path):
        os.unlink(config_path)


class TestDatabase:
    """Тесты для Database."""

    def test_add_account(self, temp_db):
        """Тест добавления аккаунта."""
        account_id = temp_db.add_account(
            email="test@example.com",
            password="password123",
            status="success"
        )
        assert account_id is not None
        
        accounts = temp_db.get_all_accounts()
        assert len(accounts) == 1
        assert accounts[0]["email"] == "test@example.com"
        assert accounts[0]["password"] == "password123"
        assert accounts[0]["status"] == "success"

    def test_get_account_by_email(self, temp_db):
        """Тест получения аккаунта по email."""
        temp_db.add_account(
            email="findme@example.com",
            password="pass123"
        )
        
        account = temp_db.get_account_by_email("findme@example.com")
        assert account is not None
        assert account["email"] == "findme@example.com"
        
        not_found = temp_db.get_account_by_email("notfound@example.com")
        assert not_found is None

    def test_update_status(self, temp_db):
        """Тест обновления статуса."""
        account_id = temp_db.add_account(
            email="updateme@example.com",
            password="pass",
            status="pending"
        )
        
        temp_db.update_status(account_id, "success")
        
        account = temp_db.get_account_by_email("updateme@example.com")
        assert account["status"] == "success"

    def test_get_accounts_by_status(self, temp_db):
        """Тест получения аккаунтов по статусу."""
        temp_db.add_account(email="success1@test.com", password="pass", status="success")
        temp_db.add_account(email="success2@test.com", password="pass", status="success")
        temp_db.add_account(email="failed@test.com", password="pass", status="failed")
        
        success_accounts = temp_db.get_accounts_by_status("success")
        assert len(success_accounts) == 2
        
        failed_accounts = temp_db.get_accounts_by_status("failed")
        assert len(failed_accounts) == 1

    def test_get_stats(self, temp_db):
        """Тест получения статистики."""
        temp_db.add_account(email="s1@test.com", password="pass", status="success")
        temp_db.add_account(email="s2@test.com", password="pass", status="success")
        temp_db.add_account(email="f1@test.com", password="pass", status="failed")
        temp_db.add_account(email="e1@test.com", password="pass", status="error")
        
        stats = temp_db.get_stats()
        assert stats["total"] == 4
        assert stats["success"] == 2
        assert stats["failed"] == 1
        assert stats["errors"] == 1

    def test_get_success_rate(self, temp_db):
        """Тест получения процента успеха."""
        temp_db.add_account(email="s1@test.com", password="pass", status="success")
        temp_db.add_account(email="s2@test.com", password="pass", status="success")
        temp_db.add_account(email="f1@test.com", password="pass", status="failed")
        
        rate = temp_db.get_success_rate()
        assert rate == pytest.approx(66.67, rel=0.01)

    def test_email_exists(self, temp_db):
        """Тест проверки существования email."""
        temp_db.add_account(email="exists@test.com", password="pass")
        
        assert temp_db.email_exists("exists@test.com") is True
        assert temp_db.email_exists("notexists@test.com") is False

    def test_delete_account(self, temp_db):
        """Тест удаления аккаунта."""
        account_id = temp_db.add_account(email="delete@test.com", password="pass")
        
        assert temp_db.delete_account(account_id) is True
        
        accounts = temp_db.get_all_accounts()
        assert len(accounts) == 0

    def test_clear(self, temp_db):
        """Тест очистки базы."""
        temp_db.add_account(email="clear1@test.com", password="pass")
        temp_db.add_account(email="clear2@test.com", password="pass")
        
        assert temp_db.clear() is True
        
        accounts = temp_db.get_all_accounts()
        assert len(accounts) == 0


class TestDatabaseIndexes:
    """Тесты для индексов базы данных."""

    def test_indexes_created(self, temp_db):
        """Тест что индексы создаются."""
        # Для SQLite проверить через PRAGMA
        if temp_db.db_type == "sqlite":
            import sqlite3
            with sqlite3.connect(temp_db.sqlite_path) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA index_list(accounts)")
                indexes = cursor.fetchall()
                
                index_names = [idx[1] for idx in indexes]
                assert "idx_email" in index_names
                assert "idx_status" in index_names
                assert "idx_created_at" in index_names
