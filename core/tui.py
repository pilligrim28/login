"""
Textual TUI для MassReg — терминальный интерфейс запуска регистраций.

Логи идут ПОРОДНЮ: каждая запись логгера — отдельная строка панели, в
порядке появления (очередь + однопоточный рендер внутри Textual). Поэтому
сообщения из десятка параллельных регистраций не слипаются в «простыню».

Использование (обычно через main.py):
    python main.py            # автозапуск регистрации в TUI
    python main.py --no-autostart
напрямую:
    python -m core.tui
"""

from __future__ import annotations

import asyncio
import logging
import queue
import time
from datetime import datetime
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Input, Static


# ---------------------------------------------------------------------------
# Очередь логов: воркеры кладут строки, UI забирает пачками.
# ---------------------------------------------------------------------------

_LOG_QUEUE: "queue.Queue[str]" = queue.Queue()


def push_log(message: str) -> None:
    """Положить сообщение в очередь лога (безопасно из любого потока)."""
    _LOG_QUEUE.put_nowait(str(message))


def _drain_logs(max_items: int = 300) -> list[str]:
    items: list[str] = []
    while len(items) < max_items:
        try:
            items.append(_LOG_QUEUE.get_nowait())
        except queue.Empty:
            break
    return items


class LogQueueHandler(logging.Handler):
    """logging.Handler, отправляющий записи логгера MassReg в очередь UI.

    Формат совпадает с консольным: ``ЧЧ:ММ:СС [УРОВЕНЬ] сообщение``.
    """

    def emit(self, record) -> None:
        try:
            ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            msg = record.getMessage()
            push_log(f"{ts} [{record.levelname}] {msg}")
        except Exception:
            pass

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Виджеты
# ---------------------------------------------------------------------------

_LEVEL_COLORS = {
    "CRITICAL": "bold white on red",
    "ERROR": "red",
    "WARNING": "yellow",
}


class LogLine(Static):
    """Одна строка лога как отдельный виджет (гарантия построчного вывода)."""

    def __init__(self, line: str) -> None:
        style = "white"
        head = line[:40]
        for level, color in _LEVEL_COLORS.items():
            if f"[{level}]" in head:
                style = color
                break
        super().__init__(line)
        self.styles.color = style


