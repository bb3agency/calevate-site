"""Keep the admin client-health board computed, so no console poll walks every tenant.

`admin/health.compute_client_health` enters each live tenant's own RLS session; per request
that returned a 500 at 7.7k accounts. This cron computes it every `BOARD_REFRESH_S` and keeps
it in Redis (`health.store_board`), where `GET /v1/admin/client-health` and the admin
assistant read it.
"""

from __future__ import annotations

from typing import Any

from apps.api.admin.health import refresh_board
from apps.api.core.logging import get_logger
from apps.api.db.session import admin_session

log = get_logger(__name__)


async def refresh_client_health(ctx: dict[str, Any]) -> str:
    del ctx
    async with admin_session() as directory:
        board = await refresh_board(directory)
    return f"accounts={len(board.rows)}"


__all__ = ["refresh_client_health"]
