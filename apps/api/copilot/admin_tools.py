"""The ADMIN copilot's read tools: platform state, the tenant in view, and the runbooks.

The client copilot's tools answer "how is MY business doing" out of one tenant's rows under
that tenant's RLS. An operator's questions are a different shape — *which client is about
to break*, *are we dialling at all*, *how much of this month's AI budget is gone*, *what do
I do when `engine_error_spike` fires* — and none of them has a tenant. So this is a second
registry rather than a widening of the first, for the reason `tools.py` gives for being a
registry at all: a tool is a schema, a permission and an executor that must not drift, and
the drift here would be a platform query running under a tenant GUC or the reverse.

## THREE THINGS THIS REGISTRY DOES DIFFERENTLY, AND NOTHING ELSE

1. **`scope="platform"` opens an `admin_session()`, not a `tenant_session`.** That session
   is the ONLY one that can enumerate tenants (migration `b57e2f9c4a13` widens `USING` on
   `organizations` and on nothing else), and every function called below either takes it as
   its documented directory session (`admin_service.tenant_overview`,
   `admin.health.client_health` — both of which then ENTER each tenant with its own GUC) or
   reads a `platform_*` table that carries no policy at all. Hard rule 1 is not bent: no
   tenant table is read cross-tenant at any instant.
2. **The permission is `admin:tenants`, which is the one the equivalent SCREEN declares.**
   `GET /v1/admin/tenants` and the health board both declare it, and no client role holds
   it — so a tool that judged itself by anything looser would be a way around the console.
   `tools.py` makes this argument for `calls:read` and `agents:read`; this is the same rule
   applied to the console's own reads.
3. **`search_runbooks` reads the process's own runbook index** (`copilot/runbooks.py`) —
   our text, our ranker, no vendor and no embeddings, so D-28 stays the founder's open
   decision. It is declared `scope="platform"` and simply does not use the session it is
   handed; `ReadTool.scope` records why there is no third scope for it.

## WHAT AN OPERATOR CAN STILL REACH THROUGH THE *CLIENT* TOOLS

The admin tool array also carries `tools.READ_TOOLS` (see `service.tool_array`), scoped by
the route to the ONE tenant whose page is open. That is where "the tenant currently being
viewed — their calls, leads, campaigns, agents" is answered, under that tenant's own RLS,
by the same code the client copilot runs. Nothing is duplicated here for it; when no tenant
is in view those tools refuse with a sentence saying so, which is the honest answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service as admin_service
from apps.api.admin.health import client_health
from apps.api.billing.ai_quota import PLATFORM_AI_BRAKE_INR, read_platform_ai_spend
from apps.api.copilot import runbooks as runbook_index
from apps.api.copilot.charts import FLEET_CHART
from apps.api.copilot.tools import MAX_ROWS, ReadTool, ToolContext, _cap, _clean, _listing
from apps.api.ops.service import read_halt_state, read_tm_registration

#: What a platform tool says when the question has an answer and the answer is "nothing".
#: A sentence rather than an empty string, for `tools._nothing()`'s reason: an empty tool
#: result reads to a model as a failure. It is written out here rather than composed by that
#: helper because the helper's every sentence is about an ACCOUNT — "this account has no X
#: yet" — and the population here is every account on the platform.
_NO_ACCOUNTS: Final = "No accounts on the platform yet."


def _when(value: datetime | None) -> str:
    """An instant as whole days ago, or `never`.

    DAYS AND NOT A TIMESTAMP, deliberately: an operator asking "when did this client last
    make a call" is asking whether it was recently, and a model handed an ISO string in UTC
    will render it in UTC to somebody working in IST. Days ago is unambiguous in every
    timezone and costs a third of the tokens.
    """
    if value is None:
        return "never"
    days = (datetime.now(UTC) - value).days
    if days <= 0:
        return "today"
    return "1 day ago" if days == 1 else f"{days} days ago"


async def _platform_tenants(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The client directory, newest first — `GET /v1/admin/tenants`' own data.

    `tenant_overview` is called rather than re-queried, so the assistant and the console's
    roster cannot answer "which clients exist" differently. It opens one tenant session per
    account it returns, so the cap is passed INTO it as the page: slicing its answer
    afterwards still paid for every account on the platform. The total is the directory's
    own count, one statement.
    """
    del context
    limit = _cap(args.get("limit"), default=MAX_ROWS)
    rows = await admin_service.tenant_overview(session, limit=limit)
    total = await admin_service.tenant_directory_total(session)
    lines = [
        _clean(
            f"{row['name']} ({row['slug']}) — {row['status']}, {row['vertical_template']}; "
            # ZEROS SAID AS WORDS, because an operator's question about this list is almost
            # always "which of these has not started" and a row of digits makes them count
            # noughts. "no live agent" is the same fact as "0 live agent(s)" and is the one
            # a model repeats as a finding rather than as a number.
            + (
                "no live agent"
                if row["live_agents"] == 0
                else f"{row['live_agents']} live agent(s)"
            )
            + ", "
            + ("no calls in 7d" if row["calls_7d"] == 0 else f"{row['calls_7d']} calls in 7d")
            + ", "
            + ("no leads yet" if row["leads"] == 0 else f"{row['leads']} lead(s)")
            + f"; last call {_when(row['last_call_at'])}"
            + (", SPEND-CAPPED" if row["capped"] else "")
            + (f"; held by: {', '.join(row['holds'])}" if row["holds"] else "")
        )
        for row in rows
    ]
    return _listing(lines, total=total, shown_of="accounts", nothing=_NO_ACCOUNTS)


