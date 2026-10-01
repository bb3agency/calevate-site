"""Demo OUTREACH data for a local stack: campaigns, lead sources and a delivery endpoint.

`scripts/seed_dev.py` creates the demo tenant with calls and leads, but it leaves every
outreach screen (campaigns, lead sources, integrations) empty, so nobody can look at those
screens with rows on them. `seed_outreach()` fills them in. It runs AFTER `seed_dev`
(it needs the tenant and owner that script creates) and is wired in by it.

**It drives the same HTTP routes the console calls**, in-process over ASGI and with the
local `dev:` bearer token, rather than writing rows. A campaign is created by
`POST /v1/campaigns`, its contacts by `POST /v1/campaigns/{id}/contacts`, and so on, so
every row passes the validation, audit and RLS a client's request would. Nothing is
UPDATEd into a state: a campaign this stack cannot lawfully launch (no DLT registration,
no approved template, no number) stays a draft, and the launch check says why. That is
the screen the redesign has to get right, and faking `running` would show one nobody can
reach.

Idempotent and keyed: campaigns by name, lead sources by kind, endpoints by URL. Re-running
creates nothing new. Every phone number is in `+9199 00000…`, which is not a dialable
Indian mobile range.

Local only, through `seed_dev._refuse_unless_local` and the dev-token gate
(`core.auth.dev_tokens_permitted`): both refuse on any host holding real credentials.

    uv run python -m scripts.seed_dev_outreach
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text

from scripts.seed_dev import OWNER_EMAIL, TENANT_SLUG, _refuse_unless_local

#: The demo contact range. `+9199` followed by `00000` is not an allocated mobile series.
DEMO_RANGE = "+91990000"

#: (name, classification, consent source or None, contact count, calling hours or None)
#: Three drafts covering the three launch-check stories: one answered and waiting only on
#: the account's own setup, one with the list's origin unanswered, and one recorded as a
#: bought list, which the gate refuses by name.
DEMO_CAMPAIGNS: tuple[tuple[str, str, str | None, int, dict[str, str] | None], ...] = (
    ("Six-month check-up reminders", "service", "existing_customer", 24, None),
    ("Whitening enquiry follow-up", "service", None, 9, {"start": "10:00", "end": "18:00"}),
    ("Diwali offer — purchased list", "promotional", "purchased_list", 12, None),
)

#: (kind, mapping, extra body). Meta brings the client's own App Secret; nothing is minted.
DEMO_SOURCES: tuple[tuple[str, dict[str, str], dict[str, Any]], ...] = (
    (
        "website_form",
        {"phone": "phone_number", "name": "full_name", "consent_field": "consent"},
        {},
    ),
    (
        "meta_lead_ads",
        {"phone": "phone_number", "consent_field": "consent_to_call"},
        {"app_secret": "demo-meta-app-secret"},
    ),
)

#: A public host, because `egress_guard` refuses loopback and private addresses at create.
DEMO_ENDPOINT_URL = "https://example.com/calevate-demo/events"


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _owner_id() -> UUID:
    from apps.api.db.session import untenanted_session

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT id FROM users WHERE lower(email) = lower(:e)"), {"e": OWNER_EMAIL}
            )
        ).first()
    if row is None:
        raise SystemExit("run `python -m scripts.seed_dev` first: the demo owner does not exist")
    return UUID(str(row[0]))


def _ok(response: httpx.Response, what: str) -> Any:
    if response.status_code >= 400:
        raise SystemExit(f"{what} was refused ({response.status_code}): {response.text}")
    return response.json() if response.content else None


def _contacts(offset: int, count: int) -> list[dict[str, str]]:
    names = ("Priya", "Ravi", "Lakshmi", "Arjun", "Sneha", "Kiran", "Meena", "Suresh")
    return [
        {"phone": f"{DEMO_RANGE}{offset + n:04d}", "name": names[n % len(names)]}
        for n in range(count)
    ]


async def _seed_campaigns(http: httpx.AsyncClient, headers: dict[str, str]) -> list[str]:
    agents = _ok(await http.get("/v1/agents", headers=headers), "listing agents")
    if not agents:
        return ["campaigns  skipped: the demo tenant has no agent"]
    agent_id = agents[0]["id"]
    existing = {
        row["name"]: row for row in _ok(await http.get("/v1/campaigns", headers=headers), "listing")
    }
    consent_day = (datetime.now(UTC) - timedelta(days=30)).replace(microsecond=0).isoformat()
    lines: list[str] = []
    for index, (name, kind, source, count, hours) in enumerate(DEMO_CAMPAIGNS):
        if name in existing:
            campaign_id = existing[name]["id"]
            lines.append(f"campaign   {name!r} already there ({existing[name]['status']})")
        else:
            body: dict[str, Any] = {
                "agent_id": agent_id,
                "name": name,
                "classification": kind,
                "concurrency": 3,
                "calling_hours": hours,
                "consent_provenance": (
                    {"source": source, "collected_at": consent_day} if source else None
                ),
            }
            created = _ok(await http.post("/v1/campaigns", json=body, headers=headers), name)
            campaign_id = created["id"]
            added = _ok(
                await http.post(
                    f"/v1/campaigns/{campaign_id}/contacts",
                    json={"contacts": _contacts(1000 + index * 100, count)},
                    headers=headers,
                ),
                f"contacts for {name}",
            )
            lines.append(f"campaign   {name!r} created, {added['added']} contacts")
        check = _ok(
            await http.get(f"/v1/campaigns/{campaign_id}/launch-check", headers=headers),
            "launch check",
        )
        rules = ", ".join(b["rule"] for b in check["blockers"]) or "none"
        lines.append(f"             ready={check['ready']}  blockers: {rules}")
    return lines


async def _seed_sources(http: httpx.AsyncClient, headers: dict[str, str]) -> list[str]:
    listed = _ok(await http.get("/v1/lead-sources", headers=headers), "listing lead sources")
    have = {item["source"] for item in listed["items"]}
    agents = _ok(await http.get("/v1/agents", headers=headers), "listing agents")
    lines: list[str] = []
    for kind, mapping, extra in DEMO_SOURCES:
        if kind in have:
            lines.append(f"source     {kind} already there")
            continue
        body = {"source": kind, "mapping": mapping, "agent_id": agents[0]["id"] if agents else None}
        body.update(extra)
        _ok(await http.post("/v1/lead-sources", json=body, headers=headers), f"source {kind}")
        lines.append(f"source     {kind} created")
    return lines


async def _seed_endpoint(http: httpx.AsyncClient, headers: dict[str, str]) -> list[str]:
    listed = _ok(await http.get("/v1/integrations/endpoints", headers=headers), "endpoints")
    if any(row["url"] == DEMO_ENDPOINT_URL for row in listed):
        return ["endpoint   already there"]
    body = {"url": DEMO_ENDPOINT_URL, "events": ["lead.created", "call.completed"]}
    response = await http.post("/v1/integrations/endpoints", json=body, headers=headers)
    if response.status_code >= 400:
        # The egress guard resolves the host; an offline laptop cannot, and that is not a
        # reason to abandon the rest of the seed.
        return [f"endpoint   not created ({response.status_code}): {response.text[:160]}"]
    return ["endpoint   created"]


async def seed_outreach() -> str:
    """Fill the demo tenant's outreach screens. Returns a short report for the terminal."""
    owner = await _owner_id()
    headers = {"Authorization": f"Bearer dev:client:{owner}", "X-Org-Slug": TENANT_SLUG}
    async with _client() as http:
        lines = await _seed_campaigns(http, headers)
        lines += await _seed_sources(http, headers)
        lines += await _seed_endpoint(http, headers)
    lines.append(
        "number     not seeded: numbers are supplied by the operator or a carrier, and the "
        "local stack has neither"
    )
    return "\n".join(["seeded outreach demo data", "", *lines])


def main(argv: list[str] | None = None) -> int:
    if argv:
        print(f"{__file__} takes no arguments (got {argv!r})", file=sys.stderr)
        return 2
    _refuse_unless_local()
    print(asyncio.run(seed_outreach()))
    return 0


if __name__ == "__main__":
    # psycopg's async mode cannot use Windows' default ProactorEventLoop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(main(sys.argv[1:]))
