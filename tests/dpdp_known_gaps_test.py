"""DPDP erasure/retention defects that are OPEN, recorded so they cannot be rediscovered.

Every entry below was found while taking one subject's data through erasure and retention
end to end, is real, and could not be closed from inside that slice — each one names the
specific reason and the specific act that closes it. Both are waiting on a person outside
this repository (a founder's commitment, counsel's reading of a regulation), which is the
only kind of entry that legitimately survives here: an engineering gap is closed in the
session that finds it or in the next one. The third entry — the archived vendor payloads
that no erasure could enumerate — was closed by code in D-126 and deleted, which is what
the equality below exists to force.

**THE ASSERTION IS AN EQUALITY**, in the shape `tests/reliability_known_gaps_test.py`
established. Each key has a probe that answers "is this still true?" and the test asserts
the set of still-open gaps EQUALS the recorded set. So an entry cannot outlive its defect
— fixing one turns this file red and forces the entry's deletion in the same change — and
a comment or a TODO, which can, is not an option.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEC_COMP = REPO_ROOT / "docs" / "SECURITY-COMPLIANCE.md"

#: Gap key → why it is open, and WHAT CLOSES IT. Delete an entry the moment its probe
#: below stops finding the defect; the equality assertion makes that mandatory.
KNOWN_OPEN_DPDP_GAPS: dict[str, str] = {
    "recording_floor_cites_an_authority_that_may_not_impose_it": (
        "The 90-day recording-retention floor is enforced in four places — a DB CHECK on "
        "`retention_policies`, `retention.RECORDING_FLOOR_DAYS`, "
        "`deletion.RECORDING_FLOOR_DAYS` and `infra/object-lifecycle` — and every one of "
        "them attributes it to TRAI (SECURITY-COMPLIANCE §1: 'TRAI recording rule … "
        "90-day minimum retention of call recordings'). The searches this slice could "
        "make do not support that attribution. TRAI's own 90-day figure in the TCCCPR "
        "framework is the OPT-OUT COOLING PERIOD — a sender may not seek fresh consent "
        "from someone who opted out for 90 days — which is a rule about consent, not "
        "about keeping audio. The two-year archive of commercial records, CDR, EDR and "
        "IPDR is Unified Licence clause 39.20 (amended December 2021), and it binds "
        "LICENSEES, i.e. telecom service providers; Calevate is a telemarketer and not a "
        "licensee. Sectoral floors that DO reach recordings (RBI ~2 years, IRDAI ~6 "
        "months) are the client's obligation and vary by client, which is what "
        "SECURITY-COMPLIANCE §1's 'BFSI clients configurable ≥ regulator minimum' row is "
        "for.\n"
        "This is not urgent in the dangerous direction: the floor errs towards KEEPING "
        "data, so no recording is destroyed too early. It errs in the other one — "
        "retaining personal data with no legal basis is the DPDP §8(7) storage-limitation "
        "breach, and 'because TRAI says so' is not a defence a regulator can be given if "
        "TRAI does not. CLOSED BY: the founder, with counsel, confirming or replacing the "
        "authority for the number, after which the floor is one constant changed in the "
        "four places named above plus a migration for the CHECK. Not this slice's: "
        "SECURITY-COMPLIANCE §1 is outside its writable set, and the floor is a term in "
        "the client DPA rather than an implementation detail."
    ),
    "subject_erasure_is_keyed_on_digits_and_cannot_reach_a_name": (
        "The \u00a712 erasure finds a data principal BY THEIR NUMBER and by nothing else. "
        "`deletion_requests` cannot even be filed without one (CHECK "
        "`open_request_names_its_subject`), and every free-text arm matches the last ten "
        "DIGITS of it \u2014 `_KB_SUBJECT_MATCH_SQL`, `_COPILOT_TURN_SUBJECT_SQL` and "
        "`_OUTBOX_SUBJECT_SQL` all strip both sides to digits with the same "
        "`regexp_replace(..., '[^0-9]', '', 'g')`.\n"
        "So a record that named the person by NAME is unreachable by any predicate the "
        "erasure has. `copilot/transcript.py` and `copilot/memory.py` state the same limit "
        "from the other end: `redact()` recognises IDENTIFIERS (phone, email, Aadhaar, "
        "PAN, card, OTP, UPI) and not PROPER NOUNS, so a staff member who types "
        "\u201cwhat did Lakshmi\u2019s enquiry say\u201d leaves a first name in a row this "
        "erasure walks straight past. It is not the assistant's limit: it is a property of "
        "the KEY, so it holds for the knowledge-base search and the outbox arm too.\n"
        "It is bounded rather than open-ended, which is why it is a disclosed limitation "
        "and not an incident. Three things reach such a row without matching a name \u2014 "
        "the copilot's own session-run clearing, the `transcript` retention clock, and "
        "tenant offboarding, which DELETEs every row unconditionally \u2014 and the columns "
        "in question are redacted on write, so what survives is a sentence with a name in "
        "it and no identifier beside it. It IS disclosed to the data principal: "
        "`deletion.ERASURE_LIMITATIONS` carries the general entry (keyword 'by name') "
        "beside the assistant-specific one (keyword 'assistant'), so the certificate says "
        "it out loud rather than leaving a reader to infer it.\n"
        "CLOSED BY: a decision that is not ours to take. Erasing by NAME means matching a "
        "proper noun against free text, which produces false positives that destroy OTHER "
        "people's records \u2014 a caller called Lakshmi asking to be erased would take "
        "every other Lakshmi's conversation with her \u2014 so it needs a verification "
        "standard for what counts as this person's record and an accepted false-positive "
        "rate. Both are the founder's, with counsel, and both are DPA terms rather than "
        "engineering defaults. Once given, the mechanism is cheap: one more identifier "
        "column on `deletion_requests`, one predicate per free-text arm, and a narrowed "
        "sentence in the two registers this entry names."
    ),
    "uploaded_campaign_contacts_have_no_retention_clock": (
        "The ERASURE half of P3.1 is closed in code: `_erase_campaign_contacts` reaches "
        "`campaign_contacts` from both the per-subject and the tenant-wide path, "
        "anonymizes the number, clears the name, the pasted CSV columns and the "
        "(unsalted, trivially reversible) dedupe hash, sets the row to `dnc_blocked` so "
        "no campaign can dial someone whose certificate says they were removed, and puts "
        "the count on both certificates.\n"
        "What is NOT closed is the CLOCK. `retention_policies.data_category` is "
        "CHECK-constrained to ('recording','transcript','lead','consent_log') in "
        "migration 05bba2f3c19c, so there is no category an uploaded contact list can be "
        "swept under — a client who pastes 5,000 numbers into a campaign has those "
        "numbers held indefinitely, in full, unless a data principal happens to ask. That "
        "is a DPDP §8(7) storage-limitation exposure and it is currently undisclosed. It "
        "errs in the dangerous direction (retaining, not destroying), unlike the recording "
        "floor above. CLOSED BY: the founder deciding the period a client's own uploaded "
        "contact list is kept for — it is a DPA commitment to the client, not an "
        "engineering default we may pick — after which it is one migration widening the "
        "CHECK, one `data_category` in the seed's retention defaults, one arm in "
        "`sweep_tenant`, and a row in SECURITY-COMPLIANCE §1's retention table. The shape "
        "is the KB reservation's exactly: the mechanism is cheap and the NUMBER is "
        "somebody else's to give."
    ),
}


async def _floor_is_attributed_to_trai() -> bool:
    """SECURITY-COMPLIANCE still names TRAI as the source of the recording floor."""
    text = SEC_COMP.read_text(encoding="utf-8")
    return "TRAI recording rule" in text and "90-day minimum retention" in text


async def _no_retention_category_reaches_campaign_contacts() -> bool:
    """The CHECK constraint still admits no category an uploaded contact list fits.

    Read off the live database rather than off the migration file, because the migration
    is the history and the constraint is the fact — and because widening it is exactly
    what closes this gap, so the probe has to watch the thing that changes.
    """
    from apps.api.db.session import untenanted_session
    from sqlalchemy import text as sql

    async with untenanted_session() as session:
        definition = (
            await session.execute(
                sql(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_retention_policies_category_enum'"
                )
            )
        ).scalar()
    # No constraint at all would ALSO mean the gap is closed differently — and would be a
    # bigger change than this probe should quietly pass, so it reads as still-open and
    # whoever removed it has to come here and say what they did.
    return definition is None or "campaign_contact" not in str(definition)


async def _subject_erasure_is_keyed_on_digits() -> bool:
    """The erasure still finds a person by their number and by nothing else.

    TWO HALVES, because closing this gap could start at either end and an entry watching
    only one of them would outlive its defect at the other. The SCHEMA half asks whether an
    open request can still name nothing but a phone number; the PREDICATE half asks whether
    the free-text arms are still digit matchers. The predicates are read off the IMPORTED
    MODULE rather than off the file's text, so reformatting, a moved comment or a rewritten
    docstring cannot flip this probe \u2014 only the SQL can.
    """
    from apps.api.db.session import untenanted_session
    from apps.workers import retention
    from sqlalchemy import text as sql

    predicates = (
        retention._KB_SUBJECT_MATCH_SQL,
        retention._COPILOT_TURN_SUBJECT_SQL,
        retention._OUTBOX_SUBJECT_SQL,
    )
    if not all("regexp_replace" in one and "[^0-9]" in one for one in predicates):
        return False

    async with untenanted_session() as session:
        definition = (
            await session.execute(
                sql(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = "
                    "'ck_deletion_requests_open_request_names_its_subject'"
                )
            )
        ).scalar()
    # A dropped constraint reads as STILL OPEN rather than as closed, for the campaign
    # probe's reason one function up: removing it is a bigger change than this file should
    # quietly pass, and whoever removed it has to come here and say what replaced it.
    return definition is None or "phone_e164" in str(definition)


#: key → the probe that answers "is this gap still real?". Every probe is async so the
#: assertion below reads as one loop rather than as two kinds of entry.
PROBES: dict[str, Callable[[], Awaitable[bool]]] = {
    "subject_erasure_is_keyed_on_digits_and_cannot_reach_a_name": (
        _subject_erasure_is_keyed_on_digits
    ),
    "recording_floor_cites_an_authority_that_may_not_impose_it": _floor_is_attributed_to_trai,
    "uploaded_campaign_contacts_have_no_retention_clock": (
        _no_retention_category_reaches_campaign_contacts
    ),
}


async def test_every_recorded_gap_is_still_open_and_no_other_is() -> None:
    """The equality. Fixing a gap fails here until its entry is deleted; recording a gap
    that is not real fails here immediately."""
    still_open = {key for key, probe in PROBES.items() if await probe()}

    assert set(PROBES) == set(KNOWN_OPEN_DPDP_GAPS), (
        "every recorded gap needs a probe, or the equality below cannot close it"
    )
    assert still_open == set(KNOWN_OPEN_DPDP_GAPS), (
        "the recorded DPDP gaps and the real ones disagree.\n"
        f"  fixed but still recorded: {sorted(set(KNOWN_OPEN_DPDP_GAPS) - still_open)}\n"
        f"  open but not recorded:    {sorted(still_open - set(KNOWN_OPEN_DPDP_GAPS))}"
    )


def test_every_gap_says_what_closes_it() -> None:
    """A recorded gap with no named remedy is a TODO wearing a test's clothes."""
    silent = [key for key, why in KNOWN_OPEN_DPDP_GAPS.items() if "CLOSED BY" not in why]
    assert silent == [], f"these entries do not say what would close them: {silent}"
