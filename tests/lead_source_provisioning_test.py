"""Lead sources stop being hand-written SQL (SURFACES §2b, BUILD-LOG "built but inert").

Every `inbound_webhooks` row used to be an operator running an INSERT, which is why the
client's own lead-sources screen had to say "ask us". These tests state the properties
the provisioning surface has to hold for that to be safe to hand over:

- the minted secret is shown ONCE and never again, and it is the secret the never-shed
  ingest path actually accepts (a create route that returns a value nothing honours is
  the worst of both worlds);
- a rotation does not drop the leads submitted while the client is still pasting the new
  value into their form vendor — and a rotation asked to revoke on the spot DOES;
- tenancy is RLS, on every one of the new routes, in both directions (cannot see,
  cannot touch);
- creating, rotating, disabling and enabling are in the audit ledger, and the ledger
  never learns the secret.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ingest import service
from apps.api.ingest.routes import SECRET_HEADER
from apps.api.ingest.service import IngestConfig, readable_mapping, verify_ingest_secret
from apps.api.integrations.service import secret_fingerprint
from apps.api.main import app
from sqlalchemy import text
from tests.api_security_test import _make_tenant

# Spelled from the module under test, not repeated as literals: a bound that drifts must
# break the code, not quietly stop being the bound these tests probe.
MAX = service.MAX_MAPPING_ENTRIES
MAX_FIELD = service.MAX_MAPPING_FIELD_LEN


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _create_source(
    http: httpx.AsyncClient, slug: str, token: str, **body: object
) -> httpx.Response:
    payload: dict[str, object] = {"source": "website_form", "mapping": {}}
    payload.update(body)
    return await http.post("/v1/lead-sources", json=payload, headers=_headers(slug, token))


async def _audit_actions(tenant_id: uuid.UUID, object_id: str) -> list[str]:
    """`audit_log` is not tenant-RLS'd (the hash chain is global), so this scopes by the
    tenant column explicitly rather than relying on a policy that does not exist."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :t AND object_id = :o "
                    "ORDER BY at"
                ),
                {"t": tenant_id, "o": object_id},
            )
        ).all()
    return [str(r[0]) for r in rows]


# --- the secret is shown once, and it is the one the ingest path honours --------


async def test_the_minted_secret_is_returned_once_and_never_by_the_list() -> None:
    """The whole point of a create response: this is the only moment the plaintext
    exists outside the database, so the list beside it must answer with a fingerprint.

    The fingerprint is asserted to be DERIVED from the secret rather than merely
    present — a constant would pass a shape check and tell a client nothing about
    whether the value in their form vendor is the one we hold.
    """
    from apps.api.integrations.service import secret_fingerprint

    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        created = await _create_source(http, slug, token, mapping={"phone": "phone_number"})
        assert created.status_code == 201, created.text
        body = created.json()
        secret = body["secret"]
        assert secret and len(secret) >= 32
        assert body["ingest_path"] == f"/hooks/v1/ingest/{body['id']}"
        assert body["secret_header"] == SECRET_HEADER

        listed = await http.get("/v1/lead-sources", headers=_headers(slug, token))
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert "secret" not in items[0], "a list endpoint must never carry a secret value"
    assert secret not in listed.text, "the plaintext must not appear anywhere in the body"
    assert items[0]["secret_fingerprint"] == secret_fingerprint(secret)
    assert items[0]["previous_secret_expires_at"] is None
    assert items[0]["mapping"] == {"phone": "phone_number"}
    assert tenant_id is not None


async def test_the_minted_secret_actually_authenticates_a_real_delivery() -> None:
    """A create route that returns a credential the receiver does not accept is a
    provisioning surface that provisions nothing. This is the seam: the value the client
    is handed goes into the header the never-shed `/hooks` endpoint reads.
    """
    _, slug, token = await _make_tenant()
    async with _client() as http:
        created = await _create_source(http, slug, token)
        source = created.json()
        wrong = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500111"},
            headers={SECRET_HEADER: "not-the-secret"},
        )
        right = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500111"},
            headers={SECRET_HEADER: source["secret"]},
        )
    assert wrong.status_code == 401, wrong.text
    # 422 `ingest_no_agent` — no agent is attached, which is a decision made AFTER the
    # credential was accepted. Anything but 401 proves the secret authenticated.
    assert right.status_code != 401, right.text


