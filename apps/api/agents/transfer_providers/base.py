"""What it takes to put a live caller through to a person, in OUR vocabulary.

D-533 built the roster — who takes the call, and who is on duty at this instant. This
package is the other half: the MECHANISM that makes the handover happen, on an engine we
run ourselves, where no vendor supplies one.

THE SHAPE OF A HANDOVER, DECIDED HERE AND NOT BY A CARRIER
-----------------------------------------------------------
**Whisper, then accept, then bridge** (founder, 21 Sep 2026):

1. a second leg is placed to the roster member's number, presenting a header that is
   OURS to present;
2. before either party can hear the other, that person hears a short private message
   naming who is calling and why, and is asked to ACCEPT;
3. accepted -> the two legs are bridged. Declined, never answered, busy, or answered and
   not accepted in time -> the leg is torn down and the OUTCOME COMES BACK, so the agent
   can tell the caller the truth and book the call-back that already exists.

The reason for step 2 is the failure it removes: an unanswered transfer is worse than no
transfer, because the caller has already been told "putting you through" and then gets
silence or somebody's voicemail greeting. Accept-before-bridge makes that state
unreachable — a leg nobody accepted never becomes the caller's problem.

WHAT IS DELIBERATELY NOT IN THIS VOCABULARY
--------------------------------------------
* **WHEN to hand over.** That is the client's own call script and their trigger wording
  (`agents/handoff.HANDOFF_TRIGGER_DEFAULT` is only what an agent gets when they write
  nothing). Nothing here encodes a circumstance, a vertical or an industry: a clinic, a
  dealership, a coaching centre and a law office each have their own answer and the agent
  is what decides it turn by turn.
* **What the destination IS.** `TransferRequest.to_e164` is data. A mobile, a landline and
  a desk endpoint are all E.164 to this seam, and no adapter may assume otherwise.
* **The caller's own number as the presented header.** `present_as` is separate from the
  caller for exactly that reason — see its field comment.

WHY A PROTOCOL AND A REGISTRY RATHER THAN ONE CARRIER'S CLIENT
---------------------------------------------------------------
`compliance/kyc_providers/` makes this argument in full and it carries over unchanged:
the cost of the seam is one package, the cost of not having it is that a carrier's field
names reach the tool endpoint, the attempt row and eventually a column. It applies with
more force here, because WHICH carrier this product ends up on is open: D-05 picks
"Vobiz/Exotel" for telephony (`docs/ROADMAP.md:348`) while the answer document is written
for Plivo, and `apps/voice-runtime/carrier_routes.py` records the same open question for
the same reason. A seam that answered only for Plivo would be thrown away with Plivo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol, runtime_checkable

from calevate_shared.engine import E164

#: The names this seam knows: one carrier and the in-house adapter. `registry` may only map
#: an engine onto a member, so a carrier added to that map without an adapter is a refusal
#: at the gate rather than an AttributeError on a live call.
TRANSFER_PROVIDERS: Final[tuple[str, ...]] = ("plivo", "fake")

#: HOW A HANDOVER ENDED, in our words rather than any carrier's.
#:
#: The four unsuccessful endings are kept APART even though all four end the same way for
#: the caller (a truthful sentence and a call-back), because they do not end the same way
#: for the CLIENT: `declined` is a person who saw the call and said no, `busy` is a person
#: on another call, `unanswered` is a phone nobody picked up, and `whisper_timeout` is a
#: person who answered, heard who was calling, and then neither accepted nor hung up.
#: Collapsing them would leave a client with "nobody took it" and no idea which of the
#: four to act on.
TransferOutcome = Literal["bridged", "declined", "busy", "unanswered", "whisper_timeout", "failed"]

#: Our endings mapped onto `agents/models.HANDOFF_OUTCOMES`, the vocabulary the
#: `handoff_attempts` CHECK already froze and every client screen already renders.
#:
#: Declared here rather than at the write site so that a member added to `TransferOutcome`
#: without a stored meaning is a KeyError in one place instead of a row that violates a
#: CHECK on a live call. `failed` is `unknown` and not `unreached`: "we could not place
#: the leg" is not evidence that the person would not have answered.
HANDOFF_OUTCOME_OF: Final[dict[str, str]] = {
    "bridged": "connected",
    "declined": "unreached",
    "busy": "unreached",
    "unanswered": "unreached",
    "whisper_timeout": "unreached",
    "failed": "unknown",
}


@dataclass(frozen=True, slots=True)
class TransferRequest:
    """One handover, fully specified, with nothing left for an adapter to decide."""

    #: The carrier's own handle for the leg the CALLER is on. Opaque to everything above
    #: the adapter: it is passed through from the engine's call id and never parsed here.
    call_ref: str
    #: Where the second leg goes — the roster member's number, as the client typed it.
    to_e164: E164
    #: THE HEADER THE SECOND LEG PRESENTS, AND IT IS NEVER THE CALLER'S NUMBER.
    #:
    #: Presenting a number we are not the subscriber of is CLI spoofing, and this
    #: product's whole regulatory position — 140/160 series, DLT registration, PE/TM — is
    #: built on who the subscriber of a presented number is. So the second leg presents a
    #: number the client holds and has registered (`agents/service.resolve_caller_id`),
    #: and the caller's identity travels in the whisper, which is a private message to one
    #: person rather than a claim to the network.
    present_as: E164
    #: The exact words the person hears before they accept. Composed by us
    #: (`agents/handoff_execution.compose_whisper`) so the sentence a client is SHOWN and
    #: the sentence their staff HEAR cannot come to differ, and so no adapter is ever in
    #: the position of writing product copy.
    whisper: str
    #: How the person signals acceptance. A keypress because it is the one input that
    #: cannot be produced by a voicemail greeting, an answering machine or a ringback
    #: tone — the three things step 2 exists to tell apart from a human being.
    accept_key: str
    #: How long the destination may ring before the leg is torn down, and how long after
    #: the whisper the person has to accept. Both bounded here rather than left to a
    #: carrier default, because both are time the CALLER spends holding.
    ring_timeout_s: int
    whisper_timeout_s: int


@dataclass(frozen=True, slots=True)
class TransferStarted:
    """What an adapter knows the moment the carrier has accepted the request.

    `outcome` is `None` when the ending is not yet known — the ordinary case for a carrier,
    which reports it later over its own callback. It is filled when the adapter drove the
    whole cycle itself and there is nothing to wait for.

    `bridged_seconds` is the SECOND LEG'S billable duration, and it is on this object
    because it is the only place it can be true: the leg is charged by the carrier for as
    long as it is up, and a handover that bills nothing is a cost class this product
    carries silently. Where it has to be metered is named in `handoff_execution`.
    """

    provider_ref: str
    outcome: TransferOutcome | None = None
    bridged_seconds: int | None = None
    #: The carrier's own word for the ending. Stored for an operator, never spoken and
    #: never mapped — `TransferOutcome` is what anything downstream reads.
    raw_status: str | None = None


class TransferContractUnverifiedError(RuntimeError):
    """This adapter's carrier contract has not been read from the carrier's own docs.

    Raised rather than guessed. An invented transfer grammar does not fail safely: it
    produces a request the carrier rejects, or worse accepts differently, while a caller
    has already been told to hold. `registry.available_transfer()` is what keeps this from
    being reachable at runtime; the exception is the backstop for a deployment that
    selects one anyway.
    """


class TransferRefusedError(RuntimeError):
    """The carrier accepted the request and would not place the leg.

    Distinct from `TransferContractUnverifiedError` because the remedies are opposite: one
    is a document nobody has read, the other is a live account, a balance or a number. The
    caller hears the same truthful sentence either way; the operator does not.
    """


@runtime_checkable
class CallTransferProvider(Protocol):
    """One carrier's ability to whisper, accept and bridge, behind our vocabulary."""

    @property
    def name(self) -> str:
        """The member of `TRANSFER_PROVIDERS` this adapter is."""

    @property
    def contract_verified(self) -> bool:
        """Has this adapter's carrier contract been read from the carrier's own docs?

        A PROPERTY OF THE ADAPTER and not of the registry, for `kyc_providers.base`'s
        reason: constructing an adapter cannot fail for an unread contract — a class with
        unwritten methods instantiates perfectly well — so a registry that only caught
        construction errors would hand back an object that fails on its first live call,
        which here means mid-conversation.
        """

    @property
    def settles_synchronously(self) -> bool:
        """Does `start_transfer` come back knowing how the handover ENDED?

        THE QUESTION IS ABOUT THE CALLER'S OWN AGENT, WHICH IS HOLDING A TURN OPEN. The
        whisper-and-accept cycle can take the better part of a minute, and a carrier that
        acknowledges the request and reports the ending later over its own callback leaves
        the agent with nothing to say for that whole time. A caller who has been asked to
        hold and then hears an apology — or nothing — is the failure this pattern exists
        to remove, so `place_handoff` refuses to place through such an adapter on a path
        that has to answer now, and says which of the two it was.

        An adapter whose contract is unread answers False: that is fail-closed on an
        unknown, not a claim about what the carrier can do.
        """

    async def start_transfer(self, request: TransferRequest) -> TransferStarted:
        """Place the second leg, whisper, and bridge on acceptance.

        ONE METHOD AND NOT THREE. Splitting it into dial/whisper/bridge would be this
        seam deciding the carrier's control flow: a carrier that expresses the whole
        pattern in one request and one that needs three would then have to be wrapped
        differently above the adapter, which is precisely what the adapter is for.
        """


__all__ = [
    "HANDOFF_OUTCOME_OF",
    "TRANSFER_PROVIDERS",
    "CallTransferProvider",
    "TransferContractUnverifiedError",
    "TransferOutcome",
    "TransferRefusedError",
    "TransferRequest",
    "TransferStarted",
]
