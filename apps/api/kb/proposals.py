"""Agent-proposed knowledge: the KB half of one copilot write tool.

The system can DRAFT a knowledge entry and hand it to a person in the business. Nothing it
drafts reaches a caller's ear without two separate human acts — a confirmation and then an
approval — and this module exists to make the second half of that structural.

═══ WHAT IS HERE AND WHAT IS NOT, BECAUSE THIS MODULE USED TO BE BOTH ═══

It shipped once as a self-contained propose→confirm lane: its own token format, its own
Redis nonce, its own `POST /v1/kb/proposals/confirm`, its own audit write and its own
`WriteTool` record. All of that is DELETED. `copilot/write_tools.py` is the one
propose→confirm machine in this repo — signed five-minute proposal, tenant-and-actor
binding, `jti` burn, permission re-check at confirm, one audit row in the executor's
transaction — and `PROPOSE_KNOWLEDGE` there is this lane's entry in its registry. Two
crypto-and-audit paths for one act is the accumulation CLAUDE.md forbids, and the second
one is where the drift starts.

What stays here is what is genuinely the KNOWLEDGE BASE's and not the copilot's: what may
be drafted, which gaps may be cited, and the one door into `kb_sources`. That is the same
division the other three write tools keep — `crm.service.update_lead`,
`compliance.dnc.add_numbers` and `campaigns.service.set_campaign_status` are all in their
own packages, and `write_tools.py` holds only the described intent.

The functions here RETURN a refusal reason rather than raising one. That is deliberate:
the copilot's refusal type (`WriteRefusedError`, handed back to the model so it can fix
itself inside the turn cap) belongs to the copilot, and importing it here would point this
package at that one — which is also the import cycle that would make registration
impossible. A `str | None` crosses the boundary and the adapter decides what a refusal IS.

═══ WHY THE PROPOSED TEXT IS NEVER DRAFTED FROM CALL DATA ═══

`kb/insights.py::render_digest` states the rule this module obeys: the system can prove
that callers keep reaching something the agent cannot answer, and it CANNOT know what the
right answer is — only the business owner does. So the split is:

* the **WHY** comes from aggregates — an open `knowledge_gaps` roll-up, named by its
  CANONICAL topic key and nothing else (`CITABLE_TOPIC_KEYS`);
* the **WHAT** comes from a person in the business. The model is a scribe for a sentence
  somebody said, never an author of policy inferred from a statistic.

Nothing in this module reads `transcript_turns`, `calls.summary`, a phone column, or the
`example_question_redacted` / `example_answer_redacted` columns that `knowledge_gaps`
carries in the very row `gap_refusal` selects from. `tests/kb_proposals_test.py` asserts
that by SOURCE INVENTORY over this module AND over the adapter in `copilot/write_tools.py`
— the technique `tests/kb_aggregate_guard_test.py` documents, because a leak added to an
existing SELECT changes no route and trips no behavioural test.

═══ AND THE GATE THAT WAS ALREADY THERE ═══

`submit_proposed_source` calls `kb.service.submit_source` — the same function the "Add
knowledge" form calls, with the same arguments, producing the same state: a
`pending_approval` source and its preview chunks. There is no second write path into
`kb_sources` and no argument this lane can pass that the form cannot, so every downstream
guard (preview, approve, publish, drift sweep, deletion) applies unchanged, because none
of them can tell the two apart except by the audit row. A test asserts this module
contains no INSERT at all: a "pre-approved" shortcut written here would produce a row the
review queue never sees, and nothing else in the repo would notice.
"""

from __future__ import annotations

from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.kb import service as kb_service
from apps.workers.redaction import redact

#: Who raised the subject. `gap_digest` — the knowledge-gap detector found a topic callers
#: keep reaching and the system asked; `copilot` — a person was chatting to the dashboard
#: assistant and a fact came up. The BODY is the person's words in both cases; what differs
#: is who raised the subject, which is exactly what a reviewer needs to know. Both origins
#: ship, both mint the same proposal through the same registry and land in the same review
#: queue: origin varies no gate, it is provenance shown to whoever approves.
ProposalOrigin = Literal["gap_digest", "copilot"]
PROPOSAL_ORIGINS: Final[tuple[ProposalOrigin, ...]] = ("gap_digest", "copilot")

#: The permission both ends of this lane require. `kb:write` is what the "Add knowledge"
#: route already declares — deciding what the agent knows is one permission (D-21), and a
#: second one for the same decision would be two answers to one question. It is in
#: `MUTATING_PERMISSIONS`, which is what makes an impersonating admin unable to reach
#: either end: `write_tools._may` applies D-22's clause, so nothing here needs its own
#: impersonation check and must not grow one.
CURATE_PERMISSION: Final = "kb:write"

#: The gap topics a proposal may CITE. `insights/detection.py::_topic` returns a canonical
#: (key, label) when a keyword matches and otherwise slugs up to three content words out of
#: THE CALLER'S OWN QUESTION — so a `q_*` key and its label are caller-derived text, and
#: citing one would carry a caller's words into a proposal and an audit summary. This is
#: this module's copy of that closed set, spelled here for the reason
#: `insights/models.GAP_SIGNALS` is spelled there rather than imported: a private name in
#: another package is not an interface. `tests/kb_proposals_test.py` asserts it still
#: equals `detection._TOPICS`, so a new canonical topic fails the build rather than
#: silently becoming uncitable — which is exactly how `warranty` was found missing.
CITABLE_TOPIC_KEYS: Final[frozenset[str]] = frozenset(
    {
        "pricing",
        "refund",
        "delivery",
        "timings",
        "location",
        "availability",
        "booking",
        "offers",
        "payment",
        "documents",
        "warranty",
        "general",
    }
)

