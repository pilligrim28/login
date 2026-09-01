import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Callable

from core.logger import log
from core.config import Config
from core.database import Database
from core.partner_api import PartnerAPI
from core.proxy_manager import ProxyManager
from core.services import get_registrator
from core.ml_model import get_model, record_to_features, find_opportunities


class Worker:
    """Воркер для массовой регистрации."""

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config)
        self.proxy_manager = ProxyManager(config)
        api_key = config.get("sms.api_key", "")
        base_url = config.get("sms.partner_url", "")
        service = config.get("sms.service", "Microsoft")
        country = config.get("sms.country", "all")
        max_price = config.get("sms.max_price", 0)
        self.sms = PartnerAPI(
            api_key,
            base_url=base_url or None,
            service=service,
            country=country,
            max_price=max_price,
            proxy_manager=self.proxy_manager
        )

        # Список сервисов для регистрации (ротация).
        services = config.get("sms.services", [])
        if isinstance(services, str):
            services = [s.strip() for s in services.split(",") if s.strip()]
        self.services = [s for s in services if s] or [service]

        # Для остановки
        self._stop_flag = threading.Event()

        # Колбэки (для GUI)
        self.on_progress = None  # (done, total, success, failed)
        self.on_account = None  # (account_dict)
        self.on_log = None  # (message)
        self.on_finished = None  # ()

    def stop(self):
        """Остановить регистрацию."""
        self._stop_flag.set()
        log.warning("Остановка запрошена...")

    def run(self):
        """Запустить регистрацию (блокирующий вызов)."""
        self._stop_flag.clear()

        total = self.config.get("worker.total_registrations", 100)
        threads = self.config.get("worker.threads", 10)

        log.info(f"Запуск: {total} регистраций, {threads} потоков")

        # Проверка баланса
        balance = self.sms.get_balance()
        if balance is not None:
            usd = balance.get("usd", 0.0)
            limit = balance.get("limit", 0.0)
            log.info(f"Баланс Partner API: ${usd:.4f} (лимит ${limit:.4f})")
        else:
            log.error("Не удалось получить баланс")
            if self.on_finished:
                self.on_finished()
            return

        # Обучение ML-модели на истории попыток и подсказка возможностей.
        self._train_and_suggest()

        success_count = 0
        fail_count = 0
        done_count = 0

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = []
            for i in range(total):
                if self._stop_flag.is_set():
                    break
                future = executor.submit(self._register_one, i + 1, total)
                futures.append(future)

            for future in as_completed(futures):
                if self._stop_flag.is_set():
                    break

                result = future.result()
                done_count += 1

                if result:
                    success_count += 1
                else:
                    fail_count += 1

                # Колбэк прогресса
                if self.on_progress:
                    try:
                        self.on_progress(done_count, total, success_count, fail_count)
                    except Exception:
                        pass

                if done_count % 10 == 0 or done_count == total:
                    log.info(f"Прогресс: {done_count}/{total} "
                             f"(успех: {success_count}, неудача: {fail_count})")

        log.success(f"=== ЗАВЕРШЕНО: {success_count}/{total} успешно ===")

        if self.on_finished:
            try:
                self.on_finished()
            except Exception:
                pass

    def _train_and_suggest(self):
        """
        Обучить ML-модель на истории попыток и вывести лучшие комбинации
        параметров («возможности»), которые чаще дают успешную регистрацию.
        """
        try:
            enabled = self.config.get("ml.enabled", True)
            if not enabled:
                return

            min_samples = int(self.config.get("ml.min_samples", 10) or 0)
            attempts = self.db.get_attempts()
            if len(attempts) < min_samples:
                log.info(
                    f"ML: недостаточно данных ({len(attempts)}/{min_samples}) "
                    "для обучения — модель пропущена"
                )
                return

            model = get_model(self.config)
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
        except Exception as e:
            log.warning(f"ML: не удалось обучить модель: {e}")

    def _register_one(self, index: int, total: int) -> Optional[Dict]:
        """Один аккаунт (в потоке)."""
        if self._stop_flag.is_set():
            return None

        # Ротация сервисов: каждый следующий аккаунт — следующий сервис.
        service_name = self.services[(index - 1) % len(self.services)]

        try:
            registrator = get_registrator(
                service_name,
                sms=self.sms,
                db=self.db,
                proxy_manager=self.proxy_manager,
                config=self.config,
                on_status=lambda status, data: self._handle_status(index, total, status, data),
                on_log=lambda msg: self._handle_log(msg)
            )
        except ValueError as e:
            log.error(str(e))
            return None

        result = asyncio.run(registrator.register())

        # Колбэк аккаунта
        if self.on_account:
            try:
                self.on_account({
                    "index": index,
                    "result": result
                })
            except Exception:
                pass

        return result

    def _handle_status(self, index, total, status, data):
        """Обработка статуса."""
        if self.on_log:
            email = data.get("email", "")
            if status == "success":
                self.on_log(f"[{index}/{total}] ✅ {email}")
            elif status == "failed":
                self.on_log(f"[{index}/{total}] ❌ {email}: {data.get('error', '')}")
            elif status == "starting":
                self.on_log(f"[{index}/{total}] ▶️ Начало: {email}")

    def _handle_log(self, message: str):
        """Передать лог в GUI."""
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass