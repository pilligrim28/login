"""
Асинхронная обёртка над ЛЮБЫМ синхронным SMS-клиентом
(PartnerAPI / SMSActivate и совместимыми с ними).

Ядро регистрации (`AsyncMicrosoftRegistrator`) умеет работать только с
асинхронным интерфейсом: `await sms.rent_number()`, `await sms.wait_code()`
и т.д. Если в воркер передан синхронный клиент, его методы возвращают
обычные значения (dict / str / float), и `await` над ними падает с ошибкой
"'dict' object can't be awaited".

Этот модуль решает проблему один раз и для всех режимов: любой синхронный
клиент оборачивается в async-интерфейс, а все блокирующие вызовы выполняются
в пуле потоков через `asyncio.to_thread()`. Синхронные воркеры при этом не
меняются — им и так нужен синхронный интерфейс.
"""

import asyncio
import inspect
from typing import Any, Optional, Set

# Методы, которые ядро регистрации вызывает через await.
ASYNC_SMS_METHODS: Set[str] = {
    "get_balance",
    "get_countries",
    "get_services",
    "get_rate",
    "get_number",
    "get_numbers",
    "rent_number",
    "get_status",
    "get_statuses",
    "wait_code",
    "get_code_immediate",
    "set_status",
    "confirm",
    "cancel",
    "report_bad_number",
    "activate_number",
    "get_active_activations",
    "close",
}


class AsyncSMSWrapper:
    """
    Async-обёртка над синхронным SMS-клиентом.

    Все методы из ASYNC_SMS_METHODS становятся корутинами (выполняются в
    пуле потоков), остальные атрибуты пробрасываются к исходному объекту
    без изменений. Контекстный менеджер (`async with`) поддерживается.
    """

    def __init__(self, sync_client: Any):
        # Защита от двойного оборачивания.
        if isinstance(sync_client, AsyncSMSWrapper):
            raise TypeError("Клиент уже завёрнут в AsyncSMSWrapper")
        self._sync = sync_client

    @property
    def sync_client(self) -> Any:
        """Исходный синхронный клиент (для отладки/GUI)."""
        return self._sync

    async def __aenter__(self):
        aenter = getattr(self._sync, "__aenter__", None)
        if callable(aenter):
            return await aenter()
        enter = getattr(self._sync, "__enter__", None)
        if callable(enter):
            entered = enter()
            return entered if entered is not None else self
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        aexit = getattr(self._sync, "__aexit__", None)
        if callable(aexit):
            return await aexit(exc_type, exc_val, exc_tb)
        exit_ = getattr(self._sync, "__exit__", None)
        if callable(exit_):
            return bool(exit_(exc_type, exc_val, exc_tb))
        return False

    def _make_coro(self, name: str):
        sync_method = getattr(self._sync, name)

        async def runner(*args, **kwargs):
            return await asyncio.to_thread(sync_method, *args, **kwargs)

        runner.__name__ = name
        runner.__qualname__ = f"AsyncSMSWrapper.{name}"
        return runner

    def __getattr__(self, item: str) -> Any:
        # Вызывается только если атрибута нет у самой обёртки
        # (_sync и служебные поля определены в __init__).
        attr = getattr(self._sync, item)

        if item in ASYNC_SMS_METHODS and callable(attr):
            if inspect.iscoroutinefunction(attr):
                return attr  # уже асинхронный метод — не оборачиваем
            return self._make_coro(item)

        return attr
