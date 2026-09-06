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


# 🔥 Патч 3: пулы для ротации fingerprint
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    (1366, 768),
    (1920, 1080),
    (1536, 864),
    (1440, 900),
    (1600, 900),
    (1280, 720),
]

_TIMEZONES = [
    "Europe/Moscow",
    "Europe/Kiev",
    "Europe/Warsaw",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/London",
    "Europe/Minsk",
]

_LOCALES = ["ru-RU", "en-US", "ru-UA", "pl-PL", "de-DE", "fr-FR", "en-GB"]


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
        on_log: Optional[Callable] = None,
    ):
        self.sms = sms
        self.db = db
        self.proxy_manager = proxy_manager
        self.config = config
        self.on_status = on_status
        self.on_log = on_log

    async def _sms_call(self, method_name: str, *args, **kwargs):
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
        username, phone, activation_id, proxy, proxy_str, country, operator,
    ) -> str:
        raise NotImplementedError


class MicrosoftRegistrator(BaseRegistrator):
    """Регистрация аккаунтов Microsoft (Outlook)."""
    SERVICE_NAME = "Microsoft"
    SMS_CODE = "mm"
    EMAIL_DOMAIN = "outlook.com"
    SIGNUP_URL = "https://signup.live.com/signup"
    SUCCESS_DOMAINS = [
        "account.microsoft.com",
        "outlook.live.com",
        "office.com",
        "login.live.com",
    ]

    def __init__(
        self,
        sms: PartnerAPI,
        db: Database,
        proxy_manager: ProxyManager,
        config,
        on_status: Optional[Callable] = None,
        on_log: Optional[Callable] = None,
    ):
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

    # ============================================
    # ГЕНЕРАЦИЯ ДАННЫХ
    # ============================================
    def generate_email(self) -> str:
        first_names = [
            "alex", "maria", "ivan", "anna", "pavel", "elena",
            "sergey", "olga", "dmitry", "nina", "mikhail", "tanya",
            "andrey", "irina", "nikolay", "svetlana", "victor", "yulia",
        ]
        last_names = [
            "smirnov", "ivanov", "petrov", "sidorov", "kuznetsov",
            "popov", "volkov", "sokolov", "mikhailov", "novikov",
            "morozov", "fedorov", "orlov", "belov", "kiselev",
        ]
        first = random.choice(first_names)
        last = random.choice(last_names)
        digits = "".join(random.choices(string.digits, k=random.randint(3, 5)))
        return f"{first}.{last}{digits}@{self.EMAIL_DOMAIN}"

    def generate_password(self) -> str:
        length = random.randint(14, 18)
        lower = string.ascii_lowercase
        upper = string.ascii_uppercase
        digits = string.digits
        special = "!@#$%^&*"
        password = [
            random.choice(lower),
            random.choice(upper),
            random.choice(digits),
            random.choice(special),
        ]
        all_chars = lower + upper + digits + special
        password.extend(random.choices(all_chars, k=length - 4))
        random.shuffle(password)
        return "".join(password)

    def generate_name(self) -> tuple:
        first_names = [
            "Алексей", "Мария", "Иван", "Анна", "Павел", "Елена",
            "Сергей", "Ольга", "Дмитрий", "Нина", "Михаил", "Таня",
            "Андрей", "Ирина", "Николай", "Светлана", "Виктор", "Юля",
        ]
        last_names = [
            "Смирнов", "Иванов", "Петров", "Сидоров", "Кузнецов",
            "Попов", "Волков", "Соколов", "Михайлов", "Новиков",
            "Морозов", "Федоров", "Орлов", "Белов", "Киселев",
        ]
        return random.choice(first_names), random.choice(last_names)

    def generate_birthdate(self) -> tuple:
        year = random.randint(1975, 2007)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        return str(day), str(month), str(year)

    def generate_username(self) -> str:
        base = "".join(random.choices(string.ascii_lowercase, k=random.randint(7, 10)))
        digits = "".join(random.choices(string.digits, k=random.randint(2, 4)))
        return f"{base}{digits}"

    # ============================================
    # ПРОВЕРКА CAPTCHA
    # ============================================
    async def _check_captcha(self, page: Page) -> bool:
        try:
            try:
                captcha_iframe = await page.frame_locator(
                    "iframe[title*='recaptcha' i]"
                ).first
                if captcha_iframe:
                    return True
            except Exception:
                pass
            page_content = await page.content()
            page_content_lower = page_content.lower()
            captcha_indicators = [
                "captcha", "verify you are human", "i'm not a robot",
                "recaptcha", "hcaptcha", "prove you're human", "security check",
            ]
            if any(indicator in page_content_lower for indicator in captcha_indicators):
                return True
            return False
        except Exception:
            return False

    # ============================================
    # РАБОТА С БРАУЗЕРОМ (🔥 ПАТЧ 3: ротация fingerprint)
    # ============================================
    async def _launch_browser(self, playwright, proxy: Optional[dict]):
        launch_options = {
            "headless": self.config.get("worker.headless", True),
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if proxy:
            launch_options["proxy"] = {
                "server": f"{proxy.get('type', 'http')}://{proxy['server']}"
            }
            if proxy.get("username"):
                launch_options["proxy"]["username"] = proxy["username"]
                launch_options["proxy"]["password"] = proxy.get("password", "")

        browser = await playwright.chromium.launch(**launch_options)

        # 🔥 Ротация fingerprint — каждый запуск с уникальными параметрами
        viewport = random.choice(_VIEWPORTS)
        context = await browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            locale=random.choice(_LOCALES),
            timezone_id=random.choice(_TIMEZONES),
            user_agent=random.choice(_USER_AGENTS),
        )
        return browser, context

    # ============================================
    # ГЛАВНЫЙ МЕТОД РЕГИСТРАЦИИ (🔥 ПАТЧ 2: свежий прокси на каждую попытку)
    # ============================================
    async def register(self) -> Optional[Dict]:
        # Генерация данных
        email = self.generate_email()
        max_attempts = 5
        for _ in range(max_attempts):
            if not self.db.email_exists(email):
                break
            email = self.generate_email()
        else:
            self._callback_status(
                "error",
                {"email": email, "error": "Не удалось сгенерировать уникальный email"},
            )
            self._callback_log(
                f"❌ Не удалось сгенерировать уникальный email после {max_attempts} попыток"
            )
            log.warning("Не удалось сгенерировать уникальный email")
            return None

        password = self.generate_password()
        first_name, last_name = self.generate_name()
        day, month, year = self.generate_birthdate()
        username = self.generate_username()

        self._callback_status("starting", {"email": email})
        self._callback_log(f"Начало регистрации [{self.SERVICE_NAME}]: {email}")
        log.info(f"Начало [{self.SERVICE_NAME}]: {email}")

        max_number_retries = int(self.config.get("worker.number_retries", 3) or 3)

        # 🔥 ПАТЧ 2: прокси и proxy_str теперь обновляются ВНУТРИ цикла
        for attempt in range(max_number_retries):
            # 🔥 КЛЮЧЕВОЕ: свежий прокси на КАЖДУЮ попытку
            proxy = self.proxy_manager.get_fresh_proxy()
            proxy_str = self._format_proxy_str(proxy)

            self._callback_log(
                f"🌐 Попытка {attempt + 1}/{max_number_retries} | "
                f"IP: {proxy_str or 'direct'}"
            )

            # 1. Аренда номера под конкретный сервис
            self._callback_status("renting_number", {"email": email})
            number_data = await self._sms_call(
                "rent_number", service=self.SMS_CODE
            )
            if not number_data:
                self._callback_status(
                    "error", {"email": email, "error": "Нет номеров"}
                )
                self.db.add_account(
                    email=email,
                    password=password,
                    status="error",
                    error="Не удалось арендовать номер",
                )
                return None

            phone = number_data["number"]
            activation_id = number_data["id"]
            country = number_data.get("country_code", "")
            operator = number_data.get("operator_name", "")

            self._callback_log(
                f"Номер арендован: {phone} "
                f"(попытка {attempt + 1}/{max_number_retries})"
            )
            log.info(f"Номер: {phone}")

            outcome = await self._run_attempt(
                email, password, first_name, last_name, day, month, year,
                username, phone, activation_id, proxy, proxy_str,
                country, operator,
            )

            if outcome == "success":
                return {"email": email, "password": password}

            # Номер уже зарегистрирован / SMS не пришло — берём новый номер
            # И на следующей итерации — ещё и новый прокси
            if outcome in ("already_registered", "sms_timeout"):
                await self._sms_call("report_bad_number", activation_id)
                self._callback_log(
                    f"↻ Номер {phone} не подходит — берём новый номер + новый IP"
                )
                continue

            # Прочие ошибки — стоп
            return None

        self._callback_status(
            "failed",
            {"email": email, "error": "Все номера уже зарегистрированы"},
        )
        return None

    def _format_proxy_str(self, proxy: Optional[Dict]) -> str:
        """Красивое представление прокси для логов."""
        if not proxy:
            return ""
        server = proxy.get("server", "")
        session = proxy.get("session", "")
        if session:
            # Показываем только хвост session_id, чтобы не засорять логи
            short_session = session.split(":")[-1][:8] if ":" in session else session[:8]
            return f"{server} (sess:{short_session})"
        return server

    async def _run_attempt(
        self,
        email, password, first_name, last_name, day, month, year,
        username, phone, activation_id, proxy, proxy_str, country, operator,
    ) -> str:
        playwright = None
        browser = None
        try:
            playwright = await async_playwright().start()
            browser, context = await self._launch_browser(playwright, proxy)
            page = await context.new_page()

            self._callback_status("opening_page", {"email": email})
            await page.goto(
                self.SIGNUP_URL,
                wait_until="networkidle",
                timeout=45000,
            )

            self._callback_status("filling_email", {"email": email})
            email_input = await page.wait_for_selector(
                'input[name="MemberName"], input[type="email"]',
                timeout=20000,
            )
            await email_input.fill(email)
            await self._click_next(page)

            await page.wait_for_timeout(3000)
            self._callback_status("filling_password", {"email": email})
            password_input = await page.wait_for_selector(
                'input[name="Password"], input[type="password"]',
                timeout=20000,
            )
            await password_input.fill(password)
            await self._click_next(page)

            await page.wait_for_timeout(3000)
            self._callback_status("filling_name", {"email": email})
            fn_input = await page.wait_for_selector(
                'input[name="FirstName"]',
                timeout=20000,
            )
            await fn_input.fill(first_name)
            ln_input = await page.wait_for_selector(
                'input[name="LastName"]',
                timeout=10000,
            )
            await ln_input.fill(last_name)
            await self._click_next(page)

            await page.wait_for_timeout(3000)
            self._callback_status("filling_birthdate", {"email": email})
            try:
                day_select = await page.wait_for_selector(
                    'select[name="BirthDay"]', timeout=10000
                )
                await day_select.select_option(day)
                month_select = await page.wait_for_selector(
                    'select[name="BirthMonth"]', timeout=5000
                )
                await month_select.select_option(month)
                year_select = await page.wait_for_selector(
                    'select[name="BirthYear"]', timeout=5000
                )
                await year_select.select_option(year)
            except Exception as e:
                self._callback_log(f"⚠️ Не удалось заполнить дату рождения: {e}")
                log.warning(f"Дата рождения не заполнена: {e}")
            await self._click_next(page)

            await page.wait_for_timeout(3000)
            self._callback_status(
                "filling_phone", {"email": email, "phone": phone}
            )
            phone_input = await page.wait_for_selector(
                'input[name="PhoneNumber"], input[type="tel"]',
                timeout=30000,
            )
            await phone_input.fill(phone)
            await self._click_next(page)

            self._callback_status(
                "waiting_sms", {"email": email, "phone": phone}
            )
            self._callback_log(f"Ожидание SMS для {phone}...")
            code = await self._sms_call("wait_code", activation_id)
            if not code:
                self._callback_status(
                    "failed", {"email": email, "error": "SMS timeout"}
                )
                self._log_attempt(
                    proxy_str, country, operator, False, "SMS timeout"
                )
                return "sms_timeout"

            self._callback_log("SMS-код получен")

            self._callback_status("entering_code", {"email": email})
            code_input = await page.wait_for_selector(
                'input[name="OtpCode"], input[type="text"]',
                timeout=20000,
            )
            await code_input.fill(code)
            await self._click_next(page)

            await page.wait_for_timeout(8000)

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
                    status="success",
                )
                self._log_attempt(
                    proxy_str, country, operator, True, ""
                )
                return "success"

            current_url = page.url
            self._callback_status(
                "failed", {"email": email, "error": f"URL: {current_url}"}
            )
            self._callback_log(
                f"❌ Неудача [{self.SERVICE_NAME}]: {email}"
            )
            log.warning(
                f"Регистрация не удалась: {email} | URL: {current_url}"
            )
            await self._sms_call("cancel", activation_id)
            self.db.add_account(
                email=email,
                password=password,
                phone=phone,
                status="failed",
                error=f"Unexpected URL: {current_url}",
            )
            self._log_attempt(
                proxy_str, country, operator, False,
                f"Unexpected URL: {current_url}",
            )
            return "failed"

        except asyncio.TimeoutError:
            self._callback_status(
                "error", {"email": email, "error": "Timeout"}
            )
            self._callback_log(f"❌ Таймаут: {email}")
            log.error(f"Таймаут при регистрации {email}")
            await self._sms_call("cancel", activation_id)
            self.db.add_account(
                email=email,
                password=password,
                phone=phone,
                status="error",
                error="Timeout",
            )
            self._log_attempt(
                proxy_str, country, operator, False, "Timeout"
            )
            return "error"
        except Exception as e:
            self._callback_status(
                "error", {"email": email, "error": str(e)}
            )
            self._callback_log(f"❌ Ошибка: {e}")
            log.error(f"Исключение при регистрации {email}: {e}")
            await self._sms_call("cancel", activation_id)
            self.db.add_account(
                email=email,
                password=password,
                phone=phone,
                status="error",
                error=str(e),
            )
            self._log_attempt(
                proxy_str, country, operator, False, str(e)
            )
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
        try:
            next_btn = await page.wait_for_selector(
                'input[type="submit"], button[type="submit"], #idSIButton9',
                timeout=10000,
            )
            await next_btn.click()
            await page.wait_for_timeout(2000)
        except Exception as e:
            log.warning(f"Не удалось нажать Далее: {e}")

    async def _save_cookies(self, context, email: str) -> str:
        os.makedirs("cookies", exist_ok=True)
        safe_email = email.replace("@", "_at_").replace(".", "_dot_")
        cookies_path = f"cookies/{safe_email}.json"
        cookies = await context.cookies()
        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        return cookies_path

    async def _check_success(self, page) -> bool:
        try:
            current_url = page.url
            for domain in self.SUCCESS_DOMAINS:
                if domain in current_url:
                    return True
            return False
        except Exception:
            return False

    def _log_attempt(
        self, proxy_str: str, country: str, operator: str,
        success: bool, error: str,
    ):
        log.info(
            f"[{self.SERVICE_NAME}] proxy={proxy_str} country={country} "
            f"operator={operator} success={success} error={error}"
        )


