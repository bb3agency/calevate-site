"""How long an agent's instructions are, layer by layer, against the calling system's box.

Read-only. It composes exactly what a publish would send right now (`agents/prompt_size`,
over `service._to_config`, after loading the ops console settings and the published spoken
style the way a live apply does) and prints character counts and labels only, never prompt
text (hard rule 6).

    uv run python -m scripts.prompt_size --agent <uuid>     # one agent, by layer
    uv run python -m scripts.prompt_size --all-live         # one line per live agent

On the VPS:

    docker compose -p calevate -f compose.prod.yml run --rm --no-deps --entrypoint python \
        api -m scripts.prompt_size --agent <uuid>

Exit 0 when everything measured fits, 1 when something is over the box, 2 when an agent
could not be measured.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from uuid import UUID

from apps.api.agents.prompt_size import PromptSize, lines, measure_agent
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import refresh
from apps.api.db.session import admin_session, tenant_session
from apps.api.engine import get_engine
from apps.api.ops.spoken_style_store import refresh_spoken_style
from sqlalchemy import text

_DIRECTORY = "SELECT id FROM organizations ORDER BY id"
_TENANT_OF = "SELECT tenant_id FROM agents WHERE id = :aid AND deleted_at IS NULL"
_LIVE = (
    "SELECT id FROM agents WHERE tenant_id = :tid AND status = 'live' "
    "AND deleted_at IS NULL ORDER BY id"
)


def reason_code(exc: Exception) -> str:
    """Our refusal code, or the exception's class: never its message, which may quote a
    script or a stored value."""
    return exc.code if isinstance(exc, ProblemError) else type(exc).__name__


async def _prepare() -> None:
    # The settings and spoken style a publish reads, so the count is today's.
    await refresh(force=True)
    await refresh_spoken_style()


async def tenant_of(agent_id: UUID) -> UUID | None:
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_DIRECTORY))).scalars()]
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            found = (await scoped.execute(text(_TENANT_OF), {"aid": agent_id})).scalar()
        if found is not None:
            return tenant_id
    return None


async def _measure(tenant_id: UUID, agent_id: UUID) -> PromptSize:
    async with tenant_session(tenant_id) as session:
        return await measure_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, engine=get_engine()
        )


async def one(agent_id: UUID) -> int:
    await _prepare()
    tenant_id = await tenant_of(agent_id)
    if tenant_id is None:
        print(f"agent {agent_id}: not found")
        return 2
    try:
        size = await _measure(tenant_id, agent_id)
    except Exception as exc:  # report the reason, never a traceback with values in it
        print(f"agent {agent_id}: cannot be measured ({reason_code(exc)})")
        return 2
    print(f"agent {agent_id} (engine {get_engine().name})")
    for line in lines(size):
        print(line)
    return 0 if size.fits else 1


async def all_live() -> int:
    await _prepare()
    worst = 0
    print(f"{'agent':<36}  {'total':>6}  {'limit':>6}  {'headroom':>8}")
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_DIRECTORY))).scalars()]
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            agents = [
                UUID(str(a))
                for a in (await scoped.execute(text(_LIVE), {"tid": tenant_id})).scalars()
            ]
        for agent_id in agents:
            try:
                size = await _measure(tenant_id, agent_id)
            except Exception as exc:  # one agent's state must not stop the listing
                print(f"{agent_id!s:<36}  cannot be measured ({reason_code(exc)})")
                worst = max(worst, 2)
                continue
            limit = "-" if size.limit is None else f"{size.limit}"
            headroom = "-" if size.headroom is None else f"{size.headroom}"
            print(f"{agent_id!s:<36}  {size.total:>6}  {limit:>6}  {headroom:>8}")
            if not size.fits:
                worst = max(worst, 1)
    return worst


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.prompt_size", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent", type=UUID, help="one agent's id")
    group.add_argument("--all-live", action="store_true", help="every live agent")
    args = parser.parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if args.agent is not None:
        return asyncio.run(one(args.agent))
    return asyncio.run(all_live())


if __name__ == "__main__":
    sys.exit(main())