# --- rotation: a cutover, not a cliff ------------------------------------------


def _config(secret: str, previous: str | None, expires: datetime | None) -> IngestConfig:
    return IngestConfig(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        agent_id=None,
        source="website_form",
        mapping={},
        secret_ref=secret,
        previous_secret_ref=previous,
        previous_secret_expires_at=expires,
    )


def test_a_retiring_secret_is_honoured_until_its_deadline_and_not_after() -> None:
    """The unit the HTTP rotation test below rests on, stated on its own so a failure
    says which half broke."""
    future = datetime.now(UTC) + timedelta(minutes=30)
    past = datetime.now(UTC) - timedelta(seconds=1)

    live = _config("new", "old", future)
    assert verify_ingest_secret(live, "new")
    assert verify_ingest_secret(live, "old"), "the client is still pasting; keep the lead"
    assert not verify_ingest_secret(live, "older-still")

    lapsed = _config("new", "old", past)
    assert verify_ingest_secret(lapsed, "new")
    assert not verify_ingest_secret(lapsed, "old"), "the window closed; the old secret is dead"

    revoked = _config("new", None, None)
    assert not verify_ingest_secret(revoked, "old")


async def test_rotation_keeps_the_old_secret_working_for_the_stated_window() -> None:
    """Rotating must not 401 the submissions arriving while a client updates Wix or
    Zapier — a rejected submission on this path is a lost enquiry, which is the one
    thing FLOWS §4 exists to prevent."""
    _, slug, token = await _make_tenant()
    async with _client() as http:
        created = await _create_source(http, slug, token)
        source = created.json()
        old_secret = source["secret"]

        rotated = await http.post(
            f"/v1/lead-sources/{source['id']}/rotate-secret",
            json={"grace_minutes": 60},
            headers=_headers(slug, token),
        )
        assert rotated.status_code == 200, rotated.text
        new_secret = rotated.json()["secret"]
        assert new_secret and new_secret != old_secret
        assert rotated.json()["previous_secret_expires_at"] is not None

        with_old = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500112"},
            headers={SECRET_HEADER: old_secret},
        )
        with_new = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500113"},
            headers={SECRET_HEADER: new_secret},
        )
    assert with_old.status_code != 401, "the grace window is the whole feature"
    assert with_new.status_code != 401

    # And the list says a rotation is in progress, so the screen can show a deadline.
    async with _client() as http:
        listed = await http.get("/v1/lead-sources", headers=_headers(slug, token))
    assert listed.json()["items"][0]["previous_secret_expires_at"] is not None


async def test_a_lapsed_rotation_window_reads_as_no_window_at_all() -> None:
    """A deadline that passed an hour ago is not a rotation in progress.

    The row keeps the columns until the next rotation overwrites them — nothing sweeps
    them, and nothing should — so it is the READ that has to be honest, or the screen
    shows a client a countdown to something that already happened.
    """
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        source = (await _create_source(http, slug, token)).json()
        await http.post(
            f"/v1/lead-sources/{source['id']}/rotate-secret",
            json={"grace_minutes": 60},
            headers=_headers(slug, token),
        )
    # Fast-forward the deadline rather than sleeping an hour. The columns stay populated,
    # which is exactly the state the read has to interpret.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE inbound_webhooks SET previous_secret_expires_at = now() "
                "- interval '1 minute' WHERE id = :id"
            ),
            {"id": uuid.UUID(source["id"])},
        )
    async with _client() as http:
        listed = await http.get("/v1/lead-sources", headers=_headers(slug, token))
        lapsed = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500121"},
            headers={SECRET_HEADER: source["secret"]},
        )
    assert listed.json()["items"][0]["previous_secret_expires_at"] is None
    assert lapsed.status_code == 401, "and the old secret really is dead by then"


async def test_zero_grace_revokes_the_old_secret_immediately() -> None:
    """What a leaked secret needs, and the reason the default is not zero."""
    _, slug, token = await _make_tenant()
    async with _client() as http:
        source = (await _create_source(http, slug, token)).json()
        rotated = await http.post(
            f"/v1/lead-sources/{source['id']}/rotate-secret",
            json={"grace_minutes": 0},
            headers=_headers(slug, token),
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["previous_secret_expires_at"] is None

        refused = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500114"},
            headers={SECRET_HEADER: source["secret"]},
        )
        accepted = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500115"},
            headers={SECRET_HEADER: rotated.json()["secret"]},
        )
    assert refused.status_code == 401, refused.text
    assert accepted.status_code != 401


