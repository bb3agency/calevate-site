"""Agent-proposed knowledge, approved by the owner — the write-back half of the KB.

The system can now DRAFT a knowledge entry and hand it to a person in the business.
Nothing it drafts reaches a caller's ear without two separate human acts, and this module
exists to make that structural rather than documentary.

═══ THE THREE GATES, AND WHY THERE ARE THREE ═══

1. **PROPOSING WRITES NOTHING.** `build_proposal` reads (an agent row must be visible, a
   cited gap must be open on it) and returns a signed, expiring, single-use token. No row
   is created, no queue is joined, nothing is reserved. A model that hallucinates a
   proposal has produced a string.
2. **CONFIRMING IS A HUMAN ACT ON A BOUND TOKEN.** `confirm_proposal` re-verifies the
   signature, the expiry, the tenant, the actor and the agent, burns the nonce so the same
   token cannot execute twice, and then calls `kb.service.submit_source` — the SAME
   function the "Add knowledge" form calls, with the same arguments, producing the same
   state: a `pending_approval` source and its preview chunks.
3. **APPROVAL IS UNCHANGED AND UNTOUCHED.** `submit_source` does not publish; only
   `kb.approve_source` → `kb.publish_source` does, on the admin surface, by a human who
   previewed the chunks. This module adds no route to that path, no flag that skips it and
   no state that anticipates it. See `kb/__init__.py`: the preview-and-approve gate is "a
   product property, not a vendor feature", and a write-back lane that shortened it would
   have deleted the product property in order to ship a feature.

═══ WHY THE PROPOSED TEXT IS NEVER DRAFTED FROM CALL DATA ═══

`kb/insights.py::render_digest` states the rule this module obeys: the system can prove
that callers keep reaching something the agent cannot answer, and it CANNOT know what the
right answer is — only the business owner does. So the split here is deliberate and is the
whole safety argument:

* the **WHY** comes from aggregates — an open `knowledge_gaps` roll-up, named by its
  CANONICAL topic key and nothing else (`CITABLE_TOPIC_KEYS`);
* the **WHAT** comes from a person in the business. The model is a scribe for a sentence
  somebody said, never an author of policy inferred from a statistic.

`ORIGIN` says which side started the conversation, and it is on the token and in the audit
row because an owner reviewing a queue has to be able to tell "your agent noticed this"
from "you and the assistant were talking and this came up" — they carry different trust.
It does NOT vary the gates: both origins mint the same proposal, confirm through the same
function and land in the same review queue.

Nothing in this module reads `transcript_turns`, `calls.summary`, a phone column, or the
`example_question_redacted` / `example_answer_redacted` columns that `knowledge_gaps`
carries in the very row this module selects from. `tests/kb_proposals_test.py` asserts
that by SOURCE INVENTORY — the technique `tests/kb_aggregate_guard_test.py` documents,
because a leak added to an existing SELECT changes no route and trips no behavioural test.

═══ WHY A SIGNED TOKEN RATHER THAN A `kb_proposals` TABLE ═══

A table would need a migration, an RLS policy, a retention story, a DPDP erasure story and
a sweeper for the proposals nobody confirmed — durable state whose entire purpose is to
live for ten minutes. The token carries its own claims and its own expiry, and the only
durable thing it needs is a way to be spent ONCE, which is a Redis `SET NX` (the primitive
`core/auth.py::_first_read_in_window` already uses). Same reasoning as a signed
confirmation link. The one place that reasoning inverts is the KB entry itself, which is
durable, reviewable and erasable — and that row is `kb_sources`, which already exists.
"""

from __future__ import annotations

import base64
import hmac
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.authn.hashing import derived_ring
from apps.api.compliance.audit import write_audit
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible
from apps.api.kb import service as kb_service
from apps.workers.redaction import redact

log = get_logger(__name__)

#: HKDF `info` for this module's signing key (RFC 5869 §3.2 key separation). Distinct from
#: the password pepper's and from `authn/codes.py`'s, so a proposal signature can never be
#: traded for either — the discipline `authn/hashing.derived_ring` exists to keep.
PROPOSAL_INFO: Final = b"calevate/kb-proposal/v1"

