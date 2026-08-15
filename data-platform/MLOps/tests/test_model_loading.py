"""Teste de _refresh_loop — etapa 8.2 do plano de bundle.

O manager e o loader já têm suíte própria (etapas 4 e 5, test_model_bundle_manager.py e
test_artifact_bundle_loader.py); este arquivo testa só o que é novo em main.py: o laço que
chama refresh_if_changed repetidamente até ser cancelado. _load_model_with_retry e
_refresh_model_bundle deixam de existir — o fluxo de recarga por assinatura de arquivo, a
cada requisição, não migra.
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
