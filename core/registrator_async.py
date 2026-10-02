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
import re
import shutil
import string
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Dict, Callable, Tuple

from playwright.async_api import async_playwright, Page, BrowserContext, Browser
from camoufox.async_api import AsyncCamoufox

from .logger import log
from .sms_async import AsyncSMSActivate
from .database import Database
from .proxy_manager import ProxyManager


# ---------------------------------------------------------------------------
# Автоустановка браузеров Playwright (fix "Executable doesn't exist at ...")
# ---------------------------------------------------------------------------

_PW_INSTALL_LOCK: Optional[asyncio.Lock] = None
_PW_LOCK_LOOP: Optional[int] = None
_PW_BROWSERS_READY = False
_PW_LAST_ERROR: Optional[str] = None
_CAMOUFOX_READY: Optional[bool] = None  # None = ещё не проверяли
_GEOIP_DB_READY: Optional[bool] = None  # None = ещё не проверяли (база geoip)


def reset_playwright_install_cache():
    """Сбросить кэш успешной установки (вызывается при свежей ошибке запуска)."""
    global _PW_BROWSERS_READY, _CAMOUFOX_READY, _GEOIP_DB_READY
    _PW_BROWSERS_READY = False
    _CAMOUFOX_READY = None
    _GEOIP_DB_READY = None


def _get_install_lock() -> asyncio.Lock:
    """Создать asyncio.Lock, привязанный к ТЕКУЩЕМУ event loop.

    ВАЖНО: в синхронном режиме каждая регистрация запускается через
    asyncio.run() в отдельном потоке — свой event loop. Глобальный Lock,
    созданный в одном loop, в другом вызывает
    "… is bound to a different event loop". Поэтому lock пересоздаётся
    при смене работающего loop (в пределах одного loop асинхронные
    потоки разделяют один lock и не плодят параллельные установки).
    """
    global _PW_INSTALL_LOCK, _PW_LOCK_LOOP
    loop_id = id(asyncio.get_running_loop())
    if _PW_INSTALL_LOCK is None or _PW_LOCK_LOOP != loop_id:
        _PW_INSTALL_LOCK = asyncio.Lock()
        _PW_LOCK_LOOP = loop_id
    return _PW_INSTALL_LOCK

# Регулярка для извлечения имени браузера из сообщения об ошибке
_EXECUTABLE_MISSING_RE = re.compile(
    r"Executable doesn't exist at\s+\S*?(chromium|firefox|webkit)[_-]\S*",
    re.IGNORECASE,
)


