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
"""

from __future__ import annotations

import hmac
import re
import time
from dataclasses import dataclass
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


async def load_config(session: AsyncSession, webhook_id: UUID) -> IngestConfig | None:
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, agent_id, source, mapping, secret_ref "
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
    )


def verify_ingest_secret(config: IngestConfig, presented: str | None) -> bool:
    """v1: `secret_ref` holds a per-endpoint shared secret compared in constant time.

    Honestly named as the interim it is: SEC-COMP §5 wants secrets in the manager and
    `secret_ref` as a REFERENCE, and Meta signs payloads properly (X-Hub-Signature-256)
    — both land when the secrets manager is wired at deploy time (DEPLOYMENT §6). The
    shape (per-endpoint secret, constant-time compare, 401 on mismatch) is already the
    final shape; only where the secret LIVES changes.
    """
    if not presented or not config.secret_ref:
        return False
    # Encoded first: `compare_digest` RAISES TypeError on a `str` with any non-ASCII
    # character, and header values arrive latin-1-decoded — so one accented byte in the
    # header turned a 401 into an unhandled 500 on the never-shed surface.
    return hmac.compare_digest(config.secret_ref.encode("utf-8"), presented.encode("utf-8"))


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
) -> dict[str, Any]:
    """The whole flow, one transaction: lead row always, dial only if lawful."""
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
                "data": _json(lead_data(mapped, phone_e164=phone)),
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


__all__ = [
    "IngestConfig",
    "apply_mapping",
    "ingest_lead",
    "lead_data",
    "load_config",
    "normalize_phone",
    "record_speed_to_lead",
    "verify_ingest_secret",
]
