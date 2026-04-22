from typing import Awaitable, Callable

from backend.chatbot.channels.base import Channel

_REGISTRY: dict[str, Channel] = {}
_identity_resolver: Callable[[str, str], Awaitable[Channel | None]] | None = None


def register(channel: Channel) -> None:
    _REGISTRY[channel.name] = channel


def get(name: str) -> Channel:
    return _REGISTRY[name]


def set_identity_resolver(
    fn: Callable[[str, str], Awaitable[Channel | None]],
) -> None:
    global _identity_resolver
    _identity_resolver = fn


async def get_for_customer(business_id: str, customer_id: str) -> Channel | None:
    if _identity_resolver is None:
        return None
    return await _identity_resolver(business_id, customer_id)
