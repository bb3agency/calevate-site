"""The invoice as a TAX document, and as the client's own (SLICE AL).

Two defects, one slice, and these tests pin both halves plus the seam between them.

**AL1 — the client could not see their own invoice.** It was admin-realm only while
BRD §51 names the client persona as the one who pays it. The fix is a second ROUTE, never
a second COMPUTATION, so the test that matters most in this file is the anti-fork one:
the client's document and ops's document must be identical field for field. A bill that
disagrees with itself is worse than a bill nobody can see.

**AL2 — it was not a valid Indian tax invoice.** It printed the word "Calevate" and
charged a flat 18% with no supplier GSTIN, no recipient GSTIN, no HSN/SAC, no place of
supply and no registered address, so a B2B client could not claim input credit against
it. The identity VALUES are a founder decision that has not been taken, so the code is
config-driven and the document refuses the "Tax Invoice" framing until they exist.

What each group here would cost if it broke, in order:

1. cross-tenant isolation (hard rule 1) — one client reading another's bill;
2. the two realms disagreeing;
3. an invalid document that calls itself a tax invoice;
4. the tax landing under the wrong head, which silently voids the recipient's credit;
5. a float anywhere near a rupee (hard rule 7).

Run: uv run pytest -q tests/invoice_gst_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.gst import (
    UT_WITHOUT_LEGISLATURE,
    parse_gstin,
    resolve_place_of_supply,
    split_tax,
    supplier_identity,
)
from apps.api.billing.invoice import RULE_46B_MAX_SERIAL_CHARS, build_invoice
from apps.api.billing.service import to_paise
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

CLIENT_PATH = "/v1/billing/invoice"

# Specimen GSTINs — structurally valid, deliberately in three different States so the
# place-of-supply branches are decidable. `36` is Telangana (our notional home),
# `29` Karnataka (a different State → IGST) and `04` Chandigarh (a Union Territory with
# no legislature → CGST + UTGST). None of these is a real registration and none of them
# is a value this repo may ship: they exist only inside this file.
SUPPLIER_GSTIN = "36AABCC1234D1Z5"
SAME_STATE_GSTIN = "36AAACR5055K1Z7"
OTHER_STATE_GSTIN = "29AAACR5055K1Z6"
UNION_TERRITORY_GSTIN = "04AAACR5055K1Z1"


@pytest.fixture
def gst_registered(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Configure the supplier identity for one test, then put it back.

    `get_settings` is `lru_cache`d, so the cache is cleared on the way in AND out —
    otherwise the first test to touch these keys would decide the answer for every test
    that ran afterwards in the same process.
    """

    def _configure(gstin: str = SUPPLIER_GSTIN, sac: str = "998315") -> None:
        monkeypatch.setenv("GST_SUPPLIER_LEGAL_NAME", "Calevate Technologies Private Limited")
        monkeypatch.setenv("GST_SUPPLIER_ADDRESS", "Plot 42, Madhapur, Hyderabad 500081")
        monkeypatch.setenv("GST_SUPPLIER_GSTIN", gstin)
        monkeypatch.setenv("GST_SUPPLY_SAC", sac)
        get_settings.cache_clear()
        get_settings()

    yield _configure
    get_settings.cache_clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


async def _tenant_with_usage(minutes: int = 120) -> dict[str, Any]:
    """A tenant with a plan fee and billable overage — the shape whose totals are worth
    comparing across two realms."""
    created = await admin_service.create_organization(
        name="Sri Traders",
        slug=f"gst-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="accounts@sritraders.example",
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), created["agent_id"]
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "concurrency_ceiling, created_at, updated_at) VALUES (:i, :t, 9999.00, 100, "
                "8.0000, 10, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', "
                ":qty, 0.5000, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "qty": Decimal(minutes * 60)},
        )
    return created


