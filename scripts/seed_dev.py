"""Demo credentials and demo data for a LOCAL stack — so both panels can be LOOKED at.

`scripts/seed.py` seeds the rows a real deployment needs (reserved slugs) and deliberately
creates no tenant and no account: on a real host the first operator arrives through
`scripts/bootstrap_admin.py`, which mails a single-use link and refuses to run twice, and
the first client arrives through the onboarding wizard. That is correct for a deployment
and useless for development, where the question is "what does the client dashboard look
like with calls in it" and the answer currently requires driving the whole onboarding flow
by hand before a single screen has anything on it.

So this is the OTHER motion, and it is a second way to create an account on purpose rather
than by drift. The two do not overlap and could not be merged without one of them getting
worse:

  bootstrap_admin.py   deployed hosts · mails a link · no password ever printed ·
                       REFUSES if the deployment already has an operator with a password
  seed_dev.py          `APP_ENV=local` only · fixed password printed to the terminal ·
                       re-runnable, and re-running RESETS the passwords it owns

**IT CANNOT RUN ANYWHERE BUT A LOCAL STACK, and there is no `--force`.** The gate is
`Settings.app_env == "local"` — the same value `core/auth.py::_dev_tokens_enabled` requires
before it will accept a `dev:` bearer token, so the deployments where a known password is
acceptable are exactly the deployments where an unauthenticated bypass already is. `app_env`
has no default and is in `BOOTSTRAP_REQUIRED` (D-49), so there is no way to reach `"local"`
by forgetting to set something.

**The passwords are in this file, in the clear, and that is the point.** They are not
secrets: they only exist on a developer's laptop, they are printed to stdout when the script
runs, and every account they open is created by this script and by nothing else. Hard rule 6
is about PII and credentials in LOGS — this writes to a terminal, on a box whose database
contains fabricated names and 555-prefixed numbers. Nothing here is written to `.env`, so
nothing here can leak into a container image or a deploy.

WHAT THE DEMO NUMBERS ARE. Every `to_e164`/`from_e164` below is in `+9199` + `00000`…,
which is not a dialable Indian mobile range — a demo row that could be dialled by a
mis-pointed campaign is a demo row that eventually is.

WHAT THIS DOES NOT FAKE. The agent is published through `agents.service.publish_agent`, the
same call the console makes, so on a stack running `ENGINE=fake` the agent reaches `live`
the way it really does and on a stack pointed at a real engine it either really publishes or
really fails. If publishing fails the seed still finishes and says so: an agent in `draft`
is an honest screen, an agent set to `live` by an UPDATE would be a lie the compliance drift
sweep would later have to catch.

USAGE — with the same environment `alembic upgrade head` needs, after migrations:

    uv run alembic upgrade head
    uv run python -m scripts.seed          # reserved slugs (this script needs them)
    uv run python -m scripts.seed_dev      # accounts + a tenant with calls and leads

Re-running is safe and is the supported way to get back to a known state: the accounts,
the tenant and the demo rows are all keyed, and the passwords are re-set on every run.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.api.db.base import uuid7
from sqlalchemy import text

# ── the accounts this script owns ──────────────────────────────────────────────
#
# `.local` rather than `example.com`: RFC 6761 reserves `.local` for link-local names that
# resolve nowhere, so a stray notification job cannot deliver one of these anywhere. It also
# makes a seeded address unmistakable in a mailbox screenshot.
ADMIN_EMAIL = "ops@calevate.local"
ADMIN_NAME = "Dev Operator"
ADMIN_PASSWORD = "CalevateDev!2026"

OWNER_EMAIL = "owner@sunrise-dental.local"
OWNER_NAME = "Padma Rao"
OWNER_PASSWORD = "CalevateDev!2026"

STAFF_EMAIL = "staff@sunrise-dental.local"
STAFF_NAME = "Kiran Kumar"
STAFF_PASSWORD = "CalevateDev!2026"

TENANT_NAME = "Sunrise Dental Care"
TENANT_SLUG = "sunrise-dental"
TENANT_VERTICAL = "clinic"
TENANT_LANGUAGE = "en-IN"

#: `managed` rather than a self-serve tier, because that is the pilot motion (D-34
#: motion 1) and because the self-serve tiers put a wallet balance in front of every
#: dial — a seeded stack whose first campaign refuses `wallet_empty` is a support
#: question rather than a demo.
TENANT_PLAN_TIER = "managed"


@dataclass(frozen=True, slots=True)
class DemoCall:
    """One row of the story the seeded dashboard tells.

    Every field a screen renders is named here rather than derived, so changing what the
    demo looks like is an edit to this list and not to the code below it.
    """

    minutes_ago: int
    direction: str
    peer_e164: str
    duration_s: int
    outcome_tag: str
    sentiment: str
    summary: str
    caller_name: str
    lead_status: str
    turns: tuple[tuple[str, str], ...]
    extraction: dict[str, Any]


# Six calls: two hot leads, one resolved, one follow-up, one transfer, one dropped — so the
# "needs attention" queue, the funnel and the outcome breakdown all have something in them
# rather than each needing its own hand-made row later.
DEMO_CALLS: tuple[DemoCall, ...] = (
    DemoCall(
        minutes_ago=35,
        direction="inbound",
        peer_e164="+919900000101",
        duration_s=142,
        outcome_tag="needs_follow_up",
        sentiment="positive",
        summary="Asked about clear aligners and pricing; wants a consultation this week.",
        caller_name="Anitha Reddy",
        lead_status="hot",
        turns=(
            ("agent", "Sunrise Dental, this is an AI assistant. How can I help you today?"),
            ("caller", "Hi, I wanted to ask about the clear aligner treatment."),
            ("agent", "Of course. Aligner treatment starts at forty thousand rupees."),
            ("caller", "That works. Can I come in on Thursday morning?"),
            ("agent", "Thursday at eleven is free. May I take your name?"),
            ("caller", "Anitha Reddy."),
        ),
        extraction={
            "intent": "appointment",
            "urgency": "high",
            "preferred_time": "Thursday 11:00",
            "treatment": "clear aligners",
        },
    ),
    DemoCall(
        minutes_ago=95,
        direction="inbound",
        peer_e164="+919900000102",
        duration_s=68,
        outcome_tag="resolved",
        sentiment="neutral",
        summary="Confirmed clinic timings and parking. No booking needed.",
        caller_name="Suresh Babu",
        lead_status="contacted",
        turns=(
            ("agent", "Sunrise Dental, this is an AI assistant. How can I help you?"),
            ("caller", "What time do you close today?"),
            ("agent", "We are open until eight in the evening, seven days a week."),
            ("caller", "Great, thank you."),
        ),
        extraction={"intent": "information", "urgency": "low", "treatment": None},
    ),
    DemoCall(
        minutes_ago=190,
        direction="outbound",
        peer_e164="+919900000103",
        duration_s=203,
        outcome_tag="needs_follow_up",
        sentiment="positive",
        summary="Recall call for a six-month cleaning; asked to be called back after Diwali.",
        caller_name="Lakshmi Prasad",
        lead_status="interested",
        turns=(
            ("agent", "Good afternoon, calling from Sunrise Dental. This call is recorded."),
            ("caller", "Yes, go ahead."),
            ("agent", "Your six-month cleaning is due. Shall I book a slot?"),
            ("caller", "Call me after Diwali, I will be travelling."),
        ),
        extraction={"intent": "recall", "urgency": "medium", "callback_after": "Diwali"},
    ),
    DemoCall(
        minutes_ago=310,
        direction="inbound",
        peer_e164="+919900000104",
        duration_s=88,
        outcome_tag="transferred",
        sentiment="negative",
        summary="Complaint about a crown fitted last month; transferred to the front desk.",
        caller_name="Ravi Teja",
        lead_status="contacted",
        turns=(
            ("agent", "Sunrise Dental, this is an AI assistant."),
            ("caller", "The crown you fitted last month is hurting."),
            ("agent", "I am sorry to hear that. Let me put you through to the front desk."),
        ),
        extraction={"intent": "complaint", "urgency": "high", "treatment": "crown"},
    ),
    DemoCall(
        minutes_ago=420,
        direction="inbound",
        peer_e164="+919900000105",
        duration_s=19,
        outcome_tag="dropped",
        sentiment="neutral",
        summary="Caller hung up during the greeting.",
        caller_name="Unknown caller",
        lead_status="new",
        turns=(("agent", "Sunrise Dental, this is an AI assistant. How can I help you?"),),
        extraction={"intent": None, "urgency": "low"},
    ),
    DemoCall(
        minutes_ago=1500,
        direction="outbound",
        peer_e164="+919900000106",
        duration_s=176,
        outcome_tag="resolved",
        sentiment="positive",
        summary="Booked a root canal consultation for Monday morning.",
        caller_name="Meena Joseph",
        lead_status="won",
        turns=(
            ("agent", "Good morning, calling from Sunrise Dental. This call is recorded."),
            ("caller", "Yes, I was expecting your call."),
            ("agent", "Monday at ten works for the consultation. Shall I confirm?"),
            ("caller", "Please do."),
        ),
        extraction={"intent": "appointment", "urgency": "medium", "treatment": "root canal"},
    ),
)


def _refuse_unless_local() -> None:
    """The whole safety story, in one function, before anything is imported that connects.

    Reads `Settings` rather than `os.environ["APP_ENV"]` so that a stack configuring itself
    through a `.env` file is judged on the value the APPLICATION resolves — the two differ
    exactly often enough for a bare `os.environ` check to be a false sense of safety.
    """
    from apps.api.core.settings import get_settings

    app_env = get_settings().app_env
    if app_env != "local":
        raise SystemExit(
            f"refusing: APP_ENV is {app_env!r}, and this script only runs on 'local'.\n"
            "It creates accounts with passwords that are published in its own source. "
            "On a deployed host use `scripts/bootstrap_admin.py`, which mails a "
            "single-use link instead. There is deliberately no override."
        )


async def _upsert_admin(*, email: str, name: str, role: str) -> UUID:
    """The operator allowlist row, idempotently.

    `authn.bootstrap.bootstrap_first_admin` is the deployed path and cannot be reused here:
    it refuses outright once ANY operator has a password, which is the second run of this
    script. Its INSERT is copied rather than shared because what differs is the whole
    decision around it — that function's value is the refusal, and a version of it that can
    be told not to refuse is not worth having.
    """
    from apps.api.db.session import credential_session

    now = datetime.now(UTC)
    async with credential_session() as session:
        found = (
            await session.execute(
                text("SELECT id FROM admin_users WHERE lower(email) = :e"),
                {"e": email.casefold()},
            )
        ).first()
        if found is not None:
            await session.commit()
            return UUID(str(found[0]))
        admin_id = uuid7()
        await session.execute(
            text(
                # `clerk_user_id` is unnamed for the reason `bootstrap.py` gives: nothing
                # writes it since D-177 and naming it would be an opinion about a column
                # hard rule 8's second step is going to drop.
                "INSERT INTO admin_users (id, email, name, role, created_at, updated_at) "
                "VALUES (:id, :email, :name, :role, :now, :now)"
            ),
            {"id": admin_id, "email": email, "name": name, "role": role, "now": now},
        )
        await session.commit()
        return admin_id


async def _upsert_user(*, email: str, name: str) -> UUID:
    """A client-realm identity. `users` is global and has no RLS (DATA-MODEL §2)."""
    # A PRIVATE name imported on purpose, and the underscore is not an oversight in either
    # direction. `_find_or_create_user` owns the `ON CONFLICT (lower(email)) WHERE
    # deactivated_at IS NULL` and the lost-race re-read under it, so a second hand-written
    # INSERT here would be the drift CLAUDE.md's "one way per problem" forbids. It stays
    # underscored because its `created` flag is the enumeration oracle `authn/subjects.py`
    # argues must never reach a route — a local-only seed script is not a route, and the
    # marker is worth more on the function than the tidiness is worth here.
    from apps.api.authn.invitations import _find_or_create_user

    user_id, _created = await _find_or_create_user(email=email, name=name, at=datetime.now(UTC))
    return user_id


async def _set_password(*, realm: str, subject_id: UUID, password: str) -> None:
    """Install the demo password, every run.

    Re-setting rather than skipping is what makes this script a way BACK to a known state:
    a developer who changed a password while testing the reset flow gets the documented one
    again by re-running the seed, instead of a silent no-op and a login they cannot make.

    Sessions are revoked in the same transaction — `credentials.set_password` requires the
    caller to decide, and the correct answer here is the compromise answer: the password
    just changed under whoever was holding a cookie for it.
    """
    from apps.api.authn.credentials import set_password
    from apps.api.authn.sessions import revoke_subject_sessions
    from apps.api.db.session import credential_session

    async with credential_session() as session:
        await set_password(session, realm=realm, subject_id=subject_id, password=password)
        await revoke_subject_sessions(session, realm=realm, subject_id=subject_id)
        await session.commit()


async def _existing_tenant(slug: str) -> UUID | None:
    """`admin_session`, because RLS hides every tenant from an untenanted read."""
    from apps.api.db.session import admin_session

    async with admin_session() as session:
        row = (
            await session.execute(
                text("SELECT id FROM organizations WHERE slug = :slug"), {"slug": slug}
            )
        ).first()
        return UUID(str(row[0])) if row is not None else None


async def _tenant_agent(tenant_id: UUID) -> UUID:
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT id FROM agents WHERE tenant_id = :t ORDER BY created_at LIMIT 1"),
                {"t": tenant_id},
            )
        ).one()
        return UUID(str(row[0]))


async def _ensure_membership(*, tenant_id: UUID, user_id: UUID, role: str) -> None:
    from apps.api.db.session import tenant_session

    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, :role, :now, :now) "
                "ON CONFLICT (tenant_id, user_id) DO NOTHING"
            ),
            {"id": uuid7(), "t": tenant_id, "u": user_id, "role": role, "now": now},
        )
        await session.commit()


async def _activate(tenant_id: UUID) -> None:
    """`onboarding` → `active`, through the repo's one transition primitive.

    A tenant left in `onboarding` is not a broken demo but it is a misleading one: the
    health board filters on this column and the dial gate reads it, so a seeded account
    should be in the state a real client is in after the wizard finishes.

    `tenant_session`, NOT `admin_session`, and this is the one thing about the statement
    that is not obvious. `app.admin` widens only the `USING` arm of `tenant_isolation`
    (migration b57e2f9c4a13) — the `WITH CHECK` arm stays `id = app.tenant_id`, so an
    admin session can SELECT every organization and UPDATE none of them. The real route
    (`admin/routes.py::set_tenant_status`) scopes to the tenant for the same reason.
    """
    from apps.api.db.session import tenant_session
    from apps.api.db.transition import transition_status

    async with tenant_session(tenant_id) as session:
        await transition_status(
            session,
            table="organizations",
            entity="Organization",
            row_id=tenant_id,
            to_status="active",
            from_statuses=("prospect", "onboarding", "suspended"),
        )
        await session.commit()


def _redacted(value: str) -> str:
    from apps.api.core.logging import redact_text

    return redact_text(value)


async def _seed_calls(*, tenant_id: UUID, agent_id: UUID, owner_user_id: UUID) -> int:
    """Calls, transcript turns, extractions, leads and the usage rows behind them.

    Keyed on `engine_call_id` (`seed-dev-<n>`), which carries a GLOBAL unique constraint —
    so a re-run inserts nothing rather than doubling the dashboard, and it does so in the
    database rather than in an `if` here.

    `text_redacted` is filled by `core.logging.redact_text`, the same function the pipeline
    uses. Writing the raw text into both columns would make every screen in the product
    look correct while defeating hard rule 5 on the one dataset a developer actually reads.
    """
    from apps.api.db.session import tenant_session

    now = datetime.now(UTC)
    written = 0
    async with tenant_session(tenant_id) as session:
        for n, demo in enumerate(DEMO_CALLS, start=1):
            engine_call_id = f"seed-dev-{n}"
            started = now - timedelta(minutes=demo.minutes_ago)
            ended = started + timedelta(seconds=demo.duration_s)
            our_number = "+919900000100"
            from_e164 = demo.peer_e164 if demo.direction == "inbound" else our_number
            to_e164 = our_number if demo.direction == "inbound" else demo.peer_e164

            # The lead first: `calls.lead_id` points at it, and a demo dataset whose calls
            # have no lead is one where half the CRM screens render empty.
            lead_id = uuid7()
            lead_row = (
                await session.execute(
                    text(
                        "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                        "status, data, schema_version, call_count, created_at, updated_at) "
                        "VALUES (:id, :t, :a, :phone, :name, :source, :status, "
                        "CAST(:data AS jsonb), 1, 1, :at, :at) "
                        "ON CONFLICT (tenant_id, phone_e164, agent_id) DO NOTHING "
                        "RETURNING id"
                    ),
                    {
                        "id": lead_id,
                        "t": tenant_id,
                        "a": agent_id,
                        "phone": demo.peer_e164,
                        "name": demo.caller_name,
                        "source": "inbound_call" if demo.direction == "inbound" else "campaign",
                        "status": demo.lead_status,
                        "data": json.dumps(demo.extraction),
                        "at": started,
                    },
                )
            ).first()
            if lead_row is None:  # a previous run owns it
                lead_id = UUID(
                    str(
                        (
                            await session.execute(
                                text(
                                    "SELECT id FROM leads WHERE tenant_id = :t "
                                    "AND phone_e164 = :p AND agent_id = :a"
                                ),
                                {"t": tenant_id, "p": demo.peer_e164, "a": agent_id},
                            )
                        ).one()[0]
                    )
                )

            call_id = uuid7()
            call_row = (
                await session.execute(
                    text(
                        "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                        "from_e164, to_e164, status, started_at, ended_at, duration_s, "
                        "disclosure_played, consent_recording, outcome_tag, sentiment, summary, "
                        "lead_id, created_at, updated_at) "
                        "VALUES (:id, :t, :a, :ecid, :dir, :from, :to, 'completed', :started, "
                        ":ended, :dur, true, 'granted', :outcome, :sentiment, :summary, :lead, "
                        ":started, :ended) "
                        "ON CONFLICT (engine_call_id) DO NOTHING RETURNING id"
                    ),
                    {
                        "id": call_id,
                        "t": tenant_id,
                        "a": agent_id,
                        "ecid": engine_call_id,
                        "dir": demo.direction,
                        "from": from_e164,
                        "to": to_e164,
                        "started": started,
                        "ended": ended,
                        "dur": demo.duration_s,
                        "outcome": demo.outcome_tag,
                        "sentiment": demo.sentiment,
                        "summary": demo.summary,
                        "lead": lead_id,
                    },
                )
            ).first()
            if call_row is None:
                continue  # this call is already seeded; so are its children.
            written += 1

            # `first_call_id` is ASSIGNED, never read back — deliberately. It is a
            # write-only column recorded in `scripts/check_half_wired.WRITE_ONLY_BASELINE`
            # (it closes when `LeadOut` grows the field), and a `COALESCE(first_call_id,
            # ...)` here would make a seed script the "reader" that retires that entry
            # while the product still has none. One statement per lead, so the plain
            # assignment is also correct: each demo call owns its own lead.
            await session.execute(
                text(
                    "UPDATE leads SET first_call_id = :c, last_call_id = :c, "
                    "assigned_to = COALESCE(assigned_to, :owner) WHERE id = :lead"
                ),
                {"c": call_id, "owner": owner_user_id, "lead": lead_id},
            )

            for idx, (speaker, line) in enumerate(demo.turns):
                await session.execute(
                    text(
                        "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, "
                        "text, text_redacted, lang, created_at, updated_at) "
                        "VALUES (:id, :t, :c, :idx, :sp, :raw, :red, :lang, :at, :at)"
                    ),
                    {
                        "id": uuid7(),
                        "t": tenant_id,
                        "c": call_id,
                        "idx": idx,
                        "sp": speaker,
                        "raw": line,
                        "red": _redacted(line),
                        "lang": TENANT_LANGUAGE,
                        "at": started,
                    },
                )

            await session.execute(
                text(
                    "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                    "model, prompt_version, valid, created_at, updated_at) "
                    "VALUES (:id, :t, :c, 1, CAST(:data AS jsonb), :model, 1, true, :at, :at)"
                ),
                {
                    "id": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "data": json.dumps(demo.extraction),
                    # Named for what actually extracts in this product (D-36 /
                    # `GEMINI_EXTRACTION_DEFAULT is False`), so a developer reading the
                    # column does not learn a model name we do not use.
                    "model": "sarvam-m-105b",
                    "at": ended,
                },
            )

            # The money rows, in the same shape `workers/pipeline.py` writes them:
            # `unit_cost_paid` is a price PER UNIT OF qty, never a leg total, and every
            # amount is a Decimal (hard rule 7).
            duration = Decimal(demo.duration_s)
            minutes = duration / Decimal(60)
            usage: tuple[tuple[str, Decimal, Decimal], ...] = (
                ("telephony_s", duration, Decimal("0.0100")),
                ("platform_min", minutes, Decimal("0.4000")),
                ("stt_s", duration, Decimal("0.0040")),
                ("tts_chars", Decimal(1), Decimal("0.6000")),
            )
            for unit_type, qty, unit_cost in usage:
                await session.execute(
                    text(
                        "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                        "unit_cost_paid, occurred_at, meta, created_at) "
                        "VALUES (:id, :t, :c, :unit, :qty, :cost, :at, "
                        "CAST(:meta AS jsonb), now())"
                    ),
                    {
                        "id": uuid7(),
                        "t": tenant_id,
                        "c": call_id,
                        "unit": unit_type,
                        "qty": qty,
                        "cost": unit_cost,
                        "at": ended,
                        "meta": json.dumps({"engine": "seed_dev", "seeded": True}),
                    },
                )
        await session.commit()
    return written


#: The receptionist script the demo agent is published with. Short on purpose: the
#: compliance sentences are NOT in it — `compose_engine_prompt` appends the AI disclosure
#: and the recording notice server-side on every publish (hard rule 5), and writing them
#: here would be a second copy that a client edit could silently drop.
DEMO_PROMPT = """You are the receptionist for Sunrise Dental Care in Hyderabad.

