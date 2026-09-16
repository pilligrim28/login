#!/usr/bin/env python3
"""
MassReg — Массовая регистрация аккаунтов
=========================================
CLI-версия для запуска регистрации.

Использование:
    python main.py              # Запустить регистрацию (синхронно)
    python main.py --check      # Проверить настройки
    python main.py --config .env
    python main.py --async      # Запустить в асинхронном режиме
"""

import sys
import os
import asyncio
import logging
import shutil
from pathlib import Path

import typer

__version__ = "0.1.0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.logger import log
from core.config import Config
from core.database import Database
from core.partner_api import PartnerAPI
from core.proxy_manager import ProxyManager
from core.ml_model import get_model, record_to_features, find_opportunities
from workers.worker import Worker


def banner():
    """Вывести баннер."""
    print(f"""
    ╔══════════════════════════════════════════════╗
    ║        MassReg v{__version__} — Пилотный запуск      ║
    ║       Массовая регистрация аккаунтов           ║
    ║    Microsoft (Outlook) • SMS-Activate • Proxy  ║
    ╚══════════════════════════════════════════════╝
    """)


def set_verbose_logging(enabled: bool = False):
    """Управление уровнем логирования в зависимости от режима --verbose."""
    if not hasattr(log, "logger"):
        return
    level = logging.DEBUG if enabled else logging.INFO
    log.logger.setLevel(level)
    for handler in log.logger.handlers:
        handler.setLevel(level)


def check_setup(config: Config) -> bool:
    """
    Проверить настройки перед запуском.

    Returns:
        True если все настройки корректны
    """
    log.info("=== Проверка конфигурации ===")

    # SMS
    api_key = config.get("sms.api_key", "")
    if not api_key or api_key == "ВАШ_API_КЛЮЧ":
        log.error("API-ключ SMS не настроен.")
        log.error("Откройте .env и укажите ключ в поле SMS__API_KEY")
        return False

    pm = ProxyManager(config)
    partner_url = config.get("sms.partner_url", "")
    api_url = config.get("sms.api_url", "")
    timeout = config.get("sms.timeout", 30)

    # Prefer Partner REST API when configured; otherwise fall back to SMS-Activate
    if partner_url:
        sms = PartnerAPI(api_key, base_url=partner_url or None, timeout=timeout, proxy_manager=pm)
        balance = sms.get_balance()
        if balance is not None and isinstance(balance, dict):
            usd = balance.get("usd", 0.0)
            log.success(f"Баланс Partner API: ${usd:.4f}")
            estimated = usd * 90 / 20  # ~20 руб за номер, курс ~90
            log.info(f"Примерно хватит на {int(estimated)} регистраций")
        else:
            log.error("Не удалось получить баланс от Partner API. Проверьте SMS__PARTNER_URL и API-ключ.")
            return False
    else:
        # Fallback to SMS-Activate compatible API
        from core.sms import SMSActivate
        sms = SMSActivate(api_key, base_url=api_url or None, timeout=timeout, proxy_manager=pm)
        balance = sms.get_balance()
        if balance is not None:
            try:
                # SMSActivate returns a float (assumed in RUB)
                bal_rub = float(balance)
            except Exception:
                log.error(f"Не удалось разобрать баланс от SMS-API: {balance}")
                return False
            log.success(f"Баланс SMS-Activate: {bal_rub:.2f} ₽")
            estimated = bal_rub / 20  # ~20 руб за номер
            log.info(f"Примерно хватит на {int(estimated)} регистраций")
        else:
            log.error("Не удалось получить баланс от SMS-API. Проверьте SMS__API_KEY и SMS__API_URL.")
            return False

    # Прокси
    if pm.has_proxies():
        log.success(f"Прокси загружены: {len(pm.proxies)}")
    else:
        log.warning("Прокси не настроены. Регистрация может не работать.")
        log.warning("Добавьте прокси в .env в поле PROXY__PROXIES")

    # База данных
    db = Database(config)
    stats = db.get_stats()
    log.success(f"База данных: всего {stats['total']} аккаунтов, "
                f"успешных {stats['success']}")

    # Воркер
    total = config.get("worker.total_registrations", 100)
    threads = config.get("worker.threads", 10)
    services = config.get("sms.services", []) or [config.get("sms.service", "Microsoft")]
    log.info(f"Параметры: {total} регистраций, {threads} потоков")
    log.info(f"Сервисы: {', '.join(services)}")

    log.success("=== Конфигурация OK ===")
    return True