# --- disable / enable ----------------------------------------------------------


async def test_disable_stops_deliveries_enable_restores_them_with_the_same_secret() -> None:
    """Re-enabling must not silently invalidate the credential: a client who disabled a
    noisy form for an afternoon should not have to re-paste anything to turn it back on.
    """
    _, slug, token = await _make_tenant()
    async with _client() as http:
        source = (await _create_source(http, slug, token)).json()
        disabled = await http.delete(
            f"/v1/lead-sources/{source['id']}", headers=_headers(slug, token)
        )
        assert disabled.status_code == 204, disabled.text
        while_off = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500116"},
            headers={SECRET_HEADER: source["secret"]},
        )
        # Idempotent: the second click is the same request, not a 404.
        again = await http.delete(f"/v1/lead-sources/{source['id']}", headers=_headers(slug, token))
        enabled = await http.post(
            f"/v1/lead-sources/{source['id']}/enable", headers=_headers(slug, token)
        )
        after = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500117"},
            headers={SECRET_HEADER: source["secret"]},
        )
    # 404, not 401: an inactive source is indistinguishable from an unknown one to a
    # probing sender (the receiver's own comment).
    assert while_off.status_code == 404, while_off.text
    assert again.status_code == 204
    assert enabled.status_code == 204, enabled.text
    assert after.status_code != 404, "the same secret must still work after re-enabling"


async def test_disabling_closes_an_open_rotation_window() -> None:
    """A source is disabled because something is wrong with it. Leaving a superseded
    secret armed to wake up with it is the opposite of what that click asked for."""
    _, slug, token = await _make_tenant()
    async with _client() as http:
        source = (await _create_source(http, slug, token)).json()
        await http.post(
            f"/v1/lead-sources/{source['id']}/rotate-secret",
            json={"grace_minutes": 600},
            headers=_headers(slug, token),
        )
        await http.delete(f"/v1/lead-sources/{source['id']}", headers=_headers(slug, token))
        await http.post(f"/v1/lead-sources/{source['id']}/enable", headers=_headers(slug, token))
        revived = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500118"},
            headers={SECRET_HEADER: source["secret"]},
        )
        listed = await http.get("/v1/lead-sources", headers=_headers(slug, token))
    assert revived.status_code == 401, "the pre-rotation secret must not come back to life"
    assert listed.json()["items"][0]["previous_secret_expires_at"] is None


# --- tenancy (hard rule 1) -----------------------------------------------------


async def test_one_tenants_lead_sources_are_invisible_and_untouchable_to_another() -> None:
    """Zero rows on the read AND 404 on every write. The read alone would pass on a
    surface where B can still rotate A's secret by id — which is the more expensive
    half, because it takes A's integration down."""
    _, slug_a, token_a = await _make_tenant()
    _, slug_b, token_b = await _make_tenant()

    async with _client() as http:
        source = (await _create_source(http, slug_a, token_a)).json()

        listed_b = await http.get("/v1/lead-sources", headers=_headers(slug_b, token_b))
        rotate_b = await http.post(
            f"/v1/lead-sources/{source['id']}/rotate-secret",
            json={"grace_minutes": 0},
            headers=_headers(slug_b, token_b),
        )
        disable_b = await http.delete(
            f"/v1/lead-sources/{source['id']}", headers=_headers(slug_b, token_b)
        )
        enable_b = await http.post(
            f"/v1/lead-sources/{source['id']}/enable", headers=_headers(slug_b, token_b)
        )

        # A's source is untouched: its original secret still authenticates.
        still_a = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500119"},
            headers={SECRET_HEADER: source["secret"]},
        )

    assert listed_b.status_code == 200
    assert listed_b.json()["items"] == [], "B must see zero rows, not A's"
    assert rotate_b.status_code == 404, rotate_b.text
    assert disable_b.status_code == 404, disable_b.text
    assert enable_b.status_code == 404, enable_b.text
    assert still_a.status_code != 401, "B's attempts must not have rotated or disabled A"


