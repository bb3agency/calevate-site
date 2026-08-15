"""DPDP erasure/retention defects that are OPEN, recorded so they cannot be rediscovered.

Every entry below was found while taking one subject's data through erasure and retention
end to end, is real, and could not be closed from inside that slice — each one names the
specific reason and the specific act that closes it. Two are waiting on a person outside
this repository (a founder's commitment, counsel's reading of a regulation); one is
waiting on a two-step column deprecation that must not be started in the same change that
found it.

**THE ASSERTION IS AN EQUALITY**, in the shape `tests/reliability_known_gaps_test.py`
established. Each key has a probe that answers "is this still true?" and the test asserts
the set of still-open gaps EQUALS the recorded set. So an entry cannot outlive its defect
— fixing one turns this file red and forces the entry's deletion in the same change — and
a comment or a TODO, which can, is not an option.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

from apps.api.compliance.deletion import ERASURE_EXCEPTIONS, ERASURE_LIMITATIONS
from apps.workers import storage

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
    "archived_vendor_payloads_would_be_unerasable_if_anything_wrote_them": (
        "`storage.archive_payload` stores the RAW vendor payload — which carries the "
        "phone number and the transcript — under `engine-payloads/{engine}/{date}/"
        "{execution_id}.json`. That key names no tenant and no subject, so a DPDP erasure "
        "cannot enumerate it the way `_erase_delivery_bodies` enumerates a subject prefix, "
        "and no retention policy category reaches it either. Today nothing is at risk: "
        "the function has NO CALLER and `calls.engine_payload_ref` is never written, so "
        "the store is empty. It is recorded because it is a loaded gun — the next slice "
        "that wires the debug archive inherits an unerasable personal-data store and "
        "nothing would tell it so. CLOSED BY: either deleting `archive_payload`, "
        "`payload_key` and `calls.engine_payload_ref` in the two-step hard rule 8 requires "
        "(stop writing, then drop in a later release — and the column is already never "
        "written, so step one is done), or giving the key a `{tenant}/{call}` prefix and "
        "an arm in `_erase_recordings`' shape BEFORE a caller exists. Both are somebody's "
        "next hour; neither belongs in the change that found it, because the delete "
        "touches `infra/object-lifecycle/policy.json`'s prefix rule and the migration "
        "head is contended."
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


async def _payload_key_names_no_subject() -> bool:
    """The archived-payload key carries neither a tenant nor a call, so no erasure can
    enumerate it. Asked of the FUNCTION rather than of a source grep: what matters is the
    shape of the key it produces, not how the f-string happens to be written."""
    key = storage.payload_key(engine="fake", execution_id=str(uuid4()))
    tenant, call = str(uuid4()), str(uuid4())
    return tenant not in key and call not in key and "{" not in key


#: key → the probe that answers "is this gap still real?". Every probe is async so the
#: assertion below reads as one loop rather than as two kinds of entry.
PROBES: dict[str, Callable[[], Awaitable[bool]]] = {
    "recording_floor_cites_an_authority_that_may_not_impose_it": _floor_is_attributed_to_trai,
    "the_erasure_notice_does_not_mention_backups": _no_limitation_mentions_backups,
    "archived_vendor_payloads_would_be_unerasable_if_anything_wrote_them": (
        _payload_key_names_no_subject
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
