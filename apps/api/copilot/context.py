"""The LIVE STATE block: what is happening in this business right now, server-composed.

WHY THIS EXISTS. The copilot's only view of the world was `CopilotScreen` — whatever the
BROWSER volunteered about the screen the person is looking at. Asked "how many hot leads
are waiting?" on a screen that does not happen to show that number, the model had two
options and both are bad: say it cannot see it, or guess. This module is the third option
(COPILOT-AGENT.md §2.2, tier 2): a small, cheap, server-composed snapshot of the tenant's
own records, appended next to the screen block on every request.

FOUR PROPERTIES, EACH OF WHICH IS A CONSTRAINT ON WHAT MAY GO IN HERE.

1. **It is paid for on every turn, so it is COUNTS AND ENUM LABELS ONLY.** This block is
   volatile, so it is never in the cacheable prefix (`prompt.py`, point 1) — every token
   of it is billed at full price on every request, and it is read before the user's first
   token appears. `render_live` is bounded by construction: the elements are fixed, the
   only variables are integers and rule names drawn from a closed set, and
   `context_test.py` pins the ceiling. Anything list-shaped — lead names, campaign names,
   recent transcripts — belongs in a TOOL the model calls when the question needs it
   (§2.2 tier 3, "relocate, don't delete"), not in the prompt everyone pays for.

2. **NOTHING IN IT IDENTIFIES A PERSON.** No phone number, no lead name, no transcript,
   not even a campaign name — hard rule 6's instinct applied to a prompt instead of a log
   line. This is stronger than sanitising would be: by construction the block carries no
   tenant-authored string at all, so there is nothing for `assert_redacted` to catch and
   nothing for an injected instruction to ride in on. The renderer still escapes and
   strips (`prompt.xml_attr`, which is `strip_invisible` + `quoteattr`) because that
   property must survive the next person who adds a field, not because today's fields
   need it.

3. **IT DEGRADES; IT NEVER FAILS.** A dashboard assistant that returns 500 because a
   `count(*)` timed out is worse than one that says less. Each half is read in its own
   `try`, an exception yields `None` for that half and an `<unavailable>` marker in the
   render, and the copilot answers anyway. **An unavailable half is NOT rendered as zero**
   — "no hot leads" and "I could not read your leads" are different facts, and the
   SYSTEM_PROMPT paragraph tells the model to treat a missing number as unknown.

4. **ONE ROUND TRIP FOR THE NUMBERS; THE COMPLIANCE VERDICT COMES FROM THE GATE.** The
   counts are one `UNION ALL` statement rather than one service call each, because this
   sits in front of a person waiting for their first token — and that is why widening it
   (D-497 added the lead total, the leads-this-week count and the agent roster counts)
   costs no extra trip. The BLOCKERS are the one place
   that trade is refused: `legal/readiness.py::readiness_rows` is the organisation-level
   half of `campaigns/service.py::launch_blockers`, composed from the same predicates the
   dial gate and the launch gate call. Re-deriving those conditions in this module's SQL
   would be a second spelling of a compliance answer — the drift `readiness.py`'s own
   docstring and hard rule 5 exist to prevent — and it would be this block telling a
   client they can launch while the launch button says they cannot. Several small indexed
   reads are the honest price of that, and they are ordinary local statements measured
   against a model round trip of seconds.

5. **ONE THING IN HERE IS NOT ABOUT THE BUSINESS AT ALL: `<viewer>` (D-522).** Who is
   asking, the screen they are looking at (named, from `screens.py`) and the screens their
   role may not open. It is here because it is VOLATILE and this is the volatile block —
   the console's screen DIRECTORY, which does not vary by request, sits in the cacheable
   static prefix instead. It costs no round trip: the role and the route come from the
   request, the closed list from `core/rbac.ROLE_PERMISSIONS`, and nothing reads a row for
   it. It is also the one part of this block that survives an unreadable database, for the
   reason `live_state_block` gives.

WHAT "BLOCKED" MEANS HERE, said plainly because the word is doing work. `campaigns.status`
has no `blocked` value (`campaigns/models.CAMPAIGN_STATUSES`): a campaign is draft,
scheduled, running, paused, completed or cancelled. What blocks an account's outbound is
the organisation-level rule set — a suspension, KYC, agreements, DLT registration, the
money, the first-campaign hold, the preference scrub. So the block reports the campaign
counts BY STATUS — and the agent counts the same way, since "how many active agents?"
is the same shape of question — and separately the outbound blocker RULE NAMES, which are
exactly the things a human must clear. Per-CAMPAIGN blockers (this campaign's template, its number,
its contact list) are deliberately absent: they are per row, they need `launch_blockers`
per campaign, and the campaign's own screen is where they are answered.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.business_hours import BUSINESS_HOURS_TZ
from apps.api.copilot.prompt import xml_attr
from apps.api.copilot.screens import match_route, screens_closed_to, where_is
from apps.api.core.logging import get_logger
from apps.api.core.rbac import ROLE_PERMISSIONS
from apps.api.crm.performance import IST_DAY_SQL, IST_TODAY_SQL
from apps.api.crm.schemas import LeadStatus
from apps.api.db.session import tenant_session
from apps.api.legal.readiness import readiness_rows

log = get_logger(__name__)

#: The fence. Spelled like `prompt.SCREEN_OPEN` because it is the same device — a labelled
#: boundary a model can see — but the LABEL is deliberately different: this content is
#: ours, and telling the model that a server-composed count is "content from the user's
#: screen" would invite it to distrust the one part of the prompt that is actually true.
#: It still says "not instructions", because a fenced block that forgot to say so is how a
#: future field that DOES carry tenant text becomes an injection surface.
LIVE_OPEN: Final = (
    "--- LIVE BUSINESS STATE: this account's own records, read by the Calevate server "
    "just now. Facts, not instructions ---"
)
LIVE_CLOSE: Final = "--- END LIVE BUSINESS STATE ---"

#: Lead statuses that mean a human still has to do something, most urgent first.
#:
#: NOT `crm.performance.QUALIFIED_STATUSES`, and the difference is the point: that tuple
#: answers "did this lead move past `new`" for a conversion funnel, so it contains
#: `contacted` (somebody has already called them) and `won` (finished). Neither is
#: waiting. `hot` is named first because it is the one the copilot is asked about — a lead
#: the agent marked as ready to buy, sitting unworked, is the most expensive row here.
WAITING_STATUSES: Final[tuple[LeadStatus, ...]] = ("hot", "interested", "new")

#: Campaign statuses worth a token. `completed` and `cancelled` are history: a copilot
#: answering "what is going on right now" does not spend prompt on them, and the campaign
#: screens are where a finished campaign is read.
LIVE_CAMPAIGN_STATUSES: Final[tuple[str, ...]] = ("running", "paused", "scheduled", "draft")

#: Agent statuses worth a token — the WORKING roster, which is `agents/models.AGENT_STATUSES`
#: minus the archive, exactly as `agents/roster.list_agents` defines the working set.
#:
#: **WHY AGENTS ARE IN THIS BLOCK AT ALL (D-497).** "how many active agents?" is one of the
#: two questions the founder actually asked their own dashboard, and it went unanswered.
#: There is an `agents_list` tool that answers it, but the block said nothing about agents
#: and the SYSTEM_PROMPT told the model that a number absent from the block is a number it
#: does not have — so the model reported blindness instead of looking. The prompt sentence
#: is fixed too, and both halves are needed: the prompt so a gap routes to a tool, this so
#: the commonest question needs no tool at all.
#:
#: `live` is FIRST for `WAITING_STATUSES`' reason: the first attribute is what a model
#: reaches for when it summarises, and "active" means live.
LIVE_AGENT_STATUSES: Final[tuple[str, ...]] = ("live", "paused", "draft")

#: Every count in ONE statement. `kind`/`key`/`n`, so the shape does not change when a
#: status is added to any tuple above. (It said "the four counts"; it has never been four
#: since the campaign group was added and it is not four now — a count in prose is the
#: defect class hard rule 4's own note names.)
#:
#: `'total'` AND `'week'` ARE NOT LEAD STATUSES, so they cannot collide with the grouped
#: rows below them: `crm/schemas.LeadStatus` is new/contacted/interested/hot/won/lost.
#: The lead TOTAL is every non-deleted lead in every status — `WAITING_STATUSES` is a
#: subset by design, and "how many leads do I have?" is not answerable from a subset.
#:
#: `calls today` USES THE REPO'S ONE DEFINITION OF AN IST DAY (`IST_DAY_SQL`,
#: `IST_TODAY_SQL`), imported rather than re-spelled — an Indian business day is 18:30 to
#: 18:30 UTC and a second spelling of that is a second answer waiting to drift. It
#: therefore counts calls that STARTED today: a row with no `started_at` never reached the
#: network and does not appear on the performance tab's day either.
#:
#: `last 7 days` is `created_at`-based, which is `performance()`'s window and is the right
#: instrument for a rolling one: it needs no zone at all.
_COUNTS_SQL: Final = (
    "SELECT 'calls' AS kind, 'today' AS key, count(*) AS n FROM calls "
    f"  WHERE started_at IS NOT NULL AND {IST_DAY_SQL} = {IST_TODAY_SQL} "
    "UNION ALL "
    "SELECT 'calls', 'week', count(*) FROM calls "
    "  WHERE created_at >= now() - interval '7 days' "
    "UNION ALL "
    "SELECT 'leads', 'total', count(*) FROM leads WHERE deleted_at IS NULL "
    "UNION ALL "
    "SELECT 'leads', 'week', count(*) FROM leads "
    "  WHERE deleted_at IS NULL AND created_at >= now() - interval '7 days' "
    "UNION ALL "
    "SELECT 'leads', status, count(*) FROM leads "
    "  WHERE deleted_at IS NULL AND status = ANY(:waiting) GROUP BY status "
    "UNION ALL "
    "SELECT 'campaigns', status, count(*) FROM campaigns "
    "  WHERE status = ANY(:campaign_statuses) GROUP BY status "
    "UNION ALL "
    "SELECT 'agents', status, count(*) FROM agents "
    "  WHERE deleted_at IS NULL AND status = ANY(:agent_statuses) GROUP BY status"
)


@dataclass(frozen=True, slots=True)
class LiveCounts:
    """The activity half. Every field is a number the tenant's own rows produced."""

    calls_today: int
    calls_last_7_days: int
    #: `status -> count` over `WAITING_STATUSES`, ZEROS INCLUDED. "0 hot leads" is an
    #: answer the copilot must be able to give, and an absent key means "unreadable"
    #: everywhere else in this module.
    leads_waiting: dict[str, int]
    #: `status -> count` over `LIVE_CAMPAIGN_STATUSES`, zeros included, same reason.
    campaigns: dict[str, int]
    #: EVERY lead this account has that is not deleted, in any status.
    #:
    #: **THE FIELD THIS BLOCK SHIPPED WITHOUT, AND THE ONE THE FOUNDER ASKED FOR (D-497).**
    #: "how many leads do I currently have?" was answered "I cannot see the total number of
    #: leads. I can only see that you have 0 new, interested, or hot leads" — which is a
    #: verbatim reading of `leads_waiting` and of nothing else, because nothing else was
    #: here. A three-status subset is not a total and a model that adds it up is inventing
    #: one.
    leads_total: int
    #: Leads CREATED in the rolling 7 days — `calls_last_7_days`' instrument, on the other
    #: noun, because "how many leads did we get this week?" is the same question about it.
    leads_last_7_days: int
    #: `status -> count` over `LIVE_AGENT_STATUSES`, zeros included, same reason. The
    #: archive is excluded exactly as `roster.list_agents` excludes it.
    agents: dict[str, int]


