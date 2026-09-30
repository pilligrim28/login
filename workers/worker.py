"""
Воркер массовой регистрации (единый, асинхронный).

Один цикл событий + asyncio.Semaphore для ограничения параллельности:
никаких ThreadPoolExecutor / asyncio.run на каждый поток — именно из-за
такой смеси раньше возникали ошибки "'dict' object can't be awaited" и
"Lock is bound to a different event loop".

Логика одна и для CLI-вывода, и для Textual TUI: Worker(config).run().
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Dict, List, Optional

from core.logger import log
from core.config import Config
from core.database import Database
from core.proxy_manager import ProxyManager
from core.services import get_registrator


def create_sms_client(config: Config, proxy_manager: ProxyManager):
    """Создать SMS-клиент по конфигурации.

    Предпочтение — Partner REST API (SMS__PARTNER_URL), иначе —
    SMS-Activate (SMS__API_URL). Возвращается СИНХРОННЫЙ клиент:
    MicrosoftRegistrator сам прозрачно оборачивает его в AsyncSMSWrapper
    (core/async_compat.py), поэтому await-интерфейс ядра не ломается.
    """
    api_key = str(config.get("sms.api_key", "") or "")
    partner_url = str(config.get("sms.partner_url", "") or "")
    api_url = str(config.get("sms.api_url", "") or "")
    service = config.get("sms.service", "Microsoft")
    country = config.get("sms.country", "all")
    max_price = config.get("sms.max_price", 0)
    timeout = config.get("sms.timeout", 30)

    if partner_url:
        from core.partner_api import PartnerAPI
        return PartnerAPI(
            api_key,
            base_url=partner_url,
            service=service,
            country=country,
            max_price=max_price,
            timeout=timeout,
            proxy_manager=proxy_manager,
        )
    from core.sms import SMSActivate
    return SMSActivate(
        api_key,
        service=service,
        country=country,
        max_price=max_price,
        timeout=timeout,
        proxy_manager=proxy_manager,
        base_url=api_url or None,
    )


class Worker:
    """Асинхронный воркер: N параллельных регистраций, лимит total."""

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config)
        self.proxy_manager = ProxyManager(config)
        self.sms = create_sms_client(config, self.proxy_manager)

        # Параметры
        self.total = int(config.get("worker.total_registrations", 100) or 100)
        self.concurrency = int(
            config.get("worker.max_concurrency", None)
            or config.get("worker.threads", 10)
            or 10
        )
        self.min_balance = float(config.get("worker.min_balance", 20) or 0)
        self.services = self._load_services()

        self._stop_flag = False
        self._task: Optional[asyncio.Task] = None

        # Статистика
        self.done = 0
        self.success = 0
        self.failed = 0

        # Колбэки (используются TUI; в plain-режиме не обязательны)
        self.on_progress: Optional[Callable[[int, int, int, int], None]] = None
        self.on_account: Optional[Callable[[Dict], None]] = None
        self.on_finished: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------
    def _load_services(self) -> List[str]:
        services = self.config.get("sms.services", [])
        if isinstance(services, str):
            services = [s.strip() for s in services.split(",") if s.strip()]
        services = [s for s in (services or []) if s]
        return services or [str(self.config.get("sms.service", "Microsoft"))]

    def stop(self) -> None:
        """Запросить остановку (безопасно вызывать из любого потока)."""
        self._stop_flag = True
        log.warning("⏹ Остановка запрошена...")

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    async def run(self) -> Dict[str, int]:
        """Выполнить `total` регистраций с параллельностью `concurrency`.

        Блокирует вызывающую корутину до завершения всей работы.
        Возвращает итоговую статистику {done, total, success, failed}.
        """
        self._stop_flag = False
        self.done = self.success = self.failed = 0
        start_ts = time.time()

        log.info(f"Запуск: {self.total} регистраций, параллельность {self.concurrency}")
        log.info(f"Сервисы: {', '.join(self.services)}")

        # Баланс (ошибочный ответ не роняет запуск — только предупреждение)
        try:
            balance = await self._get_balance()
            self._log_balance(balance)
        except Exception as exc:
            log.warning(f"Не удалось проверить баланс: {exc}")

        semaphore = asyncio.Semaphore(self.concurrency)
        tasks = [
            asyncio.create_task(self._register_one(i + 1, semaphore))
            for i in range(self.total)
        ]
        self._task = asyncio.gather(*tasks, return_exceptions=True)
        try:
            results = await self._task
        except asyncio.CancelledError:
            log.warning("Регистрации отменены")
            results = []
        finally:
            self._task = None

        # Подсчёт по результатам задач (страховка: _register_one сам всё считает)
        elapsed = time.time() - start_ts
        log.success(
            f"=== Завершено: {self.success}/{self.total} успешно "
            f"(неудач: {self.failed}, время {elapsed:.0f} c) ==="
        )
        if self.on_finished:
            try:
                self.on_finished()
            except Exception:
                pass
        return {"done": self.done, "total": self.total,
                "success": self.success, "failed": self.failed}

    # ------------------------------------------------------------------
    async def _get_balance(self):
        """Получить баланс через ядро (sync-клиент прозрачно awaits-обёрнут)."""
        from core.async_compat import AsyncSMSWrapper
        sms = self.sms
        rent = getattr(sms, "rent_number", None)
        if not (asyncio.iscoroutinefunction(rent)):
            sms = AsyncSMSWrapper(sms)
        return await sms.get_balance()

    def _log_balance(self, balance) -> None:
        if isinstance(balance, dict):
            usd = float(balance.get("usd", 0) or 0)
            limit = float(balance.get("limit", 0) or 0)
            log.info(f"Баланс Partner API: ${usd:.4f} (лимит ${limit:.4f})")
            if usd <= 0:
                log.error("💸 Баланс исчерпан — регистрации завернутся ошибкой.")
        elif balance is not None:
            try:
                rub = float(balance)
                log.info(f"Баланс SMS-API: {rub:.2f} ₽")
                if self.min_balance and rub < self.min_balance:
                    log.warning(f"⚠️ Баланс ниже минимума WORKER__MIN_BALANCE={self.min_balance}")
            except (TypeError, ValueError):
                log.warning(f"Не удалось разобрать баланс: {balance}")

    # ------------------------------------------------------------------
    async def _register_one(self, index: int, semaphore: asyncio.Semaphore) -> Optional[Dict]:
        """Зарегистрировать один аккаунт (под семафором)."""
        if self._stop_flag:
            return None
        async with semaphore:
            if self._stop_flag:
                return None

            service = self.services[(index - 1) % len(self.services)]

            def on_status(status: str, data: dict) -> None:
                email = (data or {}).get("email", "")
                if status == "starting":
                    log.info(f"[{index}/{self.total}] ▶️ Начало: {email}")
                elif status == "success":
                    log.info(f"[{index}/{self.total}] ✅ {email}")
                elif status == "failed":
                    log.info(f"[{index}/{self.total}] ❌ {email}: {(data or {}).get('error', '')}")

            try:
                registrator = get_registrator(
                    service_name=service,
                    sms=self.sms,
                    db=self.db,
                    proxy_manager=self.proxy_manager,
                    config=self.config,
                    on_status=on_status,
                    on_log=lambda msg: log.info(msg),
                )
                result = await registrator.register()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error(f"❌ [{index}/{self.total}] Исключение: {exc}")
                result = None

            self.done += 1
            if result:
                self.success += 1
            else:
                self.failed += 1

            if self.on_progress:
                try:
                    self.on_progress(self.done, self.total, self.success, self.failed)
                except Exception:
                    pass
            if self.on_account:
                try:
                    self.on_account({"index": index, "result": result})
                except Exception:
                    pass
            return result
