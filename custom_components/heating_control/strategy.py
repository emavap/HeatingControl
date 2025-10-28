"""Compatibility shim exposing the dashboard strategy under the expected name."""
from __future__ import annotations

from .dashboard import HeatingControlDashboardStrategy, async_get_strategy

__all__ = ["HeatingControlDashboardStrategy", "async_get_strategy"]