async def _verify_gstin(org: dict[str, Any], gstin: str) -> None:
    """Record the client's GST registration the way production does — through the
    audited ops route, never by writing `kyc_records` here. A test that seeds its own row
    passes against a schema the writer no longer produces."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{org['id']}/kyc",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "status": "verified",
                "entity_type": "private_limited",
                "document_kind": "gstin",
                "document_ref": gstin,
                "signatory_name": "A Signatory",
                "evidence_ref": "ops-ticket-9001",
            },
        )
    assert response.status_code == 200, response.text


async def _client_headers(org: dict[str, Any], role: str = "owner") -> dict[str, str]:
    token = await _make_member(uuid.UUID(str(org["id"])), role=role)
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])}


# -------------------------------------------------- AL1: the client's own bill, and only theirs


async def test_a_client_can_read_their_own_invoice() -> None:
    """The whole point of AL1. `billing:read` from the client realm, tenant taken from
    the principal — there is no tenant parameter to supply or to tamper with."""
    org = await _tenant_with_usage()

    async with _client() as http:
        response = await http.get(CLIENT_PATH, headers=await _client_headers(org))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organization"]["id"] == str(org["id"])
    assert body["subtotal_inr"] == "10159.00"


async def test_a_client_cannot_read_another_tenants_invoice() -> None:
    """Hard rule 1, and the reason the route has no tenant parameter.

    Tenant B holds a token for B and asks the only invoice endpoint their realm has. The
    isolation is structural — the path names no tenant and the session is RLS-scoped on
    the principal's — so what B receives is B's document, never A's, and there is no
    parameter through which B could even express the request.
    """
    tenant_a = await _tenant_with_usage(minutes=120)
    tenant_b = await _tenant_with_usage(minutes=0)

    async with _client() as http:
        as_b = await http.get(CLIENT_PATH, headers=await _client_headers(tenant_b))
        # And the admin path, which DOES name a tenant, refuses a client token outright
        # rather than serving A's bill to B's owner.
        crossed = await http.get(
            f"/v1/admin/tenants/{tenant_a['id']}/invoice",
            headers=await _client_headers(tenant_b),
        )

    assert as_b.status_code == 200, as_b.text
    assert as_b.json()["organization"]["id"] == str(tenant_b["id"])
    assert as_b.json()["organization"]["id"] != str(tenant_a["id"])
    # B's own statement carries B's (absent) usage, never A's ₹10,159.
    assert as_b.json()["subtotal_inr"] == "9999.00"
    assert crossed.status_code in (401, 403), crossed.text


async def test_staff_cannot_read_the_invoice() -> None:
    """`billing:read` is an owner permission — spend is an owner's business (SEC-COMP §5),
    and this is the same gate `GET /v1/usage` already applies."""
    org = await _tenant_with_usage()

    async with _client() as http:
        response = await http.get(CLIENT_PATH, headers=await _client_headers(org, role="staff"))

    assert response.status_code == 403, response.text


async def test_the_client_read_writes_nothing(gst_registered: Any) -> None:
    """D-64: rendering an invoice used to append the setup charge, which put a write
    behind a GET. The client path must never reintroduce one — an impersonating operator
    (D-22, read-only) opening a client's invoice would otherwise be performing a billing
    write from a session that is forbidden to write.

    Asserted on the LEDGERS rather than on the code, because that is the property that
    matters: two GETs, and `one_time_charges` and `usage_events` are unchanged.
    """
    gst_registered()
    org = await _tenant_with_usage()
    tenant_id = uuid.UUID(str(org["id"]))

    async def _counts() -> tuple[int, int]:
        async with tenant_session(tenant_id) as session:
            charges = await session.execute(
                text("SELECT count(*) FROM one_time_charges WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
            usage = await session.execute(
                text("SELECT count(*) FROM usage_events WHERE tenant_id = :t"), {"t": tenant_id}
            )
            return int(charges.scalar_one()), int(usage.scalar_one())

    before = await _counts()
    headers = await _client_headers(org)
    async with _client() as http:
        assert (await http.get(CLIENT_PATH, headers=headers)).status_code == 200
        assert (await http.get(CLIENT_PATH, headers=headers)).status_code == 200

    assert await _counts() == before, "the invoice GET must be a pure read (D-64)"


async def test_the_client_and_admin_documents_are_identical(gst_registered: Any) -> None:
    """THE ANTI-FORK TEST — the one that makes this feature trustworthy.

    Two realms, two routes, ONE `build_invoice`. If a future change adds a client-side
    "simplified" view, a rounding shortcut, or a second query for the client path, this
    fails on the field that differs and names it.

    `generated_at` is the only excusable difference: it is the instant the statement was
    derived, and the two requests are not simultaneous. Every other field — the number,
    the heading, the identity block, the place of supply, each line and each tax head —
    must match exactly.
    """
    gst_registered()
    org = await _tenant_with_usage()
    await _verify_gstin(org, OTHER_STATE_GSTIN)
    admin_token = await _make_admin()

    async with _client() as http:
        as_client = await http.get(CLIENT_PATH, headers=await _client_headers(org))
        as_admin = await http.get(
            f"/v1/admin/tenants/{org['id']}/invoice",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert as_client.status_code == 200, as_client.text
    assert as_admin.status_code == 200, as_admin.text
    client_body = as_client.json()
    admin_body = as_admin.json()
    assert client_body.pop("generated_at")
    assert admin_body.pop("generated_at")
    assert client_body == admin_body
    # And it is a REAL document, not two identical empties: the comparison would pass on
    # two error shapes, so pin that the thing being compared has the figures on it.
    assert client_body["total_inr"] == "11987.62"
    assert client_body["document_type"] == "tax_invoice"


# ------------------------------------------------------------- AL2: is it a tax invoice?


async def test_without_the_identity_config_it_refuses_to_be_a_tax_invoice() -> None:
    """The state EVERY deployment is in today (ROADMAP M0: no legal entity, no GST
    registration). The document says what it is and names the variables that would make
    it something else, rather than printing an official-looking sheet that fails in the
    recipient's return months later."""
    org = await _tenant_with_usage()

    async with _client() as http:
        body = (await http.get(CLIENT_PATH, headers=await _client_headers(org))).json()

    assert body["document_type"] == "proforma"
    assert body["document_blockers"] == [
        "GST_SUPPLIER_LEGAL_NAME",
        "GST_SUPPLIER_ADDRESS",
        "GST_SUPPLIER_GSTIN",
        "GST_SUPPLY_SAC",
    ]
    assert body["supplier"] == {
        "legal_name": None,
        "address": None,
        "gstin": None,
        "state_name": None,
        "sac": None,
    }
    # No supplier registration means no supplier location, so there is nothing to
    # classify the supply against.
    assert body["place_of_supply"]["supply_type"] == "undetermined"
    # BILL OF SUPPLY: an unregistered supplier may not collect tax (CGST s.32, Rule 49),
    # so there is NO tax head, the tax is zero, and the total is the subtotal. The document
    # states the no-tax position in words. This SUPERSEDES the old behaviour, which printed
    # a collectible 18% GST line on the proforma — exactly the tax s.32 forbids collecting.
    assert body["tax_components"] == []
    assert body["subtotal_inr"] == "10159.00"
    assert body["gst_inr"] == "0.00"
    assert body["gst_rate_pct"] == "0"
    assert body["total_inr"] == "10159.00", "no tax is added to a bill of supply"
    assert "no tax is charged" in body["tax_note"]
    assert "input tax credit" in body["tax_note"]
    # The 18% figure is kept ONLY as a clearly-labelled internal estimate, never as a
    # collectible amount — so a missing config key still moves no money on the document.
    assert body["estimated_gst_rate_pct"] == "18"
    assert body["estimated_gst_inr"] == "1828.62"
    assert body["estimated_total_inr"] == "11987.62"


