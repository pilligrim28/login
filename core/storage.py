import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict


class Storage:
    """Работа с базой данных SQLite."""

    def __init__(self, db_path: str = "accounts.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Создание таблицы, если её нет."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE,
                    password TEXT,
                    phone TEXT,
                    cookies_path TEXT,
                    proxy TEXT,
                    status TEXT DEFAULT 'created',
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def add_account(
            self,
            email: str,
            password: str,
            phone: str,
            cookies_path: str = "",
            proxy: str = "",
            status: str = "created",
            error: str = ""
    ) -> int:
        """Добавить аккаунт в базу."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO accounts 
                (email, password, phone, cookies_path, proxy, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (email, password, phone, cookies_path, proxy, status, error))
            conn.commit()
            return cursor.lastrowid

    def update_status(self, account_id: int, status: str, error: str = ""):
        """Обновить статус аккаунта."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE accounts SET status = ?, error = ? WHERE id = ?
            """, (status, error, account_id))
            conn.commit()

    def get_all_accounts(self) -> List[Dict]:
        """Получить все аккаунты."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts ORDER BY id DESC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_accounts_count(self) -> int:
        """Количество аккаунтов."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM accounts")
            return cursor.fetchone()[0]

    def get_successful_count(self) -> int:
        """Количество успешных регистраций."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM accounts WHERE status = 'success'")
            return cursor.fetchone()[0]