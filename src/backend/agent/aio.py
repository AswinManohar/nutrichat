from __future__ import annotations


async def resolved[T](value: T) -> T:
    """Awaitable that returns ``value``, so gather() takes a uniform shape."""
    return value
