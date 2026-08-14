"""Instant lead callback: webhook-in → lead → compliance gate → outbound (FLOWS §4).

Speed-to-lead is the product claim (form_ts → dial_ts under 60 seconds), but the order
of operations is compliance-first on purpose: a fast call to a number on the DNC list
is not a feature, it is a violation with a timestamp. So the lead row ALWAYS lands —
data first — and the dial happens only if the gate says yes. A blocked dispatch leaves
the lead in `new` with a timeline entry saying exactly which rule blocked it, which is
what the "needs attention" queue (SURFACES §2b) will read in M2.

Mapping: the `mapping` JSONB on `inbound_webhooks` translates the sender's field names
into ours ({"phone": "phone_number", "name": "full_name", …}). Vendors rename fields
without notice; a config row is redeployable per client without a release.

The consent provenance flag (FLOWS §4 step 2) is honored literally: if the config says
`consent_field` and the payload does not affirm it, we take the lead and refuse the
call. The form owner claiming "the form says we may call" is the client's PE
obligation; recording WHAT the payload asserted is ours.

The second half of this file (`# --- provisioning ---`) is where those config rows come
FROM. Until it existed every `inbound_webhooks` row was hand-written SQL by an operator,
which is why the Meta card on the client's own screen had to say "ask us"; the flow
above and the provisioning below share this module because they share the row, and a
create path that drifted from what `load_config` reads is exactly how a lead source
that configures cleanly starts rejecting every delivery.
"""

from __future__ import annotations

import hmac
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import dispatch_call
from apps.api.compliance.service import check_dispatch
from apps.api.core.alerting import metrics_log
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.integrations import service as integrations

log = get_logger(__name__)

# E.164-ish: our market is India, but a webhook may carry 10 digits with no prefix.
_INDIA_PREFIX = "+91"
# E.164 proper: a leading +, a non-zero country digit, 8-15 digits in total.
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
# The field names we read a number and a name out of when a source has no mapping
# (docs/WEBHOOKS.md §2.2). They are consumed into their own columns, so they must not
# also be copied into the free-form `data` blob.
_CONSUMED_KEYS = frozenset({"phone", "phone_number", "name"})

# The blocked-rule name for a source that requires form consent and names no consent
# field. Distinct from `no_form_consent` (the question WAS asked and was not affirmed)
# because they are different support tickets: this one is fixed in the lead form, that
# one is the person's own answer and must never be "fixed" at all.
NO_CONSENT_FIELD_RULE = "no_consent_field_configured"


def record_speed_to_lead(seconds: float, *, outcome: str) -> None:
    """The FLOWS §4 metric: form_ts → dial_ts, target < 60s. Named recorder per
    BACKEND-PATTERNS §8 so it can become an SLO rule without renaming."""
    metrics_log.info(
        "metric", extra={"metric": "speed_to_lead_seconds", "value": seconds, "outcome": outcome}
    )


def normalize_phone(raw: str) -> str | None:
    """Best-effort E.164. Returns None rather than guessing a country: dialling a
    wrong-country number because we assumed a prefix is worse than dropping the lead
    into the needs-attention queue.

    The other half of that promise is that what we DO return is dialable. Keeping every
    `+` in the string and then length-checking the result accepted `++91…` and
    `+91+98…` as phone numbers and wrote them to `phone_e164`, so the final `_E164`
    check is not belt-and-braces — it is the thing that makes the return type honest.
    """
    text = raw.strip()
    # A `+` is a country-code marker, and E.164 has exactly one, at the front. Anything
    # else is a malformed number, not a number we should clean up and dial.
    if text.count("+") > 1 or ("+" in text and not text.startswith("+")):
        return None
    digits = "".join(c for c in text if c.isdigit())

    if text.startswith("+"):
        # The sender named a country; we take their word for it but not their typos.
        candidate = "+" + digits if 10 <= len(digits) <= 15 else None
    elif len(digits) == 10 and digits[0] in "6789":
        candidate = _INDIA_PREFIX + digits
    elif len(digits) == 12 and digits.startswith("91"):
        candidate = "+" + digits
    else:
        candidate = None
    return candidate if candidate and _E164.match(candidate) else None