async def test_a_partial_identity_is_still_a_refusal(gst_registered: Any) -> None:
    """Three of four is not a tax invoice. Rule 46 is a list of particulars, not a
    threshold — and a malformed GSTIN counts as absent, because printing a number that
    fails validation on the recipient's side is the failure this slice removes."""
    gst_registered(gstin="36AABCC1234D1Z")  # 14 characters — one short
    org = await _tenant_with_usage()

    async with _client() as http:
        body = (await http.get(CLIENT_PATH, headers=await _client_headers(org))).json()

    assert body["document_type"] == "proforma"
    assert body["document_blockers"] == ["GST_SUPPLIER_GSTIN"]
    assert body["supplier"]["gstin"] is None
    # The three that WERE configured still print — the refusal is about the document's
    # claim, not about hiding what we know.
    assert body["supplier"]["legal_name"] == "Calevate Technologies Private Limited"
    assert body["supplier"]["sac"] == "998315"


async def test_with_the_identity_configured_it_is_a_tax_invoice(gst_registered: Any) -> None:
    """Every Rule 46 particular this code owns, on the document at once."""
    gst_registered()
    org = await _tenant_with_usage()
    await _verify_gstin(org, SAME_STATE_GSTIN)

    async with _client() as http:
        body = (await http.get(CLIENT_PATH, headers=await _client_headers(org))).json()

    assert body["document_type"] == "tax_invoice"
    assert body["document_blockers"] == []
    assert body["supplier"]["legal_name"] == "Calevate Technologies Private Limited"
    assert body["supplier"]["address"] == "Plot 42, Madhapur, Hyderabad 500081"
    assert body["supplier"]["gstin"] == SUPPLIER_GSTIN
    assert body["supplier"]["state_name"] == "Telangana"
    assert body["organization"]["gstin"] == SAME_STATE_GSTIN
    assert body["place_of_supply"]["state_name"] == "Telangana"
    # Rule 46(g): the SAC belongs on every LINE, which is where a reader looks for it.
    assert [item["sac"] for item in body["line_items"]] == ["998315", "998315"]


