"""Every panel that used to answer `dict[str, Any]` now answers a DECLARED model.

Two audits found the same gap from opposite ends, and both consequences are real:

- **The redaction guardrail was structurally blind to these routes.**
  `scripts/check_redaction_exposure.py` inspects response MODELS. A route whose
  OpenAPI response is `additionalProperties: true` with no properties has no model to
  inspect, so however good the guardrail's field list gets it can never look at that
  route. None of these leaked — but nothing prevented it, and a future field carrying
  a raw phone or a transcript line would have shipped green.
- **The frontend hand-wrote its own interfaces for them**, each with a comment saying
  "swap for the generated alias when it lands". A hand-written mirror of a server
  shape drifts silently, in a browser, as a field that is quietly `undefined`.

So these tests do two things a "the model imports" test cannot:

1. They exercise each endpoint **through the app, against seeded data**, because
   `extra="forbid"` turns an incomplete model into a 500 — and an empty tenant is
   exactly where a missing field hides. Every panel here has real numbers in it: an
   attention queue with entries, a performance tab with calls, an invoice with an
   overage line, a delivery feed with a failure.
2. They assert the response is **exactly** what the service produced, by round-tripping
   the service's own return value through the model and comparing the JSON. A model
   that quietly drops or renames a field fails here rather than on a screen.

`test_the_openapi_response_schemas_are_inspectable` is the one that ties this back to
the reason: it asserts, against the live spec, that none of these operations is a
free-form object any more.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from apps.api.admin import service as admin_service
from apps.api.admin.routes import MarginOut, TierSplitOut
from apps.api.agents import prompts
from apps.api.agents.prompt_routes import PromptVersionOut
from apps.api.billing import service as billing
from apps.api.billing.invoice import build_invoice
from apps.api.billing.routes import InvoiceOut
from apps.api.crm.attention import attention_queue
from apps.api.crm.performance import performance
from apps.api.crm.schemas import AttentionOut, PerformanceOut, UsagePanelOut
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ingest.routes import IngestActivityOut, LeadSourceDryRunOut
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# The client-realm panels, and the admin-realm ones. Kept as constants because the
# OpenAPI test below reads the same paths off the live spec.
USAGE = "/v1/usage"
PERFORMANCE = "/v1/performance"
ATTENTION = "/v1/attention"
ACTIVITY = "/v1/lead-sources/activity"
DRY_RUN = "/v1/lead-sources/{webhook_id}/test"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _owner_tenant(prefix: str) -> tuple[uuid.UUID, uuid.UUID, dict[str, str]]:
    """A freshly created tenant with one OWNER member, and the headers to call as them.

    Freshly created on purpose: other agents run pytest against the same Postgres, and
    every assertion here is about one tenant's own rows.
    """
    created = await admin_service.create_organization(
        name="Shape Clinic",
        slug=f"{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]

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
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    headers = {"Authorization": f"Bearer dev:client:{user_id}", "X-Org-Slug": str(slug)}
    return tenant_id, agent_id, headers


async def _staff_headers(tenant_id: uuid.UUID, owner_headers: dict[str, str]) -> dict[str, str]:
    """A second member of the SAME tenant, with the `staff` role.

    `staff` holds `org:read` and not `org:manage` (SEC-COMP §5), which is the boundary
    the lead-source dry run sits on: the delivery feed is a view of the client's data and
    the dry run is an action taken on their behalf.
    """
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
                "VALUES (:id, :tid, :uid, 'staff', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return {**owner_headers, "Authorization": f"Bearer dev:client:{user_id}"}


async def _admin_headers() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def _seed_billing(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """₹9999 plan, 100 included minutes at ₹8 overage, a 500-minute cap, and 120
    minutes actually used at ₹0.50/unit of supplier cost.

    Chosen so EVERY nullable field on the usage/margin/invoice models lands non-null
    and the invoice carries a real overage line: 20 overage minutes → ₹160.00,
    subtotal ₹10159.00, cost ₹3600.00, margin 64.6%.
    """
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        # The MANAGED motion, named rather than inherited (D-521 moved the default to
        # `prepaid`). The figures in this docstring are a retainer, an included allowance
        # and an overage rate — the invoiced month's arithmetic — and on a prepaid month
        # the same minutes are priced at the published list rate with no allowance in
        # front of them, so every nullable field this fixture exists to fill would land
        # somewhere else.
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'managed' WHERE id = :t"),
            {"t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "hard_cap_min, concurrency_ceiling, created_at, updated_at) VALUES (:i, :t, "
                "9999.00, 100, 8.0000, 500, 10, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, duration_s, outcome_tag, started_at, created_at, updated_at) VALUES "
                "(:i, :t, :a, :e, 'outbound', '+919876500001', 'completed', 7200, 'resolved', "
                "now(), now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', "
                "7200, 0.5000, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
        # A real spend_state row rather than the "no row" fallback: `spend_used_inr`
        # falling back to ₹0.00 is precisely the empty case that hides a missing field.
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, billed_inr, "
                "capped, created_at, updated_at) "
                "VALUES (:t, :m, 120, 250.5000, 250.5000, false, now(), now())"
            ),
            {"t": tenant_id, "m": billing.current_billing_month()},
        )


# ============================================================================
# GET /v1/usage
# ============================================================================


async def test_the_usage_panel_answers_a_declared_model_with_real_numbers() -> None:
    tenant_id, agent_id, headers = await _owner_tenant("use")
    await _seed_billing(tenant_id, agent_id)

    async with _client() as http:
        response = await http.get(USAGE, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()

    # The endpoint ships EXACTLY the declared fields — no more (the whitelist holds),
    # no fewer (a `| None` field is present-and-null, not absent).
    assert set(body) == set(UsagePanelOut.model_fields)
    UsagePanelOut.model_validate(body)

    # Money is an exact decimal STRING, never a JSON float (hard rule 7).
    assert body["minutes_used"] == "120.00"
    assert body["overage_minutes"] == "20.00"
    assert body["overage_cost_inr"] == "160.00"
    assert body["overage_rate_inr"] == "8.00"
    assert body["monthly_fee_inr"] == "9999.00"
    assert body["spend_used_inr"] == "250.50"
    assert isinstance(body["overage_cost_inr"], str), "a float here is a rupee we cannot defend"

    assert body["calls"] == 1
    assert body["included_minutes"] == 100
    assert body["cap_minutes"] == 500
    assert body["minutes_left"] == 380, "500 cap minus 120 used"
    assert body["capped"] is False
    assert body["plan_tier"] == "managed"
    # A managed client has no wallet: ₹0 would invite a support ticket about a concept
    # that does not apply to them (D-34).
    assert body["credit_balance_inr"] is None

    # Our supplier pricing lives on the admin margin panel and nowhere near this one.
    assert "cost_inr" not in body and "unit_cost_paid" not in body


async def test_the_usage_panel_matches_what_billing_actually_computed() -> None:
    """The values are the service's, not a re-derivation: round-trip `usage_summary`
    through the model and compare the JSON."""
    tenant_id, agent_id, headers = await _owner_tenant("usm")
    await _seed_billing(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
        tier = await billing.plan_tier_of(session, tenant_id)
    expected = UsagePanelOut.model_validate(
        {
            **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in summary.items()},
            "plan_tier": tier,
            "credit_balance_inr": None,
        }
    )

    async with _client() as http:
        response = await http.get(USAGE, headers=headers)

    assert response.json() == expected.model_dump(mode="json")


async def test_the_wallet_is_a_string_for_a_self_serve_client() -> None:
    """`credit_balance_inr` is the one field that flips between None and a value, so
    both branches are exercised — a `str | None` that is never non-None in a test is a
    field nobody has actually typed."""
    tenant_id, agent_id, headers = await _owner_tenant("wal")
    await _seed_billing(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
        await billing.record_entry(
            session, tenant_id=tenant_id, delta=Decimal("300.00"), reason="topup", ref="rzp_shape"
        )

    async with _client() as http:
        response = await http.get(USAGE, headers=headers)

    assert response.status_code == 200, response.text
    body = UsagePanelOut.model_validate(response.json())
    assert body.plan_tier == "self_serve"
    # PAISE, like every other money field on this panel (D-375). It used to be
    # "300.0000" — the route stringified `get_balance()`, i.e. `credit_ledger
    # .balance_after` at its NUMERIC(12,4) storage precision — and this assertion pinned
    # the inconsistency rather than the fix. It is a fix rather than a tidy-up because
    # `formatINR` TRUNCATES a fraction to two digits where `to_paise` rounds half-up: at
    # a balance of ₹489.7050 the admin wallet screen said ₹489.71 and the client's own
    # panel said ₹489.70, off one wallet, in one instant.
    assert body.credit_balance_inr == "300.00"
    assert body.monthly_fee_inr == "9999.00", "and it is not the odd one out any more"
    # Runway is now priced off the wallet, not the cap (₹300 at the ₹5/min list rate).
    assert body.minutes_left == 60


async def test_one_wallet_reads_the_same_on_the_client_panel_and_the_admin_console() -> None:
    """D-375. The client's own panel and the admin wallet screen are two readers of ONE
    `credit_ledger.balance_after`, and they must not publish it differently.

    THE BALANCE IS DELIBERATELY A FOUR-DECIMAL ONE, because that is the case the paise
    quantum decides and the only case that ever disagreed. It is not exotic: a prepaid
    debit is `rates.prepaid_billed_inr`, quantized at MONEY_Q, so any
    `self_serve_inr_per_min` that is not a divisor of 60 produces one on the first call —
    a 95-second call at ₹6.50/min is ₹10.2917.

    ₹489.7050 is the awkward half: `to_paise` (ROUND_HALF_UP, the repo's one mode) makes
    it ₹489.71, while the panel used to publish `489.7050` verbatim into `formatINR`,
    which TRUNCATES a fraction to two digits — ₹489.70. One wallet, two screens, one
    paisa apart, and the client's screen was always the low one.
    """
    tenant_id, agent_id, headers = await _owner_tenant("walq")
    await _seed_billing(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
        await billing.record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("489.7050"),
            reason="topup",
            ref="rzp_shape_q",
        )
        stored = (await billing.get_balance(session, tenant_id=tenant_id)).amount_inr

    assert stored == Decimal("489.7050"), (
        "the LEDGER keeps its full precision — only the wire is quantized"
    )

    async with _client() as http:
        response = await http.get(USAGE, headers=headers)
    body = UsagePanelOut.model_validate(response.json())

    assert body.credit_balance_inr == str(billing.to_paise(stored)) == "489.71", (
        "the client's own wallet figure must be the same paisa the admin console shows; "
        "publishing the storage precision hands it to a formatter that truncates"
    )


async def test_a_brand_new_tenant_still_gets_a_usage_panel() -> None:
    """The complement, not the whole test: a client mid-onboarding has no plan and no
    usage, and the screen must render numbers rather than a 500."""
    _tenant_id, _agent_id, headers = await _owner_tenant("new")
    async with _client() as http:
        response = await http.get(USAGE, headers=headers)

    assert response.status_code == 200, response.text
    body = UsagePanelOut.model_validate(response.json())
    assert body.monthly_fee_inr is None and body.cap_minutes is None
    assert body.minutes_used == "0.00" and body.overage_cost_inr == "0.00"


# ============================================================================
# GET /v1/performance
# ============================================================================


async def test_the_performance_panel_answers_a_declared_model_with_calls_in_it() -> None:
    tenant_id, agent_id, headers = await _owner_tenant("perf")
    async with tenant_session(tenant_id) as session:
        for status, duration, outcome, direction, ist_hour in (
            ("completed", 120, "resolved", "outbound", 11),
            ("completed", 90, None, "inbound", 11),
            ("no_answer", None, None, "outbound", 19),
            # A voicemail has a perfectly real duration; it is a dial, not a
            # conversation, and the funnel must keep saying so through the API too.
            ("voicemail", 30, None, "outbound", 19),
        ):
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, duration_s, outcome_tag, started_at, created_at, "
                    "updated_at) VALUES (:i, :t, :a, :e, :dir, '+919876500001', :st, :dur, "
                    ":out, date_trunc('day', now()) + make_interval(hours => :h) "
                    "  - interval '5 hours 30 minutes', now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"perf_{uuid.uuid4().hex[:12]}",
                    "dir": direction,
                    "st": status,
                    "dur": duration,
                    "out": outcome,
                    "h": ist_hour,
                },
            )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, '+919876500001', 'inbound_call', "
                "'interested', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "a": agent_id},
        )
        expected = PerformanceOut.model_validate(await performance(session, days=30))

    async with _client() as http:
        response = await http.get(f"{PERFORMANCE}?days=30", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(PerformanceOut.model_fields)
    assert body == expected.model_dump(mode="json")

    panel = PerformanceOut.model_validate(body)
    assert panel.funnel.calls == 4
    assert panel.funnel.connected == 2, "voicemail and no-answer are dials, not conversations"
    assert panel.funnel.qualified == 1
    assert panel.connect_rate_pct == 50
    assert panel.inbound == 1 and panel.outbound == 3
    assert panel.outcomes["resolved"] == 1
    assert panel.outcomes["no_answer"] == 1, "an untagged call reports its status honestly"
    assert len(panel.busiest_hours_ist) == 24, "all 24 buckets, even the silent ones"
    assert panel.busiest_hours_ist[11] == 2 and panel.busiest_hours_ist[5] == 0


async def test_the_performance_rates_stay_null_rather_than_zero_over_the_wire() -> None:
    """`int | None`, not `int` with a 0 default: "0% connected" and "no calls yet" are
    different facts, and a default would have invented the wrong one."""
    _tenant_id, _agent_id, headers = await _owner_tenant("prat")
    async with _client() as http:
        response = await http.get(PERFORMANCE, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["connect_rate_pct"] is None and body["qualify_rate_pct"] is None
    assert "connect_rate_pct" in body, "nullable is present-and-null, never absent"


# ============================================================================
# GET /v1/attention
# ============================================================================


async def _blocked_lead(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, rule: str, name: str | None
) -> str:
    phone = f"+9198{uuid.uuid4().int % 100000000:08d}"
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, :p, :n, 'webhook', 'new', now(), "
                "now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "p": phone, "n": name},
        )
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:i, :t, :l, 'note', CAST(:p AS jsonb), "
                "'system', now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "l": lead_id,
                "p": f'{{"kind": "blocked", "rule": "{rule}"}}',
            },
        )
    return phone


async def test_the_attention_queue_answers_a_declared_model_with_a_full_queue() -> None:
    tenant_id, agent_id, headers = await _owner_tenant("attn")
    await _blocked_lead(tenant_id, agent_id, rule="no_form_consent", name="Ravi")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, status, version, "
                "rejection_reason, created_at, updated_at) VALUES (:i, :t, :a, 'text', "
                "'Price list', 'rejected', 1, 'Prices are out of date.', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "a": agent_id},
        )
        expected = AttentionOut.model_validate(await attention_queue(session, limit=50))

    async with _client() as http:
        response = await http.get(ATTENTION, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(AttentionOut.model_fields)
    assert body == expected.model_dump(mode="json")

    queue = AttentionOut.model_validate(body)
    assert queue.total == 2
    assert queue.counts == {"lead_blocked": 1, "kb_rejected": 1}
    by_kind = {item.kind: item for item in queue.items}

    blocked = by_kind["lead_blocked"]
    assert blocked.rule == "no_form_consent", "the rule that fired is a real string"
    assert "consent checkbox" in blocked.detail, "the remedy tells them what to DO"
    assert blocked.href == "/leads"
    assert isinstance(blocked.occurred_at, datetime), "a timestamp stays a timestamp"

    rejected = by_kind["kb_rejected"]
    assert rejected.rule is None, "`rule` is genuinely nullable — not papered over"
    assert rejected.href == "/knowledge"


async def test_the_attention_queue_names_a_nameless_lead_by_its_number() -> None:
    """`title` is the one field on this model built from personal data, and for a lead
    with no captured name it is built from the phone.

    IT USED TO BE THE MASKED FORM and asserted as such. D-436 reversed it: this queue
    exists to say "nobody rang this person", and a to-do whose subject cannot be dialled
    is a to-do nobody can do. The value is still SERVER-composed prose — never a vendor
    string, never transcript text — which is why declaring these fields matters and why
    the guardrail can see them.
    """
    tenant_id, agent_id, headers = await _owner_tenant("mask")
    phone = await _blocked_lead(tenant_id, agent_id, rule="dnc", name=None)

    async with _client() as http:
        response = await http.get(ATTENTION, headers=headers)

    assert response.status_code == 200, response.text
    item = AttentionOut.model_validate(response.json()).items[0]
    assert item.title == f"{phone} was not called"
    assert "•" not in response.text, "no dots survive anywhere in the body"


# ============================================================================
# GET /v1/lead-sources/activity
# ============================================================================


async def test_the_delivery_feed_answers_a_declared_model_with_deliveries() -> None:
    tenant_id, _agent_id, headers = await _owner_tenant("act")
    webhook_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, active, "
                "created_at, updated_at) VALUES (:i, :t, 'website_form', 'secret://shape', "
                "true, now(), now())"
            ),
            {"i": webhook_id, "t": tenant_id},
        )
        for status, event_name, duplicates, last_error in (
            ("processed", "website_form", 3, None),
            ("failed", "website_form", 0, "Your endpoint answered 500."),
            # `event_name` is a NULLABLE column — a delivery recorded without one is
            # the case the frontend's hand-written `event: string` cannot represent.
            ("processing", None, 0, None),
        ):
            await session.execute(
                text(
                    "INSERT INTO webhook_inbox_events (id, provider, event_key, payload_hash, "
                    "status, event_name, duplicate_count, last_error, created_at, updated_at) "
                    "VALUES (:i, :p, :k, :k, :st, :ev, :dup, :err, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "p": f"ingest:{webhook_id}",
                    "k": uuid.uuid4().hex,
                    "st": status,
                    "ev": event_name,
                    "dup": duplicates,
                    "err": last_error,
                },
            )

    async with _client() as http:
        response = await http.get(ACTIVITY, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(IngestActivityOut.model_fields)
    feed = IngestActivityOut.model_validate(body)
    assert len(feed.items) == 3

    by_outcome = {item.outcome: item for item in feed.items}
    assert set(by_outcome) == {"accepted", "rejected", "processing"}
    assert by_outcome["accepted"].source == "website_form"
    assert by_outcome["accepted"].deduplicated == 3, "the retries we absorbed"
    assert by_outcome["accepted"].error is None
    assert by_outcome["rejected"].error == "Your endpoint answered 500."
    assert by_outcome["processing"].event is None, "`event` is genuinely nullable"
    for item in feed.items:
        assert isinstance(item.first_at, datetime) and isinstance(item.last_at, datetime)


async def test_the_delivery_feed_is_empty_not_broken_before_any_source_exists() -> None:
    _tenant_id, _agent_id, headers = await _owner_tenant("noact")
    async with _client() as http:
        response = await http.get(ACTIVITY, headers=headers)
    assert response.status_code == 200, response.text
    assert IngestActivityOut.model_validate(response.json()).items == []


# ============================================================================
# POST /v1/lead-sources/{webhook_id}/test — the dry run
#
# The one in this file that holds PII while it answers. `test_webhook` normalizes the
# sample's phone number to decide whether it is dialable and to ask the compliance gate
# about it, and it used to answer `dict[str, Any]` — so this was not a response the
# redaction guardrail judged safe, it was a response the guardrail could not see (D-71's
# defect, on a handler with a caller's number two lines above the `return`).
# ============================================================================


async def _lead_source(tenant_id: uuid.UUID, agent_id: uuid.UUID | None) -> uuid.UUID:
    """One website-form source, mapping the two field names the receiver looks for."""
    webhook_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, agent_id, source, secret_ref, "
                "mapping, active, created_at, updated_at) VALUES (:i, :t, :a, 'website_form', "
                "'secret://dry-run', CAST(:m AS jsonb), true, now(), now())"
            ),
            {
                "i": webhook_id,
                "t": tenant_id,
                "a": agent_id,
                "m": '{"phone_number": "phone_number", "full_name": "full_name"}',
            },
        )
    return webhook_id


async def test_the_dry_run_answers_a_declared_model_step_by_step() -> None:
    tenant_id, agent_id, headers = await _owner_tenant("dry")
    webhook_id = await _lead_source(tenant_id, agent_id)

    async with _client() as http:
        response = await http.post(
            f"/v1/lead-sources/{webhook_id}/test",
            headers=headers,
            json={"payload": {"phone_number": "9876512345", "full_name": "Priya"}},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(LeadSourceDryRunOut.model_fields)
    verdict = LeadSourceDryRunOut.model_validate(body)

    # Every step the real path would take, in order, each one a declared member of the
    # Literal — an unlisted step name would have failed response validation, not shipped.
    assert [step.step for step in verdict.steps] == [
        "field_mapping",
        "phone_number",
        "compliance_gate",
    ]
    mapping_step, phone_step, gate_step = verdict.steps
    assert mapping_step.mapped_fields == ["full_name", "phone_number"], "KEYS, never values"
    assert phone_step.ok is True and phone_step.mapped_fields is None
    # A freshly created org's agent is not published, so the gate refuses and NAMES the
    # rule — which is the branch that fills in `rule`, null on every other step. The
    # point is that the gate was CONSULTED (same function, same live DNC read) and its
    # verdict reported rather than acted on.
    assert verdict.would_call is False
    assert gate_step.ok is False and gate_step.rule == "agent_not_live"


async def test_the_dry_run_never_puts_the_sample_number_in_its_answer() -> None:
    """The half a schema walk cannot judge, so it is asserted against the bytes.

    The model makes a phone FIELD impossible without the guardrail reporting it
    (`tests/guardrail_audit_test.py` proves that half). Nothing structural stops a
    `detail` string from being rewritten to interpolate the number it just normalized —
    "No dialable number in +9198…" is one helpful-sounding edit away — so the whole
    response body is searched for the digits that went in, in every form they could
    come back out.
    """
    tenant_id, agent_id, headers = await _owner_tenant("dryp")
    webhook_id = await _lead_source(tenant_id, agent_id)
    local = "9876512346"

    async with _client() as http:
        response = await http.post(
            f"/v1/lead-sources/{webhook_id}/test",
            headers=headers,
            json={"payload": {"phone_number": local, "full_name": "Ravi Kumar"}},
        )

    assert response.status_code == 200, response.text
    for form in (local, f"+91{local}", f"91{local}"):
        assert form not in response.text, "the dry run reports verdicts, never the number"
    # The NAME is the sample's other personal datum and is equally absent: `mapped_fields`
    # is the keys of the mapping, and "full_name" is a key while "Ravi Kumar" is a value.
    assert "Ravi Kumar" not in response.text
    assert "full_name" in response.text


async def test_the_dry_run_reports_a_missing_agent_and_an_undialable_number() -> None:
    """The branch with no compliance step at all: `extra="forbid"` plus a Literal means
    a shape that only appears when the source is half-configured is validated too."""
    tenant_id, _agent_id, headers = await _owner_tenant("dryn")
    webhook_id = await _lead_source(tenant_id, None)

    async with _client() as http:
        response = await http.post(
            f"/v1/lead-sources/{webhook_id}/test",
            headers=headers,
            json={"payload": {"phone_number": "12345"}},
        )

    assert response.status_code == 200, response.text
    verdict = LeadSourceDryRunOut.model_validate(response.json())
    assert verdict.would_call is False
    steps = {step.step: step for step in verdict.steps}
    assert set(steps) == {"field_mapping", "phone_number", "agent"}
    assert steps["phone_number"].ok is False and steps["agent"].ok is False
    assert steps["field_mapping"].mapped_fields == ["phone_number"]


async def test_another_tenants_lead_source_is_not_dry_runnable() -> None:
    """RLS, through the route that reads the source: the id is a UUID we minted, and
    knowing one must not make another account's mapping testable."""
    tenant_id, agent_id, _headers = await _owner_tenant("drya")
    webhook_id = await _lead_source(tenant_id, agent_id)
    _other_id, _other_agent, other_headers = await _owner_tenant("dryb")

    async with _client() as http:
        response = await http.post(
            f"/v1/lead-sources/{webhook_id}/test",
            headers=other_headers,
            json={"payload": {"phone_number": "9876512347"}},
        )

    assert response.status_code == 404, "another tenant's source is indistinguishable from none"


async def test_the_dry_run_is_refused_to_a_reader_without_org_manage() -> None:
    """`org:manage`, not `org:read` — the server's deliberate call (ingest/routes.py): a
    dry run is an action taken on the client's behalf, so a `staff` member (and, by D-22,
    an impersonating operator) is refused it while the activity view stays readable."""
    tenant_id, agent_id, headers = await _owner_tenant("drys")
    webhook_id = await _lead_source(tenant_id, agent_id)
    staff_headers = await _staff_headers(tenant_id, headers)

    async with _client() as http:
        refused = await http.post(
            f"/v1/lead-sources/{webhook_id}/test",
            headers=staff_headers,
            json={"payload": {"phone_number": "9876512348"}},
        )
        readable = await http.get(ACTIVITY, headers=staff_headers)

    assert refused.status_code == 403, refused.text
    assert readable.status_code == 200, "the read next door stays on org:read"


# ============================================================================
# Admin realm: margin, invoice, prompt history
# ============================================================================


async def test_the_margin_panel_answers_a_declared_model_with_money_as_strings() -> None:
    tenant_id, agent_id, _headers = await _owner_tenant("marg")
    await _seed_billing(tenant_id, agent_id)
    admin = await _admin_headers()

    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
        tiers = await billing.tier_usage(session, tenant_id=tenant_id, month=str(margin["month"]))
    expected = MarginOut.model_validate(
        {
            **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in margin.items()},
            "tiers": {name: str(tiers[name]) for name in TierSplitOut.model_fields},
        }
    )

    async with _client() as http:
        response = await http.get(f"/v1/admin/tenants/{tenant_id}/margin", headers=admin)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(MarginOut.model_fields)
    assert body == expected.model_dump(mode="json")

    # 7200 telephony seconds at ₹0.50 = ₹3600 cost; ₹9999 + ₹160 overage = ₹10159.
    assert body["cost_inr"] == "3600.00"
    assert body["revenue_inr"] == "10159.00"
    assert body["margin_inr"] == "6559.00"
    assert body["margin_pct"] == "64.6"
    assert body["minutes_used"] == "120.00"

    # The rung split is a PARTITION of `cost_inr`, not a parallel estimate — both sides
    # come from `_tier_totals`, and the panel prints them on one card. Summed as Decimal
    # from the wire strings, because that is the arithmetic a reader does by eye and the
    # only one hard rule 7 permits on money.
    split = body["tiers"]
    assert set(split) == set(TierSplitOut.model_fields)
    assert sum(
        Decimal(split[f"cost_{rung}_inr"]) for rung in ("premium", "value", "unattributed")
    ) == Decimal(body["cost_inr"]), split
    assert sum(
        Decimal(split[f"minutes_{rung}"]) for rung in ("premium", "value", "unattributed")
    ) == Decimal(body["minutes_used"]), split
    # `_seed_billing` writes telephony rows with no `tts_tier`, so every minute lands in
    # the honest third bucket. Asserted rather than assumed: if attribution ever starts
    # stamping these rows, this line is where a reader learns the fixture changed meaning.
    assert split["cost_unattributed_inr"] == "3600.00"
    assert split["cost_premium_inr"] == "0.00"
    assert split["cost_value_inr"] == "0.00"