@dataclass(frozen=True, slots=True)
class IngestConfig:
    id: UUID
    tenant_id: UUID
    agent_id: UUID | None
    source: str
    mapping: dict[str, Any]
    secret_ref: str
    # The secret this one replaced, and the instant it stops counting. Both NULL outside
    # a rotation window; the DB constraint keeps them in step (migration a1c7d4e93b02).
    previous_secret_ref: str | None = None
    previous_secret_expires_at: datetime | None = None

    def accepted_secrets(self, *, now: datetime | None = None) -> tuple[str, ...]:
        """Every credential this endpoint honours right now, current one first.

        Rotation is a cutover, not an instant: the secret lives in a form vendor's
        settings screen, a Zapier action or a Meta app, and the window between our
        UPDATE and the client finishing the paste is a window in which submissions
        arrive signed with the old value. Answering 401 there loses enquiries, which is
        the one thing the ingest path exists not to do — so the retiring secret keeps
        verifying until `previous_secret_expires_at`, the way every webhook platform
        that has thought about it does (Stripe's rolled endpoint secrets carry an
        explicit expiry: https://docs.stripe.com/webhooks#roll-endpoint-secrets).

        Bounded on purpose, and bounded by DATA rather than by an operator's memory:
        nothing renews the window, so a rotation always ends with one live secret. A
        rotation with zero grace returns exactly one entry from the first request on,
        which is what a leaked secret needs.
        """
        live: list[str] = [self.secret_ref] if self.secret_ref else []
        expires = self.previous_secret_expires_at
        retiring = self.previous_secret_ref
        if retiring and expires is not None and (now or datetime.now(UTC)) < expires:
            live.append(retiring)
        return tuple(live)


async def load_config(session: AsyncSession, webhook_id: UUID) -> IngestConfig | None:
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, agent_id, source, mapping, secret_ref, "
                "previous_secret_ref, previous_secret_expires_at "
                "FROM inbound_webhooks WHERE id = :wid AND active"
            ),
            {"wid": webhook_id},
        )
    ).first()
    if row is None:
        return None
    return IngestConfig(
        id=row[0],
        tenant_id=row[1],
        agent_id=row[2],
        source=row[3],
        mapping=row[4] or {},
        secret_ref=row[5],
        previous_secret_ref=row[6],
        previous_secret_expires_at=row[7],
    )


def verify_ingest_secret(config: IngestConfig, presented: str | None) -> bool:
    """v1: `secret_ref` holds a per-endpoint shared secret compared in constant time.

    Honestly named as the interim it is: SEC-COMP §5 wants secrets in the manager and
    `secret_ref` as a REFERENCE, and Meta signs payloads properly (X-Hub-Signature-256)
    — both land when the secrets manager is wired at deploy time (DEPLOYMENT §6). The
    shape (per-endpoint secret, constant-time compare, 401 on mismatch) is already the
    final shape; only where the secret LIVES changes.

    Since rotation shipped there can be TWO live credentials during the grace window
    (`accepted_secrets`). Every candidate is compared — no early `return True` on the
    first match — so the work this function does depends on the endpoint's rotation
    state and not on which secret the caller happened to present.
    """
    if not presented:
        return False
    # Encoded first: `compare_digest` RAISES TypeError on a `str` with any non-ASCII
    # character, and header values arrive latin-1-decoded — so one accented byte in the
    # header turned a 401 into an unhandled 500 on the never-shed surface.
    offered = presented.encode("utf-8")
    matched = False
    for candidate in config.accepted_secrets():
        matched |= hmac.compare_digest(candidate.encode("utf-8"), offered)
    return matched


