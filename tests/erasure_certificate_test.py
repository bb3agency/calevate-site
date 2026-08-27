"""The erasure CERTIFICATE — the artifact, tested apart from the surface that serves it.

`tests/deletion_request_test.py` proves the HTTP surface. These prove the document it
hands over, because that document outlives the request that produced it: it gets filed,
forwarded to a regulator, and read years later by someone who cannot ask us what it
meant. A certificate that overstates what was erased is worse than one that admits a
limitation, because the person relying on it cannot tell.

Three claims, none of which needs a database:

1. The certificate states what was NOT erased, and why — the TRAI 90-day recording floor
   in particular (SECURITY-COMPLIANCE §1 against §4).
2. It survives a stored proof written by a different version of the worker. The proof is
   durable; the code that renders it is not, and a status read must not 500 because a
   worker learned to record one more fact.
3. The prose notice and the structured exceptions are one register, not two that drift.

The floor COUNT is the coordinated half, and both sides have now landed:
`apps/workers/retention.execute_deletion_request` writes
`scope.recordings_within_trai_floor` into the stored proof, and the certificate reports
it. What these tests hold onto is the distinction that outlives the change — a recorded
`0` says "none were inside the window", an ABSENT key says "this proof predates the
count" — because proofs written before it are not back-filled (hard rule 4) and will be
read for years. `tests/deletion_request_test.py` covers the live worker's count end to
end; the fixtures here are hand-built precisely so both states stay testable after only
one of them can still occur in new rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.api.compliance import deletion
from apps.api.compliance.deletion import (
    ERASURE_EXCEPTIONS,
    ERASURE_LIMITATIONS,
    FLOOR_COUNT_KEY,
    RECORDING_FLOOR_DAYS,
)
from apps.api.compliance.deletion_proof import certificate, notice_version
from apps.api.compliance.deletion_routes import ErasureProofOut
from apps.api.compliance.export import subject_ref
from apps.workers import retention

PHONE = "+919876543210"


def _stored(**overrides: Any) -> dict[str, Any]:
    """A stored proof exactly as `execute_deletion_request` writes it TODAY.

    Written out rather than imported so that a change to the worker's shape shows up
    here as a deliberate edit instead of being absorbed silently.
    """
    proof: dict[str, Any] = {
        "subject_hash": subject_ref(PHONE),
        "executed_at": "2026-08-11T09:30:00+00:00",
        "scope": {
            "calls": ["a" * 32],
            "leads": ["b" * 32],
            "transcript_turns_erased": 4,
            "call_extractions_erased": 1,
        },
        "actions": {
            "calls": "phone numbers, recording pointer and summary cleared",
            "transcript_turns": "text and text_redacted replaced",
        },
        "engine_deletion": "unconfirmed_pending_vendor_api",
    }
    proof.update(overrides)
    return proof


def _certified(**overrides: Any) -> dict[str, Any]:
    document = certificate(_stored(**overrides))
    assert document is not None
    # Everything the certificate builds must survive the response model that ships it —
    # `ErasureProofOut` is `extra="forbid"`, so an unmodelled key is a 500 on a status
    # read rather than a field nobody notices.
    ErasureProofOut(**document)
    return document


def _recording_entry(document: dict[str, Any]) -> dict[str, Any]:
    entries = [e for e in document["not_erased"] if "recording" in e["what"].lower()]
    assert len(entries) == 1, "exactly one entry speaks for the recording audio"
    entry: dict[str, Any] = entries[0]
    return entry


# ---------------------------------------------------------------- 1. what it admits


def test_the_certificate_says_which_audio_survived_the_pointer_it_cleared() -> None:
    """THE gap, now narrowed to the only recordings it still applies to.

    The worker clears `calls.recording_url` — the POINTER — at any age. It now also
    DESTROYS the bytes of every recording past the retention floor (`_erase_recordings`),
    so the certificate's exception is no longer "the audio survives" but "the audio still
    inside its mandatory retention period survives, and here is when it goes". The test
    holds the notice to that narrower, stronger claim: it must still name the floor and
    both sections, and it must still leave a non-engineer in no doubt that some audio may
    exist right now.
    """
    document = _certified()

    # What was cleared, said plainly.
    assert any("recording" in line.lower() for line in document["erased"]), (
        "the certificate must still say the pointer went — this is not a retreat"
    )

    entry = _recording_entry(document)
    assert entry["outcome"] == "retained_under_legal_floor"
    prose = f"{entry['why']} {entry['authority']}".lower()
    assert str(RECORDING_FLOOR_DAYS) in prose
    # A SOURCE THE READER CAN ACTUALLY OPEN. This asked for "security-compliance §4",
    # which is an internal blueprint document: the certificate is rendered on the
    # client's own data-rights screen and handed on to a data principal, and naming a
    # file they have no copy of makes the citation unverifiable — the opposite of what
    # `authority` is for. The data-processing agreement is published (`lib/legal/dpa.ts`
    # §8) and states this same floor, so it is the citation that can be checked.
    assert "data-processing agreement" in prose, (
        "a reader with no access to this codebase needs a source they can open"
    )
    assert "security-compliance" not in prose, "an internal document is not a citation"
    # AND THE FLOOR IS OURS, SAID IN THE CERTIFICATE ITSELF. This used to require
    # "SECURITY-COMPLIANCE §1", which is the section that attributes the 90 days to TRAI
    # — and the certificate said, to a data principal, that the period was one "Indian
    # telecom rules require". No primary source for that rule has ever been produced;
    # SEC-COMP §4 records that TRAI's 90-day figure is the opt-out cooling period and
    # that the two-year commercial-records archive is Unified Licence clause 39.20,
    # binding LICENSEES and not a telemarketer. Claiming a legal basis we cannot cite is
    # not the conservative error: DPDP §8(7) makes retention on a non-existent basis the
    # breach. So the certificate now says whose floor it is, and this asserts BOTH
    # directions — the true statement present, the false one gone.
    assert "calevate's own" in prose or "platform" in prose, (
        "the certificate must say the floor is Calevate's policy, not a statute's"
    )
    assert "indian telecom rules require" not in prose, (
        "a legal basis nobody can cite may not be asserted to a data principal"
    )
    # The authority for DEFERRING rather than refusing, cited where it is relied on.
    assert "dpdp §12(3)" in prose and "§8(7)" in prose, (
        "a deferral is only lawful because the statute says retention necessary for "
        "compliance with a law is the exception — cite it, do not assert it"
    )
    # The actionable half: a non-engineer must come away knowing the audio may exist.
    assert "still" in entry["why"].lower() or "not destroyed early" in entry["why"].lower()


def test_the_certificate_does_not_claim_a_lifecycle_rule_deletes_the_audio() -> None:
    """SECURITY-COMPLIANCE §4 records that the object-store lifecycle rule is a
    bucket-wide growth CEILING (2555 days for `recordings/`), not a per-tenant retention
    mechanism — "no per-tenant mechanism deletes recording bytes". A certificate that
    tells a data principal the audio is removed at 90 days by a lifecycle rule is
    describing a mechanism nobody has built.
    """
    entry = _recording_entry(_certified())
    said = f"{entry['why']} {entry['authority']}".lower()
    assert "lifecycle" not in said, (
        "the certificate must not hand the subject a deletion mechanism that does not "
        "exist per tenant (SECURITY-COMPLIANCE §4)"
    )
    notice = " ".join(ERASURE_LIMITATIONS).lower()
    assert "removed by the object-store lifecycle rule" not in notice


def test_the_certificate_admits_the_consent_ledger_keeps_the_number_itself() -> None:
    """`consent_ledger.phone_e164` is NOT NULL and the erasure does not touch it (hard
    rule 4 — it is an append-only ledger). So the number itself survives an erasure
    there. Saying only "the evidence, not the personal data" reads as "nothing about
    the person remains", which is not true of that table."""
    entries = [e for e in _certified()["not_erased"] if "consent" in e["what"].lower()]
    assert len(entries) == 1
    assert "number" in entries[0]["why"].lower()
    assert entries[0]["outcome"] == "retained_as_evidence"


