"""What one business does with its callers, as the agent builders read it.

The business copy run judges each business once (`tenancy/business_copy.Capabilities`, with
its objections, what it calls its callers and its example questions). The starters, the call
plans, the script switches, the calendar reminder and the practice callers all need the same
few answers from it, so they read this one small, hashable value rather than each parsing
the stored copy. Hashable so a starter built for it can be cached like the catalogue.

THE UNKNOWN RULE carries through unchanged: every flag is None until the business is
judged, and a consumer then does exactly what it did before the profile existed. Only False
withdraws anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.tenancy.business_copy import GeneratedCopy, parse_stored


@dataclass(frozen=True, slots=True)
class BusinessFit:
    takes_bookings: bool | None = None
    takes_orders: bool | None = None
    quotes_prices: bool | None = None
    has_premises: bool | None = None
    sells: bool | None = None
    #: (what the caller says, in the copy's call language; how to answer, English). None
    #: until a copy that was asked for them exists; empty when the business meets none.
    objections: tuple[tuple[str, str], ...] | None = None
    #: The language `objections`' caller lines are written in.
    language: str | None = None
    caller_noun: str | None = None
    #: English questions this business's callers ask.
    example_questions: tuple[str, ...] = ()
    #: The copy's own sentences for the agent's goal and role (English).
    call_goal: str | None = None
    agent_role: str | None = None

    @property
    def books(self) -> bool | None:
        """Whether callers book or order anything: False only when both are judged False,
        True when either is True, otherwise unknown."""
        if self.takes_bookings is False and self.takes_orders is False:
            return False
        if self.takes_bookings or self.takes_orders:
            return True
        return None

    @property
    def offer_noun(self) -> str | None:
        """What a caller books or orders, with its article, when the judgement says which;
        None when it does not (unknown, or neither)."""
        if self.takes_bookings and self.takes_orders:
            return "a booking or order"
        if self.takes_orders and self.takes_bookings is False:
            return "an order"
        if self.takes_bookings and self.takes_orders is False:
            return "a booking"
        return None

    def brief_text(self) -> str:
        """What a model writing for this business (a script, practice callers) is told about
        it, in English; empty while nothing is judged or written. Only what was judged is
        said, so an unjudged business's brief is what it was before the profile existed."""
        lines: list[str] = []
        said: list[str] = []
        if self.books is False:
            said.append("it takes no bookings or orders, so nothing offers one")
        else:
            if self.takes_bookings:
                said.append("callers book times with it")
            if self.takes_orders:
                said.append("callers order from it")
        if self.sells is False:
            said.append("it sells nothing to its callers, so no talk of buying or a sale")
        if self.quotes_prices is False:
            said.append("it does not tell callers prices, so no line quotes or asks one")
        if self.has_premises is False:
            said.append("callers never visit it in person")
        if said:
            lines.append("What this business does with its callers: " + "; ".join(said) + ".")
        if self.caller_noun:
            lines.append(f"It calls the people on its calls: {self.caller_noun}.")
        if self.example_questions:
            lines.append(
                "Questions its callers really ask: "
                + " ".join(q if q.endswith("?") else f"{q}?" for q in self.example_questions)
            )
        if self.objections:
            lines.append(
                "Push-back its callers really raise (the caller's words, then how to answer): "
                + " ".join(f'"{said}" {does}' for said, does in self.objections)
            )
        return "\n".join(lines)


UNKNOWN: Final = BusinessFit()


def fit_of(copy: GeneratedCopy | None, *, language: str | None = None) -> BusinessFit:
    """The fit a stored copy describes; `UNKNOWN` for no copy. A copy written before the
    capability profile keeps every flag None but still lends its own goal and role."""
    if copy is None:
        return UNKNOWN
    caps = copy.capabilities
    placeholders = copy.placeholders
    return BusinessFit(
        takes_bookings=caps.takes_bookings.applies if caps else None,
        takes_orders=caps.takes_orders.applies if caps else None,
        quotes_prices=caps.quotes_prices.applies if caps else None,
        has_premises=caps.has_premises.applies if caps else None,
        sells=caps.sells.applies if caps else None,
        objections=(
            None
            if copy.objections is None
            else tuple((o.caller_says, o.how_to_answer) for o in copy.objections)
        ),
        language=language,
        caller_noun=copy.caller_noun,
        example_questions=tuple(copy.example_questions),
        call_goal=placeholders.call_goal,
        agent_role=placeholders.agent_role,
    )


async def business_fit(session: AsyncSession, tenant_id: UUID | None = None) -> BusinessFit:
    """The account's fit. Scoped by RLS, and by `tenant_id` too when given, so an operator's
    session scoped to the tenant reads the same row (`business_copy.capabilities_for`)."""
    sql = "SELECT generated, language FROM business_copies"
    params: dict[str, object] = {}
    if tenant_id is not None:
        sql += " WHERE tenant_id = :tid"
        params["tid"] = tenant_id
    row = (await session.execute(text(sql), params)).first()
    if row is None:
        return UNKNOWN
    return fit_of(parse_stored(row[0]), language=None if row[1] is None else str(row[1]))


__all__ = ["UNKNOWN", "BusinessFit", "business_fit", "fit_of"]
