"""Do-not-call: the write side of the suppression list (SEC-COMP §3, hard rule 5).

The test this module exists for is the first one: a number suppressed a moment ago is
not dialled a moment later. Everything else here defends the shape of that promise —
that the list cannot be widened by a typo, that a consumer's opt-out cannot be deleted
by the account it was made to, that one tenant's suppressions are invisible to another,
and that the numbers themselves never come back out in a response body.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import dnc
from apps.api.compliance.service import assert_dispatch_allowed, check_dispatch
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter
from apps.api.core.settings import Settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the gate's clock to 11:00 IST so `calling_hours` never masquerades as `dnc`
    — a suppression test that passes at 22:00 for the wrong reason proves nothing."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


def _number() -> str:
    """A fresh dialable Indian mobile. `dnc_list` is global-ish across a test run (a
    global row has no tenant), so reusing a constant would couple these tests."""
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


async def _tenant(role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """(tenant_id, agent_id, org slug, dev bearer token) for a fresh org with a member."""
    created = await admin_service.create_organization(
        name="DNC Motors",
        slug=f"dnc-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]

    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
    return tenant_id, agent_id, str(slug), f"dev:client:{clerk_id}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


def _code(response: object) -> str:
    """The stable machine identifier lives in `type`'s last segment, not in a `code`
    key — RFC-9457 has no `code` field and `core/errors.py` does not invent one."""
    body = response.json()  # type: ignore[attr-defined]
    return str(body["type"]).rsplit("/", 1)[-1]


def _own(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Tenant-scope entries only. A GLOBAL row belongs to no tenant and is visible to
    every one of them, so any run of this suite sees the global rows other tests left
    behind — filtering is the honest way to assert about "this tenant's list"."""
    return [entry for entry in entries if entry["scope"] == "tenant"]


async def _insert_global(phone: str) -> uuid.UUID:
    """A global entry is deliberately NOT tenant-reachable (the RLS WITH CHECK forbids
    it), so the only honest way to make one in a test is the owner role — the same
    connection the migrations run under."""
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: a global DNC row bypasses RLS"
    entry_id = uuid.uuid4()
    owner = create_async_engine(owner_url)
    try:
        async with owner.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                    "created_at) VALUES (:id, NULL, :phone, 'global', 'regulator', now(), now())"
                ),
                {"id": entry_id, "phone": phone},
            )
    finally:
        await owner.dispose()
    return entry_id


