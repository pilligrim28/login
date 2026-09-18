"""
Async registrator wrapper for use with AsyncPartnerAPI.

MicrosoftAsyncRegistrator mirrors MicrosoftRegistrator (sync) but works
directly with AsyncSMSActivate + AsyncMicrosoftRegistrator so it can be
awaited inside the AsyncWorker event loop without spinning up another
thread or calling asyncio.run().
"""

import asyncio
from typing import Optional, Dict, Callable

from .logger import log
from .proxy_manager import ProxyManager
from .database import Database
from .sms_async import AsyncSMSActivate
from .registrator_async import AsyncMicrosoftRegistrator


class MicrosoftAsyncRegistrator:
    """
    Обёртка над AsyncMicrosoftRegistrator для работы внутри
    уже запущенного event loop (AsyncWorker).

    Принимает уже открытый AsyncSMSActivate (или любой совместимый
    клиент с интерфейсами rent_number / wait_code / confirm / cancel)
    и переиспользует его вместо создания нового.
    """

    SMS_CODE = "mm"
    SERVICE_NAME = "Microsoft"

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
        """
        Выполнить регистрацию, переиспользуя переданный self.sms.
        """
        proxy = self.proxy_manager.get_next()

        reg = AsyncMicrosoftRegistrator(
            sms=self.sms,
            db=self.db,
            proxy_manager=self.proxy_manager,
            config=self.config,
            on_status=self._callback_status,
            on_log=self._callback_log,
        )
        # Фиксируем прокси
        reg.proxy_manager.get_next = lambda: proxy

        try:
            async with reg:
                return await reg.register()
        except Exception as e:
            log.error(f"Ошибка в MicrosoftAsyncRegistrator: {e}")
            return None
