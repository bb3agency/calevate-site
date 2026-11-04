"""The business profile's own words for ONE business: its labels, hints and examples.

A business of any kind fills in the same eight steps, so the platform cannot name what it
offers, whether it charges a price, how people go ahead with it, or give an example of any
of them: a clinic's "Consultation, ₹500" is nonsense to a farmers' bookkeeping app, and a
price column is nonsense to a business that quotes none. The model writes these once from
what the business says about itself (its "Meet your agent" brief and what it sells,
`agents/starter_plans.business_known`), and again whenever that changes. Until it has,
every screen shows `NEUTRAL`: generic English labels and no example at all, never another
trade's.

Stored on `organizations.profile_wording` as `{"known": <digest>, "wording": {...}}`,
written by `workers/profile_wording`. `known` is the description it was written from, so a
read can tell a stale draft from a current one and queue the next (`read_wording`): there is
no backfill, an account that predates this gets its draft the first time its profile is read.

Display only. Nothing here reaches an agent's prompt or changes what is stored in the
profile: hiding the price column keeps every price already on file.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final
from uuid import UUID

from pydantic import ConfigDict, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.starter_plans import business_known
from apps.api.core.schemas import Strict
from apps.api.reliability.service import enqueue_outbox_once
from apps.api.tenancy.business_copy import screen_text_problems

#: The ARQ job that writes it (`workers/profile_wording`).
WRITE_JOB: Final = "write_profile_wording"

#: A column label or a short field label.
LABEL_MAX: Final = 24
#: A step's heading, as a question.
TITLE_MAX: Final = 60
#: A step's one line under its heading.
HINT_MAX: Final = 120
#: An example inside an empty field.
EXAMPLE_MAX: Final = 80
#: The booking rules example is prose, like the field it sits in.
PROSE_EXAMPLE_MAX: Final = 300

#: A price example, as the profile form takes a price: whole rupees, digits only.
_PRICE: Final = re.compile(r"^[1-9][0-9]{0,8}$")


class _Frozen(Strict):
    model_config = ConfigDict(frozen=True)


class ProfileExamples(_Frozen):
    """The examples inside the profile's empty fields; None shows no example."""

    branch_label: str | None = None
    offer_name: str | None = None
    #: Digits only, like the price it shows how to type.
    offer_price: str | None = None
    offer_note: str | None = None
    faq_question: str | None = None
    staff_name: str | None = None
    staff_spoken: str | None = None
    staff_role: str | None = None
    booking_rules: str | None = None
    contact_name: str | None = None


#: Each example key's cap.
EXAMPLE_CAPS: Final[dict[str, int]] = {
    key: PROSE_EXAMPLE_MAX if key == "booking_rules" else EXAMPLE_MAX
    for key in ProfileExamples.model_fields
}


class ProfileWording(_Frozen):
    """What the profile's business-specific words are for one business."""

    #: What one thing it offers is called, as a column label: "Service", "Plan", "Course".
    offer_label: str
    #: What its price is called ("Price", "Fee", "Monthly fee"); None when it quotes none,
    #: and the price column is not shown.
    price_label: str | None
    #: The "What do you offer?" step's line.
    offers_hint: str
    #: The booking step's heading and line: how a caller goes ahead with THIS business
    #: (books, orders, signs up, visits).
    booking_title: str
    booking_hint: str
    examples: ProfileExamples
    #: False while the neutral wording stands in for a draft not yet written.
    drafted: bool


#: Before a draft exists, and for any part of one that broke a rule: generic English and
#: no example. An instruction reads as an instruction; another trade's example reads as a
#: mistake about this business.
NEUTRAL: Final = ProfileWording(
    offer_label="Service",
    price_label="Price",
    offers_hint="What callers can ask about. Add a price where you give one.",
    booking_title="How do callers go ahead?",
    booking_hint="What a caller should know before they book, buy or sign up.",
    examples=ProfileExamples(),
    drafted=False,
)

#: The text fields a draft writes, with their caps. `price_label` may also be empty.
_TEXT_CAPS: Final[dict[str, int]] = {
    "offer_label": LABEL_MAX,
    "price_label": LABEL_MAX,
    "offers_hint": HINT_MAX,
    "booking_title": TITLE_MAX,
    "booking_hint": HINT_MAX,
}


