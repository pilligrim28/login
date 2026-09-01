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
from core.partner_api import PartnerAPI
from core.proxy_manager import ProxyManager
from workers.worker import Worker


def banner():
    """Вывести баннер."""
    print("""
    ╔══════════════════════════════════════════════╗
    ║           MassReg v0.1 — Пилотный запуск       ║
    ║       Массовая регистрация аккаунтов           ║
    ║  Microsoft • Google • Apple • Snapchat и др.   ║
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
    base_url = config.get("sms.partner_url", "")
    sms = PartnerAPI(api_key, base_url=base_url or None, proxy_manager=pm)
    balance = sms.get_balance()
    if balance is not None:
        usd = balance.get("usd", 0.0)
        limit = balance.get("limit", 0.0)
        log.success(f"Баланс Partner API: ${usd:.4f} (лимит ${limit:.4f})")
        estimated = usd / 0.05  # ~$0.05 за номер (Microsoft)
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
    services = config.get("sms.services", []) or [config.get("sms.service", "Microsoft")]
    log.info(f"Параметры: {total} регистраций, {threads} потоков")
    log.info(f"Сервисы: {', '.join(services)}")

    log.success("=== Конфигурация OK ===")
    return True


def ml_suggest(config: Config):
    """Обучить ML-модель на истории попыток и показать топ возможностей."""
    from core.ml_model import get_model, record_to_features, find_opportunities

    db = Database(config)
    attempts = db.get_attempts()
    if not attempts:
        log.warning("Нет истории попыток — модель не на чем обучать.")
        return

    model = get_model(config)
    model.fit([(record_to_features(a), int(a.get("success", 0))) for a in attempts])
    model.save()

    log.success(f"ML-модель обучена на {len(attempts)} попытках.")
    opportunities = find_opportunities(model, attempts, top_k=10)
    log.info("Топ возможностей (вероятность успеха):")
    for proba, opts in opportunities:
        log.info(
            f"  {proba * 100:5.1f}%  {opts.get('service') or '?'} / "
            f"{opts.get('country') or '?'}"
        )


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

    # ML: показать топ возможностей
    if args.ml_suggest:
        ml_suggest(config)
        sys.exit(0)

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