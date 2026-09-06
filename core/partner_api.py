"""
Модуль работы с Partner REST API провайдера SMS-номеров.

Полный список эндпоинтов (base_url = https://46.21.159.86/partner):

    GET  /get_balance            (header ``x-api-key``)  -> {"usd": float, "limit": float}
    GET  /get_services           (header ``x-api-key``)  -> [Service, ...]
    GET  /get_rate/{code}        (header ``x-api-key``)  -> [Rate, ...]
    GET  /get_messages/{api_key} (query ``service``)     -> [Message, ...]
    GET  /get_actual_senders/    (query ``api_key``)     -> [str, ...]
    POST /get_number             (header ``x-api-key``)  -> аренда номера
    POST /get_status             (header ``x-api-key``)  -> статус/код активации
    POST /set_status             (header ``x-api-key``)  -> управление активацией
    POST /activate_number        (header ``x-api-key``)  -> активация существующего номера

Ключ передаётся:
    * через заголовок ``x-api-key`` для POST-эндпоинтов и /get_balance,
      /get_services, /get_rate;
    * через path/query-параметр ``api_key`` для /get_messages, /get_actual_senders.

Ответы приходят в формате JSON (в отличие от старого SMS-Activate
совместимого API с текстовыми ответами ACCESS_*).

Класс реализует как низкоуровневые методы (по одному на эндпоинт), так и
высокоуровневые методы, совместимые по сигнатуре с ``SMSActivate``
(``rent_number``, ``wait_code``, ``confirm``, ``cancel``, ...), чтобы его
можно было использовать как drop-in замену в потоке регистрации.
"""

import httpx
import random
import time
from typing import Optional, Dict, List, Any


