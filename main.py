#!/usr/bin/env python3
"""
MassReg — Массовая регистрация аккаунтов
=========================================
CLI-версия для запуска регистрации.

Использование:
    python main.py              # Запустить регистрацию (синхронно)
    python main.py --check      # Проверить настройки
    python main.py --config custom.yaml
    python main.py --async      # Запустить в асинхронном режиме
"""

import sys
import argparse
import os
import asyncio

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
    print("""
    ╔══════════════════════════════════════════════╗
    ║           MassReg v0.1 — Пилотный запуск       ║
    ║       Массовая регистрация аккаунтов           ║
    ║    Microsoft (Outlook) • SMS-Activate • Proxy  ║
    ╚══════════════════════════════════════════════╝
    """)


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
        log.error("Откройте config.yaml и укажите ключ в поле sms.api_key")
        return False

    pm = ProxyManager(config)
    base_url = config.get("sms.partner_url", "")
    sms = PartnerAPI(api_key, base_url=base_url or None, proxy_manager=pm)
    balance = sms.get_balance()
    if balance is not None:
        log.success(f"Баланс SMS-Activate: {balance:.2f} ₽")
        estimated = balance / 20  # ~20 руб за номер
        log.info(f"Примерно хватит на {int(estimated)} регистраций")
    else:
        log.error("Не удалось получить баланс. Проверьте API-ключ.")
        return False

    # Прокси
    if pm.has_proxies():
        log.success(f"Прокси загружены: {len(pm.proxies)}")
    else:
        log.warning("Прокси не настроены. Регистрация может не работать.")
        log.warning("Добавьте прокси в config.yaml в поле proxy.proxies")

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
        log.success("Регистрация завершена")

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

    from core.sms_async import AsyncSMSActivate
    async with AsyncSMSActivate(api_key, base_url=base_url or None) as sms:
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


def main():
    """Точка входа."""
    parser = argparse.ArgumentParser(
        description="MassReg — массовая регистрация аккаунтов"
    )
    parser.add_argument("--check", action="store_true",
                        help="Проверить настройки и выйти")
    parser.add_argument("--ml-suggest", action="store_true",
                        help="Обучить ML-модель на истории и показать топ возможностей")
    parser.add_argument("--config", default="config.yaml",
                        help="Путь к файлу конфигурации")
    parser.add_argument("--async", action="store_true", dest="async_mode",
                        help="Использовать асинхронный режим")
    args = parser.parse_args()

    banner()

    # Загрузка конфигурации
    try:
        config = Config(args.config)
    except FileNotFoundError:
        log.error(f"Файл {args.config} не найден.")
        log.error("Создайте config.yaml на основе шаблона.")
        sys.exit(1)

    # Проверка
    if args.check:
        if args.async_mode:
            ok = asyncio.run(async_check_setup(config))
        else:
            ok = check_setup(config)
        sys.exit(0 if ok else 1)

    # ML: показать топ возможностей
    if args.ml_suggest:
        ml_suggest(config)
        sys.exit(0)

    # Запуск
    if args.async_mode:
        asyncio.run(run_async(config))
    else:
        run_sync(config)


if __name__ == "__main__":
    main()
