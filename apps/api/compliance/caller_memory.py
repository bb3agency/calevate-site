"""Whether an agent may remember its callers: the switch's gates, not the memory.

Caller memory is the engine's (D-973). `agents.caller_memory_enabled` publishes ThinnestAI
`voice.pastConversations` as `recap` or `fresh` (`engine/thinnest.py`), and the engine keeps
and forgets what earlier calls said. This module holds what decides whether the switch may
be on and whether it counts: the SPDI refusal (D-507(b)), the owner's versioned statement
(D-513, D-900, D-971), and `MEMORY_ON_SQL`, the one predicate every reader of the switch
uses.

Our own store of notes is retired (D-973): nothing writes or reads `caller_memories` or
`calls.caller_memory_state` any more. Rows written before then are still erased by DPDP
requests and expired on the `caller_memory` clock (`retrieval/caller_erasure.py`,
`workers/retention.py`) and exported with the subject's data (`compliance/export.py`), until
the follow-up migration drops both.
"""

from __future__ import annotations

from typing import Final

#: Verticals where a note about a caller is SENSITIVE PERSONAL DATA by construction, and
#: where cross-call memory is therefore refused however the agent's switch is set (D-507(b)).
#:
#: THE QUESTION WAS "IS 'ASKED ABOUT IVF PRICING' HEALTH DATA?" and the honest answer is
#: that it depends on who the business is, which no classifier over free text can be
#: trusted to decide — and being wrong is not recoverable. The SPDI Rules 2011 list is
#: EXHAUSTIVE and includes "physical, physiological and mental health condition" and
#: "medical records and history" (Rule 3), so a memory that a caller enquired about a
#: treatment is, on a clinic, an inference about exactly that.
#:
#: SPDI Rule 5(1) wants consent IN WRITING for collecting sensitive personal data. A phone
#: call cannot give one. So the refusal is not "until we word the notice better" — it is
#: until an instrument exists that a phone call can produce, which is not a code change.
#:
#: ⚠ REPORTED, NOT VERIFIED HERE: the SPDI Rules stand repealed by DPDP §44(2) on a date
#: reported as 13 May 2027 (18 months from the 13 Nov 2025 commencement gazette), which
#: would ALSO be when DPDP §§5-6 (notice and consent) first bind. `meity.gov.in` is
#: egress-blocked from this container, so that schedule comes from the search index of the
#: gazette PDF and from law-firm summaries, not from reading the notification. Whichever
#: regime governs on the day, this list is the conservative side of both, and re-reading
#: the gazette is what would let it shrink.
#:
#: A PROXY AND KNOWN TO BE ONE. `vertical_template` is the extraction schema a tenant
#: STARTED from, so a fertility clinic onboarded as `real_estate` is not caught by it. The
#: copy run's judged `health_business` (`tenancy/business_copy.Capabilities`) is the second
#: signal: it can only ADD a refusal, never lift one, so a clinic judged otherwise is still
#: refused. The per-tenant attestation below is the instrument on the enable path.
SPDI_REFUSED_VERTICALS: Final[frozenset[str]] = frozenset({"clinic"})


def spdi_refuses_memory(vertical_template: str | None, *, judged_health: bool | None) -> bool:
    """Does D-507(b) refuse cross-call memory for this tenant? Refused on a refused vertical
    template, or when the business is judged to give health care (`judged_health is True`);
    an unjudged business (None) is refused on its template alone.

    ONE PREDICATE, because there are two readers and they must not drift:
    `agents/publishing.set_caller_memory` refuses to switch memory on, and
    `compliance/caller_notice.py` decides whether the client's generated notice may tell
    their callers that the agents remember them. A notice describing processing the switch
    refuses is a false notice, which is the exact defect that module exists to avoid.

    The notice passes `judged_health=None`: the switch's own column, not this predicate,
    decides what the engine recalls (`MEMORY_ON_SQL`), so an agent switched on before its
    business was judged health still remembers callers, and a notice silenced by the
    judgement would hide processing that happens. The judgement refuses switching ON.

    `organizations.vertical_template` is NULLABLE (`tenancy/models.Organization`), and a
    tenant with none on file is NOT refused. The refusal is driven by a POSITIVE signal —
    "this business said it is a clinic" — and an absent column says nothing at all; a NULL
    read as a refusal would disable the feature for accounts created by a path that never
    asked, which is a different decision from the one D-507 took.
    """
    return vertical_template in SPDI_REFUSED_VERTICALS or judged_health is True


