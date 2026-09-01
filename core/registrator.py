"""
Модуль регистрации аккаунтов на разных сервисах.
Использует Playwright для эмуляции браузера.

Архитектура:
    - ``BaseRegistrator`` — общий цикл регистрации
      (аренда номера -> прокси -> браузер -> форма -> SMS -> проверка).
    - Подклассы реализуют специфичную для сервиса форму входа
      (``_fill_signup_form``, ``_enter_code``) и метаданные
      (``SIGNUP_URL``, ``SMS_CODE``, ``SUCCESS_DOMAINS``, ``EMAIL_DOMAIN``).

Реестр сервисов и фабрика ``get_registrator`` находятся в ``core/services.py``.
"""

import asyncio
import json
import os
import random
import string
from typing import Optional, Dict, Callable

from playwright.async_api import async_playwright

from .logger import log
from .partner_api import PartnerAPI
from .database import Database
from .proxy_manager import ProxyManager


class BaseRegistrator:
    """
    Базовый класс регистрации аккаунтов.

    Подклассы обязаны определить:
        SERVICE_NAME     — человекочитаемое имя сервиса.
        SMS_CODE         — код сервиса Partner API (напр. ``mm``).
        SIGNUP_URL       — URL страницы регистрации.
        EMAIL_DOMAIN     — домен генерируемого email.
        SUCCESS_DOMAINS  — домены, означающие успешную регистрацию.

    И переопределить (при необходимости):
        ``_fill_signup_form`` — заполнение формы (включая телефон).
        ``_enter_code``       — ввод SMS-кода.
        ``_check_success``    — проверка успеха (по умолчанию по URL).
    """

    SERVICE_NAME = "unknown"
    SMS_CODE = None
    SIGNUP_URL = ""
    EMAIL_DOMAIN = "outlook.com"
    SUCCESS_DOMAINS = []

    def __init__(
            self,
            sms: PartnerAPI,
            db: Database,
            proxy_manager: ProxyManager,
            config,
            on_status: Optional[Callable] = None,
            on_log: Optional[Callable] = None
    ):
        """
        Инициализация регистратора.

        Args:
            sms: Клиент Partner API (SMS).
            db: База данных.
            proxy_manager: Менеджер прокси.
            config: Конфигурация.
            on_status: Колбэк для статуса (status, data).
            on_log: Колбэк для логов (message).
        """
        self.sms = sms
        self.db = db
        self.proxy_manager = proxy_manager
        self.config = config
        self.on_status = on_status
        self.on_log = on_log

    # ============================================
    # КОЛБЭКИ
    # ============================================

    def _callback_status(self, status: str, data: dict = None):
        """Вызвать колбэк статуса."""
        if self.on_status:
            try:
                self.on_status(status, data or {})
            except Exception:
                pass

    def _callback_log(self, message: str):
        """Вызвать колбэк лога."""
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass

    # ============================================
    # ГЕНЕРАЦИЯ ДАННЫХ
    # ============================================

    def generate_email(self) -> str:
        """Сгенерировать случайный email вида name.surname123@DOMAIN."""
        first_names = [
            "alex", "maria", "ivan", "anna", "pavel", "elena",
            "sergey", "olga", "dmitry", "nina", "mikhail", "tanya",
            "andrey", "irina", "nikolay", "svetlana", "victor", "yulia"
        ]

        last_names = [
            "smirnov", "ivanov", "petrov", "sidorov", "kuznetsov",
            "popov", "volkov", "sokolov", "mikhailov", "novikov",
            "morozov", "fedorov", "orlov", "belov", "kiselev"
        ]

        first = random.choice(first_names)
        last = random.choice(last_names)
        digits = ''.join(random.choices(string.digits, k=random.randint(3, 5)))

        return f"{first}.{last}{digits}@{self.EMAIL_DOMAIN}"

    def generate_password(self) -> str:
        """Сгенерировать надёжный пароль (14-18 символов)."""
        length = random.randint(14, 18)
        lower = string.ascii_lowercase
        upper = string.ascii_uppercase
        digits = string.digits
        special = "!@#$%^&*"

        password = [
            random.choice(lower),
            random.choice(upper),
            random.choice(digits),
            random.choice(special)
        ]

        all_chars = lower + upper + digits + special
        password.extend(random.choices(all_chars, k=length - 4))
        random.shuffle(password)

        return ''.join(password)

    def generate_name(self) -> tuple:
        """Сгенерировать имя и фамилию. Returns (first_name, last_name)."""
        first_names = [
            "Алексей", "Мария", "Иван", "Анна", "Павел", "Елена",
            "Сергей", "Ольга", "Дмитрий", "Нина", "Михаил", "Татьяна",
            "Андрей", "Ирина", "Николай", "Светлана", "Виктор", "Юлия"
        ]

        last_names = [
            "Смирнов", "Иванов", "Петров", "Сидоров", "Кузнецов",
            "Попов", "Волков", "Соколов", "Михайлов", "Новиков",
            "Морозов", "Фёдоров", "Орлов", "Белов", "Киселёв"
        ]

        return random.choice(first_names), random.choice(last_names)

    def generate_birthdate(self) -> tuple:
        """Сгенерировать дату рождения (18-50 лет). Returns (day, month, year)."""
        year = random.randint(1975, 2007)
        month = random.randint(1, 12)
        day = random.randint(1, 28)

        return str(day), str(month), str(year)

    def generate_username(self) -> str:
        """Сгенерировать username для сервисов, где нужен логин (Snapchat и т.п.)."""
        base = ''.join(random.choices(string.ascii_lowercase, k=random.randint(7, 10)))
        digits = ''.join(random.choices(string.digits, k=random.randint(2, 4)))
        return f"{base}{digits}"

    # ============================================
    # БРАУЗЕР
    # ============================================

    async def _launch_browser(self, playwright, proxy: Optional[dict]):
        """Запустить браузер с прокси. Returns (browser, context)."""
        launch_options = {
            "headless": self.config.get("worker.headless", True),
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        }

        if proxy:
            launch_options["proxy"] = {
                "server": f"{proxy.get('type', 'http')}://{proxy['server']}"
            }
            if proxy.get("username"):
                launch_options["proxy"]["username"] = proxy["username"]
                launch_options["proxy"]["password"] = proxy.get("password", "")

        browser = await playwright.chromium.launch(**launch_options)

        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        return browser, context

    # ============================================
    # ХУКИ (переопределяются подклассами)
    # ============================================

    async def _fill_signup_form(self, page, data: dict):
        """
        Заполнить форму регистрации вплоть до отправки телефона.

        Универсальная реализация пробует стандартные селекторы;
        сервисы с нестандартной формой переопределяют этот метод.
        """
        # email
        await self._try_fill(
            page,
            ['input[name="MemberName"]', 'input[type="email"]',
             'input[name="email"]', 'input[autocomplete="email"]'],
            data["email"], "email"
        )
        await self._click_next(page)

        # password
        await page.wait_for_timeout(2000)
        await self._try_fill(
            page,
            ['input[name="Password"]', 'input[type="password"]',
             'input[name="password"]', 'input[autocomplete="new-password"]'],
            data["password"], "password"
        )
        await self._click_next(page)

        # имя / фамилия
        await page.wait_for_timeout(2000)
        await self._try_fill(page, ['input[name="FirstName"]', 'input[name="firstName"]'],
                             data["first_name"], "first_name")
        await self._try_fill(page, ['input[name="LastName"]', 'input[name="lastName"]'],
                             data["last_name"], "last_name")
        await self._click_next(page)

        # дата рождения (опционально)
        await page.wait_for_timeout(2000)
        await self._fill_birthdate(page, data)
        await self._click_next(page)

        # телефон
        await page.wait_for_timeout(2000)
        await self._try_fill(
            page,
            ['input[name="PhoneNumber"]', 'input[type="tel"]',
             'input[name="phone"]', 'input[autocomplete="tel"]'],
            data["phone"], "phone"
        )
        await self._click_next(page)

    async def _enter_code(self, page, code: str):
        """Ввести SMS-код подтверждения."""
        code_input = await page.wait_for_selector(
            'input[name="OtpCode"], input[name="code"], input[type="text"], input[type="tel"]',
            timeout=20000
        )
        await code_input.fill(code)
        await self._click_next(page)

    async def _check_success(self, page) -> bool:
        """Проверить, успешна ли регистрация (по URL)."""
        url = page.url
        return any(domain in url for domain in self.SUCCESS_DOMAINS)

    # ============================================
    # РЕГИСТРАЦИЯ
    # ============================================

    async def register(self) -> Optional[Dict]:
        """
        Выполнить полный цикл регистрации.

        Returns:
            {"email": ..., "password": ...} при успехе, None при неудаче.
        """
        email = self.generate_email()
        password = self.generate_password()
        first_name, last_name = self.generate_name()
        day, month, year = self.generate_birthdate()
        username = self.generate_username()

        self._callback_status("starting", {"email": email})
        self._callback_log(f"Начало регистрации [{self.SERVICE_NAME}]: {email}")
        log.info(f"Начало [{self.SERVICE_NAME}]: {email}")

        # Прокси получаем один раз (меняем только номер).
        proxy = self.proxy_manager.get_next()
        proxy_str = str(proxy) if proxy else ""

        max_number_retries = int(self.config.get("worker.number_retries", 3) or 3)

        for attempt in range(max_number_retries):
            # 1. Аренда номера под конкретный сервис
            self._callback_status("renting_number", {"email": email})
            number_data = self.sms.rent_number(service=self.SMS_CODE)

            if not number_data:
                self._callback_status(
                    "error", {"email": email, "error": "Нет номеров"}
                )
                self.db.add_account(
                    email=email,
                    password=password,
                    status="error",
                    error=f"Не удалось арендовать номер ({self.SERVICE_NAME})"
                )
                self._log_attempt(proxy_str, success=False, error="Нет номеров")
                return None

            phone = number_data["number"]
            activation_id = number_data["id"]
            country = number_data.get("country_code", "")
            operator = number_data.get("operator_name", "")

            self._callback_log(
                f"Номер арендован: {phone} (попытка {attempt + 1}/{max_number_retries})"
            )
            log.info(f"Номер: {phone}")

            outcome = await self._run_attempt(
                email, password, first_name, last_name, day, month, year,
                username, phone, activation_id, proxy, proxy_str, country, operator
            )

            if outcome == "success":
                return {"email": email, "password": password}

            # Номер уже зарегистрирован на сервисе либо SMS не пришло —
            # помечаем номер как использованный и берём новый.
            if outcome in ("already_registered", "sms_timeout"):
                self.sms.report_bad_number(activation_id)
                self._callback_log(f"↻ Номер {phone} не подходит — берём новый")
                continue

            # Прочие ошибки (таймаут страницы и т.п.) — не меняем номер.
            return None

        self._callback_status(
            "failed", {"email": email, "error": "Все номера уже зарегистрированы"}
        )
        return None

    async def _run_attempt(
            self,
            email, password, first_name, last_name, day, month, year,
            username, phone, activation_id, proxy, proxy_str, country, operator
    ) -> str:
        """
        Выполнить одну попытку регистрации с конкретным номером.

        Returns:
            Строка-статус: "success" | "already_registered" | "sms_timeout" |
            "failed" | "error".
        """
        playwright = None
        browser = None

        try:
            playwright = await async_playwright().start()
            browser, context = await self._launch_browser(playwright, proxy)
            page = await context.new_page()

            # 2. Открываем страницу регистрации
            self._callback_status("opening_page", {"email": email})
            await page.goto(
                self.SIGNUP_URL,
                wait_until="networkidle",
                timeout=45000
            )

            # 3. Заполняем форму
            self._callback_status("filling_form", {"email": email})
            data = {
                "email": email,
                "password": password,
                "first_name": first_name,
                "last_name": last_name,
                "day": day,
                "month": month,
                "year": year,
                "username": username,
                "phone": phone,
            }
            await self._fill_signup_form(page, data)

            # 4. Проверка: не сообщает ли страница, что номер уже зарегистрирован.
            if await self._detect_already_registered(page):
                self._log_attempt(proxy_str, country, operator, False,
                                  "Номер уже зарегистрирован")
                return "already_registered"

            # 5. Ожидание SMS
            self._callback_status("waiting_sms", {"email": email, "phone": phone})
            self._callback_log(f"Ожидание SMS для {phone}...")

            code = self.sms.wait_code(activation_id)

            if not code:
                self._callback_status(
                    "failed", {"email": email, "error": "SMS timeout"}
                )
                self._log_attempt(proxy_str, country, operator, False, "SMS timeout")
                return "sms_timeout"

            self._callback_log("SMS-код получен")

            # 6. Ввод кода
            self._callback_status("entering_code", {"email": email})
            await self._enter_code(page, code)

            # 7. Ждём завершения
            await page.wait_for_timeout(8000)

            # 8. Проверяем результат
            current_url = page.url
            is_success = await self._check_success(page)

            if is_success:
                self._callback_status("success", {"email": email})
                self._callback_log(f"✅ Успех [{self.SERVICE_NAME}]: {email}")
                log.success(f"Регистрация успешна: {email}")

                cookies_path = await self._save_cookies(context, email)
                self.sms.confirm(activation_id)

                self.db.add_account(
                    email=email,
                    password=password,
                    phone=phone,
                    cookies_path=cookies_path,
                    proxy=proxy_str,
                    status="success"
                )
                self._log_attempt(proxy_str, country, operator, True, "")
                return "success"

            # Неудача (неожиданный URL) — номер не меняем.
            self._callback_status(
                "failed",
                {"email": email, "error": f"URL: {current_url}"}
            )
            self._callback_log(f"❌ Неудача [{self.SERVICE_NAME}]: {email}")
            log.warning(
                f"Регистрация не удалась: {email} | URL: {current_url}"
            )

            self.sms.cancel(activation_id)
            self.db.add_account(
                email=email,
                password=password,
                phone=phone,
                status="failed",
                error=f"Unexpected URL: {current_url}"
            )
            self._log_attempt(proxy_str, country, operator, False,
                              f"Unexpected URL: {current_url}")
            return "failed"

        except asyncio.TimeoutError:
            self._callback_status("error", {"email": email, "error": "Timeout"})
            self._callback_log(f"❌ Таймаут: {email}")
            log.error(f"Таймаут при регистрации {email}")
            self.sms.cancel(activation_id)
            self.db.add_account(
                email=email,
                password=password,
                phone=phone,
                status="error",
                error="Timeout"
            )
            self._log_attempt(proxy_str, country, operator, False, "Timeout")
            return "error"

        except Exception as e:
            self._callback_status("error", {"email": email, "error": str(e)})
            self._callback_log(f"❌ Ошибка: {e}")
            log.error(f"Исключение при регистрации {email}: {e}")
            self.sms.cancel(activation_id)
            self.db.add_account(
                email=email,
                password=password,
                phone=phone,
                status="error",
                error=str(e)
            )
            self._log_attempt(proxy_str, country, operator, False, str(e))
            return "error"

        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()

    # ============================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================

    # Фразы, по которым определяем, что номер уже зарегистрирован на сервисе.
    ALREADY_REGISTERED_PHRASES = (
        "already registered",
        "already in use",
        "already been used",
        "this phone number is already",
        "уже зарегистрирован",
        "уже используется",
        "номер уже используется",
        "already associated",
        "this number is already",
    )

    async def _detect_already_registered(self, page) -> bool:
        """
        Определить по тексту страницы, что номер уже зарегистрирован.

        Returns:
            True, если сервис сообщает об уже использованном номере.
        """
        try:
            text = await page.inner_text("body")
        except Exception:
            return False

        low = text.lower()
        return any(phrase in low for phrase in self.ALREADY_REGISTERED_PHRASES)

    def _log_attempt(self, proxy, country="", operator="", success=False, error=""):
        """Записать попытку в БД для обучения ML-модели."""
        try:
            self.db.add_attempt(
                service=self.SERVICE_NAME,
                country=country or "",
                operator=operator or "",
                proxy=proxy or "",
                success=success,
                error=error or "",
            )
        except Exception as e:
            log.warning(f"Не удалось записать попытку для ML: {e}")

    async def _click_next(self, page):
        """Нажать кнопку 'Далее'."""
        try:
            next_btn = await page.wait_for_selector(
                'input[type="submit"], button[type="submit"], #idSIButton9',
                timeout=10000
            )
            await next_btn.click()
            await page.wait_for_timeout(2000)
        except Exception as e:
            log.warning(f"Не удалось нажать Далее: {e}")

    async def _try_fill(self, page, selectors, value: str, label: str) -> bool:
        """Попытаться заполнить поле по списку селекторов. Returns True при успехе."""
        for sel in selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=5000)
                await el.fill(value)
                return True
            except Exception:
                continue
        log.warning(f"Поле '{label}' не найдено (селекторы: {selectors})")
        return False

    async def _fill_birthdate(self, page, data: dict):
        """Заполнить дату рождения (опционально)."""
        try:
            day_select = await page.wait_for_selector(
                'select[name="BirthDay"], select[name="birthDay"]', timeout=5000
            )
            await day_select.select_option(data["day"])

            month_select = await page.wait_for_selector(
                'select[name="BirthMonth"], select[name="birthMonth"]', timeout=5000
            )
            await month_select.select_option(data["month"])

            year_select = await page.wait_for_selector(
                'select[name="BirthYear"], select[name="birthYear"]', timeout=5000
            )
            await year_select.select_option(data["year"])
        except Exception as e:
            log.warning(f"Дата рождения не заполнена: {e}")

    async def _save_cookies(self, context, email: str) -> str:
        """Сохранить cookies в файл. Returns путь к файлу."""
        os.makedirs("cookies", exist_ok=True)

        safe_email = email.replace("@", "_at_").replace(".", "_dot_")
        cookies_path = f"cookies/{safe_email}.json"

        cookies = await context.cookies()

        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        return cookies_path