async def test_an_unverified_gstin_is_not_printed(gst_registered: Any) -> None:
    """The recipient GSTIN comes from the VERIFIED KYC record. An `in_review` claim is a
    claim; a GSTIN on an invoice that does not match the recipient's registration is a
    mismatch in their return, so the document says "not registered" rather than guessing.
    """
    gst_registered()
    org = await _tenant_with_usage()
    token = await _make_admin()
    async with _client() as http:
        recorded = await http.post(
            f"/v1/admin/tenants/{org['id']}/kyc",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "status": "in_review",
                "document_kind": "gstin",
                "document_ref": OTHER_STATE_GSTIN,
                "evidence_ref": "ops-ticket-9002",
            },
        )
        assert recorded.status_code == 200, recorded.text
        body = (await http.get(CLIENT_PATH, headers=await _client_headers(org))).json()

    assert body["organization"]["gstin"] is None
    # Unregistered recipient → place of supply falls back to the supplier's location
    # (IGST Act s.12(2)(b)), which makes it an intra-State supply.
    assert body["place_of_supply"]["supply_type"] == "intrastate"


async def test_the_invoice_serial_length_is_46b_compliant_but_the_series_is_not() -> None:
    """The LENGTH half of Rule 46(b) is now fixed; the CONSECUTIVE half is still open, and
    both are pinned so neither can rot into a comment nobody reads.

    Rule 46(b) wants a serial that is (i) at most sixteen characters and (ii) CONSECUTIVE
    within the financial year. This slice fixed (i) — the number is exactly sixteen
    characters — while (ii) remains a deterministic per-tenant-month hash rather than a
    series, because a consecutive series needs the stateful issued-invoice registry that is
    a founder decision blocked on the GST registration. `billing/invoice.py` carries the
    verified clause text, why the second half is blocked, and the registry design.

    Both halves are asserted separately, each with the remedy for its own half, so whichever
    one moves the failure names it. Closing the CONSECUTIVE half means deleting this test —
    after the series assertion has something to say about a real registry, not before.
    """
    org = await _tenant_with_usage()
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)
    serial = str(invoice["invoice_number"])

    # THE LENGTH HALF, now fixed: at most sixteen characters, alphanumerics only.
    assert len(serial) <= RULE_46B_MAX_SERIAL_CHARS, (
        f"the invoice serial {serial!r} exceeds Rule 46(b)'s sixteen characters again — the "
        "length regressed. The suffix width or the prefix changed; see "
        "billing/invoice.py::build_invoice, which asserts sixteen at the build site."
    )
    assert serial.isalnum(), f"Rule 46(b) allows alphanumerics (and -/); {serial!r} has neither"

    # THE CONSECUTIVE HALF, still open, probed the only way it can be without an
    # issued-invoice registry to read: two tenants billed in the SAME month get numbers with
    # no ordering relationship, because there is no series for them to be positions in. A
    # real 46(b) series would hand these two consecutive integers.
    other = await _tenant_with_usage(minutes=0)
    other_id = uuid.UUID(str(other["id"]))
    async with tenant_session(other_id) as session:
        other_invoice = await build_invoice(session, tenant_id=other_id)
    other_serial = str(other_invoice["invoice_number"])

    # `CAL` + YYMM (7 chars) is the shared month prefix; the last 9 are the per-tenant hash.
    head, tail = serial[:7], serial[7:]
    other_head, other_tail = other_serial[:7], other_serial[7:]
    assert head == other_head, "the two documents are not even from the same month series"
    assert (
        not tail.isdigit() or not other_tail.isdigit() or abs(int(tail) - int(other_tail)) != 1
    ), (
        f"the serials {serial!r} and {other_serial!r} now differ by one, so the scheme may "
        "have become a consecutive series. If it has: confirm the counter is allocated under "
        "a lock with a unique index behind it and resets by financial year rather than by "
        "cron (billing/invoice.py has the design), and then delete this test."
    )