def test_an_erasure_that_matched_nothing_still_states_its_limitations() -> None:
    """The empty case is the one most likely to be filed as "we hold nothing about you",
    and it is exactly where an unqualified answer misleads: the consent ledger and any
    recording still exist regardless of whether calls/leads matched."""
    document = _certified(
        scope={
            "calls": [],
            "leads": [],
            "transcript_turns_erased": 0,
            "call_extractions_erased": 0,
        }
    )
    assert document["erased"] == [
        "No call record held this number.",
        "No CRM lead held this number.",
    ]
    assert len(document["not_erased"]) == len(ERASURE_EXCEPTIONS)


def test_the_filed_certificate_is_readable_without_the_response_around_it() -> None:
    """`limitations` rides the response envelope, and the envelope is not what gets
    filed — the proof is. Carrying the same notice inside the document is what makes the
    artifact self-contained a year later, and pinning them equal is what stops the two
    from drifting into saying different things."""
    document = _certified()
    assert document["limitations"] == list(ERASURE_LIMITATIONS)
    filed = json.dumps(document, ensure_ascii=False).lower()
    assert "data-processing agreement" in filed
    assert "security-compliance" not in filed, "an internal document is not a citation"
    assert "indian telecom rules require" not in filed
    assert str(RECORDING_FLOOR_DAYS) in filed