# ================================================
# КОНКРЕТНЫЕ РЕГИСТРАТОРЫ
# ================================================


class MicrosoftRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Microsoft (Outlook)."""

    SERVICE_NAME = "Microsoft"
    SMS_CODE = "mm"
    SIGNUP_URL = "https://signup.live.com/signup"
    EMAIL_DOMAIN = "outlook.com"
    SUCCESS_DOMAINS = [
        "account.microsoft.com",
        "outlook.live.com",
        "office.com",
        "login.live.com"
    ]

    async def _fill_signup_form(self, page, data: dict):
        """Специфичная форма Microsoft (email -> password -> name -> birthdate -> phone)."""
        await self._try_fill(
            page,
            ['input[name="MemberName"]', 'input[type="email"]'],
            data["email"], "email"
        )
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(
            page,
            ['input[name="Password"]', 'input[type="password"]'],
            data["password"], "password"
        )
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[name="FirstName"]'], data["first_name"], "first_name")
        await self._try_fill(page, ['input[name="LastName"]'], data["last_name"], "last_name")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._fill_birthdate(page, data)
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(
            page,
            ['input[name="PhoneNumber"]', 'input[type="tel"]'],
            data["phone"], "phone"
        )
        await self._click_next(page)

    async def _enter_code(self, page, code: str):
        code_input = await page.wait_for_selector(
            'input[name="OtpCode"], input[type="text"]', timeout=20000
        )
        await code_input.fill(code)
        await self._click_next(page)


class GoogleRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Google (Gmail)."""

    SERVICE_NAME = "Google"
    SMS_CODE = "go"
    SIGNUP_URL = "https://accounts.google.com/signup"
    EMAIL_DOMAIN = "gmail.com"
    SUCCESS_DOMAINS = [
        "myaccount.google.com",
        "mail.google.com",
        "accounts.google.com"
    ]

    async def _fill_signup_form(self, page, data: dict):
        await self._try_fill(page, ['input[name="firstName"]', 'input[type="text"]'],
                             data["first_name"], "first_name")
        await self._try_fill(page, ['input[name="lastName"]'],
                             data["last_name"], "last_name")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._fill_birthdate(page, data)
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[name="Username"]', 'input[type="email"]'],
                             data["email"], "email")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[name="Passwd"]', 'input[type="password"]'],
                             data["password"], "password")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[type="tel"]', 'input[name="phoneNumber"]'],
                             data["phone"], "phone")
        await self._click_next(page)