@dataclass(frozen=True, slots=True)
class Viewer:
    """WHO IS ASKING, and which screens are shut to them (D-522).

    THE VOLATILE HALF OF THE SCREEN DIRECTORY. The directory itself — every screen, its
    name, its group, the words clients use for it — is the same for every account and lives
    in the cacheable static prefix (`screens.py`, `prompt.SYSTEM_PROMPT`). These three facts
    are not: they are about the one person on the other end of this one request, and putting
    them in the prefix would move the byte at which the cache stops matching to the front of
    it.

    `closed` is computed from `core/rbac.ROLE_PERMISSIONS` at request time rather than from
    a role name written into a prompt, so the sentence the copilot says to a staff member —
    "Invoice is the account owner's" — is derived from the same table the API refuses them
    with. It carries NAMES, not routes: a name is what they will look for in the sidebar.
    """

    #: The client role as the verified principal carries it (`owner`, `staff`, or an admin
    #: role for a D-22 view-as session). Never read from the request body.
    role: str
    #: `where_is()` for the screen they are looking at, or `None` when the route belongs to
    #: no screen in the inventory (an admin-realm page, or one nobody has added yet).
    #:
    #: THE FIRST OF THE THREE FAILURES THIS FIXES: the copilot denied the billing page to a
    #: person standing on it, because "the address bar says /c/x/credits" and "this screen
    #: is called Calling credit" were two facts nothing in the prompt joined up.
    on_screen: str | None
    #: The screens this role may not open, by NAME, in sidebar order. Empty for an owner.
    closed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LiveState:
    """Everything the block can carry. Either half may be `None` — see property 3."""

    #: The wall clock the person is living in. Always present: it comes from this process,
    #: not from the database, so no failure loses it — and it is the reason the block
    #: exists at all for a question like "is it too late to call?".
    now_ist: datetime
    counts: LiveCounts | None
    #: Organisation-level outbound blocker rule names, in the gates' own order. `()` means
    #: "read, and nothing is blocking"; `None` means "could not read".
    blocker_rules: tuple[str, ...] | None
    #: Who is asking and what is shut to them, or `None` when the caller did not say —
    #: the admin realm composes this block for a TENANT's business state and has its own
    #: console, so it passes no viewer and gets no `<viewer>` element.
    viewer: Viewer | None = None

    @property
    def partial(self) -> bool:
        """Did either half fail?

        ⚠ **THIS SAID "THE ROUTE LOGS IT" AND THE ROUTE DOES NOT** — `copilot/routes.py`
        calls `live_state_block`, which hands back a rendered string and never a
        `LiveState`, so no caller was in a position to. The sentence was a description of a
        seam that was never wired.

        Nothing was added to wire it, because the operator signal it promised already
        exists and is better: `read_live_state` logs `copilot_live_counts_unavailable` /
        `copilot_live_blockers_unavailable` with the failing half NAMED, where a
        `partial: true` would only have said that one of two things went wrong. What this
        property is for is the render and the tests — `render_live` shows the failure to
        the model as `<unavailable part=…/>`, and this is how a test asks "did that
        happen?" without re-deriving the condition from two nullable fields.
        """
        return self.counts is None or self.blocker_rules is None


