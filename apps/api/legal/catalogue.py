"""WHICH documents bind a client, WHICH version is current, and WHEN a change re-asks.

THE SOURCE OF TRUTH FOR DOCUMENT IDENTITY LIVES HERE AND THE WEB BUNDLE MIRRORS IT.
`apps/web/src/lib/legal/` holds the PROSE — the eight documents, their sections and the
`{{PLACEHOLDER}}` machinery — and it is authoritative for that. It cannot be
authoritative for the version an acceptance row names, because a row in Postgres is
compared against this constant on every read of every gate, on a machine that never runs
Node. So the identity of a document (slug · revision · material · effective date) is
declared once, HERE, and `apps/web/src/lib/legal/versions.ts` carries the copy the
screens need. `scripts/check_docs_drift.legal_catalogue_drift()` fails CI when the two
disagree — the mechanism §4b already uses for the TTS rate card, for the same reason: a
mirror nothing checks is a mirror that is wrong the first time one side moves.

WHAT THAT GUARD DOES NOT PROVE, AND WHAT NOW DOES. It compares IDENTITY, not TEXT: nothing
in this tree can read the prose of a TypeScript module from Python without a TS parser. So
until 7 September 2026 a lawyer editing a clause in `terms.ts` without bumping `revision`
here produced an acceptance row naming a version whose words had changed, and no check saw
it — the discipline that closed it was human, and this paragraph used to end there.

It is now mechanical, ONE DIRECTORY OVER RATHER THAN HERE. Every revision in
`apps/web/src/lib/legal/versions.ts` carries a `contentHash` — sha256 of that document's
OPERATIVE TEXT, meaning every string a reader of `/legal/<slug>` is shown with the
`{{PLACEHOLDER}}` tokens resolved, and not the module's imports, comments or formatting —
and `apps/web/tests/legalContentHash.test.ts` fails in both directions: words that moved
under an unbumped revision, and a bump whose words are identical to the revision before it
(a different mistake, and the one that teaches clients to click through an acceptance).
`pnpm -C apps/web legal:hashes` prints the value; nothing writes it.

NO HASH IS MIRRORED HERE, DELIBERATELY. The prose exists only in TypeScript, so this side
could never recompute one — a hash copied into this file would be a number that looks
authoritative and that nothing on this side can check or contradict, which is exactly the
laundering hard rule 11 forbids. This module stays authoritative for a document's
IDENTITY, which is what an acceptance row is compared against; the bundle is authoritative
for its WORDS, which is where they live. `check_docs_drift` asserts the one thing Python
can honestly assert — that the current revision of every document HAS a hash.

`PENDING_LEGAL_REVIEW` is the other mechanical half, and it is the one that matters most
today.

--------------------------------------------------------------------------------
THE VERSION CARRIES THE REVIEW STATE, WHICH IS WHY THE FLIP NEEDS NO SPECIAL CASE
--------------------------------------------------------------------------------

The set was published on 2 September 2026. Until then `apps/web/src/lib/legal/
placeholders.ts` carried a pending-review constant, the documents showed a draft banner,
and nearly every fact in them — the supplier's name, the named Grievance Officer, the
principal place of business — was a visible blank; LEGAL-OPS-PLAYBOOK.md:481 is blunt
about what that was worth commercially: *"Templates + draft banner are not a defence."*
Every one of those blanks was filled before the flip, and the bundle's own
`assertLegalSetPublishable` refuses to render a document if one is not.

An acceptance taken in that period is PROVISIONAL, and the review state is part of the
version string rather than a flag beside it, which is why a stored row still says which
of the two it was:

    revision "1", pending review   ->  "1+pre-review"
    revision "1", reviewed         ->  "1"

The moment a human turns that constant off, every document's current version changes,
every stored acceptance names a version that is no longer current, and
`reacceptance_required` demands the whole set again — because a change of review state is
MATERIAL by construction. Nothing special-cases the transition; it falls out of
versioning, which is what was asked for. What it DOES need is one edit on each side of
the mirror, and the drift guard names the side that was missed.

(The transition is deliberately described without quoting the constant beside a boolean
literal: `check_docs_drift`'s section 5 reads `NAME is False` as a claim about the tree's
current value, and a sentence about what WILL happen would be reported as prose that has
gone stale.)

--------------------------------------------------------------------------------
BLOCKING vs READABLE
--------------------------------------------------------------------------------

Four documents bind the client and are accepted: Terms of Service, Privacy Policy, the
DPA and the Acceptable Use Policy. LEGAL-OPS-PLAYBOOK.md:475 puts the DPA in the "client
signs or clickwrap" column, and §13's "must publish" list is where the other three come
from. The remaining four published documents — sub-processors, refunds, grievance,
cookies — are readable and are NOT accepted: a sub-processor list is a notice we owe the
client, not a promise they make us, and demanding a signature on it would make every
vendor change a consent event for every tenant.
"""

from __future__ import annotations

from dataclasses import dataclass

#: MIRRORS `apps/web/src/lib/legal/placeholders.ts::PENDING_LEGAL_REVIEW`.
#:
#: Not imported (there is no import from TypeScript) and not inferred: it is declared
#: here and the drift guard fails CI if the two ever disagree. That is deliberately a
#: LOUD coupling — flipping it publishes eight legal documents and invalidates every
#: acceptance in the ledger, which is a change that should cost a diff on both sides with
#: a name on it. It was flipped on 2 September 2026, on the founder's instruction given
#: after a lawyer's review of the set, and with every placeholder in the bundle filled
#: first (the bundle's own `assertLegalSetPublishable` refuses the render otherwise).
PENDING_LEGAL_REVIEW = False

