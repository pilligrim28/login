"""
Textual TUI для MassReg — терминальный интерфейс запуска регистраций.

Главное отличие от «сырого» вывода: логи идут ПОРОДНЮ (каждая запись —
отдельная строка в порядке появления), а не слипаются в одну «простыню»,
когда 10 потоков пишут одновременно. Это достигается очередью сообщений
и однопоточным рендером внутри приложения Textual.

Использование (обычно через main.py):
    python main.py tui
или напрямую:
    python -m core.tui
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from datetime import datetime
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Input, Static

# ---------------------------------------------------------------------------
# Очередь логов: все потоки-воркеры кладут сюда строки, UI забирает пачками.
# ---------------------------------------------------------------------------

_LOG_QUEUE: "queue.Queue[str]" = queue.Queue()


def push_log(message: str) -> None:
    """Положить сообщение в очередь лога (безопасно из любого потока)."""
    _LOG_QUEUE.put_nowait(str(message))


def _drain_logs(max_items: int = 300) -> list[str]:
    """Забрать до ``max_items`` накопившихся сообщений без блокировки."""
    items: list[str] = []
    while len(items) < max_items:
        try:
            items.append(_LOG_QUEUE.get_nowait())
        except queue.Empty:
            break
    return items


class LogQueueHandler:
    """
    Duck-type совместимый с ``logging.Handler`` адаптер.

    Перехватывает записи логгера MassReg (из worker / registrator / main)
    и отправляет их в очередь UI вместо stderr. Формат строки совпадает
    с консольным: ``ЧЧ:ММ:СС [УРОВЕНЬ] сообщение``.
    """

    def __init__(self) -> None:
        self.level = 0
        self.formatter = None

    def setLevel(self, level) -> None:  # noqa: N802 (интерфейс logging)
        self.level = level

    def setFormatter(self, fmt) -> None:  # noqa: N802
        self.formatter = fmt

    def emit(self, record) -> None:
        try:
            ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            msg = record.getMessage()
            if self.formatter is not None:
                msg = self.formatter.formatMessage(record)
            push_log(f"{ts} [{record.levelname}] {msg}")
        except Exception:
            pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Виджеты
# ---------------------------------------------------------------------------

_LEVEL_STYLES = {
    "ERROR": "bold red",
    "WARNING": "yellow",
    "CRITICAL": "bold white on red",
}


_LEVEL_COLORS = {
    "ERROR": "red",
    "CRITICAL": "white",
    "WARNING": "yellow",
}


class LogLine(Static):
    """Одна строка лога как отдельный виджет (гарантия «породню», без склейки)."""

    def __init__(self, line: str) -> None:
        color = "white"
        for level, lvl_color in _LEVEL_COLORS.items():
            if f"[{level}]" in line[:40]:
                color = lvl_color
                break
        super().__init__(line)
        self.styles.color = color


class LogPane(VerticalScroll):
    """Панель логов: складывает сообщения ПОРОДНЮ, в порядке появления."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines: list[str] = []

    def append_line(self, line: str) -> None:
        self._lines.append(line)
        self.mount(LogLine(line))
        self.scroll_end(animate=False)

    def clear_lines(self) -> None:
        self._lines.clear()
        self.remove_children(LogLine)

    @property
    def lines(self) -> list[str]:
        return list(self._lines)


class StatLabel(Static):
    """Одна метрика в шапке статистики («портянка» цифр вместо каша-строк)."""

    def __init__(self, name: str, key: str, **kwargs) -> None:
        super().__init__(f"{name}: —", id=f"stat-{key}", **kwargs)
        self.name_text = name
        self.key = key

    def set_value(self, value) -> None:
        self.update(f"{self.name_text}: [bold]{value}[/]")


class StatusBar(Static):
    """Строка состояния внизу над футером."""

    def __init__(self, **kwargs) -> None:
        super().__init__("Готово к запуску.", id="status-bar", **kwargs)

    def set_status(self, text: str) -> None:
        self.update(text)


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

