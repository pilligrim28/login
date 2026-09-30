"""Тесты единого асинхронного воркера (workers/worker.py)."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from workers.worker import Worker, create_sms_client
from core.config import Config
from tests.config_helpers import write_config


@pytest.fixture
def temp_config():
    """Временный конфиг с изолированной SQLite-базой."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_worker.db")
        config_data = {
            "sms": {
                "api_key": "test_key_123",
                "service": "Microsoft",
                "country": "all",
                "max_price": 0,
            },
            "proxy": {"enabled": False, "type": "http", "proxies": []},
            "worker": {
                "threads": 2,
                "total_registrations": 4,
                "headless": True,
            },
            "database": {"type": "sqlite", "sqlite_path": db_path},
        }
        path = write_config(Path(tmpdir) / ".env", config_data)
        yield Config(str(path))


def make_worker(temp_config):
    with patch("workers.worker.create_sms_client", return_value=MagicMock()):
        worker = Worker(temp_config)
    worker.sms.get_balance.return_value = {"usd": 10.0, "limit": 100.0}
    return worker


def test_worker_reads_limits_from_config(temp_config):
    worker = make_worker(temp_config)
    assert worker.total == 4
    assert worker.concurrency == 2
    assert worker.services == ["Microsoft"]


def test_create_sms_client_prefers_partner_url(temp_config):
    from core.partner_api import PartnerAPI
    pm = MagicMock()
    client = create_sms_client(temp_config, pm)
    assert isinstance(client, PartnerAPI)


def test_worker_run_counts_success_and_failure(temp_config):
    worker = make_worker(temp_config)

    async def fake_register(proxy=None):
        # Чётные индексы — успех, нечётные — нет (порядок не гарантирован,
        # поэтому считаем по сумме результатов).
        return None

    captured = []

    def fake_get_registrator(**kwargs):
        reg = MagicMock()
        reg.register = MagicMock(side_effect=lambda **kw: _result_for(kwargs["service_name"]))
        return reg

    async def _noop(*a, **k):
        pass

    results = [None, {"email": "a@b.c"}, None, {"email": "d@e.f"}]
    it = iter(results)

    def _result_for(_service):
        # Возвращаем корутину, совместимую с await в воркере
        async def coro():
            try:
                return next(it)
            except StopIteration:
                return None
        return coro()

    progress_events = []
    worker.on_progress = lambda *args: progress_events.append(args)

    with patch("workers.worker.get_registrator", side_effect=fake_get_registrator):
        stats = asyncio.run(worker.run())

    assert stats["done"] == 4
    assert stats["success"] == 2
    assert stats["failed"] == 2
    assert progress_events[-1][:2] == (4, 4)


def test_worker_stop_skips_remaining(temp_config):
    worker = make_worker(temp_config)
    worker.stop()  # стоп до запуска задач
    with patch("workers.worker.get_registrator") as gr:
        stats = asyncio.run(worker.run())
    gr.assert_not_called()
    assert stats["done"] == 0