def run_sync(config: Config):
    """Запустить регистрацию в синхронном режиме."""
    worker = Worker(config)

    def on_progress(done, total, success, failed):
        log.info(f"Прогресс: {done}/{total} (успех: {success}, неудача: {failed})")

    def on_account(account):
        log.info(f"Аккаунт: {account}")

    def on_log(message):
        log.info(message)

    def on_finished():
        log.info("Работа воркера завершена")

    worker.on_progress = on_progress
    worker.on_account = on_account
    worker.on_log = on_log
    worker.on_finished = on_finished

    try:
        worker.run()
    except KeyboardInterrupt:
        log.warning("Прервано пользователем (Ctrl+C)")
        worker.stop()


async def run_async(config: Config):
    """Запустить регистрацию в асинхронном режиме."""
    from workers.async_worker import AsyncWorker

    worker = AsyncWorker(config)

    try:
        await worker.run()
    except KeyboardInterrupt:
        log.warning("Прервано пользователем (Ctrl+C)")
        worker.stop()


async def async_check_setup(config: Config) -> bool:
    """Проверить настройки в асинхронном режиме."""
    log.info("=== Проверка конфигурации (async) ===")

    api_key = config.get("sms.api_key", "")
    if not api_key or api_key == "ВАШ_API_КЛЮЧ":
        log.error("API-ключ SMS не настроен.")
        return False

    base_url = config.get("sms.api_url", "")
    timeout = config.get("sms.timeout", 30)

    from core.sms_async import AsyncSMSActivate
    async with AsyncSMSActivate(api_key, base_url=base_url or None, timeout=timeout) as sms:
        balance = await sms.get_balance()
        if balance is not None:
            log.success(f"Баланс SMS-Activate: {balance:.2f} ₽")
        else:
            log.error("Не удалось получить баланс. Проверьте API-ключ.")
            return False

    pm = ProxyManager(config)
    if pm.has_proxies():
        log.success(f"Прокси загружены: {len(pm.proxies)}")
    else:
        log.warning("Прокси не настроены.")

    db = Database(config)
    stats = db.get_stats()
    log.success(f"База данных: всего {stats['total']} аккаунтов, успешных {stats['success']}")

    log.success("=== Конфигурация OK ===")
    return True


def ml_suggest(config: Config):
    """Обучить ML-модель и показать возможности."""
    db = Database(config)
    attempts = db.get_attempts()

    if len(attempts) < 10:
        log.warning(f"Недостаточно данных для ML: {len(attempts)}/10")
        return

    model = get_model(config)
    records = [(record_to_features(a), int(a.get("success", 0))) for a in attempts]
    model.fit(records)
    model.save()
    log.info(f"ML: модель обучена на {len(records)} попытках")

    opportunities = find_opportunities(model, attempts, top_k=5)
    if opportunities:
        log.info("ML: топ возможностей (сервис / страна -> вероятность):")
        for proba, opts in opportunities:
            log.info(
                f"     {opts.get('service') or '?'} / "
                f"{opts.get('country') or '?'} -> {proba * 100:.1f}%"
            )
    else:
        log.info("ML: возможности не найдены")


app = typer.Typer(
    add_completion=False,
    help="MassReg — массовая регистрация аккаунтов.",
    epilog="Примеры:\n  python main.py setup\n  python main.py run --config .env\n  python main.py check --async\n  python main.py status\n  python main.py doctor\n  python main.py ml-suggest --config .env",
    rich_markup_mode="rich",
)


def _load_config(config_path: str) -> Config:
    """Загрузить конфигурацию и показать понятную ошибку при отсутствии файла."""
    try:
        return Config(config_path)
    except FileNotFoundError:
        log.error(f"Файл {config_path} не найден.")
        log.error("Создайте .env на основе .env.example.")
        raise typer.Exit(code=1)