def lead_data(mapped: dict[str, Any], *, phone_e164: str) -> dict[str, Any]:
    """The free-form half of a lead row: everything the sender told us that is not
    already a column of its own.

    The number gets its own column AND its own masking rule at every serialization
    boundary (`LeadOut.phone_masked`). Copying it into `data` as well hands it straight
    back out through the one field on that model that is not masked — which is exactly
    what happened for a source with no mapping, where the payload is taken as-is and
    the number arrives under `phone_number` rather than `phone`.

    So: drop the keys we consumed, and drop any other value that IS this lead's number
    however the sender spelled it. A hostile sender does not get to smuggle it back in
    under a second name.
    """
    kept: dict[str, Any] = {}
    for key, value in mapped.items():
        if key in _CONSUMED_KEYS:
            continue
        if isinstance(value, str) and normalize_phone(value) == phone_e164:
            continue
        kept[key] = value
    return kept


def apply_mapping(mapping: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Sender's field names → ours. Only mapped fields survive: an unmapped field is
    unknown data from an external party, and it does not belong in a lead row."""
    fields: dict[str, Any] = {}
    for ours, theirs in mapping.items():
        if isinstance(theirs, str) and theirs in payload:
            fields[ours] = payload[theirs]
    return fields


async def ingest_lead(
    session: AsyncSession,
    *,
    config: IngestConfig,
    payload: dict[str, Any],
    received_at: float,
    require_form_consent: bool = False,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The whole flow, one transaction: lead row always, dial only if lawful.

    `require_form_consent` flips the default for sources where **the arrival of a
    record is not itself an assertion that the person may be telephoned**. On the
    shared-secret path the client's own system POSTs us a lead it decided to send, so
    a missing `consent_field` means "this client has not configured that question" and
    the dial proceeds. A Meta Lead Ads fill is not that: the person handed their number
    to Meta inside an ad unit, and reading it as permission for a voice agent to ring
    them is exactly the assumed consent hard rule 5 and DPDP §6 forbid. With this set,
    a source that names no consent field keeps the lead and refuses the call.

    `provenance` is OUR record of where the lead came from, merged into `leads.data`
    alongside the mapped fields. It bypasses the mapping on purpose — `apply_mapping`
    drops unmapped keys because an unmapped key is unknown data from an external party,
    and this is not that: it is what we know, and no client should have to map it to
    keep it. Ids only; nothing here may carry an answer.
    """
    mapped = apply_mapping(config.mapping, payload) if config.mapping else dict(payload)

    raw_phone = str(mapped.get("phone") or mapped.get("phone_number") or "")
    phone = normalize_phone(raw_phone) if raw_phone else None
    if phone is None:
        # No number, no lead — there is nothing to call and nothing to key on.
        raise ProblemError(
            kind="validation",
            code="ingest_no_phone",
            title="No usable phone number",
            detail="The payload did not contain a phone number we could dial.",
            fields=[{"field": "phone", "rule": "required", "message": "missing or malformed"}],
        )
    name = str(mapped.get("name") or "").strip() or None

    if config.agent_id is None:
        raise ProblemError.business_rule(
            "ingest_no_agent",
            "This lead source has no agent attached yet.",
            remediation="Attach an agent to the webhook in the admin console.",
        )

    # THE SAME REFUSAL `dispatch_call` ALREADY MAKES, MOVED IN FRONT OF THE INSERT.
    #
    # It is not a new rule and not a new error code: an unpublished agent could never
    # be dialled, and step 4 below has always raised `agent_not_published` for it. What
    # was new was WHERE it landed. Raising it after the lead row meant the outcome
    # depended on which exit the request took: on the dial path the ProblemError rolled
    # the whole transaction back and the lead vanished, while on the two early returns
    # (consent provenance, compliance gate) the request succeeded and the lead was KEPT.
    # One misconfiguration, two opposite answers, and the surviving half was the half
    # nothing could ever delete.
    #
    # Why "nothing could ever delete": `apps/workers/retention.py::_due_tenants` resolves
    # its worklist from `engine_agent_routes`, the global bridge, because a cross-tenant
    # resolution must not need the admin role (hard rule 1). `publish_agent` writes that
    # route in the same transaction as `agents.engine_agent_ref`, so the column checked
    # here and the row the sweep reads are one fact. A tenant that has never published
    # ANY agent is therefore in no worklist, and a lead it kept ages forever — personal
    # data outliving its `lead` TTL, which is a DPDP obligation and not a preference.
    #
    # Refusing costs the enquiry, and that cost is paid knowingly: the sender gets a 422
    # naming the fix, the client cannot call anybody in this state anyway, and the moment
    # they publish, every later lead both lands and expires on schedule. Keeping the lead
    # instead would mean the platform can hold personal data with no route to it, which
    # is the invariant the sweep is built on.
    ref = (
        await session.execute(
            text("SELECT engine_agent_ref FROM agents WHERE id = :aid"),
            {"aid": config.agent_id},
        )
    ).scalar()
    if not isinstance(ref, str) or not ref:
        raise ProblemError.business_rule(
            "agent_not_published",
            "This agent has not been published to the voice platform yet.",
            remediation="Publish the agent from the admin console, then resend the lead.",
        )

    # 1. THE LEAD ALWAYS LANDS. A compliance block or an engine failure below must
    # not lose the enquiry — the data is the client's either way.
    lead_id = uuid7()
    row = (
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, :name, "
                "'webhook', 'new', CAST(:data AS jsonb), now(), now()) "
                "ON CONFLICT (tenant_id, phone_e164, agent_id) DO UPDATE SET "
                "  name = COALESCE(EXCLUDED.name, leads.name), "
                "  data = leads.data || EXCLUDED.data, "
                "  updated_at = now() "
                "RETURNING id"
            ),
            {
                "id": lead_id,
                "tid": config.tenant_id,
                "aid": config.agent_id,
                "phone": phone,
                "name": name,
                "data": _json(
                    {**lead_data(mapped, phone_e164=phone), **(provenance or {})},
                ),
            },
        )
    ).first()
    resolved_lead = UUID(str(row[0])) if row else lead_id

    # D-23: the client's CRM hears about it in the SAME transaction as the lead row —
    # before the gate, before the dial, because the lead landing is the fact being
    # reported. Whether we then called them is a separate event.
    #
    # The domain row goes in as-is: `enqueue_event` masks the phone per endpoint at the
    # fan-out, which is the only place that knows whether THIS endpoint opted in
    # (docs/WEBHOOKS.md §1.2). Masking here instead would apply one answer to every
    # subscriber.
    await integrations.enqueue_event(
        session,
        tenant_id=config.tenant_id,
        event="lead.created",
        data={
            "lead_id": str(resolved_lead),
            "phone": phone,
            "name": name,
            "source": "webhook",
            "status": "new",
        },
    )

    # 2. Consent provenance (FLOWS §4): if the config names a consent field, the
    # payload must affirm it. We keep the lead and refuse the CALL.
    consent_field = config.mapping.get("consent_field")
    if not (isinstance(consent_field, str) and consent_field) and require_form_consent:
        # The source asserts nothing about permission and the caller has told us that
        # arriving is not consenting. Keep the lead, refuse the dial, and name the fix
        # (add the question to the lead form) rather than the symptom.
        await _timeline(
            session, config.tenant_id, resolved_lead, "blocked", {"rule": NO_CONSENT_FIELD_RULE}
        )
        record_speed_to_lead(time.time() - received_at, outcome="blocked_consent")
        return {"lead_id": resolved_lead, "dispatched": False, "blocked": NO_CONSENT_FIELD_RULE}
    if isinstance(consent_field, str) and consent_field:
        consent_value = str(payload.get(consent_field, "")).strip().lower()
        if consent_value not in ("true", "yes", "1", "on"):
            await _timeline(
                session, config.tenant_id, resolved_lead, "blocked", {"rule": "no_form_consent"}
            )
            record_speed_to_lead(time.time() - received_at, outcome="blocked_consent")
            return {"lead_id": resolved_lead, "dispatched": False, "blocked": "no_form_consent"}

    # 3. The compliance gate — the same one every dispatch path calls (hard rule 5).
    decision = await check_dispatch(
        session, tenant_id=config.tenant_id, agent_id=config.agent_id, phone_e164=phone
    )
    if not decision.allowed:
        await _timeline(
            session, config.tenant_id, resolved_lead, "blocked", {"rule": decision.rule}
        )
        record_speed_to_lead(time.time() - received_at, outcome=f"blocked_{decision.rule}")
        return {"lead_id": resolved_lead, "dispatched": False, "blocked": decision.rule}

    # 4. Dial, with the form fields as context so the agent opens with
    # "you enquired about…" rather than a cold open.
    handle = await dispatch_call(
        session,
        tenant_id=config.tenant_id,
        agent_id=config.agent_id,
        lead_id=resolved_lead,
        phone_e164=phone,
        lead_name=name,
        context_note=f"Enquiry via {config.source}",
    )
    await _timeline(session, config.tenant_id, resolved_lead, "call", {"engine_call_id": handle})
    elapsed = time.time() - received_at
    record_speed_to_lead(elapsed, outcome="dispatched")
    log.info(
        "lead_callback_dispatched",
        extra={"lead_id": str(resolved_lead), "speed_to_lead_s": round(elapsed, 2)},
    )
    return {"lead_id": resolved_lead, "dispatched": True, "call_handle": handle}


