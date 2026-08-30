#!/usr/bin/env python3
"""
MassReg — Массовая регистрация аккаунтов
=========================================
CLI-версия для простого запуска без GUI.

Использование:
    python main.py              # Запустить регистрацию
    python main.py --check      # Проверить настройки
    python main.py --config custom.yaml
"""

import sys
import argparse
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.logger import log
from core.config import Config
from core.database import Database
from core.sms import SMSActivate
from core.proxy_manager import ProxyManager
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
    Проверить конфигурацию перед запуском.

    Returns:
        True если всё настроено
    """
    log.info("=== Проверка конфигурации ===")

    # SMS
    api_key = config.get("sms.api_key", "")
    if not api_key or api_key == "ВАШ_API_КЛЮЧ":
        log.error("API-ключ SMS не настроен.")
        log.error("Откройте config.yaml и укажите ключ в поле sms.api_key")
        return False

    pm = ProxyManager(config)
    base_url = config.get("sms.api_url", "")
    sms = SMSActivate(api_key, base_url=base_url or None, proxy_manager=pm)
    balance = sms.get_balance()
    if balance is not None:
        log.success(f"Баланс SMS-Activate: {balance:.2f} ₽")
        estimated = balance / 20  # ~20 руб за номер
        log.info(f"Примерно хватит на {int(estimated)} регистраций")
    else:
        log.error("Не удалось проверить баланс. Проверьте API-ключ.")
        return False

    # Прокси
    if pm.has_proxies():
        log.success(f"Прокси загружено: {len(pm.proxies)}")
    else:
        log.warning("Прокси не настроены. Регистрация может не работать.")
        log.warning("Добавьте прокси в config.yaml в разделе proxy.proxies")

    # База данных
    db = Database(config)
    stats = db.get_stats()
    log.success(f"База данных: всего {stats['total']} аккаунтов, "
                f"успешных {stats['success']}")

    # Воркер
    total = config.get("worker.total_registrations", 100)
    threads = config.get("worker.threads", 10)
    log.info(f"Параметры: {total} регистраций, {threads} потоков")

    log.success("=== Конфигурация OK ===")
    return True


def main():
    """Точка входа."""
    parser = argparse.ArgumentParser(
        description="MassReg — массовая регистрация аккаунтов"
    )
    parser.add_argument("--check", action="store_true",
                        help="Проверить настройки и выйти")
    parser.add_argument("--config", default="config.yaml",
                        help="Путь к файлу конфигурации")
    args = parser.parse_args()

    banner()

    # Загрузка конфига
    try:
        config = Config(args.config)
    except FileNotFoundError:
        log.error(f"Файл {args.config} не найден.")
        log.error("Создайте config.yaml на основе шаблона.")
        sys.exit(1)

    # Проверка
    if args.check:
        ok = check_setup(config)
        sys.exit(0 if ok else 1)

    # Запуск
    if not check_setup(config):
        log.error("Конфигурация неверна. Запустите с --check для диагностики.")
        sys.exit(1)

    worker = Worker(config)

    try:
        worker.run()
    except KeyboardInterrupt:
        log.warning("Прервано пользователем (Ctrl+C)")
        worker.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()