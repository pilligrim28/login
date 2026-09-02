"""
Асинхронный воркер для массовой регистрации аккаунтов.
Использует asyncio для параллельной работы.
"""

import asyncio
import threading
from typing import Optional, Dict, Callable, List

from core.logger import log
from core.config import Config
from core.database import Database
from core.sms_async import AsyncSMSActivate
from core.proxy_manager import ProxyManager
from core.registrator import MicrosoftRegistrator


class AsyncWorker:
    """
    Асинхронный воркер для регистрации аккаунтов.
    
    Использует asyncio.gather для параллельной работы.
    """

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config)
        self.proxy_manager = ProxyManager(config)
        
        api_key = config.get("sms.api_key", "")
        base_url = config.get("sms.api_url", "")
        service = config.get("sms.service", "Microsoft")
        country = config.get("sms.country", "all")
        max_price = config.get("sms.max_price", 0)
        
        self.api_key = api_key
        self.base_url = base_url
        self.service = service
        self.country = country
        self.max_price = max_price

        # Для остановки
        self._stop_flag = False
        self._lock = asyncio.Lock()

        # Колбэки
        self.on_progress = None
        self.on_account = None
        self.on_log = None
        self.on_finished = None

    def stop(self):
        """Остановить регистрацию."""
        self._stop_flag = True
        log.warning("Остановка запрошена...")

    async def run(self):
        """
        Запустить асинхронную регистрацию.
        """
        self._stop_flag = False

        total = self.config.get("worker.total_registrations", 100)
        concurrency = self.config.get("worker.threads", 10)

        log.info(f"Запуск: {total} регистраций, {concurrency} одновременно")

        # Проверка баланса
        async with AsyncSMSActivate(
            api_key=self.api_key,
            base_url=self.base_url or None,
            service=self.service,
            country=self.country,
            max_price=self.max_price
        ) as sms:
            balance = await sms.get_balance()
            if balance is not None:
                log.info(f"Баланс SMS-Activate: {balance} ₽")
            else:
                log.error("Не удалось получить баланс")
                if self.on_finished:
                    self.on_finished()
                return

            min_balance_per_registration = 20
            
            if balance is not None and balance < min_balance_per_registration:
                log.error(f"Недостаточно средств: {balance:.2f}₽ (нужно минимум {min_balance_per_registration}₽)")
                if self.on_finished:
                    self.on_finished()
                return

            # Создаем задачи
            tasks = []
            for i in range(min(total, concurrency)):
                if self._stop_flag:
                    break
                task = asyncio.create_task(self._register_one(i + 1, total, sms))
                tasks.append(task)

            # Обрабатываем результаты
            success_count = 0
            fail_count = 0
            done_count = 0

            while tasks and not self._stop_flag:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                
                for task in done:
                    result = task.result()
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
                    
                    # Добавляем новую задачу если есть что регистрировать
                    if done_count + len(pending) < total:
                        new_index = done_count + len(pending) + 1
                        new_task = asyncio.create_task(self._register_one(new_index, total, sms))
                        pending.add(new_task)
                
                tasks = list(pending)

            # Ждем завершения всех задач
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        log.success(f"=== Завершено: {success_count}/{total} успешно ===")

        if self.on_finished:
            try:
                self.on_finished()
            except Exception:
                pass

    async def _register_one(self, index: int, total: int, sms: AsyncSMSActivate) -> Optional[Dict]:
        """
        Зарегистрировать один аккаунт.
        """
        if self._stop_flag:
            return None

        # Проверка баланса
        balance = await sms.get_balance()
        if balance is None:
            log.error("Не удалось проверить баланс SMS-Activate")
            return None

        min_balance = 20
        if balance < min_balance:
            log.warning(f"Недостаточно средств: {balance:.2f}₽")
            return None

        # Создаем регистратор с асинхронным SMS
        registrator = MicrosoftRegistrator(
            sms=sms,
            db=self.db,
            proxy_manager=self.proxy_manager,
            config=self.config,
            on_status=lambda status, data: self._handle_status(index, total, status, data),
            on_log=lambda msg: self._handle_log(msg)
        )

        result = await registrator.register()

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
        """Передача лога в GUI."""
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass
