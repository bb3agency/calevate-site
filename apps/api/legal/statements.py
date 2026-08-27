"""The exact wording an owner ticks, and the version a stored row names.

It lives HERE rather than in the React component that renders it, for the reason
`compliance/whatsapp_optin.ALERT_NOTICE_TEXT` gives: a `statement_version` in a database
row is only evidence if the wording it names can still be produced years later, and a
string that lives only in a screen cannot be. The console renders what this module
returns; it never carries its own copy.

Two statements, because there are two states of the world and they are not the same
promise. Which one is in force is decided by `catalogue.PENDING_LEGAL_REVIEW`, so the
version string moves with the documents' own version rather than being bumped separately.

═══ WHAT THE PROVISIONAL WORDING MAY AND MAY NOT SAY ═══

`docs/LEGAL-SURFACE.md` findings F-11..F-15 are five occasions on which a client-facing
sentence in this product claimed something the product does not do, and every one of them
survived review because it read as reassurance. The rule §6 of that document states —
"invents no company identity anywhere in the prose" — binds this text too. So:

* it does not give an effective date, because the documents have none
  (`catalogue.effective_date` is None for every document, because `{{EFFECTIVE_DATE}}`
  is an unfilled placeholder in the bundle);
* it does not NAME which facts are still blank. Which placeholders carry a value is
  decided in `apps/web/src/lib/legal/placeholders.ts` and it moves — the entity name and
  the GST position were both answered while this file was being written — so a list here
  would be a claim about another module's current state, asserted from memory and stale
  the next time somebody fills one in (hard rule 11). The screen shows the reader the
  markers on the document itself, which is the copy that cannot go out of date;
* it does not describe the acceptance as binding, a signature, or a contract, because
  LEGAL-OPS-PLAYBOOK.md:481 says in terms that *"Templates + draft banner are not a
  defence"* and nobody has yet had these documents reviewed;
* it does not quantify what is missing, for the same reason and from the same source:
  `unresolvedPlaceholders()` counts them, in a module this one cannot read.

What it DOES say is the whole truth available: these are drafts, several facts in them are
still blank and visible on the page, what you are recording is that you have read them and
will operate under them as they stand, and you will be asked again when the reviewed
versions are published.
"""

from __future__ import annotations

from apps.api.legal.catalogue import PENDING_LEGAL_REVIEW, version_of

#: Bump WITH the text, never separately — two deployments whose `acceptance-v1` says
#: different things is the one failure `statement_version` exists to prevent. The review
#: state is carried by `version_of`, exactly as it is for a document, so a stored row says
#: which of the two statements below the person actually read.
_STATEMENT_REVISION = "1"

PROVISIONAL_STATEMENT = (
    "I accept the Terms of Service, the Privacy Policy, the Data Processing Addendum and "
    "the Acceptable Use Policy on behalf of this business, and I confirm I am authorised "
    "to do so. I understand that these are drafts: they have not been reviewed by a "
    "lawyer, and some of the facts they need are still blank and are shown as markers on "
    "the page. I understand that Calevate will ask me to accept these documents again "
    "when the reviewed versions are published."
)

REVIEWED_STATEMENT = (
    "I accept the Terms of Service, the Privacy Policy, the Data Processing Addendum and "
    "the Acceptable Use Policy on behalf of this business, and I confirm I am authorised "
    "to do so."
)

#: The sentence the SCREEN leads with, above the documents. Server-authored for the reason
#: `lib/api/aiQuota.ts` states about every other verdict on a console screen: the browser
#: must not compose the explanation of a state the server decided.
PROVISIONAL_NOTICE = (
    "These documents are drafts. They have not been through legal review, and some of the "
    "facts they need are still blank — where that is so, the document shows a marker in "
    "double braces instead of the missing detail. Accepting them records that you have "
    "read them and will operate under them as they stand. It does not replace the "
    "reviewed versions: when those are published, we will ask you to accept them again."
)


def statement_text() -> str:
    """The wording in force."""
    return PROVISIONAL_STATEMENT if PENDING_LEGAL_REVIEW else REVIEWED_STATEMENT


def statement_version() -> str:
    """The version a row records for the wording in force."""
    return version_of(_STATEMENT_REVISION)


__all__ = [
    "PROVISIONAL_NOTICE",
    "PROVISIONAL_STATEMENT",
    "REVIEWED_STATEMENT",
    "statement_text",
    "statement_version",
]
