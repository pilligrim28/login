"""
Надёжные logging-хендлеры.

Проблема, которую решает этот модуль:
    Стандартный RotatingFileHandler на Windows при ротации выполняет
        self.stream.tell()
    над файлом, открытым в текстовом режиме с буферизацией. Если в буфере
    остались недописанные многобайтовые символы (кириллица/эмодзи) или файл
    заблокирован другим процессом (например, логи открыты в редакторе),
    tell() бросает OSError [Errno 22] Invalid argument. logging не глотает
    системные ошибки хендлеров -> в консоль сыпется "--- Logging error ---"
    с простынёй трейсбеков после КАЖДОЙ записи.

Решение:
    SafeRotatingFileHandler — ownEmit с перехватом OSError: битый поток
    закрывается и переоткрывается (doRollover вызывается вручную), запись
    повторяется один раз; при повторном сбое она просто отбрасывается,
    а не печатает трейсбек.

    ThreadSafeStreamHandler — потокобезопасная запись в консоль/TUI
    (logging.StreamHandler не сериализует emit между потоками).
"""

from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler


class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler, устойчивый к OSError при ротации на Windows."""

    def shouldRollover(self, record):  # noqa: N802 (имя из stdlib)
        try:
            return super().shouldRollover(record)
        except OSError:
            # Поток повреждён (Errno 22 и т.п.) — пробуем восстановить его,
            # чтобы следующая проверка размера работала корректно.
            self._reopen_stream()
            try:
                return super().shouldRollover(record)
            except OSError:
                return 0

    def _reopen_stream(self) -> None:
        try:
            if self.stream is not None:
                self.stream.close()
        except Exception:
            pass
        self.stream = None
        try:
            # Всегда переоткрываем поток (delay=False в нашем логгере),
            # иначе logging.StreamHandler.emit молча пропустит запись.
            self.stream = self._open()
        except Exception:
            self.stream = None

    def doRollover(self):  # noqa: N802
        try:
            super().doRollover()
        except OSError:
            # Файл логов занят другим процессом (Windows) — ротацию пропускаем,
            # продолжаем писать в текущий файл вместо падения логгера.
            self._reopen_stream()

    def emit(self, record):
        for attempt in range(2):
            try:
                # Внутренние ошибки (shouldRollover/doRollover) гасим сами,
                # чтобы не получать "--- Logging error ---" от stdlib.
                with self.lock:
                    if self.shouldRollover(record):
                        self.doRollover()
                    self.stream_and_write(record)
                return
            except OSError:
                # Сбой записи/ротации (Errno 22): чиним поток и пробуем ещё раз.
                self._reopen_stream()
                if attempt == 0 and self.stream is not None:
                    continue
            except Exception:
                pass
            # Вторая неудача или неизвестная ошибка — молча отбрасываем запись.
            return

    def stream_and_write(self, record) -> None:
        """Одна запись в открытый поток (без повторной проверки ротации)."""
        if self.stream is None:
            raise OSError(9, "log stream unavailable")
        msg = self.format(record)
        stream = self.stream
        stream.write(msg + self.terminator)
        self.flush()

    def handleError(self, record):  # noqa: N802
        # Глушим стандартный вывод "--- Logging error ---".
        # Ошибки самого логгера не должны мешать основной программе.
        return


class ThreadSafeStreamHandler(logging.StreamHandler):
    """StreamHandler с сериализацией emit между потоками (для консоли и TUI)."""

    def __init__(self, stream=None):
        super().__init__(stream)
        self._write_lock = threading.Lock()

    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            with self._write_lock:
                stream.write(msg + self.terminator)
                self.flush()
        except Exception:
            try:
                self.handleError(record)
            except Exception:
                pass


class NullErrorHandler(logging.Handler):
    """Хендлер-заглушка: никогда не печатает трейсбеки ошибок логирования."""

    def emit(self, record):
        return

    def handleError(self, record):  # noqa: N802
        return
