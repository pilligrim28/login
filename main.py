#!/usr/bin/env python3
"""
MassReg — массовая регистрация аккаунтов (CLI + Textual TUI)
=============================================================

Единая точка входа проекта. Интерфейс — только терминальный:

    python main.py                 # TUI (Textual): логи идут ПОРОДНЮ, по порядку
    python main.py --no-autostart  # TUI без автозапуска (старт по клавише 'r')
    python main.py run             # То же, что запуск без аргументов
    python main.py run --no-tui    # Обычный консольный вывод логов
    python main.py check           # Проверить конфигурацию и выйти
    python main.py doctor          # Диагностика окружения (пакеты, браузеры)
    python main.py status          # Краткий статус (БД, конфиг, логи)
    python main.py logs -n 100     # Последние строки файла логов
    python main.py setup           # Создать .env из .env.example
    python main.py reset --confirm --all   # Очистить локальные данные

Клавиши в TUI: r — запуск, s — стоп, c — очистить логи, q — выход.
Внизу есть строка ввода команд: run | stop | clear | quit.

Настройки читаются из .env (SECTION__FIELD), см. .env.example.
Ядро регистрации единое (workers/worker.py -> core/registrator_async.py),
поэтому поведение TUI и plain-режима совпадает.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer

__version__ = "0.2.0"

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.logger import log          # noqa: E402
from core.config import Config       # noqa: E402
from core.database import Database   # noqa: E402
from core.proxy_manager import ProxyManager  # noqa: E402


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _show_version() -> None:
    typer.echo(f"MassReg v{__version__}")


def set_verbose_logging(enabled: bool = False) -> None:
    """DEBUG-уровень логгера, если включён подробный вывод."""
    if not hasattr(log, "logger"):
        return
    level = logging.DEBUG if enabled else logging.INFO
    log.logger.setLevel(level)
    for handler in log.logger.handlers:
        handler.setLevel(level)


def _load_config(config_path: str) -> Config:
    try:
        return Config(config_path)
    except FileNotFoundError:
        log.error(f"Файл {config_path} не найден.")
        log.error("Создайте его командой: python main.py setup")
        raise typer.Exit(code=1)


def _apply_browser_backend(config: Config, browser: str | None) -> str:
    """Выбрать движок браузера (camoufox|chromium) и вернуть его имя."""
    if browser is not None:
        normalized = browser.strip().lower()
        if normalized not in {"camoufox", "chromium"}:
            raise typer.BadParameter("--browser: camoufox или chromium")
        config.set("browser.backend", normalized)
        config.set("camoufox.enabled", normalized == "camoufox")
    backend = str(config.get("browser.backend", "camoufox")).strip().lower()
    if backend not in {"camoufox", "chromium"}:
        backend = "camoufox"
        config.set("browser.backend", backend)
    return backend


def textual_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("textual") is not None
    except Exception:
        return False


def resolve_ui_mode(config: Config, ui: str | None = None) -> str:
    """Вернуть 'textual' (TUI) или 'plain' (обычный консольный вывод).

    Приоритет: флаг --ui / --no-tui > UI__MODE в .env > 'textual'.
    Автоматический откат на plain, если stdout не терминал или textual не
    установлен — иначе TUI вывел бы кашу вместо интерфейса.
    """
    chosen = (ui or "").strip().lower()
    if not chosen:
        chosen = str(os.environ.get("UI__MODE", "")
                     or config.get("ui.mode", "")
                     or "textual").strip().lower()
    if chosen in {"plain", "console", "off", "no", "none", "cli"}:
        return "plain"
    if chosen not in {"textual", "tui", "on", "yes", "gui", "interface"}:
        log.warning(f"Неизвестный режим интерфейса '{chosen}' — используется plain.")
        return "plain"
    if not sys.stdout.isatty():
        log.warning("stdout не терминал — TUI отключён, обычный вывод логов.")
        return "plain"
    if not textual_available():
        log.warning("Пакет textual не установлен — обычный вывод. Установка: pip install textual")
        return "plain"
    return "textual"


# ---------------------------------------------------------------------------
# Проверка конфигурации / окружения
# ---------------------------------------------------------------------------

def _ensure_playwright_browsers() -> bool:
    """Разовая синхронная проверка/установка браузеров Playwright."""
    from core.registrator_async import (
        _playwright_browsers_installed,
        _headless_shell_installed,
        reset_playwright_install_cache,
    )

    if not _playwright_browsers_installed():
        log.info("Браузеры Playwright не найдены — устанавливаю "
                 "`playwright install chromium` (разовая операция, минуты)...")
        reset_playwright_install_cache()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=1800, check=False,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            log.error(f"Не удалось запустить установку браузеров: {exc}")
            return False
        if result.returncode != 0:
            out = "\n".join(p for p in (result.stdout, result.stderr) if p).strip()
            log.error("Авто-установка браузеров не удалась:\n" + out[:2000])
            log.error("Выполните вручную: python -m playwright install chromium")
            return False
        log.success("✅ Браузеры Playwright установлены.")
    if not _headless_shell_installed():
        log.info("Chromium headless shell не найден — будет использован полный "
                 "Chromium в headless-режиме.")
    return True


def check_setup(config: Config) -> bool:
    """Проверить ключевые настройки перед запуском. True — можно стартовать."""
    log.info("=== Проверка конфигурации ===")
    ok = True

    api_key = str(config.get("sms.api_key", "") or "").strip()
    if not api_key or api_key.upper() in {"ВАШ_API_КЛЮЧ", "YOUR_API_KEY"}:
        log.error("API-ключ SMS не настроен (SMS__API_KEY в .env).")
        return False

    # Баланс — через тот же клиент, что использует воркер
    from workers.worker import create_sms_client
    pm = ProxyManager(config)
    sms = create_sms_client(config, pm)
    try:
        balance = sms.get_balance()
    except Exception as exc:
        log.error(f"Ошибка обращения к SMS-API: {exc}")
        return False
    if isinstance(balance, dict):
        usd = float(balance.get("usd", 0) or 0)
        log.success(f"Баланс Partner API: ${usd:.4f}")
        if usd <= 0:
            log.warning("⚠️ Баланс нулевой — регистрации завернутся ошибкой.")
    elif balance is not None:
        try:
            log.success(f"Баланс SMS-API: {float(balance):.2f} ₽")
        except (TypeError, ValueError):
            log.error(f"Не удалось разобрать баланс: {balance}")
            ok = False
    else:
        log.error("Не удалось получить баланс. Проверьте SMS__API_KEY / SMS__PARTNER_URL.")
        return False

    if pm.has_proxies():
        log.success(f"Прокси загружены: {pm.count()} шт.")
    else:
        log.warning("Прокси не настроены (PROXY__PROXIES) — регистрации могут блокироваться.")

    db = Database(config)
    stats = db.get_stats()
    log.success(f"БД: всего {stats.get('total', 0)} аккаунтов, успешных {stats.get('success', 0)}")

    backend = str(config.get("browser.backend", "camoufox")).strip().lower()
    camoufox_enabled = backend == "camoufox" and bool(config.get("camoufox.enabled", True))
    if not camoufox_enabled:
        if not _ensure_playwright_browsers():
            ok = False
    else:
        # Camoufox выбран движком — проверим, что браузер реально скачан,
        # и сразу подскажем одну команду для докачки (чтобы не ждать молча
        # ~200 МБ при первом же старте регистрации).
        try:
            from core.registrator_async import AsyncMicrosoftRegistrator

            if not AsyncMicrosoftRegistrator._camoufox_browser_ready():
                log.warning(
                    "Camoufox браузер ещё не скачан. Скачайте разово: "
                    "python -m camoufox fetch  "
                    "(или переключитесь на Chromium: python main.py run --browser chromium)")
            # GeoIP база (~9 МБ) — без неё Camoufox падает при запуске;
            # скачаем заранее, чтобы первая регистрация не ждала сеть.
            AsyncMicrosoftRegistrator._ensure_geoip_db()
        except Exception:
            pass

    total = int(config.get("worker.total_registrations", 100) or 100)
    threads = int(config.get("worker.max_concurrency", None)
                  or config.get("worker.threads", 10) or 10)
    services = config.get("sms.services", []) or [config.get("sms.service", "Microsoft")]
    log.info(f"Параметры: {total} регистраций, параллельность {threads}, "
             f"сервисы: {', '.join(str(s) for s in services)}")

    if ok:
        log.success("=== Конфигурация OK ===")
    else:
        log.warning("=== Конфигурация с предупреждениями ===")
    return ok


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def launch_tui(config: Config, autostart: bool = True) -> None:
    """Запустить Textual TUI (очередь логов -> построчный вывод)."""
    try:
        from core.tui import MassRegApp
    except ImportError as exc:  # pragma: no cover
        log.error("Для TUI нужен пакет textual: pip install textual")
        raise typer.Exit(code=1) from exc
    MassRegApp(config=config, autostart=autostart).run()


def run_plain(config: Config) -> None:
    """Запустить регистрацию с обычным консольным выводом логов."""
    from workers.worker import Worker
    worker = Worker(config)
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        log.warning("Прервано пользователем (Ctrl+C)")
        worker.stop()


def run_with_ui(config: Config, ui: str | None, autostart: bool = True) -> None:
    mode = resolve_ui_mode(config, ui)
    if mode == "textual":
        launch_tui(config, autostart=autostart)
    else:
        run_plain(config)


# ---------------------------------------------------------------------------
# CLI (typer)
# ---------------------------------------------------------------------------

app = typer.Typer(
    add_completion=False,
    help=f"MassReg v{__version__} — массовая регистрация (CLI + Textual TUI).",
    epilog="Быстрый старт:  python main.py setup  →  правим .env  →  python main.py",
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Показать версию и выйти."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробные логи (DEBUG)."),
    config_path: str = typer.Option(".env", "--config", "-c", help="Путь к .env-файлу."),
    browser: str | None = typer.Option(None, "--browser", help="camoufox | chromium."),
    ui: str | None = typer.Option(None, "--ui", help="textual (по умолчанию) | plain."),
    no_tui: bool = typer.Option(False, "--no-tui", help="Запуск без TUI (обычный вывод)."),
    autostart: bool = typer.Option(True, "--autostart/--no-autostart",
                                   help="В TUI сразу начать регистрацию."),
):
    """Запуск по умолчанию: Textual TUI, логи идут породно, по порядку."""
    if version:
        _show_version()
        raise typer.Exit(code=0)

    set_verbose_logging(verbose)
    if ctx.invoked_subcommand is not None:
        return

    config = _load_config(config_path)
    backend = _apply_browser_backend(config, browser)
    log.info(f"Браузерный движок: {backend}")
    run_with_ui(config, ui=("plain" if no_tui else ui), autostart=autostart)


@app.command("run")
def run_command(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробные логи (DEBUG)."),
    config_path: str = typer.Option(".env", "--config", "-c", help="Путь к .env-файлу."),
    browser: str | None = typer.Option(None, "--browser", help="camoufox | chromium."),
    ui: str | None = typer.Option(None, "--ui", help="textual (по умолчанию) | plain."),
    no_tui: bool = typer.Option(False, "--no-tui", help="Без TUI, обычный вывод логов."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Только проверка конфигурации."),
    autostart: bool = typer.Option(True, "--autostart/--no-autostart",
                                   help="В TUI сразу начать регистрацию."),
):
    """Запустить массовую регистрацию (TUI по умолчанию)."""
    set_verbose_logging(verbose)
    config = _load_config(config_path)
    backend = _apply_browser_backend(config, browser)
    log.info(f"Браузерный движок: {backend}")
    if dry_run:
        ok = check_setup(config)
        raise typer.Exit(code=0 if ok else 1)
    run_with_ui(config, ui=("plain" if no_tui else ui), autostart=autostart)


@app.command("check")
def check_command(
    config_path: str = typer.Option(".env", "--config", "-c", help="Путь к .env-файлу."),
    browser: str | None = typer.Option(None, "--browser", help="camoufox | chromium."),
):
    """Проверить конфигурацию (баланс SMS-API, прокси, БД, браузеры) и выйти."""
    config = _load_config(config_path)
    _apply_browser_backend(config, browser)
    ok = check_setup(config)
    raise typer.Exit(code=0 if ok else 1)


@app.command("doctor")
def doctor_command(
    config_path: str = typer.Option(".env", "--config", "-c", help="Путь к .env-файлу."),
    browser: str | None = typer.Option(None, "--browser", help="camoufox | chromium."),
):
    """Диагностика окружения: пакеты, браузеры, конфигурация."""
    config = _load_config(config_path)
    backend = _apply_browser_backend(config, browser)

    typer.echo(f"Python: {sys.version.split()[0]} ({sys.executable})")
    for pkg in ("textual", "playwright", "camoufox", "httpx", "typer", "pydantic"):
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "?")
            typer.secho(f"  ✓ {pkg} {ver}", fg=typer.colors.GREEN)
        except ImportError:
            typer.secho(f"  ✗ {pkg} НЕ установлен", fg=typer.colors.RED)

    from core.registrator_async import (
        _playwright_browsers_installed,
        _headless_shell_installed,
        AsyncMicrosoftRegistrator,
    )
    pw_ok = _playwright_browsers_installed()
    typer.secho(f"  {'✓' if pw_ok else '✗'} Playwright browsers",
                fg=typer.colors.GREEN if pw_ok else typer.colors.RED)
    hs_ok = _headless_shell_installed()
    typer.secho(f"  {'✓' if hs_ok else '—'} chrome-headless-shell (опционально)",
                fg=typer.colors.GREEN if hs_ok else typer.colors.CYAN)
    if backend == "camoufox":
        cli = AsyncMicrosoftRegistrator._resolve_camoufox_cli()
        typer.secho(f"  {'✓ Camoufox CLI: ' + str(cli) if cli else '— Camoufox CLI не найден (fallback на Chromium)'}",
                    fg=typer.colors.GREEN if cli else typer.colors.YELLOW)

    typer.echo("")
    ok = check_setup(config)
    raise typer.Exit(code=0 if ok else 1)


@app.command("status")
def status_command(
    config_path: str = typer.Option(".env", "--config", "-c", help="Путь к .env-файлу."),
):
    """Краткий статус: конфигурация, база данных, лог-файлы."""
    config = _load_config(config_path)
    db = Database(config)
    stats = db.get_stats()
    logs_dir = BASE_DIR / "logs"
    log_files = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if logs_dir.exists() else []
    resolved = Path(config_path)
    if not resolved.is_absolute():
        resolved = BASE_DIR / resolved
    typer.echo(f"Config:  {resolved}")
    typer.echo(f"Backend: {config.get('browser.backend', 'camoufox')}")
    typer.echo(f"SMS key: {'задан' if str(config.get('sms.api_key', '')).strip() else 'НЕ задан'}")
    typer.echo(f"БД:      {config.get('database.sqlite_path', 'accounts.db')} "
               f"(всего {stats.get('total', 0)}, успешно {stats.get('success', 0)})")
    typer.echo(f"Logs:    {log_files[0].name if log_files else 'нет'}")


@app.command("logs")
def logs_command(
    lines: int = typer.Option(50, "--lines", "-n", help="Сколько последних строк показать."),
    latest: bool = typer.Option(True, "--latest/--all", help="Только свежий файл или все."),
):
    """Показать последние строки файлов логов."""
    logs_dir = BASE_DIR / "logs"
    files = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if logs_dir.exists() else []
    if not files:
        typer.secho("Логи отсутствуют.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    for file in (files[:1] if latest else files):
        typer.echo(f"--- {file.name} ---")
        with file.open("r", encoding="utf-8", errors="replace") as fh:
            for entry in fh.readlines()[-lines:]:
                typer.echo(entry.rstrip())


@app.command("setup")
def setup_command(
    force: bool = typer.Option(False, "--force", help="Перезаписать существующий .env."),
    config_path: str = typer.Option(".env", "--config", "-c", help="Создаваемый файл."),
):
    """Создать .env из .env.example."""
    source = BASE_DIR / ".env.example"
    target = Path(config_path)
    if not target.is_absolute():
        target = BASE_DIR / target
    if not source.exists():
        typer.secho(".env.example не найден.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if target.exists() and not force:
        typer.secho(f"Уже существует: {target} (перезапись: --force)", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    shutil.copy2(source, target)
    typer.secho(f"Создан {target}. Заполните SMS__API_KEY, PROXY__*, BROWSER__BACKEND.",
                fg=typer.colors.GREEN)


@app.command("reset")
def reset_command(
    confirm: bool = typer.Option(False, "--confirm", help="Подтверждение удаления."),
    database: bool = typer.Option(False, "--db", help="Удалить SQLite-базу."),
    logs: bool = typer.Option(False, "--logs", help="Удалить логи."),
    cookies: bool = typer.Option(False, "--cookies", help="Удалить cookies."),
    all_data: bool = typer.Option(False, "--all", help="Удалить всё перечисленное."),
):
    """Очистить локальные данные (только с --confirm)."""
    if not confirm:
        typer.secho("Добавьте --confirm для подтверждения.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if all_data:
        database = logs = cookies = True
    removed = []
    if database:
        db_path = BASE_DIR / "accounts.db"
        if db_path.exists():
            db_path.unlink()
            removed.append(str(db_path))
    if logs:
        logs_dir = BASE_DIR / "logs"
        if logs_dir.exists():
            for f in logs_dir.glob("*.log*"):
                f.unlink()
            removed.append(str(logs_dir))
    if cookies:
        cookies_dir = BASE_DIR / "cookies"
        if cookies_dir.exists():
            shutil.rmtree(cookies_dir)
            removed.append(str(cookies_dir))
    if removed:
        typer.secho("Удалено: " + ", ".join(removed), fg=typer.colors.GREEN)
    else:
        typer.secho("Нечего удалять.", fg=typer.colors.YELLOW)


if __name__ == "__main__":
    app()