#: How long a proposal stays confirmable. Long enough to read the drafted paragraph and
#: think about it, short enough that a token left in a browser history is already dead.
PROPOSAL_TTL_S: Final = 600

#: The nonce's Redis key prefix. The burn record outlives the token by a margin, so that a
#: replay arriving at the last legal instant finds a SPENT nonce rather than an absent one
#: — "already used" and "never seen" must not converge inside the window where the
#: signature still verifies.
_BURN_PREFIX: Final = "kb:proposal:burned:"
_BURN_TTL_S: Final = PROPOSAL_TTL_S * 2

#: Who started it. `gap_digest` — the knowledge-gap detector found a topic callers keep
#: reaching and the system asked; `copilot` — a person was chatting to the dashboard
#: assistant and a fact came up. The BODY is the person's words in both cases; what
#: differs is who raised the subject, which is exactly what a reviewer needs to know.
ProposalOrigin = Literal["gap_digest", "copilot"]
PROPOSAL_ORIGINS: Final[tuple[ProposalOrigin, ...]] = ("gap_digest", "copilot")

#: The gap topics a proposal may CITE. `insights/detection.py::_topic` returns a canonical
#: (key, label) when a keyword matches and otherwise slugs up to three content words out of
#: THE CALLER'S OWN QUESTION — so a `q_*` key and its label are caller-derived text, and
#: citing one would carry a caller's words into a proposal and an audit summary. This is
#: this module's copy of that closed set, spelled here for the reason
#: `insights/models.GAP_SIGNALS` is spelled there rather than imported: a private name in
#: another package is not an interface. `tests/kb_proposals_test.py` asserts it still
#: equals `detection._TOPICS`, so a new canonical topic fails the build rather than
#: silently becoming uncitable.
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
        "general",
    }
)

#: Bounds on what may be drafted. `MAX_BODY_CHARS` is deliberately far below the form's
#: 200k ceiling: a person confirming a proposal has to be able to READ it first, and a
#: wall of text is a consent button pressed on something nobody checked.
MAX_NAME_CHARS: Final = 120
MAX_BODY_CHARS: Final = 4_000
MIN_BODY_CHARS: Final = 10

#: The tool the model calls. Named for what it does to the system, not for what it does to
#: the conversation: it proposes, and a proposal is not a write.
PROPOSE_KNOWLEDGE_TOOL_NAME: Final = "propose_knowledge"

#: The permission both ends of this lane require. `kb:write` is what the "Add knowledge"
#: route and the knowledge-gap teach route already declare — deciding what the agent knows
#: is one permission (D-21), and a second one for the same decision would be two ways to
#: answer one question. It is in `MUTATING_PERMISSIONS`, which is also what makes an
#: impersonating admin unable to reach either end: `core/auth.requires` refuses those
#: under D-22, so nothing here needs its own impersonation check and must not grow one.
CURATE_PERMISSION: Final = "kb:write"


@dataclass(frozen=True, slots=True)
class KbProposal:
    """One drafted knowledge entry, bound to who may confirm it and to what it would do.

    Every field is a CLAIM the signature protects and `confirm_proposal` re-checks against
    the live principal — the token is evidence that WE minted these claims, never evidence
    that they are still true. `nonce` is what makes it single-use.
    """

    nonce: str
    tenant_id: UUID
    actor_id: UUID
    agent_id: UUID
    name: str
    body: str
    origin: ProposalOrigin
    #: The canonical gap topic this answers. REQUIRED when `origin` is `gap_digest` (you
    #: cannot claim the agent noticed something without naming what it noticed) and
    #: optional otherwise. Never a `q_*` key — see `CITABLE_TOPIC_KEYS`.
    topic_key: str | None
    expires_at: datetime

    def claims(self) -> dict[str, Any]:
        """The signed payload. Every field is in it — a claim outside the signature is a
        field an attacker may edit."""
        return {
            "nonce": self.nonce,
            "tenant_id": str(self.tenant_id),
            "actor_id": str(self.actor_id),
            "agent_id": str(self.agent_id),
            "name": self.name,
            "body": self.body,
            "origin": self.origin,
            "topic_key": self.topic_key,
            "expires_at": self.expires_at.isoformat(),
        }


