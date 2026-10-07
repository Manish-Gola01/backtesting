"""Canonical timeframe registry.

A timeframe string is `<positive integer><unit>` where unit is one of
m(inute), h(our), d(ay), w(eek), M(onth). Month is approximated as 30 days
for gap-checking purposes only (documented in docs/ASSUMPTIONS.md).
"""

_UNITS_SECONDS: dict[str, int] = {
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
    "M": 2592000,  # 30-day month approximation — gap checks only
}

TIMEFRAME_SECONDS: dict[str, int] = {
    f"{n}{u}": n * s for u, s in _UNITS_SECONDS.items() for n in (1, 2, 3, 5, 15, 30)
    if not (u == "w" and n > 1) and not (u == "M" and n > 1)
}
# plus a few common extras
TIMEFRAME_SECONDS.update({"4h": 4 * 3600, "1d": 86400})


def is_valid_timeframe(tf: str) -> bool:
    if tf in TIMEFRAME_SECONDS:
        return True
    if len(tf) < 2:
        return False
    unit, _, num = tf[-1], "", tf[:-1]
    return unit in _UNITS_SECONDS and num.isdigit() and int(num) > 0


def timeframe_seconds(tf: str) -> int:
    """Expected spacing between consecutive candles, in seconds."""
    if not is_valid_timeframe(tf):
        raise ValueError(f"Invalid timeframe: {tf!r}")
    if tf in TIMEFRAME_SECONDS:
        return TIMEFRAME_SECONDS[tf]
    return int(tf[:-1]) * _UNITS_SECONDS[tf[-1]]
