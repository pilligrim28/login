"""
Модуль работы с SMS-Activate API.
Аренда номеров, получение кодов, управление активациями.
"""

import httpx
import time
from typing import Optional, Dict, List


class SMSActivate:
    """Клиент для SMS-Activate.org API."""

    BASE_URL = "https://api.sms-activate.org/stubs/handler_api.php"

    # Коды сервисов
    SERVICES = {
        "op": "Microsoft / Outlook",
        "sc": "Snapchat",
        "ap": "Apple",
        "go": "Google",
        "tg": "Telegram",
        "wa": "WhatsApp",
        "vk": "VK",
        "ok": "Одноклассники",
        "fb": "Facebook",
        "ig": "Instagram"
    }

    # Коды стран
    COUNTRIES = {
        0: "Россия",
        1: "Украина",
        2: "Казахстан",
        3: "Беларусь",
        4: "США",
        5: "Германия",
        6: "Польша",
        7: "Турция",
        8: "Индия",
        9: "Китай"
    }

    def __init__(
            self,
            api_key: str,
            service_code: str = "op",
            country: int = 0,
            timeout: int = 20
    ):
        """
        Инициализация клиента.

        Args:
            api_key: API-ключ от sms-activate.org
            service_code: Код сервиса (op, sc, ap и т.д.)
            country: Код страны (0 = Россия)
            timeout: Таймаут HTTP-запросов (сек)
        """
        self.api_key = api_key
        self.service_code = service_code
        self.country = country
        self.timeout = timeout

    # ============================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # ============================================

    def _request(self, params: dict) -> str:
        """
        Выполнить GET-запрос к API.

        Args:
            params: Параметры запроса

        Returns:
            Текстовый ответ
        """
        params["api_key"] = self.api_key

        try:
            response = httpx.get(
                self.BASE_URL,
                params=params,
                timeout=self.timeout
            )
            return response.text.strip()
        except httpx.TimeoutException:
            from .logger import log
            log.error("Таймаут при запросе к SMS-Activate")
            return "ERROR: TIMEOUT"
        except httpx.ConnectError:
            from .logger import log
            log.error("Ошибка соединения с SMS-Activate")
            return "ERROR: CONNECT"
        except httpx.HTTPStatusError as e:
            from .logger import log
            log.error(f"HTTP ошибка: {e.response.status_code}")
            return f"ERROR: HTTP {e.response.status_code}"
        except Exception as e:
            from .logger import log
            log.error(f"Исключение при запросе: {e}")
            return f"ERROR: {e}"

    # ============================================
    # БАЛАНС
    # ============================================

    def get_balance(self) -> Optional[float]:
        """
        Получить баланс аккаунта.

        Returns:
            Баланс в рублях или None при ошибке
        """
        data = self._request({"action": "getBalance"})

        if "ACCESS_BALANCE" in data:
            try:
                balance_str = data.split(":")[1]
                return float(balance_str)
            except (ValueError, IndexError):
                from .logger import log
                log.error(f"Неверный формат баланса: {data}")
                return None

        elif "BAD_KEY" in data:
            from .logger import log
            log.error("Неверный API-ключ")
            return None

        elif "ERROR_SQL" in data:
            from .logger import log
            log.error("Ошибка SQL на стороне SMS-Activate")
            return None

        else:
            from .logger import log
            log.error(f"Неизвестный ответ при запросе баланса: {data}")
            return None

    def get_balance_and_cashback(self) -> Optional[Dict]:
        """
        Получить баланс и кэшбек.

        Returns:
            {"balance": float, "cashback": float} или None
        """
        data = self._request({"action": "getBalanceAndCashBack"})

        if "ACCESS_BALANCE" in data:
            try:
                # Формат: ACCESS_BALANCE:100.00:5.00
                parts = data.split(":")
                return {
                    "balance": float(parts[1]),
                    "cashback": float(parts[2]) if len(parts) > 2 else 0.0
                }
            except (ValueError, IndexError):
                return None

        return None

    # ============================================
    # АРЕНДА НОМЕРА
    # ============================================

    def rent_number(
            self,
            country: Optional[int] = None,
            service_code: Optional[str] = None,
            max_retries: int = 3
    ) -> Optional[Dict[str, str]]:
        """
        Арендовать номер.

        Args:
            country: Код страны (если None — из конфига)
            service_code: Код сервиса (если None — из конфига)
            max_retries: Максимум попыток

        Returns:
            {"id": activation_id, "number": phone} или None
        """
        if country is None:
            country = self.country

        if service_code is None:
            service_code = self.service_code

        for attempt in range(max_retries):
            data = self._request({
                "action": "getNumber",
                "service": service_code,
                "country": country
            })

            if "ACCESS_NUMBER" in data:
                parts = data.split(":")
                if len(parts) >= 3:
                    return {
                        "id": parts[1],
                        "number": parts[2]
                    }

            elif "NO_NUMBERS" in data:
                from .logger import log
                log.warning(f"Нет номеров (попытка {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(15)
                continue

            elif "NO_BALANCE" in data:
                from .logger import log
                log.error("Недостаточно средств")
                return None

            elif "BAD_KEY" in data:
                from .logger import log
                log.error("Неверный API-ключ")
                return None

            elif "BANNED" in data:
                from .logger import log
                log.error("Аккаунт забанен")
                return None

            elif "WRONG_SERVICE" in data:
                from .logger import log
                log.error(f"Неверный сервис: {service_code}")
                return None

            else:
                from .logger import log
                log.error(f"Неизвестный ответ: {data}")
                time.sleep(5)

        return None

    def rent_number_with_forward(
            self,
            forward_number: str,
            country: Optional[int] = None,
            service_code: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """
        Арендовать номер с переадресацией.

        Args:
            forward_number: Номер для переадресации
            country: Код страны
            service_code: Код сервиса

        Returns:
            {"id": ..., "number": ...} или None
        """
        if country is None:
            country = self.country
        if service_code is None:
            service_code = self.service_code

        data = self._request({
            "action": "getNumber",
            "service": service_code,
            "country": country,
            "forward": 1,
            "phone": forward_number
        })

        if "ACCESS_NUMBER" in data:
            parts = data.split(":")
            if len(parts) >= 3:
                return {"id": parts[1], "number": parts[2]}

        return None

    # ============================================
    # ОЖИДАНИЕ КОДА
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
            data = self._request({
                "action": "getStatus",
                "id": activation_id
            })

            if "STATUS_OK" in data:
                parts = data.split(":")
                if len(parts) >= 2:
                    log.success(f"SMS получен за {attempts} попыток")
                    return parts[1]

            elif "STATUS_CANCEL" in data:
                log.warning("Аренда отменена сервисом")
                return None

            elif "STATUS_WAIT_CODE" in data:
                # Ещё ждём — это норма
                pass

            elif "STATUS_WAIT_RETRY" in data:
                log.debug("Ожидание повторной отправки SMS")

            elif "STATUS_WAIT_RESEND" in data:
                log.debug("Ожидание переотправки")

            elif "STATUS_OK" not in data and "STATUS" not in data:
                log.warning(f"Неизвестный ответ: {data}")

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
        data = self._request({
            "action": "getStatus",
            "id": activation_id
        })

        if "STATUS_OK" in data:
            parts = data.split(":")
            if len(parts) >= 2:
                return parts[1]

        return None

    # ============================================
    # УПРАВЛЕНИЕ АКТИВАЦИЕЙ
    # ============================================

    def confirm(self, activation_id: str):
        """
        Подтвердить успешную активацию (status=6).

        Args:
            activation_id: ID активации
        """
        data = self._request({
            "action": "setStatus",
            "id": activation_id,
            "status": 6
        })

        from .logger import log
        if "ACCESS_ACTIVATION" in data:
            log.debug(f"Активация {activation_id} подтверждена")
        else:
            log.warning(f"Не удалось подтвердить {activation_id}: {data}")

    def cancel(self, activation_id: str):
        """
        Отменить аренду (status=8).

        Args:
            activation_id: ID активации
        """
        data = self._request({
            "action": "setStatus",
            "id": activation_id,
            "status": 8
        })

        from .logger import log
        if "ACCESS_CANCEL" in data or "ACCESS_ACTIVATION" in data:
            log.debug(f"Активация {activation_id} отменена")
        else:
            log.warning(f"Не удалось отменить {activation_id}: {data}")

    def report_bad_number(self, activation_id: str):
        """
        Пожаловаться на номер (status=3).

        Args:
            activation_id: ID активации
        """
        self._request({
            "action": "setStatus",
            "id": activation_id,
            "status": 3
        })

    def resend_sms(self, activation_id: str) -> bool:
        """
        Запросить повторную отправку SMS.

        Args:
            activation_id: ID активации

        Returns:
            True если запрос принят
        """
        data = self._request({
            "action": "setStatus",
            "id": activation_id,
            "status": 10
        })
        return "ACCESS" in data

    # ============================================
    # СПРАВОЧНАЯ ИНФОРМАЦИЯ
    # ============================================

    def get_countries(self) -> Dict[int, str]:
        """Получить список стран."""
        return self.COUNTRIES.copy()

    def get_services(self) -> Dict[str, str]:
        """Получить список сервисов."""
        return self.SERVICES.copy()

    def get_service_name(self, code: str) -> str:
        """Получить название сервиса по коду."""
        return self.SERVICES.get(code, code)

    def get_country_name(self, code: int) -> str:
        """Получить название страны по коду."""
        return self.COUNTRIES.get(code, str(code))

    # ============================================
    # СТАТИСТИКА АККАУНТА
    # ============================================

    def get_active_activations(self) -> List[Dict]:
        """
        Получить активные активации.

        Returns:
            Список активаций
        """
        data = self._request({"action": "getActiveActivations"})

        # Формат: ACCESS_ACTIVATION:id:phone:service:date:status|id:phone:...
        if "ACCESS_ACTIVATION" in data:
            activations = []
            parts = data.split(":")[1:]
            # Простая парсинг, может отличаться
            for i in range(0, len(parts), 5):
                if i + 4 < len(parts):
                    activations.append({
                        "id": parts[i],
                        "phone": parts[i + 1],
                        "service": parts[i + 2],
                        "date": parts[i + 3],
                        "status": parts[i + 4]
                    })
            return activations

        return []