async def test_margin_percent_is_null_over_the_wire_before_anything_is_billed() -> None:
    tenant_id, _agent_id, _headers = await _owner_tenant("mnil")
    admin = await _admin_headers()
    async with _client() as http:
        response = await http.get(f"/v1/admin/tenants/{tenant_id}/margin", headers=admin)
    assert response.status_code == 200, response.text
    margin = MarginOut.model_validate(response.json())
    assert margin.margin_pct is None, "'0% margin' and 'nothing billed yet' differ"
    assert margin.revenue_inr == "0.00"


async def test_the_invoice_answers_a_declared_model_with_an_overage_line() -> None:
    tenant_id, agent_id, _headers = await _owner_tenant("inv")
    await _seed_billing(tenant_id, agent_id)
    admin = await _admin_headers()

    async with _client() as http:
        response = await http.get(f"/v1/admin/tenants/{tenant_id}/invoice", headers=admin)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(InvoiceOut.model_fields)
    invoice = InvoiceOut.model_validate(body)

    # Suffix read from the shipped function, not re-derived: it was `tenant_id.hex[:8]`
    # until D-114 found that layout collides for any two tenants onboarded within 65
    # seconds of each other.
    from apps.api.billing.invoice import _tenant_serial_suffix

    expected_suffix = _tenant_serial_suffix(tenant_id)
    # Rule 46(b) sixteen-character format: CAL + YYMM + base-36 tenant suffix.
    assert invoice.invoice_number == f"CAL{invoice.month[2:4]}{invoice.month[5:7]}{expected_suffix}"
    assert len(invoice.invoice_number) == 16
    assert invoice.organization.id == str(tenant_id)
    assert invoice.organization.billing_email is None, "nullable, and genuinely null here"

    assert len(invoice.line_items) == 2, "the plan fee AND the overage line"
    plan_line, overage_line = invoice.line_items
    assert plan_line.description == "Monthly plan fee"
    # Both quantities are strings, including the plan fee's "1": the invoice serializes
    # every number the same way so a consumer never gets a bare JSON number on one line
    # and a string on the next.
    assert plan_line.qty == "1"
    assert plan_line.amount_inr == "9999.00"
    assert overage_line.qty == "20.00"
    assert overage_line.unit_inr == "8.00"
    assert overage_line.amount_inr == "160.00"
    # qty * unit = amount, the one piece of arithmetic a client does by hand.
    assert Decimal(overage_line.qty) * Decimal(overage_line.unit_inr) == Decimal(
        overage_line.amount_inr
    )

    # No GST registration is configured here, so the document is a BILL OF SUPPLY: no tax
    # is charged, the total is the subtotal, and the words say so (CGST s.32, Rule 49). The
    # 18% figure survives only as a clearly-labelled internal estimate.
    assert invoice.subtotal_inr == "10159.00"
    assert invoice.gst_rate_pct == "0"
    assert invoice.gst_inr == "0.00"
    assert invoice.total_inr == "10159.00"
    assert invoice.tax_components == []
    assert invoice.tax_note is not None and "no tax is charged" in invoice.tax_note
    assert invoice.estimated_gst_rate_pct == "18"
    assert invoice.estimated_gst_inr == "1828.62"
    assert invoice.estimated_total_inr == "11987.62"
    assert invoice.usage.minutes_used == "120.00"
    assert invoice.usage.calls == 1
    assert invoice.usage.included_minutes == 100