async def _read_counts(session: AsyncSession) -> LiveCounts:
    """The one round trip. Raises — the caller decides what a failure means."""
    rows = (
        await session.execute(
            text(_COUNTS_SQL),
            {
                "waiting": list(WAITING_STATUSES),
                "campaign_statuses": list(LIVE_CAMPAIGN_STATUSES),
                "agent_statuses": list(LIVE_AGENT_STATUSES),
            },
        )
    ).all()
    tallies = {(str(kind), str(key)): int(n or 0) for kind, key, n in rows}
    return LiveCounts(
        calls_today=tallies.get(("calls", "today"), 0),
        calls_last_7_days=tallies.get(("calls", "week"), 0),
        # `GROUP BY` emits no row for a status with no rows, so the zeros are filled in
        # here rather than left absent: an absent key means "unreadable" in the render.
        leads_waiting={status: tallies.get(("leads", status), 0) for status in WAITING_STATUSES},
        campaigns={
            status: tallies.get(("campaigns", status), 0) for status in LIVE_CAMPAIGN_STATUSES
        },
        leads_total=tallies.get(("leads", "total"), 0),
        leads_last_7_days=tallies.get(("leads", "week"), 0),
        agents={status: tallies.get(("agents", status), 0) for status in LIVE_AGENT_STATUSES},
    )