class PartnerAPI:
    """Клиент Partner REST API (https://46.21.159.86/partner)."""

    # Базовый URL Partner REST API.
    # Настраивается через параметр ``base_url`` конструктора или
    # ключ конфига ``sms.partner_url``.
    BASE_URL = "https://46.21.159.86/partner"

    # Коды статуса для /set_status.
    STATUS_CANCEL = -1           # отменить активацию
    STATUS_REQUEST_ANOTHER = 3   # запросить ещё один код
    STATUS_COMPLETE = 6          # завершить активацию (код подтверждён)
    STATUS_NUMBER_USED = 8       # номер использован — отменить активацию

    # Сопоставление понятных имён сервисов с кодами Partner API.
    # Актуальные коды можно получить через get_services().
    # Значение, не найденное в словаре, передаётся как есть (считается,
    # что это уже корректный код сервиса).
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
        "Snapchat": "fu",
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
        """
        Инициализация клиента.

        Args:
            api_key: API-ключ SMS-провайдера (Partner REST API).
            base_url: Базовый URL API (по умолчанию BASE_URL).
            service: Название сервиса по умолчанию (Microsoft, Google и т.д.).
            country: Код страны по умолчанию ("all" = любая).
            max_price: Максимальная цена (не используется в Partner API).
            timeout: Таймаут HTTP-запросов (сек).
            proxy_manager: ProxyManager для ротации прокси.
            verify_ssl: Проверять SSL-сертификат (False — для хостов
                с самоподписанным сертификатом, напр. по IP-адресу).
        """
        self.api_key = api_key
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.service = service
        self.country = country
        self.max_price = max_price
        self.timeout = timeout
        self.proxy_manager = proxy_manager
        self.verify_ssl = verify_ssl

        # Кэш списка сервисов (используется для выбора случайной страны,
        # когда country == "all").
        self._services_cache = None
        self._services_cached_at = 0.0

    # ============================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # ============================================

    def _get(
            self,
            path: str,
            params: Optional[dict] = None,
            headers: Optional[dict] = None,
    ) -> Any:
        """
        Выполнить GET-запрос к Partner REST API и разобрать JSON.

        Args:
            path: Относительный путь (напр. ``get_balance``).
            params: Query-параметры.
            headers: Дополнительные заголовки.

        Returns:
            Разобранный JSON-ответ или None при ошибке.
        """
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
                response = client.get(
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=self.timeout,
                )
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

    def _post(
            self,
            path: str,
            json: Optional[dict] = None,
            headers: Optional[dict] = None,
    ) -> Any:
        """
        Выполнить POST-запрос к Partner REST API и разобрать JSON.

        Args:
            path: Относительный путь (напр. ``get_number``).
            json: Тело запроса (JSON-объект).
            headers: Дополнительные заголовки.

        Returns:
            Разобранный JSON-ответ или None при ошибке.
        """
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
                response = client.post(
                    url,
                    json=json,
                    headers=request_headers,
                    timeout=self.timeout,
                )
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
        """Заголовки авторизации для эндпоинтов с ``x-api-key``."""
        return {"x-api-key": self.api_key}

    # ============================================
    # БАЛАНС
    # ============================================

    def get_balance(self) -> Optional[Dict[str, float]]:
        """
        Получить баланс аккаунта.

        Returns:
            Словарь вида ``{"usd": float, "limit": float}`` или None при ошибке.

            * ``usd`` — баланс в USD (может быть отрицательным);
            * ``limit`` — кредитный лимит в USD.
        """
        from .logger import log

        data = self._get("get_balance", headers=self._auth_headers())
        if not isinstance(data, dict):
            return None
        try:
            return {
                "usd": float(data.get("usd", 0.0)),
                "limit": float(data.get("limit", 0.0)),
            }
        except (TypeError, ValueError):
            log.error(f"Не удалось разобрать баланс: {data}")
            return None

    # ============================================
    # СЕРВИСЫ
    # ============================================

    def get_services(self) -> Optional[List[Dict]]:
        """
        Получить список доступных сервисов.

        Returns:
            Список сервисов вида:
                {"code", "name", "price", "countries": [CountryData, ...]}
            или None при ошибке.
        """
        data = self._get("get_services", headers=self._auth_headers())
        if isinstance(data, list):
            return data
        return None

    # ============================================
    # СТАВКИ (ЦЕНЫ)
    # ============================================

    def get_rate(self, code: str) -> Optional[List[Dict]]:
        """
        Получить ставки по коду сервиса.

        Args:
            code: Код сервиса (напр. ``wa``, ``ig``).

        Returns:
            Список стран с ценами вида:
                {"id", "code", "country_name", "rate",
                 "operators": [{"name", "rate"}, ...]}
            или None при ошибке.
        """
        data = self._get(f"get_rate/{code}", headers=self._auth_headers())
        if isinstance(data, list):
            return data
        return None

    # ============================================
    # СООБЩЕНИЯ
    # ============================================

    def get_messages(
            self,
            api_key: Optional[str] = None,
            service: Optional[str] = None,
    ) -> Optional[List[Dict]]:
        """
        Получить список входящих SMS.

        Args:
            api_key: Ключ (по умолчанию ``self.api_key``).
            service: Необязательный фильтр по коду сервиса.

        Returns:
            Список сообщений вида:
                {"number", "service", "country", "message", "created_at"}
            или None при ошибке.
        """
        key = api_key or self.api_key
        params = None
        if service:
            params = {"service": service}
        data = self._get(f"get_messages/{key}", params=params)
        if isinstance(data, list):
            return data
        return None

    # ============================================
    # АКТИВНЫЕ ОТПРАВИТЕЛИ
    # ============================================

    def get_actual_senders(self, api_key: Optional[str] = None) -> Optional[List[str]]:
        """
        Получить список активных отправителей (номеров).

        Args:
            api_key: Ключ (по умолчанию ``self.api_key``).

        Returns:
            Список строк-отправителей или None при ошибке.
        """
        key = api_key or self.api_key
        data = self._get("get_actual_senders/", params={"api_key": key})
        if isinstance(data, list):
            return data
        return None

    # ============================================
    # ВСПОМОГАТЕЛЬНЫЕ (СОВМЕСТИМОСТЬ С SMSActivate)
    # ============================================

    def _resolve_service(self, service: str) -> str:
        """
        Преобразовать понятное имя сервиса в короткий код Partner API.

        Неизвестное значение передаётся как есть (считается, что это уже
        корректный код сервиса).
        """
        return self.SERVICES.get(service, service)

    def _get_services_cached(self) -> Optional[List[Dict]]:
        """Вернуть список сервисов с кэшированием (5 минут)."""
        now = time.time()
        if self._services_cache is not None and now - self._services_cached_at < 300:
            return self._services_cache

        data = self.get_services()
        self._services_cache = data
        self._services_cached_at = now
        return data

    def _pick_country(self, service_code: str) -> Optional[str]:
        """
        Выбрать случайную страну для сервиса (для country == "all").

        Returns:
            Код страны (напр. ``NG``) или None, если список недоступен.
        """
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

    # ============================================
    # АРЕНДА НОМЕРА (POST /get_number)
    # ============================================

    def get_number(
            self,
            service: str,
            country=None,
            operator: Optional[str] = None,
            extra_fields: Optional[dict] = None,
    ) -> Optional[Dict]:
        """
        Арендовать один номер (низкоуровневый вызов POST /get_number).

        Args:
            service: Код сервиса (напр. ``mm`` для Microsoft).
            country: Код страны (``NG``) или ID страны (``19``).
            operator: Необязательное имя оператора.
            extra_fields: Необязательные доп. поля запроса.

        Returns:
            Словарь с ключами ``id``, ``number``, ``country_code``,
            ``operator_name``, ``lifetime`` и т.д. либо None при ошибке.
        """
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
        """
        Массовая аренда номеров (до 100 документов за запрос).

        Args:
            requests: Список запросов вида
                ``{"service", "country", "operator"?, "extra_fields"?}``.

        Returns:
            Список ответов (успех или ошибка по каждому) или None.
        """
        from .logger import log

        if not requests:
            return []
        if len(requests) > 100:
            log.warning("get_numbers: максимум 100 документов, обрезаю")
            requests = requests[:100]

        data = self._post("get_number", json=requests, headers=self._auth_headers())
        return data if isinstance(data, list) else None

    def rent_number(
            self,
            service: Optional[str] = None,
            country: Optional[str] = None,
            max_price: Optional[float] = None,
            operator: Optional[str] = None,
            max_retries: int = 3,
    ) -> Optional[Dict[str, str]]:
        """
        Арендовать номер (совместимо с SMSActivate.rent_number).

        Args:
            service: Название сервиса (Microsoft, Google и т.д.) или код.
            country: Код/ID страны, либо "all" (любая доступная страна).
            max_price: Игнорируется (Partner API не принимает max_price).
            operator: Имя оператора (пусто = любой).
            max_retries: Число попыток.

        Returns:
            {"id": activation_id, "number": phone} или None.
        """
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

            data = self.get_number(
                service_code,
                country=use_country,
                operator=operator or None,
            )

            if data and data.get("id"):
                result = {"id": data["id"], "number": data["number"]}
                if data.get("country_code"):
                    result["country_code"] = data["country_code"]
                if data.get("operator_name"):
                    result["operator_name"] = data["operator_name"]
                if data.get("lifetime") is not None:
                    result["lifetime"] = data["lifetime"]
                return result

            log.warning(f"Не удалось арендовать номер "
                        f"(попытка {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(2)

        return None

    # ============================================
    # СТАТУС АКТИВАЦИИ (POST /get_status)
    # ============================================

    def get_status(self, activation_id: str) -> Optional[Dict]:
        """
        Получить статус и код активации (POST /get_status).

        Args:
            activation_id: ID активации.

        Returns:
            Словарь ``{"status": "ok"|"wait"|"cancel",
            "status_code": 1|0|-1, "code": str|None}`` или None.
        """
        from .logger import log

        data = self._post(
            "get_status",
            json={"id": activation_id},
            headers=self._auth_headers(),
        )

        if not isinstance(data, dict):
            return None
        if data.get("success") is False:
            log.warning(f"get_status: {data.get('error')}")
            return None
        return data

    def get_statuses(self, ids: List[str]) -> Optional[List[Dict]]:
        """
        Массовый опрос статусов (до 100 документов).

        Args:
            ids: Список ID активаций.

        Returns:
            Список ответов или None.
        """
        from .logger import log

        if not ids:
            return []
        if len(ids) > 100:
            log.warning("get_statuses: максимум 100 документов, обрезаю")
            ids = ids[:100]

        payload = [{"id": i} for i in ids]
        data = self._post("get_status", json=payload, headers=self._auth_headers())
        return data if isinstance(data, list) else None

    def wait_code(
            self,
            activation_id: str,
            timeout: int = 300,
            poll_interval: int = 5,
    ) -> Optional[str]:
        """
        Дождаться SMS-кода (совместимо с SMSActivate.wait_code).

        Args:
            activation_id: ID активации.
            timeout: Максимальное время ожидания (сек).
            poll_interval: Интервал опроса (сек).

        Returns:
            Код подтверждения или None (таймаут/отмена).
        """
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
        """
        Проверить код один раз без ожидания.

        Returns:
            Код или None.
        """
        data = self.get_status(activation_id)
        if data and data.get("status") == "ok" and data.get("code"):
            return str(data["code"])
        return None

    # ============================================
    # УПРАВЛЕНИЕ АКТИВАЦИЕЙ (POST /set_status)
    # ============================================

    def set_status(self, activation_id: str, status_code: int) -> bool:
        """
        Изменить статус активации (POST /set_status).

        Args:
            activation_id: ID активации.
            status_code:
                -1 — отменить активацию;
                3 — запросить ещё один код;
                6 — завершить активацию;
                8 — номер использован, отменить активацию.

        Returns:
            True при успехе.
        """
        from .logger import log

        data = self._post(
            "set_status",
            json={"id": activation_id, "status_code": status_code},
            headers=self._auth_headers(),
        )

        if not isinstance(data, dict):
            return False
        if data.get("success") is False:
            log.warning(f"set_status: {data.get('error')}")
            return False
        return True

    def confirm(self, activation_id: str):
        """Подтвердить успешную активацию (завершить аренду)."""
        from .logger import log

        if self.set_status(activation_id, self.STATUS_COMPLETE):
            log.debug(f"Активация {activation_id} подтверждена")
        else:
            log.warning(f"Не удалось подтвердить активацию {activation_id}")

    def cancel(self, activation_id: str):
        """Отменить аренду (вернуть деньги)."""
        from .logger import log

        if self.set_status(activation_id, self.STATUS_CANCEL):
            log.debug(f"Активация {activation_id} отменена")
        else:
            log.warning(f"Не удалось отменить активацию {activation_id}")

    def report_bad_number(self, activation_id: str):
        """Пожаловаться на номер (номер использован — отменить)."""
        from .logger import log

        if self.set_status(activation_id, self.STATUS_NUMBER_USED):
            log.debug(f"Номер {activation_id} помечен как использованный")
        else:
            log.warning(f"Не удалось пометить номер {activation_id}")

    # ============================================
    # АКТИВАЦИЯ СУЩЕСТВУЮЩЕГО НОМЕРА (POST /activate_number)
    # ============================================

    def activate_number(
            self,
            service: str,
            number: str,
            country: Optional[str] = None,
            operator: Optional[str] = None,
            any_key: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Активировать уже имеющийся номер (POST /activate_number).

        Args:
            service: Код сервиса (напр. ``wa``).
            number: Номер телефона без ``+``.
            country: Необязательный код страны.
            operator: Необязательное имя оператора.
            any_key: Необязательный ключ активации «любого» номера.

        Returns:
            Словарь ``{"id", "number", "lifetime", ...}`` или None.
        """
        from .logger import log

        payload = {"service": service, "number": number}
        if country is not None:
            payload["country"] = country
        if operator is not None:
            payload["operator"] = operator
        if any_key is not None:
            payload["any_key"] = any_key

        data = self._post(
            "activate_number",
            json=payload,
            headers=self._auth_headers(),
        )

        if not isinstance(data, dict):
            return None
        if data.get("error") and not data.get("id"):
            log.error(f"activate_number: {data.get('error')}")
            return None
        return data

    # ============================================
    # СТАТИСТИКА (не поддерживается Partner API)
    # ============================================

    def get_active_activations(self) -> List[Dict]:
        """
        Partner API не предоставляет список активных активаций.

        Returns:
            Пустой список.
        """
        return []