def _apply_browser_backend(config: Config, browser: str | None = None) -> str:
    """Установить выбранный браузерный движок и вернуть его имя."""
    if browser is None:
        backend = config.get("browser.backend", "camoufox")
        normalized = str(backend).strip().lower()
        if normalized not in {"camoufox", "chromium"}:
            normalized = "camoufox"
        config.set("browser.backend", normalized)
        config.set("camoufox.enabled", normalized == "camoufox")
        return normalized

    normalized = browser.strip().lower()
    if normalized not in {"camoufox", "chromium"}:
        raise typer.BadParameter("--browser должен быть одним из: camoufox, chromium")

    config.set("browser.backend", normalized)
    config.set("camoufox.enabled", normalized == "camoufox")
    return normalized


def _show_version():
    typer.echo(f"MassReg v{__version__}")


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _resolve_config_path(config_path: str) -> Path:
    path = Path(config_path)
    if not path.is_absolute():
        path = _project_root() / path
    return path


def _latest_log_file() -> Path | None:
    logs_dir = _project_root() / "logs"
    if not logs_dir.exists():
        return None
    files = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def launch_desktop_app(config_path: str = ".env") -> None:
    """Запустить десктопный интерфейс через единую точку входа."""
    try:
        from PySide6.QtWidgets import QApplication
        from desktop.main_window import MainWindow
    except ImportError as exc:
        typer.secho(
            "Для GUI нужен PySide6. Установите зависимости: pip install -r requirements-dev.txt",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    app_qt = QApplication(sys.argv)
    app_qt.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app_qt.exec())


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Показать версию приложения и выйти.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Включить подробный вывод отладки.",
    ),
    banner_flag: bool = typer.Option(
        False,
        "--banner",
        help="Показать информационный баннер при запуске.",
    ),
    browser: str | None = typer.Option(
        None,
        "--browser",
        help="Выбрать движок браузера: camoufox или chromium.",
    ),
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Путь к файлу .env (или env-файлу) с настройками.",
    ),
    async_mode: bool = typer.Option(
        False,
        "--async",
        help="Использовать асинхронный режим регистрации.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Проверить настройки и выйти.",
    ),
    ml_suggest: bool = typer.Option(
        False,
        "--ml-suggest",
        help="Обучить ML-модель и показать топ возможностей.",
    ),
):
    """Главный entrypoint CLI. Если команда не указана, используется прежнее поведение."""
    if version:
        _show_version()
        raise typer.Exit(code=0)

    set_verbose_logging(verbose)
    # Показывать баннер только если явно запрошено
    if banner_flag:
        banner()

    if ctx.invoked_subcommand is not None:
        return

    config = _load_config(config_path)
    backend = _apply_browser_backend(config, browser)
    log.info(f"Используется браузерный движок: {backend}")

    if check:
        ok = asyncio.run(async_check_setup(config)) if async_mode else check_setup(config)
        raise typer.Exit(code=0 if ok else 1)

    if ml_suggest:
        ml_suggest(config)
        raise typer.Exit(code=0)

    if async_mode:
        asyncio.run(run_async(config))
    else:
        run_sync(config)


@app.command("version")
def version_command():
    """Показать версию приложения."""
    _show_version()


@app.command("desktop")
def desktop_command(
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Путь к .env-файлу для GUI-приложения.",
    ),
):
    """Запустить десктопный интерфейс через main.py."""
    _load_config(config_path)
    launch_desktop_app(config_path=config_path)


@app.command("gui")
def gui_command(
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Путь к .env-файлу для GUI-приложения.",
    ),
):
    """Alias для запуска GUI через main.py."""
    desktop_command(config_path=config_path)


@app.command("check")
def check_command(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Показать более подробный вывод.",
    ),
    browser: str | None = typer.Option(
        None,
        "--browser",
        help="Выбрать движок браузера: camoufox или chromium.",
    ),
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Путь к файлу .env.",
    ),
    async_mode: bool = typer.Option(
        False,
        "--async",
        help="Проверить настройки в асинхронном режиме.",
    ),
):
    """Проверить настройки и выйти."""
    set_verbose_logging(verbose)
    config = _load_config(config_path)
    backend = _apply_browser_backend(config, browser)
    log.info(f"Используется браузерный движок: {backend}")
    ok = asyncio.run(async_check_setup(config)) if async_mode else check_setup(config)
    raise typer.Exit(code=0 if ok else 1)


