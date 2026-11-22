"""Every read the client Agents screens make answers for an account with two agents and no
campaigns: the list (`/c/[slug]/agents`), one agent's four tabs (`/c/[slug]/agents/[id]`) and
New agent (`/c/[slug]/agents/new`).

A read that 500s leaves its panel on an error or, where the screen waits on it, a skeleton
that never resolves, so each one is asked for here with the account those screens are first
opened on.
"""

from __future__ import annotations

import uuid

from tests.first_run_test import _client, _owner, _tenant

#: The reads the list and New agent make, by `apps/web/src/lib/api/*`.
ACCOUNT_READS = (
    "/v1/agents",
    "/v1/agents?status=archived",
    "/v1/agents/stats",
    "/v1/agents/lanes",
    "/v1/agents/starters",
    "/v1/agents/languages",
    "/v1/agents/engine-catalogue",
    "/v1/readiness?limit=200",
    "/v1/first-run",
    "/v1/trial",
    "/v1/trial/calls",
    "/v1/organization/llm-defaults",
    "/v1/organization/call-handling",
    "/v1/business-profile",
    "/v1/business-copy",
    "/v1/inbound-lines",
    "/v1/go-live",
    "/v1/kb/knows",
    "/v1/kb/notes",
    "/v1/kb/uploads",
    "/v1/teach/questions",
    "/v1/integrations/credentials",
    "/v1/integrations/connections/status",
    "/v1/team-alerts/contacts",
    "/v1/legal/readiness",
    "/v1/billing/wallet",
    "/v1/billing/spend",
    "/v1/me",
    "/v1/campaigns",
)

#: The reads one agent's screen makes, across Overview, Actions, Settings and Training.
AGENT_READS = (
    "",
    "/jobs",
    "/readiness",
    "/pending",
    "/engine-state",
    "/experiment",
    "/extraction-schema",
    "/handoff",
    "/call-handling",
    "/caller-help",
    "/call-mistakes",
    "/known-facts",
    "/team-alert",
    "/test-cases",
    "/voice-tuning",
    "/actions",
    "/script",
    "/script/tests",
)


async def _two_agents() -> tuple[dict[str, str], list[str]]:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        made = await http.put(
            "/v1/first-run/agent",
            headers=headers,
            json={"name": "Anjali", "language_primary": "te-IN", "languages_extra": []},
        )
        assert made.status_code == 200, made.text
        second = await http.post(
            "/v1/agents", headers=headers, json={"name": "Ravi", "language_primary": "en-IN"}
        )
        assert second.status_code in (200, 201), second.text
    return headers, [made.json()["agent_id"], second.json()["id"]]


async def test_every_read_on_the_agents_screens_answers() -> None:
    headers, agent_ids = await _two_agents()
    failed: dict[str, str] = {}
    async with _client() as http:
        for path in ACCOUNT_READS:
            got = await http.get(path, headers=headers)
            if got.status_code != 200:
                failed[path] = f"{got.status_code} {got.text[:200]}"
        for agent_id in agent_ids:
            paths = [f"/v1/agents/{agent_id}{tail}" for tail in AGENT_READS] + [
                f"/v1/calls?agent_id={agent_id}&limit=5",
                f"/v1/teach/questions?agent_id={agent_id}",
                f"/v1/compliance/promo-check/agents/{agent_id}",
            ]
            for path in paths:
                got = await http.get(path, headers=headers)
                if got.status_code != 200:
                    failed[path] = f"{got.status_code} {got.text[:200]}"
        listed = (await http.get("/v1/agents", headers=headers)).json()
    assert failed == {}
    assert {row["id"] for row in listed} == set(agent_ids)


async def test_an_agent_of_another_account_is_not_found() -> None:
    headers, _ = await _two_agents()
    _, theirs = await _two_agents()
    async with _client() as http:
        for tail in ("", "/jobs", "/readiness"):
            got = await http.get(f"/v1/agents/{theirs[0]}{tail}", headers=headers)
            assert got.status_code == 404, (tail, got.text)
        missing = await http.get(f"/v1/agents/{uuid.uuid4()}/jobs", headers=headers)
    assert missing.status_code == 404, missing.text