class MassRegApp(App[None]):
    """Терминальный GUI MassReg на Textual."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #header-panel {
        height: auto;
        padding: 0 1;
        content-align: left middle;
    }

    #stats {
        height: 1;
        padding: 0 1;
        background: $panel;
    }

    #stats StatLabel {
        width: auto;
        padding-right: 2;
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

    #controls {
        height: auto;
        padding: 0 1;
    }

    #cmd-input {
        width: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit_app", "Выход"),
        ("c", "clear_logs", "Очистить"),
        ("r", "run_start", "Запуск"),
        ("s", "stop_run", "Стоп"),
    ]

    def __init__(self, config=None) -> None:
        super().__init__()
        self._config = config
        self._worker = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._start_ts: Optional[float] = None
        self._handler_installed = False

    # -- композация ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            "[bold cyan]MassReg TUI[/] — массовая регистрация аккаунтов. "
            "Логи идут породню; команды: [b]r[/] запуск, [b]s[/] стоп, "
            "[b]c[/] очистить, [b]Ctrl+C[/]/[b]q[/] выход.",
            id="header-panel",
        )
        with Horizontal(id="stats"):
            yield StatLabel("Режим", "mode")
            yield StatLabel("Прогресс", "progress")
            yield StatLabel("Успех", "success")
            yield StatLabel("Неудача", "failed")
            yield StatLabel("Время", "elapsed")
        yield LogPane(id="log-pane")
        yield StatusBar()
        with Horizontal(id="controls"):
            yield Input(placeholder="Команда: run | stop | clear | quit", id="cmd-input")
        yield Footer()

    # -- жизненный цикл ----------------------------------------------------

    def on_mount(self) -> None:
        self._install_log_handler()
        self.set_interval(0.1, self._pump_logs)
        self.set_interval(1.0, self._tick_elapsed)
        if self._config is not None:
            mode = str(self._config.get("run.mode", "") or
                       self._config.get("worker.mode", "") or "auto")
            self.query_one("#stat-mode", StatLabel).set_value(mode)
        self._log_ui("TUI готов. Нажмите 'r' или введите 'run' для старта.")

    def _install_log_handler(self) -> None:
        """Перенаправить стандартный логгер MassReg в панель логов."""
        if self._handler_installed:
            return
        try:
            from core.logger import log as app_log

            formatter = None
            keep_console = False
            for handler in getattr(app_log.logger, "handlers", []):
                if type(handler).__name__ == "StreamHandler":
                    keep_console = handler.stream is not None and \
                        handler.stream is not __import__("sys").stderr
                    formatter = handler.formatter
                    if not keep_console:
                        app_log.logger.removeHandler(handler)
            app_log.logger.addHandler(LogQueueHandler())
            if formatter is not None:
                pass  # формат уже применяется в emit()
            self._handler_installed = True
        except Exception:
            # Если логгер недоступен — UI всё равно работает через push_log
            self._handler_installed = True

    # -- поток логов --------------------------------------------------------

    def _pump_logs(self) -> None:
        """Выбрать сообщения из очереди и вывести КАЖДЫЙ отдельной строкой."""
        lines = _drain_logs()
        if not lines:
            return
        pane = self.query_one("#log-pane", LogPane)
        for line in lines:
            pane.append_line(line)

    def _log_ui(self, message: str) -> None:
        push_log(message)

    # -- статистика ----------------------------------------------------------

    def watch_progress(self, *_args) -> None:  # pragma: no cover - хук Textual
        pass

    def _tick_elapsed(self) -> None:
        if self._start_ts is None:
            return
        secs = int(time.time() - self._start_ts)
        self.query_one("#stat-elapsed", StatLabel).set_value(
            f"{secs // 60:02d}:{secs % 60:02d}"
        )

    def _update_stats(self, done: int, total: int, success: int, failed: int) -> None:
        self.query_one("#stat-progress", StatLabel).set_value(f"{done}/{total}")
        self.query_one("#stat-success", StatLabel).set_value(success)
        self.query_one("#stat-failed", StatLabel).set_value(failed)

    # -- запуск / остановка ---------------------------------------------------

    def action_run_start(self) -> None:
        self.start_run()

    def start_run(self) -> None:
        if self._running:
            self._log_ui("[WARNING] Регистрация уже выполняется. Дождитесь окончания или 'stop'.")
            return
        if self._config is None:
            self._log_ui("[ERROR] Конфигурация не загружена (--config).")
            return

        from main import resolve_run_mode  # локальный импорт против цикла

        mode = resolve_run_mode(self._config)
        self.query_one("#stat-mode", StatLabel).set_value(mode)
        self._running = True
        self._start_ts = time.time()
        self.query_one(StatusBar).set_status(f"▶ Выполняется ({mode})…")

        runner = self._run_sync_worker if mode == "sync" else self._run_async_worker
        self._thread = threading.Thread(target=runner, daemon=True, name="massreg-run")
        self._thread.start()

    def _run_sync_worker(self) -> None:
        """Фоновый запуск потокового Worker (тот же код, что и CLI)."""
        try:
            from workers.worker import Worker

            worker = Worker(self._config)
            self._worker = worker

            def on_progress(done, total, success, failed):
                self.call_from_thread(self._update_stats, done, total, success, failed)

            worker.on_progress = on_progress
            worker.run()
        except Exception as exc:  # показываем ошибку в UI, не роняем его
            push_log(f"[ERROR] Сбой воркера: {exc}")
        finally:
            self._finish_run()

    def _run_async_worker(self) -> None:
        """Фоновый запуск AsyncWorker в собственном event loop."""
        try:
            from workers.async_worker import AsyncWorker

            async def _main():
                worker = AsyncWorker(self._config)
                self._worker = worker

                def on_progress(done, total, success, failed):
                    self.call_from_thread(self._update_stats, done, total, success, failed)

                worker.on_progress = on_progress
                await worker.run()

            asyncio.run(_main())
        except Exception as exc:
            push_log(f"[ERROR] Сбой асинхронного воркера: {exc}")
        finally:
            self._finish_run()

    def _finish_run(self) -> None:
        self._running = False
        self._worker = None
        try:
            self.call_from_thread(self._on_run_finished)
        except Exception:
            pass

    def _on_run_finished(self) -> None:
        self.query_one(StatusBar).set_status("■ Остановлено.")

    def action_stop_run(self) -> None:
        self.stop_run()

    def stop_run(self) -> None:
        if not self._running:
            self._log_ui("[INFO] Сейчас ничего не выполняется.")
            return
        worker = self._worker
        if worker is not None:
            try:
                worker.stop()
                self._log_ui("[WARNING] Остановка запрошена…")
            except Exception as exc:
                push_log(f"[ERROR] Не удалось остановить: {exc}")
        else:
            self._log_ui("[WARNING] Воркер ещё не инициализирован.")

    # -- очистка --------------------------------------------------------------

    def action_clear_logs(self) -> None:
        self.query_one("#log-pane", LogPane).clear_lines()

    # -- команды из поля ввода --------------------------------------------------

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
            self.exit()
        elif cmd:
            self._log_ui(f"[WARNING] Неизвестная команда: {cmd}. "
                         f"Доступны: run, stop, clear, quit")

    def action_quit_app(self) -> None:
        if self._running:
            self.stop_run()
        self.exit()


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def run_tui(config=None) -> None:
    """Запустить Textual TUI (используется из main.py командой ``tui``)."""
    MassRegApp(config=config).run()


if __name__ == "__main__":  # pragma: no cover
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.config import Config

    run_tui(Config(os.environ.get("MASSREG_CONFIG", ".env")))
