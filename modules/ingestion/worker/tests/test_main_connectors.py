import asyncio
import logging

import pytest
from knowcel_ingestion_worker import __main__ as main


async def test_connectors_that_fail_are_logged(caplog: pytest.LogCaptureFixture):
    async def boom() -> None:
        raise RuntimeError("no lease")

    task = asyncio.create_task(boom())
    task.add_done_callback(main.log_failure)
    with caplog.at_level(logging.ERROR):
        await asyncio.wait({task})
        await asyncio.sleep(0)
    assert "the connectors stopped" in caplog.text


async def test_connectors_are_cancelled_when_they_do_not_stop(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "CONNECTOR_GRACE", 0.05)
    stop = asyncio.Event()
    cancelled = asyncio.Event()

    async def stuck() -> None:
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    task = asyncio.create_task(stuck())
    await asyncio.sleep(0)
    await main.stop_connectors(task, stop)
    assert stop.is_set()
    assert task.cancelled()
    assert cancelled.is_set()


async def test_connectors_get_time_to_finish():
    stop = asyncio.Event()
    done = []

    async def finishing() -> None:
        await stop.wait()
        done.append(True)

    task = asyncio.create_task(finishing())
    await main.stop_connectors(task, stop)
    assert done
    assert not task.cancelled()