#: The suffix a pre-review version carries. A separator that cannot occur in a revision
#: id, so `_split` is unambiguous.
PRE_REVIEW_SUFFIX = "+pre-review"


@dataclass(frozen=True, slots=True)
class Revision:
    """One authored revision of one document.

    `material` describes the STEP INTO this revision, not the document: it answers "does
    somebody who accepted the previous revision have to accept again?". On the first
    revision there is no previous one, and it is True because a first acceptance is
    required anyway — which keeps the predicate a single rule instead of a rule plus an
    edge case.
    """

    revision: str
    material: bool
    #: WHY this revision exists, for the reader deciding whether `material` is right.
    note: str


@dataclass(frozen=True, slots=True)
class LegalDocumentSpec:
    """One published document, as the server knows it."""

    slug: str
    #: The title the console prints. It IS the bundle's `shortTitle`, compared by the
    #: drift guard — one document, one name, in both realms.
    title: str
    #: Does an unaccepted copy of this document stop the organisation operating?
    blocking: bool
    #: Oldest first. The last entry is the current revision.
    revisions: tuple[Revision, ...]
    #: The date the document starts binding, ISO-8601, or None while it has none.
    #:
    #: 2 September 2026 for every document — the day the set was published. It must be
    #: the same day the bundle's `{{EFFECTIVE_DATE}}` placeholder prints in the page
    #: header, in that placeholder's prose spelling; a date here that the published page
    #: does not show would be a claim nobody can check (hard rule 11).
    effective_date: str | None = None

    @property
    def current(self) -> Revision:
        return self.revisions[-1]

    @property
    def current_version(self) -> str:
        return version_of(self.current.revision)


def version_of(revision: str) -> str:
    """The wire version for an authored revision, under the review state in force."""
    return f"{revision}{PRE_REVIEW_SUFFIX}" if PENDING_LEGAL_REVIEW else revision


def _split(version: str) -> tuple[str, bool]:
    """`("1", True)` for `"1+pre-review"` — the revision, and whether it was provisional."""
    if version.endswith(PRE_REVIEW_SUFFIX):
        return version[: -len(PRE_REVIEW_SUFFIX)], True
    return version, False


def is_provisional(version: str) -> bool:
    """Was this version accepted before legal review? Reads a stored row, so it must
    answer for versions the current review state no longer produces."""
    return _split(version)[1]