@app.command("run")
def run_command(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Показать подробный вывод во время запуска.",
    ),
    browser: str | None = typer.Option(
        None,
        "--browser",
        help="Выбрать движок браузера: camoufox или chromium.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Проверить конфигурацию и выйти без запуска регистрации.",
    ),
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Путь к файлу .env.",
    ),
    async_mode: bool = typer.Option(
        False,
        "--async",
        help="Использовать асинхронный режим.",
    ),
):
    """Запустить массовую регистрацию."""
    set_verbose_logging(verbose)
    config = _load_config(config_path)
    backend = _apply_browser_backend(config, browser)
    log.info(f"Используется браузерный движок: {backend}")

    if dry_run:
        typer.echo(f"Dry run: проверка конфигурации для {config_path}")
        ok = asyncio.run(async_check_setup(config)) if async_mode else check_setup(config)
        raise typer.Exit(code=0 if ok else 1)

    if async_mode:
        asyncio.run(run_async(config))
    else:
        run_sync(config)


@app.command("ml-suggest")
def ml_suggest_command(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Показать подробный вывод во время обучения.",
    ),
    browser: str | None = typer.Option(
        None,
        "--browser",
        help="Выбрать движок браузера: camoufox или chromium.",
    ),
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Путь к файлу .env.",
    ),
):
    """Обучить ML-модель и показать рекомендации по параметрам."""
    set_verbose_logging(verbose)
    config = _load_config(config_path)
    backend = _apply_browser_backend(config, browser)
    log.info(f"Используется браузерный движок: {backend}")
    ml_suggest(config)


@app.command("doctor")
def doctor_command(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Показать подробный вывод диагностики.",
    ),
    browser: str | None = typer.Option(
        None,
        "--browser",
        help="Выбрать движок браузера: camoufox или chromium.",
    ),
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Путь к файлу .env.",
    ),
):
    """Проверить конфигурацию, окружение и состояние браузера."""
    set_verbose_logging(verbose)
    config = _load_config(config_path)
    backend = _apply_browser_backend(config, browser)
    log.info(f"Используется браузерный движок: {backend}")

    ok = check_setup(config)
    if backend == "camoufox":
        from core.registrator_async import AsyncMicrosoftRegistrator
        camoufox_cli = AsyncMicrosoftRegistrator._resolve_camoufox_cli()
        if camoufox_cli:
            log.success(f"Camoufox CLI найден: {camoufox_cli}")
        else:
            log.warning("Camoufox CLI не найден; будет работать fallback на Chromium.")

    raise typer.Exit(code=0 if ok else 1)


@app.command("menu")
def menu_command():
    """Краткое меню и примеры использования (человекочитаемо)."""
    typer.secho("MassReg — быстрые команды:", fg=typer.colors.CYAN, bold=True)
    typer.echo("")
    typer.secho("Запуск:", fg=typer.colors.GREEN)
    typer.echo("  python main.py run --config .env           Запустить регистрацию (синхронно)")
    typer.echo("  python main.py run --async --config .env   Запустить асинхронно")
    typer.echo("")
    typer.secho("Конфигурация:", fg=typer.colors.GREEN)
    typer.echo("  python main.py setup                       Создать .env из .env.example")
    typer.echo("  python main.py status --config .env        Показать краткий статус")
    typer.echo("")
    typer.secho("Диагностика и GUI:", fg=typer.colors.GREEN)
    typer.echo("  python main.py doctor --config .env        Полная диагностика окружения")
    typer.echo("  python main.py desktop                     Запустить GUI (если установлен PySide6)")
    typer.echo("")
    typer.secho("Управление данными:", fg=typer.colors.GREEN)
    typer.echo("  python main.py logs --lines 100            Показать последние логи")
    typer.echo("  python main.py reset --confirm --all      Удалить локальные данные (опасно)")
    typer.echo("")
    typer.secho("Дополнительно:", fg=typer.colors.YELLOW)
    typer.echo("  python main.py doctor --banner             Показать баннер в диагностике")
    typer.echo("")


