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

WHAT THAT GUARD DOES NOT PROVE, SAID PLAINLY. It compares IDENTITY, not TEXT. Nothing in
this tree can read the prose of a TypeScript module from Python without a TS parser, so a
lawyer editing a clause in `terms.ts` without bumping `revision` here produces an
acceptance row naming a version whose words have changed, and no check sees it. The
discipline that closes it is human and is written at the top of `REVISIONS`: an edit to a
document's operative text is a new revision. `PENDING_LEGAL_REVIEW` is the half that IS
mechanical, and it is the half that matters most today.

--------------------------------------------------------------------------------
THE VERSION CARRIES THE REVIEW STATE, WHICH IS WHY THE FLIP NEEDS NO SPECIAL CASE
--------------------------------------------------------------------------------

`apps/web/src/lib/legal/placeholders.ts` sets `PENDING_LEGAL_REVIEW = true`: these
documents have not been through legal review and nearly every fact in them — the
supplier's registered name, its GSTIN, the named Grievance Officer, the DLT telemarketer
id — is still a visible blank. LEGAL-OPS-PLAYBOOK.md:481 is blunt about what that means
commercially: *"Templates + draft banner are not a defence."*

So acceptance is built in full and is PROVISIONAL, and the review state is part of the
version string rather than a flag beside it:

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
#: a name on it.
PENDING_LEGAL_REVIEW = True

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
    #: None for every document today, and that is a FACT rather than a gap in this file:
    #: `{{EFFECTIVE_DATE}}` is an unfilled placeholder in the bundle, so the documents
    #: carry no effective date and the screen says so. Inventing one here would be a date
    #: the published page does not show (hard rule 11).
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
        ),
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
        ),
    ),
    LegalDocumentSpec(
        slug="acceptable-use",
        title="Acceptable Use",
        blocking=True,
        revisions=(Revision("1", True, "First published draft of the client-facing legal set."),),
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
        ),
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
        ),
    ),
    LegalDocumentSpec(
        slug="refunds",
        title="Refunds & Cancellation",
        blocking=False,
        revisions=(Revision("1", True, "First published draft of the client-facing legal set."),),
    ),
    LegalDocumentSpec(
        slug="grievance",
        title="Grievance Redressal",
        blocking=False,
        revisions=(Revision("1", True, "First published draft of the client-facing legal set."),),
    ),
    LegalDocumentSpec(
        slug="cookies",
        title="Cookies & Tracking",
        blocking=False,
        revisions=(Revision("1", True, "First published draft of the client-facing legal set."),),
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