async def test_two_tenants_billed_in_one_month_get_different_invoice_numbers() -> None:
    """THE COLLISION THE 46(b) FINDING WAS HIDING, and it is not a compliance nicety.

    The serial was `CAL-{month}-{tenant_id.hex[:8]}`. Tenant ids are uuid7, whose first
    48 bits are the Unix millisecond timestamp, so `hex[:8]` is `ms >> 16` — a value that
    advances once every 65.5 seconds. **Two organizations created in the same minute
    therefore carried the SAME invoice number, in every month, permanently.** Onboarding
    two clients in one sitting is the ordinary case, and the two tenants this very test
    file creates back to back reproduced it on the first run.

    It survived because the finding above only ever asserted the serial's LENGTH: nothing
    in the suite had two tenants compare numbers, so a "unique for a financial year" claim
    that was simply false sat in a comment as `ok`.

    The two tenants here are created microseconds apart deliberately — that is the
    worst case, and it is also the realistic one.
    """
    first = await _tenant_with_usage(minutes=0)
    second = await _tenant_with_usage(minutes=0)
    assert str(first["id"])[:8] == str(second["id"])[:8], (
        "these two tenants no longer share a uuid7 timestamp prefix, so this test is not "
        "exercising the collision it was written for — uuid7 or the fixture changed"
    )

    numbers = []
    for org in (first, second):
        tenant_id = uuid.UUID(str(org["id"]))
        async with tenant_session(tenant_id) as session:
            numbers.append((await build_invoice(session, tenant_id=tenant_id))["invoice_number"])

    assert numbers[0] != numbers[1], (
        f"two tenants created in the same minute share the invoice number {numbers[0]!r}. "
        "The suffix must derive from the WHOLE tenant id, not from a prefix of a "
        "time-ordered uuid (billing/invoice.py::_tenant_serial_suffix)."
    )


