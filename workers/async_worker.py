"""
Асинхронный воркер для круглосуточной массовой регистрации.

Работает бесконечно, пока:
- Есть деньги на балансе SMS-провайдера
- Есть рабочие прокси

Использует asyncio.Semaphore для контроля параллельности.
"""

import asyncio
import time
from typing import Optional, Dict, Callable, List

from core.logger import log
from core.config import Config
from core.database import Database
from core.proxy_manager import ProxyManager
from core.async_partner_api import AsyncPartnerAPI
from core.services import get_registrator
from core.registrator import MicrosoftRegistrator


class AsyncWorker:
    """
    Асинхронный воркер для круглосуточной регистрации.

    Работает в бесконечном цикле:
    1. Проверяет баланс — если < минимума, ждёт или останавливается
    2. Проверяет прокси — если нет рабочих, ждёт или останавливается
    3. Запускает N параллельных регистраций
    4. Повторяет
    """

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config)
        self.proxy_manager = ProxyManager(config)

        # Параметры
        self.api_key = config.get("sms.api_key", "")
        self.partner_url = config.get("sms.partner_url", "")
        self.base_url = config.get("sms.api_url", "")
        self.min_balance = float(config.get("worker.min_balance", 20))
        self.max_concurrency = int(config.get("worker.threads", 10))
        self.services = self._load_services()

        # Для остановки
        self._stop_flag = False
        self._paused = False
        self._lock = asyncio.Lock()

        # Статистика
        self._total_started = 0
        self._total_success = 0
        self._total_failed = 0
        self._total_skipped_no_balance = 0
        self._total_skipped_no_proxy = 0

        # Колбэки
        self.on_progress = None
        self.on_account = None
        self.on_log = None
        self.on_finished = None

    def _load_services(self) -> List[str]:
        """Загрузить список сервисов для ротации."""
        services = self.config.get("sms.services", [])
        if isinstance(services, str):
            services = [s.strip() for s in services.split(",") if s.strip()]
        if not services:
            default = self.config.get("sms.service", "Microsoft")
            services = [default]
        return services

    def stop(self):
        """Остановить воркер."""
        self._stop_flag = True
        log.warning("⏹ Остановка запрошена...")

    def pause(self):
        """Поставить на паузу."""
        self._paused = True
        log.info("⏸ Пауза")

    def resume(self):
        """Снять с паузы."""
        self._paused = False
        log.info("▶️ Продолжено")

    async def run(self):
        """
        Запустить бесконечный цикл регистрации.

        Работает пока:
        - self._stop_flag == False
        - Есть баланс >= min_balance
        - Есть рабочие прокси
        """
        self._stop_flag = False
        self._paused = False

        log.info("=" * 60)
        log.info("🚀 AsyncWorker запущен (бесконечный режим)")
        log.info(f"   Сервисы: {', '.join(self.services)}")
        log.info(f"   Параллельность: {self.max_concurrency}")
        log.info(f"   Мин. баланс: {self.min_balance}₽")
        log.info("=" * 60)

        # Создаём AsyncPartnerAPI
        async with AsyncPartnerAPI(
            api_key=self.api_key,
            base_url=self.partner_url or self.base_url or None,
            service=self.services[0] if self.services else "Microsoft",
            proxy_manager=self.proxy_manager,
        ) as sms:
            while not self._stop_flag:
                # --- Пауза ---
                while self._paused and not self._stop_flag:
                    await asyncio.sleep(2)

                if self._stop_flag:
                    break

                # --- Проверка баланса ---
                try:
                    balance_data = await sms.get_balance()
                except Exception as e:
                    log.error(f"Ошибка проверки баланса: {e}")
                    await asyncio.sleep(10)
                    continue

                if balance_data is None:
                    log.error("Не удалось получить баланс, ждём 30 сек...")
                    await asyncio.sleep(30)
                    continue

                usd = balance_data.get("usd", 0)
                rubles = usd * 90  # приблизительный курс USD→RUB

                log.info(f"💰 Баланс: {usd:.2f} USD (~{rubles:.0f} RUB)")

                if rubles < self.min_balance:
                    log.warning(
                        f"⚠️ Баланс ниже минимума ({rubles:.0f} < {self.min_balance}₽)"
                    )
                    self._total_skipped_no_balance += 1

                    # Если баланс 0 — останавливаемся
                    if usd <= 0:
                        log.error("💸 Баланс исчерпан. Остановка.")
                        break

                    # Ждём пополнения
                    log.info("⏳ Ожидание пополнения баланса (60 сек)...")
                    await asyncio.sleep(60)
                    continue

                # --- Проверка прокси ---
                if not self.proxy_manager.has_proxies():
                    log.error("❌ Нет доступных прокси")
                    self._total_skipped_no_proxy += 1
                    log.info("⏳ Ожидание прокси (60 сек)...")
                    await asyncio.sleep(60)
                    continue

                alive = self.proxy_manager.alive_count()
                total = self.proxy_manager.count()
                log.info(f"🌐 Прокси: {alive}/{total} живых")

                if alive == 0:
                    log.warning("⚠️ Все прокси мёртвые, пробуем перезагрузку...")
                    self.proxy_manager.reload()
                    alive = self.proxy_manager.alive_count()

                    if alive == 0:
                        log.error("❌ Нет рабочих прокси после перезагрузки")
                        self._total_skipped_no_proxy += 1
                        await asyncio.sleep(60)
                        continue

                # --- Запуск пачки регистраций ---
                await self._run_batch(sms, balance_data)

    async def _run_batch(self, sms: AsyncPartnerAPI, balance_data: Dict):
        """
        Запустить пачку параллельных регистраций.

        Использует semaphore для контроля параллельности.
        Когда все задачи в пачке завершаются — цикл повторяется.
        """
        semaphore = asyncio.Semaphore(self.max_concurrency)
        tasks = []

        # Определяем размер пачки
        batch_size = self.max_concurrency

        log.info(f"📦 Запуск пачки: {batch_size} регистраций")

        for i in range(batch_size):
            task = asyncio.create_task(
                self._register_one(i + 1, sms, semaphore)
            )
            tasks.append(task)

        # Ждём завершения всех задач в пачке
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Считаем результаты
        success = 0
        failed = 0
        errors = 0

        for result in results:
            if isinstance(result, Exception):
                errors += 1
                log.error(f"Исключение в задаче: {result}")
            elif result is not None:
                success += 1
            else:
                failed += 1

        self._total_started += batch_size
        self._total_success += success
        self._total_failed += failed

        log.info(
            f"✅ Пачка завершена: "
            f"{success} успех | {failed} неудача | {errors} ошибка"
        )
        log.info(
            f"📊 Итого: {self._total_started} всего, "
            f"{self._total_success} успех, "
            f"{self._total_failed} неудача"
        )

        # Выводим статистику прокси
        stats = self.proxy_manager.get_stats()
        log.info(f"🌐 Статистика прокси: {stats}")

    async def _register_one(
            self, index: int, sms: AsyncPartnerAPI, semaphore: asyncio.Semaphore
    ) -> Optional[Dict]:
        """
        Зарегистрировать один аккаунт.

        Использует semaphore для ограничения параллельности.
        """
        async with semaphore:
            # Проверяем стоп-флаг
            if self._stop_flag:
                return None

            # Выбираем сервис (ротация)
            service = self.services[(index - 1) % len(self.services)]

            try:
                # Создаём регистратор
                registrator = get_registrator(
                    service_name=service,
                    sms=sms,
                    db=self.db,
                    proxy_manager=self.proxy_manager,
                    config=self.config,
                    on_status=lambda s, d: self._handle_status(index, s, d),
                    on_log=lambda msg: self._handle_log(msg),
                )

                # Запускаем регистрацию
                result = await registrator.register()

                # Колбэк аккаунта
                if self.on_account:
                    try:
                        self.on_account({
                            "index": index,
                            "result": result,
                        })
                    except Exception:
                        pass

                return result

            except Exception as e:
                log.error(f"❌ Ошибка регистрации [{index}]: {e}")
                if self.on_log:
                    self.on_log(f"[{index}] ❌ Ошибка: {e}")
                return None

    def _handle_status(self, index: int, status: str, data: dict):
        """Обработка статуса из регистратора."""
        if self.on_log:
            email = data.get("email", "")
            if status == "success":
                self.on_log(f"[{index}] ✅ {email}")
            elif status == "failed":
                self.on_log(f"[{index}] ❌ {email}: {data.get('error', '')}")
            elif status == "starting":
                self.on_log(f"[{index}] ▶️ Начало: {email}")
            elif status == "waiting_sms":
                phone = data.get("phone", "")
                self.on_log(f"[{index}] 📱 Ожидание SMS: {phone}")
            elif status == "renting_number":
                self.on_log(f"[{index}] 📞 Аренда номера...")

    def _handle_log(self, message: str):
        """Передача лога."""
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass

    def get_stats(self) -> Dict:
        """Получить статистику работы."""
        return {
            "total_started": self._total_started,
            "total_success": self._total_success,
            "total_failed": self._total_failed,
            "skipped_no_balance": self._total_skipped_no_balance,
            "skipped_no_proxy": self._total_skipped_no_proxy,
            "stop_flag": self._stop_flag,
            "paused": self._paused,
        }