@app.command("setup")
def setup_command(
    force: bool = typer.Option(
        False,
        "--force",
        help="Перезаписать существующий .env даже если он уже есть.",
    ),
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Путь к конфигурационному файлу, который нужно создать.",
    ),
):
    """Создать .env из .env.example и подготовить рабочее окружение."""
    root = _project_root()
    source = root / ".env.example"
    target = _resolve_config_path(config_path)

    if not source.exists():
        typer.secho("Файл .env.example не найден в корне проекта.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if target.exists() and not force:
        typer.secho(f"Файл уже существует: {target}. Используйте --force для перезаписи.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    shutil.copy2(source, target)
    typer.secho(f"Создан конфигурационный файл: {target}", fg=typer.colors.GREEN)
    typer.echo("Далее отредактируйте .env и задайте SMS__API_KEY, PROXY__PROXIES и BROWSER__BACKEND.")


@app.command("status")
def status_command(
    browser: str | None = typer.Option(
        None,
        "--browser",
        help="Принудительно выбрать движок браузера: camoufox или chromium.",
    ),
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Путь к файлу .env.",
    ),
):
    """Показать краткий статус проекта, конфигурации и базы данных."""
    config = _load_config(config_path)
    backend = _apply_browser_backend(config, browser)
    db = Database(config)
    stats = db.get_stats()

    sms_key = bool(config.get("sms.api_key", "").strip())
    proxies = bool(config.get("proxy.proxies", [])) or config.get("proxy.enabled", False)
    db_path = _resolve_config_path(config.get("database.sqlite_path", "accounts.db"))

    typer.echo(f"Backend: {backend}")
    typer.echo(f"Config: {_resolve_config_path(config_path)}")
    typer.echo(f"SMS API key: {'configured' if sms_key else 'missing'}")
    typer.echo(f"Proxies: {'enabled' if proxies else 'not configured'}")
    typer.echo(f"Database: {db_path} ({stats.get('total', 0)} total / {stats.get('success', 0)} success)")
    typer.echo(f"Logs: {_latest_log_file() or 'not found'}")


@app.command("logs")
def logs_command(
    lines: int = typer.Option(
        50,
        "--lines",
        "-n",
        help="Сколько последних строк показать из лога.",
    ),
    latest: bool = typer.Option(
        True,
        "--latest/--all",
        help="Показать только самый свежий лог-файл или все доступные.",
    ),
):
    """Показать последние строки логов проекта."""
    logs_dir = _project_root() / "logs"
    if not logs_dir.exists():
        typer.secho("Каталог logs не найден.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    files = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        typer.secho("Логи отсутствуют.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    selected = files[:1] if latest else files
    for file in selected:
        typer.echo(f"--- {file.name} ---")
        with file.open("r", encoding="utf-8", errors="replace") as handle:
            entries = handle.readlines()[-lines:]
            if not entries:
                typer.echo("(пустой лог)")
                continue
            for entry in entries:
                typer.echo(entry.rstrip())


@app.command("reset")
def reset_command(
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Подтвердить сброс данных. Без него команда не выполняется.",
    ),
    database: bool = typer.Option(
        False,
        "--db",
        help="Удалить SQLite-базу данных.",
    ),
    logs: bool = typer.Option(
        False,
        "--logs",
        help="Удалить файлы логов.",
    ),
    cookies: bool = typer.Option(
        False,
        "--cookies",
        help="Удалить сохранённые cookies.",
    ),
    all_data: bool = typer.Option(
        False,
        "--all",
        help="Удалить все локальные данные: БД, логи и cookies.",
    ),
):
    """Очистить локальные данные проекта после явного подтверждения."""
    if not confirm:
        typer.secho("Для сброса данных используйте --confirm.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if all_data:
        database = True
        logs = True
        cookies = True

    root = _project_root()
    if database:
        db_path = root / "accounts.db"
        if db_path.exists():
            db_path.unlink()
            typer.secho(f"Удалён файл БД: {db_path}", fg=typer.colors.GREEN)
    if logs:
        logs_dir = root / "logs"
        if logs_dir.exists():
            for log_file in logs_dir.glob("*.log"):
                log_file.unlink()
            typer.secho(f"Удалены логи из: {logs_dir}", fg=typer.colors.GREEN)
    if cookies:
        cookies_dir = root / "cookies"
        if cookies_dir.exists():
            shutil.rmtree(cookies_dir)
            typer.secho(f"Удалена папка cookies: {cookies_dir}", fg=typer.colors.GREEN)

    if not any((database, logs, cookies, all_data)):
        typer.secho("Нечего сбрасывать. Укажите --db, --logs, --cookies или --all.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