#: The sentence a client accepts to switch cross-call memory on, stored nowhere and
#: rendered by the API so the screen and the refusal cannot describe different promises.
#:
#: IT IS AN ATTESTATION AND NOT A CHECKBOX ON A FORM, which is why it is phrased as a
#: statement in the first person about facts only the client knows. It is the per-tenant
#: instrument `SPDI_REFUSED_VERTICALS` above says belongs on the enable path, and the proxy
#: stays above it as the belt: a clinic is refused whatever it attests, because the
#: vertical is a RECORD and an attestation is a CLAIM.
#:
#: VERSIONED like the outbound pledge: the account's row keeps the version it accepted
#: (`organizations.caller_memory_attestation_version`), and a published version is never
#: edited. Version 2 (founder, 27 Oct 2026): the memory sentence moved to the goodbye (D-865).
#: Version 3 (founder, 5 Nov 2026, D-971: "Drop it entirely"): nothing about memory is said on
#: calls, so the client's own written notice is how callers learn it, and the statement says
#: that is what the owner accepts.
CALLER_MEMORY_ATTESTATION_VERSION: Final = 3
CALLER_MEMORY_ATTESTATIONS: Final[dict[int, str]] = {
    1: (
        "I confirm that these calls do not collect health, medical, financial, biometric or "
        "other sensitive personal data about callers, that my business is the Data Fiduciary "
        "for these callers, and that my own privacy notice tells them we keep a short note of "
        "what they ask about. I understand that my agents will say so at the start of every "
        "call, that notes are kept for 180 days, and that a caller may ask for theirs to be "
        "erased."
    ),
    2: (
        "I confirm that these calls do not collect health, medical, financial, biometric or "
        "other sensitive personal data about callers, that my business is the Data Fiduciary "
        "for these callers, and that my own privacy notice tells them we keep a short note of "
        "what they ask about. I understand that my agents will say so before ending each "
        "call, that notes are kept for 180 days, and that a caller may ask for theirs to be "
        "erased."
    ),
    CALLER_MEMORY_ATTESTATION_VERSION: (
        "I confirm that these calls do not collect health, medical, financial, biometric or "
        "other sensitive personal data about callers, that my business is the Data Fiduciary "
        "for these callers, and that my own privacy notice tells them we keep a short note of "
        "what they ask about. I understand that my agents do not tell callers this on the "
        "call, so my own notice is how they learn it, that notes are kept for 180 days, and "
        "that a caller may ask for theirs to be erased."
    ),
}
CALLER_MEMORY_ATTESTATION: Final = CALLER_MEMORY_ATTESTATIONS[CALLER_MEMORY_ATTESTATION_VERSION]

#: AN ACCEPTANCE OF AN OLDER STATEMENT DOES NOT COVER WHAT AGENTS DO NOW (D-900, founder,
#: 27 Oct 2026). Until the owner accepts the current one, the account is treated exactly as
#: one that never accepted: no agent of it remembers callers (the engine is told to start
#: every call fresh), and switching memory on asks for the statement. The agents' own
#: switches are left as the owner set them, so accepting resumes memory on exactly those
#: agents with nothing to remember about which were on.
#:
#: Every reader that decides whether an agent remembers callers uses this fragment over
#: `agents a JOIN organizations o`, never `a.caller_memory_enabled` alone.
MEMORY_ON_SQL: Final = (
    "(a.caller_memory_enabled AND COALESCE(o.caller_memory_attestation_version, 0) >= "
    f"{CALLER_MEMORY_ATTESTATION_VERSION})"
)


def statement_is_current(version: int | None) -> bool:
    """Does an account that accepted statement `version` (None = never) cover memory now?"""
    return version is not None and version >= CALLER_MEMORY_ATTESTATION_VERSION


__all__ = [
    "CALLER_MEMORY_ATTESTATION",
    "CALLER_MEMORY_ATTESTATIONS",
    "CALLER_MEMORY_ATTESTATION_VERSION",
    "MEMORY_ON_SQL",
    "SPDI_REFUSED_VERTICALS",
    "spdi_refuses_memory",
    "statement_is_current",
]
