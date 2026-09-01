"""
Реестр поддерживаемых сервисов регистрации и фабрика регистраторов.

Сопоставляет человекочитаемое имя сервиса с классом регистратора
(см. ``core/registrator.py``) и его кодом Partner API.
"""

from typing import Optional, Dict, Callable

from .registrator import (
    BaseRegistrator,
    MicrosoftRegistrator,
    GoogleRegistrator,
    AppleRegistrator,
    SnapchatRegistrator,
    InstagramRegistrator,
    FacebookRegistrator,
    DiscordRegistrator,
)


# Имя сервиса -> класс регистратора.
# Ключи соответствуют как ``sms.service``/``sms.services`` в config.yaml,
# так и коротким кодам Partner API (например ``wx`` для Apple).
REGISTRATORS: Dict[str, type] = {
    "Microsoft": MicrosoftRegistrator,
    "Outlook": MicrosoftRegistrator,
    "Google": GoogleRegistrator,
    "Gmail": GoogleRegistrator,
    "Apple": AppleRegistrator,
    "Snapchat": SnapchatRegistrator,
    "Instagram": InstagramRegistrator,
    "Facebook": FacebookRegistrator,
    "Discord": DiscordRegistrator,
}

# Короткий код Partner API -> класс регистратора.
REGISTRATORS_BY_CODE: Dict[str, type] = {
    cls.SMS_CODE: cls for cls in REGISTRATORS.values()
}


def get_registrator_class(service_name: str) -> Optional[type]:
    """
    Получить класс регистратора по имени сервиса или коду.

    Args:
        service_name: Имя сервиса (Microsoft, Google, ...) или код (mm, go, ...).

    Returns:
        Класс регистратора или None, если сервис не поддерживается.
    """
    if not service_name:
        return None
    key = str(service_name).strip()
    return (
        REGISTRATORS.get(key)
        or REGISTRATORS.get(key.capitalize())
        or REGISTRATORS_BY_CODE.get(key)
    )


# Канонические (отображаемые) имена сервисов в порядке для UI.
CANONICAL_SERVICES = [
    "Microsoft",
    "Google",
    "Apple",
    "Snapchat",
    "Instagram",
    "Facebook",
    "Discord",
]


def list_services() -> Dict[str, str]:
    """
    Вернуть словарь {SERVICE_NAME: SMS_CODE} поддерживаемых сервисов
    (только канонические имена, без алиасов).
    """
    result = {}
    for name in CANONICAL_SERVICES:
        cls = REGISTRATORS.get(name)
        if cls is not None:
            result[name] = getattr(cls, "SMS_CODE", None)
    return result


def get_registrator(
        service_name: str,
        sms,
        db,
        proxy_manager,
        config,
        on_status: Optional[Callable] = None,
        on_log: Optional[Callable] = None,
) -> BaseRegistrator:
    """
    Создать экземпляр регистратора для указанного сервиса.

    Args:
        service_name: Имя сервиса (Microsoft, Google, ...) или код (mm, go, ...).
        sms: Клиент Partner API.
        db: База данных.
        proxy_manager: Менеджер прокси.
        config: Конфигурация.
        on_status: Колбэк статуса.
        on_log: Колбэк логов.

    Returns:
        Экземпляр регистратора.

    Raises:
        ValueError: если сервис не поддерживается.
    """
    cls = get_registrator_class(service_name)
    if cls is None:
        supported = ", ".join(sorted(set(
            n for n in REGISTRATORS
            if n[0].isupper()
        )))
        raise ValueError(
            f"Сервис '{service_name}' не поддерживается. Доступно: {supported}"
        )

    return cls(
        sms=sms,
        db=db,
        proxy_manager=proxy_manager,
        config=config,
        on_status=on_status,
        on_log=on_log,
    )