# ------------------------------------------------------- 2. the floor count handshake


def test_the_certificate_does_not_invent_a_count_it_was_never_given() -> None:
    """A proof written before the job recorded the count — the fixture omits the key.

    Those rows are not back-filled (hard rule 4), so this is a document that will still
    be rendered and read years from now. It has to say the number is not recorded rather
    than imply zero: "0 recordings were inside the floor" is a claim, and a proof that
    never carried the field cannot support it.
    """
    document = _certified()
    assert document["scope"][FLOOR_COUNT_KEY] is None
    entry = _recording_entry(document)
    assert entry["count"] is None
    assert "does not state how many" in entry["why"]


def test_a_recorded_count_is_reported_as_the_number_it_is() -> None:
    """The other half, now that the job stores it: a recorded count is stated, and a
    recorded ZERO says "none were" rather than falling back to the "not recorded"
    wording. The two are different claims and the certificate must not blur them."""
    document = _certified(
        scope={
            "calls": ["a" * 32, "c" * 32],
            "leads": [],
            "transcript_turns_erased": 0,
            "call_extractions_erased": 0,
            FLOOR_COUNT_KEY: 2,
        }
    )
    assert document["scope"][FLOOR_COUNT_KEY] == 2
    entry = _recording_entry(document)
    assert entry["count"] == 2
    assert "2 of those recordings" in entry["why"]
    assert "does not state how many" not in entry["why"]

    none = _certified(
        scope={
            "calls": ["a" * 32],
            "leads": [],
            "transcript_turns_erased": 0,
            "call_extractions_erased": 0,
            FLOOR_COUNT_KEY: 0,
        }
    )
    assert _recording_entry(none)["count"] == 0
    assert "None of those recordings" in _recording_entry(none)["why"]


def test_the_floor_the_certificate_quotes_is_the_floor_the_worker_enforces() -> None:
    """Duplicated rather than imported (the API must not pull the worker module in to
    print a number), so the two are pinned together here — the same arrangement
    `tests/object_lifecycle_test.py` makes for the infra copy."""
    assert RECORDING_FLOOR_DAYS == retention.RECORDING_FLOOR_DAYS


# -------------------------------------------------- 3. it survives its own durability


def test_a_stored_proof_from_another_worker_version_still_renders() -> None:
    """The stored proof is durable and the renderer is not. A proof that gained a key
    the API has never heard of must still produce a certificate: `ErasureProofOut` is
    `extra="forbid"`, so splatting the stored document into it is a status read that
    500s on the one endpoint whose subject is a person who asked to be erased.
    """
    document = _certified(
        engine_deletion="confirmed_by_vendor",
        something_a_later_worker_added={"nested": True},
        scope={
            "calls": [],
            "leads": [],
            "transcript_turns_erased": 0,
            "call_extractions_erased": 0,
            "a_scope_key_from_the_future": "ignored",
        },
    )
    assert document["engine_deletion"] == "confirmed_by_vendor"
    assert "something_a_later_worker_added" not in document
    assert "a_scope_key_from_the_future" not in document["scope"]


def test_a_proof_with_no_counts_at_all_claims_only_what_it_can() -> None:
    """Where "absent is not zero" bites, and where it does not.

    The four erasure counts are typed `int` and read as zero, which is safe because the
    sentences beside them say "No call record held this number" rather than implying a
    count was taken and came back empty. The FLOOR count is the one that must not
    collapse: zero there is the claim "no recording was inside the 90-day window", and a
    field the proof never carried cannot support it.
    """
    document = _certified(scope={})
    assert document["scope"]["transcript_turns_erased"] == 0
    assert document["erased"] == [
        "No call record held this number.",
        "No CRM lead held this number.",
    ]
    assert document["scope"][FLOOR_COUNT_KEY] is None
    assert "does not state how many" in _recording_entry(document)["why"]