async def _timeline(
    session: AsyncSession, tenant_id: UUID, lead_id: UUID, kind: str, payload: dict[str, Any]
) -> None:
    await session.execute(
        text(
            "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
            "created_at, updated_at) VALUES (:id, :tid, :lid, :type, CAST(:payload AS jsonb), "
            "'system', now(), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "lid": lead_id,
            # lead_events.type is a fixed enum; "blocked" maps onto "note".
            "type": "call" if kind == "call" else "note",
            "payload": _json({"kind": kind, **payload}),
        },
    )


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


# --- provisioning -------------------------------------------------------------
#
# WHERE THE SECRET LIVES, SAID ONCE AND PLAINLY.
#
# `secret_ref` holds the credential VALUE, not a secrets-manager pointer, and this
# module does not change that — `verify_ingest_secret` above already names it as the
# interim SEC-COMP §5 replaces, and `outbound_webhooks` stores its signing secret the
# same way (integrations/routes.py `create_endpoint`). One scheme for both directions
# is the point: the day the manager is wired, ONE resolver turns both columns into
# references, and a create path that had invented a second scheme in the meantime would
# be the thing blocking it.
#
# A hash instead of the value was considered and rejected, and the reason is structural
# rather than a preference: a `meta_lead_ads` source's `secret_ref` is the Meta App
# Secret, and both things done with it — HMAC-verifying `X-Hub-Signature-256` over the
# raw body, and deriving the `hub.verify_token` — need the secret itself. Hashing only
# the sources where it happens to work would put two storage schemes in one column, and
# the next reader would have to know which is which before they could verify anything.

