"""Shared helpers for the Planetpod integration."""
from __future__ import annotations

from typing import Any

import aiohttp


def is_valid_grid_payload(payload: Any) -> bool:
    """Validate minimum open API response contract for grid status."""
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("grid_id"), int)
        and isinstance(payload.get("pods"), list)
    )


async def read_json_payload(resp: aiohttp.ClientResponse) -> dict[str, Any] | None:
    """Read JSON body safely without assuming content type or shape."""
    try:
        payload = await resp.json(content_type=None)
    except (aiohttp.ContentTypeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    return payload