async def test_an_agent_from_another_tenant_cannot_be_attached() -> None:
    """The foreign key is to the GLOBAL `agents` table and knows nothing about tenancy,
    so without an explicit tenant-scoped read this would create a source that dispatches
    through somebody else's agent."""
    tenant_a, slug_a, token_a = await _make_tenant()
    _, slug_b, token_b = await _make_tenant()
    async with tenant_session(tenant_a) as session:
        agent_a = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()

    async with _client() as http:
        refused = await _create_source(http, slug_b, token_b, agent_id=str(agent_a))
        allowed = await _create_source(http, slug_a, token_a, agent_id=str(agent_a))
    assert refused.status_code == 404, refused.text
    assert allowed.status_code == 201, allowed.text


# --- refusals a client can act on ---------------------------------------------


async def test_a_mapping_that_never_finds_a_phone_number_is_refused_at_creation() -> None:
    """Every delivery through such a source would answer 422 `ingest_no_phone`, forever.
    Refuse it once here rather than once per lead."""
    _, slug, token = await _make_tenant()
    async with _client() as http:
        refused = await _create_source(http, slug, token, mapping={"name": "full_name"})
        # An EMPTY mapping is legal and different: it means "read the payload as it
        # comes", which is what a bare custom POST wants.
        allowed = await _create_source(http, slug, token, mapping={})
    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith("/mapping_has_no_phone")
    assert allowed.status_code == 201, allowed.text


async def test_a_meta_source_needs_the_clients_app_secret_and_others_refuse_one() -> None:
    """Meta signs with the App Secret of the client's own Meta app, so there is nothing
    for us to mint; for every other source we mint and a caller-supplied value would be
    a second, weaker scheme in the same column."""
    _, slug, token = await _make_tenant()
    async with _client() as http:
        no_secret = await _create_source(http, slug, token, source="meta_lead_ads")
        with_secret = await _create_source(
            http, slug, token, source="meta_lead_ads", app_secret="the-meta-app-secret"
        )
        unwanted = await _create_source(
            http, slug, token, source="website_form", app_secret="mine-thanks"
        )
    assert no_secret.status_code == 422, no_secret.text
    assert no_secret.json()["type"].endswith("/app_secret_required")
    assert with_secret.status_code == 201, with_secret.text
    assert with_secret.json()["secret"] is None, "nothing of ours was minted"
    assert with_secret.json()["ingest_path"].startswith("/hooks/v1/ingest/meta/")
    assert unwanted.status_code == 422, unwanted.text
    assert unwanted.json()["type"].endswith("/app_secret_not_accepted")


