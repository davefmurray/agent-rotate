from __future__ import annotations

import pytest

from agent_rotate.credentials import Credential
from agent_rotate.proxy import Router
from agent_rotate.store import Store


class FakeCredentials:
    async def get(self, account, *, refresh=False):
        suffix = "-fresh" if refresh else ""
        return Credential(f"test-token-{account.name}{suffix}", f"test-id-{account.name}")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "state")


@pytest.fixture
async def router_factory(store):
    routers = []

    async def make(provider, upstream, **kwargs):
        router = Router(store, provider, FakeCredentials(), upstream=str(upstream), **kwargs)
        await router.start()
        routers.append(router)
        return router

    yield make
    for router in routers:
        await router.close()