# --- signing ------------------------------------------------------------------


def _canonical(claims: dict[str, Any]) -> bytes:
    """Canonical JSON: sorted keys, no whitespace, UTF-8 preserved.

    `sort_keys` rather than insertion order because the bytes must be reproducible from a
    DECODED payload, whose key order is whatever the parser handed back.
    `ensure_ascii=False` so a Telugu body signs and verifies as the bytes it was written
    as, rather than as whatever the encoder felt like escaping.
    """
    return json.dumps(claims, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sign(payload: bytes, key: bytes) -> str:
    return base64.urlsafe_b64encode(hmac.digest(key, payload, "sha256")).decode().rstrip("=")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token(proposal: KbProposal) -> str:
    """`<payload>.<signature>`, signed under the ACTIVE derived key.

    Signed under generation 0 only, verified across the whole ring — the same
    write-new/read-any discipline `authn/codes.py` keeps, so a KEK rotation does not
    invalidate a proposal somebody is reading right now.
    """
    payload = _canonical(proposal.claims())
    return f"{_b64encode(payload)}.{_sign(payload, derived_ring(PROPOSAL_INFO)[0])}"


def _refuse(
    code: str, title: str, detail: str, remediation: str, status: int = 400
) -> ProblemError:
    """One refusal shape for every way a token can fail to be confirmable.

    The DETAIL is deliberately the same story for a forged signature, a tampered payload,
    an expired token and a token addressed to somebody else: a caller who can tell those
    apart has an oracle for which half of a token they got right. What differs is the
    `code`, so the browser can offer the right next step, and the remediation — which is
    the same sentence in every case, because the person's action is the same: get a fresh
    proposal.
    """
    return ProblemError(
        kind="validation",
        code=code,
        title=title,
        detail=detail,
        remediation=remediation,
        status=status,
    )


def _invalid() -> ProblemError:
    return _refuse(
        "kb_proposal_invalid",
        "That suggestion is no longer valid",
        "This knowledge suggestion could not be confirmed — it may have expired, already "
        "been used, or been altered.",
        "Ask for the suggestion again, then confirm the new one.",
    )


def verify_token(token: str) -> KbProposal:
    """Decode and authenticate a token, or refuse. Says nothing about WHO is presenting it.

    Split from the principal checks in `confirm_proposal` on purpose: this half proves the
    token is ours and intact, the other half proves it belongs to the person holding it,
    and conflating them is how a valid-signature check comes to stand in for an
    authorization check.
    """
    encoded, _, signature = token.partition(".")
    if not encoded or not signature:
        raise _invalid()
    try:
        payload = _b64decode(encoded)
        claims = json.loads(payload)
    except (ValueError, json.JSONDecodeError) as exc:
        raise _invalid() from exc
    if not isinstance(claims, dict):
        raise _invalid()
    # EVERY generation, and `compare_digest` on each: a rotation must not invalidate a
    # token in flight, and a wrong signature must not leak where it stopped matching.
    if not any(
        hmac.compare_digest(signature, _sign(payload, key)) for key in derived_ring(PROPOSAL_INFO)
    ):
        raise _invalid()
    try:
        origin = str(claims["origin"])
        if origin not in PROPOSAL_ORIGINS:
            raise ValueError("origin")
        proposal = KbProposal(
            nonce=str(claims["nonce"]),
            tenant_id=UUID(str(claims["tenant_id"])),
            actor_id=UUID(str(claims["actor_id"])),
            agent_id=UUID(str(claims["agent_id"])),
            name=str(claims["name"]),
            body=str(claims["body"]),
            origin=origin,
            topic_key=None if claims["topic_key"] is None else str(claims["topic_key"]),
            expires_at=datetime.fromisoformat(str(claims["expires_at"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        # Reachable only under a key compromise or a bug in `claims()` — the signature
        # already verified, so these bytes are ours. Logged as an operator problem, with
        # the exception TYPE and nothing from the payload (hard rule 6).
        log.error("kb_proposal_claims_malformed", extra={"error": type(exc).__name__})
        raise _invalid() from exc
    if proposal.expires_at <= datetime.now(UTC):
        raise _invalid()
    return proposal


async def _burn(nonce: str) -> None:
    """Spend the nonce, or refuse. FAILS CLOSED, unlike the audit-window cache.

    `core/auth.py::_first_read_in_window` uses this same `SET NX` and fails TOWARDS
    recording, because an audit control degrading into noise is the safe direction there.
    Here the direction is the opposite: Redis is the only thing standing between a
    captured token and a second `kb_sources` row, so an unreachable Redis means the
    confirmation does not happen. A lost draft is one sentence to recover; "single-use" is
    either true or it is not, and a replay guard that quietly stops guarding during an
    outage is worse than one that stops working visibly.
    """
    try:
        fresh = bool(await get_redis().set(f"{_BURN_PREFIX}{nonce}", "1", nx=True, ex=_BURN_TTL_S))
    except Exception as exc:
        log.warning("kb_proposal_burn_unavailable", extra={"error": type(exc).__name__})
        raise _refuse(
            "kb_proposal_unconfirmable",
            "We could not confirm that just now",
            "The service that makes a suggestion single-use is temporarily unavailable, "
            "so the suggestion was not added.",
            "Try again in a moment. Nothing was saved.",
            status=503,
        ) from exc
    if not fresh:
        raise _refuse(
            "kb_proposal_already_used",
            "That suggestion was already added",
            "This knowledge suggestion has already been confirmed once.",
            "Open Knowledge in your dashboard to see it waiting for review.",
            status=409,
        )


# --- the content guards -------------------------------------------------------


def assert_proposable(name: str, body: str) -> None:
    """What may be drafted. Run at PROPOSE and again at CONFIRM.

    Twice, because they are different moments with different inputs: propose validates
    what the model emitted, confirm validates what came back off the wire. The signature
    already proves the second is the first — but the guard costs a regex sweep, and the
    alternative is a rule that holds only until somebody adds a second minting path.

    THE REDACTION GUARD IS THE INTERESTING ONE, and it narrows what THIS LANE can carry
    rather than what the product can. `redact()` masks phone numbers, email addresses and
    identity numbers; a proposal that trips it is refused, which also refuses a business's
    OWN phone number. That is the intended cost and the direction is deliberate: the
    assistant receives only redacted screen state (D-127 G-2), so a contact-shaped string
    in a DRAFTED body is far likelier to be a value reproduced from context than a number
    the business wants callers to hear — and the owner can still type their own number
    into the ordinary Knowledge form, which is unchanged and has no such guard. The
    refusal names that alternative rather than leaving the person stuck.
    """
    if not name.strip() or len(name) > MAX_NAME_CHARS:
        raise _refuse(
            "kb_proposal_name_invalid",
            "That suggestion needs a title",
            f"A knowledge suggestion needs a short title of at most {MAX_NAME_CHARS} characters.",
            "Ask for the suggestion again with a shorter title.",
        )
    stripped = body.strip()
    if len(stripped) < MIN_BODY_CHARS or len(stripped) > MAX_BODY_CHARS:
        raise _refuse(
            "kb_proposal_body_invalid",
            "That suggestion is not the right length",
            f"A knowledge suggestion must be between {MIN_BODY_CHARS} and "
            f"{MAX_BODY_CHARS} characters, so you can read it before confirming.",
            "Ask for a shorter version, or add longer knowledge yourself under Knowledge "
            "in your dashboard.",
        )
    # The offending value is NOT named in the refusal — naming it would put the personal
    # value into a problem body, which is the thing being prevented (hard rule 6; the
    # argument `copilot/sanitize.assert_redacted` makes at length).
    if redact(name).changed or redact(stripped).changed:
        raise _refuse(
            "kb_proposal_contains_contact_details",
            "The assistant cannot add contact details for you",
            "This suggestion contains something that looks like a phone number, an email "
            "address or an identity number, and the assistant is not allowed to write "
            "those into your agent's knowledge.",
            "Add it yourself under Knowledge in your dashboard — type the number or "
            "address in there, and it goes through the same review.",
        )


async def _assert_citable_gap(session: AsyncSession, *, topic_key: str, agent_id: UUID) -> None:
    """A cited gap must be CANONICALLY named, this agent's, and still open.

    Selects a literal and no column. `example_question_redacted` and
    `example_answer_redacted` sit in the row this statement matches and are exactly what
    somebody enriching a proposal ("show them what the caller asked") would reach for;
    they are caller-derived, and this lane may not carry them. The `topic_key` allowlist
    is the second half of the same rule — see `CITABLE_TOPIC_KEYS`.

    RLS does the tenancy: the session is already scoped, so there is no `tenant_id`
    predicate here and there must not be one (hard rule 1 — a WHERE clause a caller can
    forget is not isolation).
    """
    if topic_key not in CITABLE_TOPIC_KEYS:
        raise _refuse(
            "kb_proposal_gap_not_citable",
            "That gap cannot be named in a suggestion",
            "A suggestion may only refer to a recognised topic, never to the wording of "
            "one caller's question.",
            "Ask for the knowledge to be suggested without referring to that gap.",
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
        raise _refuse(
            "kb_proposal_gap_unknown",
            "That gap is not open on this agent",
            "The knowledge gap this suggestion refers to is not open for this agent.",
            "Ask for the suggestion again from the agent's current gaps.",
            status=404,
        )


def _assert_may_curate(principal: Principal) -> None:
    """The tenant-and-actor half of the permission check.

    The PERMISSION itself is `requires(CURATE_PERMISSION)` on the route; this is the half
    that cannot be expressed there — a proposal is bound to a tenant and to a person, and
    a principal carrying neither cannot be either end of that binding. Restated in the
    service for the same reason `assert_proposable` runs twice: a function that is safe
    only because of its current caller is one call site away from not being.
    """
    if principal.tenant_id is None or principal.user_id is None:
        raise _refuse(
            "kb_proposal_no_actor",
            "This suggestion needs a client account",
            "Knowledge suggestions belong to a client account and to the person "
            "confirming them, and this request identifies neither.",
            "Open your client dashboard and try again.",
            status=403,
        )


# --- propose (READS ONLY) -----------------------------------------------------


async def build_proposal(
    session: AsyncSession,
    *,
    principal: Principal,
    agent_id: UUID,
    name: str,
    body: str,
    origin: ProposalOrigin,
    topic_key: str | None = None,
) -> tuple[KbProposal, str]:
    """Draft a knowledge entry and mint the token that could execute it. WRITES NOTHING.

    The reads are authorization reads and nothing else: the agent must be visible to this
    tenant's session (`assert_visible` — a foreign key is checked with row security
    bypassed, the mechanism `kb.service.submit_source` documents), and a cited gap must be
    open on it. Both refuse BEFORE a token exists, so a proposal that could never be
    confirmed is never handed to anybody.

    A `gap_digest` proposal MUST name its gap. That is not bookkeeping: the origin is a
    claim about provenance shown to the person approving it, and "your agent noticed this"
    with nothing to point at is a claim the system cannot support.
    """
    _assert_may_curate(principal)
    assert principal.tenant_id is not None
    assert principal.user_id is not None
    if origin == "gap_digest" and topic_key is None:
        raise _refuse(
            "kb_proposal_origin_needs_gap",
            "That suggestion is missing the gap it answers",
            "A suggestion presented as something the agent noticed must name the topic it noticed.",
            "Ask for the suggestion again from the agent's knowledge gaps.",
        )
    assert_proposable(name, body)
    await assert_visible(session, "agent", agent_id)
    if topic_key is not None:
        await _assert_citable_gap(session, topic_key=topic_key, agent_id=agent_id)
    proposal = KbProposal(
        nonce=uuid7().hex,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        agent_id=agent_id,
        name=name.strip(),
        body=body.strip(),
        origin=origin,
        topic_key=topic_key,
        expires_at=datetime.now(UTC) + timedelta(seconds=PROPOSAL_TTL_S),
    )
    return proposal, issue_token(proposal)


# --- confirm (the only mutation) ----------------------------------------------


async def confirm_proposal(
    session: AsyncSession,
    *,
    token: str,
    principal: Principal,
    ip: str | None = None,
) -> dict[str, Any]:
    """Execute a confirmed proposal through the ordinary KB submission path.

    THE ORDER IS THE SECURITY PROPERTY, and each step refuses before the next is possible:

    1. the principal can be an actor at all (`_assert_may_curate`; the PERMISSION is the
       route's `requires(CURATE_PERMISSION)`);
    2. the token is ours, intact and unexpired (`verify_token`);
    3. it was minted FOR THIS PERSON, IN THIS TENANT — a token is not a bearer credential
       here, it is a proposal addressed to somebody;
    4. the nonce is spent, once, before any row is written;
    5. the agent is still visible and the content still passes the guards — a token minted
       ten minutes ago describes a world that may have moved;
    6. `kb.service.submit_source` creates the `pending_approval` source and its chunks,
       and `write_audit` appends the record IN THE SAME TRANSACTION.

    Step 6 is the point of the whole design: it is the same function the form calls, with
    the same arguments, producing the same state. There is no second write path into
    `kb_sources` and no argument this module can pass that the form cannot — so every
    downstream guard (preview, approve, publish, drift sweep, deletion) applies unchanged,
    because none of them can tell the two apart except by the audit row.

    THE BURN COMES BEFORE THE WRITE, deliberately, and the failure mode is chosen. If the
    transaction then rolls back, the nonce is spent and the token is dead — the person
    asks again. The other ordering (write, then burn) makes a crash between them
    replayable, which is the failure this mechanism exists to prevent.

    THE SESSION IS THE CALLER'S TENANT SESSION, not a fresh one. `core/deps.db` IS a
    `tenant_session` — one transaction, RLS context set, commit on clean exit — so the KB
    row and its audit row commit together (`write_audit` is explicit that this is the
    point). Opening a second session inside the request would split them across two
    transactions and put a second connection behind the same advisory lock
    `submit_source` takes.
    """
    _assert_may_curate(principal)
    proposal = verify_token(token)
    if proposal.tenant_id != principal.tenant_id or proposal.actor_id != principal.user_id:
        # Refused as invalid rather than as forbidden: telling a caller "that token is
        # real but not yours" confirms the token is real, which is an oracle for whoever
        # took it. The operator gets the ids in the log line instead.
        log.warning(
            "kb_proposal_principal_mismatch",
            extra={
                "tenant_id": str(principal.tenant_id),
                "actor_id": str(principal.user_id),
            },
        )
        raise _invalid()
    await _burn(proposal.nonce)
    assert_proposable(proposal.name, proposal.body)
    await assert_visible(session, "agent", proposal.agent_id)
    created = await kb_service.submit_source(
        session,
        tenant_id=proposal.tenant_id,
        agent_id=proposal.agent_id,
        name=proposal.name,
        body=proposal.body,
        kind="text",
        submitted_by=proposal.actor_id,
    )
    await write_audit(
        session,
        action="kb.proposal.confirm",
        actor=principal,
        tenant_id=proposal.tenant_id,
        object_type="kb_source",
        object_id=str(created["id"]),
        ip=ip,
        # IDS, COUNTS AND CLOSED-SET STRINGS ONLY (hard rules 4 and 6). Not the title, not
        # the body: `audit_log` is append-only, so text written into it is text a DPDP
        # erasure cannot take back out. The `kb_sources` row is where the words live and
        # where deletion already reaches them. `actor_realm` is recorded because an
        # operator putting words into a client's agent's mouth is precisely the event an
        # investigator would go looking for (D-483's finding class), and `write_audit`'s
        # own `actor_type` is derived rather than declared.
        summary={
            "agent_id": str(proposal.agent_id),
            "version": created["version"],
            "chunks": created["chunks"],
            "status": created["status"],
            "origin": proposal.origin,
            "topic_key": proposal.topic_key,
            "actor_realm": principal.realm,
        },
    )
    return created


# --- the tool -----------------------------------------------------------------


def propose_knowledge_tool() -> dict[str, Any]:
    """THE tool definition, in the subset the vendor's own tooling preserves.

    Same shape discipline as `copilot/prompt.set_fields_tool`: `type`, `properties`,
    `required` naming every property, `additionalProperties: false` on every object, and
    no `pattern`/`minLength`/`format` — all length and content validation is
    `assert_proposable`, on our side, where it is testable. A function rather than a
    constant so mypy checks the shape and no request can mutate the dict a previous one
    sent.

    THE DESCRIPTION IS PART OF THE SAFETY ARGUMENT, and it is written for the failure mode
    that matters: a model that infers a business policy from a statistic and presents it
    as fact. It says the fact must come from the person, it forbids repeating a caller,
    and it says out loud that nothing is saved — a model that believes it has already
    written something will tell the user so.
    """
    return {
        "type": "function",
        "function": {
            "name": PROPOSE_KNOWLEDGE_TOOL_NAME,
            "description": (
                "Suggest a fact to add to this agent's knowledge. Only use this for "
                "something the person has just told you about their own business — never "
                "invent a price, a policy or an opening time, and never repeat something "
                "a caller said. Nothing is saved: the person must confirm the suggestion, "
                "and it then goes to review before the agent can use it."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "A short title for this knowledge, e.g. 'Saturday opening "
                            f"hours'. At most {MAX_NAME_CHARS} characters."
                        ),
                    },
                    "body": {
                        "type": "string",
                        "description": (
                            "What the agent should know, in the words the person used. "
                            "Write it the way you would tell a new receptionist. Do not "
                            "include phone numbers, email addresses or identity numbers."
                        ),
                    },
                    "topic_key": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": (
                            "The recognised knowledge-gap topic this answers, if it "
                            "answers one: " + ", ".join(sorted(CITABLE_TOPIC_KEYS)) + ". "
                            "Null when the person simply volunteered the fact."
                        ),
                    },
                },
                "required": ["name", "body", "topic_key"],
                "additionalProperties": False,
            },
        },
    }


#: What a registry needs from a tool, and nothing more.
ToolHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class WriteTool:
    """One model-callable tool that PROPOSES a mutation.

    Deliberately a plain record rather than a call into another package's registry: the
    copilot's tool registry is a sibling module, and reaching into it from here would make
    this lane's correctness depend on an import that points the wrong way. The parent
    wires it in one line — see `kb_write_tools`.
    """

    name: str
    definition: dict[str, Any]
    handler: ToolHandler


def kb_write_tools() -> tuple[WriteTool, ...]:
    """THE registration seam. Every KB write-back tool, for a registry to fold in.

    A tuple returned from a function rather than a mutation of somebody else's dict, so
    that registering is the caller's decision and importing this module has no side
    effect.
    """
    return (
        WriteTool(
            name=PROPOSE_KNOWLEDGE_TOOL_NAME,
            definition=propose_knowledge_tool(),
            handler=build_proposal,
        ),
    )


__all__ = [
    "CITABLE_TOPIC_KEYS",
    "CURATE_PERMISSION",
    "MAX_BODY_CHARS",
    "MAX_NAME_CHARS",
    "MIN_BODY_CHARS",
    "PROPOSAL_ORIGINS",
    "PROPOSAL_TTL_S",
    "PROPOSE_KNOWLEDGE_TOOL_NAME",
    "KbProposal",
    "ProposalOrigin",
    "WriteTool",
    "assert_proposable",
    "build_proposal",
    "confirm_proposal",
    "issue_token",
    "kb_write_tools",
    "propose_knowledge_tool",
    "verify_token",
]
