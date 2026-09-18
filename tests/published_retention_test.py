"""The retention periods we ENFORCE and the ones we PUBLISH have to be the same set.

**WHY THIS FILE EXISTS.** `caller_memory` — what an agent remembers about a CALLER between
calls — was seeded at 180 days, swept nightly by its own arm, disclosed in the DPA and in
the sub-processor register, and named in the sentence the agent speaks at the start of the
call. The one place it was missing was the retention table on `/legal/privacy`, which is
the document the caller themselves reads. It is also the only category on that page whose
subject IS the caller rather than the client's staff, so it was the one omission that
mattered most, and nothing in the tree could see it: the periods lived in
`scripts/seed.DEFAULT_RETENTION_POLICIES` as data and in `privacy.ts` as prose, and prose
does not fail a build.

**SO THIS IS AN EQUALITY, NOT A SUBSET.** A category seeded and not published is an
undisclosed retention period. A category published and not seeded is a promise no sweep
keeps — the worse of the two, because it reads as a control that exists. Both fail here.

**AND THE NUMBER IS CHECKED, not only the row.** The published period is asserted to state
the seeded `ttl_days`, so shortening a period in the seed without correcting the page fails
in the same place. `consent_log` carries no number by design: it is an append-only ledger
(hard rule 4) that nothing expires on a timer, which is published as "Retained".

**A NOTE ON WHAT THIS CANNOT SEE.** It compares the SEEDED defaults against the page, not
a live tenant's rows — a client may lengthen their own periods, and the page says so in the
paragraph above the table. What it does guarantee is that every category the product knows
how to expire is a category the reader has been told about.

⚠ EDITING `privacy.ts` IS EDITING A PUBLISHED LEGAL DOCUMENT. `apps/web/tests/
legalContentHash.test.ts` pins the operative text of each revision, so a change to the
table needs a new revision with its hash in `versions.ts` AND in `apps/api/legal/
catalogue.py`. That is a different guard in a different language; this one only watches the
numbers.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.seed import DEFAULT_RETENTION_POLICIES

PRIVACY_TS = (
    Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "lib" / "legal" / "privacy.ts"
)

#: The categories that are deliberately published with no number, and why. Keyed per
#: CATEGORY rather than "anything may be null", so the next category that arrives without a
#: period has to come here and say what it is.
PUBLISHED_WITHOUT_A_PERIOD: dict[str, str] = {
    "consent_log": (
        "an append-only ledger (hard rule 4). Nothing expires it on a timer, and the seed "
        "carries a ttl only so the category is explicit rather than forgotten — "
        "`_apply_one` returns before touching it. 'Retained' is the honest publication"
    ),
}

_ENTRY = re.compile(
    r'category:\s*"(?P<category>[a-z_]+)",\s*days:\s*(?P<days>null|\d+),\s*'
    r"label:(?P<label>.*?)period:\s*(?P<period>(?:\s*\"[^\"]*\"\s*\+?)+),",
    re.DOTALL,
)


def _published() -> dict[str, tuple[int | None, str]]:
    """category -> (published days, published period text), read off the page itself.

    Parsed from the SOURCE rather than imported, because the source is TypeScript and this
    suite is Python — and because the thing under test is what a reader is shown, which is
    a property of that file and not of any object this process can build.
    """
    source = PRIVACY_TS.read_text(encoding="utf-8")
    start = source.index("export const PUBLISHED_RETENTION")
    block = source[start : source.index("\n];", start)]
    found = {
        match["category"]: (
            None if match["days"] == "null" else int(match["days"]),
            "".join(re.findall(r'"([^"]*)"', match["period"])),
        )
        for match in _ENTRY.finditer(block)
    }
    assert found, "no published retention rows were parsed; the page's shape changed"
    return found


def test_every_enforced_retention_period_is_published() -> None:
    """The equality. A seeded category missing from the page is an undisclosed period."""
    seeded = {row["data_category"]: int(row["ttl_days"]) for row in DEFAULT_RETENTION_POLICIES}
    published = _published()
    assert set(published) == set(seeded), (
        "the retention periods this product enforces and the ones it publishes disagree.\n"
        f"  enforced but unpublished: {sorted(set(seeded) - set(published))}\n"
        f"  published but unenforced: {sorted(set(published) - set(seeded))}"
    )


def test_every_published_period_states_its_seeded_number() -> None:
    """A row on the page is worth the number on it. `1095 days (three years)` counts."""
    seeded = {row["data_category"]: int(row["ttl_days"]) for row in DEFAULT_RETENTION_POLICIES}
    for category, (days, period) in sorted(_published().items()):
        if category in PUBLISHED_WITHOUT_A_PERIOD:
            assert days is None, f"{category} is published with a period; drop its exemption"
            assert period == "Retained", f"{category} publishes {period!r}, not 'Retained'"
            continue
        assert days == seeded[category], (
            f"/legal/privacy publishes {days} days for {category} and the seed installs "
            f"{seeded[category]}"
        )
        assert period.startswith(f"{days} days"), (
            f"{category} carries days={days} beside a period that reads {period!r}"
        )


def test_the_published_table_is_rendered_from_that_list() -> None:
    """The rows a reader sees come FROM `PUBLISHED_RETENTION` and are not a second copy.

    Without this the pin above is defeated by the least suspicious edit available: adding a
    category to the const, leaving the table's own rows inlined as they used to be, and
    publishing nothing. Two lists in one file that must agree is the drift this repo's
    "one way per problem" rule refuses.
    """
    source = PRIVACY_TS.read_text(encoding="utf-8")
    assert "rows: PUBLISHED_RETENTION.map(" in source, (
        "the retention table no longer renders from PUBLISHED_RETENTION, so the equality "
        "test above proves nothing about what is on the page"
    )


def test_the_period_whose_subject_is_the_caller_is_on_the_page() -> None:
    """`caller_memory` by name, because it is the omission this file was written for.

    Named explicitly rather than left to the equality: the equality passes the day somebody
    deletes the row AND the seed entry together, which would be a retention period silently
    removed from a caller-facing document. This one has a spoken notice and a DPA clause
    behind it, so it does not leave quietly.
    """
    days, period = _published()["caller_memory"]
    assert days == 180 and period.startswith("180 days")