async def test_the_invoice_number_is_stable_across_regenerations() -> None:
    """D-46's own property, and the one the collision fix must not cost.

    The statement is recomputed from the ledgers and never stored, so "one number per
    tenant-month" holds only if the number is a pure function of the tenant and the
    month. A suffix that drew on anything else — a rotating secret, a random salt, the
    clock — would hand the accountant two numbers for one month.
    """
    org = await _tenant_with_usage()
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        once = await build_invoice(session, tenant_id=tenant_id)
        twice = await build_invoice(session, tenant_id=tenant_id)
    assert once["invoice_number"] == twice["invoice_number"]
    month = str(once["month"])  # "YYYY-MM"
    assert once["invoice_number"].startswith(f"CAL{month[2:4]}{month[5:7]}")
    assert len(str(once["invoice_number"])) == 16


# --------------------------------------------- the split: which head the tax lands under


async def test_a_supply_in_our_own_state_is_cgst_plus_sgst(gst_registered: Any) -> None:
    """Intra-State (CGST Act s.8): 18% arrives as CGST 9 + SGST 9. The total is the same
    number it always was; what is new is that the recipient can credit it, because CGST,
    SGST and IGST are three different ledgers and tax charged without saying which one
    cannot be claimed (Rule 46(l)-(m))."""
    gst_registered()
    org = await _tenant_with_usage()
    await _verify_gstin(org, SAME_STATE_GSTIN)

    async with _client() as http:
        body = (await http.get(CLIENT_PATH, headers=await _client_headers(org))).json()

    assert body["place_of_supply"]["supply_type"] == "intrastate"
    assert body["tax_components"] == [
        {"label": "CGST", "rate_pct": "9", "amount_inr": "914.31"},
        {"label": "SGST", "rate_pct": "9", "amount_inr": "914.31"},
    ]
    # The heads sum to the published total EXACTLY, so no screen has to add them up and
    # disagree with the figure beside them.
    assert sum(Decimal(c["amount_inr"]) for c in body["tax_components"]) == Decimal(body["gst_inr"])


async def test_a_supply_to_another_state_is_igst(gst_registered: Any) -> None:
    """Inter-State (IGST Act s.5, place of supply per s.12(2)(a)): one IGST line, and
    Rule 46(n)'s "place of supply along with the name of the State" is on the face of
    the document."""
    gst_registered()
    org = await _tenant_with_usage()
    await _verify_gstin(org, OTHER_STATE_GSTIN)

    async with _client() as http:
        body = (await http.get(CLIENT_PATH, headers=await _client_headers(org))).json()

    assert body["place_of_supply"] == {
        "state_code": "29",
        "state_name": "Karnataka",
        "supply_type": "interstate",
        "basis": "Location of the recipient, a registered person (IGST Act s.12(2)(a)).",
    }
    assert body["tax_components"] == [{"label": "IGST", "rate_pct": "18", "amount_inr": "1828.62"}]


def test_a_union_territory_without_a_legislature_gets_utgst() -> None:
    """UTGST Act: an intra-UT supply in Chandigarh, Ladakh, Lakshadweep, Andaman &
    Nicobar or Dadra & Nagar Haveli and Daman & Diu is CGST + UTGST, not CGST + SGST.
    Delhi, Puducherry and Jammu & Kashmir have legislatures and are treated as States.

    A pure unit test: the branch is decided entirely by the state code, and driving it
    through HTTP would need a supplier registered in a UT — config this deployment must
    never carry.
    """
    supplier = supplier_identity(
        _settings_with(gstin=UNION_TERRITORY_GSTIN, sac="998315"),
    )
    recipient = parse_gstin(UNION_TERRITORY_GSTIN)
    place = resolve_place_of_supply(supplier, recipient)

    assert place.supply_type == "intrastate"
    assert place.state_name == "Chandigarh"
    assert [
        c.label
        for c in split_tax(subtotal_inr=Decimal("100.00"), rate_pct=Decimal("18"), place=place)
    ] == ["CGST", "UTGST"]
    # Delhi has a legislature: same intra-UT shape, SGST rather than UTGST.
    assert "07" not in UT_WITHOUT_LEGISLATURE
    assert "34" not in UT_WITHOUT_LEGISLATURE


