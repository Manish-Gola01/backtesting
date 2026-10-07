"""Strategy registry — plugin pattern.

Strategies self-register by name; the engine looks them up here. Adding a new
strategy later = define a BaseStrategy subclass and call register_strategy —
zero changes to the engine.
"""
from __future__ import annotations

from threading import Lock

from app.strategies.base import BaseStrategy

_REGISTRY: dict[str, BaseStrategy] = {}
_LOCK = Lock()


def register_strategy(strategy: BaseStrategy) -> BaseStrategy:
    with _LOCK:
        if not strategy.name:
            raise ValueError("strategy must define a non-empty `name`")
        _REGISTRY[strategy.name] = strategy
    return strategy


def get_strategy(name: str) -> BaseStrategy:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"strategy {name!r} is not registered; available: {sorted(_REGISTRY)}"
        ) from None


def list_strategies() -> list[dict]:
    return [
        {"name": s.name, "description": s.description, "param_schema": dict(s.param_schema)}
        for s in _REGISTRY.values()
    ]


def _clear() -> None:  # test helper: wipe registry AND bootstrap flag
    global _bootstrapped
    with _LOCK:
        _REGISTRY.clear()
    _bootstrapped = False


_bootstrapped = False


def bootstrap() -> None:
    """Register all built-in strategies exactly once. Called at app startup and
    defensively by services. Importing here avoids a circular import at module
    load time."""
    global _bootstrapped
    if _bootstrapped:
        return
    from app.strategies.liquidity_oi import LiquidityOIStrategy
    register_strategy(LiquidityOIStrategy())
    _bootstrapped = True