class LogPane(VerticalScroll):
    """Панель логов: сообщения складываются ПОРОДНЮ, в порядке появления."""

    MAX_LINES = 5000  # защита от разрастания памяти при очень длинных сессиях

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._count = 0

    def append_line(self, line: str) -> None:
        self.mount(LogLine(line))
        self._count += 1
        if self._count > self.MAX_LINES:
            stale = self.query(LogLine)[: self.MAX_LINES // 2]
            for widget in stale:
                widget.remove()
            self._count -= len(stale)
        self.scroll_end(animate=False)

    def clear_lines(self) -> None:
        self.remove_children(LogLine)
        self._count = 0


class StatLabel(Static):
    """Одна метрика в строке статистики."""

    def __init__(self, name: str, key: str, **kwargs) -> None:
        super().__init__(f"{name}: —", id=f"stat-{key}", **kwargs)
        self.name_text = name
        self.key = key

    def set_value(self, value) -> None:
        self.update(f"{self.name_text}: [bold]{value}[/]")


class StatusBar(Static):
    def __init__(self, **kwargs) -> None:
        super().__init__("Готово к запуску.", id="status-bar", **kwargs)

    def set_status(self, text: str) -> None:
        self.update(text)


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

class MassRegApp(App[None]):
    """Терминальный интерфейс MassReg на Textual."""

    TITLE = "MassReg"

    CSS = """
    Screen { layout: vertical; }

    #header-panel {
        height: auto;
        padding: 0 1;
    }

    #stats {
        height: 1;
        padding: 0 1;
        background: $panel;
    }

    #log-pane {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }

    #status-bar {
        height: 1;
        padding: 0 1;
        background: $boost;
    }

    #controls { height: auto; padding: 0 1; }
    #cmd-input { width: 1fr; }
    """

    BINDINGS = [
        ("q", "quit_app", "Выход"),
        ("c", "clear_logs", "Очистить"),
        ("r", "run_start", "Запуск"),
        ("s", "stop_run", "Стоп"),
    ]

    def __init__(self, config=None, autostart: bool = False) -> None:
        super().__init__()
        self._config = config
        self._autostart = autostart
        self._worker = None            # workers.worker.Worker
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._start_ts: Optional[float] = None
        self._handler_installed = False

    # -- композация ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            "[bold cyan]MassReg TUI[/] — массовая регистрация. "
            "[b]r[/] запуск · [b]s[/] стоп · [b]c[/] очистить · [b]q[/] выход. "
            "Команды: run | stop | clear | quit",
            id="header-panel",
        )
        with Horizontal(id="stats"):
            yield StatLabel("Параллельно", "mode")
            yield StatLabel("Прогресс", "progress")
            yield StatLabel("Успех", "success")
            yield StatLabel("Неудача", "failed")
            yield StatLabel("Время", "elapsed")
        yield LogPane(id="log-pane")
        yield StatusBar()
        with Horizontal(id="controls"):
            yield Input(placeholder="Команда: run | stop | clear | quit", id="cmd-input")
        yield Footer()

    # -- жизненный цикл ------------------------------------------------------

    def on_mount(self) -> None:
        self._install_log_handler()
        self.set_interval(0.1, self._pump_logs)
        self.set_interval(1.0, self._tick_elapsed)
        if self._config is not None:
            conc = (self._config.get("worker.max_concurrency", None)
                    or self._config.get("worker.threads", 10))
            self.query_one("#stat-mode", StatLabel).set_value(conc)
        if self._autostart and self._config is not None:
            self._log_ui("[INFO] TUI готов — автозапуск регистрации…")
            self.set_timer(0.3, self.start_run)
        else:
            self._log_ui("[INFO] TUI готов. Нажмите 'r' или введите 'run' для старта.")

    def _install_log_handler(self) -> None:
        """Перенаправить консольный вывод логгера в панель логов TUI."""
        if self._handler_installed:
            return
        try:
            import sys as _sys
            from core.logger import log as app_log
            from core.log_handlers import ThreadSafeStreamHandler
            for handler in list(getattr(app_log.logger, "handlers", [])):
                if isinstance(handler, ThreadSafeStreamHandler) and \
                        getattr(handler, "stream", None) in (_sys.stdout, _sys.stderr):
                    app_log.logger.removeHandler(handler)
            if not any(isinstance(h, LogQueueHandler) for h in app_log.logger.handlers):
                app_log.logger.addHandler(LogQueueHandler())
        except Exception:
            pass
        self._handler_installed = True

    # -- поток логов ----------------------------------------------------------

    def _pump_logs(self) -> None:
        lines = _drain_logs()
        if not lines:
            return
        pane = self.query_one("#log-pane", LogPane)
        for line in lines:
            pane.append_line(line)

    def _log_ui(self, message: str) -> None:
        push_log(message)

    # -- статистика ------------------------------------------------------------

    def _tick_elapsed(self) -> None:
        if self._start_ts is None:
            return
        secs = int(time.time() - self._start_ts)
        self.query_one("#stat-elapsed", StatLabel).set_value(f"{secs // 60:02d}:{secs % 60:02d}")

    def _update_stats(self, done: int, total: int, success: int, failed: int) -> None:
        self.query_one("#stat-progress", StatLabel).set_value(f"{done}/{total}")
        self.query_one("#stat-success", StatLabel).set_value(success)
        self.query_one("#stat-failed", StatLabel).set_value(failed)

    # -- запуск / остановка -----------------------------------------------------

    def action_run_start(self) -> None:
        self.start_run()

    def start_run(self) -> None:
        if self._running:
            self._log_ui("[WARNING] Регистрация уже выполняется ('s' — стоп).")
            return
        if self._config is None:
            self._log_ui("[ERROR] Конфигурация не загружена (--config).")
            return

        from workers.worker import Worker

        worker = Worker(self._config)
        worker.on_progress = lambda done, total, ok, bad: self.call_from_thread(
            self._update_stats, done, total, ok, bad
        )
        worker.on_finished = lambda: self.call_from_thread(self._on_run_finished)

        self._worker = worker
        self._running = True
        self._start_ts = time.time()
        self.query_one(StatusBar).set_status(f"▶ Выполняется ({worker.concurrency} параллельно)…")

        # Один цикл событий в отдельном потоке: та же асинхронная ядро-логика,
        # что и в plain-режиме; колбэки возвращаются в UI через call_from_thread.
        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                loop.run_until_complete(worker.run())
            except Exception as exc:
                push_log(f"[ERROR] Сбой воркера: {exc}")
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()
                self._loop = None

        import threading
        threading.Thread(target=_runner, daemon=True, name="massreg-run").start()

    def _on_run_finished(self) -> None:
        self._running = False
        self.query_one(StatusBar).set_status("■ Завершено.")

    def action_stop_run(self) -> None:
        self.stop_run()

    def stop_run(self) -> None:
        if not self._running:
            self._log_ui("[INFO] Сейчас ничего не выполняется.")
            return
        worker = self._worker
        if worker is None:
            self._log_ui("[WARNING] Воркер ещё не инициализирован.")
            return
        try:
            loop = self._loop
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(worker.stop)
            else:
                worker.stop()
            self._log_ui("[WARNING] Остановка запрошена… дождитесь завершения активных задач.")
        except Exception as exc:
            push_log(f"[ERROR] Не удалось остановить: {exc}")

    # -- очистка -----------------------------------------------------------------

    def action_clear_logs(self) -> None:
        self.query_one("#log-pane", LogPane).clear_lines()

    # -- команды из поля ввода ------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip().lower()
        event.input.value = ""
        if cmd in {"run", "старт", "запуск"}:
            self.start_run()
        elif cmd in {"stop", "стоп", "остановить"}:
            self.stop_run()
        elif cmd in {"clear", "cls", "очистить"}:
            self.action_clear_logs()
        elif cmd in {"quit", "exit", "выход"}:
            self.action_quit_app()
        elif cmd:
            self._log_ui(f"[WARNING] Неизвестная команда: {cmd}. Доступны: run, stop, clear, quit")

    def action_quit_app(self) -> None:
        if self._running:
            self.stop_run()
        self.exit()


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def run_tui(config=None) -> None:
    MassRegApp(config=config).run()


if __name__ == "__main__":  # pragma: no cover
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.config import Config

    run_tui(Config(os.environ.get("MASSREG_CONFIG", ".env")))