#: Bounds on what may be drafted. `MAX_BODY_CHARS` is deliberately far below the form's
#: 200k ceiling: a person confirming a proposal has to be able to READ it first, and a wall
#: of text is a consent button pressed on something nobody checked.
MAX_NAME_CHARS: Final = 120
MAX_BODY_CHARS: Final = 4_000
MIN_BODY_CHARS: Final = 10


def proposable_refusal(name: str, body: str) -> str | None:
    """What may be drafted — the reason it may not, or None. Checked at PROPOSE and again
    at CONFIRM.

    Twice, because they are different moments with different inputs: propose validates what
    the model emitted, confirm validates what the signature carried back. The signature
    already proves the second is the first, so the second call is cheap insurance against
    a future second minting path rather than against a forger.

    THE REDACTION GUARD IS THE INTERESTING ONE, and it narrows what THIS LANE can carry
    rather than what the product can. `redact()` masks phone numbers, email addresses and
    identity numbers; a proposal that trips it is refused, which also refuses a business's
    OWN phone number. That is the intended cost and the direction is deliberate: the
    assistant receives only redacted screen state (D-127 G-2), so a contact-shaped string
    in a DRAFTED body is far likelier to be a value reproduced from context than a number
    the business wants callers to hear — and the owner can still type their own number into
    the ordinary Knowledge form, which is unchanged and has no such guard. The refusal names
    that alternative rather than leaving the person stuck.

    THE OFFENDING VALUE IS NEVER NAMED. This string reaches a log line and the model's next
    prompt, and naming it would put the personal value into both — which is the thing being
    prevented (hard rule 6; the argument `copilot/sanitize.assert_redacted` makes at length).
    """
    if not name.strip() or len(name) > MAX_NAME_CHARS:
        return (
            "the suggestion needs a short title of at most "
            f"{MAX_NAME_CHARS} characters and this one does not have it"
        )
    stripped = body.strip()
    if len(stripped) < MIN_BODY_CHARS or len(stripped) > MAX_BODY_CHARS:
        return (
            f"the knowledge must be between {MIN_BODY_CHARS} and {MAX_BODY_CHARS} "
            "characters so the person can read it before confirming"
        )
    if redact(name).changed or redact(stripped).changed:
        return (
            "it contains something shaped like a phone number, an email address or an "
            "identity number, and you may not write those into an agent's knowledge — "
            "say that the person should add it themselves under Knowledge"
        )
    return None


async def gap_refusal(session: AsyncSession, *, agent_id: UUID, topic_key: str) -> str | None:
    """A cited gap must be CANONICALLY named, this agent's, and still open — or the reason.

    SELECTS A LITERAL AND NO COLUMN. `example_question_redacted` and
    `example_answer_redacted` sit in the row this statement matches and are exactly what
    somebody enriching a proposal ("show them what the caller asked") would reach for; they
    are caller-derived, and this lane may not carry them. The `topic_key` allowlist is the
    second half of the same rule — see `CITABLE_TOPIC_KEYS`.

    RLS does the tenancy: the session is already scoped, so there is no `tenant_id`
    predicate here and there must not be one (hard rule 1 — a WHERE clause a caller can
    forget is not isolation).
    """
    if topic_key not in CITABLE_TOPIC_KEYS:
        return (
            f"`{topic_key}` is not a recognised knowledge-gap topic — a suggestion may "
            "only refer to a recognised topic, never to the wording of one caller's "
            "question"
        )
    found = (
        await session.execute(
            text(
                "SELECT 1 FROM knowledge_gaps WHERE agent_id = :aid AND topic_key = :tk "
                "AND status = 'open'"
            ),
            {"aid": agent_id, "tk": topic_key},
        )
    ).scalar()
    if found is None:
        return f"no `{topic_key}` knowledge gap is open on that agent"
    return None


async def submit_proposed_source(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    agent_id: UUID,
    name: str,
    body: str,
) -> dict[str, Any]:
    """THE ONE DOOR, and it is somebody else's door.

    `kb.service.submit_source` with `kind="text"` — byte for byte the call
    `POST /v1/kb/sources` makes. `submitted_by` is the person who CONFIRMED, not the model
    and not the proposer, because that is who the review queue has to be able to ask about
    it.

    A wrapper this thin is worth its line for one reason: it is the name the source
    inventory and the no-INSERT test look for, so "the confirm path has exactly one door
    into `kb_sources`" is a property a test can state about a file rather than a claim
    about a call graph.
    """
    return await kb_service.submit_source(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        name=name,
        body=body,
        kind="text",
        submitted_by=actor_id,
    )


__all__ = [
    "CITABLE_TOPIC_KEYS",
    "CURATE_PERMISSION",
    "MAX_BODY_CHARS",
    "MAX_NAME_CHARS",
    "MIN_BODY_CHARS",
    "PROPOSAL_ORIGINS",
    "ProposalOrigin",
    "gap_refusal",
    "proposable_refusal",
    "submit_proposed_source",
]