# The upper bound on a rotation grace window. A day is long enough to cover a client
# who rotates on Friday evening and updates their form vendor on Monday; anything
# longer stops being a cutover and becomes a second permanent credential.
MAX_GRACE_MINUTES = 24 * 60

# The mapping is config a human typed, not a payload: these bounds exist so a bad paste
# is refused at the config screen rather than stored and re-read on every delivery.
MAX_MAPPING_ENTRIES = 50
MAX_MAPPING_FIELD_LEN = 128

# The mapping keys `ingest_lead` reads a dialable number out of. A non-empty mapping
# that names neither is a lead source that would answer `ingest_no_phone` to every
# delivery it ever receives.
PHONE_MAPPING_KEYS = ("phone", "phone_number")

# The one source whose secret we cannot mint, because it is not ours: Meta signs with
# the App Secret from the client's own Meta app (ingest/meta.py). Spelled here as a
# property of PROVISIONING — "the client brings this credential" — which is why it is
# not imported from `routes.META_SOURCE`, whose meaning is "the source this receiver is
# written for".
CLIENT_SUPPLIED_SECRET_SOURCES = frozenset({"meta_lead_ads"})


@dataclass(frozen=True, slots=True)
class LeadSourceSummary:
    """One lead source as a config screen may see it. NEVER carries a secret value —
    the fingerprint is the whole of what leaves the database after creation."""

    id: UUID
    source: str
    agent_id: UUID | None
    active: bool
    mapping: dict[str, str]
    secret_fingerprint: str
    previous_secret_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