Answer questions about treatments, timings and pricing. The clinic is open 9am to 8pm,
seven days a week. A consultation is 500 rupees; clear aligner treatment starts at 40,000
rupees; a root canal is 6,000 to 12,000 rupees depending on the tooth.

Book appointments by taking the caller's name, phone number and preferred time. If the
caller has a complaint about work already done, transfer them to the front desk.

Speak in the caller's language — English or Telugu. Keep answers short."""


async def _ensure_prompt(tenant_id: UUID, agent_id: UUID) -> None:
    """The script, without which `publish_agent` correctly refuses `agent_has_no_script`.

    Written through `write_prompt_version` rather than INSERTed, so the demo agent's
    prompt history looks like a real one — version 1, applied because the agent is still
    a draft — and so the publish below is exercising the same rows the console produces.
    Idempotent: a re-run finds version 1 already there and adds no second version, which
    keeps the history screen honest instead of growing a version per seed run.
    """
    from apps.api.agents.prompts import list_prompt_versions, write_prompt_version
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as session:
        if await list_prompt_versions(session, agent_id):
            return
        await write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=DEMO_PROMPT,
            notes="Seeded by scripts/seed_dev.py",
            created_by=None,
        )
        await session.commit()


async def _publish(tenant_id: UUID, agent_id: UUID) -> str:
    """Publish through the real service, and report the truth if it will not.

    On `ENGINE=fake` this is the whole publish path — compliance sentences composed and
    verified against the engine included — so a seeded stack exercises it rather than
    pretending. On a stack pointed at an engine it cannot reach, the failure is the
    interesting fact and is printed, not swallowed.
    """
    from apps.api.agents.service import publish_agent
    from apps.api.db.session import tenant_session

    try:
        async with tenant_session(tenant_id) as session:
            # The return value is the ENGINE REF, not the status — reading `agents.status`
            # back is what actually answers "is this agent live", and it is the column the
            # console renders.
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
            await session.commit()
    except Exception as exc:
        return f"draft (publish failed: {type(exc).__name__}: {exc})"
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(text("SELECT status FROM agents WHERE id = :a"), {"a": agent_id})
        ).one()
        return str(row[0])