async def _platform_health(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The triage board: accounts with at least one live signal, worst first.

    `client_health` is the console's own board and already ranks and explains itself
    (`_triage_order`: most things broken, then most things about to break, then name). The
    causes come back as the GATES' OWN RULE NAMES and never their prose — that is
    `HealthSignal`'s hard-rule-6 line and it is why this renders `signal.causes` rather
    than looking for a reason string.
    """
    del context, args
    board = await client_health(session)
    lines = [
        _clean(
            f"{row.name} ({row.slug}, {row.plan_tier}"
            + (", free trial: test calls only" if row.on_trial else "")
            + f") — {row.severity}: "
            + "; ".join(
                signal.rule
                + (" (waiting on the client)" if signal.waiting_on == "client" else "")
                + (f" x{signal.count}" if signal.count is not None else "")
                + (f" [{', '.join(signal.causes)}]" if signal.causes else "")
                for signal in row.signals
            )
            + f"; {row.volume.calls_7d} calls in 7d (prev {row.volume.calls_prev_7d}, "
            f"basis {row.volume.basis}), last call {_when(row.volume.last_call_at)}"
        )
        for row in board
    ]
    return _listing(
        lines,
        total=len(board),
        shown_of="flagged accounts",
        nothing="No account has a live health signal — nothing is flagged right now.",
    )


async def _platform_ops_state(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """Is the platform dialling, is our telemarketer registration live, and how much of
    this month's AI budget is left.

    THREE FACTS AN OPERATOR CHECKS TOGETHER, in one tool, because they are the three that
    decide whether an incident is ours: the big red switch, our telemarketer registration
    (on record only since D-692, which no dial gate asks for), and the ceiling that pauses
    every AI surface on the platform. Each is read through the function that OWNS it —
    `read_halt_state`, `read_tm_registration`, `read_platform_ai_spend` — never re-queried
    here, so the assistant and the ops console cannot disagree about a halt.
    """
    del context, args
    halt = await read_halt_state(session)
    registration = await read_tm_registration(session)
    spend = await read_platform_ai_spend(session)
    return _clean(
        "Outbound dialling: "
        + (f"HALTED — {halt.reason or 'no reason recorded'}" if halt.outbound_halted else "running")
        + f"\nTelemarketer (TM) registration: {registration.status}"
        # D-692: no gate asks for it; outbound needs each client's verified KYC and
        # no-cold-calls pledge, so a missing registration is not an incident.
        + " (on record only; not required to dial out)"
        + (f", TM id {registration.tm_id}" if registration.tm_id else "")
        + f"\nPlatform AI spend {spend.month}: INR {spend.spend_inr} of {PLATFORM_AI_BRAKE_INR} "
        f"({spend.requests} metered request(s))"
        + (
            " — BRAKE TRIPPED, AI help is paused for every tenant and for this console"
            if spend.tripped
            else ""
        )
    )


async def _search_runbooks(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The runbook sections that answer an operator's question, verbatim.

    NO SESSION IS USED and the parameter is accepted only because the registry has one
    signature — `tools._Executor`'s shape, which `write_tools.Executor` also matches, and
    two calling conventions in one package is the drift CLAUDE.md calls a defect even when
    both work. `ReadTool.scope` records the one round trip that costs.

    VERBATIM, and truncated VISIBLY. A runbook is a procedure somebody will follow during
    an incident, so a paraphrase is the one thing this must not return; when a section does
    not fit, the marker is what lets the model say "open the file" instead of answering
    from half of it.
    """
    del session, context
    question = str(args.get("question") or "").strip()
    if not question:
        return "Ask again with the question you want the runbooks searched for."
    if not runbook_index.index():
        # NOT "there is no runbook for that". The corpus could not be read, and saying so
        # is the difference between an operator opening the file themselves and an
        # operator believing nothing is written down (hard rule 11's shape, in a sentence
        # a model will repeat).
        return (
            "The runbooks could not be read in this deployment, so I cannot search them. "
            "Tell the operator to open runbooks/ directly — do not answer from memory."
        )
    found = runbook_index.search(question)
    if not found:
        return (
            "No runbook section matched that. Say so rather than guessing a procedure — "
            "an invented incident step is worse than none."
        )
    passages = []
    for section in found:
        body = section.body
        if len(body) > runbook_index.MAX_SECTION_CHARS:
            body = body[: runbook_index.MAX_SECTION_CHARS].rstrip() + "\n… (section truncated)"
        passages.append(f"[{section.title}]\n{body}")
    return _clean("\n\n".join(passages))


_FIRST_ADMIN_READ_TOOLS: Final[tuple[ReadTool, ...]] = (
    ReadTool(
        name="platform_tenants",
        description=(
            "Every client account on the platform, newest first: name, slug, status, "
            "vertical, how many live agents, calls in the last 7 days, total leads, when "
            "they last made a call, whether they are spend-capped, and which human-action "
            "gates are holding them. Use it for which clients exist; for one client's "
            "verification, trial or dialling block use `admin_client_standing`."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": (
                        f"How many to return, at most {MAX_ROWS}. Null means {MAX_ROWS}."
                    ),
                }
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
        permission="admin:tenants",
        scope="platform",
        run=_platform_tenants,
    ),
    ReadTool(
        name="platform_health",
        description=(
            "The client triage board: every account with at least one live health signal, "
            "worst first, with the rule names that fired (spend cap, KYC missing, PE "
            "registration missing, stalled pipeline, knowledge waiting, failed webhook "
            "deliveries, call volume collapse) and this week's call volume against last "
            "week's. Use it to answer which clients need attention."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        permission="admin:tenants",
        scope="platform",
        run=_platform_health,
    ),
    ReadTool(
        name="platform_ops_state",
        description=(
            "The platform's own state right now: whether outbound dialling is halted (the "
            "big red switch) and why, Calevate's telemarketer registration (on record only; "
            "outbound does not need it), "
            "and how much of this month's platform-wide AI budget has been spent against "
            "the ceiling that pauses AI for everyone. Call this before saying anything "
            "about whether the platform is working."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        permission="admin:tenants",
        scope="platform",
        run=_platform_ops_state,
    ),
    ReadTool(
        name="search_runbooks",
        description=(
            "Search Calevate's own operator runbooks — the written incident procedures in "
            "runbooks/, including the alarm index that maps an alarm code to what to do "
            "about it. Use it for any 'what do I do when X' or 'how do I recover Y' "
            "question, and quote the steps it returns rather than writing your own."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "What the operator needs to do, or the alarm code they are looking "
                        "at, e.g. 'engine_error_spike' or 'restore the database'."
                    ),
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        # THE SAME DOOR AS THE CONSOLE ITSELF. The runbooks are internal operating
        # procedure, not public documentation: they name hosts, units and recovery
        # commands. `admin:tenants` is held by both admin roles and by no client role.
        permission="admin:tenants",
        scope="platform",
        run=_search_runbooks,
    ),
)

# --- D-698: the queues and boards an operator works from ---------------------------------


async def _admin_kyc_queue(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The Identity reviews screen's own route function, `kyc_review_queue`, called with
    this directory session rather than copied: it reads each client under that client's own
    RLS session, which is the property worth not re-implementing."""
    from apps.api.compliance.kyc_admin_routes import kyc_review_queue
    from apps.api.core.context import Principal

    principal = Principal(realm="admin", user_id=None, tenant_id=None, role=context.role)
    items = await kyc_review_queue(session, principal, _cap(args.get("limit"), default=MAX_ROWS))
    lines = [
        _clean(
            f"{item.name} ({item.slug}) — {item.status}, {item.kyc_path or 'path unknown'}"
            + (f", owner ID {item.owner_id_type}" if item.owner_id_type else "")
            + (", DigiLocker required" if item.digilocker_required else "")
            + f", submitted {_when(item.submitted_at)}"
        )
        for item in items
    ]
    return _listing(
        lines,
        shown_of="verifications waiting for review",
        nothing="No client's verification is waiting for review.",
    ) + (
        "\nTo decide one, open that client's page; `admin_kyc_review` acts on the client "
        "whose page is open."
        if items
        else ""
    )


async def _admin_held_accounts(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`admin.holds.held_tenants` — the Held accounts screen's read."""
    del context, args
    from apps.api.admin.holds import held_tenants

    rows = await held_tenants(session)
    lines = [
        _clean(f"{row.name} ({row.slug}, {row.plan_tier}) — held by: {', '.join(row.rules)}")
        for row in rows[:MAX_ROWS]
    ]
    return _listing(lines, total=len(rows), shown_of="held accounts", nothing="No account is held.")


async def _admin_alerts(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`ops.alerts_service.alert_report` — the Alerts screen's read. Alerts close on their
    own after an hour of quiet; there is nothing to acknowledge, so triage is reading this
    and following the runbook (`search_runbooks` with the code)."""
    del context, args
    from apps.api.ops.alerts_service import alert_report

    report = await alert_report(session, days=7, limit=MAX_ROWS)
    open_counts = ", ".join(f"{k} {v}" for k, v in report.open_by_severity.items()) or "none"
    lines = [
        _clean(
            f"{episode.code} · {episode.severity} · {episode.stage} · {episode.service} · "
            f"{episode.occurrences}x, last {_when(episode.last_seen_at)}"
        )
        for episode in report.episodes
    ]
    return f"Open alerts by severity: {open_counts}.\n" + _listing(
        lines, shown_of="alert episodes this week", nothing="No alert in the last 7 days."
    )


async def _admin_voices(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`hosted_voices.list_hosted_voices` — the Voices screen's read of the voices an
    operator added, with the agents `voice_curation` counts beside them."""
    del context, args
    from apps.api.agents.hosted_voices import list_hosted_voices
    from apps.api.agents.own_model import own_model_readiness
    from apps.api.agents.voice_curation import NOT_IN_USE, count_agents_by_engine_voice
    from apps.api.core.settings import get_settings

    rows = await list_hosted_voices(session, scope="added")
    usage = await count_agents_by_engine_voice()

    def _used(voice_id: str) -> str:
        held = usage.get(voice_id, NOT_IN_USE)
        if not held.total:
            return "no agent"
        return (
            f"{held.total} agent(s): {held.live} live, {held.ready} ready, "
            f"{held.not_published} not published"
        )

    lines = [
        _clean(f"{row.label} · {row.state} · {_used(row.voice_id)}") + f" [voice_id {row.voice_id}]"
        for row in rows[:MAX_ROWS]
    ]
    # The Voices screen's "Our own model" card (D-764), so a question about which model the
    # agents answer with is answered from the same readiness the card shows.
    own = await own_model_readiness(session, engine=get_settings().engine)
    own_line = _clean(
        f"Our own model (Gemini on our Google key): {'on' if own.switched_on else 'off'}, "
        f"{'ready' if own.ready else 'not ready'}, default {own.default_model}, "
        f"{len(own.workspaces)} client workspace(s) on our key."
        + (" Missing: " + " ".join(own.missing()) if not own.ready else "")
    )
    return (
        _listing(lines, total=len(rows), shown_of="voices", nothing="No voice has been added yet.")
        + "\n"
        + own_line
    )


#: The most clients a name can match before the tool asks which one was meant.
_STANDING_CANDIDATES: Final = 5


async def _admin_client_standing(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """ONE client's standing, named by slug or by name, from any admin screen.

    The account tools (`verification_status` and the live block's `<account>` line) answer
    for the client whose page is open; an operator on the clients list or the dashboard who
    asks "is Raghava Organics verified?" has no page open. This resolves the name in the
    directory session, then reads the client under its OWN tenant session with the same
    readers the live block uses and the readiness gates' own rows — nothing re-derived.
    """
    del context
    from sqlalchemy import text

    from apps.api.copilot.context import read_account_standing
    from apps.api.core.loadshed import get_platform_status
    from apps.api.db.session import tenant_session
    from apps.api.legal.readiness import readiness_rows

    asked = str(args.get("client") or "").strip()
    if not asked:
        return "Name the client: its slug or part of its name."
    matches = (
        await session.execute(
            text(
                "SELECT id, name, slug FROM organizations WHERE deleted_at IS NULL "
                "AND (lower(slug) = lower(:q) OR name ILIKE :like) "
                "ORDER BY (lower(slug) = lower(:q)) DESC, name LIMIT :n"
            ),
            {
                "q": asked,
                # The directory search's own pattern, so `%` and `_` match themselves.
                "like": admin_service._directory_params(
                    tenant_id=None, q=asked, status=None, plan_tier=None
                )["like"],
                "n": _STANDING_CANDIDATES,
            },
        )
    ).all()
    if not matches:
        return _clean(f"No client's name or slug matches “{asked}”.")
    exact = [row for row in matches if str(row[2]).lower() == asked.lower()]
    if len(matches) > 1 and not exact:
        names = "; ".join(f"{row[1]} ({row[2]})" for row in matches)
        return _clean(f"More than one client matches: {names}. Ask again with the slug.")
    tenant_id, name, slug = (exact or matches)[0]
    platform = await get_platform_status()
    async with tenant_session(tenant_id) as scoped:
        account = await read_account_standing(scoped, tenant_id=tenant_id)
        rows = await readiness_rows(scoped, tenant_id=tenant_id, platform=platform)
    kyc = account.kyc.replace("_", " ")
    if account.kyc_path:
        kyc += f" (path: {'DigiLocker' if account.kyc_path == 'digilocker' else 'document review'})"
    lines = [
        f"{name} ({slug})",
        f"Lifecycle: {account.lifecycle}.",
        f"Business verification (KYC): {kyc}.",
        f"No-cold-calls pledge: {account.pledge.replace('_', ' ')}.",
        f"Trial: {account.trial}; first payment made: {'yes' if account.paid else 'no'}.",
        f"Voice workspace: {account.workspace.replace('_', ' ')}.",
        f"Owner has joined: {'yes' if account.owner_joined else 'no'}.",
        "Business profile: "
        + (
            "ready for an agent to go live."
            if not account.profile_missing
            else "missing " + ", ".join(account.profile_missing) + "."
        ),
        "Outbound calling: "
        + (
            "nothing at account level is blocking it."
            if not rows
            else "blocked by " + "; ".join(f"{row.rule} ({row.actor}'s move)" for row in rows) + "."
        ),
    ]
    return _clean("\n".join(lines))


# --- D-776: the auto-healer, as Pip's own work ------------------------------------------
#
# Every reader below is the healer's own (`healer/incidents`, `healer/ledger`,
# `healer/wording`, `healer/money`), so Pip and `/admin/ops/healer` cannot describe an
# incident differently. Incident and call ids are appended OUTSIDE `_clean`: the redactor
# can read a uuid's digit runs as a phone number.

#: How many steps of each incident the list shows; the full trail is `healer_incident`.
_LISTED_STEPS: Final = 3
#: How many calls the money evidence lists one by one.
_LISTED_CALLS: Final = 10


def _age(since: datetime) -> str:
    hours = int((datetime.now(UTC) - since).total_seconds() // 3600)
    if hours < 1:
        return "under an hour"
    if hours < 48:
        return f"{hours} hour(s)"
    return f"{hours // 24} day(s)"


def _healer_switches() -> str:
    from apps.api.core.settings import get_settings
    from apps.api.healer.playbooks import paused_keys

    settings = get_settings()
    paused = sorted(paused_keys())
    return "Auto-healer: " + (
        ("on" if settings.healer_enabled else "SWITCHED OFF (only the agent settings check runs)")
        + (f"; paused repairs: {', '.join(paused)}" if paused else "; no repair is paused")
        + "."
    )


def _step_words(action: Any) -> str:
    from apps.api.healer.money import ist

    who = "" if action.actor_type == "healer" else f" by {action.actor_type}"
    return f"{action.step} {action.outcome}{who} {ist(action.at)}" + (
        f" ({action.detail})" if action.detail else ""
    )


def _incident_line(incident: Any, steps: list[Any], finding: str | None) -> str:
    from apps.api.healer import incidents, wording
    from apps.api.healer.money import ist
    from apps.api.healer.playbooks import PLAYBOOK_BY_KEY

    playbook = PLAYBOOK_BY_KEY.get(incident.playbook)
    automatic = playbook.automatic if playbook is not None else False
    kind = wording.incident_kind(incident.trigger_code)
    progress = wording.progress(
        playbook=incident.playbook,
        automatic=automatic,
        state=incident.state,
        attempts=incident.attempts,
        last_outcome=incident.last_outcome,
        escalated=incident.escalated_at is not None,
    )
    tries = (
        f"{incident.attempts} of {playbook.max_attempts}" if playbook else str(incident.attempts)
    )
    body = (
        f"{playbook.title if playbook else incident.playbook}: {kind.title}. {progress}. "
        f"Found {ist(incident.opened_at)}, "
        + (
            f"closed {ist(incident.resolved_at)}. "
            if incident.resolved_at
            else f"open for {_age(incident.opened_at)}. "
        )
        + f"Automatic tries: {tries}. What to do: {kind.next_step}"
        + (f" Last steps: {'; '.join(_step_words(s) for s in steps)}." if steps else "")
        + (f" Pip's finding: {finding}" if finding else "")
    )
    return _clean(body) + f" [ref {incidents.short_ref(incident.id)}]"


async def _healer_incidents(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The healer screen's problem list: `incidents.list_incidents` with each incident's
    newest steps and, for money, the evidence the healer stored when it handed it over."""
    del context
    from apps.api.healer import incidents, ledger
    from apps.api.healer.playbooks import MONEY_REVIEW

    rows = await incidents.list_incidents(
        session, days=7, limit=MAX_ROWS, open_only=args.get("include_closed") is not True
    )
    steps = await ledger.recent_steps(session, [i.id for i in rows], per_incident=_LISTED_STEPS)
    findings = await ledger.latest_findings(
        session, [i.id for i in rows if i.playbook == MONEY_REVIEW]
    )
    lines = [_incident_line(i, steps.get(i.id, []), findings.get(i.id)) for i in rows]
    return (
        _healer_switches()
        + "\n"
        + _listing(
            lines,
            shown_of="healer problems",
            nothing="The healer has no open problem."
            if args.get("include_closed") is not True
            else "The healer found no problem in the last 7 days.",
        )
    )


async def _healer_incident(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """One incident: its plain words, what its playbook may do, every ledger step, the
    client it is about, and what Pip may propose for it."""
    del context
    from sqlalchemy import text

    from apps.api.healer import decisions, incidents, ledger, wording
    from apps.api.healer.playbooks import MONEY_REVIEW, PLAYBOOK_BY_KEY, may_run

    ref = str(args.get("incident") or "")
    incident = await incidents.find(session, ref)
    if incident is None:
        return _clean(
            f"No healer problem has the reference “{ref[:40]}”. List them with healer_incidents."
        )
    kind = wording.incident_kind(incident.trigger_code)
    playbook = PLAYBOOK_BY_KEY.get(incident.playbook)
    trail = await ledger.list_actions(session, incident_id=incident.id, limit=MAX_ROWS)
    finding = (await ledger.latest_findings(session, [incident.id])).get(incident.id)
    client = None
    if incident.tenant_id is not None:
        client = (
            await session.execute(
                text("SELECT name, slug FROM organizations WHERE id = :t"),
                {"t": incident.tenant_id},
            )
        ).first()
    lines = [
        _incident_line(incident, [], finding),
        _clean(f"What it means: {kind.meaning}"),
    ]
    if client is not None:
        lines.append(_clean(f"Client: {client[0]} ({client[1]})."))
    if playbook is not None:
        lines.append(
            _clean(
                f"The playbook does: {playbook.action} It checks: {playbook.verify} "
                f"Undo: {playbook.undo} "
                + (
                    "It never acts itself."
                    if not playbook.automatic
                    else f"It may try {playbook.max_attempts} time(s), "
                    f"{playbook.cooldown_s // 60} minutes apart; "
                    + ("it is running." if may_run(playbook.key) else "it is SWITCHED OFF.")
                )
            )
        )
    lines.append(
        "Every step, newest first: "
        + (_clean("; ".join(_step_words(s) for s in trail)) if trail else "none yet")
        + "."
    )
    if incident.resolved_at is None:
        options = ["healer_resolve (mark it handled, with the operator's reason)"]
        refusal = decisions.retry_refusal(incident)
        options.insert(
            0,
            "healer_retry (run its next step now)"
            if refusal is None
            else f"not healer_retry: {refusal}",
        )
        if incident.playbook == MONEY_REVIEW:
            options.append(
                "healer_money_review for the call-by-call evidence, then healer_attest_rate "
                "with the posted rate THE OPERATOR reads in the voice platform's console"
            )
        lines.append(_clean("What you can propose: " + "; ".join(options) + "."))
    return "\n".join(lines)


async def _healer_money_review(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The evidence behind every open money incident at once (`healer/money.gather`), so
    differences that share one rate are seen as one cause."""
    del context, args
    from apps.api.healer import incidents, money
    from apps.api.healer.playbooks import MONEY_REVIEW

    open_money = [
        i
        for i in await incidents.list_incidents(session, days=1, limit=MAX_ROWS, open_only=True)
        if i.playbook == MONEY_REVIEW
    ]
    oldest = min((i.opened_at for i in open_money), default=datetime.now(UTC))
    evidence = await money.gather(since=oldest - money.LOOKBACK)
    head = (
        "Open money problems: "
        + "; ".join(
            _clean(f"{i.trigger_code} found {money.ist(i.opened_at)}")
            + f" [ref {incidents.short_ref(i.id)}]"
            for i in open_money
        )
        if open_money
        else "No money problem is open; this is the last day's evidence."
    )
    rates = (
        "; ".join(
            f"{key} ₹{price.inr_per_min}/min from {money.ist(price.effective_from)}, attested "
            f"{money.ist(price.attested_at)} ({price.source_note})"
            for key, price in sorted(evidence.rates.items())
        )
        or "none attested"
    )
    shown = sorted(evidence.differing, key=lambda c: c.at, reverse=True)[:_LISTED_CALLS]
    calls = [
        _clean(
            f"{c.client} · {money.ist(c.at)} · {c.rate_key or 'no rate key'} · "
            f"{c.billed_minutes if c.billed_minutes is not None else '?'} billed min at "
            f"₹{c.stamped_rate if c.stamped_rate is not None else '?'}/min · metered "
            f"₹{c.metered_inr} · charged ₹{c.charged_inr} (₹{c.expected_inr} with the fee)"
            + (f" · implies ₹{c.implied_rate}/min" if c.implied_rate is not None else "")
        )
        + f" [call {c.call_id}]"
        for c in shown
    ]
    cause = evidence.one_cause()
    guidance = (
        f"One cause: every differing call is on the {cause.rate_key} rate and implies the "
        f"same posted rate, first seen {money.ist(cause.first_at)}. "
        if cause is not None
        else ""
    ) + (
        "An implied rate is worked back from the voice platform's charges: it is evidence, "
        "NOT an attested figure, and you must never propose it as one. Ask the operator to "
        "read the posted rate in the voice platform's console and type it, then propose "
        "healer_attest_rate with THEIR figure, from when the rate changed, naming every "
        "open money problem it explains."
        if evidence.differing
        else ""
    )
    return "\n".join(
        part
        for part in (
            head,
            _clean(evidence.explain()),
            _clean(f"Rates in force now: {rates}."),
            ("Calls that differ, newest first:\n" + "\n".join(calls)) if calls else "",
            _clean(guidance) if guidance else "",
            f"Read from Calevate's own records at {money.ist(evidence.read_at)}.",
        )
        if part
    )


_NO_ARGS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

ADMIN_READ_TOOLS: Final[tuple[ReadTool, ...]] = (
    *_FIRST_ADMIN_READ_TOOLS,
    ReadTool(
        name="admin_kyc_queue",
        description=(
            "Clients whose business verification is waiting for a reviewer, oldest first: "
            "status, which path (document or DigiLocker), and when they submitted."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": f"How many to return, at most {MAX_ROWS}.",
                }
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
        permission="admin:tenants",
        scope="platform",
        run=_admin_kyc_queue,
    ),
    ReadTool(
        name="admin_held_accounts",
        description="Accounts whose outbound calling is held on identity verification (KYC).",
        parameters=_NO_ARGS,
        # The console screen declares `org:read`, which every client role also holds; the
        # admin realm's platform tools are gated on a permission no client role holds.
        permission="admin:tenants",
        scope="platform",
        run=_admin_held_accounts,
    ),
    ReadTool(
        name="admin_alerts",
        description=(
            "The platform's alert episodes over the last week and how many are open by "
            "severity. Use `search_runbooks` with an alert code for what to do."
        ),
        parameters=_NO_ARGS,
        permission="ops:manage",
        scope="platform",
        run=_admin_alerts,
    ),
    ReadTool(
        name="admin_voices",
        description=(
            "Every voice an operator added, whether clients may choose it, and how many "
            "live agents use it."
        ),
        parameters=_NO_ARGS,
        permission="ops:manage",
        scope="platform",
        run=_admin_voices,
    ),
    ReadTool(
        name="admin_client_standing",
        description=(
            "One client's standing, from any admin screen: lifecycle, business verification "
            "(KYC) status and path, the no-cold-calls pledge, trial and first payment, voice "
            "workspace, whether the owner has joined, what the business profile lacks, and "
            "what blocks outbound calling. Use it for 'is X verified', 'is X still on "
            "trial', 'why can X not dial'; the whole roster is `platform_tenants`."
        ),
        parameters={
            "type": "object",
            "properties": {
                "client": {
                    "type": "string",
                    "description": "The client's slug, or part of its name.",
                }
            },
            "required": ["client"],
            "additionalProperties": False,
        },
        permission="admin:tenants",
        scope="platform",
        run=_admin_client_standing,
    ),
    ReadTool(
        name="healer_incidents",
        description=(
            "The auto-healer's problems — your own repair work: each one's plain title, "
            "where it stands, how long it has been open, the automatic tries used, what to "
            "do, its newest steps, and for money problems the evidence you stored when you "
            "handed it over. Each line ends with its [ref]. Call this before saying anything "
            "about what the healer found or fixed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "include_closed": {
                    "anyOf": [{"type": "boolean"}, {"type": "null"}],
                    "description": "True to include problems closed in the last 7 days.",
                }
            },
            "required": ["include_closed"],
            "additionalProperties": False,
        },
        # The healer screen's own permission (`healer/routes.py`, `ops:manage`).
        permission="ops:manage",
        scope="platform",
        run=_healer_incidents,
    ),
    ReadTool(
        name="healer_incident",
        description=(
            "One healer problem in full, by its ref: what it means, the client it is about, "
            "what its playbook may do and whether it is switched off, every step taken, and "
            "which of healer_retry, healer_resolve and healer_attest_rate you may propose."
        ),
        parameters={
            "type": "object",
            "properties": {
                "incident": {
                    "type": "string",
                    "description": "The problem's ref (8 characters) or its full id.",
                }
            },
            "required": ["incident"],
            "additionalProperties": False,
        },
        permission="ops:manage",
        scope="platform",
        run=_healer_incident,
    ),
    ReadTool(
        name="healer_money_review",
        description=(
            "The evidence behind every open money problem at once, from our own records: "
            "charged calls compared with what we metered, the per-minute rates in force, "
            "the calls that differ with the rate each one's charge implies, and whether one "
            "rate change explains them all. Use it before explaining a money problem or "
            "proposing healer_attest_rate."
        ),
        parameters=_NO_ARGS,
        permission="ops:manage",
        scope="platform",
        run=_healer_money_review,
    ),
    # D-934: a chart across clients, drawn in the panel (`copilot/charts.py`).
    FLEET_CHART,
)

ADMIN_READ_TOOL_NAMES: Final[frozenset[str]] = frozenset(tool.name for tool in ADMIN_READ_TOOLS)


__all__ = ["ADMIN_READ_TOOLS", "ADMIN_READ_TOOL_NAMES"]