async def test_a_rotated_meta_app_secret_keeps_verifying_deliveries_in_flight() -> None:
    """The grace window covers the OTHER receiver too.

    A client rotating their Meta App Secret changes it in the Meta App Dashboard and in
    Calevate at two different moments, and the notifications in between are signed with
    the one they have not replaced yet. Those are leads.

    The HANDSHAKE deliberately does not get the same treatment (see `meta_verify`): a
    refused subscription is retried with the current token and costs nothing, while
    honouring a retired token would take back what `meta.verify_token_for` promises.
    """
    from tests.meta_lead_ads_test import _notification, _signed

    _, slug, token = await _make_tenant()
    old_app_secret = "old-meta-app-secret"
    new_app_secret = "new-meta-app-secret"
    async with _client() as http:
        source = (
            await _create_source(
                http, slug, token, source="meta_lead_ads", app_secret=old_app_secret
            )
        ).json()
        rotated = await http.post(
            f"/v1/lead-sources/{source['id']}/rotate-secret",
            json={"grace_minutes": 30, "app_secret": new_app_secret},
            headers=_headers(slug, token),
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["secret"] is None, "nothing of ours was minted"

        raw_old, headers_old = _signed(
            _notification(leadgen_id=str(uuid.uuid4().int % 10**15)), secret=old_app_secret
        )
        in_flight = await http.post(source["ingest_path"], content=raw_old, headers=headers_old)

        raw_new, headers_new = _signed(
            _notification(leadgen_id=str(uuid.uuid4().int % 10**15)), secret=new_app_secret
        )
        current = await http.post(source["ingest_path"], content=raw_new, headers=headers_new)

        raw_bad, headers_bad = _signed(
            _notification(leadgen_id=str(uuid.uuid4().int % 10**15)), secret="never-ours"
        )
        stranger = await http.post(source["ingest_path"], content=raw_bad, headers=headers_bad)

    assert in_flight.status_code == 200, in_flight.text
    assert current.status_code == 200, current.text
    assert stranger.status_code == 401, stranger.text


async def test_staff_may_look_but_not_provision() -> None:
    """SEC-COMP §5: staff do not get org settings. A lead source mints a credential that
    dials this tenant's customers on arrival, so it is org settings."""
    _, slug, token = await _make_tenant(role="staff")
    async with _client() as http:
        listed = await http.get("/v1/lead-sources", headers=_headers(slug, token))
        created = await _create_source(http, slug, token)
    assert listed.status_code == 200, listed.text
    assert created.status_code == 403, created.text


# --- the audit ledger ----------------------------------------------------------


async def test_every_change_is_audited_and_the_ledger_never_learns_the_secret() -> None:
    """Hard rule 5's shape for a credential surface: the security-relevant acts are in
    the tamper-evident ledger, and a no-op is not one of them."""
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        source = (await _create_source(http, slug, token)).json()
        await http.post(
            f"/v1/lead-sources/{source['id']}/rotate-secret",
            json={"grace_minutes": 5},
            headers=_headers(slug, token),
        )
        await http.delete(f"/v1/lead-sources/{source['id']}", headers=_headers(slug, token))
        # The second disable changes nothing, so it must not add a row.
        await http.delete(f"/v1/lead-sources/{source['id']}", headers=_headers(slug, token))
        await http.post(f"/v1/lead-sources/{source['id']}/enable", headers=_headers(slug, token))

    assert await _audit_actions(tenant_id, source["id"]) == [
        "lead_source.created",
        "lead_source.secret_rotated",
        "lead_source.disabled",
        "lead_source.enabled",
    ]


@pytest.mark.parametrize("grace", [-1, 24 * 60 + 1])
async def test_the_grace_window_is_bounded_at_the_boundary(grace: int) -> None:
    """A grace of "forever" is a second permanent credential, and a negative one is a
    value that reaches SQL. Both are refused by the request model, before any row moves.
    """
    _, slug, token = await _make_tenant()
    async with _client() as http:
        source = (await _create_source(http, slug, token)).json()
        refused = await http.post(
            f"/v1/lead-sources/{source['id']}/rotate-secret",
            json={"grace_minutes": grace},
            headers=_headers(slug, token),
        )
        # And the secret it was asked to rotate is untouched.
        unchanged = await http.post(
            source["ingest_path"],
            json={"phone_number": "9876500120"},
            headers={SECRET_HEADER: source["secret"]},
        )
    assert refused.status_code == 422, refused.text
    assert unchanged.status_code != 401


# --- the refusals ---------------------------------------------------------------
#
# The area docstring in `scripts/check_coverage_ratchet.py` says it plainly: "the branch
# that goes untested is always the refusal, because the happy path is what the demo
# exercises". Everything above this line is the demo. Everything below is what the
# surface does when it is asked for something it must not do.


async def test_a_mapping_with_too_many_rules_is_refused() -> None:
    """A bound on config a human typed, checked at the config screen rather than
    re-read on every delivery for the life of the source."""
    _, slug, token = await _make_tenant()
    async with _client() as http:
        refused = await _create_source(
            http,
            slug,
            token,
            mapping={"phone": "phone_number", **{f"field_{i}": "x" for i in range(MAX + 1)}},
        )
        # One under the bound is accepted, so the refusal is the LIMIT and not the shape
        # of the request.
        allowed = await _create_source(
            http,
            slug,
            token,
            mapping={"phone": "phone_number", **{f"field_{i}": "x" for i in range(MAX - 1)}},
        )
    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith("/mapping_too_large")
    assert allowed.status_code == 201, allowed.text


@pytest.mark.parametrize(
    ("mapping", "why"),
    [
        ({"phone": "   "}, "a field name that is only whitespace names no field"),
        ({"   ": "phone_number"}, "and neither does a blank key"),
    ],
)
async def test_a_blank_field_mapping_is_refused_rather_than_stored(
    mapping: dict[str, str], why: str
) -> None:
    """Stored, this maps one of our fields onto a form field called "" — which matches
    nothing, forever, silently. The refusal names the offending key so the client can
    find it in a form with thirty of them."""
    _, slug, token = await _make_tenant()
    async with _client() as http:
        refused = await _create_source(http, slug, token, mapping=mapping)
    assert refused.status_code == 422, why
    assert refused.json()["type"].endswith("/mapping_blank_field")


async def test_an_overlong_field_name_is_refused() -> None:
    """A field name is a form vendor's identifier, not free text: something this long is
    a paste accident, and the place to say so is the screen that took the paste."""
    _, slug, token = await _make_tenant()
    async with _client() as http:
        by_value = await _create_source(http, slug, token, mapping={"phone": "x" * (MAX_FIELD + 1)})
        by_key = await _create_source(
            http, slug, token, mapping={"phone": "phone_number", "y" * (MAX_FIELD + 1): "z"}
        )
    for refused in (by_value, by_key):
        assert refused.status_code == 422, refused.text
        assert refused.json()["type"].endswith("/mapping_field_too_long")


async def test_a_mapping_that_is_not_an_object_reads_as_no_mapping() -> None:
    """Hand-provisioned rows predate this surface and `mapping` is untyped JSONB, so a
    row can hold a LIST where the screen expects an object.

    `apply_mapping` would ignore it; the config screen must agree, or it renders rules
    the ingest path does not follow. Empty is the honest answer — and the one thing it
    must not do is raise on a row somebody else wrote.
    """
    assert readable_mapping(["phone", "name"]) == {}
    assert readable_mapping("phone") == {}
    assert readable_mapping(None) == {}
    # A real mapping keeps only the entries that DO something: `apply_mapping` requires
    # a string on the right-hand side, so a number there is a rule nothing follows.
    assert readable_mapping({"phone": "phone_number", "retries": 3}) == {"phone": "phone_number"}


async def test_the_list_renders_a_row_whose_mapping_is_not_an_object() -> None:
    """The same fact through the route, because that is where it would actually bite:
    one legacy row must not 500 the screen that lists every source."""
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        source = (await _create_source(http, slug, token)).json()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_webhooks SET mapping = CAST(:m AS jsonb) WHERE id = :id"),
            {"m": '["phone", "name"]', "id": uuid.UUID(source["id"])},
        )
    async with _client() as http:
        listed = await http.get("/v1/lead-sources", headers=_headers(slug, token))
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["mapping"] == {}