# Every published document, in the order `apps/web/src/lib/legal/index.ts` lists them, so
# the console and the public `/legal` index read the same sequence.
#
# ═══ ADDING A REVISION ═══
# An edit to a document's OPERATIVE TEXT is a new `Revision`, appended here and mirrored
# in `versions.ts`. `material=True` when somebody who accepted the previous revision must
# accept again — a changed obligation, a changed liability position, a new processing
# purpose. `material=False` for a correction that changes nothing anybody agreed to: a
# typo, a broken cross-reference, a filled-in placeholder that made no promise.
# A non-material revision still shows the client a banner and still records an
# acknowledgement row when they dismiss it (see `service.record_acceptance`); it just
# never stops them operating.
#
# THE MIRROR'S ENTRY CARRIES ONE MORE FIELD THAN THIS ONE: a `contentHash` of the words
# that revision publishes (see the header). Append the revision in both files, and print
# the hash for the new entry with `pnpm -C apps/web legal:hashes` — the frontend suite
# fails until it is there, and fails if a revision was added whose words did not move.
DOCUMENTS: tuple[LegalDocumentSpec, ...] = (
    LegalDocumentSpec(
        slug="privacy",
        title="Privacy Policy",
        blocking=True,
        revisions=(
            Revision("1", True, "First published draft of the client-facing legal set."),
            Revision(
                "2",
                True,
                "Speech-leg residency and the model-training promise corrected against "
                "the speech vendor's published terms and privacy policy: an Indian "
                "VENDOR is not India-only PROCESSING, and its terms permit training on "
                "inputs and outputs absent a signed order form.",
            ),
            Revision(
                "3",
                True,
                "The in-app assistant became an agent that reads a client's own records "
                "and proposes changes, and gained a store of what it was asked and what "
                "it learned. A new category of stored personal data, a new processing "
                "purpose and a widened description of what the dashboard language leg "
                "receives; the owner's switch for staff knowledge curation stated too.",
            ),
            Revision(
                "4",
                False,
                "Published. The set came out of draft on 2 September 2026: every "
                "placeholder in the bundle was filled, the entity narration and the "
                "internal blocker names came out of the prose, and the pending-review "
                "banner came off. Non-material — nothing anybody agreed to changed "
                "meaning, and the review-state flip re-demands the set on its own.",
            ),
            Revision(
                "5",
                False,
                "The published principal place of business was reduced to the city, "
                "state and country: the street lines were the founder's home address "
                "and no identification duty asks for them. Non-material — the "
                "identification is narrower, and nothing anybody agreed to changed "
                "meaning.",
            ),
            Revision(
                "6",
                True,
                "The second voice quality brought a second speech vendor into the "
                "notice. Section 6 states what that vendor's own published privacy "
                "policy permits it to do with what it receives and what it receives "
                "(the words an agent speaks, as text, a turn at a time — never the "
                "caller's audio, transcript or recording); section 8 states that where "
                "it processes has not been established and names no country for it; and "
                "voice synthesis is no longer described as running wholly on the Indian "
                "provider. MATERIAL — a new recipient of caller-derived text is a new "
                "disclosure, not a clarification.",
            ),
            Revision(
                "7",
                True,
                "Section 9 publishes two retention periods the notice had never "
                "disclosed and one it enforced in silence. An uploaded campaign contact "
                "list and a promised call-back — a name, a number and a note about "
                "someone who may never have been dialled — previously aged out never, "
                "and now expire on the lead and transcript clocks; and what an agent "
                "remembers about a CALLER between calls was enforced at 180 days while "
                "appearing in no published table. MATERIAL, conservatively: nothing here "
                "is a new use of anybody's data and every period either shortens a "
                "retention or names one already running, but a reader of revision 6 "
                "could not have known an uploaded list was kept indefinitely or that "
                "their callers were remembered for six months, and what is kept about "
                "you is exactly what a person agrees to.",
            ),
            Revision(
                "8",
                True,
                "The speech vendor no longer synthesises the agent's voice. It still "
                "hears every call and still reads the first pass over the transcript, so "
                "nothing this notice says about what it receives or what its own terms "
                "permit changed; the cheaper voice quality passed to a third company, and "
                "BOTH voice qualities are now spoken by companies whose processing "
                "location has not been established. Two things a reader of revision 7 was "
                "told are WITHDRAWN rather than reworded: that voice synthesis ran on the "
                "Indian provider for agents on the first quality, and that a client could "
                "keep an unplaceable synthesiser away from their callers by keeping every "
                "agent on the other quality. MATERIAL — where an agent's voice is made, "
                "and whether there is a choice that keeps it with a company whose "
                "published position somebody has read, are both things a reader agreed "
                "to; and nobody here has been able to open a page the new company "
                "publishes.",
            ),
            Revision(
                "9",
                True,
                "A client may now verify their own identity through DigiLocker with a "
                "licensed intermediary (D-635). Section 4 states what that route "
                "collects: the intermediary handles the Aadhaar, Calevate receives the "
                "confirmation, the intermediary's reference, the name confirmed and the "
                "date, and no Aadhaar number or identity document is received or stored "
                "by either route. MATERIAL — an intermediary may now stand between the "
                "client and us on this path, and a new party in a data flow is a new "
                "disclosure rather than a clarification. The section 29 reasoning is "
                "unchanged and the twelve-digit refusal now covers three more fields.",
            ),
            Revision(
                "10",
                False,
                "The voice-platform wording from the Bolna era is replaced by the owned "
                "runtime it describes (D-639 deleted Bolna): the call runs as a program of "
                "ours on Pipecat Cloud in a region whose country is not established, over "
                "the telephone carrier Vobiz, which states no processing location; carrier "
                "callbacks are accepted from the carrier's published addresses, with its "
                "call record as the record of truth; and the carrier's copies are named "
                "among those an erasure reports as unconfirmed. NON-MATERIAL, the "
                "founder's call (2 Oct 2026): a factual correction of vendor wording, and "
                "no right or obligation changes. No residency claim is added.",
            ),
            # The founder's call (3 Oct 2026), D-668.
            Revision(
                "11",
                False,
                "Call recording wording (D-668): our copies of call recordings are kept "
                "for 90 days and then deleted; Vobiz records the call, we copy the "
                "recording into our own storage, and Vobiz's copy is deleted one day after "
                "ours is saved, never kept beyond its own limit of up to 30 days; an "
                "erasure deletes the carrier's recordings through its published deletion "
                "and its call records remain a written request. NON-MATERIAL, the "
                "founder's call (3 Oct 2026): no right or obligation changes.",
            ),
            # D-679.
            Revision(
                "12",
                True,
                "Vendor names are removed (D-679): the notice describes sub-processors by "
                "category and says a named list is available on request. Every disclosure is "
                "kept without the name: the speech provider's cross-border transfers and "
                "training terms, the carrier's recording, object storage outside India, the "
                "language model's United States region and the three model providers. Adds "
                "that a deployment may run the call on a hosted voice platform that states "
                "storage in India and a language-model step that may be processed outside "
                "India. MATERIAL: how recipients are disclosed changes.",
            ),
            # D-687.
            Revision(
                "13",
                True,
                "Calls run on the hosted voice platform since 7 Oct 2026, so sections 6 and 8 "
                "describe it as the live path, with its India and no-training statements "
                "reported as its own (including that it may train on its pay-as-you-go plan "
                "unless switched off); the speech provider reads transcripts after the call "
                "and hears calls only on our own call program; the cheaper voice is the "
                "platform's own and the dearer one a separate company; the platform's own "
                "recording retention is stated. MATERIAL: a new training position on the "
                "live call path.",
            ),
            # D-692.
            Revision(
                "14",
                True,
                "D-692: section 4's KYC entry now says what verification keeps: the "
                "business document (encrypted, kept while the account is open), the owner "
                "ID file until review or 30 days, the masked number, the name check and the "
                "provider reference; the outbound pledge record replaces the DLT "
                "registration row. MATERIAL: a stored document class that revision 13 said "
                "we never hold.",
            ),
            Revision(
                "15",
                True,
                "Section 4's DigiLocker route now says we receive the whole record the owner "
                "chose (which can include date of birth, gender, address and contact details, "
                "a photo link and the full PAN), read it in memory and keep only the name on "
                "it, whether that name matches the OWNER the client named (not the business) "
                "and the masked number; the kept list gains that name. MATERIAL: a reader "
                "learns we receive more than revision 14 said.",
            ),
            # D-696.
            Revision(
                "16",
                False,
                "D-696: section 4's upload route takes the owner's PAN card only, no longer "
                "an Aadhaar copy (Aadhaar regulation 16C(1)), and says our reviewer matches "
                "the PAN, name and date of birth at the Income Tax 'Verify Your PAN' "
                "service; the kept list gains that the PAN check matched, who checked and "
                "when, and says the date of birth is never stored. NOT MATERIAL: we collect "
                "less than revision 15 described, so nobody needs to accept again.",
            ),
            # D-694 G-1, D-698.
            Revision(
                "17",
                True,
                "D-694/D-698: the in-app assistant runs first on the provider whose "
                "developer service names no region, only while its no-training plan is "
                "recorded, with the East US 2 provider as its fallback; and it now makes the "
                "changes a person asks for — reversible ones at once with an Undo, anything "
                "that calls, spends, publishes, deletes or changes do-not-call only on a "
                "confirm. MATERIAL: a new place where what a client types is processed, and "
                "'nothing it suggests takes effect on its own' stopped being true.",
            ),
            # D-700.
            Revision(
                "18",
                False,
                "D-700: section 7 says a client can have its agent act in the client's own "
                "accounts during a call (CRM, spreadsheet, calendar, WhatsApp, Razorpay "
                "payment links, its own API), that those companies are the client's "
                "processors acting on its instruction, what reaches them, and that a "
                "WhatsApp or payment link needs the caller's messaging consent. NOT "
                "MATERIAL: nothing we do on our own account changed; each flow runs only "
                "when a client connects its own account and switches it on.",
            ),
        ),
        effective_date="2026-09-02",
    ),
    LegalDocumentSpec(
        slug="terms",
        title="Terms of Service",
        blocking=True,
        revisions=(
            Revision("1", True, "First published draft of the client-facing legal set."),
            Revision(
                "2",
                True,
                "Speech-leg residency and the model-training promise corrected against "
                "the speech vendor's published terms and privacy policy: an Indian "
                "VENDOR is not India-only PROCESSING, and its terms permit training on "
                "inputs and outputs absent a signed order form.",
            ),
            Revision(
                "3",
                True,
                "The in-app assistant became an agent that reads a client's own records "
                "and proposes changes, and gained a store of what it was asked and what "
                "it learned. A new category of stored personal data, a new processing "
                "purpose and a widened description of what the dashboard language leg "
                "receives; the owner's switch for staff knowledge curation stated too.",
            ),
            Revision(
                "4",
                False,
                "Published. The set came out of draft on 2 September 2026: every "
                "placeholder in the bundle was filled, the entity narration and the "
                "internal blocker names came out of the prose, and the pending-review "
                "banner came off. Non-material — nothing anybody agreed to changed "
                "meaning, and the review-state flip re-demands the set on its own.",
            ),
            Revision(
                "5",
                False,
                "The published principal place of business was reduced to the city, "
                "state and country: the street lines were the founder's home address "
                "and no identification duty asks for them. Non-material — the "
                "identification is narrower, and nothing anybody agreed to changed "
                "meaning.",
            ),
            Revision(
                "6",
                True,
                "Clause 6.1 gained the credit-lot promise: each purchase of credit is "
                "priced at the per-minute rates shown for that purchase when it was "
                "made, one rate for each voice quality an agent can speak in, and those "
                "rates hold for that purchase's credit until it is spent, whatever the "
                "rate card does afterwards; credit does not expire and is spent oldest "
                "purchase first. The clause's rate language went plural, because there "
                "are now two. MATERIAL — a new operative fee term changes what somebody "
                "agreed to about what they pay.",
            ),
            Revision(
                "7",
                True,
                "Clause 5 gains two obligations the client did not have before: the "
                "advance written notice to their own telecom access provider that these "
                "calls are dialled automatically, and the per-number confirmation that "
                "their business is the sender before an ordinary ten-digit line may "
                "dial. Clause 4 widens to say a withdrawn notice stops outbound as a "
                "lapsed registration does. MATERIAL — a client who accepted revision 6 "
                "agreed to a document that never named the thing now refusing every "
                "outbound call they make.",
            ),
            Revision(
                "8",
                False,
                "Clause 4's staff paragraph now says that what staff add to the agents' "
                "knowledge goes to the agents once it has been read, without review by the "
                "owner or by Calevate (D-658). Non-material — the terms never promised a "
                "review, staff curation is still off until the owner turns it on, and "
                "nothing anybody agreed to changes meaning.",
            ),
            Revision(
                "9",
                False,
                "The definition of Engine, the dependency sentence and the erasure "
                "sentence stop describing a third-party voice platform (Bolna, deleted by "
                "D-639): the engine is our own call program on a third-party hosting "
                "platform, and the copies an erasure certificate names include the "
                "telephone carrier's. NON-MATERIAL, the founder's call (2 Oct 2026): "
                "factual vendor wording only, and no right or obligation changes.",
            ),
            # D-679.
            # D-679, D-681.
            Revision(
                "10",
                True,
                "Call time is billed in 30-second steps, each part-step rounded up, and an "
                "unanswered call is not charged (section 6.1, D-681): MATERIAL, because it "
                "changes how calls are charged. Also, the definition of Engine and the "
                "dependency clause say suppliers are listed by category on the sub-processor "
                "list with a named list on request (D-679).",
            ),
            # D-687.
            Revision(
                "11",
                False,
                '"Engine" and clause 9\'s dependency sentence name the hosted voice platform '
                "that runs calls since 7 Oct 2026 as well as our own call program. "
                "NON-MATERIAL: a definition and a description; no right or obligation moves.",
            ),
            # D-692.
            Revision(
                "12",
                True,
                "D-692: outbound calling rests on verification and the no-cold-calls "
                "pledge, not DLT registrations; Calevate is no longer described as the "
                "client's telemarketer; numbers rented through Calevate are described, and "
                "released on closure. MATERIAL: the client's outbound obligations change.",
            ),
            # D-699.
            Revision(
                "13",
                True,
                "D-699: clause 11 says unused credit is forfeited when the account closes; "
                "clause 6.3 adds auto-recharge (one approval, a monthly limit, notice before "
                "each charge) and what a payment dispute pauses. MATERIAL: a client loses "
                "money they might have expected back.",
            ),
        ),
        effective_date="2026-09-02",
    ),
    LegalDocumentSpec(
        slug="acceptable-use",
        title="Acceptable Use",
        blocking=True,
        revisions=(
            Revision("1", True, "First published draft of the client-facing legal set."),
            Revision(
                "2",
                False,
                "Published. The set came out of draft on 2 September 2026: every "
                "placeholder in the bundle was filled, the entity narration and the "
                "internal blocker names came out of the prose, and the pending-review "
                "banner came off. Non-material — nothing anybody agreed to changed "
                "meaning, and the review-state flip re-demands the set on its own.",
            ),
            Revision(
                "3",
                True,
                "Section 2.9 adds a precondition to all outbound dialling the policy "
                "never carried — the sender's own advance notice to their access "
                "provider — and 2.10 adds the thirty-minute limit on a call placed off "
                "a lead delivery. Section 2.2 now refuses a transactional campaign "
                "outright, where it had described transactional as a classification a "
                "client could pick, and conditions dialling from an ordinary ten-digit "
                "number on a per-number sender confirmation. MATERIAL — each is a new "
                "obligation rather than a clarification, and the old 2.2 told clients "
                "to do something the product now refuses.",
            ),
            # D-692.
            Revision(
                "4",
                True,
                "D-692: section 2.1 replaces the three DLT registrations with business "
                "verification and the no-cold-calls pledge, and section 2.2 drops the "
                "number-series and sender-confirmation rules. MATERIAL: what the client "
                "must do before an outbound call changes.",
            ),
            # D-696.
            Revision(
                "5",
                False,
                "D-696: section 2.1's upload route takes the owner's PAN card only, no "
                "longer an Aadhaar copy. NOT MATERIAL: the client is asked for less and no "
                "obligation moves.",
            ),
        ),
        effective_date="2026-09-02",
    ),
    LegalDocumentSpec(
        slug="dpa",
        title="Data Processing Addendum",
        blocking=True,
        revisions=(
            Revision("1", True, "First published draft of the client-facing legal set."),
            Revision(
                "2",
                True,
                "Speech-leg residency and the model-training promise corrected against "
                "the speech vendor's published terms and privacy policy: an Indian "
                "VENDOR is not India-only PROCESSING, and its terms permit training on "
                "inputs and outputs absent a signed order form.",
            ),
            Revision(
                "3",
                True,
                "The in-app assistant became an agent that reads a client's own records "
                "and proposes changes, and gained a store of what it was asked and what "
                "it learned. A new category of stored personal data, a new processing "
                "purpose and a widened description of what the dashboard language leg "
                "receives; the owner's switch for staff knowledge curation stated too.",
            ),
            Revision(
                "4",
                False,
                "Published. The set came out of draft on 2 September 2026: every "
                "placeholder in the bundle was filled, the entity narration and the "
                "internal blocker names came out of the prose, and the pending-review "
                "banner came off. Non-material — nothing anybody agreed to changed "
                "meaning, and the review-state flip re-demands the set on its own.",
            ),
            Revision(
                "5",
                False,
                "The published principal place of business was reduced to the city, "
                "state and country: the street lines were the founder's home address "
                "and no identification duty asks for them. Non-material — the "
                "identification is narrower, and nothing anybody agreed to changed "
                "meaning.",
            ),
            Revision(
                "6",
                True,
                "Clause 2 gained the second vendor whose published terms permit training "
                "on what it receives; clause 5 narrowed its own warranty for the one "
                "register row whose data-processing agreement nobody has established can "
                "be entered without an enterprise contract; clause 9 stopped saying "
                "voice synthesis runs wholly on the Indian provider and records that "
                "where the second vendor processes has not been established. MATERIAL — "
                "a narrowed warranty and a new recipient both change what somebody "
                "agreed to.",
            ),
            Revision(
                "7",
                True,
                "Clause 2's voice-synthesis bullet no longer names the company that hears "
                "the call: it was removed from the synthesis leg, and the cheaper voice "
                "quality passed to a third company of whose published position we have "
                "read nothing — every one of its own sites refuses a connection from the "
                "environment this software is built in. Clause 5 gains a SECOND exception "
                "to its warranty for that company, on the stronger ground that we cannot "
                "say whether it offers a data-processing agreement at all. Clause 9 stops "
                "saying voice synthesis runs on the Indian provider for the first voice "
                "quality and WITHDRAWS the sentence that keeping your agents on that "
                "quality kept your callers' data away from an unplaceable vendor — there "
                "is no longer a quality that does. MATERIAL — a narrowed warranty and a "
                "withdrawn assurance both change what somebody agreed to.",
            ),
            Revision(
                "8",
                False,
                "Three sentences said we had read nothing at all of the company that "
                "speaks the cheaper voice quality. It does publish a price list and it "
                "has now been read, so the claim narrows to what is true: a not-finding "
                "had been written down as a fact about the vendor and had reached a "
                "client-facing document. NON-MATERIAL — the operative words are "
                "verbatim. We still represent nothing about whether it offers a "
                "data-processing agreement, still name no country, and its training and "
                "retention position is still not stated.",
            ),
            Revision(
                "9",
                False,
                "Bolna-era voice-platform wording replaced (D-639 deleted Bolna): clause "
                "9 says the call runs as a program of ours on a hosting platform in a "
                "region whose country is not established, with its audio through a "
                "telephone carrier that states no processing location; the erasure "
                "paragraph names the carrier's copies; Annex B.4 describes the carrier's "
                "callbacks rather than a voice platform's webhooks. NON-MATERIAL, the "
                "founder's call (2 Oct 2026): factual vendor wording, and no right or "
                "obligation changes.",
            ),
            # The founder's call (3 Oct 2026), D-668.
            Revision(
                "10",
                False,
                "Call recording wording (D-668): an erasure deletes the carrier's "
                "recordings through its published deletion and its call records remain a "
                "written request; clause 8 states call recordings are kept for 90 days. "
                "NON-MATERIAL, the founder's call (3 Oct 2026): no right or obligation "
                "changes.",
            ),
            # D-679.
            Revision(
                "11",
                True,
                "Clause 5 and Annex C authorise sub-processors by the categories on the "
                "sub-processor page plus a named list available on request, and a new company "
                "in an existing category is notified like a new category (D-679). Clause 9 "
                "says each category's location rather than each named vendor's, and corrects "
                "a stale sentence that still said one voice quality is synthesised by the "
                "speech provider (untrue since 18 Sep 2026). MATERIAL: the authorisation "
                "clause changes.",
            ),
            # D-687.
            Revision(
                "12",
                True,
                "Clause 5's warranty that every sub-processor is engaged under a written "
                "contract gains an exception for the hosted voice platform that now runs "
                "every call, whose data-processing agreement is offered and not recorded as "
                "signed; clause 2 relays its training statement as its own; clause 9 "
                "describes it as the live call path. MATERIAL: a narrowed warranty.",
            ),
        ),
        effective_date="2026-09-02",
    ),
    LegalDocumentSpec(
        slug="subprocessors",
        title="Sub-processors",
        blocking=False,
        revisions=(
            Revision("1", True, "First published draft of the client-facing legal set."),
            Revision(
                "2",
                True,
                "Speech-leg residency and the model-training promise corrected against "
                "the speech vendor's published terms and privacy policy: an Indian "
                "VENDOR is not India-only PROCESSING, and its terms permit training on "
                "inputs and outputs absent a signed order form.",
            ),
            Revision(
                "3",
                True,
                "The in-app assistant became an agent that reads a client's own records "
                "and proposes changes, and gained a store of what it was asked and what "
                "it learned. A new category of stored personal data, a new processing "
                "purpose and a widened description of what the dashboard language leg "
                "receives; the owner's switch for staff knowledge curation stated too.",
            ),
            Revision(
                "4",
                True,
                "Cartesia was added as the voice-synthesis sub-processor for the second "
                "voice quality, in its own row beside its existing contingency one, with "
                "a section recording what its published terms allow and the three things "
                "about it nobody has established — where it processes, its retention on "
                "a non-enterprise plan, and whether its data-processing agreement can be "
                "signed without an enterprise contract. MATERIAL — a new sub-processor "
                "is the event the DPA's notification clause exists for, and a client may "
                "object to it.",
            ),
            Revision(
                "5",
                True,
                "The platform the call itself now runs on was added: the conversation "
                "moved into a container of ours on a third party's compute, which puts a "
                "new company on the path the caller's AUDIO travels, and no row named "
                "it. Its row and section 3.7 record what nobody has established about it "
                "— the operating entity, where its region is, what its terms permit, "
                "its retention, whether a data-processing agreement can be entered, and "
                "its own sub-processors — rather than filling any of it in, because "
                "its documentation cannot be read from the environment this is built in. "
                "The carrier row is widened in the same revision: under the same design "
                "the carrier now carries the call audio and not only the numbers and the "
                "call records. MATERIAL — a new sub-processor on the call path is "
                "the event the DPA's notification clause exists for, and it is the most "
                "sensitive category in the product.",
            ),
            Revision(
                "6",
                True,
                "Three recipients that were in the product and on no page, found by "
                "auditing the register FROM THE CODE rather than by re-reading its rows. "
                "The knowledge store and search service an operator can select from the "
                "ops console at runtime, which then holds every passage of the knowledge "
                "a client publishes; a third voice-synthesis vendor, chosen per agent, "
                "receiving the words the agent speaks; and an unnamed row for a tracing "
                "collector, whose address is a setting that could point at a monitoring "
                "vendor. All three are switched off, which is not the same as "
                "undisclosed: a register that omits a recipient one setting away from "
                "being live is the failure the notification clause exists for. MATERIAL "
                "— new sub-processors are what a client may object to.",
            ),
            Revision(
                "7",
                True,
                "No row is added and none is removed; what moved is which vendor does "
                "what. The speech vendor's entry loses voice synthesis — it still hears "
                "every call and still reads the transcript first, and nothing in its "
                "location, what it receives, or the section on what its terms permit "
                "narrowed by a word. The third voice-synthesis vendor, disclosed one "
                "revision ago as a quality nobody could choose, becomes the vendor of the "
                "cheaper of the two qualities. The section written for one synthesis "
                "vendor now covers both, and its closing assurance — that a client could "
                "keep every agent on the other voice quality and that vendor would then "
                "receive nothing of theirs — is WITHDRAWN, because both qualities are now "
                "spoken by companies whose published position nobody here has read. "
                "MATERIAL — re-assigning the most sensitive leg in the product from a "
                "vendor whose terms are set out on this page to one whose pages cannot be "
                "opened at all tells a client something new about who processes what.",
            ),
            Revision(
                "8",
                False,
                "The register row and section 3.6 said that company publishes no price. "
                "It does; the page had not been found, and the not-finding was written "
                "down as a fact about the vendor. The correction is stated in the cell "
                "itself, as this register states its other corrections, because a client "
                "may have read revision 7, and the true reason the quality still cannot "
                "be sold is restated: a list price is not an invoice. NON-MATERIAL — no "
                "row is added or removed, nothing about who receives what changes, and "
                "no assurance is withdrawn.",
            ),
            Revision(
                "9",
                False,
                "The carrier row names Vobiz as the carrier in use, on Calevate's own "
                "account, with Plivo as a switchable fallback; Exotel, a candidate with "
                "no adapter, is dropped, as are the sentences saying no carrier was "
                "chosen. Vobiz's processing location is stated as not stated by the "
                "vendor, and its console's 30-day recording window is recorded. The Bolna "
                "row is removed (D-639 deleted it from the product; no client data is in "
                "production) and section 3.1 now describes the owned runtime. "
                "NON-MATERIAL, the founder's call (2 Oct 2026): no new sub-processor is "
                "added and no assurance is withdrawn.",
            ),
            # The founder's call (3 Oct 2026), D-668.
            Revision(
                "10",
                False,
                "The Vobiz row and section 3.1 say Vobiz records the call and we copy the "
                "recording into our own storage, kept 90 days; Vobiz's copy is deleted one "
                "day after ours is saved. NON-MATERIAL, the founder's call (3 Oct 2026): "
                "no new sub-processor is added and no assurance is withdrawn.",
            ),
            # D-678.
            Revision(
                "11",
                True,
                "ThinnestAI is added as the platform that runs the whole call (speech, "
                "language model, voice, numbers and recording) on a deployment switched to "
                "it, with its published storage location and its own named "
                "sub-processors. MATERIAL: a new sub-processor.",
            ),
            # D-679.
            Revision(
                "12",
                True,
                "The register becomes a table of sub-processor categories with no vendor "
                "named except the payment gateway and services a client connects itself; a "
                "named list is available on request and is what clause 5 notices are given "
                "against (D-679). Every location, receipt, status, training, retention and "
                "cross-border fact is kept at category level. MATERIAL: the form of the "
                "authorised list changes.",
            ),
            # D-687.
            Revision(
                "13",
                False,
                "The Status column follows the live deployment: the hosted voice platform is "
                "Core, and the carrier on our own account, live speech recognition and the "
                "in-call language models are configured, not enabled. The platform's written "
                "DPA and training statements are reported as its statements, it holds our "
                "admin-cloned voices, and the dearer voice reaches its company through the "
                "platform on our account. NON-MATERIAL: no company is added.",
            ),
            # D-692.
            Revision(
                "14",
                True,
                "D-692: adds the identity-verification category (DigiLocker), configured, "
                "not enabled until its credentials are set. MATERIAL: a new sub-processor.",
            ),
            Revision(
                "15",
                True,
                "The identity-verification row now says we receive the whole record the owner "
                "chose (which can include date of birth, gender, address and contact details, "
                "a photo link and the full PAN), read it in memory and keep only the name, a "
                "masked number and the reference. MATERIAL: we receive more than revision 14 "
                "said.",
            ),
            # D-694 G-1, D-698.
            Revision(
                "16",
                True,
                "D-694/D-698: the language-model row says the in-app assistant runs first on "
                "the provider that names no region (while its no-training plan is recorded) "
                "with the default provider as its fallback, and section 3.5 says the "
                "assistant can make changes. MATERIAL: a new place where assistant traffic "
                "is processed.",
            ),
            # D-699.
            Revision(
                "17",
                True,
                "D-699: the payments row says Razorpay also takes automatic top-ups on an "
                "approval the client gives, refunds and chargebacks, and receives the "
                "approving member's name, email and mobile for automatic top-ups. MATERIAL: "
                "a sub-processor receives personal data for a new purpose.",
            ),
            # D-700.
            Revision(
                "18",
                False,
                "D-700: the integrations row names Zoho, HubSpot and Razorpay beside Google "
                "and Meta as services a client connects to its own account, says they are "
                "the client's processors acting on its instruction and what each receives, "
                "and that only the owner connects them. NOT MATERIAL: no company processes "
                "data for us that did not before; each acts only for a client that "
                "connects it.",
            ),
        ),
        effective_date="2026-09-02",
    ),
    LegalDocumentSpec(
        slug="refunds",
        title="Refunds & Cancellation",
        blocking=False,
        revisions=(
            Revision("1", True, "First published draft of the client-facing legal set."),
            Revision(
                "2",
                False,
                "Published. The set came out of draft on 2 September 2026: every "
                "placeholder in the bundle was filled, the entity narration and the "
                "internal blocker names came out of the prose, and the pending-review "
                "banner came off. Non-material — nothing anybody agreed to changed "
                "meaning, and the review-state flip re-demands the set on its own.",
            ),
            Revision(
                "3",
                False,
                "The published principal place of business was reduced to the city, "
                "state and country: the street lines were the founder's home address "
                "and no identification duty asks for them. Non-material — the "
                "identification is narrower, and nothing anybody agreed to changed "
                "meaning.",
            ),
            Revision(
                "4",
                True,
                "Section 1 gained the same credit-lot promise the Terms now carry, which "
                "is what makes an unused balance in this policy a determinate amount: a "
                "top-up is spent at the rates it was bought at. MATERIAL — it changes "
                "what the refundable balance in a policy about money means.",
            ),
            # D-699.
            Revision(
                "5",
                True,
                "D-699: unused credit is forfeited when the account closes (and on an "
                "Acceptable Use termination) instead of refunded; a top-up taken in error "
                "is refundable up to its unspent part; section 6 says what a dispute pauses "
                "and holds. MATERIAL: a client loses money they might have expected back.",
            ),
        ),
        effective_date="2026-09-02",
    ),
    LegalDocumentSpec(
        slug="grievance",
        title="Grievance Redressal",
        blocking=False,
        revisions=(
            Revision("1", True, "First published draft of the client-facing legal set."),
            Revision(
                "2",
                False,
                "Published. The set came out of draft on 2 September 2026: every "
                "placeholder in the bundle was filled, the entity narration and the "
                "internal blocker names came out of the prose, and the pending-review "
                "banner came off. Non-material — nothing anybody agreed to changed "
                "meaning, and the review-state flip re-demands the set on its own.",
            ),
            Revision(
                "3",
                False,
                "The published principal place of business was reduced to the city, "
                "state and country: the street lines were the founder's home address "
                "and no identification duty asks for them. Section 1 also stopped "
                "calling that address the place a legal notice is served — a city "
                "cannot be served on, and the Terms already route service to email. "
                "Non-material — the identification is narrower and the serving claim "
                "was one the Terms contradicted.",
            ),
        ),
        effective_date="2026-09-02",
    ),
    LegalDocumentSpec(
        slug="cookies",
        title="Cookies & Tracking",
        blocking=False,
        revisions=(
            Revision("1", True, "First published draft of the client-facing legal set."),
            Revision(
                "2",
                False,
                "Published. The set came out of draft on 2 September 2026: every "
                "placeholder in the bundle was filled, the entity narration and the "
                "internal blocker names came out of the prose, and the pending-review "
                "banner came off. Non-material — nothing anybody agreed to changed "
                "meaning, and the review-state flip re-demands the set on its own.",
            ),
            Revision(
                "3",
                False,
                "The client session cookie's stated lifetime was corrected (D-539). It "
                "now lasts until the session row's own final expiry rather than until "
                "the browser closes, so it survives a phone putting the tab to sleep; "
                "the operator cookie is unchanged and still ends with the browser. "
                "Non-material — a factual description in a notice nobody accepts, and "
                "the server-side bounds it describes (12h/14d, 30min/8h) did not move.",
            ),
            # D-679.
            Revision(
                "4",
                False,
                "The edge network in front of the site is described by its role rather than "
                "named (D-679). Non-material: what is recorded and why did not change.",
            ),
        ),
        effective_date="2026-09-02",
    ),
)

