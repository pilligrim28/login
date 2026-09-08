"""
Реестр регистраторов аккаунтов (синхронная обёртка).

Каждый регистратор — обёртка над асинхронной логикой из ``registrator_async.py``.
Метод ``register()`` возвращает ``asyncio.run(...)`` для запуска в потоке.
"""

import asyncio
from typing import Optional, Dict, Callable

from .logger import log
from .proxy_manager import ProxyManager
from .database import Database
from .sms_async import AsyncSMSActivate
from .registrator_async import AsyncMicrosoftRegistrator


class BaseRegistrator:
    """Базовый класс регистратора."""

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

    async def register(self) -> Optional[Dict]:
        raise NotImplementedError


class MicrosoftRegistrator(BaseRegistrator):
    """Регистрация Microsoft (Outlook)."""

    SMS_CODE = "mm"
    SERVICE_NAME = "Microsoft"

    async def register(self) -> Optional[Dict]:
        api_key = getattr(self.sms, "api_key", "")
        api_url = self.config.get("sms.api_url", None)
        timeout = getattr(self.sms, "timeout", 30)

        sms_async = AsyncSMSActivate(
            api_key=api_key,
            base_url=api_url,
            timeout=timeout,
        )

        proxy = self.proxy_manager.get_next()

        async with sms_async as sms_client:
            reg = AsyncMicrosoftRegistrator(
                sms=sms_client,
                db=self.db,
                proxy_manager=self.proxy_manager,
                config=self.config,
                on_status=self._callback_status,
                on_log=self._callback_log,
            )
            reg.proxy_manager.get_next = lambda: proxy
            return await reg.register()


class SnapchatRegistrator(BaseRegistrator):
    SERVICE_NAME = "Snapchat"
    SMS_CODE = "fu"