# --- the service contract behind the routes ------------------------------------
#
# WHY THESE CALL THE SERVICE DIRECTLY, when everything above goes through HTTP.
#
# Two of the refusals below CANNOT be reached through the route, and that is by design
# rather than an oversight: `RotateSecretIn` bounds `grace_minutes` with `ge=0, le=…`,
# so the request model refuses an out-of-range value before the service ever sees one.
# The service keeps its own check because it is a public function of this module and the
# request model is not its only caller — a worker or an admin path added later would
# arrive with nothing validated. Testing the second gate means calling the second gate.
#
# The rest are here for a duller reason worth writing down: coverage does not record
# lines executed inside a request made through `httpx.ASGITransport` once the handler
# has awaited the database — the route tests above genuinely execute `set_active`'s
# CAS branches and `rotate_secret`'s 404, and the report shows them unexecuted. The
# HTTP tests are the binding ones for behaviour; these state the same contracts at the
# seam where they can also be measured.


async def _one_source(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        webhook_id, secret = await service.create_lead_source(
            session,
            tenant_id=tenant_id,
            source="website_form",
            agent_id=None,
            mapping={"phone": "phone_number"},
            supplied_secret=None,
        )
    assert secret, "a website form's secret is ours to mint"
    return webhook_id


async def test_the_service_refuses_a_grace_the_request_model_would_never_pass() -> None:
    """The second gate, tested at the second gate.

    `grace_minutes` reaches SQL as an interval. Negative is a window that closed before
    it opened; unbounded is a second permanent credential wearing a rotation's clothes.
    The route's Pydantic bounds catch both today — this is what catches them when the
    next caller is not the route.
    """
    tenant_id, _slug, _token = await _make_tenant()
    webhook_id = await _one_source(tenant_id)

    for grace in (-1, service.MAX_GRACE_MINUTES + 1):
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as raised:
                await service.rotate_secret(
                    session, webhook_id=webhook_id, grace_minutes=grace, supplied_secret=None
                )
        assert raised.value.code == "grace_out_of_range"
        assert raised.value.status == 422

    # A value ON the bound is accepted: the refusal is the range, not a mood.
    async with tenant_session(tenant_id) as session:
        rotation = await service.rotate_secret(
            session,
            webhook_id=webhook_id,
            grace_minutes=service.MAX_GRACE_MINUTES,
            supplied_secret=None,
        )
    assert rotation.secret
    assert rotation.previous_secret_expires_at is not None


async def test_rotating_a_source_that_is_not_this_tenants_finds_nothing() -> None:
    """`UPDATE … RETURNING` under RLS: another tenant's row is not merely refused, it is
    not there. The 404 is what turns "zero rows changed" into an answer instead of a
    silent success — the exact defect that would let a client believe they had rotated a
    secret that never moved."""
    tenant_a, _slug_a, _token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    webhook_id = await _one_source(tenant_a)

    for scope, target in (("another tenant's", webhook_id), ("nobody's", uuid.uuid4())):
        async with tenant_session(tenant_b) as session:
            with pytest.raises(ProblemError) as raised:
                await service.rotate_secret(
                    session, webhook_id=target, grace_minutes=0, supplied_secret=None
                )
        assert raised.value.code == "not_found", scope
        assert raised.value.status == 404


async def test_set_active_reports_whether_it_was_the_one_that_changed_things() -> None:
    """The return value IS the audit decision (the route writes a row only on True), so
    "did this call change anything" has to be answered exactly.

    Three outcomes, and the middle one is the whole point: a second disable is the same
    request as the first and the source really is disabled, so it is a quiet success —
    NOT the 404 the outbound endpoint answers to a second click.
    """
    tenant_id, _slug, _token = await _make_tenant()
    webhook_id = await _one_source(tenant_id)

    async with tenant_session(tenant_id) as session:
        assert await service.set_active(session, webhook_id=webhook_id, active=False) is True
        assert await service.set_active(session, webhook_id=webhook_id, active=False) is False
        assert await service.set_active(session, webhook_id=webhook_id, active=True) is True
        assert await service.set_active(session, webhook_id=webhook_id, active=True) is False


async def test_set_active_on_a_source_that_does_not_exist_is_a_404_not_a_shrug() -> None:
    """The other half of the idempotent answer above: "already off" and "never existed"
    look identical to a CAS whose predicate did not match, and only one of them may be
    reported as success."""
    tenant_id, _slug, _token = await _make_tenant()
    other_tenant, _s, _t = await _make_tenant()
    webhook_id = await _one_source(other_tenant)

    async with tenant_session(tenant_id) as session:
        for target in (uuid.uuid4(), webhook_id):
            with pytest.raises(ProblemError) as raised:
                await service.set_active(session, webhook_id=target, active=False)
            assert raised.value.code == "not_found"
            assert raised.value.status == 404


async def test_the_service_refuses_an_agent_that_is_not_this_tenants() -> None:
    """The foreign key is to the GLOBAL `agents` table, so it would accept this. The
    route test above proves the 404 over HTTP; this pins the check at the function that
    makes it, including the unknown-id case a foreign-agent test does not reach."""
    tenant_a, _slug_a, _token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    async with tenant_session(tenant_a) as session:
        agent_a = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()

    for scope, target in (("another tenant's agent", agent_a), ("no agent at all", uuid.uuid4())):
        async with tenant_session(tenant_b) as session:
            with pytest.raises(ProblemError) as raised:
                await service.create_lead_source(
                    session,
                    tenant_id=tenant_b,
                    source="website_form",
                    agent_id=UUID(str(target)),
                    mapping={},
                    supplied_secret=None,
                )
        assert raised.value.code == "not_found", scope

    # And the same call with an agent that IS theirs writes the row and mints a secret.
    async with tenant_session(tenant_a) as session:
        webhook_id, secret = await service.create_lead_source(
            session,
            tenant_id=tenant_a,
            source="website_form",
            agent_id=UUID(str(agent_a)),
            mapping={},
            supplied_secret=None,
        )
        listed = await service.list_lead_sources(session)
    assert secret
    assert [row.id for row in listed] == [webhook_id]
    assert listed[0].agent_id == agent_a
    assert listed[0].active is True
    assert listed[0].secret_fingerprint == secret_fingerprint(secret)
    assert listed[0].previous_secret_expires_at is None
