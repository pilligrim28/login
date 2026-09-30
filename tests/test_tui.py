"""Тесты Textual TUI (core/tui.py)."""

import queue

import pytest

textual = pytest.importorskip("textual")

from core.tui import MassRegApp, LogPane, _LOG_QUEUE, push_log, _drain_logs


@pytest.fixture(autouse=True)
def clear_queue():
    while not _LOG_QUEUE.empty():
        _LOG_QUEUE.get_nowait()
    yield


def test_push_drain_order_preserved():
    for i in range(5):
        push_log(f"line-{i}")
    assert _drain_logs() == ["line-0", "line-1", "line-2", "line-3", "line-4"]


async def test_app_mounts_and_renders_logs_in_order():
    app = MassRegApp(config=None, autostart=False)
    async with app.run_test(size=(100, 30)) as pilot:
        pane = app.query_one("#log-pane", LogPane)
        push_log("[INFO] первая")
        push_log("[ERROR] вторая")
        await pilot.pause(0.3)
        lines = [str(w.renderable) if hasattr(w, "renderable") else w.content
                 for w in pane.query("LogLine")]
        texts = [t for t in lines if "первая" in t or "вторая" in t]
        assert any("первая" in t for t in texts)
        assert any("вторая" in t for t in texts)
        # Порядок сохранён: первая строка лога раньше второй
        idx_first = next(i for i, t in enumerate(lines) if "первая" in t)
        idx_second = next(i for i, t in enumerate(lines) if "вторая" in t)
        assert idx_first < idx_second


async def test_quit_binding_exits():
    app = MassRegApp(config=None, autostart=False)
    async with app.run_test() as pilot:
        await pilot.press("q")
        assert app._exit
