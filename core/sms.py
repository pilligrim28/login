"""
Модуль работы с SMS-Activate совместимым API.
Аренда номеров, получение кодов, управление активациями.

Поддерживается любой провайдер с протоколом SMS-Activate v1
(endpoint вида https://host/stubs/handler_api.php с query-параметром
api_key). Базовый URL настраивается через параметр ``base_url``
конструктора или ключ конфига ``sms.api_url``.

Ответы приходят в текстовом виде, например:
    ACCESS_BALANCE:100.5
    ACCESS_NUMBER:123456789:79991234567
    STATUS_OK:100001
"""

import httpx
import time
from typing import Optional, Dict, List, Any


class SMSActivate:
    """Клиент для SMS-Activate совместимого API."""

    # Базовый URL endpoint SMS-Activate v1.
    # Настраивается через параметр ``base_url`` конструктора или
    # ключ конфига ``sms.api_url``.
    BASE_URL = "https://46.21.159.86/stubs/handler_api.php"

    # Сопоставление понятных имён сервисов с их короткими кодами.
    # Актуальный список кодов можно получить через getServicesList().
    # Значение, не найденное в словаре, передаётся в API как есть
    # (считается, что это уже короткий код сервиса).
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
    }

    def __init__(
            self,
            api_key: str,
            service: str = "Microsoft",
            country: str = "all",
            max_price: float = 0,
            operator: str = "",
            timeout: int = 20,
            proxy_manager = None,
            base_url: Optional[str] = None,
            verify_ssl: bool = False
    ):
        """
        Инициализация клиента.

        Args:
            api_key: API-ключ SMS-провайдера (SMS-Activate совместимый)
            service: Название сервиса (Microsoft, Google и т.д.)
            country: Код страны (all, RU, US, UA и т.д.)
            max_price: Максимальная цена за номер (0 = без лимита)
            operator: Номер оператора (пусто = любой)
            timeout: Таймаут HTTP-запросов (сек)
            proxy_manager: ProxyManager для ротации прокси
            base_url: URL endpoint (по умолчанию BASE_URL)
            verify_ssl: Проверять SSL-сертификат (False — для хостов
                с самоподписанным сертификатом, напр. по IP-адресу)
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
        Выполнить GET-запрос к SMS-Activate совместимому API.

        Args:
            action: Действие (getBalance, getNumber, getStatus, ...)
            params: Дополнительные query-параметры

        Returns:
            Сырой текст ответа или None при ошибке
        """
        query = {"action": action, "api_key": self.api_key}
        if params:
            query.update(params)

        # Прокси (httpx 0.28 принимает одиночный URL в proxy=)
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
        Преобразовать понятное имя сервиса в его короткий код.
        Неизвестное значение передаётся как есть (предполагается, что
        это уже корректный код сервиса).
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
    # СПИСОК СТРАН
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
    # СПИСОК СЕРВИСОВ
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
            service: Сервис (Microsoft, Google и т.д.) или его короткий код
            country: ID страны (число) или "all" (любая страна)
            max_price: Максимальная цена (0 = без лимита)
            operator: Оператор(ы) через запятую (пусто = любой)
            max_retries: Максимум попыток

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
                log.error(f"Неожиданный формат номера: {text}")
                return None

            if text == "NO_NUMBERS":
                log.warning(f"Нет номеров (попытка {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(15)
                continue
            elif text == "NO_BALANCE":
                log.error("Недостаточно средств")
                return None
            elif text == "BAD_KEY":
                log.error("Неверный API-ключ")
                return None
            elif text == "BAD_SERVICE":
                log.error(f"Неверный сервис: {service}")
                return None
            elif text == "BAD_ACTION":
                log.error(f"Неверное действие: {text}")
                return None
            elif text.startswith("WRONG_MAX_PRICE:"):
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
            timeout: Максимальное время ожидания (сек)
            poll_interval: Интервал опроса (сек)

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
                if text.startswith("STATUS_OK:"):
                    code = text.split(":", 1)[1]
                    if code:
                        log.success(f"SMS получен за {attempts} попыток")
                        return code
                elif text == "STATUS_CANCEL":
                    log.warning("Аренда отменена сервисом")
                    return None
                elif text == "STATUS_WAIT_CODE":
                    pass  # Ещё ждём — это норма
                elif text.startswith("STATUS_WAIT_RETRY"):
                    pass  # Ждём уточняющего кода
                elif text == "STATUS_WAIT_RESEND":
                    pass  # Ждём повторной отправки
                elif text == "NO_ACTIVATION":
                    log.warning("ID активации не существует")
                    return None
                elif text == "BAD_KEY":
                    log.error("Неверный API-ключ")
                    return None
                else:
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
    # УПРАВЛЕНИЕ АКТИВАЦИЕЙ
    # ============================================

    def confirm(self, activation_id: str):
        """
        Подтвердить успешную активацию (завершить аренду).

        Args:
            activation_id: ID активации
        """
        from .logger import log

        # status=6 — завершить активацию (код получен и подтверждён)
        text = self._request("setStatus", {"id": activation_id, "status": 6})

        if text == "ACCESS_ACTIVATION":
            log.debug(f"Активация {activation_id} подтверждена")
        elif text == "NO_ACTIVATION":
            log.warning(f"Активация {activation_id} не найдена")
        else:
            log.warning(f"Не удалось подтвердить {activation_id}: {text}")

    def cancel(self, activation_id: str):
        """
        Отменить аренду.

        Args:
            activation_id: ID активации
        """
        from .logger import log

        # status=8 — отменить активацию (вернуть деньги)
        text = self._request("setStatus", {"id": activation_id, "status": 8})

        if text == "ACCESS_CANCEL":
            log.debug(f"Активация {activation_id} отменена")
        elif text == "EARLY_CANCEL_DENIED":
            log.warning(f"Нельзя отменить {activation_id} в первые 2 минуты")
        elif text == "NO_ACTIVATION":
            log.warning(f"Активация {activation_id} не найдена")
        else:
            log.warning(f"Не удалось отменить {activation_id}: {text}")

    def report_bad_number(self, activation_id: str):
        """
        Пожаловаться на номер.

        В SMS-Activate совместимом API нет отдельного действия «плохой
        номер», поэтому выполняем отмену активации (status=8) — это
        возвращает средства.

        Args:
            activation_id: ID активации
        """
        self.cancel(activation_id)

    # ============================================
    # СТАТИСТИКА АККАУНТА
    # ============================================

    def get_active_activations(self) -> List[Dict]:
        """
        Получить активные активации.

        Returns:
            Список активаций
        """
        data = self._request_json("getActiveActivations")
        if isinstance(data, dict):
            items = data.get("data")
            if isinstance(items, list):
                return items
        if isinstance(data, list):
            return data
        return []
