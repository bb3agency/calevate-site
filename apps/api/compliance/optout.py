"""An in-call opt-out becomes a suppression — detection, and the ONE write path.

`dnc.SOURCES` has carried `call_optout` since the DNC module shipped and until now only
TESTS ever wrote it: a caller could say "remove my number", the agent could politely
confirm, and the next campaign tick dialled them again. SEC-COMP §2.3 has always asked
for the opposite ("'don't call me again' ⇒ tool adds to tenant `dnc_list` within the
call; propagates to campaigns immediately"), and hard rule 5 puts a deadline on it. This
module is that path.

--------------------------------------------------------------------------------
WHAT THE REGULATOR ACTUALLY REQUIRES (researched 2026-08-12)
--------------------------------------------------------------------------------

Sources are cited so the next reader inherits the evidence rather than the conclusion.
`trai.gov.in`, `indiankanoon.org` and the law-firm write-ups are all blocked by this
environment's egress proxy, so the quoted wording below was read through the search
index rather than fetched from the gazette PDF; anyone re-checking this should open
`https://www.trai.gov.in/sites/default/files/2024-09/RegulationUcc19072018.pdf` (TCCCPR
2018) and `https://www.trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf`
(Second Amendment, 12 Feb 2025) directly. That limitation is recorded rather than hidden
because the regulatory half is the part that is not recoverable if wrong.

* **TIMEFRAME.** TCCCPR 2018 requires that "preferences recorded or modified by the
  Subscriber are given effect to in near real time and in such a manner that no delivery
  of commercial communication is made or blocked in contravention to the Subscribers'
  preference **after twenty-four hours** or such time as the Authority may prescribe".
  Twenty-four hours is the OUTER limit on the network side, and "near real time" is the
  standard — which is why hard rule 5's own deadline ("before the next dispatch tick",
  30 seconds here) is stricter than the regulation and stays that way. A timeframe we
  meet by a factor of ~2800 is not gold-plating: the 24-hour figure is measured from the
  moment the preference is RECORDED, and the only thing that records this one is us.
* **REVOCATION MUST BE RECORDED, IMMUTABLY.** The regulations require revocation of
  consent to be recorded "in a robust manner which is immutable and non-repudiable". Our
  answer is a `consent_ledger` row (append-only, hard rule 4) carrying the call, the
  moment and the words — not a mutable flag on a lead.
* **NINETY DAYS.** A sender "shall not make a request seeking consent of a customer who
  has opted out, before ninety (90) days from the date of such opt-out". That is why
  `dnc.REMOVABLE_SOURCES` excludes `call_optout`: a client employee deleting the entry
  and re-dialling is the exact prohibited act, and the DNC module already refuses it.
* **WHOSE OBLIGATION.** The **Principal Entity — our client — is responsible for
  compliance regardless of whether a third-party telemarketer is used**; Calevate is the
  registered Telemarketer, performs the delivery and scrubbing functions, and must be
  traceable through them (SEC-COMP §3's role model, unchanged by the 2025 amendment,
  which tightened PE/TM traceability and cut the permitted chain of intermediaries). So
  the obligation we are discharging here is our CLIENT's, executed by us, on our
  infrastructure, with our record. It follows that the suppression is written at TENANT
  scope (the PE's own list) and never globally, and that the evidence must be legible to
  the client, because they are the party a complaint is filed against.
* **WHAT THIS IS NOT.** A verbal opt-out to a telemarketer is NOT a DND/preference
  registration. Registry-grade opt-out runs through the Access Provider (1909/DND) and
  registrar-recorded consent revocation runs through DLT — neither is a facility we hold
  (`compliance/consent.py` makes the same point about grants). So this row is the
  TM-side suppression plus the evidence of the request; it is honest about being that
  and nothing more.
* **The complaint clock is 7 days** (2025 amendment, up from 3), and 5+ complaints in a
  rolling 10 days puts the CLIENT's registration at risk (SEC-COMP §1). That is the
  practical cost of a missed opt-out and the reason the failure direction below is
  chosen the way it is.

Sources: TRAI TCCCPR 2018 (Reg. 6 preference/effect timing; Reg. 17 sender obligations)
and the TCCCPR Second Amendment dated 12 Feb 2025, gazette PDFs linked above; PIB press
release PRID 2102413 ("TRAI Strengthens Consumer Protection with Amendments to TCCCPR,
2018", 12 Feb 2025) for the 7-day complaint window; DPDP Act 2023 §6(6) for withdrawal
being as easy as consent.

--------------------------------------------------------------------------------
DETECTION: WHICH LAYER, AND WHY BOTH
--------------------------------------------------------------------------------

Two honest places, and they are not equivalent:

1. **An in-call tool** the agent invokes the moment the caller asks (voice-runtime's
   `POST /tools/v1/opt-out` → `workers.optout.record_in_call_optout`). Immediate, and it
   is what SEC-COMP §2.3 specifies. What it does NOT cover: it depends on the model
   choosing to call the function, on the engine supporting custom functions the way we
   assume, and on the tool round trip completing — Bolna's custom-function contract is
   an OPERATIONS §2 gate (item 8: "test a custom function to our endpoint and record the
   tool-call p95 — no timeout is documented"), not a verified behaviour (D-31/D-32). A
   layer that can be silently absent is not a layer you may rely on alone.
2. **The post-call pipeline** reading the transcript (`workers/pipeline.py`, step 2b).
   Offline, deterministic, and it runs on EVERY completed call whether or not the model
   cooperated — including calls where the agent talked over the request. What it does
   NOT cover: it is late by the length of the call plus the pipeline's own lag (SLO 2
   minutes), and the dispatch tick runs every 30 seconds, so a tenant dialling the same
   number on another campaign during the call still gets through.

**Both are built, because they fail differently**: the tool fails when the MODEL misses
the request; the transcript pass fails when the CALL is long. Neither failure mode
covers the other, and the union is what makes hard rule 5's deadline true for the
population rather than for the happy path. The alternative — the pipeline alone, which
is what the pinned xfail proposed — was rejected because a 40-minute call with an
opt-out in minute two leaves 38 minutes in which the number is dialable and every gate
in this codebase says it is fine. The alternative in the other direction — the tool
alone, which is what SEC-COMP §2.3 literally says — was rejected because it rests
entirely on an unverified vendor behaviour and on the model's judgement, and hard rule 5
is not a thing to bet on a prompt.

**One write path, and the dedupe is real.** Both detectors call `record_call_optout` and
nothing else writes `call_optout`. The `dnc_list` insert is `ON CONFLICT DO NOTHING`
(`compliance.service.add_to_dnc`); the ledger row is guarded on
`(tenant_id, phone, purpose, status, call_id)`, so the tool and the transcript pass
racing on the same call produce ONE piece of evidence, and a pipeline replay (which
D-31 makes normal) produces none extra. The ledger is append-only, so the guard is a
pre-check rather than an upsert — the same doctrine `pipeline._meter` uses for money.

--------------------------------------------------------------------------------
THE DETECTOR IS A PHRASE LIST, AND SAYS SO
--------------------------------------------------------------------------------

`detect_opt_out` is a curated list of regular expressions over Telugu, Hindi and English
(romanised — how Sarvam Saaras returns code-mixed Indian speech — plus a smaller set of
native-script forms). It is NOT comprehension and it must never be described as such: it
will miss an opt-out phrased in a way nobody wrote down, and it has no model behind it.

That is stated plainly because the alternative — an LLM call in the pipeline — buys
recall at the cost of a second model dependency on a compliance path, a cost per call,
and a failure mode ("the extractor was down, so nobody was suppressed") that is exactly
what hard rule 5 forbids. The engine's own tool call IS the comprehension layer; this is
the deterministic floor under it, and a floor that always runs beats a ceiling that
sometimes does.

**The failure direction is chosen, not accidental.** A false positive suppresses a
caller who did not ask: the client loses a lead and the caller is left alone — annoying,
recoverable through support, and lawful. A false negative dials someone who asked us to
stop: that is a TCCCPR violation with the client's own registration on the line. So the
patterns are written to fire on the ambiguous middle rather than to be precise, and the
one place precision IS enforced is Telugu's negative suffix — `call cheyandi` ("please
call") and `call cheyakandi` ("don't call") differ by two letters, and matching the
former would suppress the very caller who asked for a callback. Every pattern requires
the CALLER to have said it: the agent's acknowledgement ("mee number ni do-not-call list
lo pettanu") contains every keyword in the list and is not an opt-out.

Deliberately NOT in scope: consent withdrawal and erasure ("naa data motham delete
cheyandi"). Those are DPDP §12 requests with their own surface
(`compliance/deletion.py`), and a caller asking for erasure has not necessarily asked us
to stop calling. Folding them in here would file a suppression the caller did not ask
for AND leave the erasure unserved, which is the worse of the two errors on both counts.
The red-team fixtures `rt_cl_consent_withdrawn_midcall` and
`rt_re_erasure_request_midcall` sit in that gap on purpose; closing it is a separate
seam (see the report accompanying this change).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import add_to_dnc
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.ingest.service import normalize_phone

log = get_logger(__name__)

# The `dnc_list.source` this path writes. One constant, because three modules switch on
# it: this writer, `dnc.SOURCES` (which validates the console's own adds) and
# `dnc.REMOVABLE_SOURCES` (which refuses to let a client delete it again).
CALL_OPTOUT_SOURCE = "call_optout"

# The consent purpose an opt-out from calls withdraws. `marketing`, not `messaging`:
# the caller said something about CALLS, and SEC-COMP §4 makes messaging consent its own
# permission with its own provenance — `rt_re_optout_then_whatsapp_assumed` is the
# fixture that exists for exactly this line. Withdrawing a messaging grant the caller
# never mentioned would be inventing an instruction, in the same way inferring one would.
OPTOUT_PURPOSE = "marketing"

# WHO says it was said. `inbound_call_verbal` is the consent-source enum's member for
# "spoken by the person, on a call" — `CONSENT_SOURCES` is a CHECK constraint, and the
# alternative was a migration adding a near-synonym for the outbound case. Two spellings
# of one idea is the defect CLAUDE.md names; the direction word in the member describes
# where the STATEMENT came from (the person, inbound to us), not who dialled.
OPTOUT_CONSENT_SOURCE = "inbound_call_verbal"

# Where the detection came from, recorded on every row so an auditor can tell the layer
# that caught it — and so we can measure whether the engine tool is actually firing once
# OPERATIONS gate 8 verifies it.
DETECTED_IN_CALL = "in_call_tool"
DETECTED_POST_CALL = "post_call_transcript"
DETECTION_SOURCES = (DETECTED_IN_CALL, DETECTED_POST_CALL)


class SpokenTurn(Protocol):
    """The shape the detector needs, and no more.

    A Protocol rather than `TranscriptTurn` because two callers hold different objects —
    the pipeline holds the shared model, the eval harness holds `"caller: ..."` strings
    it splits itself — and neither should have to construct the other's type to ask one
    question.
    """

    @property
    def speaker(self) -> str: ...

    @property
    def text(self) -> str: ...


@dataclass(frozen=True, slots=True)
class OptOutSignal:
    """What was matched, and where. The `matched` span is the EVIDENCE: it is what the
    consent ledger stores and what a support agent reads when a client asks why a number
    was suppressed. It is a few words of the caller's own request — never their number,
    and never the whole turn."""

    rule: str
    language: str
    # WHICH turn, when a transcript was read. `None` on the in-call path: the engine's
    # tool call has no turn index of ours to point at, and inventing one (-1, 0) would
    # put a number in the evidence that means nothing.
    turn_idx: int | None
    matched: str


# Straight, curly and backtick — all three occur in STT output and in pasted text.
# The curly one is written as an escape so ruff's ambiguous-character rule (RUF001) does
# not fire on the very character this line exists to remove.
_APOSTROPHES = str.maketrans("", "", "'\u2019`")


def _is_kept(char: str) -> bool:
    """Letters, digits — and COMBINING MARKS.

    The marks are the whole reason this is not `re.sub(r"[^\\w]+", ...)`. Python's `\\w`
    is `isalnum()` plus underscore, and an Indic vowel sign (`ॉ` in कॉल, `ే` in చేయ) is
    category Mn/Mc: not alphanumeric. Stripping them shatters every native-script word
    into consonants — कॉल became "क ल" — so a Devanagari or Telugu opt-out could never
    match a Devanagari or Telugu pattern. Romanised text was unaffected, which is
    exactly why the fixtures did not catch it.
    """
    return char.isalnum() or unicodedata.category(char).startswith("M")


def normalize_utterance(value: str) -> str:
    """Lowercase, drop apostrophes, collapse everything else to single spaces.

    Apostrophes are REMOVED rather than replaced, so "don't" becomes "dont" and one
    pattern covers both spellings. Everything else becomes a space, so punctuation,
    hyphens and the transcript's own formatting cannot hide a phrase ("do-not-call" and
    "do not call" are the same string here).
    """
    folded = value.translate(_APOSTROPHES).lower()
    return " ".join("".join(c if _is_kept(c) else " " for c in folded).split())


# The list. Each entry is (rule id, language, pattern). The rule id is what lands in the
# ledger's evidence, so it has to name the thing a human would say the caller said.
#
# Recall over precision, on purpose (see the module docstring). Two rules are
# deliberately narrow anyway, and both for the same reason: the negation carries the
# whole meaning. Telugu `cheyakandi`/`cheyyoddu` ("do not do") vs `cheyandi` ("please
# do"), and Hindi `mat karo` ("do not do") vs `karo` — a pattern that lost the negative
# would suppress every caller who asked to be rung back.
_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # --- English --------------------------------------------------------------
    ("stop_calling", "en", r"\bstop (calling|ringing|the calls|these calls|all calls)\b"),
    ("do_not_call", "en", r"\b(dont|do not|never|no more|stop) (call|ring|phone|contact)\w*\b"),
    ("do_not_call_list", "en", r"\bdo not call list\b|\bdnc list\b"),
    ("remove_my_number", "en", r"\b(remove|delete|drop) (my|this|the) (number|phone|contact)\b"),
    ("take_me_off", "en", r"\btake (me|my number|my name) off\b"),
    ("unsubscribe", "en", r"\bunsubscribe\b|\bopt me out\b|\bopt out\b"),
    # --- Telugu (romanised) ---------------------------------------------------
    # "call cheyakandi" / "phone cheyyoddu" / "call vaddu" — the negative form only.
    (
        "call_cheyakandi",
        "te",
        r"\b(call|calls|phone|fone)\w*\s+(chey+a?kandi|chey+akandhi|chey+oddu|vad+u|vod+u)\b",
    ),
    # "naa number teeseyandi" / "list lo nunchi teesivEyandi" — remove my number.
    (
        "number_teeseyandi",
        "te",
        r"\b(number|nambar|nambaru)\b[\w ]{0,20}\b(t[eh]+se|tise|thise|t[eh]+si|tholaginch)\w*\b",
    ),
    # --- Hindi (romanised) ----------------------------------------------------
    (
        "call_mat_karo",
        "hi",
        r"\b(call|phone|fone|kaal)\s+(mat|nahi|nahin|na)\s+"
        r"\w*(karo|kariye|kijiye|karna|karein|kare|kar)\b",
    ),
    ("number_hata_do", "hi", r"\b(number|nambar|list|suchi)\b[\w ]{0,25}\bhata\w*\b"),
    ("band_karo", "hi", r"\b(call|phone|fone)\w*[\w ]{0,15}\bband kar\w*\b"),
    # --- Native script --------------------------------------------------------
    # A SMALLER list than the romanised ones, and marked as such: every red-team fixture
    # we hold is romanised, so these are written from the language rather than from
    # observed STT output. They are additive — nothing depends on them being complete —
    # and the first native-script transcript from the pilot is what should grow them.
    ("do_not_call_deva", "hi", r"कॉल\s*(मत|न)\s*(करो|करें|कीजिए|करना)"),
    ("remove_number_deva", "hi", r"(नंबर|नम्बर)[^\n]{0,20}हटा"),
    ("do_not_call_telu", "te", r"(కాల్|ఫోన్)\s*చేయ(కండి|వద్దు)"),
    ("remove_number_telu", "te", r"(నంబర్|నెంబర్)[^\n]{0,20}తీసే"),
)

_COMPILED: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (rule, language, re.compile(pattern, re.UNICODE)) for rule, language, pattern in _PATTERNS
)

# How much of the matched text becomes evidence. A phrase, not a paragraph: the ledger
# needs to show WHAT the caller said, and the transcript itself (with its own retention
# policy and its redaction) is where the full record lives.
_EVIDENCE_CHARS = 80


def detect_opt_out(turns: Sequence[SpokenTurn]) -> OptOutSignal | None:
    """The FIRST opt-out a caller states, or None.

    First rather than last: an opt-out is not superseded by anything said afterwards
    (unlike a corrected name or a replaced requirement), and the earliest one is the
    moment the obligation attached — which is what the ledger should be able to show.

    Only caller turns are read. The agent's acknowledgement contains every keyword in
    the list, and an agent-triggered suppression would let a prompt regression suppress
    a client's entire contact list one call at a time.
    """
    for idx, turn in enumerate(turns):
        if turn.speaker != "caller":
            continue
        normalized = normalize_utterance(turn.text)
        if not normalized:
            continue
        for rule, language, pattern in _COMPILED:
            found = pattern.search(normalized)
            if found is None:
                continue
            return OptOutSignal(
                rule=rule,
                language=language,
                turn_idx=idx,
                matched=found.group(0)[:_EVIDENCE_CHARS],
            )
    return None


@dataclass(frozen=True, slots=True)
class OptOutRecord:
    """`suppressed` is "this number is now on the list", true even when a previous call
    already put it there — the question a caller cares about. `newly_suppressed` and
    `evidence_written` are the two things that actually happened, and they are separate
    because a second call from an already-suppressed person still deserves its own
    evidence row."""

    suppressed: bool
    newly_suppressed: bool
    evidence_written: bool


async def record_call_optout(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    raw_phone: str,
    call_id: UUID | None,
    detected_by: str,
    signal: OptOutSignal,
) -> OptOutRecord:
    """Suppress the number, record the evidence, audit it. In the CALLER'S transaction.

    Three writes that belong together and must not half-happen: a `dnc_list` row without
    evidence cannot be explained to the client whose registration is on the line, and
    evidence without the suppression is a record of an instruction we then ignored. They
    share the caller's session so a rollback takes all three.

    Idempotent by construction, because both detectors and every pipeline replay may
    reach it: the DNC insert is `ON CONFLICT DO NOTHING`, and the ledger row is
    pre-checked on (tenant, phone, purpose, status, call) — append-only means the guard
    cannot be an upsert (hard rule 4), so it is a read, and the ARQ job id (keyed on the
    call) is what keeps two runs from overlapping in practice. The same doctrine, and
    the same residual, as `pipeline._meter`.
    """
    if detected_by not in DETECTION_SOURCES:  # pragma: no cover — programmer error
        raise ValueError(f"unknown opt-out detection source: {detected_by}")
    phone_e164 = normalize_phone(raw_phone)
    if phone_e164 is None:
        # Reached when the engine hands us a number we cannot key. Refusing loudly beats
        # writing a suppression under a string the dispatch gate will never match: a row
        # that looks like protection and blocks nothing is worse than no row.
        raise ProblemError.business_rule(
            "optout_phone_invalid",
            "That call has no usable caller number to suppress.",
            remediation="Check the call record; the suppression must be added by hand.",
        )

    before = (
        await session.execute(
            text(
                "SELECT 1 FROM dnc_list WHERE phone_e164 = :phone "
                "AND (tenant_id = :tid OR tenant_id IS NULL) LIMIT 1"
            ),
            {"phone": phone_e164, "tid": tenant_id},
        )
    ).first()
    # `compliance.service.add_to_dnc` — the existing single-number writer, which the gate
    # module already owns — rather than an INSERT of our own. (The console's bulk add,
    # `dnc.add_numbers`, is a separate statement because it has a different job: it
    # deduplicates a pasted LIST against global rows and reports counts. Two writers, two
    # shapes of input, one table and one conflict target; a third would be the drift.)
    await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone_e164, source=CALL_OPTOUT_SOURCE)
    newly_suppressed = before is None

    evidence = json.dumps(
        {
            "detected_by": detected_by,
            "rule": signal.rule,
            "language": signal.language,
            "turn_idx": signal.turn_idx,
            # The caller's own words, which is what "robust, non-repudiable record of
            # the revocation" means in practice. Never the number.
            "matched": signal.matched,
        }
    )
    written = (
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, call_id, phone_e164, purpose, "
                "status, consent_source, captured_at, evidence, created_at) "
                "SELECT :id, :tid, :cid, :phone, CAST(:purpose AS text), 'withdrawn', "
                ":source, now(), CAST(:evidence AS jsonb), now() WHERE NOT EXISTS ("
                "  SELECT 1 FROM consent_ledger WHERE tenant_id = :tid AND phone_e164 = :phone "
                "  AND purpose = CAST(:purpose AS text) AND status = 'withdrawn' "
                # `IS NOT DISTINCT FROM` because `call_id` is nullable: a NULL never
                # equals a NULL, so `=` would let a call we could not resolve write an
                # evidence row on every retry.
                "  AND call_id IS NOT DISTINCT FROM :cid) RETURNING id"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cid": call_id,
                "phone": phone_e164,
                "purpose": OPTOUT_PURPOSE,
                "source": OPTOUT_CONSENT_SOURCE,
                "evidence": evidence,
            },
        )
    ).first()
    evidence_written = written is not None

    if evidence_written:
        # Audited once per opt-out, not once per replay: the audit chain is a record of
        # things that happened, and a replay is not a second request from the caller.
        await write_audit(
            session,
            action="compliance.call_optout_recorded",
            actor_type="system",
            tenant_id=tenant_id,
            object_type="call",
            object_id=str(call_id) if call_id else None,
            summary={
                "detected_by": detected_by,
                "rule": signal.rule,
                "language": signal.language,
                "newly_suppressed": newly_suppressed,
            },
        )

    # Ids, a rule name and counts. NEVER the number (hard rule 6) — and never the
    # matched text either, which is transcript content however short.
    log.info(
        "call_optout_recorded",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call_id) if call_id else None,
            "detected_by": detected_by,
            "rule": signal.rule,
            "newly_suppressed": newly_suppressed,
        },
    )
    return OptOutRecord(
        suppressed=True, newly_suppressed=newly_suppressed, evidence_written=evidence_written
    )


__all__ = [
    "CALL_OPTOUT_SOURCE",
    "DETECTED_IN_CALL",
    "DETECTED_POST_CALL",
    "DETECTION_SOURCES",
    "OPTOUT_CONSENT_SOURCE",
    "OPTOUT_PURPOSE",
    "OptOutRecord",
    "OptOutSignal",
    "SpokenTurn",
    "detect_opt_out",
    "normalize_utterance",
    "record_call_optout",
]