def test_the_two_halves_always_sum_to_the_published_total() -> None:
    """An odd number of paise cannot be halved. The remainder lands on the SECOND
    component — the same doctrine the last overage line follows — so "CGST + SGST equals
    the GST line" holds for every subtotal, not merely for the tidy ones."""
    supplier = supplier_identity(_settings_with(gstin=SUPPLIER_GSTIN, sac="998315"))
    place = resolve_place_of_supply(supplier, parse_gstin(SAME_STATE_GSTIN))

    for paise in range(1, 40):
        subtotal = Decimal(paise) / Decimal("100")
        components = split_tax(subtotal_inr=subtotal, rate_pct=Decimal("18"), place=place)
        # `to_paise` — the repo's ONE rounding function, half-up by explicit choice — is
        # what `build_invoice` publishes as `gst_inr`. Quantizing here with Python's
        # default (half-EVEN) instead would assert against a different rounding policy
        # than the document uses and call the difference a bug: 18% of ₹0.25 is ₹0.045,
        # which is ₹0.05 on this invoice and ₹0.04 under banker's rounding.
        expected = to_paise(subtotal * Decimal("18") / Decimal("100"))
        assert sum(c.amount_inr for c in components) == expected, f"drift at {subtotal}"


def test_a_gstin_with_a_retired_state_code_is_refused() -> None:
    """25 (old Daman & Diu) and 28 (undivided Andhra Pradesh) no longer issue numbers.
    A GSTIN carrying one is refused rather than printed against a State that does not
    exist — the same rule that makes a malformed number absent rather than accepted."""
    assert parse_gstin("25AAACR5055K1Z9") is None
    assert parse_gstin("28AAACR5055K1Z2") is None
    assert parse_gstin("99AAACR5055K1Z9") is None
    assert parse_gstin(None) is None
    assert parse_gstin("  36aabcc1234d1z5  ") is not None, "trimmed and upper-cased, not rejected"


# ------------------------------------------------------------------- hard rule 7: no floats


async def test_every_money_field_on_the_document_is_an_exact_decimal_string(
    gst_registered: Any,
) -> None:
    """Hard rule 7's boundary shadow: a JSON float cannot hold a rupee amount, so every
    money field leaves as a string and `Decimal(...)` must accept it unchanged. The new
    fields — each tax component's amount — are in the sweep for the same reason the old
    ones are."""
    gst_registered()
    org = await _tenant_with_usage()
    await _verify_gstin(org, OTHER_STATE_GSTIN)

    async with _client() as http:
        body = (await http.get(CLIENT_PATH, headers=await _client_headers(org))).json()

    money = [body["subtotal_inr"], body["gst_inr"], body["total_inr"]]
    money += [item["amount_inr"] for item in body["line_items"]]
    money += [item["unit_inr"] for item in body["line_items"]]
    money += [component["amount_inr"] for component in body["tax_components"]]
    for value in money:
        assert isinstance(value, str), f"money crossed the boundary as {type(value)}: {value!r}"
        assert Decimal(value).quantize(Decimal("0.01")) == Decimal(value), value

    # And the underlying values are Decimals, not floats that happened to serialize well.
    async with tenant_session(uuid.UUID(str(org["id"]))) as session:
        invoice = await build_invoice(session, tenant_id=uuid.UUID(str(org["id"])))
    for component in invoice["tax_components"]:
        assert isinstance(component["amount_inr"], Decimal)
        assert isinstance(component["rate_pct"], Decimal)


def _settings_with(*, gstin: str, sac: str) -> Any:
    """A Settings stand-in carrying only the four identity fields.

    A real `Settings()` would need the whole environment, and these two unit tests are
    about the state-code arithmetic rather than about configuration loading — which the
    HTTP tests above already exercise end to end.
    """

    class _Stub:
        gst_supplier_legal_name = "Calevate Technologies Private Limited"
        gst_supplier_address = "Plot 42, Madhapur, Hyderabad 500081"
        gst_supplier_gstin = gstin
        gst_supply_sac = sac

    return _Stub()