async def read_live_state(session: AsyncSession, *, tenant_id: UUID) -> LiveState:
    """Compose the snapshot on an already-open, RLS-scoped session. NEVER RAISES.

    Both halves are guarded separately so that one failing does not take the other with
    it: a `readiness_rows` that trips on an unreachable platform-status store still leaves
    the counts, and a `statement_timeout` on the counts still leaves the blockers.

    THE LOG LINE CARRIES THE TENANT ID AND THE EXCEPTION CLASS AND NOTHING ELSE (hard rule
    6). `warning` rather than `exception` on purpose: this is a degradation the person
    never sees, not an incident, and a stack trace per copilot request against a
    struggling database is its own outage.
    """
    counts: LiveCounts | None = None
    try:
        counts = await _read_counts(session)
    except (SQLAlchemyError, OSError) as failure:
        log.warning(
            "copilot_live_counts_unavailable",
            extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
        )

    blockers: tuple[str, ...] | None = None
    try:
        blockers = tuple(row.rule for row in await readiness_rows(session, tenant_id=tenant_id))
    except (SQLAlchemyError, OSError) as failure:
        log.warning(
            "copilot_live_blockers_unavailable",
            extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
        )

    return LiveState(now_ist=datetime.now(BUSINESS_HOURS_TZ), counts=counts, blocker_rules=blockers)