async def test_the_invoice_matches_what_build_invoice_produced() -> None:
    tenant_id, agent_id, _headers = await _owner_tenant("invm")
    await _seed_billing(tenant_id, agent_id)
    admin = await _admin_headers()

    def _stringify(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {k: _stringify(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_stringify(v) for v in value]
        return value

    async with tenant_session(tenant_id) as session:
        built = await build_invoice(session, tenant_id=tenant_id)
    expected = InvoiceOut.model_validate({k: _stringify(v) for k, v in built.items()})

    async with _client() as http:
        response = await http.get(f"/v1/admin/tenants/{tenant_id}/invoice", headers=admin)

    body = response.json()
    # `generated_at` is stamped at build time, so it is the one field compared for
    # shape rather than value: it must parse as a timestamp, and everything else must
    # match the service's output exactly.
    stamp = body.pop("generated_at")
    assert datetime.fromisoformat(stamp).tzinfo is not None, "an aware ISO-8601 timestamp"
    without_stamp = expected.model_dump(mode="json")
    without_stamp.pop("generated_at")
    assert body == without_stamp


async def test_a_tenant_with_no_plan_still_gets_an_invoice_that_validates() -> None:
    tenant_id, _agent_id, _headers = await _owner_tenant("invn")
    admin = await _admin_headers()
    async with _client() as http:
        response = await http.get(f"/v1/admin/tenants/{tenant_id}/invoice", headers=admin)
    assert response.status_code == 200, response.text
    invoice = InvoiceOut.model_validate(response.json())
    assert invoice.line_items == [], "absence states the absence of a charge"
    assert invoice.total_inr == "0.00"


async def test_the_prompt_history_answers_a_declared_model_with_versions() -> None:
    """Already typed before this change — locked here so it stays that way, and because
    a history endpoint with an empty list proves nothing about its item model."""
    tenant_id, agent_id, _headers = await _owner_tenant("prm")
    admin = await _admin_headers()
    async with tenant_session(tenant_id) as session:
        first = await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="You are the clinic receptionist. Book appointments politely.",
            notes="initial draft",
            created_by=None,
        )
        second = await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="You are the clinic receptionist. Confirm the patient name first.",
            notes=None,
            created_by=None,
        )

    async with _client() as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt", headers=admin
        )

    assert response.status_code == 200, response.text
    history = [PromptVersionOut.model_validate(row) for row in response.json()]
    assert [entry.version for entry in history] == [second, first], "newest first"
    assert [entry.version for entry in history if entry.active] == [second]
    assert history[1].notes == "initial draft"
    assert history[0].notes is None, "`notes` is genuinely nullable"
    # The BODY is never in the history response: prompts routinely embed client
    # business detail (hard rule 6).
    assert set(response.json()[0]) == set(PromptVersionOut.model_fields)
    assert "body" not in response.json()[0]


