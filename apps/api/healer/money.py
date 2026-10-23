"""The evidence behind a `money_review` incident, read from rows we already hold (D-776).

The healer never moves money and a per-minute rate is only ever attested by an operator
(hard rules 7 and 11), so the three charge alarms (`engine_charge_mismatch`,
`engine_call_cost_variance`, `engine_charge_unmatched`) can only be closed by a person. What
can be automated is the investigation their "What to do" used to leave to that person:
which calls differ, what we metered, what the voice platform charged
(`calls.engine_charged_inr`, recorded by the charge reconciler), and the rate in force.

Everything here is a read. `ChargedCall.implied_rate` is the vendor's charge divided by the
billed minutes: evidence of what the posted rate probably is, labelled as such wherever it
is shown, and never an input to an attestation. The operator reads the posted rate in the
voice platform's console and types it (`copilot/admin_actions.HEALER_ATTEST_RATE`).

The worker stores `MoneyEvidence.summary()` on the incident's ledger when it escalates and
on each hourly re-check, so the diagnosis is on the healer screen before anyone asks; Pip
reads the same evidence in full through `copilot/admin_tools`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.engine_minutes import (
    EngineMinutePrice,
    attested_minute_prices,
    minute_cost_rows,
    required_wallet_fee,
)
from apps.api.billing.plans import IST
from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.core.logging import MAX_FREE_TEXT, get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.healer.playbooks import MONEY_REVIEW, PLAYBOOK_BY_KEY
from apps.workers.engine_charges import (
    CHARGE_LOOKBACK_DAYS,
    cost_with_fee,
    engine_tenants,
    within_tolerance,
)

log = get_logger(__name__)

MONEY_CODES: Final[tuple[str, ...]] = PLAYBOOK_BY_KEY[MONEY_REVIEW].triggers
UNMATCHED_CODE: Final = "engine_charge_unmatched"

#: How far before an incident opened its evidence reaches: the charge sweep's own lookback,
#: so the calls that raised the alarm are inside it.
LOOKBACK: Final = timedelta(days=CHARGE_LOOKBACK_DAYS)
#: Charged calls read per client, newest first.
CALLS_PER_TENANT: Final = 200
#: A completed call older than this with no charge recorded is one the matching missed:
#: the platform settles a call's charge after `call.analysed`, within minutes.
SETTLE_GRACE: Final = timedelta(hours=2)

_PAISA: Final = Decimal("0.01")

_CHARGED_CALLS = text(
    "SELECT c.id, coalesce(c.ended_at, c.created_at), c.engine_charged_inr, "
    f"sum(u.qty * u.unit_cost_paid) FILTER (WHERE {minute_cost_rows('u.')}), "
    "bool_or(u.unit_cost_paid IS NULL) FILTER (WHERE u.unit_type = 'platform_min'), "
    "count(u.id) FILTER (WHERE u.unit_type = 'platform_min'), "
    "max(u.meta->>'engine_rate_key') FILTER (WHERE u.unit_type = 'platform_min'), "
    "max(u.meta->>'billed_minutes') FILTER (WHERE u.unit_type = 'platform_min'), "
    "max(u.meta->>'inr_per_min') FILTER (WHERE u.unit_type = 'platform_min') "
    "FROM calls c LEFT JOIN usage_events u ON u.call_id = c.id AND u.tenant_id = c.tenant_id "
    "WHERE c.engine_charged_inr IS NOT NULL AND coalesce(c.ended_at, c.created_at) >= :since "
    "GROUP BY c.id ORDER BY 2 DESC LIMIT :cap"
)
_UNCHARGED_CALLS = text(
    "SELECT count(*) FROM calls WHERE status = 'completed' AND engine_charged_inr IS NULL "
    "AND coalesce(ended_at, created_at) >= :since "
    "AND coalesce(ended_at, created_at) < now() - make_interval(secs => :grace)"
)
_OPEN_ALARMS = text(
    "SELECT DISTINCT code FROM platform_alerts WHERE cleared_at IS NULL "
    "AND code = ANY(CAST(:codes AS text[]))"
)


def ist(at: datetime) -> str:
    """`10 Oct 18:17 IST`: how every time in this evidence is written (D-709)."""
    return at.astimezone(IST).strftime("%d %b %H:%M IST")


def _decimal(value: object) -> Decimal | None:
    try:
        return None if value is None else Decimal(str(value))
    except ArithmeticError:
        return None


@dataclass(frozen=True, slots=True)
class ChargedCall:
    tenant_id: UUID
    client: str
    call_id: UUID
    at: datetime
    #: The rate key and posted rate the meter stamped on the call's minute row.
    rate_key: str | None
    billed_minutes: Decimal | None
    stamped_rate: Decimal | None
    #: What we metered (minute row plus fee restatements and corrections); None when the
    #: minute was unpriced or never metered.
    metered_inr: Decimal | None
    charged_inr: Decimal
    #: The charge with the wallet top-up fee added: what `metered_inr` must reproduce.
    expected_inr: Decimal

    @property
    def matches(self) -> bool | None:
        if self.metered_inr is None:
            return None
        return within_tolerance(self.metered_inr, self.expected_inr)

    @property
    def implied_rate(self) -> Decimal | None:
        """The posted per-minute rate the charge implies, before the fee. Evidence only."""
        if not self.billed_minutes:
            return None
        return (self.charged_inr / self.billed_minutes).quantize(_PAISA, rounding=ROUNDING)


@dataclass(frozen=True, slots=True)
class RateFinding:
    """The differing calls on one rate key, and what they say about that rate."""

    rate_key: str
    in_force: Decimal | None
    stamped: tuple[Decimal, ...]
    implied: tuple[Decimal, ...]
    differing: int
    first_at: datetime

    @property
    def one_rate(self) -> bool:
        """Every differing call implies the same posted rate: one rate change explains them."""
        return len(self.implied) == 1


@dataclass(frozen=True, slots=True)
class MoneyEvidence:
    engine: str
    fee: Decimal
    since: datetime
    calls: tuple[ChargedCall, ...]
    rates: Mapping[str, EngineMinutePrice]
    #: Completed calls past `SETTLE_GRACE` with no charge recorded.
    uncharged: int
    open_alarms: frozenset[str]
    #: Clients whose rows could not be read; the evidence is partial when this is not zero.
    unreadable: int = 0
    read_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def differing(self) -> list[ChargedCall]:
        return [c for c in self.calls if c.matches is False]

    @property
    def matching(self) -> list[ChargedCall]:
        return [c for c in self.calls if c.matches is True]

    @property
    def unpriced(self) -> list[ChargedCall]:
        return [c for c in self.calls if c.matches is None]

    def findings(self) -> list[RateFinding]:
        by_key: dict[str, list[ChargedCall]] = {}
        for call in self.differing:
            by_key.setdefault(call.rate_key or "unknown", []).append(call)
        out = []
        for key, calls in sorted(by_key.items()):
            price = self.rates.get(key)
            out.append(
                RateFinding(
                    rate_key=key,
                    in_force=price.inr_per_min if price else None,
                    stamped=tuple(sorted({c.stamped_rate for c in calls if c.stamped_rate})),
                    implied=tuple(sorted({r for c in calls if (r := c.implied_rate) is not None})),
                    differing=len(calls),
                    first_at=min(c.at for c in calls),
                )
            )
        return out

    def one_cause(self) -> RateFinding | None:
        """The single rate every differing call points at, when there is exactly one."""
        found = self.findings()
        return found[0] if len(found) == 1 and found[0].one_rate else None

    def settled(self, code: str, *, after: datetime) -> bool:
        """Whether the problem behind `code` is visibly over: its alarm is closed and the
        calls charged since `after` show it. A quiet alarm alone is not enough, because an
        hour without calls closes an alarm too.

        For a differing charge, only calls after the newest attestation count: a call
        metered before the operator corrected the rate keeps its old cost (hard rule 4),
        so it would hold the incident open forever."""
        if code in self.open_alarms:
            return False
        attested = [price.attested_at for price in self.rates.values()]
        if code != UNMATCHED_CODE and attested:
            after = max(after, *attested)
        since = [c for c in self.calls if c.at >= after]
        if code == UNMATCHED_CODE:
            return bool(since)
        priced = [c for c in since if c.matches is not None]
        return bool(priced) and all(c.matches for c in priced)

    def summary(self) -> str:
        """The diagnosis in one short line, for the ledger and the healer screen; `explain`
        carries the rest for Pip. Kept inside `MAX_FREE_TEXT`, which the ledger's redaction
        would otherwise cut mid-sentence."""
        if self.calls:
            head = (
                f"{len(self.differing)} of {len(self.calls)} charged calls differ since "
                f"{ist(self.since)}."
            )
        else:
            head = f"None of our calls in the window checked (from {ist(self.since)}) is charged."
        parts = [head]
        found = self.findings()
        if found:
            first = found[0]
            held = f"₹{first.in_force}/min" if first.in_force is not None else "no rate"
            implied = f"₹{first.implied[0]}/min" if first.implied else "an unknown rate"
            parts.append(f"{first.rate_key}: we hold {held}, charges imply {implied}.")
            if self.one_cause() is not None and len(self.differing) > 1:
                parts.append("One rate explains all.")
            elif len(found) > 1 or len(first.implied) > 1:
                parts.append("More than one rate differs.")
        if self.uncharged:
            parts.append(f"{self.uncharged} calls lack a charge.")
        parts.append("Alarm open." if self.open_alarms else "Alarm cleared.")
        line = " ".join(parts)
        return line if len(line) <= MAX_FREE_TEXT else line[: MAX_FREE_TEXT - 1] + "…"

    def explain(self) -> str:
        """The diagnosis in plain sentences, for Pip to explain from."""
        parts = [self._counts()]
        for finding in self.findings():
            parts.append(self._finding_sentence(finding))
        cause = self.one_cause()
        if cause is not None and len(self.differing) > 1:
            parts.append(f"One cause explains every difference: the {cause.rate_key} rate.")
        if self.unpriced:
            parts.append(f"{len(self.unpriced)} charged call(s) have no metered cost to compare.")
        if self.uncharged:
            parts.append(f"{self.uncharged} completed call(s) have no charge recorded yet.")
        if self.unreadable:
            parts.append(f"{self.unreadable} client(s) could not be read; this is partial.")
        parts.append(
            "Alarm still open: " + ", ".join(sorted(self.open_alarms)) + "."
            if self.open_alarms
            else "No charge alarm is open."
        )
        return " ".join(parts)

    def _counts(self) -> str:
        if not self.calls:
            return (
                f"The check reads back to {ist(self.since)}; none of our calls in "
                "that window has a charge recorded, so nothing compares. That time is where "
                "the window starts, not when charges stopped."
            )
        return (
            f"Since {ist(self.since)}: {len(self.calls)} charged call(s), "
            f"{len(self.matching)} match what we metered, {len(self.differing)} differ."
        )

    def _finding_sentence(self, finding: RateFinding) -> str:
        held = f"₹{finding.in_force}/min" if finding.in_force is not None else "no rate"
        implied = (
            " or ".join(f"₹{r}/min" for r in finding.implied) if finding.implied else "an unknown"
        )
        return (
            f"{finding.rate_key}: we hold {held}; the charges imply {implied} before the "
            f"{_percent(self.fee)}% top-up fee, on {finding.differing} call(s) from "
            f"{ist(finding.first_at)}."
        )


def _percent(fee: Decimal) -> str:
    return format((fee * 100).normalize(), "f")


async def _client_calls(
    tenant_id: UUID, *, since: datetime, fee: Decimal
) -> tuple[list[ChargedCall], int]:
    async with tenant_session(tenant_id) as session:
        client = (
            await session.execute(
                text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar_one_or_none()
        rows = (
            await session.execute(_CHARGED_CALLS, {"since": since, "cap": CALLS_PER_TENANT})
        ).all()
        uncharged = (
            await session.execute(
                _UNCHARGED_CALLS, {"since": since, "grace": int(SETTLE_GRACE.total_seconds())}
            )
        ).scalar_one()
    calls = []
    for call_id, at, charged, metered, unpriced, minute_rows, key, minutes, rate in rows:
        charged_inr = Decimal(str(charged))
        calls.append(
            ChargedCall(
                tenant_id=tenant_id,
                client=str(client or tenant_id),
                call_id=call_id,
                at=at,
                rate_key=key,
                billed_minutes=_decimal(minutes),
                stamped_rate=_decimal(rate),
                metered_inr=None
                if unpriced or not minute_rows or metered is None
                else Decimal(str(metered)).quantize(MONEY_Q, rounding=ROUNDING),
                charged_inr=charged_inr,
                expected_inr=cost_with_fee(charged_inr, fee=fee),
            )
        )
    return calls, int(uncharged)


async def gather(
    *, since: datetime, tenant_ids: Iterable[UUID] | None = None, now: datetime | None = None
) -> MoneyEvidence:
    """Every charged call since `since` on the engine in force, with what we metered, the
    rates in force now, and which charge alarms are open. One client's failure is counted
    in `unreadable` rather than failing the whole reading. `tenant_ids` narrows the walk
    (tests); production reads every client with an agent on the engine."""
    engine = get_settings().engine
    at = now or datetime.now(UTC)
    async with untenanted_session() as session:
        fee = (await required_wallet_fee(session, engine=engine, at=at)).fee
    calls: list[ChargedCall] = []
    uncharged = unreadable = 0
    for tenant_id in tenant_ids if tenant_ids is not None else await engine_tenants(engine):
        try:
            found, missing = await _client_calls(tenant_id, since=since, fee=fee)
        except Exception as exc:
            unreadable += 1
            log.warning(
                "healer_money_evidence_unreadable",
                extra={"tenant_id": str(tenant_id), "reason": type(exc).__name__},
            )
            continue
        calls.extend(found)
        uncharged += missing
    async with untenanted_session() as session:
        rates = await attested_minute_prices(session, engine=engine, at=at)
        open_alarms = frozenset(
            str(code)
            for code in (
                await session.execute(_OPEN_ALARMS, {"codes": list(MONEY_CODES)})
            ).scalars()
        )
    calls.sort(key=lambda c: c.at, reverse=True)
    return MoneyEvidence(
        engine=engine,
        fee=fee,
        since=since,
        calls=tuple(calls),
        rates=rates,
        uncharged=uncharged,
        open_alarms=open_alarms,
        unreadable=unreadable,
        read_at=at,
    )


__all__ = [
    "CALLS_PER_TENANT",
    "LOOKBACK",
    "MONEY_CODES",
    "SETTLE_GRACE",
    "UNMATCHED_CODE",
    "ChargedCall",
    "MoneyEvidence",
    "RateFinding",
    "gather",
    "ist",
]