def mint_secret() -> str:
    """A shared secret for a source whose sender we hand it to.

    `token_urlsafe(32)` — 256 bits, the same generator and the same width as the
    outbound signing secret, and URL-safe because a client will paste it into a form
    vendor's header field where a `+` or a `/` gets mangled by somebody's encoder.
    """
    return secrets.token_urlsafe(32)


def readable_mapping(raw: object) -> dict[str, str]:
    """The mapping entries that DO something, as strings.

    `apply_mapping` ignores any entry whose value is not a string, so a config screen
    that rendered the raw JSONB would show rules the ingest path does not follow. This
    returns exactly the effective set — which is also what keeps the response model off
    `dict[str, Any]`, the shape `scripts/check_redaction_exposure.py` refuses because a
    free-form dict serializes whatever the query happened to select.
    """
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, str)}


def validate_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """Refuse a mapping that could only ever produce rejected deliveries.

    An empty mapping is legal and means "take the payload as it comes" — `ingest_lead`
    reads `phone`/`phone_number`/`name` straight off the body, which is what a bare
    custom POST wants. A NON-empty mapping that names no phone field is different: every
    delivery through it answers 422 `ingest_no_phone`, forever. Refusing once here
    rather than once per lead is the same trade `create_sheets_endpoint` makes about a
    column order it cannot infer.
    """
    cleaned = {key.strip(): value.strip() for key, value in mapping.items()}
    if len(cleaned) > MAX_MAPPING_ENTRIES:
        raise ProblemError(
            kind="validation",
            code="mapping_too_large",
            title="Too many field mappings",
            detail=f"A lead source maps at most {MAX_MAPPING_ENTRIES} fields.",
            fields=[{"field": "mapping", "rule": "max_entries", "message": "too many"}],
        )
    for key, value in cleaned.items():
        if not key or not value:
            raise ProblemError(
                kind="validation",
                code="mapping_blank_field",
                title="A field mapping is blank",
                detail="Every mapping needs both our field name and the name your form sends.",
                fields=[{"field": "mapping", "rule": "non_empty", "message": key or "(blank)"}],
            )
        if len(key) > MAX_MAPPING_FIELD_LEN or len(value) > MAX_MAPPING_FIELD_LEN:
            raise ProblemError(
                kind="validation",
                code="mapping_field_too_long",
                title="A field name is too long",
                detail=f"Field names are limited to {MAX_MAPPING_FIELD_LEN} characters.",
                fields=[{"field": "mapping", "rule": "max_length", "message": key}],
            )
    if cleaned and not any(key in cleaned for key in PHONE_MAPPING_KEYS):
        raise ProblemError(
            kind="validation",
            code="mapping_has_no_phone",
            title="The mapping never finds a phone number",
            detail=(
                "This mapping would reject every lead: none of its rules says which "
                "field of your form carries the phone number."
            ),
            remediation=(
                "Add a mapping from `phone` to the field name your form sends, or "
                "remove the mapping entirely to have us read the payload as it comes."
            ),
            fields=[{"field": "mapping", "rule": "phone_required", "message": "no phone rule"}],
        )
    return cleaned


async def _agent_is_ours(session: AsyncSession, agent_id: UUID) -> bool:
    """Hard rule 1 in one query: the session is tenant-scoped, so an agent belonging to
    anyone else reads back as zero rows and this returns False.

    Worth doing even though `inbound_webhooks.agent_id` has a foreign key: the FK is to
    the GLOBAL `agents` table and knows nothing about tenancy, so it would happily
    accept another tenant's agent id and leave a config row that dispatches through it.
    """
    return (
        await session.execute(text("SELECT 1 FROM agents WHERE id = :aid"), {"aid": agent_id})
    ).first() is not None


