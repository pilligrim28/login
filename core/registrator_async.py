"""
Асинхронный модуль регистрации аккаунтов Microsoft (Outlook).
Использует Playwright для автоматизации браузера.

Добавлено:
- Полная асинхронность
- Обработка CAPTCHA
- Проверка на дубликаты email
- Улучшенная обработка ошибок
- Поддержка отмены через asyncio.CancelledError
"""

import asyncio
import json
import os
import random
import string
from typing import Optional, Dict, Callable, Tuple

from playwright.async_api import async_playwright, Page, BrowserContext, Browser

from .logger import log
from .sms_async import AsyncSMSActivate
from .database import Database
from .proxy_manager import ProxyManager


class AsyncMicrosoftRegistrator:
    """
    Асинхронная регистрация аккаунтов Microsoft (Outlook).
    
    Пример использования:
        async with AsyncMicrosoftRegistrator(sms, db, proxy_manager, config) as registrator:
            result = await registrator.register()
    """

    SIGNUP_URL = "https://signup.live.com/signup"

    # Домены, указывающие на успешную регистрацию
    SUCCESS_DOMAINS = [
        "account.microsoft.com",
        "outlook.live.com",
        "office.com",
        "login.live.com"
    ]

    def __init__(
            self,
            sms: AsyncSMSActivate,
            db: Database,
            proxy_manager: ProxyManager,
            config,
            on_status: Optional[Callable] = None,
            on_log: Optional[Callable] = None
    ):
        """
        Инициализация регистратора.

        Args:
            sms: Асинхронный клиент SMS-Activate
            db: База данных
            proxy_manager: Менеджер прокси
            config: Конфигурация
            on_status: Колбэк для статуса (status, data)
            on_log: Колбэк для логов (message)
        """
        self.sms = sms
        self.db = db
        self.proxy_manager = proxy_manager
        self.config = config
        self.on_status = on_status
        self.on_log = on_log
        
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    async def __aenter__(self):
        """Асинхронный контекстный менеджер (вход)."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный контекстный менеджер (выход)."""
        await self._close_browser()

    async def _close_browser(self):
        """Закрыть браузер."""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

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
        """Сгенерировать случайный email."""
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
        return f"{first}.{last}{digits}@outlook.com"

    def generate_password(self) -> str:
        """Сгенерировать надежный пароль."""
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

    def generate_name(self) -> Tuple[str, str]:
        """Сгенерировать имя и фамилию."""
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

    def generate_birthdate(self) -> Tuple[str, str, str]:
        """Сгенерировать дату рождения."""
        year = random.randint(1975, 2007)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        return str(day), str(month), str(year)

    # ============================================
    # ПРОВЕРКА CAPTCHA
    # ============================================

    async def _check_captcha(self, page: Page) -> bool:
        """Проверить страницу на наличие CAPTCHA."""
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
                "captcha", "verify you are human", "i'm not a robot",
                "recaptcha", "hcaptcha", "prove you're human", "security check"
            ]
            
            if any(indicator in page_content_lower for indicator in captcha_indicators):
                return True

            return False
        except Exception:
            return False

    # ============================================
    # РАБОТА С БРАУЗЕРОМ
    # ============================================

    async def _launch_browser(self, proxy: Optional[dict] = None) -> Tuple[Browser, BrowserContext]:
        """Запустить браузер с прокси."""
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

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(**launch_options)

        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        return self._browser, self._context

    async def _click_next(self, page: Page) -> bool:
        """Нажать кнопку 'Далее'."""
        try:
            if await self._check_captcha(page):
                self._callback_log("⚠️ Обнаружена CAPTCHA! Пожалуйста, решите её вручную.")
                log.warning("Обнаружена CAPTCHA!")
                return False

            next_btn = await page.wait_for_selector(
                'input[type="submit"], button[type="submit"], #idSIButton9',
                timeout=10000
            )
            await next_btn.click()
            await page.wait_for_timeout(2000)
            return True
        except Exception as e:
            log.warning(f"Не удалось нажать Далее: {e}")
            return False

    async def _save_cookies(self, context: BrowserContext, email: str) -> str:
        """Сохранить cookies в файл."""
        os.makedirs("cookies", exist_ok=True)
        safe_email = email.replace("@", "_at_").replace(".", "_dot_")
        cookies_path = f"cookies/{safe_email}.json"
        cookies = await context.cookies()
        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        return cookies_path

    # ============================================
    # ГЛАВНЫЙ МЕТОД РЕГИСТРАЦИИ
    # ============================================

    async def register(self) -> Optional[Dict]:
        """
        Выполнить полный цикл регистрации.
        
        Returns:
            {"email": ..., "password": ...} при успехе, None при неудаче
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

        self._callback_status("starting", {"email": email})
        self._callback_log(f"Начало регистрации: {email}")
        log.info(f"Начало: {email}")

        # 1. Аренда номера
        self._callback_status("renting_number", {"email": email})
        number_data = await self.sms.rent_number()

        if not number_data:
            self._callback_status("error", {"email": email, "error": "Не удалось арендовать номер"})
            self.db.add_account(
                email=email,
                password=password,
                status="error",
                error="Не удалось арендовать номер"
            )
            return None

        phone = number_data["number"]
        activation_id = number_data["id"]
        self._callback_log(f"Номер арендован: {phone}")
        log.info(f"Номер: {phone}")

        # 2. Получаем прокси
        proxy = self.proxy_manager.get_next()

        try:
            # 3. Запускаем браузер
            await self._launch_browser(proxy)
            self._page = await self._context.new_page()

            # 4. Открываем страницу регистрации
            self._callback_status("opening_page", {"email": email})
            await self._page.goto(
                self.SIGNUP_URL,
                wait_until="networkidle",
                timeout=45000
            )

            # Проверка CAPTCHA после загрузки страницы
            if await self._check_captcha(self._page):
                self._callback_status("error", {"email": email, "error": "CAPTCHA на странице регистрации"})
                await self.sms.cancel(activation_id)
                self.db.add_account(
                    email=email,
                    password=password,
                    phone=phone,
                    status="error",
                    error="CAPTCHA на странице регистрации"
                )
                return None

            # 5. Заполняем email
            self._callback_status("filling_email", {"email": email})
            email_input = await self._page.wait_for_selector(
                'input[name="MemberName"], input[type="email"]',
                timeout=20000
            )
            await email_input.fill(email)
            if not await self._click_next(self._page):
                await self.sms.cancel(activation_id)
                return None

            # 6. Заполняем пароль
            await self._page.wait_for_timeout(3000)
            self._callback_status("filling_password", {"email": email})
            password_input = await self._page.wait_for_selector(
                'input[name="Password"], input[type="password"]',
                timeout=20000
            )
            await password_input.fill(password)
            if not await self._click_next(self._page):
                await self.sms.cancel(activation_id)
                return None

            # 7. Заполняем имя и фамилию
            await self._page.wait_for_timeout(3000)
            self._callback_status("filling_name", {"email": email})

            fn_input = await self._page.wait_for_selector(
                'input[name="FirstName"]',
                timeout=20000
            )
            await fn_input.fill(first_name)

            ln_input = await self._page.wait_for_selector(
                'input[name="LastName"]',
                timeout=10000
            )
            await ln_input.fill(last_name)
            if not await self._click_next(self._page):
                await self.sms.cancel(activation_id)
                return None

            # 8. Дата рождения
            await self._page.wait_for_timeout(3000)
            self._callback_status("filling_birthdate", {"email": email})

            try:
                day_select = await self._page.wait_for_selector(
                    'select[name="BirthDay"]',
                    timeout=10000
                )
                await day_select.select_option(day)

                month_select = await self._page.wait_for_selector(
                    'select[name="BirthMonth"]',
                    timeout=5000
                )
                await month_select.select_option(month)

                year_select = await self._page.wait_for_selector(
                    'select[name="BirthYear"]',
                    timeout=5000
                )
                await year_select.select_option(year)
            except Exception as e:
                self._callback_log(f"⚠️ Не удалось заполнить дату рождения: {e}")
                log.warning(f"Дата рождения не заполнена: {e}")

            if not await self._click_next(self._page):
                await self.sms.cancel(activation_id)
                return None

            # 9. Номер телефона
            await self._page.wait_for_timeout(3000)
            self._callback_status("filling_phone", {"email": email, "phone": phone})

            phone_input = await self._page.wait_for_selector(
                'input[name="PhoneNumber"], input[type="tel"]',
                timeout=30000
            )
            await phone_input.fill(phone)
            if not await self._click_next(self._page):
                await self.sms.cancel(activation_id)
                return None

            # 10. Ожидание SMS
            self._callback_status("waiting_sms", {"email": email, "phone": phone})
            self._callback_log(f"Ожидание SMS для {phone}...")

            code = await self.sms.wait_code(activation_id)

            if not code:
                self._callback_status("failed", {"email": email, "error": "SMS timeout"})
                await self.sms.cancel(activation_id)
                self.db.add_account(
                    email=email,
                    password=password,
                    phone=phone,
                    status="failed",
                    error="SMS timeout"
                )
                return None

            self._callback_log(f"SMS-код получен")

            # 11. Ввод кода
            self._callback_status("entering_code", {"email": email})

            code_input = await self._page.wait_for_selector(
                'input[name="OtpCode"], input[type="text"]',
                timeout=20000
            )
            await code_input.fill(code)
            if not await self._click_next(self._page):
                await self.sms.cancel(activation_id)
                return None

            # 12. Ожидание завершения
            await self._page.wait_for_timeout(8000)

            # 13. Проверка успеха
            current_url = self._page.url
            is_success = any(
                domain in current_url
                for domain in self.SUCCESS_DOMAINS
            )

            if is_success:
                self._callback_status("success", {"email": email})
                self._callback_log(f"✅ Успех: {email}")
                log.success(f"Регистрация успешна: {email}")

                # Сохраняем cookies
                cookies_path = await self._save_cookies(self._context, email)

                # Подтверждаем номер
                await self.sms.confirm(activation_id)

                # Сохраняем в базу
                self.db.add_account(
                    email=email,
                    password=password,
                    phone=phone,
                    cookies_path=cookies_path,
                    proxy=str(proxy) if proxy else "",
                    status="success"
                )

                return {"email": email, "password": password}
            else:
                self._callback_status(
                    "failed",
                    {"email": email, "error": f"URL: {current_url}"}
                )
                self._callback_log(f"❌ Неудача: {email}")
                log.warning(f"Регистрация не удалась: {email} | URL: {current_url}")

                await self.sms.cancel(activation_id)
                self.db.add_account(
                    email=email,
                    password=password,
                    phone=phone,
                    status="failed",
                    error=f"Unexpected URL: {current_url}"
                )

                return None

        except asyncio.CancelledError:
            self._callback_status("error", {"email": email, "error": "Cancelled"})
            self._callback_log(f"❌ Отменено: {email}")
            log.warning(f"Регистрация отменена: {email}")
            await self.sms.cancel(activation_id)
            self.db.add_account(
                email=email,
                password=password,
                phone=phone,
                status="error",
                error="Cancelled"
            )
            return None

        except Exception as e:
            self._callback_status("error", {"email": email, "error": str(e)})
            self._callback_log(f"❌ Ошибка: {e}")
            log.error(f"Исключение при регистрации {email}: {e}")
            await self.sms.cancel(activation_id)
            self.db.add_account(
                email=email,
                password=password,
                phone=phone,
                status="error",
                error=str(e)
            )
            return None

        finally:
            await self._close_browser()