def _playwright_browsers_installed() -> bool:
    """Быстрая проверка: есть ли хотя бы один установленный браузер в реестре Playwright."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            for name in ("chromium", "firefox", "webkit"):
                bt = getattr(pw, name)
                try:
                    if Path(bt.executable_path).exists():
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


async def ensure_playwright_browsers(names: Tuple[str, ...] = ("chromium",)) -> bool:
    """Установить недостающие браузеры Playwright (аналог `playwright install`).

    Вызывается автоматически при первом запуске Chromium-fallback, если
    браузеры не скачаны. Потоки не плодят параллельные установки —
    всё сериализовано через lock и кэш результата.
    """
    global _PW_BROWSERS_READY, _PW_LAST_ERROR

    if _PW_BROWSERS_READY:
        return True

    async with _get_install_lock():
        # двойная проверка после получения лога
        if _PW_BROWSERS_READY:
            return True

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            installed = await loop.run_in_executor(pool, _playwright_browsers_installed)

        if installed:
            _PW_BROWSERS_READY = True
            return True

        args = [sys.executable, "-m", "playwright", "install", *names]
        log.info("Браузеры Playwright не найдены — запускаю авто-установку: "
                 f"{' '.join(args[2:])} (может занять несколько минут)...")
        try:
            def _run_install() -> subprocess.CompletedProcess:
                return subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                    check=False,
                )

            result = await loop.run_in_executor(None, _run_install)
        except (subprocess.SubprocessError, OSError) as exc:
            _PW_LAST_ERROR = str(exc)
            log.error(f"Не удалось запустить авто-установку браузеров: {exc}")
            return False

        output = "\n".join(p for p in (result.stdout, result.stderr) if p).strip()
        if result.returncode == 0:
            _PW_BROWSERS_READY = True
            log.info("✅ Браузеры Playwright успешно установлены.")
            return True

        _PW_LAST_ERROR = output[:2000] or f"exit code {result.returncode}"
        log.error(f"Авто-установка браузеров завершилась с ошибкой:\n{_PW_LAST_ERROR}")
        return False


def _is_executable_missing_error(message: str) -> bool:
    """Определить, что ошибка запуска — отсутствующий бинарник браузера."""
    lowered = message.lower()
    return "executable doesn't exist" in lowered or "playwright install" in lowered


def _playwright_browsers_root() -> Optional[Path]:
    """Каталог, куда Playwright скачивает браузеры (по умолчанию ~/.cache/ms-playwright
    на Linux, %LOCALAPPDATA%\\ms-playwright на Windows)."""
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        try:
            return Path(env).expanduser()
        except Exception:
            return None
    try:
        from playwright._impl._driver import compute_driver_dir

        driver_dir = Path(compute_driver_dir())
        # driver лежит в site-packages/playwright/driver — поднимаемся до site-packages
        for parent in driver_dir.parents:
            if parent.name.lower() in ("site-packages", "lib"):
                candidates = [parent.parent / "ms-playwright",
                              parent / "ms-playwright"]
                for c in candidates:
                    if c.exists():
                        return c
    except Exception:
        pass
    home = Path.home()
    for cand in (
        home / "AppData" / "Local" / "ms-playwright",   # Windows
        home / ".cache" / "ms-playwright",              # Linux
        home / "Library" / "Caches" / "ms-playwright",  # macOS
    ):
        if cand.exists():
            return cand
    return None


def _find_headless_shell_executable() -> Optional[str]:
    """Найти бинарник chrome-headless-shell в каталоге браузеров Playwright.

    Надёжный способ без приватных API (в разных версиях playwright они разные):
    ищем каталоги вида chromium_headless_shell-* / chromium-headless-shell-* и
    внутри — исполняемый файл.
    """
    root = _playwright_browsers_root()
    if root is None or not root.exists():
        return None
    # Порядок поиска исполняемых файлов: сначала «родной» для текущей ОС,
    # затем остальные варианты (важно для тестов и переноса кэша браузеров
    # между машинами с разными ОС).
    exe_names = ["chrome-headless-shell"]
    if os.name == "nt":
        exe_names.insert(0, "chrome-headless-shell.exe")
    else:
        exe_names.append("chrome-headless-shell.exe")
    try:
        for d in sorted(root.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            name = d.name.lower()
            if "headless" not in name or not name.startswith("chromium"):
                continue
            for sub in ("chrome-headless-shell-win64", "chrome-headless-shell-linux64",
                        "chrome-headless-shell-mac", "."):
                cand_dir = d / sub
                if not cand_dir.exists():
                    continue
                for exe in exe_names:
                    cand = cand_dir / exe
                    if cand.exists():
                        return str(cand)
            # запасной вариант — рекурсивный поиск одного файла
            for exe in exe_names:
                matches = list(d.rglob(exe))
                if matches:
                    return str(matches[0])
    except Exception:
        return None
    return None


def _headless_shell_installed() -> bool:
    """Есть ли в реестре Playwright скачанный chromium-headless-shell.

    В Playwright >= 1.49 `chromium.launch(headless=True)` по умолчанию использует
    отдельный бинарник `chrome-headless-shell`, который НЕ ставится вместе с
    обычным `chromium` (нужна команда `playwright install chromium-headless-shell`).
    Если его нет, а обычный Chromium установлен — мы подменим канал запуска,
    чтобы не требовать вторую загрузку (~100 МБ).
    """
    return _find_headless_shell_executable() is not None


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
        self._camoufox = None
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

        if self._camoufox:
            await self._camoufox.__aexit__(None, None, None)
        elif self._browser:
            await self._browser.close()

        if self._playwright:
            await self._playwright.stop()

        self._page = None
        self._context = None
        self._browser = None
        self._camoufox = None
        self._playwright = None

    @staticmethod
    def _resolve_camoufox_cli() -> Optional[str]:
        """Найти способ запустить Camoufox CLI в текущем окружении."""
        candidates = [
            shutil.which("camoufox"),
            os.path.join(os.path.dirname(sys.executable), "camoufox"),
            os.path.join(os.path.dirname(sys.executable), "camoufox.exe"),
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        # Вариант без скрипта в PATH: python -m camoufox (актуально для Windows,
        # где Scripts\camoufox.exe может отсутствовать)
        try:
            import camoufox  # noqa: F401
            return "python-module"
        except Exception:
            return None

    @classmethod
    def _run_camoufox_cli(cls, args: list, timeout: int) -> subprocess.CompletedProcess:
        """Выполнить Camoufox CLI (или `python -m camoufox`) с указанными аргументами."""
        cli_path = cls._resolve_camoufox_cli()
        if not cli_path:
            raise FileNotFoundError("Camoufox CLI не найден")
        cmd = [sys.executable, "-m", "camoufox", *args] if cli_path == "python-module" \
            else [cli_path, *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=os.getcwd(),
            timeout=timeout,
            check=False,
        )

    @staticmethod
    def _camoufox_browser_ready() -> bool:
        """Проверить наличие скачанного Camoufox browser напрямую (без subprocess).

        Важно: в multiversion-раскладке camoufox>=0.4 функция
        camoufox_path(download_if_missing=False) может бросить
        "Version 'official' not found in cache" / CamoufoxNotInstalled даже
        тогда, когда версии уже скачаны, но активная не выбрана. Поэтому
        сначала проверяем реальный каталог установок, и только потом —
        camoufox_path.
        """
        try:
            from camoufox import multiversion as mv

            # 1) Multiversion-раскладка (camoufox >= 0.4/0.5): версии лежат в
            #    <INSTALL_DIR>/browsers/<repo>/<version> с version.json
            if mv.BROWSERS_DIR.exists():
                for repo_dir in mv.BROWSERS_DIR.iterdir():
                    if not repo_dir.is_dir():
                        continue
                    for ver_dir in repo_dir.iterdir():
                        if (ver_dir / "version.json").exists() and any(
                            (ver_dir / exe).exists()
                            for exe in ("camoufox.exe", "camoufox")
                        ):
                            # Активная версия отсутствует? Выберем эту, чтобы
                            # AsyncCamoufox знал, какой браузер запускать.
                            if mv.get_active_path() is None:
                                try:
                                    mv.set_active(
                                        f"browsers/{repo_dir.name}/{ver_dir.name}")
                                except Exception:
                                    pass
                            return True

            # 2) Старая раскладка: браузер прямо в корне INSTALL_DIR
            install_dir = Path(str(mv.INSTALL_DIR))
            if (install_dir / "camoufox.exe").exists() or (install_dir / "camoufox").exists():
                return True

            # 3) Фолбэк: прямой запрос пути (без скачивания)
            from camoufox.pkgman import camoufox_path

            return Path(camoufox_path(download_if_missing=False)).exists()
        except Exception:
            return False

    @staticmethod
    def _ensure_geoip_db() -> bool:
        """Проверить/скачать GeoIP базу Camoufox (один раз на процесс).

        Без geoip/mmdb/*.mmdb запуск с geoip=True падает с FileNotFoundError
        («maxmind geolite2-ipv4.mmdb»). Скачивание базы (~9 МБ) выполняется
        штатной функцией camoufox с перебором зеркал; при сетевом сбое
        возвращается False — вызывающий код отключит geoip, чтобы
        регистрация не вставала из-за геолокации.
        """
        global _GEOIP_DB_READY
        if _GEOIP_DB_READY is not None:
            return _GEOIP_DB_READY
        try:
            from camoufox import geolocation as geo
            if not geo.ALLOW_GEOIP:
                log.warning("Модуль maxminddb не установлен — geoip отключён "
                            "(pip install camoufox[geoip])")
                _GEOIP_DB_READY = False
                return False
            mmdb_path = geo.get_mmdb_path("ipv4")
            if mmdb_path.exists() and not geo.needs_update():
                _GEOIP_DB_READY = True
                return True
            log.info(f"Скачиваю GeoIP базу Camoufox → {mmdb_path} ...")
            geo.download_mmdb()
            _GEOIP_DB_READY = mmdb_path.exists()
            if _GEOIP_DB_READY:
                log.info("GeoIP база Camoufox готова.")
            else:
                log.warning("GeoIP база не появилась после скачивания — geoip будет отключён.")
            return _GEOIP_DB_READY
        except Exception as exc:
            log.warning(f"Не удалось скачать GeoIP базу ({exc}) — geoip будет отключён.")
            _GEOIP_DB_READY = False
            return False

    def _ensure_camoufox_runtime(self) -> bool:
        """Убедиться, что Camoufox runtime установлен и готов к запуску.

        КЭШ: проверка выполняется один раз на процесс. Если браузер уже
        скачан — никаких повторных `camoufox fetch` (раньше полная
        перепроверка/докачка запускалась при КАЖДОМ старте браузера,
        что приводило к лавине предупреждений и откатов на Chromium).
        """
        global _CAMOUFOX_READY
        if _CAMOUFOX_READY is not None:
            return _CAMOUFOX_READY

        if self._camoufox_browser_ready():
            _CAMOUFOX_READY = True
            return True

        if not self._resolve_camoufox_cli():
            log.warning("Camoufox CLI не найден в окружении. Используется Chromium fallback.")
            _CAMOUFOX_READY = False
            return False

        log.info("Camoufox браузер не скачан — запускаю `camoufox sync + fetch` "
                 "(разовая операция, ~200 МБ)...")
        # 1) Синхронизируем список версий из репозиториев — без этого fetch
        #    на некоторых сборках падает с "Version 'official' not found in cache".
        try:
            self._run_camoufox_cli(["sync"], timeout=120)
        except (subprocess.SubprocessError, OSError, ValueError):
            pass  # sync не критичен — fetch сам подтянет кэш при успехе сети

        last_output = ""
        for attempt in (1, 2):
            try:
                result = self._run_camoufox_cli(["fetch"], timeout=900)
            except subprocess.TimeoutExpired:
                log.warning("camoufox fetch: таймаут (медленная сеть?)")
                continue
            except (OSError, ValueError) as exc:
                log.warning(f"Не удалось запустить camoufox fetch: {exc}")
                break

            output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
            last_output = output
            if result.returncode == 0 and self._camoufox_browser_ready():
                log.info("✅ Camoufox runtime успешно установлен.")
                _CAMOUFOX_READY = True
                return True
            if attempt == 1 and not self._camoufox_browser_ready():
                log.info("Camoufox fetch: первая попытка не удалась, повторяю...")

        if self._camoufox_browser_ready():
            _CAMOUFOX_READY = True
            return True

        if last_output:
            log.warning(last_output[:2000])
        log.warning("Camoufox runtime недоступен (сеть/антивирус блокирует загрузку?). "
                    "Используется Chromium fallback. Для антидетект-движка выполните "
                    "вручную: python -m camoufox fetch")
        _CAMOUFOX_READY = False
        return False

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

    async def _launch_chromium(
        self,
        launch_options: dict,
        context_options: dict,
    ) -> Tuple[Browser, BrowserContext]:
        """Запустить Chromium через Playwright.

        Особенности (fix "Executable doesn't exist at .../chrome-headless-shell.exe"):
        1. Если браузеры Playwright вообще не скачаны — автоматически
           выполняется `playwright install chromium` (разовая операция).
        2. В headless-режиме Playwright >= 1.49 по умолчанию ищет отдельный
           бинарник chrome-headless-shell. Если он отсутствует, но обычный
           Chromium установлен — подменяем канал на 'chromium' и запускаем
           полный браузер в headless (без второй загрузки ~100 МБ).
        """
        # Проактивная проверка до первого запуска (экономит время при 10+ потоках)
        await ensure_playwright_browsers(("chromium",))

        # Обход отсутствующего headless shell: используем полный Chromium
        if launch_options.get("headless"):
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=1) as pool:
                hs_ok = await loop.run_in_executor(pool, _headless_shell_installed)
            if not hs_ok:
                launch_options = {**launch_options, "channel": "chromium"}

        for attempt in range(2):
            self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(**launch_options)
                break
            except Exception as exc:
                message = str(exc)
                await self._stop_playwright()
                if attempt == 0 and _is_executable_missing_error(message):
                    log.warning(
                        "Бинарник Chromium отсутствует — запускаю авто-установку "
                        "браузеров Playwright (это разовая операция)..."
                    )
                    reset_playwright_install_cache()
                    if await ensure_playwright_browsers(("chromium",)):
                        # при повторе убираем явный канал — после установки всё на месте
                        launch_options = {k: v for k, v in launch_options.items()
                                          if k != "channel"}
                        continue
                raise

        self._context = await self._browser.new_context(**context_options)
        return self._browser, self._context

    async def _stop_playwright(self):
        """Корректно остановить инстанс playwright после неудачного запуска."""
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = None

    async def _launch_browser(self, proxy: Optional[dict] = None) -> Tuple[Browser, BrowserContext]:
        """Запустить браузер через Camoufox с возможностью отката к обычному Chromium.

        FIX #37: proxy передаётся ТОЛЬКО в AsyncCamoufox. new_context() — без proxy.
        FIX #39: persistent_context не используется (всегда создаём новый контекст).
        """
        browser_backend = str(self.config.get("browser.backend", self.config.get("camoufox.enabled", True) and "camoufox" or "chromium")).strip().lower()
        if browser_backend not in {"camoufox", "chromium"}:
            browser_backend = "camoufox" if self.config.get("camoufox.enabled", True) else "chromium"
        use_camoufox = browser_backend == "camoufox"
        headless = self.config.get("camoufox.headless", self.config.get("worker.headless", True))
        locale = self.config.get("camoufox.locale", "ru-RU")
        timezone_id = self.config.get("camoufox.timezone_id", "Europe/Moscow")
        viewport_width = self.config.get("camoufox.viewport_width", 1366)
        viewport_height = self.config.get("camoufox.viewport_height", 768)
        user_agent = self.config.get(
            "camoufox.user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        debug = self.config.get("camoufox.debug", False)

        # ---- Формируем proxy_config ----
        proxy_config = None
        if proxy:
            ptype = (proxy.get("type") or "http").lower()
            server = proxy["server"]
            if ptype.startswith("socks"):
                server = f"{ptype}://{server}"
            else:
                server = f"http://{server}"
            proxy_config = {"server": server}
            if proxy.get("username"):
                proxy_config["username"] = proxy["username"]
                proxy_config["password"] = proxy.get("password", "")
            log.info(f"🌐 Proxy config: {proxy_config}")

        # ---- Camoufox ----
        if use_camoufox:
            if not self._ensure_camoufox_runtime():
                log.warning("Camoufox runtime не готов, откат на Chromium.")
                use_camoufox = False

        if use_camoufox:
            # geoip=True требует локальную базу mmdb; без неё запуск падает с
            # FileNotFoundError — скачиваем один раз, при неудаче отключаем geoip.
            camoufox_kwargs = {
                "headless": headless,
                "debug": debug,
                "humanize": True,
                "geoip": self._ensure_geoip_db(),
            }
            if proxy_config:
                # Camoufox ожидает proxy в формате: server + username/password отдельно
                camoufox_proxy = {"server": proxy_config["server"]}
                if proxy_config.get("username"):
                    camoufox_proxy["username"] = proxy_config["username"]
                    camoufox_proxy["password"] = proxy_config["password"]
                camoufox_kwargs["proxy"] = camoufox_proxy

            try:
                self._camoufox = AsyncCamoufox(**camoufox_kwargs)
                self._browser = await self._camoufox.__aenter__()
                # new_context БЕЗ proxy — Camoufox уже знает про прокси
                self._context = await self._browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                    locale=locale,
                    timezone_id=timezone_id,
                    user_agent=user_agent,
                )
                return self._browser, self._context
            except Exception as exc:
                message = str(exc)
                log.error(f"❌ Camoufox launch failed: {message}")
                log.error(f"   proxy: {proxy_config}")
                import traceback
                log.error(traceback.format_exc())
                if "not installed" in message.lower() or "camoufox fetch" in message.lower():
                    if self._ensure_camoufox_runtime():
                        try:
                            self._camoufox = AsyncCamoufox(**camoufox_kwargs)
                            self._browser = await self._camoufox.__aenter__()
                            self._context = await self._browser.new_context(
                                viewport={"width": viewport_width, "height": viewport_height},
                                locale=locale,
                                timezone_id=timezone_id,
                                user_agent=user_agent,
                            )
                            return self._browser, self._context
                        except Exception as e:
                            log.error(f"❌ Camoufox retry failed: {e}")
                log.warning("Camoufox не запустился, откат на Chromium.")
                use_camoufox = False

        # ---- Chromium (fallback) ----
        launch_options = {
            "headless": headless,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if proxy_config:
            launch_options["proxy"] = proxy_config

        context_options = {
            "viewport": {"width": viewport_width, "height": viewport_height},
            "locale": locale,
            "timezone_id": timezone_id,
            "user_agent": user_agent,
        }

        return await self._launch_chromium(launch_options, context_options)

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

    async def register(self, proxy: Optional[dict] = None, retries: int = 0) -> Optional[Dict]:
        """
        Выполнить полный цикл регистрации с повторными попытками.

        Args:
            proxy: Явный прокси (dict из ProxyManager). Если None — на каждой
                   попытке берётся следующий прокси из пула (или direct).
            retries: Число ПОВТОРОВ поверх первой попытки. По умолчанию
                     берётся из worker.retry_count (3 => 2 повтора).

        Returns:
            {"email": ..., "password": ...} при успехе, None при неудаче
        """
        if not retries:
            try:
                retries = max(0, int(self.config.get("worker.retry_count", 3) or 3) - 1)
            except (TypeError, ValueError):
                retries = 2

        attempts = retries + 1
        for attempt in range(attempts):
            current_proxy = proxy if attempt == 0 else self.proxy_manager.get_next()
            proxy_str = f"{current_proxy['server']}" if current_proxy else "direct"
            self._callback_log(f"🌐 Попытка {attempt + 1}/{attempts} | IP: {proxy_str}")

            result = await self._register_once(current_proxy)
            if result:
                return result

            if attempt < attempts - 1:
                self._callback_log(f"↻ Попытка {attempt + 1} не удалась, пробуем снова...")

        self._callback_log(f"❌ Все {attempts} попыток исчерпаны")
        return None

    async def _register_once(self, proxy: Optional[dict] = None) -> Optional[Dict]:
        """
        Одна попытка полного цикла регистрации.

        Прокси фиксируется для всей попытки: и браузер, и SMS-клиент
        работают с одним и тем же IP (переопределяем get_next()).
        """
        original_get_next = self.proxy_manager.get_next
        self.proxy_manager.get_next = lambda: proxy
        try:
            return await self._do_register()
        finally:
            self.proxy_manager.get_next = original_get_next

    async def _do_register(self) -> Optional[Dict]:
        """Внутренняя реализация одной попытки регистрации."""
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

        # 2. Прокси этой попытки уже зафиксирован в _register_once
        proxy = self.proxy_manager.get_next()

        try:
            # 3. Запускаем браузер
            await self._launch_browser(proxy)
            self._page = await self._context.new_page()

            # 4. Открываем страницу регистрации
            self._callback_status("opening_page", {"email": email})
            await self._page.goto(
                self.SIGNUP_URL,
                wait_until="domcontentloaded",
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
            # Попытка пометить прокси как мёртвый, если ошибка связана с прокси/соединением
            try:
                if 'proxy' in str(e).lower() or 'ns_error' in str(e).lower() or 'connection' in str(e).lower():
                    if 'proxy' in locals() and proxy:
                        try:
                            self.proxy_manager.mark_dead(proxy)
                            log.info("Прокси помечен как мёртвый из-за ошибки")
                        except Exception:
                            log.debug("Не удалось пометить прокси как мёртвый")
            except Exception:
                pass
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
