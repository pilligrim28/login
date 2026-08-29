"""
Модуль базы данных.
Поддержка SQLite (по умолчанию) и PostgreSQL.
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any


class Database:
    """Работа с базой данных аккаунтов."""

    def __init__(self, config):
        """
        Инициализация базы данных.

        Args:
            config: Объект Config с настройками
        """
        self.config = config
        self.db_type = config.get("database.type", "sqlite")

        if self.db_type == "sqlite":
            self._init_sqlite()
        elif self.db_type == "postgres":
            self._init_postgres()
        else:
            raise ValueError(f"Неизвестный тип БД: {self.db_type}")

    # ============================================
    # ИНИЦИАЛИЗАЦИЯ
    # ============================================

    def _init_sqlite(self):
        """Инициализация SQLite."""
        self.sqlite_path = self.config.get("database.sqlite_path", "accounts.db")

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE,
                    password TEXT,
                    phone TEXT,
                    cookies_path TEXT,
                    proxy TEXT,
                    status TEXT DEFAULT 'pending',
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

        from .logger import log
        log.debug(f"SQLite подключена: {self.sqlite_path}")

    def _init_postgres(self):
        """Инициализация PostgreSQL."""
        import psycopg2
        self.pg_url = self.config.get("database.postgres_url")

        with psycopg2.connect(self.pg_url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS accounts (
                        id SERIAL PRIMARY KEY,
                        email TEXT UNIQUE,
                        password TEXT,
                        phone TEXT,
                        cookies_path TEXT,
                        proxy TEXT,
                        status TEXT DEFAULT 'pending',
                        error TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                conn.commit()

        from .logger import log
        log.debug("PostgreSQL подключена")

    # ============================================
    # ДОБАВЛЕНИЕ
    # ============================================

    def add_account(
            self,
            email: str,
            password: str,
            phone: str = "",
            cookies_path: str = "",
            proxy: str = "",
            status: str = "pending",
            error: str = ""
    ) -> Optional[int]:
        """
        Добавить аккаунт в базу.

        Args:
            email: Email аккаунта
            password: Пароль
            phone: Номер телефона
            cookies_path: Путь к файлу cookies
            proxy: Использованный прокси
            status: Статус (pending, success, failed, error)
            error: Описание ошибки

        Returns:
            ID добавленной записи или None при ошибке
        """
        try:
            if self.db_type == "sqlite":
                with sqlite3.connect(self.sqlite_path) as conn:
                    cur = conn.execute("""
                        INSERT OR REPLACE INTO accounts 
                        (email, password, phone, cookies_path, proxy, status, error)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (email, password, phone, cookies_path, proxy, status, error))
                    conn.commit()
                    return cur.lastrowid
            else:
                import psycopg2
                with psycopg2.connect(self.pg_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO accounts 
                            (email, password, phone, cookies_path, proxy, status, error)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (email) DO UPDATE SET
                                password = EXCLUDED.password,
                                phone = EXCLUDED.phone,
                                status = EXCLUDED.status,
                                error = EXCLUDED.error
                            RETURNING id
                        """, (email, password, phone, cookies_path, proxy, status, error))
                        conn.commit()
                        result = cur.fetchone()
                        return result[0] if result else None
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка добавления аккаунта: {e}")
            return None

    # ============================================
    # ОБНОВЛЕНИЕ
    # ============================================

    def update_status(self, account_id: int, status: str, error: str = ""):
        """
        Обновить статус аккаунта.

        Args:
            account_id: ID аккаунта
            status: Новый статус
            error: Описание ошибки (опционально)
        """
        try:
            if self.db_type == "sqlite":
                with sqlite3.connect(self.sqlite_path) as conn:
                    conn.execute("""
                        UPDATE accounts SET status = ?, error = ? WHERE id = ?
                    """, (status, error, account_id))
                    conn.commit()
            else:
                import psycopg2
                with psycopg2.connect(self.pg_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE accounts SET status = %s, error = %s WHERE id = %s
                        """, (status, error, account_id))
                        conn.commit()
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка обновления статуса: {e}")

    def update_status_by_email(self, email: str, status: str, error: str = ""):
        """
        Обновить статус по email.

        Args:
            email: Email аккаунта
            status: Новый статус
            error: Описание ошибки
        """
        try:
            if self.db_type == "sqlite":
                with sqlite3.connect(self.sqlite_path) as conn:
                    conn.execute("""
                        UPDATE accounts SET status = ?, error = ? WHERE email = ?
                    """, (status, error, email))
                    conn.commit()
            else:
                import psycopg2
                with psycopg2.connect(self.pg_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE accounts SET status = %s, error = %s WHERE email = %s
                        """, (status, error, email))
                        conn.commit()
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка обновления по email: {e}")

    # ============================================
    # ПОЛУЧЕНИЕ
    # ============================================

    def get_all_accounts(self) -> List[Dict[str, Any]]:
        """
        Получить все аккаунты.

        Returns:
            Список словарей с данными аккаунтов
        """
        try:
            if self.db_type == "sqlite":
                with sqlite3.connect(self.sqlite_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.execute("SELECT * FROM accounts ORDER BY id DESC")
                    rows = cur.fetchall()
                    return [dict(row) for row in rows]
            else:
                import psycopg2
                import psycopg2.extras
                with psycopg2.connect(self.pg_url) as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute("SELECT * FROM accounts ORDER BY id DESC")
                        return cur.fetchall()
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка получения аккаунтов: {e}")
            return []

    def get_accounts_by_status(self, status: str) -> List[Dict[str, Any]]:
        """
        Получить аккаунты по статусу.

        Args:
            status: Статус (success, failed, error, pending)

        Returns:
            Список аккаунтов
        """
        try:
            if self.db_type == "sqlite":
                with sqlite3.connect(self.sqlite_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.execute(
                        "SELECT * FROM accounts WHERE status = ? ORDER BY id DESC",
                        (status,)
                    )
                    rows = cur.fetchall()
                    return [dict(row) for row in rows]
            else:
                import psycopg2
                import psycopg2.extras
                with psycopg2.connect(self.pg_url) as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(
                            "SELECT * FROM accounts WHERE status = %s ORDER BY id DESC",
                            (status,)
                        )
                        return cur.fetchall()
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка получения аккаунтов по статусу: {e}")
            return []

    def get_account_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Найти аккаунт по email.

        Args:
            email: Email для поиска

        Returns:
            Словарь с данными или None
        """
        try:
            if self.db_type == "sqlite":
                with sqlite3.connect(self.sqlite_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.execute(
                        "SELECT * FROM accounts WHERE email = ?",
                        (email,)
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None
            else:
                import psycopg2
                import psycopg2.extras
                with psycopg2.connect(self.pg_url) as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(
                            "SELECT * FROM accounts WHERE email = %s",
                            (email,)
                        )
                        result = cur.fetchone()
                        return result if result else None
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка поиска по email: {e}")
            return None

    # ============================================
    # СТАТИСТИКА
    # ============================================

    def get_stats(self) -> Dict[str, int]:
        """
        Получить статистику регистраций.

        Returns:
            {"total": N, "success": N, "failed": N, "errors": N}
        """
        try:
            if self.db_type == "sqlite":
                with sqlite3.connect(self.sqlite_path) as conn:
                    cur = conn.execute("""
                        SELECT 
                            COUNT(*) as total,
                            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors
                        FROM accounts
                    """)
                    row = cur.fetchone()
                    return {
                        "total": row[0] or 0,
                        "success": row[1] or 0,
                        "failed": row[2] or 0,
                        "errors": row[3] or 0
                    }
            else:
                import psycopg2
                with psycopg2.connect(self.pg_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT 
                                COUNT(*) as total,
                                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors
                            FROM accounts
                        """)
                        row = cur.fetchone()
                        return {
                            "total": row[0] or 0,
                            "success": row[1] or 0,
                            "failed": row[2] or 0,
                            "errors": row[3] or 0
                        }
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка получения статистики: {e}")
            return {"total": 0, "success": 0, "failed": 0, "errors": 0}

    def get_success_rate(self) -> float:
        """
        Получить процент успешных регистраций.

        Returns:
            Процент (0-100)
        """
        stats = self.get_stats()
        total = stats.get("total", 0)
        success = stats.get("success", 0)

        if total == 0:
            return 0.0

        return (success / total) * 100

    # ============================================
    # УДАЛЕНИЕ
    # ============================================

    def delete_account(self, account_id: int) -> bool:
        """
        Удалить аккаунт по ID.

        Returns:
            True если удалён
        """
        try:
            if self.db_type == "sqlite":
                with sqlite3.connect(self.sqlite_path) as conn:
                    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
                    conn.commit()
                    return True
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка удаления: {e}")
            return False

    def clear(self) -> bool:
        """
        Очистить всю таблицу.

        Returns:
            True если успешно
        """
        try:
            if self.db_type == "sqlite":
                with sqlite3.connect(self.sqlite_path) as conn:
                    conn.execute("DELETE FROM accounts")
                    conn.commit()
                    return True
            else:
                import psycopg2
                with psycopg2.connect(self.pg_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM accounts")
                        conn.commit()
                        return True
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка очистки: {e}")
            return False