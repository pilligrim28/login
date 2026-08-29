"""
Модуль регистрации аккаунтов Microsoft (Outlook).
Использует Playwright для эмуляции браузера.
"""

import asyncio
import json
import os
import random
import string
from typing import Optional, Dict, Callable

from playwright.async_api import async_playwright

from .logger import log
from .sms import SMSActivate
from .database import Database
from .proxy_manager import ProxyManager


class MicrosoftRegistrator:
    """Регистрация аккаунтов Microsoft (Outlook)."""

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
            sms: SMSActivate,
            db: Database,
            proxy_manager: ProxyManager,
            config,
            on_status: Optional[Callable] = None,
            on_log: Optional[Callable] = None
    ):
        """
        Инициализация регистратора.

        Args:
            sms: Клиент SMS-Activate
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
        """
        Сгенерировать случайный email.

        Returns:
            Email вида name.surname123@outlook.com
        """
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
        """
        Сгенерировать дату рождения (18-50 лет).

        Returns:
            (day, month, year) — строки
        """
        year = random.randint(1975, 2007)
        month = random.randint(1, 12)
        day = random.randint(1, 28)

        return str(day), str(month), str(year)

    # ============================================
    # БРАУЗЕР
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
    # РЕГИСТРАЦИЯ
    # ============================================

    async def register(self) -> Optional[Dict]:
        """
        Выполнить полный цикл регистрации.

        Returns:
            {"email": ..., "password": ...} при успехе, None при неудаче
        """
        email = self.generate_email()
        password = self.generate_password()
        first_name, last_name = self.generate_name()
        day, month, year = self.generate_birthdate()

        self._callback_status("starting", {"email": email})
        self._callback_log(f"Начало регистрации: {email}")
        log.info(f"Начало: {email}")

        # 1. Аренда номера
        self._callback_status("renting_number", {"email": email})
        number_data = self.sms.rent_number()

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
        self._callback_log(f"Номер арендован: {phone}")
        log.info(f"Номер: {phone}")

        # 2. Получаем прокси
        proxy = self.proxy_manager.get_next()

        playwright = None
        browser = None

        try:
            playwright = await async_playwright().start()
            browser, context = await self._launch_browser(playwright, proxy)
            page = await context.new_page()

            # 3. Открываем страницу регистрации
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

            code = self.sms.wait_code(activation_id)

            if not code:
                self._callback_status("failed", {"email": email, "error": "SMS timeout"})
                self.sms.cancel(activation_id)
                self.db.add_account(
                    email=email,
                    password=password,
                    phone=phone,
                    status="failed",
                    error="SMS timeout"
                )
                await browser.close()
                return None

            self._callback_log(f"SMS-код получен")

            # 10. Ввод кода
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
            is_success = any(
                domain in current_url
                for domain in self.SUCCESS_DOMAINS
            )

            if is_success:
                self._callback_status("success", {"email": email})
                self._callback_log(f"✅ Успех: {email}")
                log.success(f"Регистрация успешна: {email}")

                # Сохраняем cookies
                cookies_path = self._save_cookies(context, email)

                # Подтверждаем номер
                self.sms.confirm(activation_id)

                # Сохраняем в базу
                self.db.add_account(
                    email=email,
                    password=password,
                    phone=phone,
                    cookies_path=cookies_path,
                    proxy=str(proxy) if proxy else "",
                    status="success"
                )

                await browser.close()
                return {"email": email, "password": password}
            else:
                self._callback_status(
                    "failed",
                    {"email": email, "error": f"URL: {current_url}"}
                )
                self._callback_log(f"❌ Неудача: {email}")
                log.warning(f"Регистрация не удалась: {email} | URL: {current_url}")

                self.sms.cancel(activation_id)
                self.db.add_account(
                    email=email,
                    password=password,
                    phone=phone,
                    status="failed",
                    error=f"Unexpected URL: {current_url}"
                )

                await browser.close()
                return None

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
            if browser:
                await browser.close()
            return None

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
            if browser:
                await browser.close()
            return None

        finally:
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

    def _save_cookies(self, context, email: str) -> str:
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

        cookies = context.cookies()

        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        return cookies_path