"""Env-only, never-raising capture helpers for terminal adapters."""

import os

MAX_VALUE_BYTES = 1024


def bounded_env(names: tuple[str, ...]) -> dict[str, str]:
    captured = {}
    for name in names:
        try:
            value = os.environ.get(name)
            if (
                not isinstance(value, str)
                or "\0" in value
                or len(value.encode("utf-8")) > MAX_VALUE_BYTES
            ):
                continue
        except Exception:
            continue
        captured[name] = value
    return captured


def is_decimal_id(value, max_len: int = 12) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_len
        and value.isascii()
        and value.isdigit()
    )