#: The four a client must accept. Derived, never a second list to keep in step.
BLOCKING_SLUGS: tuple[str, ...] = tuple(doc.slug for doc in DOCUMENTS if doc.blocking)

#: Every slug this server will accept a row for. A POST naming anything else is refused
#: before it reaches the table, which is what keeps the ledger's `document_slug` a closed
#: vocabulary without a CHECK constraint that a new document would have to migrate past.
ACCEPTABLE_SLUGS: frozenset[str] = frozenset(BLOCKING_SLUGS)


def document(slug: str) -> LegalDocumentSpec | None:
    """Resolve a slug. A linear scan over eight entries rather than a dict, for the
    reason `apps/web/src/lib/legal/index.ts::legalDocument` gives: the argument comes off
    a URL or a request body, and a keyed lookup with such a value is the prototype hazard
    `lib/lookup.ts` exists to refuse."""
    return next((doc for doc in DOCUMENTS if doc.slug == slug), None)


def reacceptance_required(spec: LegalDocumentSpec, accepted_version: str | None) -> bool:
    """Must this organisation accept `spec` again before it may operate?

    The whole versioning rule, in one predicate, so the gate, the screen and the tests
    cannot each have their own reading of it:

    * **Never accepted** — yes. There is nothing to compare.
    * **Accepted the current version** — no.
    * **The REVIEW STATE changed** — yes, always. A provisional acceptance of an
      unreviewed draft is not an acceptance of the lawyer-reviewed document that replaced
      it; the client agreed to something whose blanks were visible on the page. This is
      what makes the `PENDING_LEGAL_REVIEW` flip re-demand the whole set without a
      special case anywhere.
    * **A revision this file does not know** — yes. A row naming a revision that is not
      in the history is one we cannot prove was superseded only by cosmetic changes, and
      the safe answer to "we cannot tell" is to ask again. (It is reachable: a revision
      deleted from the history by a later edit, or a database restored across a rollback.)
    * **Otherwise** — yes iff any revision AFTER the accepted one is material. Stepping
      over two cosmetic revisions is still no; one material revision anywhere in the
      chain is yes, even if the newest revision is cosmetic.
    """
    if accepted_version is None:
        return True
    if accepted_version == spec.current_version:
        return False
    accepted_revision, accepted_provisional = _split(accepted_version)
    if accepted_provisional != PENDING_LEGAL_REVIEW:
        return True
    known = [rev.revision for rev in spec.revisions]
    if accepted_revision not in known:
        return True
    index = known.index(accepted_revision)
    return any(rev.material for rev in spec.revisions[index + 1 :])


def changed_since(spec: LegalDocumentSpec, accepted_version: str | None) -> bool:
    """Has the document moved since this acceptance, materially or not? Drives the
    banner; `reacceptance_required` drives the gate."""
    return accepted_version is not None and accepted_version != spec.current_version


__all__ = [
    "ACCEPTABLE_SLUGS",
    "BLOCKING_SLUGS",
    "DOCUMENTS",
    "PENDING_LEGAL_REVIEW",
    "PRE_REVIEW_SUFFIX",
    "LegalDocumentSpec",
    "Revision",
    "changed_since",
    "document",
    "is_provisional",
    "reacceptance_required",
    "version_of",
]