def test_certifying_the_same_stored_proof_twice_gives_the_same_document() -> None:
    """Hard rule 4: a correction is a NEW entry, never an edit. Two readers of one
    stored proof must get byte-identical certificates, or "which copy is authoritative?"
    has no answer — and the version below is how a copy rendered against a later notice
    is told apart from one rendered against this one."""
    assert certificate(_stored()) == certificate(_stored())


def test_no_certificate_carries_the_subjects_number() -> None:
    """Hard rule 6, at the artifact rather than the response: the certificate names its
    subject by the same one-way hash the subject-access export files under, so an
    auditor can line an access request up against an erasure — and by nothing else."""
    document = _certified()
    assert document["subject_hash"] == subject_ref(PHONE)
    filed = json.dumps(document)
    assert PHONE not in filed and PHONE.lstrip("+") not in filed
    assert PHONE.lstrip("+")[-10:] not in filed


def test_the_notice_version_is_derived_from_the_notice_itself() -> None:
    """A certificate filed today and one rendered after the notice is rewritten are two
    different statements about the same erasure. Hard rule 4 says the second is a new
    entry rather than a correction of the first — which only helps a reader who can tell
    them apart, so the document carries a version derived from the text it quotes."""
    document = _certified()
    assert document["limitations_version"] == notice_version(
        ERASURE_LIMITATIONS, ERASURE_EXCEPTIONS
    )
    assert document["limitations_version"].startswith("sha256:")
    widened = (*ERASURE_LIMITATIONS, "And one more thing we cannot erase.")
    assert notice_version(widened, ERASURE_EXCEPTIONS) != document["limitations_version"]


def test_the_prose_notice_and_the_structured_exceptions_are_one_register() -> None:
    """Two lists that say the same thing drift. They are paired by index so that adding
    a limitation to one without the other fails here rather than in front of a
    regulator."""
    assert len(ERASURE_EXCEPTIONS) == len(ERASURE_LIMITATIONS)
    for exception, prose in zip(ERASURE_EXCEPTIONS, ERASURE_LIMITATIONS, strict=True):
        assert exception.keyword.lower() in prose.lower(), (
            f"the structured entry {exception.what!r} and the prose beside it describe "
            "different things"
        )
        assert exception.why and exception.authority


def test_the_backup_window_is_one_number_in_three_places() -> None:
    """The certificate, the DPA and the ops runbook must quote the same window.

    THE GAP THIS CLOSES. `infra/backup/README.md` set 35 days and reasoned about exactly
    this consequence — "every extra day of retention is an extra day in which an erasure
    request cannot fully reach our data" — while the certificate handed to a data
    principal said nothing about backups at all. Then the DPA published the window to
    clients, so the product was disclosing a limitation in one document and omitting it
    from the one the erasure itself produces.

    Now all three read from `BACKUP_WINDOW_DAYS`, and this asserts the two that cannot
    import it still agree. A cross-language number kept in step by memory is the drift
    class D-103 exists for; the runbook is where the number is actually DECIDED, so if it
    moves, this fails until the other two follow.
    """
    window = str(deletion.BACKUP_WINDOW_DAYS)
    root = Path(__file__).resolve().parents[1]

    runbook = (root / "infra" / "backup" / "README.md").read_text(encoding="utf-8")
    assert f"{window} days" in runbook or f"retain FULL {window}" in runbook, (
        f"the backup runbook no longer quotes a {window}-day window, so the certificate "
        "is now promising a retention period the ops procedure does not implement"
    )

    dpa = (root / "apps" / "web" / "src" / "lib" / "legal" / "dpa.ts").read_text(encoding="utf-8")
    assert window in dpa, (
        f"the DPA no longer quotes {window} days. It is a published contractual "
        "commitment about how long an erased record can survive; the certificate quotes "
        "the same number, and the two must not drift"
    )


def test_the_certificate_tells_a_data_principal_about_backups() -> None:
    """A limitation that exists only in a contract the CLIENT signed is not disclosed to
    the person the data is about — and the certificate is what reaches them."""
    joined = " ".join(deletion.ERASURE_LIMITATIONS).lower()
    assert "backup" in joined, "the certificate omits the backup window entirely"
    assert str(deletion.BACKUP_WINDOW_DAYS) in " ".join(deletion.ERASURE_LIMITATIONS)

    # Index-aligned with the structured half, which the module states as a rule and which
    # is what a machine-readable consumer reads instead of the prose.
    assert len(deletion.ERASURE_LIMITATIONS) == len(deletion.ERASURE_EXCEPTIONS)
    assert any(e.keyword == "backup" for e in deletion.ERASURE_EXCEPTIONS)
