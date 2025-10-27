import asyncio
from dataclasses import dataclass
import sys
import types
from typing import Any, Dict, Optional

import pytest

# Provide lightweight stubs for modules pulled in by Home Assistant that we don't exercise
if "hass_nabucasa" not in sys.modules:
    hass_nabucasa = types.ModuleType("hass_nabucasa")
    hass_nabucasa.__path__ = []  # mark as package
    sys.modules["hass_nabucasa"] = hass_nabucasa

    remote_module = types.ModuleType("hass_nabucasa.remote")

    class _RemoteUI:
        """Minimal stub used during tests."""

        def __init__(self, *args, **kwargs) -> None:
            pass

    remote_module.RemoteUI = _RemoteUI
    sys.modules["hass_nabucasa.remote"] = remote_module

    acme_module = types.ModuleType("hass_nabucasa.acme")

    class _DummyError(Exception):
        pass

    class _DummyHandler:
        def __init__(self, *args, **kwargs) -> None:
            pass

    acme_module.AcmeClientError = _DummyError
    acme_module.AcmeHandler = _DummyHandler
    sys.modules["hass_nabucasa.acme"] = acme_module


@dataclass
class DummyState:
    state: str
    attributes: Dict[str, Any]


class DummyStateMachine:
    def __init__(self, states: Optional[Dict[str, DummyState]] = None) -> None:
        self._states = states or {}

    def get(self, entity_id: str) -> Optional[DummyState]:
        return self._states.get(entity_id)

    def set(self, entity_id: str, state: DummyState) -> None:
        self._states[entity_id] = state


class DummyServices:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def async_call(self, domain: str, service: str, data: dict[str, Any], blocking: bool = False) -> None:
        self.calls.append(
            {
                "domain": domain,
                "service": service,
                "data": data,
                "blocking": blocking,
            }
        )


class DummyHass:
    def __init__(self, states: Optional[Dict[str, DummyState]] = None) -> None:
        self.states = DummyStateMachine(states)
        self.services = DummyServices()
        self.loop = asyncio.get_event_loop_policy().get_event_loop()

    async def async_add_executor_job(self, func, *args, **kwargs):
        return func(*args, **kwargs)


@pytest.fixture
def dummy_hass():
    return DummyHass()


@pytest.fixture
def no_sleep(monkeypatch):
    async def _sleep(_):
        return None

    monkeypatch.setattr("custom_components.heating_control.controller.asyncio.sleep", _sleep)
