"""Teste de _refresh_loop: o laço que chama refresh_if_changed repetidamente até ser
cancelado. O manager e o loader têm suíte própria em test_model_bundle_manager.py e
test_artifact_bundle_loader.py.
"""
import asyncio
from contextlib import suppress

import pytest

from MLOps.app.api.main import _refresh_loop


class FakeManager:
    def __init__(self) -> None:
        self.call_count = 0

    def refresh_if_changed(self) -> bool:
        self.call_count += 1
        return False


@pytest.mark.asyncio
async def test_refresh_loop_calls_refresh_if_changed_repeatedly_until_cancelled() -> None:
    manager = FakeManager()
    loop_task = asyncio.create_task(_refresh_loop(manager, refresh_seconds=0.001))

    for _ in range(200):
        if manager.call_count >= 3:
            break
        await asyncio.sleep(0.001)

    loop_task.cancel()
    with suppress(asyncio.CancelledError):
        await loop_task

    assert manager.call_count >= 3
