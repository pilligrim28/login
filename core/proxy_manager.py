"""
Модуль управления прокси с API ротацией.
Поддержка: IPRoyal, статический список, rotation URL.
"""

import httpx
import random
import threading
import time
from typing import Optional, List, Dict, Any


class ProxyManager:
    """
    Управление пулом прокси.

    Поддерживает:
    - IPRoyal API ротация (sticky IP)
    - Список статических прокси (round-robin)
    - Rotation URL
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
        self._iproyal_session: Optional[str] = None
        self._iproyal_last_fetch: float = 0

        self._load_proxies()

    # ============================================
    # ЗАГРУЗКА
    # ============================================

    def _load_proxies(self):
        """Загрузить прокси из конфигурации."""
        from .logger import log

        # GUI/сервер используют флаг proxy.enabled; core — proxy.mode.
        # Если прокси явно отключены — ничего не загружаем.
        enabled = self.config.get("proxy.enabled", True)
        if not enabled:
            log.info("Прокси отключены (proxy.enabled=false)")
            return

        proxy_mode = self.config.get("proxy.mode", "static")

        if proxy_mode == "iproyal":
            self._load_iproyal()
        else:
            self._load_static()

        log.info(f"Загружено прокси: {len(self.proxies)}")

    def _load_iproyal(self):
        """Загрузить прокси через IPRoyal API."""
        from .logger import log

        api_key = self.config.get("proxy.iproyal_api_key", "")
        country = self.config.get("proxy.iproyal_country", "all")
        length = self.config.get("proxy.iproyal_length", 30)

        if not api_key:
            log.error("IPRoyal API ключ не настроен")
            return

        log.info(f"Загрузка прокси через IPRoyal API (country={country}, length={length})")

        # Запрашиваем прокси через API
        proxies = self._fetch_iproyal_proxies(api_key, country, length)
        if proxies:
            self.proxies = proxies
            self._iproyal_session = api_key.split(":")[0] if ":" in api_key else api_key
            log.success(f"Получено {len(proxies)} прокси от IPRoyal")
        else:
            log.error("Не удалось получить прокси от IPRoyal")

    def _fetch_iproyal_proxies(self, api_key: str, country: str, length: int) -> List[Dict]:
        """
        Запросить прокси через IPRoyal API.

        Args:
            api_key: API ключ (login:password или session_id)
            country: Код страны (all, US, RU, UA и т.д.)
            length: Длительность сессии в секундах

        Returns:
            Список словарей прокси
        """
        url = "https://getproxy.iproyal.com/api/session-manager"

        # Парсим API ключ
        if ":" in api_key:
            login, password = api_key.split(":", 1)
        else:
            login = api_key
            password = ""

        params = {
            "session": api_key,
            "length": length,
            "country": country,
            "login": login,
            "password": password,
        }

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                if data.get("status") == "success" and "proxies" in data:
                    proxy_list = data["proxies"]
                    result = []

                    for proxy_str in proxy_list:
                        parts = proxy_str.split(":")
                        if len(parts) >= 2:
                            result.append({
                                "server": f"{parts[0]}:{parts[1]}",
                                "type": "http",
                                "username": login,
                                "password": password,
                                "rotation": False,
                                "dead": False,
                                "ip": data.get("ip"),
                                "session": api_key
                            })

                    return result

                log.error(f"IPRoyal API error: {data}")
                return None
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка запроса к IPRoyal: {e}")
            return []

    def _load_static(self):
        """Загрузить статические прокси из конфига."""
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

        # Разбиваем максимум на 4 части: host, port, user, password.
        # Пароль может содержать двоеточия — они сохраняются в последней части.
        parts = proxy_str.split(":", 3)

        if len(parts) == 2:
            return {
                "server": f"{parts[0]}:{parts[1]}",
                "type": proxy_type,
                "username": None,
                "password": None,
                "rotation": False,
                "dead": False
            }

        elif len(parts) >= 4:
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

        # Для IPRoyal — обновляем сессию если нужно
        if self.config.get("proxy.mode") == "iproyal":
            self._refresh_iproyal_session()

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

    def _refresh_iproyal_session(self):
        """Обновить сессию IPRoyal если нужно."""
        from .logger import log

        api_key = self.config.get("proxy.iproyal_api_key", "")
        country = self.config.get("proxy.iproyal_country", "all")
        length = self.config.get("proxy.iproyal_length", 30)

        # Обновляем каждые length секунд
        if time.time() - self._iproyal_last_fetch > length:
            log.info("Обновление прокси IPRoyal...")
            new_proxies = self._fetch_iproyal_proxies(api_key, country, length)
            if new_proxies:
                with self._lock:
                    self.proxies = new_proxies
                    self._current_index = 0
                    self._dead_proxies.clear()
                log.success(f"Прокси обновлены: {len(new_proxies)}")
                self._iproyal_last_fetch = time.time()

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