async def create_lead_source(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    source: str,
    agent_id: UUID | None,
    mapping: dict[str, str],
    supplied_secret: str | None,
) -> tuple[UUID, str | None]:
    """Returns `(id, minted_secret)`; `minted_secret` is None when the client brought
    their own (Meta), because there is nothing of ours to show them once.

    Created ACTIVE, for the reason `create_sheets_endpoint` gives: there is a route to
    disable and a route to re-enable, so an inactive-on-create row would be a source
    that silently 404s every delivery while its screen says it exists.
    """
    cleaned = validate_mapping(mapping)
    if agent_id is not None and not await _agent_is_ours(session, agent_id):
        raise ProblemError.not_found("Agent")

    needs_supplied = source in CLIENT_SUPPLIED_SECRET_SOURCES
    if needs_supplied and not supplied_secret:
        raise ProblemError(
            kind="validation",
            code="app_secret_required",
            title="This source needs your app secret",
            detail=(
                "Meta signs every notification with your Meta app's App Secret, so we "
                "cannot generate one for you — paste yours here."
            ),
            remediation=(
                "Find it under App settings → Basic → App secret in the Meta App Dashboard."
            ),
            fields=[{"field": "app_secret", "rule": "required", "message": "missing"}],
        )
    if supplied_secret and not needs_supplied:
        raise ProblemError(
            kind="validation",
            code="app_secret_not_accepted",
            title="This source does not take a secret you supply",
            detail="We generate the secret for this kind of lead source and show it once.",
            remediation="Create the source without a secret and copy the one we return.",
            fields=[{"field": "app_secret", "rule": "not_accepted", "message": source}],
        )

    minted = None if needs_supplied else mint_secret()
    webhook_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, agent_id, "
            "mapping, active, created_at, updated_at) VALUES (:id, :tid, :source, :secret, "
            ":aid, CAST(:mapping AS jsonb), true, now(), now())"
        ),
        {
            "id": webhook_id,
            # Written from the principal, but the INSERT runs under the session's RLS
            # context, whose policy carries a WITH CHECK on `tenant_id` (migration
            # d41f88a2c6e9) — so a mismatched tenant is refused by the policy rather
            # than by this line (hard rule 1).
            "tid": tenant_id,
            "source": source,
            "secret": supplied_secret or minted,
            "aid": agent_id,
            "mapping": _json(cleaned),
        },
    )
    return webhook_id, minted


