"""
Модуль управления прокси с API ротацией.
Поддержка: IPRoyal, статический список, rotation URL.
"""
import httpx
import random
import threading
import time
import uuid
from typing import Optional, List, Dict, Any


class ProxyManager:
    def __init__(self, config):
        from .logger import log
        self.config = config
        self.proxies: List[Dict] = []
        self._lock = threading.Lock()
        self._current_index = 0
        self._dead_proxies: Dict[str, float] = {}
        self._dead_timeout = 300
        self._iproyal_session: Optional[str] = None
        self._iproyal_last_fetch: float = 0
        self._load_proxies()

    def _load_proxies(self):
        from .logger import log
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
        from .logger import log
        api_key = self.config.get("proxy.iproyal_api_key", "")
        country = self.config.get("proxy.iproyal_country", "all")
        length = self.config.get("proxy.iproyal_length", 30)
        if not api_key:
            log.error("IPRoyal API ключ не настроен")
            return
        proxies = self._fetch_iproyal_proxies(api_key, country, length)
        if proxies:
            self.proxies = proxies
            self._iproyal_session = api_key.split(":")[0] if ":" in api_key else api_key
            log.success(f"Получено {len(proxies)} прокси от IPRoyal")

    def _fetch_iproyal_proxies(self, api_key: str, country: str, length: int, session_id: Optional[str] = None) -> List[Dict]:
        url = "https://getproxy.iproyal.com/api/session-manager"
        login, password = (api_key.split(":", 1) + [""])[:2]
        session_name = session_id if session_id else api_key
        
        params = {"session": session_name, "length": length, "country": country, "login": login, "password": password}
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                if data.get("status") == "success" and "proxies" in data:
                    result = []
                    for proxy_str in data["proxies"]:
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
                                "session": session_name,
                            })
                    return result
        except Exception as e:
            from .logger import log
            log.error(f"Ошибка запроса к IPRoyal: {e}")
        return []

    def _load_static(self):
        from .logger import log
        proxy_type = self.config.get("proxy.type", "http")
        rotation_url = self.config.get("proxy.rotation_url", "")
        proxy_list = self.config.get("proxy.proxies", [])
        
        if rotation_url:
            self.proxies.append({"server": rotation_url, "type": proxy_type, "username": None, "password": None, "rotation": True, "dead": False})
            
        for proxy_str in proxy_list:
            if not proxy_str or not proxy_str.strip():
                continue
            proxy = self._parse_proxy_string(proxy_str.strip(), proxy_type)
            if proxy:
                self.proxies.append(proxy)

    def _parse_proxy_string(self, proxy_str: str, default_type: str) -> Optional[Dict]:
        proxy_type = default_type
        if "://" in proxy_str:
            parts = proxy_str.split("://", 1)
            proxy_type = parts[0]
            proxy_str = parts[1]
        parts = proxy_str.split(":", 3)
        if len(parts) == 2:
            return {"server": f"{parts[0]}:{parts[1]}", "type": proxy_type, "username": None, "password": None, "rotation": False, "dead": False}
        elif len(parts) >= 4:
            return {"server": f"{parts[0]}:{parts[1]}", "type": proxy_type, "username": parts[2], "password": parts[3], "rotation": False, "dead": False}
        return None

    def reload(self):
        with self._lock:
            self.proxies.clear()
            self._dead_proxies.clear()
            self._current_index = 0
        self._load_proxies()

    def get_next(self) -> Optional[Dict]:
        if not self.proxies:
            return None
        with self._lock:
            for _ in range(len(self.proxies)):
                proxy = self.proxies[self._current_index % len(self.proxies)]
                self._current_index += 1
                if self._is_alive(proxy):
                    return proxy.copy()
            # Если все мертвы, сбрасываем
            self._dead_proxies.clear()
            for p in self.proxies:
                p["dead"] = False
            proxy = self.proxies[self._current_index % len(self.proxies)]
            self._current_index += 1
            return proxy.copy()

    # НОВЫЙ МЕТОД: Гарантирует свежий прокси для каждой попытки
    def get_fresh_proxy(self) -> Optional[Dict]:
        """Получить свежий прокси. Для IPRoyal — новая сессия, для static — следующий по кругу."""
        from .logger import log
        if self.config.get("proxy.mode") == "iproyal":
            api_key = self.config.get("proxy.iproyal_api_key", "")
            if api_key:
                country = self.config.get("proxy.iproyal_country", "all")
                length = self.config.get("proxy.iproyal_length", 30)
                fresh_session = f"{api_key}:s_{uuid.uuid4().hex[:10]}"
                proxies = self._fetch_iproyal_proxies(api_key, country, length, session_id=fresh_session)
                if proxies:
                    log.debug(f"🔄 Fresh IPRoyal session: {fresh_session}")
                    return proxies[0]
        # Для static режима просто берем следующий (round-robin)
        return self.get_next()

    def _is_alive(self, proxy: Dict) -> bool:
        server = proxy.get("server", "")
        if proxy.get("dead", False):
            death_time = self._dead_proxies.get(server, 0)
            if time.time() - death_time > self._dead_timeout:
                proxy["dead"] = False
                self._dead_proxies.pop(server, None)
                return True
            return False
        return True

    def mark_dead(self, proxy: Dict):
        server = proxy.get("server", "")
        with self._lock:
            proxy["dead"] = True
            self._dead_proxies[server] = time.time()

    def has_proxies(self) -> bool:
        return len(self.proxies) > 0

    def count(self) -> int:
        return len(self.proxies)

    def alive_count(self) -> int:
        return sum(1 for p in self.proxies if self._is_alive(p))

    def get_requests_proxy(self) -> Optional[Dict]:
        proxy = self.get_next()
        if not proxy:
            return None
        if proxy.get("username"):
            auth = f"{proxy['username']}:{proxy['password']}"
            url = f"{proxy['type']}://{auth}@{proxy['server']}"
        else:
            url = f"{proxy['type']}://{proxy['server']}"
        return {"http": url, "https": url}