async def test_a_number_suppressed_now_is_not_dialled_next_tick() -> None:
    """Hard rule 5, end to end: the gate reads the list live, so an addition lands
    before the next dispatch decision — no cache to invalidate, no tick to wait for."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    phone = _number()

    async with tenant_session(tenant_id) as session:
        before = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )
        assert before.allowed, f"baseline must be dialable, got {before.rule}"

        await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[phone], source="call_optout"
        )

        after = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )
    assert not after.allowed
    assert after.rule == "dnc"


async def test_add_counts_what_it_did_and_normalizes_the_way_the_lead_path_does() -> None:
    """One number typed twice is one suppression, not a duplicate report; a 10-digit
    mobile and its +91 spelling are the same number; unparseable input is counted, not
    guessed at."""
    tenant_id, _agent_id, _slug, _token = await _tenant()
    bare = f"98{uuid.uuid4().int % 100000000:08d}"

    async with tenant_session(tenant_id) as session:
        first = await dnc.add_numbers(
            session,
            tenant_id=tenant_id,
            raw_numbers=[bare, f"+91{bare}", _number(), "banana", "12"],
            source="manual",
        )
        assert (first.added, first.already_suppressed, first.malformed) == (2, 0, 2)

        second = await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[f"+91{bare}"], source="manual"
        )
        assert (second.added, second.already_suppressed) == (0, 1)

        # And the gate agrees the bare form reached it as E.164.
        check = await dnc.check_number(session, tenant_id=tenant_id, raw=bare)
    assert check.suppressed and check.scope == "tenant"


async def test_a_number_already_suppressed_globally_is_not_added_again() -> None:
    """The unique constraint is (tenant_id, phone_e164), so a tenant row shadowing a
    global one would NOT conflict — it would be a second row saying the same thing and
    an `added: 1` that changed nothing."""
    tenant_id, _agent_id, _slug, _token = await _tenant()
    phone = _number()
    await _insert_global(phone)

    async with tenant_session(tenant_id) as session:
        result = await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[phone], source="manual"
        )
        rows = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = :p"), {"p": phone}
            )
        ).scalar()
    assert (result.added, result.already_suppressed) == (0, 1)
    assert rows == 1


async def test_neither_the_add_response_nor_the_list_repeats_the_number() -> None:
    """Hard rule 6 at the serialization boundary. A suppression list is a list of people
    who asked us to stop calling — the most sensitive list an account holds."""
    _tenant_id, _agent_id, slug, token = await _tenant()
    phone = _number()

    async with _client() as http:
        created = await http.post(
            "/v1/dnc",
            headers=_headers(token, slug),
            json={"numbers": [phone], "source": "customer_request"},
        )
        listed = await http.get("/v1/dnc", headers=_headers(token, slug))

    assert created.status_code == 201, created.text
    assert created.json() == {"added": 1, "already_suppressed": 0, "malformed": 0}
    assert phone not in created.text and phone.lstrip("+") not in created.text

    assert listed.status_code == 200
    entries = _own(listed.json())
    assert len(entries) == 1
    assert phone not in listed.text and phone.lstrip("+") not in listed.text
    assert entries[0]["phone_masked"] == f"••••••{phone[-2:]}"
    assert entries[0]["removable"] is False, "a consumer request is not the client's to undo"


async def test_checking_a_number_is_a_post_and_answers_what_the_gate_would() -> None:
    """A GET would write the number into access logs, proxy logs and browser history —
    the same reason the subject-access export is a POST."""
    _tenant_id, _agent_id, slug, token = await _tenant()
    suppressed, clean = _number(), _number()

    async with _client() as http:
        await http.post(
            "/v1/dnc",
            headers=_headers(token, slug),
            json={"numbers": [suppressed], "source": "manual"},
        )
        hit = await http.post(
            "/v1/dnc/check", headers=_headers(token, slug), json={"phone": suppressed}
        )
        miss = await http.post(
            "/v1/dnc/check", headers=_headers(token, slug), json={"phone": clean}
        )
        junk = await http.post(
            "/v1/dnc/check", headers=_headers(token, slug), json={"phone": "not a number"}
        )
        as_a_get = await http.get(
            f"/v1/dnc/check?phone={suppressed}", headers=_headers(token, slug)
        )

    assert hit.json() == {"valid": True, "suppressed": True, "scope": "tenant"}
    assert miss.json() == {"valid": True, "suppressed": False, "scope": None}
    assert junk.json() == {"valid": False, "suppressed": False, "scope": None}
    assert as_a_get.status_code == 405, "there must be no GET form to leak into a log"


async def test_a_global_suppression_is_visible_to_a_tenant_and_not_removable() -> None:
    """Visible because a nationally suppressed number a client cannot see is a number
    they will keep re-adding to campaigns; not removable because it is not theirs."""
    _tenant_id, _agent_id, slug, token = await _tenant()
    phone = _number()
    entry_id = await _insert_global(phone)

    async with _client() as http:
        listed = await http.get("/v1/dnc", headers=_headers(token, slug))
        deleted = await http.delete(f"/v1/dnc/{entry_id}", headers=_headers(token, slug))

    entry = next(e for e in listed.json() if e["id"] == str(entry_id))
    assert entry["scope"] == "global" and entry["removable"] is False
    assert deleted.status_code == 422
    assert _code(deleted) == "dnc_global_entry"


async def test_a_client_can_undo_its_own_typo_but_not_a_consumers_opt_out() -> None:
    """The distinction the whole removal rule exists for: fix your own paste, never
    delete someone else's request."""
    tenant_id, _agent_id, slug, token = await _tenant()
    typo, optout = _number(), _number()

    async with tenant_session(tenant_id) as session:
        await dnc.add_numbers(session, tenant_id=tenant_id, raw_numbers=[typo], source="manual")
        await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[optout], source="call_optout"
        )
        ids = {
            row[1]: row[0]
            for row in (
                await session.execute(
                    text("SELECT id, source FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
                )
            ).all()
        }

    async with _client() as http:
        undone = await http.delete(f"/v1/dnc/{ids['manual']}", headers=_headers(token, slug))
        refused = await http.delete(f"/v1/dnc/{ids['call_optout']}", headers=_headers(token, slug))

    # 204 with no body: the row that was just deleted holds a phone number, and the
    # answer to "please forget this" is the one response that must not repeat it. The
    # `{"status": "removed"}` this replaced said nothing a 2xx on a DELETE did not.
    assert undone.status_code == 204 and undone.content == b""
    assert refused.status_code == 422
    assert _code(refused) == "dnc_consumer_optout"

    async with tenant_session(tenant_id) as session:
        remaining = (
            await session.execute(
                text("SELECT source FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalars()
    assert list(remaining) == ["call_optout"]


async def test_removal_is_audited_by_id_and_never_by_number() -> None:
    tenant_id, _agent_id, slug, token = await _tenant()
    phone = _number()

    async with tenant_session(tenant_id) as session:
        await dnc.add_numbers(session, tenant_id=tenant_id, raw_numbers=[phone], source="manual")
        entry_id = (
            await session.execute(
                text("SELECT id FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()

    async with _client() as http:
        await http.delete(f"/v1/dnc/{entry_id}", headers=_headers(token, slug))

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT object_id, actor_type FROM audit_log WHERE action = 'dnc.removed' "
                    "AND tenant_id = :t ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": tenant_id},
            )
        ).first()
    assert row is not None, "removing a suppression must leave a record of who did it"
    # The entry id, never the number. (`write_audit`'s `summary` is deliberately not a
    # column — it goes to the log stream keyed by entry id — so the row itself can only
    # ever carry the id, which is the property this test is here to keep true.)
    assert row[0] == str(entry_id)
    assert row[1] == "user"


async def test_one_tenants_suppressions_are_invisible_to_another() -> None:
    _a_id, _a_agent, slug_a, token_a = await _tenant()
    _b_id, _b_agent, slug_b, token_b = await _tenant()
    phone = _number()

    async with _client() as http:
        await http.post("/v1/dnc", headers=_headers(token_a, slug_a), json={"numbers": [phone]})
        b_list = await http.get("/v1/dnc", headers=_headers(token_b, slug_b))
        b_check = await http.post(
            "/v1/dnc/check", headers=_headers(token_b, slug_b), json={"phone": phone}
        )

    assert _own(b_list.json()) == []
    assert b_check.json()["suppressed"] is False, "A's suppression must not leak into B"


async def test_an_unknown_source_is_refused_by_name() -> None:
    tenant_id, _agent_id, _slug, _token = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as caught:
            await dnc.add_numbers(
                session, tenant_id=tenant_id, raw_numbers=[_number()], source="vibes"
            )
    assert caught.value.code == "dnc_unknown_source"


async def test_a_paste_of_nothing_dialable_adds_nothing_and_says_how_much_it_dropped() -> None:
    """A list where every line is unusable must report `malformed`, not a silent zero.

    This is the shape of a real accident: a column paste that picked up the header row,
    or a CSV whose numbers arrived as `#ERROR`. The client believes they suppressed a
    list; the truthful answer is that nothing was suppressed and how many lines were
    unreadable, because a quiet `added: 0` is what lets them close the screen and let
    the campaign dial.
    """
    tenant_id, _agent_id, _slug, _token = await _tenant()

    async with tenant_session(tenant_id) as session:
        result = await dnc.add_numbers(
            session,
            tenant_id=tenant_id,
            raw_numbers=["phone", "", "+91", "12345"],
            source="manual",
        )

    assert result.added == 0
    assert result.already_suppressed == 0
    assert result.malformed == 4, "every unreadable line has to be counted, not swallowed"

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert rows == 0, "an unreadable line must never become a suppression row"


async def test_removing_an_entry_that_is_not_ours_is_a_404_and_not_a_500() -> None:
    """An entry id this tenant cannot see is "not found", the same answer as an id that
    never existed.

    Both halves matter. The 404 rather than a 500 is the interface; the 404 rather than
    a 403 is the tenancy property — a distinguishable "exists, but not yours" would let
    one client probe another client's suppression list one id at a time, and the ids are
    the only handles on numbers this surface hands out.
    """
    _tenant_id, _agent_id, slug, token = await _tenant()
    other_id, _other_agent, _other_slug, _other_token = await _tenant()
    phone = _number()

    async with tenant_session(other_id) as session:
        await dnc.add_numbers(session, tenant_id=other_id, raw_numbers=[phone], source="manual")
        neighbours_entry = (
            await session.execute(
                text("SELECT id FROM dnc_list WHERE tenant_id = :t"), {"t": other_id}
            )
        ).scalar()

    async with _client() as http:
        invented = await http.delete(f"/v1/dnc/{uuid.uuid4()}", headers=_headers(token, slug))
        neighbours = await http.delete(f"/v1/dnc/{neighbours_entry}", headers=_headers(token, slug))

    assert invented.status_code == 404, invented.text
    assert neighbours.status_code == 404, "another tenant's entry is not found, not forbidden"
    assert neighbours.status_code == invented.status_code, (
        "the two answers must be indistinguishable, or the id space becomes an oracle"
    )

    # And the neighbour still has their suppression — a 404 that quietly deleted it
    # would be the worst of both.
    async with tenant_session(other_id) as session:
        survived = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE id = :i"), {"i": neighbours_entry}
            )
        ).scalar()
    assert survived == 1


class _StolenUnderneath:
    """An `AsyncSession` that lets a second writer delete the row between the lookup and
    the DELETE — the race `remove_entry`'s rowcount check exists for."""

    def __init__(self, inner: object, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> None:
        self._inner = inner
        self._tenant_id = tenant_id
        self._entry_id = entry_id
        self._armed = True

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    async def execute(self, statement: object, params: object = None) -> object:
        result = await self._inner.execute(statement, params)  # type: ignore[attr-defined]
        if self._armed:
            # Fires once, right after the SELECT that decided the row is removable.
            self._armed = False
            async with tenant_session(self._tenant_id) as rival:
                await rival.execute(
                    text("DELETE FROM dnc_list WHERE id = :i"), {"i": self._entry_id}
                )
        return result


async def test_a_removal_that_deletes_no_row_reports_not_found_rather_than_success() -> None:
    """When the DELETE affects zero rows, the caller must be told the entry is gone —
    never handed a 2xx for work that did not happen.

    Two things arrive at this branch: two people removing the same entry at once (the
    race staged here), and RLS silently refusing the write on a row the non-locking
    lookup could still read. A success answer would tell a client their number is back
    in the campaign when it is not — and on this surface the client's next act is to
    dial it.
    """
    tenant_id, _agent_id, _slug, _token = await _tenant()
    phone = _number()

    async with tenant_session(tenant_id) as session:
        await dnc.add_numbers(session, tenant_id=tenant_id, raw_numbers=[phone], source="manual")
        entry_id = (
            await session.execute(
                text("SELECT id FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()

    async with tenant_session(tenant_id) as session:
        racing = _StolenUnderneath(session, tenant_id, uuid.UUID(str(entry_id)))
        with pytest.raises(ProblemError) as caught:
            await dnc.remove_entry(racing, entry_id=uuid.UUID(str(entry_id)))  # type: ignore[arg-type]

    assert caught.value.status == 404
    assert caught.value.code == "not_found"
    assert "dnc entry" in caught.value.detail.lower(), caught.value.detail


async def test_the_raising_gate_refuses_a_suppressed_number_by_name_and_logs_no_digits(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`assert_dispatch_allowed` is the form used by dial paths that have no screen to
    render a refusal on, so its refusal has to carry everything downstream needs.

    Three properties in one, because on this path they are one event: it RAISES rather
    than returning a decision nobody checked (a caller that forgets to read `.allowed`
    places the call — which is why the raising form exists at all); the machine code
    names the rule that blocked it, so an operator reading a failed dial knows whether
    to look at the DNC list or at consent; and the log line it leaves behind carries the
    rule and the tenant and never the number (hard rule 6), because the numbers this
    gate refuses are precisely the ones a person asked us to stop holding out loud.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    phone = _number()
    formatter = JsonFormatter()

    async with tenant_session(tenant_id) as session:
        # Allowed: it returns None. Nothing raised, nothing for a caller to forget.
        assert (
            await assert_dispatch_allowed(
                session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
            )
            is None
        )

        await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[phone], source="call_optout"
        )

        with caplog.at_level(logging.INFO), pytest.raises(ProblemError) as caught:
            await assert_dispatch_allowed(
                session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
            )

    assert caught.value.code == "dispatch_blocked_dnc", "the code has to name the rule"
    assert caught.value.status == 422
    assert caught.value.remediation, "a refusal a caller cannot act on is a dead end"
    assert "do-not-call" in caught.value.detail.lower()

    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert "dispatch_blocked" in rendered, "an operator has to be able to see the refusal"
    assert str(tenant_id) in rendered
    assert phone not in rendered and phone.lstrip("+") not in rendered
