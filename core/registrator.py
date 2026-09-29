"""
Реестр регистраторов аккаунтов (единая точка входа для обоих режимов).

Здесь живут только ТОНКИЕ обёртки над асинхронным ядром из
`registrator_async.py`. Весь цикл попыток/прокси/регистрации реализован
в одном месте — в `AsyncMicrosoftRegistrator.register()`, поэтому между
синхронным (`workers/worker.py`) и асинхронным (`workers/async_worker.py`)
режимами нет расхождений и путаницы.
"""
from typing import Optional, Dict, Callable

from .database import Database
from .proxy_manager import ProxyManager
from .registrator_async import AsyncMicrosoftRegistrator


class BaseRegistrator:
    """Базовый класс регистратора (тонкая обёртка над async-ядром)."""
    SMS_CODE: Optional[str] = None
    SERVICE_NAME: str = "Unknown"

    def __init__(
        self,
        sms,
        db: Database,
        proxy_manager: ProxyManager,
        config,
        on_status: Optional[Callable] = None,
        on_log: Optional[Callable] = None,
    ):
        self.sms = sms
        self.db = db
        self.proxy_manager = proxy_manager
        self.config = config
        self.on_status = on_status
        self.on_log = on_log

    def _callback_status(self, status: str, data: dict = None):
        if self.on_status:
            try:
                self.on_status(status, data or {})
            except Exception:
                pass

    def _callback_log(self, message: str):
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass

    async def register(self, proxy: Optional[dict] = None) -> Optional[Dict]:
        raise NotImplementedError


class MicrosoftRegistrator(BaseRegistrator):
    """Регистрация Microsoft (Outlook).

    Полностью делегирует работу AsyncMicrosoftRegistrator: тот сам
    перебирает прокси и попытки (worker.retry_count), прокси можно не
    передавать — тогда он берёт их из пула сам.
    """
    SMS_CODE = "mm"
    SERVICE_NAME = "Microsoft"

    async def register(self, proxy: Optional[dict] = None) -> Optional[Dict]:
        reg = AsyncMicrosoftRegistrator(
            sms=self.sms,
            db=self.db,
            proxy_manager=self.proxy_manager,
            config=self.config,
            on_status=self._callback_status,
            on_log=self._callback_log,
        )
        async with reg:
            return await reg.register(proxy=proxy)


class SnapchatRegistrator(MicrosoftRegistrator):
    """Заглушка Snapchat (использует тот же поток регистрации Microsoft)."""
    SERVICE_NAME = "Snapchat"
    SMS_CODE = "fu"  # 🔥 Исправлено: было "sc"