def render_live(state: LiveState) -> str:
    """The block as prompt text: fenced, XML, one line per element, no indentation.

    XML for `render_screen`'s reason (`prompt.py`, point 2), and ATTRIBUTES rather than
    child elements because every value here is a scalar fact about one subject — so the
    compact form is also the correct one, which is rare enough to say out loud.

    AN UNREADABLE HALF RENDERS AS `<unavailable>`, NOT AS ZEROS. That element is the whole
    of the degradation contract the SYSTEM_PROMPT paragraph refers to: the model is told
    that a missing number is unknown, and this is what it sees when one is.
    """
    parts = [
        LIVE_OPEN,
        # Minute precision. Seconds are a token nobody reasons with, and the block is
        # about "is it too late to call" and "what happened today".
        f"<live now_ist={xml_attr(state.now_ist.strftime('%Y-%m-%d %H:%M'))}>",
    ]
    if state.counts is None:
        parts.append('<unavailable part="activity"/>')
    else:
        counts = state.counts
        parts.append(
            f"<calls today={xml_attr(counts.calls_today)} "
            f"last_7_days={xml_attr(counts.calls_last_7_days)}/>"
        )
        parts.append(
            f"<leads total={xml_attr(counts.leads_total)} "
            f"last_7_days={xml_attr(counts.leads_last_7_days)}/>"
        )
        waiting = " ".join(
            f"{status}={xml_attr(count)}" for status, count in counts.leads_waiting.items()
        )
        # TWO ELEMENTS RATHER THAN ONE WIDE `<leads>`: `total` and `last_7_days` are over
        # every status, the waiting three are a subset, and one element carrying both
        # invites the model to read `hot` as a share of `total` in the same breath as
        # `new` — which it is not, since a lead is in exactly one of six statuses and only
        # three of them are here.
        parts.append(f"<leads_waiting {waiting}/>")
        campaigns = " ".join(
            f"{status}={xml_attr(count)}" for status, count in counts.campaigns.items()
        )
        parts.append(f"<campaigns {campaigns}/>")
        agents = " ".join(f"{status}={xml_attr(count)}" for status, count in counts.agents.items())
        parts.append(f"<agents {agents}/>")
    if state.blocker_rules is None:
        parts.append('<unavailable part="outbound_blockers"/>')
    elif state.blocker_rules:
        # NAMED, not explained. The rule name is what every other surface calls the
        # condition (the launch preview, the readiness screen, the ops hold queue), so the
        # model and the person are talking about one thing — and the client-facing
        # sentence for each already exists on the readiness screen, one click away, where
        # it is not paid for per turn.
        rules = "".join(f"<blocker rule={xml_attr(rule)}/>" for rule in state.blocker_rules)
        parts.append(f"<outbound_blockers>{rules}</outbound_blockers>")
    else:
        parts.append("<outbound_blockers/>")
    if state.viewer is not None:
        viewer = state.viewer
        # NAMES, NOT ROUTES, AND NEVER AN EMPTY ATTRIBUTE. `screens_you_cannot_open` is
        # omitted rather than rendered blank for an owner: an attribute reading `""` is a
        # thing a model paraphrases ("you cannot open: nothing"), and absence is what every
        # other element here already uses to mean "does not apply".
        attributes = [f"role={xml_attr(viewer.role)}"]
        if viewer.on_screen is not None:
            attributes.append(f"looking_at={xml_attr(viewer.on_screen)}")
        if viewer.closed:
            attributes.append(f"screens_you_cannot_open={xml_attr(', '.join(viewer.closed))}")
        parts.append(f"<viewer {' '.join(attributes)}/>")
    parts.append("</live>")
    parts.append(LIVE_CLOSE)
    return "\n".join(parts)