async def list_lead_sources(session: AsyncSession) -> list[LeadSourceSummary]:
    """Every lead source this tenant has. Scoped by RLS, never by a WHERE clause —
    the session's GUC is the tenancy boundary and a hand-written predicate beside it
    would be a second, weaker one."""
    rows = (
        await session.execute(
            text(
                "SELECT id, source, agent_id, active, mapping, secret_ref, "
                "previous_secret_ref, previous_secret_expires_at, created_at, updated_at "
                "FROM inbound_webhooks ORDER BY created_at DESC"
            )
        )
    ).all()
    now = datetime.now(UTC)
    return [
        LeadSourceSummary(
            id=row[0],
            source=str(row[1]),
            agent_id=row[2],
            active=bool(row[3]),
            mapping=readable_mapping(row[4]),
            # The VALUE never leaves the database after creation; this says only which
            # secret we hold, which is what answers "is the one in my form the current
            # one" without disclosing either.
            secret_fingerprint=integrations.secret_fingerprint(str(row[5])),
            # Reported only while it is still true. A window that closed an hour ago is
            # not a rotation in progress, and rendering it as one would have a client
            # waiting for something that already happened.
            previous_secret_expires_at=(row[7] if row[6] and row[7] and now < row[7] else None),
            created_at=row[8],
            updated_at=row[9],
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class Rotation:
    secret: str | None
    previous_secret_expires_at: datetime | None


async def rotate_secret(
    session: AsyncSession,
    *,
    webhook_id: UUID,
    grace_minutes: int,
    supplied_secret: str | None,
) -> Rotation:
    """Install a new secret and put the old one on a clock.

    ONE statement, so there is no window in which the row holds a new secret and no
    record of the old one — a crash between two statements would be a rotation that
    revoked instantly while the client was told they had an hour. The old value is read
    from the row inside the same UPDATE (`secret_ref` on the right-hand side is the
    pre-update value in Postgres), which also means two concurrent rotations serialize
    on the row lock rather than racing to overwrite each other's grace window.

    `grace_minutes = 0` writes NULL into both columns, which is a revocation: the moment
    this commits, the old secret is refused. That is the correct answer for a leak and
    the wrong default for a planned rotation, so the route defaults it high and the
    caller has to ask for zero.
    """
    if not 0 <= grace_minutes <= MAX_GRACE_MINUTES:
        raise ProblemError(
            kind="validation",
            code="grace_out_of_range",
            title="Grace period out of range",
            detail=f"The old secret may stay valid for at most {MAX_GRACE_MINUTES} minutes.",
            fields=[{"field": "grace_minutes", "rule": "range", "message": str(grace_minutes)}],
        )
    minted = None if supplied_secret else mint_secret()
    row = (
        await session.execute(
            text(
                "UPDATE inbound_webhooks SET "
                "  secret_ref = :new, "
                "  previous_secret_ref = CASE WHEN :grace > 0 THEN secret_ref END, "
                "  previous_secret_expires_at = CASE WHEN :grace > 0 "
                "    THEN now() + make_interval(mins => :grace) END, "
                "  updated_at = now() "
                "WHERE id = :id RETURNING previous_secret_expires_at"
            ),
            {"id": webhook_id, "new": supplied_secret or minted, "grace": grace_minutes},
        )
    ).first()
    if row is None:
        # Under RLS "no such source" and "another tenant's source" are the same answer,
        # deliberately (ProblemError.not_found says so).
        raise ProblemError.not_found("Lead source")
    return Rotation(secret=minted, previous_secret_expires_at=row[0])


async def set_active(session: AsyncSession, *, webhook_id: UUID, active: bool) -> bool:
    """CAS on the flag (BACKEND-PATTERNS §5); True when this call is what changed it.

    Idempotent rather than 404-on-repeat: the second click of "Disable" is the same
    request as the first and the source really is disabled, so answering "not found"
    would be a lie about a row we just read. The return value is what keeps the audit
    honest — only a real transition is written, so the ledger records changes rather
    than button presses.

    A rotation window is closed by DISABLING as well, and that is not tidiness: a
    source is disabled because something is wrong with it, and leaving a superseded
    secret armed to wake up with it is the opposite of what the operator asked for.
    """
    result = await session.execute(
        text(
            "UPDATE inbound_webhooks SET active = :active, updated_at = now(), "
            "  previous_secret_ref = CASE WHEN :active THEN previous_secret_ref END, "
            "  previous_secret_expires_at = CASE WHEN :active "
            "    THEN previous_secret_expires_at END "
            "WHERE id = :id AND active = :was"
        ),
        {"id": webhook_id, "active": active, "was": not active},
    )
    if rowcount_of(result) == 1:
        return True
    exists = (
        await session.execute(
            text("SELECT 1 FROM inbound_webhooks WHERE id = :id"), {"id": webhook_id}
        )
    ).first()
    if exists is None:
        raise ProblemError.not_found("Lead source")
    return False


__all__ = [
    "CLIENT_SUPPLIED_SECRET_SOURCES",
    "MAX_GRACE_MINUTES",
    "NO_CONSENT_FIELD_RULE",
    "PHONE_MAPPING_KEYS",
    "IngestConfig",
    "LeadSourceSummary",
    "Rotation",
    "apply_mapping",
    "create_lead_source",
    "ingest_lead",
    "lead_data",
    "list_lead_sources",
    "load_config",
    "mint_secret",
    "normalize_phone",
    "readable_mapping",
    "record_speed_to_lead",
    "rotate_secret",
    "set_active",
    "validate_mapping",
    "verify_ingest_secret",
]