# ============================================================================
# The reason all of the above exists
# ============================================================================


def _response_schema(
    spec: dict[str, Any], path: str, method: str, status: str = "200"
) -> dict[str, Any]:
    operation = spec["paths"][path][method]
    content = operation["responses"][status]["content"]["application/json"]
    schema: dict[str, Any] = content["schema"]
    return schema


def test_the_openapi_response_schemas_are_inspectable() -> None:
    """The point of the whole exercise, asserted against the LIVE spec.

    `scripts/check_redaction_exposure.py` walks response models. Before this change
    each of these operations advertised `additionalProperties: true` with no
    properties, so there was no model to walk and the guardrail was structurally blind
    to them — however good its field list got. This test fails the moment one of them
    goes back to an untyped dict.
    """
    from scripts.check_redaction_exposure import _is_freeform_object, reachable_models

    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    operations = [
        (USAGE, "get", "200"),
        (PERFORMANCE, "get", "200"),
        (ATTENTION, "get", "200"),
        (ACTIVITY, "get", "200"),
        ("/v1/admin/tenants/{tenant_id}/margin", "get", "200"),
        ("/v1/admin/tenants/{tenant_id}/invoice", "get", "200"),
        ("/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt", "get", "200"),
        # The dry run: the one on this list that holds a normalized caller number while
        # it builds its answer, which is why it was the worst one to be invisible.
        (DRY_RUN, "post", "200"),
        # The two intake receivers. Machine-facing, and that is the argument FOR
        # declaring them rather than against: the sender's whole payload is in scope of
        # the `return`, and nobody is reading these responses on a screen where an
        # echoed lead would be noticed.
        ("/hooks/v1/ingest/{webhook_id}", "post", "202"),
        ("/hooks/v1/ingest/meta/{webhook_id}", "post", "200"),
        ("/v1/campaigns/{campaign_id}/schedule", "delete", "200"),
    ]
    for path, method, status in operations:
        schema = _response_schema(spec, path, method, status)
        assert not _is_freeform_object(schema), f"{method.upper()} {path} is still a free-form dict"
        models = reachable_models(schema, schemas)
        assert models, f"{method.upper()} {path} references no response model to inspect"
        for name in models:
            properties = schemas[name].get("properties", {})
            assert properties, f"{name} declares no properties — nothing for the guardrail to see"
            for field, field_schema in properties.items():
                # A `dict[str, Any]` field is an undeclared response model wearing a
                # declared one's name. The two acknowledged passthroughs live on
                # LeadOut/CallDetailOut and are not reachable from these panels.
                assert not _is_freeform_object(field_schema), (
                    f"{name}.{field} is a free-form dict — whatever the query selected "
                    "would be serialized verbatim"
                )


