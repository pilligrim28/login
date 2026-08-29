"""
Модуль управления прокси.
Поддержка списка прокси, rotation URL, round-robin и случайного выбора.
"""

import random
import threading
import time
from typing import Optional, List, Dict, Any


class ProxyManager:
    """
    Управление пулом прокси.

    Поддерживает:
    - Список прокси в формате host:port:username:password
    - Rotation URL (один endpoint для автоматической ротации)
    - Round-robin и случайный выбор
    - Отслеживание нерабочих прокси
    """

    def __init__(self, config):
        """
        Инициализация менеджера прокси.

        Args:
            config: Объект Config
        """
        self.config = config
        self.proxies: List[Dict] = []
        self._lock = threading.Lock()
        self._current_index = 0
        self._dead_proxies: Dict[str, float] = {}
        self._dead_timeout = 300

        self._load_proxies()

    # ============================================
    # ЗАГРУЗКА
    # ============================================

    def _load_proxies(self):
        """Загрузить прокси из конфигурации."""
        from .logger import log

        proxy_type = self.config.get("proxy.type", "http")
        rotation_url = self.config.get("proxy.rotation_url", "")
        proxy_list = self.config.get("proxy.proxies", [])

        # Rotation URL
        if rotation_url:
            self.proxies.append({
                "server": rotation_url,
                "type": proxy_type,
                "username": None,
                "password": None,
                "rotation": True,
                "dead": False
            })
            log.info(f"Загружен rotation URL: {self._mask_url(rotation_url)}")

        # Список прокси
        for proxy_str in proxy_list:
            if not proxy_str or not proxy_str.strip():
                continue

            proxy = self._parse_proxy_string(proxy_str.strip(), proxy_type)
            if proxy:
                self.proxies.append(proxy)
            else:
                log.warning(f"Неверный формат прокси: {proxy_str[:50]}...")

        log.info(f"Загружено прокси: {len(self.proxies)}")

    def _parse_proxy_string(self, proxy_str: str, default_type: str) -> Optional[Dict]:
        """
        Разобрать строку прокси.

        Форматы:
        - host:port
        - host:port:username:password
        - type://host:port:username:password

        Returns:
            Словарь с параметрами или None
        """
        proxy_type = default_type

        if "://" in proxy_str:
            parts = proxy_str.split("://", 1)
            proxy_type = parts[0]
            proxy_str = parts[1]

        parts = proxy_str.split(":")

        if len(parts) == 2:
            return {
                "server": f"{parts[0]}:{parts[1]}",
                "type": proxy_type,
                "username": None,
                "password": None,
                "rotation": False,
                "dead": False
            }

        elif len(parts) == 4:
            return {
                "server": f"{parts[0]}:{parts[1]}",
                "type": proxy_type,
                "username": parts[2],
                "password": parts[3],
                "rotation": False,
                "dead": False
            }

        return None

    def _mask_url(self, url: str) -> str:
        """Скрыть чувствительные данные в URL для логов."""
        if len(url) > 50:
            return url[:47] + "..."
        return url

    def reload(self):
        """Перезагрузить прокси из конфига."""
        with self._lock:
            self.proxies.clear()
            self._dead_proxies.clear()
            self._current_index = 0
        self._load_proxies()

    # ============================================
    # ПОЛУЧЕНИЕ ПРОКСИ
    # ============================================

    def get_next(self) -> Optional[Dict]:
        """
        Получить следующий прокси (round-robin).

        Returns:
            Копия словаря прокси или None
        """
        if not self.proxies:
            return None

        with self._lock:
            # Пробуем найти живой прокси
            for _ in range(len(self.proxies)):
                proxy = self.proxies[self._current_index % len(self.proxies)]
                self._current_index += 1

                if self._is_alive(proxy):
                    return proxy.copy()

            # Все мертвы — сбрасываем
            self._dead_proxies.clear()
            for p in self.proxies:
                p["dead"] = False

            proxy = self.proxies[self._current_index % len(self.proxies)]
            self._current_index += 1
            return proxy.copy()

    def get_random(self) -> Optional[Dict]:
        """
        Получить случайный прокси.

        Returns:
            Копия словаря прокси или None
        """
        if not self.proxies:
            return None

        alive = [p for p in self.proxies if self._is_alive(p)]

        if not alive:
            alive = self.proxies

        return random.choice(alive).copy()

    def get_playwright_proxy(self) -> Optional[Dict]:
        """
        Получить прокси в формате для Playwright.

        Returns:
            {"server": "type://host:port", "username": "...", "password": "..."}
        """
        proxy = self.get_next()
        if not proxy:
            return None

        result = {
            "server": f"{proxy['type']}://{proxy['server']}"
        }

        if proxy.get("username"):
            result["username"] = proxy["username"]
            result["password"] = proxy.get("password", "")

        return result

    def get_requests_proxy(self) -> Optional[Dict]:
        """
        Получить прокси в формате для requests/httpx.

        Returns:
            {"http": "...", "https": "..."} или None
        """
        proxy = self.get_next()
        if not proxy:
            return None

        if proxy.get("username"):
            auth = f"{proxy['username']}:{proxy['password']}"
            url = f"{proxy['type']}://{auth}@{proxy['server']}"
        else:
            url = f"{proxy['type']}://{proxy['server']}"

        return {
            "http": url,
            "https": url
        }

    # ============================================
    # УПРАВЛЕНИЕ СОСТОЯНИЕМ
    # ============================================

    def _is_alive(self, proxy: Dict) -> bool:
        """
        Проверить, жив ли прокси.

        Args:
            proxy: Словарь прокси

        Returns:
            True если прокси можно использовать
        """
        server = proxy.get("server", "")

        # Если прокси помечен как мёртвый
        if proxy.get("dead", False):
            death_time = self._dead_proxies.get(server, 0)

            # Если прошло больше dead_timeout — пробуем снова
            if time.time() - death_time > self._dead_timeout:
                proxy["dead"] = False
                self._dead_proxies.pop(server, None)
                return True

            return False

        return True

    def mark_dead(self, proxy: Dict):
        """
        Пометить прокси как нерабочий.

        Args:
            proxy: Словарь прокси
        """
        server = proxy.get("server", "")

        with self._lock:
            proxy["dead"] = True
            self._dead_proxies[server] = time.time()

        from .logger import log
        log.warning(f"Прокси помечен как нерабочий: {server}")

    def mark_alive(self, proxy: Dict):
        """
        Пометить прокси как рабочий.

        Args:
            proxy: Словарь прокси
        """
        server = proxy.get("server", "")

        with self._lock:
            proxy["dead"] = False
            self._dead_proxies.pop(server, None)

    # ============================================
    # ИНФОРМАЦИЯ
    # ============================================

    def has_proxies(self) -> bool:
        """Есть ли прокси."""
        return len(self.proxies) > 0

    def count(self) -> int:
        """Количество прокси."""
        return len(self.proxies)

    def alive_count(self) -> int:
        """Количество живых прокси."""
        return sum(1 for p in self.proxies if self._is_alive(p))

    def dead_count(self) -> int:
        """Количество мёртвых прокси."""
        return sum(1 for p in self.proxies if not self._is_alive(p))

    def get_all(self) -> List[Dict]:
        """Получить все прокси (копии)."""
        return [p.copy() for p in self.proxies]

    def get_stats(self) -> Dict[str, int]:
        """Получить статистику."""
        return {
            "total": self.count(),
            "alive": self.alive_count(),
            "dead": self.dead_count()
        }