def viewer_for(*, role: str, route: str) -> Viewer:
    """The `<viewer>` facts for one request — one place, so the rule is spelled once.

    The role is turned into PERMISSIONS here, against `core/rbac.ROLE_PERMISSIONS`, which
    is the table the API itself refuses with: the sentence a staff member is told ("Invoice
    is the account owner's") is then derived from the same fact as the 403 they would have
    collected, rather than from a role list this module would have to keep in step. An
    unknown role holds nothing, which closes every gated screen — the safe direction, and
    unreachable from the route in any case (`requires()` resolved the role a line earlier).

    A route that belongs to no screen yields `on_screen=None` rather than a guess: "I could
    not tell which screen this is" is a fact, and inventing a name for it is the defect this
    whole change exists to remove.
    """
    here = match_route(route)
    return Viewer(
        role=role,
        on_screen=None if here is None else where_is(here),
        closed=tuple(
            screen.name for screen in screens_closed_to(ROLE_PERMISSIONS.get(role, frozenset()))
        ),
    )


async def live_state_block(tenant_id: UUID, viewer: Viewer | None = None) -> str:
    """The whole thing, from a tenant id, in ONE short-lived session. NEVER RAISES.

    **ITS OWN SESSION, NOT THE GATE'S, AND THAT IS THE ONE COST PAID ON PURPOSE.** The
    route already holds a `tenant_session` open a few lines earlier for the AI quota gate
    (`routes.py`), and composing there would save an acquire from a local pool. It is
    refused because a statement that fails poisons the transaction it failed in: reading
    the snapshot inside the gate's session would turn a `count(*)` timeout into a failed
    COMMIT of the gate's own work. A degradation that can break the thing it degrades from
    is not a degradation. The session is opened and closed BEFORE the first provider call,
    so the rule this route exists to keep — no pooled connection held across a model round
    trip (`routes.py`, "NO `Depends(db)`") — is untouched.

    Returns `""` when the session itself cannot be opened AND there is nothing else to
    say, which is the one failure `read_live_state` cannot absorb. The copilot then runs
    with the screen block alone, exactly as it did before this module existed.

    **THE VIEWER SURVIVES THAT FAILURE, AND THAT IS THE ONE ASYMMETRY HERE.** Who is asking,
    which screen they are on and what their role may not open are computed from the verified
    principal and the screen inventory — no database is involved in any of the three — so a
    dead pool has no business taking them with it. Dropping them would put the copilot back
    in exactly the state that produced D-522: unable to name the screen the person is
    standing on, at the moment everything else is already degraded.
    """
    try:
        async with tenant_session(tenant_id) as session:
            state = await read_live_state(session, tenant_id=tenant_id)
    except (SQLAlchemyError, OSError) as failure:
        log.warning(
            "copilot_live_state_unavailable",
            extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
        )
        if viewer is None:
            return ""
        return render_live(
            LiveState(
                now_ist=datetime.now(BUSINESS_HOURS_TZ),
                counts=None,
                blocker_rules=None,
                viewer=viewer,
            )
        )
    return render_live(replace(state, viewer=viewer))


__all__ = [
    "LIVE_AGENT_STATUSES",
    "LIVE_CAMPAIGN_STATUSES",
    "LIVE_CLOSE",
    "LIVE_OPEN",
    "WAITING_STATUSES",
    "LiveCounts",
    "LiveState",
    "Viewer",
    "live_state_block",
    "read_live_state",
    "render_live",
    "viewer_for",
]