def test_the_acks_with_nothing_to_say_answer_204_rather_than_a_constant() -> None:
    """The other half of the same sweep, and the reason it is not "wrap every dict".

    Four routes answered a CONSTANT — `{"status": "paused"}`, `{"status": "running"}`,
    `{"status": "recorded"}`, `{"status": "removed"}` — which told a caller only what the
    URL it had just posted to already said, in a shape neither the generated TypeScript
    client nor the redaction guardrail can describe. Modelling a constant would have
    satisfied both tools and taught the next reader nothing, so these say nothing
    properly: 204, no content, no schema to keep honest.

    Asserted against the live spec so a body cannot creep back onto them unnoticed.
    """
    spec = app.openapi()
    for path, method in (
        ("/v1/campaigns/{campaign_id}/pause", "post"),
        ("/v1/campaigns/{campaign_id}/resume", "post"),
        ("/v1/campaigns/{campaign_id}/consent-provenance", "post"),
        ("/v1/dnc/{entry_id}", "delete"),
    ):
        responses = spec["paths"][path][method]["responses"]
        success = {code: body for code, body in responses.items() if code.startswith("2")}
        assert set(success) == {"204"}, f"{method.upper()} {path} still advertises a 2xx body"
        assert "content" not in success["204"], f"{method.upper()} {path} 204 carries a schema"