class GoogleRegistrator(BaseRegistrator):
    SERVICE_NAME = "Google"
    SMS_CODE = "go"
    EMAIL_DOMAIN = "gmail.com"
    SIGNUP_URL = "https://accounts.google.com/signup"


class AppleRegistrator(BaseRegistrator):
    SERVICE_NAME = "Apple"
    SMS_CODE = "wx"
    EMAIL_DOMAIN = "icloud.com"
    SIGNUP_URL = "https://appleid.apple.com/account"


class SnapchatRegistrator(BaseRegistrator):
    SERVICE_NAME = "Snapchat"
    SMS_CODE = "sc"
    EMAIL_DOMAIN = "snapchat.com"
    SIGNUP_URL = "https://account.snapchat.com/accounts/signup"


class InstagramRegistrator(BaseRegistrator):
    SERVICE_NAME = "Instagram"
    SMS_CODE = "ig"
    EMAIL_DOMAIN = "instagram.com"
    SIGNUP_URL = "https://www.instagram.com/accounts/emailsignup"


class FacebookRegistrator(BaseRegistrator):
    SERVICE_NAME = "Facebook"
    SMS_CODE = "fb"
    EMAIL_DOMAIN = "facebook.com"
    SIGNUP_URL = "https://www.facebook.com/r/"


class DiscordRegistrator(BaseRegistrator):
    SERVICE_NAME = "Discord"
    SMS_CODE = "dc"
    EMAIL_DOMAIN = "discord.com"
    SIGNUP_URL = "https://discord.com/register"