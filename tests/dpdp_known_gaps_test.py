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

from apps.api.compliance.deletion import ERASURE_EXCEPTIONS, ERASURE_LIMITATIONS

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
    "the_erasure_notice_does_not_mention_backups": (
        "Both backup chains retain 35 days (D-50), so for up to 35 days after a completed "
        "erasure the person's data still exists in a base backup, in the WAL segments and "
        "in the offsite dump — and a point-in-time restore un-erases anyone whose request "
        "completed after the recovery target. Every OTHER limitation of the erasure is "
        "disclosed on the certificate; this one is not, and the asymmetry is the defect: "
        "a data principal reading the register would reasonably conclude it is exhaustive. "
        "`runbooks/database-restore.md` already makes replaying erasures a mandatory "
        "restore step, so the operational half exists. CLOSED BY: the founder with "
        "counsel adding a backup clause to `ERASURE_LIMITATIONS`/`ERASURE_EXCEPTIONS` and "
        "to SECURITY-COMPLIANCE §4 in the same release — a sentence in a notice that "
        "clients hand to data principals is a commitment, not a code change, which is "
        "why §4 already records it as reserved."
    ),
}


async def _floor_is_attributed_to_trai() -> bool:
    """SECURITY-COMPLIANCE still names TRAI as the source of the recording floor."""
    text = SEC_COMP.read_text(encoding="utf-8")
    return "TRAI recording rule" in text and "90-day minimum retention" in text


async def _no_limitation_mentions_backups() -> bool:
    """Neither half of the register says a word about backups or restores."""
    said = " ".join(
        [*ERASURE_LIMITATIONS, *(f"{e.what} {e.why} {e.authority}" for e in ERASURE_EXCEPTIONS)]
    ).lower()
    return "backup" not in said and "restore" not in said


#: key → the probe that answers "is this gap still real?". Every probe is async so the
#: assertion below reads as one loop rather than as two kinds of entry.
PROBES: dict[str, Callable[[], Awaitable[bool]]] = {
    "recording_floor_cites_an_authority_that_may_not_impose_it": _floor_is_attributed_to_trai,
    "the_erasure_notice_does_not_mention_backups": _no_limitation_mentions_backups,
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