class AppleRegistrator(BaseRegistrator):
    """Регистрация Apple ID (appleid.apple.com)."""

    SERVICE_NAME = "Apple"
    SMS_CODE = "wx"
    SIGNUP_URL = "https://appleid.apple.com/account"
    EMAIL_DOMAIN = "icloud.com"
    SUCCESS_DOMAINS = [
        "appleid.apple.com",
        "apple.com",
        "icloud.com"
    ]

    async def _fill_signup_form(self, page, data: dict):
        await self._try_fill(page, ['input[name="firstName"]', 'input[type="text"]'],
                             data["first_name"], "first_name")
        await self._try_fill(page, ['input[name="lastName"]'],
                             data["last_name"], "last_name")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._fill_birthdate(page, data)
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[name="emailAddress"]', 'input[type="email"]'],
                             data["email"], "email")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[name="password"]', 'input[type="password"]'],
                             data["password"], "password")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[name="phoneNumber"]', 'input[type="tel"]'],
                             data["phone"], "phone")
        await self._click_next(page)


class SnapchatRegistrator(BaseRegistrator):
    """Регистрация Snapchat (accounts.snapchat.com)."""

    SERVICE_NAME = "Snapchat"
    SMS_CODE = "fu"
    SIGNUP_URL = "https://accounts.snapchat.com/accounts/signup"
    EMAIL_DOMAIN = "gmail.com"
    SUCCESS_DOMAINS = [
        "accounts.snapchat.com",
        "snapchat.com"
    ]

    async def _fill_signup_form(self, page, data: dict):
        await self._try_fill(page, ['input[name="firstName"]', 'input[type="text"]'],
                             data["first_name"], "first_name")
        await self._try_fill(page, ['input[name="lastName"]'],
                             data["last_name"], "last_name")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._fill_birthdate(page, data)
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[name="username"]'],
                             data["username"], "username")
        await self._try_fill(page, ['input[name="email"]', 'input[type="email"]'],
                             data["email"], "email")
        await self._try_fill(page, ['input[name="password"]', 'input[type="password"]'],
                             data["password"], "password")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[type="tel"]', 'input[name="phoneNumber"]'],
                             data["phone"], "phone")
        await self._click_next(page)


