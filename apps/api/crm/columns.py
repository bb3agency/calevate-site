"""WHICH COLUMNS this client is looking at — the one answer the screen and the file share.

SURFACES §2 asks for a "column chooser mirrored in CSV export (choose-what-you-export,
Outpero parity)". The word that carries the weight is *mirrored*: a chooser that changes
the table and not the download is not a smaller feature, it is a screen and a file that
disagree about the same request — and this route is the one that carries a whole contact
list out of the building in one click (`crm.routes.export_leads`, role-gated + audited).

So the mirroring is structural rather than promised. There is exactly one registry of
selectable columns, exactly one resolver (`resolve`), and both `list_leads_page` and
`export_leads_csv` call it with the same arguments. Neither surface owns a column list
of its own, so neither can grow one the other does not have. `tests/lead_columns_test.py`
pins the property from the outside anyway — the header of the file equals the columns of
the page — because a structural argument that nothing checks is a comment.

**The registry is per-agent, not global.** The extraction schema IS the Leads table's
column list (TRD §7 (c)) and it differs per agent and per tenant, so `available()` takes
the fields the caller already resolved and splices them into the fixed columns. A
hard-coded field list would be wrong the day a second vertical lands.

**What the fixed half is, and why it grew.** Before this module the screen rendered
name/phone/status/owner + schema + calls/updated, and the export wrote
phone/name/status/source/calls/created_at + schema. Two overlapping, hand-maintained
lists — the export had `source` and `created_at` the screen never showed, the screen had
`owner` and `updated_at` the file never held. The union is the registry, and the export
query now carries the owner join so both halves can answer for every column. That widens
the default export by two columns; the alternative was per-surface defaults, which is two
ways to answer one question and is how the two lists drifted in the first place.

**A dropped COLUMN is not a dropped FILTER, and the asymmetry is deliberate.** An
unknown column key is dropped silently here (and reported in `dropped`): it narrows the
file, it is applied identically to the screen and the file, and a saved view or a
bookmark that outlives one edit of the extraction schema should keep working. An unknown
FILTER key is refused by the route instead, because dropping a filter WIDENS the set —
somebody narrows the table to eleven leads, presses Export and mails a supplier the whole
contact list. `crm.routes` states that rule where it enforces it.

Industry check, because saved views and column choosers are old problems: Jira's answer
to a deleted custom field is that "filters, dashboards and automation rules break" and an
integrity checker cleans up the dangling references afterwards
(https://confluence.atlassian.com/adminjiraserver/editing-or-deleting-custom-fields-1047552719.html,
https://jira.atlassian.com/browse/JRA-4423). That is the standard and it is beatable at
no cost: resolving against the CURRENT schema on every read means a stale reference
degrades to a missing column and a sentence, never a 500 and never a repair job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from calevate_shared.extraction import ExtractionField, FieldType

ColumnKind = Literal["fixed", "extraction"]


@dataclass(frozen=True, slots=True)
class LeadColumn:
    """One selectable column of the Leads table.

    `row_key` is the name of the SQL column that holds it in `crm.service._LEAD_COLUMNS`
    — a NAME rather than a tuple index, because an index is a second place the select
    list's order is written down and the first one to go stale. Extraction columns carry
    `row_key=None` and are read out of the `data` JSONB under `key`.
    """

    key: str
    label: str
    kind: ColumnKind
    type: FieldType
    row_key: str | None = None
    #: Declared values, for an `enum` column. Drives the facet list (`crm.service`).
    enum_values: tuple[str, ...] = ()


# The fixed columns, split around the extraction fields so a client's own capture list
# lands in the middle of the table rather than after the timestamps. Order here IS the
# default column order of both the screen and the file.
#
# `phone` is ONE column rendered ONE way on both surfaces — `LeadOut.phone_e164` on the
# wire, `l.phone_e164` in the file. It used to be the same column under two rules (full
# in the export, dotted on the screen), which is exactly the screen/file disagreement
# this registry exists to make impossible; D-436 removed the second rule.
_LEADING_FIXED: tuple[LeadColumn, ...] = (
    LeadColumn("name", "Name", "fixed", "text", row_key="name"),
    LeadColumn("phone", "Phone", "fixed", "text", row_key="phone_e164"),
    LeadColumn(
        "status",
        "Status",
        "fixed",
        "enum",
        row_key="status",
        # D-21's fixed six. Declared here so the chooser can describe the column, NOT so
        # it can be faceted — status already has its own chip row and its own truthful
        # per-status counts (`LeadListOut.status_counts_matching_search`), and a second
        # control for one filter is the defect even when both work.
        enum_values=("new", "contacted", "interested", "hot", "won", "lost"),
    ),
    LeadColumn("owner", "Owner", "fixed", "text", row_key="assigned_to_name"),
    LeadColumn(
        "source",
        "Source",
        "fixed",
        "enum",
        row_key="source",
        enum_values=("inbound_call", "webhook", "campaign", "manual"),
    ),
)

_TRAILING_FIXED: tuple[LeadColumn, ...] = (
    LeadColumn("calls", "Calls", "fixed", "number", row_key="call_count"),
    LeadColumn("created_at", "Created", "fixed", "date", row_key="created_at"),
    LeadColumn("updated_at", "Updated", "fixed", "date", row_key="updated_at"),
)

#: Keys the registry reserves for itself. An extraction field may not take one — see
#: `available`.
FIXED_KEYS: frozenset[str] = frozenset(c.key for c in _LEADING_FIXED + _TRAILING_FIXED)


def available(fields: list[ExtractionField]) -> tuple[LeadColumn, ...]:
    """Every column this request may choose from, in default order.

    A schema field whose key collides with a fixed one is DROPPED rather than allowed to
    shadow it. `ExtractionField.key` is `^[a-z][a-z0-9_]{0,39}$` and nothing stops an
    admin naming a field `status`, at which point one key would mean two columns and the
    export's own header would not say which. Fixed wins because it is the one the
    filters, the counts and the timeline are already keyed on.
    """
    extraction = tuple(
        LeadColumn(
            key=f.key,
            label=f.label,
            kind="extraction",
            type=f.type,
            enum_values=tuple(f.enum_values or ()),
        )
        for f in fields
        if f.key not in FIXED_KEYS
    )
    return _LEADING_FIXED + extraction + _TRAILING_FIXED


def facetable(columns: tuple[LeadColumn, ...]) -> tuple[LeadColumn, ...]:
    """The columns a facet panel may offer: the EXTRACTION enum fields, and only those.

    Extraction-driven, per the slice's own requirement — a hard-coded facet list is
    wrong the moment a second vertical lands. `status` is excluded although it is an
    enum, because it already has a dedicated chip row and dedicated counts; `source` is
    excluded for the narrower reason that it is a four-value SYSTEM field describing how
    a row reached us rather than something the client captured, and facets are for the
    client's own vocabulary.
    """
    return tuple(c for c in columns if c.kind == "extraction" and c.type == "enum")


@dataclass(frozen=True, slots=True)
class Resolved:
    """The columns to render, and the keys that were asked for and no longer exist."""

    columns: tuple[LeadColumn, ...]
    dropped: tuple[str, ...]


def resolve(columns: tuple[LeadColumn, ...], requested: list[str] | None) -> Resolved:
    """The chooser's answer: which of `columns`, in which order.

    `requested is None` means "no choice was made" and yields everything — the shape a
    client who has never opened the chooser gets, and the shape the export had before
    this existed.

    The REQUESTED order is preserved rather than the registry's. A chooser that cannot
    move a column is half a chooser, and the alternative (sort back into registry order)
    would silently discard a saved view's arrangement.

    An all-unknown selection falls back to everything instead of producing a file with
    no columns in it. That is the one case where "what you see" cannot be honoured, and
    a header-less CSV would be a worse answer than a wide one — the caller still learns
    what happened from `dropped`.
    """
    if requested is None:
        return Resolved(columns=columns, dropped=())
    by_key = {c.key: c for c in columns}
    chosen: list[LeadColumn] = []
    seen: set[str] = set()
    dropped: list[str] = []
    for key in requested:
        if key in seen:
            continue
        seen.add(key)
        column = by_key.get(key)
        if column is None:
            dropped.append(key)
        else:
            chosen.append(column)
    if not chosen:
        return Resolved(columns=columns, dropped=tuple(dropped))
    return Resolved(columns=tuple(chosen), dropped=tuple(dropped))


__all__ = [
    "FIXED_KEYS",
    "ColumnKind",
    "LeadColumn",
    "Resolved",
    "available",
    "facetable",
    "resolve",
]
