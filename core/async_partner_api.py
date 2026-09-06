"""
Асинхронная обёртка над PartnerAPI.

Позволяет использовать синхронный PartnerAPI в асинхронном воркере
через asyncio.to_thread(), чтобы не блокировать event loop.
"""

import asyncio
from typing import Optional, Dict, List, Any

from .partner_api import PartnerAPI


class AsyncPartnerAPI:
    """
    Асинхронная обёртка над PartnerAPI.

    Все методы выполняются в потоке через asyncio.to_thread(),
    но интерфейс остаётся полностью совместимым с MicrosoftRegistrator.

    Пример:
        async with AsyncPartnerAPI(api_key, base_url=...) as sms:
            balance = await sms.get_balance()
            number = await sms.rent_number(service="Microsoft")
            code = await sms.wait_code(activation_id)
    """

    def __init__(
            self,
            api_key: str,
            base_url: Optional[str] = None,
            service: str = "Microsoft",
            country: str = "all",
            max_price: float = 0,
            timeout: int = 30,
            proxy_manager=None,
            verify_ssl: bool = False,
    ):
        self._sync_api = PartnerAPI(
            api_key=api_key,
            base_url=base_url,
            service=service,
            country=country,
            max_price=max_price,
            timeout=timeout,
            proxy_manager=proxy_manager,
            verify_ssl=verify_ssl,
        )

    # ============================================
    # КОНТЕКСТНЫЙ МЕНЕДЖЕР
    # ============================================

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass  # PartnerAPI не требует очистки

    # ============================================
    # ВСПОМОГАТЕЛЬНЫЕ
    # ============================================

    def _run(self, method, *args, **kwargs):
        """Запустить синхронный метод в потоке."""
        return asyncio.get_event_loop().run_in_executor(None, method, *args, **kwargs)

    # ============================================
    # БАЛАНС
    # ============================================

    async def get_balance(self) -> Optional[Dict[str, float]]:
        """Получить баланс аккаунта."""
        return await self._run(self._sync_api.get_balance)

    # ============================================
    # СЕРВИСЫ
    # ============================================

    async def get_services(self) -> Optional[List[Dict]]:
        """Получить список доступных сервисов."""
        return await self._run(self._sync_api.get_services)

    async def get_rate(self, code: str) -> Optional[List[Dict]]:
        """Получить ставки по коду сервиса."""
        return await self._run(self._sync_api.get_rate, code)

    # ============================================
    # АРЕНДА НОМЕРА
    # ============================================

    async def rent_number(
            self,
            service: Optional[str] = None,
            country: Optional[str] = None,
            max_price: Optional[float] = None,
            operator: Optional[str] = None,
            max_retries: int = 3,
    ) -> Optional[Dict[str, str]]:
        """Арендовать номер (совместимо с PartnerAPI.rent_number)."""
        return await self._run(
            self._sync_api.rent_number,
            service, country, max_price, operator, max_retries,
        )

    async def get_number(
            self,
            service: str,
            country=None,
            operator: Optional[str] = None,
            extra_fields: Optional[dict] = None,
    ) -> Optional[Dict]:
        """Низкоуровневая аренда номера."""
        return await self._run(
            self._sync_api.get_number,
            service, country, operator, extra_fields,
        )

    async def get_numbers(self, requests: List[Dict]) -> Optional[List[Dict]]:
        """Массовая аренда номеров."""
        return await self._run(self._sync_api.get_numbers, requests)

    # ============================================
    # СТАТУС / КОД
    # ============================================

    async def get_status(self, activation_id: str) -> Optional[Dict]:
        """Получить статус активации."""
        return await self._run(self._sync_api.get_status, activation_id)

    async def wait_code(
            self,
            activation_id: str,
            timeout: int = 300,
            poll_interval: int = 5,
    ) -> Optional[str]:
        """Дождаться SMS-кода."""
        return await self._run(
            self._sync_api.wait_code,
            activation_id, timeout, poll_interval,
        )

    async def get_code_immediate(self, activation_id: str) -> Optional[str]:
        """Проверить код один раз."""
        return await self._run(self._sync_api.get_code_immediate, activation_id)

    # ============================================
    # УПРАВЛЕНИЕ АКТИВАЦИЕЙ
    # ============================================

    async def set_status(self, activation_id: str, status_code: int) -> bool:
        """Изменить статус активации."""
        return await self._run(
            self._sync_api.set_status, activation_id, status_code,
        )

    async def confirm(self, activation_id: str):
        """Подтвердить успешную активацию."""
        await self._run(self._sync_api.confirm, activation_id)

    async def cancel(self, activation_id: str):
        """Отменить аренду."""
        await self._run(self._sync_api.cancel, activation_id)

    async def report_bad_number(self, activation_id: str):
        """Пожаловаться на номер."""
        await self._run(self._sync_api.report_bad_number, activation_id)

    # ============================================
    # АКТИВАЦИЯ СУЩЕСТВУЮЩЕГО НОМЕРА
    # ============================================

    async def activate_number(
            self,
            service: str,
            number: str,
            country: Optional[str] = None,
            operator: Optional[str] = None,
            any_key: Optional[str] = None,
    ) -> Optional[Dict]:
        """Активировать имеющийся номер."""
        return await self._run(
            self._sync_api.activate_number,
            service, number, country, operator, any_key,
        )

    # ============================================
    # СТАТИСТИКА
    # ============================================

    async def get_active_activations(self) -> List[Dict]:
        """Получить список активных активаций."""
        return await self._run(self._sync_api.get_active_activations)

    # ============================================
    # ПЕРЕИНИЦИАЛИЗАЦИЯ (для ротации прокси / смены настроек)
    # ============================================

    def reset(self, **kwargs):
        """Пересоздать синхронный API с новыми параметрами."""
        if kwargs:
            self._sync_api = PartnerAPI(
                api_key=self._sync_api.api_key,
                base_url=kwargs.get("base_url", self._sync_api.base_url),
                service=kwargs.get("service", self._sync_api.service),
                country=kwargs.get("country", self._sync_api.country),
                max_price=kwargs.get("max_price", self._sync_api.max_price),
                timeout=kwargs.get("timeout", self._sync_api.timeout),
                proxy_manager=kwargs.get("proxy_manager", self._sync_api.proxy_manager),
                verify_ssl=kwargs.get("verify_ssl", self._sync_api.verify_ssl),
            )