# --- the sweep, derived rather than listed (D-303) ------------------------------------

#: 2xx operations whose body legitimately has no declared model, and why. Keyed
#: `"METHOD /path"`. The bar is that there is nothing to whitelist — a byte stream, a
#: plain-text echo, or an ops contract that is deliberately open-ended AND gated.
_UNMODELLED_SUCCESS: dict[str, str] = {
    "GET /healthz": (
        "the probe contract (BACKEND-PATTERNS §6): a status word to everybody and a "
        "`checks`/`fields[]` detail that only an `ops:manage` holder sees. Its shape is "
        "deliberately open-ended and it carries no tenant data."
    ),
    "GET /healthz/live": "the same probe contract; a two-key literal that touches nothing.",
    "GET /healthz/ready": "the same probe contract, plus queue depth and missing config keys.",
    "GET /v1/leads/export.csv": (
        "a CSV byte stream, not JSON — there is no model to declare. Its redaction is "
        "covered at runtime by tests/crm_egress_redaction_test.py."
    ),
    "POST /v1/leads/export.csv": (
        "a CSV byte stream, not JSON — see the GET twin. The POST shape exists so a "
        "phone-number `search` travels in a body rather than a query string."
    ),
    "POST /v1/numbers/purchase": (
        "there is no success response to model: the handler is `NoReturn` and ends in a "
        "raise on every path (`kyc_not_verified`, then "
        "`number_provisioning_not_configured`). The 202 is the status it will answer "
        "with the day a provisioning adapter lands, and modelling a body for it now "
        "would publish a shape no caller can ever receive."
    ),
    "GET /hooks/v1/ingest/meta/{webhook_id}": (
        "Meta's subscription handshake, which must echo `hub.challenge` verbatim as "
        "plain text — a JSON model would break the handshake."
    ),
    "POST /v1/copilot/ask": (
        "an SSE stream, not one JSON body — there is no single 2xx model to declare. "
        "FastAPI 0.140 emits `text/event-stream` with an `itemSchema` describing the SSE "
        "FRAME (`data`/`event`/`id`/`retry`), and that is deliberately NOT counted as a "
        "declared shape here: the frame envelope says nothing about the payloads, so this "
        "walk would go green while seeing no more than it does now. The four event "
        "payloads are modelled in `apps/api/copilot/schemas.py` and written out in the "
        "route's own `description`; the egress property this walk exists to protect is "
        "covered at RUNTIME by `apps/api/copilot/route_test.py` — the same split "
        "`GET /v1/leads/export.csv` above makes with tests/crm_egress_redaction_test.py."
    ),
    "POST /v1/admin/copilot/ask": (
        "the ADMIN twin of `POST /v1/copilot/ask` above (D-499), and exempt for exactly "
        "the same reason and no other: an SSE stream has no single 2xx model to declare, "
        "and the frame envelope FastAPI emits describes the SSE wrapper rather than the "
        "payloads. Listed separately instead of pattern-matching `*/copilot/ask`, because "
        "a pattern would silently exempt the next route somebody names that way — the "
        "admin realm reads across tenants, so a free-form 200 there is the more dangerous "
        "of the two, not the safer. The runtime egress property is covered by "
        "`tests/admin_copilot_billing_test.py` and the redaction guard the route shares "
        "with its client twin."
    ),
    "POST /v1/actions/invoke/{engine}/{tool_id}": (
        "the engine-called in-call action endpoint (source-IP gated like the webhook "
        "receiver, never a client dashboard route). The body IS the tool result the LLM "
        "reads back, and its shape is whatever the tenant-configured external API returns "
        "or a structured failure — genuinely open-ended, so there is no model to declare. "
        "It carries no Calevate-stored tenant data; the recipient is the engine/LLM."
    ),
}


