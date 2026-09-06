"""
Модуль работы с SMS-Activate совместимым API.
Аренда номеров, получение SMS-кодов, проверка баланса.

Поддерживает:
- SMS-Activate (основной сервис)
- Настраиваемый base_url через конфигурацию
- Работа через прокси
- Обработка всех основных ошибок API
"""

import httpx
import time
from typing import Optional, Dict, List, Any


class SMSActivate:
    """
    Клиент для SMS-Activate совместимого API.
    
    Пример использования:
        sms = SMSActivate(api_key="YOUR_API_KEY")
        balance = sms.get_balance()
        number = sms.rent_number(service="Microsoft")
        code = sms.wait_code(number["id"])
    """

    # Базовый URL API (можно переопределить через base_url в конструкторе)
    # По умолчанию используется рабочий URL SMS-Activate
    BASE_URL = "https://sms-activate.ru/stubs/handler_api.php"

    # Соответствие названий сервисов их кодам в API
    SERVICES = {
        "Microsoft": "mm",
        "Outlook": "mm",
        "Snapchat": "sf",
        "Apple": "at",
        "Google": "go",
        "Telegram": "tg",
        "WhatsApp": "wa",
        "VK": "vk",
        "Facebook": "fb",
        "Instagram": "ig",
        "Twitter": "tw",
        "TikTok": "tt",
    }

    def __init__(
            self,
            api_key: str,
            service: str = "Microsoft",
            country: str = "all",
            max_price: float = 0,
            operator: str = "",
            timeout: int = 30,
            proxy_manager = None,
            base_url: Optional[str] = None,
            verify_ssl: bool = False
    ):
        """
        Инициализация клиента.

        Args:
            api_key: API-ключ SMS-Activate совместимого сервиса
            service: Название сервиса (Microsoft, Google и т.д.)
            country: Код страны (all, RU, US, UA и т.д.)
            max_price: Максимальная цена за номер (0 = без лимита)
            operator: Оператор (пусто = любой)
            timeout: Таймаут HTTP-запросов (секунды)
            proxy_manager: Менеджер прокси для запросов
            base_url: Base URL API (по умолчанию BASE_URL)
            verify_ssl: Проверять SSL-сертификаты (False для тестовых серверов)
        """
        self.api_key = api_key
        self.service = service
        self.country = country
        self.max_price = max_price
        self.operator = operator
        self.timeout = timeout
        self.proxy_manager = proxy_manager
        self.base_url = base_url or self.BASE_URL
        self.verify_ssl = verify_ssl

    # ============================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # ============================================

    def _request(self, action: str, params: Optional[dict] = None) -> Optional[str]:
        """
        Выполнить GET-запрос к API.

        Args:
            action: Действие (getBalance, getNumber, getStatus, ...)
            params: Дополнительные параметры запроса

        Returns:
            Сырой текст ответа или None при ошибке
        """
        query = {"action": action, "api_key": self.api_key}
        if params:
            query.update(params)

        # Прокси для запроса
        proxy_url = None
        if self.proxy_manager:
            proxy_dict = self.proxy_manager.get_requests_proxy()
            if proxy_dict:
                proxy_url = proxy_dict.get("https") or proxy_dict.get("http")

        try:
            with httpx.Client(proxy=proxy_url, verify=self.verify_ssl) as client:
                response = client.get(self.base_url, params=query, timeout=self.timeout)
                response.raise_for_status()
                return response.text
        except httpx.TimeoutException:
            from .logger import log
            log.error("Таймаут при запросе к SMS-API")
            return None
        except httpx.ConnectError:
            from .logger import log
            log.error("Ошибка соединения с SMS-API")
            return None
        except httpx.HTTPStatusError as e:
            from .logger import log
            body = ""
            try:
                body = e.response.text
            except Exception:
                pass
            log.error(f"HTTP ошибка {e.response.status_code}: {body[:200]}")
            return None
        except Exception as e:
            from .logger import log
            log.error(f"Исключение при запросе: {e}")
            return None

    def _request_json(self, action: str, params: Optional[dict] = None) -> Any:
        """Выполнить запрос и разобрать JSON-ответ."""
        import json

        text = self._request(action, params)
        if text is None:
            return None

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            from .logger import log
            log.error(f"Некорректный JSON-ответ ({action}): {text[:200]}")
            return None

    def _resolve_service(self, service: str) -> str:
        """
        Преобразовать название сервиса в его код.
        Если сервис не найден в списке, возвращает его как есть.
        """
        return self.SERVICES.get(service, service)

    # ============================================
    # БАЛАНС
    # ============================================

    def get_balance(self) -> Optional[float]:
        """
        Получить баланс аккаунта.

        Returns:
            Баланс или None при ошибке
        """
        from .logger import log

        text = self._request("getBalance")
        if not text:
            return None

        # Формат ответа: ACCESS_BALANCE:100.5
        if text.startswith("ACCESS_BALANCE:"):
            try:
                return float(text.split(":", 1)[1])
            except (ValueError, IndexError):
                log.error(f"Не удалось разобрать баланс: {text}")
                return None

        log.error(f"Ошибка получения баланса: {text}")
        return None

    # ============================================
    # СТРАНЫ
    # ============================================

    def get_countries(self) -> Optional[List[Dict]]:
        """
        Получить список доступных стран.

        Returns:
            Список стран или None
        """
        data = self._request_json("getCountries")
        if isinstance(data, list):
            return data
        return None

    # ============================================
    # СЕРВИСЫ
    # ============================================

    def get_services(self) -> Optional[List[Dict]]:
        """
        Получить список доступных сервисов.

        Returns:
            Список сервисов или None
        """
        data = self._request_json("getServicesList")
        if isinstance(data, dict) and data.get("status") == "success":
            return data.get("services", [])
        return None

    # ============================================
    # АРЕНДА НОМЕРА
    # ============================================

    def rent_number(
            self,
            service: Optional[str] = None,
            country: Optional[str] = None,
            max_price: Optional[float] = None,
            operator: Optional[str] = None,
            max_retries: int = 3
    ) -> Optional[Dict[str, str]]:
        """
        Арендовать номер.

        Args:
            service: Сервис (Microsoft, Google и т.д.) или его код
            country: ID страны (число) или "all" (любая страна)
            max_price: Максимальная цена (0 = без лимита)
            operator: Оператор (пусто = любой)
            max_retries: Максимальное количество попыток

        Returns:
            {"id": activation_id, "number": phone} или None
        """
        from .logger import log

        if service is None:
            service = self.service
        if country is None:
            country = self.country
        if max_price is None:
            max_price = self.max_price
        if operator is None:
            operator = self.operator

        service_code = self._resolve_service(service)

        for attempt in range(max_retries):
            params = {"service": service_code}
            if country and str(country).lower() != "all":
                params["country"] = country
            if max_price and max_price > 0:
                params["maxPrice"] = max_price
            if operator:
                params["operator"] = operator

            text = self._request("getNumber", params)

            if text is None:
                time.sleep(2)
                continue

            # Успех: ACCESS_NUMBER:<id>:<phone>
            if text.startswith("ACCESS_NUMBER:"):
                parts = text.split(":")
                if len(parts) >= 3:
                    return {
                        "id": parts[1],
                        "number": parts[2]
                    }
                log.error(f"Неожданный формат номера: {text}")
                return None

            # Обработка ошибок
            error_handlers = {
                "NO_NUMBERS": lambda: log.warning(f"Нет номеров (попытка {attempt + 1}/{max_retries})"),
                "NO_BALANCE": lambda: log.error("Недостаточно средств"),
                "BAD_KEY": lambda: log.error("Неверный API-ключ"),
                "BAD_SERVICE": lambda: log.error(f"Неверный сервис: {service}"),
                "BAD_ACTION": lambda: log.error(f"Неверное действие: {text}"),
            }

            for error_code, handler in error_handlers.items():
                if text == error_code:
                    handler()
                    if error_code == "NO_NUMBERS" and attempt < max_retries - 1:
                        time.sleep(15)
                    elif error_code in ["NO_BALANCE", "BAD_KEY", "BAD_SERVICE", "BAD_ACTION"]:
                        return None
                    continue

            if text.startswith("WRONG_MAX_PRICE:"):
                log.error(f"Максимальная цена ниже допустимой: {text}")
                return None
            elif text.startswith("BANNED"):
                log.error(f"Аккаунт заблокирован: {text}")
                return None
            else:
                log.error(f"Неизвестный ответ getNumber: {text}")

            time.sleep(2)

        return None

    # ============================================
    # ПОЛУЧЕНИЕ КОДА
    # ============================================

    def wait_code(
            self,
            activation_id: str,
            timeout: int = 300,
            poll_interval: int = 5
    ) -> Optional[str]:
        """
        Ожидать SMS-код.

        Args:
            activation_id: ID активации
            timeout: Максимальное время ожидания (секунды)
            poll_interval: Интервал опроса (секунды)

        Returns:
            Код подтверждения или None
        """
        from .logger import log

        start = time.time()
        attempts = 0

        while time.time() - start < timeout:
            attempts += 1
            text = self._request("getStatus", {"id": activation_id})

            if text:
                response_handlers = {
                    "STATUS_OK:": lambda t: t.split(":", 1)[1] if len(t.split(":")) > 1 else None,
                    "STATUS_CANCEL": lambda t: (log.warning("Аренда отменена сервисом"), None)[1],
                    "STATUS_WAIT_CODE": lambda t: None,
                    "STATUS_WAIT_RETRY": lambda t: None,
                    "STATUS_WAIT_RESEND": lambda t: None,
                    "NO_ACTIVATION": lambda t: (log.warning("ID активации не существует"), None)[1],
                    "BAD_KEY": lambda t: (log.error("Неверный API-ключ"), None)[1],
                }

                for prefix, handler in response_handlers.items():
                    if text.startswith(prefix):
                        result = handler(text)
                        if prefix == "STATUS_OK:" and result:
                            log.success(f"SMS получен за {attempts} попыток")
                            return result
                        elif prefix in ["STATUS_CANCEL", "NO_ACTIVATION", "BAD_KEY"]:
                            return result
                        break
                else:
                    if text not in ["STATUS_WAIT_CODE", "STATUS_WAIT_RETRY", "STATUS_WAIT_RESEND"]:
                        log.warning(f"Неизвестный статус: {text}")

            time.sleep(poll_interval)

        log.warning(f"Таймаут ожидания SMS ({timeout} сек, {attempts} попыток)")
        return None

    def get_code_immediate(self, activation_id: str) -> Optional[str]:
        """
        Проверить код один раз (без ожидания).

        Args:
            activation_id: ID активации

        Returns:
            Код или None
        """
        text = self._request("getStatus", {"id": activation_id})
        if text and text.startswith("STATUS_OK:"):
            code = text.split(":", 1)[1]
            if code:
                return code
        return None

    # ============================================
    # УПРАВЛЕНИЕ АКТИВАЦИЯМИ
    # ============================================

    def confirm(self, activation_id: str):
        """
        Подтвердить активацию (заверить номер).

        Args:
            activation_id: ID активации
        """
        from .logger import log

        # status=6 — завершить активацию (код получен и использован)
        text = self._request("setStatus", {"id": activation_id, "status": 6})

        if text == "ACCESS_ACTIVATION":
            log.debug(f"Активация {activation_id} подтверждена")
        elif text == "NO_ACTIVATION":
            log.warning(f"Активация {activation_id} не найдена")
        else:
            log.warning(f"Не удалось подтвердить активацию {activation_id}: {text}")

    def cancel(self, activation_id: str):
        """
        Отменить активацию.

        Args:
            activation_id: ID активации
        """
        from .logger import log

        # status=8 — отменить активацию (вернуть деньги)
        text = self._request("setStatus", {"id": activation_id, "status": 8})

        if text == "ACCESS_CANCEL":
            log.debug(f"Активация {activation_id} отменена")
        elif text == "EARLY_CANCEL_DENIED":
            log.warning(f"Нельзя отменить активацию {activation_id} в первые 2 минуты")
        elif text == "NO_ACTIVATION":
            log.warning(f"Активация {activation_id} не найдена")
        else:
            log.warning(f"Не удалось отменить активацию {activation_id}: {text}")

    def report_bad_number(self, activation_id: str):
        """
        Пожаловаться на номер.

        Args:
            activation_id: ID активации
        """
        self.cancel(activation_id)

    # ============================================
    # СТАТИСТИКА АКТИВАЦИЙ
    # ============================================

    def get_active_activations(self) -> List[Dict]:
        """
        Получить активные активации.

        Returns:
            Список активных активаций
        """
        data = self._request_json("getActiveActivations")
        if isinstance(data, dict):
            items = data.get("data")
            if isinstance(items, list):
                return items
        if isinstance(data, list):
            return data
        return []