def _one_line(value: Any, cap: int) -> str | None:
    """`value` as one trimmed line within `cap`, or None when it is not a usable string.
    Over the cap is unusable rather than cut: a label cut mid-word reads as a defect."""
    if not isinstance(value, str):
        return None
    line = " ".join(value.split())
    return line if line and len(line) <= cap else None


def _kept(path: str, value: Any, cap: int, *, clinic: bool) -> str | None:
    line = _one_line(value, cap)
    if line is None or screen_text_problems(path, line, clinic=clinic):
        return None
    return line


def clean_wording(raw: Any, *, clinic: bool) -> ProfileWording | None:
    """The model's answer as wording, or None when it is not the shape asked for.

    A part that breaks a rule of text a client reads (`screen_text_problems`), runs over its
    cap or is blank falls back to `NEUTRAL`'s, so one bad hint costs that hint, not the draft.
    An empty `price_label` is the model's answer that no price applies, and is kept as such.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("examples"), dict):
        return None
    out: dict[str, Any] = {}
    for key, cap in _TEXT_CAPS.items():
        out[key] = _kept(key, raw.get(key), cap, clinic=clinic) or getattr(NEUTRAL, key)
    price_label = raw.get("price_label")
    if isinstance(price_label, str) and not price_label.strip():
        out["price_label"] = None
    given = raw["examples"]
    examples: dict[str, str | None] = {}
    for key, cap in EXAMPLE_CAPS.items():
        examples[key] = _kept(f"examples.{key}", given.get(key), cap, clinic=clinic)
    price = examples["offer_price"]
    if out["price_label"] is None or (price is not None and not _PRICE.match(price)):
        examples["offer_price"] = None
    return ProfileWording(**out, examples=ProfileExamples(**examples), drafted=True)


def wording_to_json(known: str, wording: ProfileWording) -> str:
    return json.dumps({"known": known, "wording": wording.model_dump(exclude={"drafted"})})


def _from_row(raw: Any) -> tuple[ProfileWording, str | None]:
    """The stored draft and the description digest it was written from; `NEUTRAL` and None
    for an empty row or one a past shape no longer reads."""
    if not isinstance(raw, dict) or not isinstance(raw.get("wording"), dict):
        return NEUTRAL, None
    try:
        wording = ProfileWording.model_validate({**raw["wording"], "drafted": True})
    except ValidationError:
        return NEUTRAL, None
    known = raw.get("known")
    return wording, known if isinstance(known, str) else None


async def _queue(session: AsyncSession, *, tenant_id: UUID, known: str) -> bool:
    queued = await enqueue_outbox_once(
        session,
        job=WRITE_JOB,
        payload={"tenant_id": str(tenant_id), "known": known},
        dedupe_key=f"profile-wording:{tenant_id}:{known}",
    )
    return queued is not None


async def maybe_write_profile_wording(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Queue the wording once anything describes the business, again each time that
    changes. Deduped per description, so one change asks once."""
    known = await business_known(session, tenant_id=tenant_id)
    return known is not None and await _queue(session, tenant_id=tenant_id, known=known)


async def read_wording(session: AsyncSession, *, tenant_id: UUID) -> ProfileWording:
    """This business's wording, `NEUTRAL` until its draft lands.

    A draft written from an older description is still shown (it is about this business),
    and a draft for the current one is queued when none was: this is how an account that
    existed before drafts did gets its first, with no backfill."""
    raw = (
        await session.execute(
            text("SELECT profile_wording FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar_one_or_none()
    wording, written_for = _from_row(raw)
    known = await business_known(session, tenant_id=tenant_id)
    if known is not None and known != written_for:
        await _queue(session, tenant_id=tenant_id, known=known)
    return wording


__all__ = [
    "EXAMPLE_CAPS",
    "HINT_MAX",
    "LABEL_MAX",
    "NEUTRAL",
    "TITLE_MAX",
    "WRITE_JOB",
    "ProfileExamples",
    "ProfileWording",
    "clean_wording",
    "maybe_write_profile_wording",
    "read_wording",
    "wording_to_json",
]
