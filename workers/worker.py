import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Callable

from core.logger import log
from core.config import Config
from core.database import Database
from core.sms import SMSActivate
from core.proxy_manager import ProxyManager
from core.registrator import MicrosoftRegistrator


class Worker:
    """Воркер для массовой регистрации."""

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config)
        self.proxy_manager = ProxyManager(config)
        api_key = config.get("sms.api_key", "")
        service_code = config.get("sms.service_code", "op")
        country = config.get("sms.country", 0)
        self.sms = SMSActivate(api_key, service_code, country)

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
            log.info(f"Баланс SMS-Activate: {balance} ₽")
        else:
            log.error("Не удалось получить баланс")
            if self.on_finished:
                self.on_finished()
            return

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

    def _register_one(self, index: int, total: int) -> Optional[Dict]:
        """Один аккаунт (в потоке)."""
        if self._stop_flag.is_set():
            return None

        registrator = MicrosoftRegistrator(
            sms=self.sms,
            db=self.db,
            proxy_manager=self.proxy_manager,
            config=self.config,
            on_status=lambda status, data: self._handle_status(index, total, status, data),
            on_log=lambda msg: self._handle_log(msg)
        )

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