def test_no_success_response_in_the_whole_app_is_an_undeclared_shape() -> None:
    """The generalisation of the test above, and the reason it had to be written.

    `test_the_openapi_response_schemas_are_inspectable` drives eleven operations BY NAME.
    It is a list, so it can only ever be behind the app: five admin routes
    (`.../kb/{source_id}/approve`, `/reject`, `/numbers/{number_id}/dlt-status` and the
    two DLT template writes) shipped `dict[str, str]` response models the whole time that
    list was green, because nobody had put them on it.

    Derived off the LIVE spec instead: every 2xx with a body must reference a schema that
    declares properties. The exemptions are enumerated with reasons — the same move
    `check_public_routes` makes — so a new free-form response is a reviewed line rather
    than a silence.
    """
    from scripts.check_redaction_exposure import _is_freeform_object

    spec = app.openapi()
    offenders: list[str] = []
    checked = 0
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            key = f"{method.upper()} {path}"
            for code, response in operation.get("responses", {}).items():
                if not code.startswith("2"):
                    continue
                content = response.get("content")
                if not content:
                    continue  # 204 and friends — the test above owns those.
                if key in _UNMODELLED_SUCCESS:
                    continue
                schema = next(iter(content.values())).get("schema", {})
                checked += 1
                if _is_freeform_object(schema) or schema == {}:
                    offenders.append(f"{key} -> {code} is a free-form object")
    assert not offenders, (
        "these operations answer with an undeclared shape, so the redaction guardrail "
        f"cannot inspect them and the typed client cannot describe them: {offenders}"
    )
    assert checked >= 120, f"only {checked} success responses inspected — the walk is broken"


def test_the_unmodelled_exemptions_still_name_live_operations() -> None:
    """The registry may only shrink (`check_public_routes` clause 2). An exemption that
    outlives its route is a standing permission waiting for the path to be reused."""
    spec = app.openapi()
    live = {
        f"{method.upper()} {path}"
        for path, operations in spec["paths"].items()
        for method in operations
    }
    stale = sorted(set(_UNMODELLED_SUCCESS) - live)
    assert not stale, f"_UNMODELLED_SUCCESS names operations that no longer exist: {stale}"