class InstagramRegistrator(BaseRegistrator):
    """Регистрация Instagram (instagram.com)."""

    SERVICE_NAME = "Instagram"
    SMS_CODE = "ig"
    SIGNUP_URL = "https://www.instagram.com/accounts/emailsignup/"
    EMAIL_DOMAIN = "gmail.com"
    SUCCESS_DOMAINS = [
        "instagram.com"
    ]

    async def _fill_signup_form(self, page, data: dict):
        await self._try_fill(page, ['input[name="emailOrPhone"]', 'input[type="text"]'],
                             data["email"], "email")
        await self._try_fill(page, ['input[name="fullName"]'],
                             f"{data['first_name']} {data['last_name']}", "full_name")
        await self._try_fill(page, ['input[name="username"]'],
                             data["username"], "username")
        await self._try_fill(page, ['input[name="password"]', 'input[type="password"]'],
                             data["password"], "password")
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._fill_birthdate(page, data)
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[type="tel"]', 'input[name="phoneNumber"]'],
                             data["phone"], "phone")
        await self._click_next(page)


class FacebookRegistrator(BaseRegistrator):
    """Регистрация Facebook (facebook.com/reg)."""

    SERVICE_NAME = "Facebook"
    SMS_CODE = "fb"
    SIGNUP_URL = "https://www.facebook.com/reg"
    EMAIL_DOMAIN = "gmail.com"
    SUCCESS_DOMAINS = [
        "facebook.com"
    ]

    async def _fill_signup_form(self, page, data: dict):
        await self._try_fill(page, ['input[name="firstname"]', 'input[type="text"]'],
                             data["first_name"], "first_name")
        await self._try_fill(page, ['input[name="lastname"]'],
                             data["last_name"], "last_name")
        await self._try_fill(page, ['input[name="reg_email__"]', 'input[type="email"]'],
                             data["email"], "email")
        await self._try_fill(page, ['input[name="reg_passwd__"]', 'input[type="password"]'],
                             data["password"], "password")
        await self._fill_birthdate(page, data)
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[type="tel"]', 'input[name="phoneNumber"]'],
                             data["phone"], "phone")
        await self._click_next(page)


class DiscordRegistrator(BaseRegistrator):
    """Регистрация Discord (discord.com/register)."""

    SERVICE_NAME = "Discord"
    SMS_CODE = "ds"
    SIGNUP_URL = "https://discord.com/register"
    EMAIL_DOMAIN = "gmail.com"
    SUCCESS_DOMAINS = [
        "discord.com"
    ]

    async def _fill_signup_form(self, page, data: dict):
        await self._try_fill(page, ['input[name="email"]', 'input[type="email"]'],
                             data["email"], "email")
        await self._try_fill(page, ['input[name="username"]'],
                             data["username"], "username")
        await self._try_fill(page, ['input[name="password"]', 'input[type="password"]'],
                             data["password"], "password")
        await self._fill_birthdate(page, data)
        await self._click_next(page)

        await page.wait_for_timeout(3000)
        await self._try_fill(page, ['input[type="tel"]', 'input[name="phoneNumber"]'],
                             data["phone"], "phone")
        await self._click_next(page)
