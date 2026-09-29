"""
Модуль работы с Partner REST API провайдера SMS-номеров.
Полный список эндпоинтов (base_url = https://46.21.159.86/partner):
GET  /get_balance            (header x-api-key)  -> {"usd": float, "limit": float}
GET  /get_services           (header x-api-key)  -> [Service, ...]
GET  /get_rate/{code}        (header x-api-key)  -> [Rate, ...]
GET  /get_messages/{api_key} (query service)     -> [Message, ...]
GET  /get_actual_senders/    (query api_key)     -> [str, ...]
POST /get_number             (header x-api-key)  -> аренда номера
POST /get_status             (header x-api-key)  -> статус/код активации
POST /set_status             (header x-api-key)  -> управление активацией
POST /activate_number        (header x-api-key)  -> активация существующего номера
"""
import httpx
import random
import time
from typing import Optional, Dict, List, Any


class PartnerAPI:
    """Клиент Partner REST API (https://46.21.159.86/partner)."""
    BASE_URL = "https://46.21.159.86/partner"

    STATUS_CANCEL = -1
    STATUS_REQUEST_ANOTHER = 3
    STATUS_COMPLETE = 6
    STATUS_NUMBER_USED = 8

    SERVICES = {
        "Microsoft": "mm",
        "Outlook": "mm",
        "Apple": "wx",
        "Google": "go",
        "Gmail": "go",
        "Telegram": "tg",
        "WhatsApp": "wa",
        "WhatsApp Business": "wab",
        "VK": "vk",
        "Facebook": "fb",
        "Instagram": "ig",
        "Snapchat": "fu",  # ✅ Правильно
        "Airbnb": "uk",
        "Amazon": "am",
        "Binance": "bnb",
        "Alibaba": "alibaba",
        "1xBet": "onex",
        "Discord": "ds",
    }

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        service: str = "Microsoft",
        country: str = "all",
        max_price: float = 0,
        timeout: int = 30,
        proxy_manager=None,
        verify_ssl: bool = False,
    ):
        self.api_key = api_key
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.service = service
        self.country = country
        self.max_price = max_price
        self.timeout = timeout
        self.proxy_manager = proxy_manager
        self.verify_ssl = verify_ssl
        self._services_cache = None
        self._services_cached_at = 0.0

    def _get(self, path: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Any:
        from .logger import log
        proxy_url = None
        if self.proxy_manager:
            proxy_dict = self.proxy_manager.get_requests_proxy()
            if proxy_dict:
                proxy_url = proxy_dict.get("https") or proxy_dict.get("http")

        request_headers = dict(headers or {})
        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            with httpx.Client(proxy=proxy_url, verify=self.verify_ssl) as client:
                response = client.get(url, params=params, headers=request_headers, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            log.error("Таймаут при запросе к Partner API")
            return None
        except httpx.ConnectError:
            log.error("Ошибка соединения с Partner API")
            return None
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text
            except Exception:
                pass
            log.error(f"HTTP ошибка {e.response.status_code}: {body[:200]}")
            return None
        except ValueError as e:
            log.error(f"Некорректный JSON-ответ ({path}): {e}")
            return None
        except Exception as e:
            log.error(f"Исключение при запросе: {e}")
            return None

    def _post(self, path: str, json: Optional[dict] = None, headers: Optional[dict] = None) -> Any:
        from .logger import log
        proxy_url = None
        if self.proxy_manager:
            proxy_dict = self.proxy_manager.get_requests_proxy()
            if proxy_dict:
                proxy_url = proxy_dict.get("https") or proxy_dict.get("http")

        request_headers = dict(headers or {})
        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            with httpx.Client(proxy=proxy_url, verify=self.verify_ssl) as client:
                response = client.post(url, json=json, headers=request_headers, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            log.error("Таймаут при запросе к Partner API")
            return None
        except httpx.ConnectError:
            log.error("Ошибка соединения с Partner API")
            return None
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text
            except Exception:
                pass
            log.error(f"HTTP ошибка {e.response.status_code}: {body[:200]}")
            return None
        except ValueError as e:
            log.error(f"Некорректный JSON-ответ ({path}): {e}")
            return None
        except Exception as e:
            log.error(f"Исключение при запросе: {e}")
            return None

    def _auth_headers(self) -> Dict[str, str]:
        return {"x-api-key": self.api_key}

    def get_balance(self) -> Optional[Dict[str, float]]:
        from .logger import log
        data = self._get("get_balance", headers=self._auth_headers())
        if not isinstance(data, dict):
            return None
        try:
            return {"usd": float(data.get("usd", 0.0)), "limit": float(data.get("limit", 0.0))}
        except (TypeError, ValueError):
            log.error(f"Не удалось разобрать баланс: {data}")
            return None

    def get_services(self) -> Optional[List[Dict]]:
        data = self._get("get_services", headers=self._auth_headers())
        if isinstance(data, list):
            return data
        return None

    def get_rate(self, code: str) -> Optional[List[Dict]]:
        data = self._get(f"get_rate/{code}", headers=self._auth_headers())
        if isinstance(data, list):
            return data
        return None

    def get_messages(self, api_key: Optional[str] = None, service: Optional[str] = None) -> Optional[List[Dict]]:
        key = api_key or self.api_key
        params = None
        if service:
            params = {"service": service}
        data = self._get(f"get_messages/{key}", params=params)
        if isinstance(data, list):
            return data
        return None

    def get_actual_senders(self, api_key: Optional[str] = None) -> Optional[List[str]]:
        key = api_key or self.api_key
        data = self._get("get_actual_senders/", params={"api_key": key})
        if isinstance(data, list):
            return data
        return None

    def _resolve_service(self, service: str) -> str:
        return self.SERVICES.get(service, service)

    def _get_services_cached(self) -> Optional[List[Dict]]:
        now = time.time()
        if self._services_cache is not None and now - self._services_cached_at < 300:
            return self._services_cache
        data = self.get_services()
        self._services_cache = data
        self._services_cached_at = now
        return data

    def _pick_country(self, service_code: str) -> Optional[str]:
        from .logger import log
        services = self._get_services_cached()
        if not services:
            log.error("Не удалось получить список сервисов для выбора страны")
            return None
        for svc in services:
            if svc.get("code") == service_code:
                countries = svc.get("countries") or []
                if not countries:
                    log.error(f"Нет доступных стран для сервиса {service_code}")
                    return None
                chosen = random.choice(countries)
                return chosen.get("code") or str(chosen.get("id"))
        log.error(f"Сервис {service_code} не найден в списке")
        return None

    def get_number(self, service: str, country=None, operator: Optional[str] = None, extra_fields: Optional[dict] = None) -> Optional[Dict]:
        from .logger import log
        payload = {"service": service}
        if country is not None:
            payload["country"] = country
        if operator:
            payload["operator"] = operator
        if extra_fields is not None:
            payload["extra_fields"] = extra_fields

        data = self._post("get_number", json=payload, headers=self._auth_headers())
        if not isinstance(data, dict):
            return None
        if data.get("error") and not data.get("id"):
            log.error(f"get_number: {data.get('error')}")
            return None
        if not data.get("id"):
            log.error(f"get_number: неожиданный ответ {data}")
            return None
        return data

    def get_numbers(self, requests: List[Dict]) -> Optional[List[Dict]]:
        from .logger import log
        if not requests:
            return []
        if len(requests) > 100:
            log.warning("get_numbers: максимум 100 документов, обрезаю")
            requests = requests[:100]
        data = self._post("get_number", json=requests, headers=self._auth_headers())
        return data if isinstance(data, list) else None

    def rent_number(self, service: Optional[str] = None, country: Optional[str] = None, max_price: Optional[float] = None, operator: Optional[str] = None, max_retries: int = 3) -> Optional[Dict[str, str]]:
        from .logger import log
        if service is None:
            service = self.service
        if country is None:
            country = self.country

        service_code = self._resolve_service(service)

        for attempt in range(max_retries):
            use_country = country
            if not use_country or str(use_country).lower() in ("all", "any", ""):
                use_country = self._pick_country(service_code)
                if use_country is None:
                    return None

            data = self.get_number(service_code, country=use_country, operator=operator or None)
            if data and data.get("id"):
                result = {"id": data["id"], "number": data["number"]}
                if data.get("country_code"):
                    result["country_code"] = data["country_code"]
                if data.get("operator_name"):
                    result["operator_name"] = data["operator_name"]
                if data.get("lifetime") is not None:
                    result["lifetime"] = data["lifetime"]
                return result

            log.warning(f"Не удалось арендовать номер (попытка {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(2)

        return None

    def get_status(self, activation_id: str) -> Optional[Dict]:
        from .logger import log
        data = self._post("get_status", json={"id": activation_id}, headers=self._auth_headers())
        if not isinstance(data, dict):
            return None
        if data.get("success") is False:
            log.warning(f"get_status: {data.get('error')}")
            return None
        return data

    def get_statuses(self, ids: List[str]) -> Optional[List[Dict]]:
        from .logger import log
        if not ids:
            return []
        if len(ids) > 100:
            log.warning("get_statuses: максимум 100 документов, обрезаю")
            ids = ids[:100]
        payload = [{"id": i} for i in ids]
        data = self._post("get_status", json=payload, headers=self._auth_headers())
        return data if isinstance(data, list) else None

    def wait_code(self, activation_id: str, timeout: int = 300, poll_interval: int = 5) -> Optional[str]:
        from .logger import log
        start = time.time()
        attempts = 0
        while time.time() - start < timeout:
            attempts += 1
            data = self.get_status(activation_id)
            if data is None:
                time.sleep(poll_interval)
                continue
            status = data.get("status")
            code = data.get("code")
            if status == "ok" and code:
                log.info(f"SMS-код получен ({attempts} опросов)")
                return str(code)
            if status == "cancel":
                log.warning("Активация отменена провайдером")
                return None
            time.sleep(poll_interval)
        log.warning(f"Таймаут ожидания SMS ({timeout} сек, {attempts} попыток)")
        return None

    def get_code_immediate(self, activation_id: str) -> Optional[str]:
        data = self.get_status(activation_id)
        if data and data.get("status") == "ok" and data.get("code"):
            return str(data["code"])
        return None

    def set_status(self, activation_id: str, status_code: int) -> bool:
        from .logger import log
        data = self._post("set_status", json={"id": activation_id, "status_code": status_code}, headers=self._auth_headers())
        if not isinstance(data, dict):
            return False
        if data.get("success") is False:
            log.warning(f"set_status: {data.get('error')}")
            return False
        return True

    def confirm(self, activation_id: str):
        from .logger import log
        if self.set_status(activation_id, self.STATUS_COMPLETE):
            log.debug(f"Активация {activation_id} подтверждена")
        else:
            log.warning(f"Не удалось подтвердить активацию {activation_id}")

    def cancel(self, activation_id: str):
        from .logger import log
        if self.set_status(activation_id, self.STATUS_CANCEL):
            log.debug(f"Активация {activation_id} отменена")
        else:
            log.warning(f"Не удалось отменить активацию {activation_id}")

    def report_bad_number(self, activation_id: str):
        from .logger import log
        if self.set_status(activation_id, self.STATUS_NUMBER_USED):
            log.debug(f"Номер {activation_id} помечен как использованный")
        else:
            log.warning(f"Не удалось пометить номер {activation_id}")

    def activate_number(self, service: str, number: str, country: Optional[str] = None, operator: Optional[str] = None, any_key: Optional[str] = None) -> Optional[Dict]:
        from .logger import log
        payload = {"service": service, "number": number}
        if country is not None:
            payload["country"] = country
        if operator is not None:
            payload["operator"] = operator
        if any_key is not None:
            payload["any_key"] = any_key

        data = self._post("activate_number", json=payload, headers=self._auth_headers())
        if not isinstance(data, dict):
            return None
        if data.get("error") and not data.get("id"):
            log.error(f"activate_number: {data.get('error')}")
            return None
        return data

    def get_active_activations(self) -> List[Dict]:
        return []