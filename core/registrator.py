"""
Реестр регистраторов аккаунтов (синхронная обёртка).
Каждый регистратор — обёртка над асинхронной логикой из `registrator_async.py`.
Метод `register()` возвращает `asyncio.run(...)` для запуска в потоке.
"""
import asyncio
from typing import Optional, Dict, Callable
from .logger import log
from .proxy_manager import ProxyManager
from .database import Database
from .async_partner_api import AsyncPartnerAPI
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
        partner_url = self.config.get("sms.partner_url", None)
        service = self.config.get("sms.service", self.SERVICE_NAME)
        country = self.config.get("sms.country", "all")
        max_price = self.config.get("sms.max_price", 0)
        timeout = getattr(self.sms, "timeout", 30)
        
        # 🔥 Цикл попыток с получением нового прокси на каждой итерации
        max_retries = self.config.get("worker.number_retries", 3)
        
        for attempt in range(max_retries):
            # 🔥 Получаем свежий прокси на каждую попытку
            proxy = self.proxy_manager.get_next()
            proxy_str = f"{proxy['server']}" if proxy else "direct"
            
            self._callback_log(f"🌐 Попытка {attempt + 1}/{max_retries} | IP: {proxy_str}")
            
            sms_async = AsyncPartnerAPI(
                api_key=api_key,
                base_url=partner_url,
                service=service,
                country=country,
                max_price=max_price,
                timeout=timeout,
                proxy_manager=self.proxy_manager,
            )
            
            async with sms_async as sms_client:
                reg = AsyncMicrosoftRegistrator(
                    sms=sms_client,
                    db=self.db,
                    proxy_manager=self.proxy_manager,
                    config=self.config,
                    on_status=self._callback_status,
                    on_log=self._callback_log,
                )
                # 🔥 Передаём прокси явно, без фиксации
                result = await reg.register(proxy=proxy)
                
                if result:
                    return result
                
                # Если регистрация не удалась — пробуем снова с новым прокси
                self._callback_log(f"↻ Попытка {attempt + 1} не удалась, пробуем снова...")
        
        self._callback_log(f"❌ Все {max_retries} попыток исчерпаны")
        return None


class SnapchatRegistrator(BaseRegistrator):
    """Регистрация Snapchat."""
    SERVICE_NAME = "Snapchat"
    SMS_CODE = "fu"  # 🔥 Исправлено: было "sc"