"""
Модуль регистрации аккаунтов Microsoft (Outlook).
Использует Playwright для эмуляции браузера.
"""

import asyncio
import json
import os
import random
import string
from typing import Optional, Dict, Callable, Tuple

from playwright.async_api import async_playwright, Page, BrowserContext

from .logger import log
from .partner_api import PartnerAPI
from .database import Database
from .proxy_manager import ProxyManager


class BaseRegistrator:
    """Базовый класс для всех регистраторов."""

    SERVICE_NAME: str = "Unknown"
    SMS_CODE: str = ""
    SIGNUP_URL: str = ""

    def __init__(
            self,
            sms,
            db,
            proxy_manager,
            config,
            on_status: Optional[Callable] = None,
            on_log: Optional[Callable] = None
    ):
        self.sms = sms
        self.db = db
        self.proxy_manager = proxy_manager
        self.config = config
        self.on_status = on_status
        self.on_log = on_log

    async def _sms_call(self, method_name: str, *args, **kwargs):
        """
        Вызвать метод SMS-API, работая и с синхронным, и с асинхронным клиентом.

        Если метод возвращает coroutine — awaiting, иначе — обычный вызов.
        """
        method = getattr(self.sms, method_name)
        result = method(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _callback_status(self, status: str, data: dict = None):
        if self.on_status:
            try:
                self.on_status(status, data or {})
            except Exception:
                pass

    def _callback_log(self, message: str):
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass

    def generate_email(self) -> str:
        raise NotImplementedError

    def generate_password(self) -> str:
        raise NotImplementedError

    def generate_name(self) -> tuple:
        raise NotImplementedError

    def generate_birthdate(self) -> tuple:
        raise NotImplementedError

    def generate_username(self) -> str:
        raise NotImplementedError

    async def register(self) -> Optional[Dict]:
        raise NotImplementedError

    async def _run_attempt(
            self,
            email, password, first_name, last_name, day, month, year,
            username, phone, activation_id, proxy, proxy_str, country, operator
    ) -> str:
        raise NotImplementedError


class MicrosoftRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Microsoft (Outlook)."""

    SERVICE_NAME = "Microsoft"
    SMS_CODE = "mm"
    EMAIL_DOMAIN = "outlook.com"
    SIGNUP_URL = "https://signup.live.com/signup"

    # Домены, которые считаются успешной регистрацией
    SUCCESS_DOMAINS = [
        "account.microsoft.com",
        "outlook.live.com",
        "office.com",
        "login.live.com"
    ]

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
        """
        Сгенерировать надёжный пароль.

        Returns:
            Пароль 14-18 символов
        """
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
        """
        Сгенерировать имя и фамилию.

        Returns:
            (first_name, last_name)
        """
        first_names = [
            "Алексей", "Мария", "Иван", "Анна", "Павел", "Елена",
            "Сергей", "Ольга", "Дмитрий", "Нина", "Михаил", "Таня",
            "Андрей", "Ирина", "Николай", "Светлана", "Виктор", "Юля"
        ]

        last_names = [
            "Смирнов", "Иванов", "Петров", "Сидоров", "Кузнецов",
            "Попов", "Волков", "Соколов", "Михайлов", "Новиков",
            "Морозов", "Федоров", "Орлов", "Белов", "Киселев"
        ]

        return random.choice(first_names), random.choice(last_names)

    def generate_birthdate(self) -> tuple:
        """
        Сгенерировать дату рождения (18-50 лет).

        Returns:
            (day, month, year) — строки
        """
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
    # ПРОВЕРКА CAPTCHA
    # ============================================

    async def _check_captcha(self, page: Page) -> bool:
        """
        Проверить страницу на наличие CAPTCHA.

        Args:
            page: Страница Playwright

        Returns:
            True если CAPTCHA обнаружена
        """
        try:
            # Проверка на наличие reCAPTCHA iframe
            try:
                captcha_iframe = await page.frame_locator("iframe[title*='recaptcha' i]").first
                if captcha_iframe:
                    return True
            except Exception:
                pass

            # Проверка по содержимому страницы
            page_content = await page.content()
            page_content_lower = page_content.lower()
            
            captcha_indicators = [
                "captcha",
                "verify you are human",
                "i'm not a robot",
                "recaptcha",
                "hcaptcha",
                "prove you're human",
                "security check",
            ]
            
            if any(indicator in page_content_lower for indicator in captcha_indicators):
                return True

            return False
        except Exception:
            return False

    # ============================================
    # РАБОТА С БРАУЗЕРОМ
    # ============================================

    async def _launch_browser(self, playwright, proxy: Optional[dict]):
        """
        Запустить браузер с прокси.

        Args:
            playwright: Экземпляр playwright
            proxy: Параметры прокси

        Returns:
            (browser, context)
        """
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
    # ГЛАВНЫЙ МЕТОД РЕГИСТРАЦИИ
    # ============================================

    async def register(self) -> Optional[Dict]:
        """
        Выполнить полный цикл регистрации.

        Returns:
            {"email": ..., "password": ...} при успехе, None при неудаче.
        """
        # Генерация данных
        email = self.generate_email()
        
        # Проверка на дубликат email
        max_attempts = 5
        for _ in range(max_attempts):
            if not self.db.email_exists(email):
                break
            email = self.generate_email()
        else:
            self._callback_status("error", {"email": email, "error": "Не удалось сгенерировать уникальный email"})
            self._callback_log(f"❌ Не удалось сгенерировать уникальный email после {max_attempts} попыток")
            log.warning(f"Не удалось сгенерировать уникальный email")
            return None

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
            number_data = await self._sms_call("rent_number", service=self.SMS_CODE)

            if not number_data:
                self._callback_status("error", {"email": email, "error": "Нет номеров"})
                self.db.add_account(
                    email=email,
                    password=password,
                    status="error",
                    error="Не удалось арендовать номер"
                )
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
                await self._sms_call("report_bad_number", activation_id)
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

            # 4. Заполняем email
            self._callback_status("filling_email", {"email": email})
            email_input = await page.wait_for_selector(
                'input[name="MemberName"], input[type="email"]',
                timeout=20000
            )
            await email_input.fill(email)
            await self._click_next(page)

            # 5. Заполняем пароль
            await page.wait_for_timeout(3000)
            self._callback_status("filling_password", {"email": email})
            password_input = await page.wait_for_selector(
                'input[name="Password"], input[type="password"]',
                timeout=20000
            )
            await password_input.fill(password)
            await self._click_next(page)

            # 6. Заполняем имя и фамилию
            await page.wait_for_timeout(3000)
            self._callback_status("filling_name", {"email": email})

            fn_input = await page.wait_for_selector(
                'input[name="FirstName"]',
                timeout=20000
            )
            await fn_input.fill(first_name)

            ln_input = await page.wait_for_selector(
                'input[name="LastName"]',
                timeout=10000
            )
            await ln_input.fill(last_name)
            await self._click_next(page)

            # 7. Дата рождения
            await page.wait_for_timeout(3000)
            self._callback_status("filling_birthdate", {"email": email})

            try:
                day_select = await page.wait_for_selector(
                    'select[name="BirthDay"]',
                    timeout=10000
                )
                await day_select.select_option(day)

                month_select = await page.wait_for_selector(
                    'select[name="BirthMonth"]',
                    timeout=5000
                )
                await month_select.select_option(month)

                year_select = await page.wait_for_selector(
                    'select[name="BirthYear"]',
                    timeout=5000
                )
                await year_select.select_option(year)
            except Exception as e:
                self._callback_log(f"⚠️ Не удалось заполнить дату рождения: {e}")
                log.warning(f"Дата рождения не заполнена: {e}")

            await self._click_next(page)

            # 8. Номер телефона
            await page.wait_for_timeout(3000)
            self._callback_status("filling_phone", {"email": email, "phone": phone})

            phone_input = await page.wait_for_selector(
                'input[name="PhoneNumber"], input[type="tel"]',
                timeout=30000
            )
            await phone_input.fill(phone)
            await self._click_next(page)

            # 9. Ожидание SMS
            self._callback_status("waiting_sms", {"email": email, "phone": phone})
            self._callback_log(f"Ожидание SMS для {phone}...")

            code = await self._sms_call("wait_code", activation_id)

            if not code:
                self._callback_status(
                    "failed", {"email": email, "error": "SMS timeout"}
                )
                self._log_attempt(proxy_str, country, operator, False, "SMS timeout")
                return "sms_timeout"

            self._callback_log("SMS-код получен")

            # 6. Ввод кода
            self._callback_status("entering_code", {"email": email})

            code_input = await page.wait_for_selector(
                'input[name="OtpCode"], input[type="text"]',
                timeout=20000
            )
            await code_input.fill(code)
            await self._click_next(page)

            # 11. Ждём завершения
            await page.wait_for_timeout(8000)

            # 12. Проверяем результат
            current_url = page.url
            is_success = await self._check_success(page)

            if is_success:
                self._callback_status("success", {"email": email})
                self._callback_log(f"✅ Успех [{self.SERVICE_NAME}]: {email}")
                log.success(f"Регистрация успешна: {email}")

                cookies_path = await self._save_cookies(context, email)
                await self._sms_call("confirm", activation_id)

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

            await self._sms_call("cancel", activation_id)
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
            await self._sms_call("cancel", activation_id)
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
            await self._sms_call("cancel", activation_id)
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

    async def _click_next(self, page):
        """
        Нажать кнопку "Далее".

        Args:
            page: Страница Playwright
        """
        try:
            next_btn = await page.wait_for_selector(
                'input[type="submit"], button[type="submit"], #idSIButton9',
                timeout=10000
            )
            await next_btn.click()
            await page.wait_for_timeout(2000)
        except Exception as e:
            log.warning(f"Не удалось нажать Далее: {e}")

    async def _save_cookies(self, context, email: str) -> str:
        """
        Сохранить cookies в файл.

        Args:
            context: Контекст браузера
            email: Email аккаунта

        Returns:
            Путь к файлу cookies
        """
        os.makedirs("cookies", exist_ok=True)

        safe_email = email.replace("@", "_at_").replace(".", "_dot_")
        cookies_path = f"cookies/{safe_email}.json"

        cookies = await context.cookies()

        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        return cookies_path

    async def _check_success(self, page) -> bool:
        """
        Проверить, завершится ли регистрация успешно.

        Args:
            page: Страница Playwright

        Returns:
            True если регистрация успешна
        """
        try:
            current_url = page.url
            for domain in self.SUCCESS_DOMAINS:
                if domain in current_url:
                    return True
            return False
        except Exception:
            return False

    def _log_attempt(self, proxy_str: str, country: str, operator: str,
                     success: bool, error: str):
        """
        Записать попытку в лог.

        Args:
            proxy_str: Строка прокси
            country: Код страны
            operator: Название оператора
            success: True если успешно
            error: Описание ошибки
        """
        log.info(
            f"[{self.SERVICE_NAME}] proxy={proxy_str} country={country} "
            f"operator={operator} success={success} error={error}"
        )


class GoogleRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Google (Gmail)."""

    SERVICE_NAME = "Google"
    SMS_CODE = "go"
    EMAIL_DOMAIN = "gmail.com"
    SIGNUP_URL = "https://accounts.google.com/signup"


class AppleRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Apple (ID)."""

    SERVICE_NAME = "Apple"
    SMS_CODE = "wx"
    EMAIL_DOMAIN = "icloud.com"
    SIGNUP_URL = "https://appleid.apple.com/account"


class SnapchatRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Snapchat."""

    SERVICE_NAME = "Snapchat"
    SMS_CODE = "sc"
    EMAIL_DOMAIN = "snapchat.com"
    SIGNUP_URL = "https://account.snapchat.com/accounts/signup"


class InstagramRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Instagram."""

    SERVICE_NAME = "Instagram"
    SMS_CODE = "ig"
    EMAIL_DOMAIN = "instagram.com"
    SIGNUP_URL = "https://www.instagram.com/accounts/emailsignup"


class FacebookRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Facebook."""

    SERVICE_NAME = "Facebook"
    SMS_CODE = "fb"
    EMAIL_DOMAIN = "facebook.com"
    SIGNUP_URL = "https://www.facebook.com/r/"


class DiscordRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Discord."""

    SERVICE_NAME = "Discord"
    SMS_CODE = "dc"
    EMAIL_DOMAIN = "discord.com"
    SIGNUP_URL = "https://discord.com/register"