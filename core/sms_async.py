"""
Асинхронный модуль работы с SMS-Activate совместимым API.
Использует httpx.AsyncClient для асинхронных запросов.
"""

import httpx
import time
from typing import Optional, Dict, List, Any


class AsyncSMSActivate:
    """
    Асинхронный клиент для SMS-Activate совместимого API.
    
    Пример использования:
        async with AsyncSMSActivate(api_key="YOUR_API_KEY") as sms:
            balance = await sms.get_balance()
            number = await sms.rent_number(service="Microsoft")
            code = await sms.wait_code(number["id"])
    """

    BASE_URL = "https://sms-activate.ru/stubs/handler_api.php"

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
            base_url: Optional[str] = None,
            verify_ssl: bool = False,
            proxy: Optional[str] = None
    ):
        """
        Инициализация клиента.

        Args:
            api_key: API-ключ SMS-Activate
            service: Название сервиса
            country: Код страны
            max_price: Максимальная цена
            operator: Оператор
            timeout: Таймаут запросов
            base_url: Base URL API
            verify_ssl: Проверять SSL
            proxy: Прокси для запросов
        """
        self.api_key = api_key
        self.service = service
        self.country = country
        self.max_price = max_price
        self.operator = operator
        self.timeout = timeout
        self.base_url = base_url or self.BASE_URL
        self.verify_ssl = verify_ssl
        self.proxy = proxy
        
        self._client = None

    async def __aenter__(self):
        """Асинхронный контекстный менеджер (вход)."""
        self._client = httpx.AsyncClient(
            verify=self.verify_ssl,
            proxy=self.proxy,
            timeout=self.timeout
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный контекстный менеджер (выход)."""
        if self._client:
            await self._client.aclose()

    async def close(self):
        """Закрыть клиент."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self):
        """Получить клиент (создать если не существует)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                verify=self.verify_ssl,
                proxy=self.proxy,
                timeout=self.timeout
            )
        return self._client

    async def _request(self, action: str, params: Optional[dict] = None) -> Optional[str]:
        """
        Выполнить асинхронный GET-запрос к API.

        Args:
            action: Действие
            params: Дополнительные параметры

        Returns:
            Текст ответа или None
        """
        from .logger import log
        
        query = {"action": action, "api_key": self.api_key}
        if params:
            query.update(params)

        try:
            client = self._get_client()
            response = await client.get(self.base_url, params=query)
            response.raise_for_status()
            return response.text
        except httpx.TimeoutException:
            log.error("Таймаут при запросе к SMS-API")
            return None
        except httpx.ConnectError:
            log.error("Ошибка соединения с SMS-API")
            return None
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text
            except Exception:
                pass
            log.error(f"HTTP ошибка {e.response.status_code}: {body[:200]}")
            return None
        except Exception as e:
            log.error(f"Исключение при запросе: {e}")
            return None

    def _resolve_service(self, service: str) -> str:
        """Преобразовать название сервиса в код."""
        return self.SERVICES.get(service, service)

    # ============================================
    # БАЛАНС
    # ============================================

    async def get_balance(self) -> Optional[float]:
        """Получить баланс."""
        from .logger import log
        
        text = await self._request("getBalance")
        if not text:
            return None

        if text.startswith("ACCESS_BALANCE:"):
            try:
                return float(text.split(":", 1)[1])
            except (ValueError, IndexError):
                log.error(f"Не удалось разобрать баланс: {text}")
                return None

        log.error(f"Ошибка получения баланса: {text}")
        return None

    # ============================================
    # АРЕНДА НОМЕРА
    # ============================================

    async def rent_number(
            self,
            service: Optional[str] = None,
            country: Optional[str] = None,
            max_price: Optional[float] = None,
            operator: Optional[str] = None,
            max_retries: int = 3
    ) -> Optional[Dict[str, str]]:
        """Арендовать номер."""
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

            text = await self._request("getNumber", params)

            if text is None:
                await asyncio.sleep(2)
                continue

            if text.startswith("ACCESS_NUMBER:"):
                parts = text.split(":")
                if len(parts) >= 3:
                    return {"id": parts[1], "number": parts[2]}
                log.error(f"Неожданный формат номера: {text}")
                return None

            # Обработка ошибок
            if text == "NO_NUMBERS":
                log.warning(f"Нет номеров (попытка {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(15)
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
            elif text.startswith("WRONG_MAX_PRICE:"):
                log.error(f"Максимальная цена ниже допустимой: {text}")
                return None
            elif text.startswith("BANNED"):
                log.error(f"Аккаунт заблокирован: {text}")
                return None
            else:
                log.error(f"Неизвестный ответ getNumber: {text}")

            await asyncio.sleep(2)

        return None

    # ============================================
    # ПОЛУЧЕНИЕ КОДА
    # ============================================

    async def wait_code(
            self,
            activation_id: str,
            timeout: int = 300,
            poll_interval: int = 5
    ) -> Optional[str]:
        """Ожидать SMS-код."""
        from .logger import log

        start = time.time()
        attempts = 0

        while time.time() - start < timeout:
            attempts += 1
            text = await self._request("getStatus", {"id": activation_id})

            if text:
                if text.startswith("STATUS_OK:"):
                    code = text.split(":", 1)[1]
                    if code:
                        log.success(f"SMS получен за {attempts} попыток")
                        return code
                elif text == "STATUS_CANCEL":
                    log.warning("Аренда отменена сервисом")
                    return None
                elif text in ["STATUS_WAIT_CODE", "STATUS_WAIT_RETRY", "STATUS_WAIT_RESEND"]:
                    pass
                elif text == "NO_ACTIVATION":
                    log.warning("ID активации не существует")
                    return None
                elif text == "BAD_KEY":
                    log.error("Неверный API-ключ")
                    return None
                else:
                    log.warning(f"Неизвестный статус: {text}")

            await asyncio.sleep(poll_interval)

        log.warning(f"Таймаут ожидания SMS ({timeout} сек, {attempts} попыток)")
        return None

    async def get_code_immediate(self, activation_id: str) -> Optional[str]:
        """Проверить код один раз."""
        text = await self._request("getStatus", {"id": activation_id})
        if text and text.startswith("STATUS_OK:"):
            code = text.split(":", 1)[1]
            if code:
                return code
        return None

    # ============================================
    # УПРАВЛЕНИЕ АКТИВАЦИЯМИ
    # ============================================

    async def confirm(self, activation_id: str):
        """Подтвердить активацию."""
        from .logger import log
        
        text = await self._request("setStatus", {"id": activation_id, "status": 6})
        if text == "ACCESS_ACTIVATION":
            log.debug(f"Активация {activation_id} подтверждена")
        else:
            log.warning(f"Не удалось подтвердить активацию {activation_id}: {text}")

    async def cancel(self, activation_id: str):
        """Отменить активацию."""
        from .logger import log
        
        text = await self._request("setStatus", {"id": activation_id, "status": 8})
        if text == "ACCESS_CANCEL":
            log.debug(f"Активация {activation_id} отменена")
        elif text == "EARLY_CANCEL_DENIED":
            log.warning(f"Нельзя отменить активацию {activation_id} в первые 2 минуты")
        else:
            log.warning(f"Не удалось отменить активацию {activation_id}: {text}")

    async def report_bad_number(self, activation_id: str):
        """Пожаловаться на номер."""
        await self.cancel(activation_id)