async def _run() -> str:
    from apps.api.admin import service as admin_service

    admin_id = await _upsert_admin(email=ADMIN_EMAIL, name=ADMIN_NAME, role="superadmin")
    await _set_password(realm="admin", subject_id=admin_id, password=ADMIN_PASSWORD)

    owner_id = await _upsert_user(email=OWNER_EMAIL, name=OWNER_NAME)
    staff_id = await _upsert_user(email=STAFF_EMAIL, name=STAFF_NAME)
    await _set_password(realm="client", subject_id=owner_id, password=OWNER_PASSWORD)
    await _set_password(realm="client", subject_id=staff_id, password=STAFF_PASSWORD)

    tenant_id = await _existing_tenant(TENANT_SLUG)
    if tenant_id is None:
        created = await admin_service.create_organization(
            name=TENANT_NAME,
            slug=TENANT_SLUG,
            vertical_template=TENANT_VERTICAL,
            billing_email=OWNER_EMAIL,
            language=TENANT_LANGUAGE,
            created_by=admin_id,
            plan_tier=TENANT_PLAN_TIER,
            owner_user_id=owner_id,
        )
        tenant_id = UUID(str(created["id"]))
        agent_id = UUID(str(created["agent_id"]))
    else:
        agent_id = await _tenant_agent(tenant_id)

    # Both memberships every run: the owner's is written by the birth transaction only on
    # the run that creates the tenant, and the staff one never is.
    await _ensure_membership(tenant_id=tenant_id, user_id=owner_id, role="owner")
    await _ensure_membership(tenant_id=tenant_id, user_id=staff_id, role="staff")
    await _activate(tenant_id)

    await _ensure_prompt(tenant_id, agent_id)
    agent_status = await _publish(tenant_id, agent_id)
    calls = await _seed_calls(tenant_id=tenant_id, agent_id=agent_id, owner_user_id=owner_id)

    return "\n".join(
        [
            "seeded a local development stack",
            "",
            f"  tenant   {TENANT_NAME} ({TENANT_SLUG})  id={tenant_id}  tier={TENANT_PLAN_TIER}",
            f"  agent    {agent_id}  status={agent_status}",
            f"  calls    +{calls} this run ({len(DEMO_CALLS)} defined, re-runs add none)",
            "",
            "ADMIN CONSOLE  (admin.calevate.tech / http://localhost:3000 admin realm)",
            f"  email     {ADMIN_EMAIL}",
            f"  password  {ADMIN_PASSWORD}",
            "  NOTE: the admin realm requires a second factor (TRD §2). The code is",
            "  emailed; with no mail provider configured locally the ConsoleTransport",
            "  prints it in the API server's log.",
            "",
            "CLIENT DASHBOARD  (app.calevate.tech / http://localhost:3000 client realm)",
            f"  owner     {OWNER_EMAIL}  /  {OWNER_PASSWORD}",
            f"  staff     {STAFF_EMAIL}  /  {STAFF_PASSWORD}",
            "  The staff account exists to show what the role does NOT get: no billing,",
            "  no org settings, no unredacted transcripts.",
            "",
            "Re-run this script at any time to reset these three passwords.",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    if argv:
        print(f"{__file__} takes no arguments (got {argv!r})", file=sys.stderr)
        return 2
    _refuse_unless_local()
    print(asyncio.run(_run()))
    return 0


if __name__ == "__main__":
    # Same reason as `scripts/seed.py`: psycopg's async mode cannot use Windows'
    # default ProactorEventLoop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(main(sys.argv[1:]))
