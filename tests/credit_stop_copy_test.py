"""The withdrawn promise, and the guard that stops it coming back (D-551, 8 Sep 2026).

Until 8 Sep 2026 an empty wallet stopped OUTGOING calls only, and eleven client- and
operator-facing surfaces said so in the client's own words: *"people calling you still get
through — a low balance never blocks an incoming call"*. D-551 reversed it. At a balance of
zero or below `agents.service.reconcile_inbound_answering` silences every live answering
agent at the engine and the caller hears `agents.service.CREDIT_STOP_MESSAGE`, so every one
of those sentences became false in the direction that costs the most: a client reads it,
does nothing, and their callers are turned away all night.

**WHY A TEXT GUARD AND NOT A TYPE.** There is nothing to type. The correction is words, on
eleven surfaces in two languages, none of which imports any of the others — and the failure
mode is not a compile error but a sentence that stays true-looking. The same reasoning
produced `apps/web/tests/legalContentHash.test.ts` this session and `campaignBlockerCopy
.test.ts` before it: when the fact under test is what a client READS, the guard reads it too.

**THE HALF THAT MATTERS AS MUCH IS THE SECOND TEST.** Four OTHER conditions stop outbound
dialling — the client's own monthly spend cap, a suspended account, the big red switch and
a maintenance window — and for every one of them inbound answering genuinely IS unaffected.
A sweep that pattern-matched on the phrase would have deleted four true sentences to correct
one false one, so those four are pinned here as well: this file fails if the promise comes
back where it is false, AND if it disappears where it is true.

Python copy is read by IMPORTING the constant, so the test cannot pass against a string
nobody renders. TypeScript copy is read from source with comments stripped first — every
corrected file quotes the withdrawn sentence in a comment on purpose, recording what it used
to say, and a guard that could not tell copy from commentary would forbid the record of its
own correction.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "apps/web/src"

#: The sentences the decision withdrew, lowercased. Each is a real fragment that was on a
#: client's screen on 7 Sep 2026, not a paraphrase — a guard written against words nobody
#: shipped would pass while the shipped words rotted.
WITHDRAWN = (
    "still get through",
    "never blocks an incoming call",
    "incoming calls are still answered",
    "incoming calls are answered throughout",
    "inbound calls are unaffected",
    "inbound answering is unaffected",
    "incoming calls are unaffected",
    "receptionist keeps answering",
)

#: What correct credit copy has to carry. Not one phrasing — each surface writes in its own
#: file's voice — so each fact is a set of accepted spellings and the assertion is that at
#: least one of each set is present.
FACT_OUTGOING = ("outgoing calls", "outgoing ones", "make outgoing", "nothing goes out")
FACT_INCOMING = (
    "answering incoming",
    "no longer answering",
    "not answering incoming",
    "stopped answering",
    "stop answering",
    "the incoming ones",
    "will not answer incoming",
    "and incoming",
)
FACT_RESTORE = (
    "start again",
    "starts again",
    "start answering",
    "resume",
    "undoes both",
    "adding credit",
    "add credit",
    "top up",
)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def _copy_only(source: str) -> str:
    """Source with its commentary removed, so only what a reader could see is scanned."""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", source))


def _read(rel: str) -> str:
    path = REPO / rel
    assert path.is_file(), f"{rel} has moved — this guard is scanning nothing"
    return path.read_text(encoding="utf-8")


def _assert_three_facts(text: str, where: str) -> None:
    lowered = text.lower()
    assert any(f in lowered for f in FACT_OUTGOING), f"{where}: does not say outgoing calls stopped"
    assert any(f in lowered for f in FACT_INCOMING), (
        f"{where}: does not say the agents have stopped ANSWERING — the half D-551 added, "
        "and the half a client cannot discover any other way"
    )
    assert any(f in lowered for f in FACT_RESTORE), (
        f"{where}: does not say a top-up undoes it. A refusal with no next action is the "
        "shape every copy rule in this repo exists to prevent"
    )


def _assert_not_withdrawn(text: str, where: str) -> None:
    lowered = text.lower()
    for phrase in WITHDRAWN:
        assert phrase not in lowered, (
            f"{where} promises a client that incoming calls survive an empty wallet "
            f"(“{phrase}”). D-551 made that false: at zero the agents are silenced at the "
            "engine and the caller hears a short apology. Say both halves and say that a "
            "top-up undoes both — `apps/api/crm/attention.py::BLOCK_REMEDIES['no_credits']` "
            "is the wording every surface matches, fact for fact."
        )


# ─────────────────────────── the Python copy, by import ───────────────────────────


def _python_credit_copy() -> dict[str, str]:
    """Every credit-exhausted sentence this backend can render, from its own module.

    Imported rather than parsed: a constant that no longer exists fails the collection,
    which is the loud version of a guard silently scanning a renamed name.
    """
    from apps.api.compliance.service import NO_CREDITS_REASON
    from apps.api.crm.attention import BLOCK_REMEDIES, INBOUND_STOPPED_DETAIL
    from apps.api.legal.readiness import ROW_COPY
    from apps.workers.wallet_alerts import WALLET_LEVEL_EMPTY, WALLET_LEVEL_LOW, compose

    return {
        "compliance.service.NO_CREDITS_REASON": NO_CREDITS_REASON,
        "crm.attention.BLOCK_REMEDIES['no_credits']": BLOCK_REMEDIES["no_credits"],
        "crm.attention.INBOUND_STOPPED_DETAIL": INBOUND_STOPPED_DETAIL,
        "legal.readiness.ROW_COPY['no_credits']": ROW_COPY["no_credits"].next_step,
        "workers.wallet_alerts.compose(empty)": compose(
            level=WALLET_LEVEL_EMPTY, balance_inr=Decimal("0"), minutes_left=(), slug="clinic"
        ),
        "workers.wallet_alerts.compose(low)": compose(
            level=WALLET_LEVEL_LOW, balance_inr=Decimal("150"), minutes_left=(), slug="clinic"
        ),
    }


def test_no_backend_surface_promises_that_callers_still_get_through() -> None:
    copy = _python_credit_copy()
    assert len(copy) == 6, "a credit-exhausted sentence was added or dropped without a guard"
    for where, text in copy.items():
        assert text.strip(), f"{where} renders nothing"
        _assert_not_withdrawn(text, where)


@pytest.mark.parametrize(
    "key",
    [
        "compliance.service.NO_CREDITS_REASON",
        "crm.attention.BLOCK_REMEDIES['no_credits']",
        "legal.readiness.ROW_COPY['no_credits']",
        "workers.wallet_alerts.compose(empty)",
    ],
)
def test_every_backend_surface_states_all_three_facts(key: str) -> None:
    """Both halves stop, and a top-up undoes both.

    TWO STRINGS ARE DELIBERATELY NOT IN THIS LIST, and each has its own assertion instead.
    The LOW-balance mail warns about what is coming rather than reporting what happened, so
    "outgoing calls have stopped" would be false in it. `INBOUND_STOPPED_DETAIL` answers a
    narrower question — "why has THIS agent gone quiet" — beside a `no_credits` row that
    already carries the outbound half; it still has to say the two facts that are its own.
    Both remain covered by the withdrawn-phrase sweep above.
    """
    _assert_three_facts(_python_credit_copy()[key], key)


def test_the_silenced_agent_row_says_what_stopped_and_what_undoes_it() -> None:
    """`INBOUND_STOPPED_DETAIL` is the row a client sees when their phone is quiet and no
    outbound traffic ever told them why. It is scoped to one agent, so it does not claim
    anything about dialling — but the two facts it IS about are not optional."""
    detail = _python_credit_copy()["crm.attention.INBOUND_STOPPED_DETAIL"].lower()
    assert any(f in detail for f in FACT_INCOMING), "does not say the agent stopped answering"
    assert any(f in detail for f in FACT_RESTORE), "does not say a top-up brings it back"


# ────────────────────── the TypeScript copy, by reading source ──────────────────────

#: One region per surface. `None` for the end marker means "to the end of the file", used
#: only where the whole file is about the wallet; the two mixed files stop at the SPEND-CAP
#: arm, which is a different condition and whose copy is still true.
WEB_CREDIT_REGIONS: tuple[tuple[str, str, str | None], ...] = (
    ("apps/web/src/app/c/[slug]/billing/WalletHero.tsx", "export function WalletHero", None),
    ("apps/web/src/app/c/[slug]/page.tsx", "calling_credit", None),
    ("apps/web/src/app/c/[slug]/billing/page.tsx", '"outbound_stopped"', None),
    ("apps/web/src/app/c/[slug]/leads/page.tsx", 'rule === "no_credits"', 'rule === "spend_cap"'),
    ("apps/web/src/app/c/[slug]/campaigns/page.tsx", "  no_credits: {", "  spend_cap: {"),
    ("apps/web/src/app/admin/tenants/[tenantId]/credits/page.tsx", "result.stops_dialling", None),
    ("apps/web/src/app/pricing/page.tsx", "Prepaid credit", "Two ceilings"),
)


@pytest.mark.parametrize("rel,start,end", WEB_CREDIT_REGIONS)
def test_no_web_surface_promises_that_callers_still_get_through(
    rel: str, start: str, end: str | None
) -> None:
    source = _copy_only(_read(rel))
    begin = source.find(start)
    assert begin >= 0, (
        f"{rel}: the anchor “{start}” is gone, so this guard was reading nothing. Re-aim it "
        "at whatever renders the empty-wallet copy now — do not delete the case."
    )
    stop = source.find(end, begin) if end else len(source)
    assert stop > begin, f"{rel}: the end anchor “{end}” no longer follows the start anchor"
    _assert_not_withdrawn(source[begin:stop], f"{rel} (empty-wallet copy)")


def test_the_client_is_told_on_the_wallet_screen_what_their_callers_hear() -> None:
    """The reputational half, on the one screen a client opens when the phone goes quiet.

    A caller who works out that the business has not paid its bill is a harm WE inflicted
    on our client, so the in-call message gives no reason (`agents.service
    .credit_stop_prompt` forbids each available reason by name) — and the client has to be
    told that, or they will assume the worst and ring us at 9pm to ask.
    """
    hero = _copy_only(_read("apps/web/src/app/c/[slug]/billing/WalletHero.tsx"))
    _assert_three_facts(hero, "WalletHero.tsx")
    assert "gives no reason and says nothing about your account" in hero


# ───────── the four conditions that did NOT change, pinned so nobody over-corrects ─────────

#: (file, anchor, what the anchor is the copy FOR). Each of these stops outbound dialling and
#: leaves inbound answering completely alone, so each one's reassurance is TRUE and deleting
#: it would be the mirror-image defect of the one this file exists to prevent.
UNCHANGED_CONDITIONS: tuple[tuple[str, str, str], ...] = (
    (
        "apps/web/src/app/c/[slug]/billing/UsageTab.tsx",
        "you have reached your spending",
        "the client's own monthly spend cap",
    ),
    (
        "apps/web/src/app/admin/tenants/[tenantId]/lifecycle/page.tsx",
        "Inbound answering is never affected",
        "a suspended account",
    ),
    (
        "apps/web/src/app/admin/ops/maintenance/page.tsx",
        "Inbound calls are still answered",
        "a platform maintenance window",
    ),
    (
        "apps/web/src/app/admin/ops/page.tsx",
        "Inbound calls are unaffected",
        "the big red switch",
    ),
)


@pytest.mark.parametrize("rel,anchor,condition", UNCHANGED_CONDITIONS)
def test_the_four_unchanged_conditions_still_say_inbound_is_unaffected(
    rel: str, anchor: str, condition: str
) -> None:
    assert anchor in _copy_only(_read(rel)), (
        f"{rel} no longer tells a client that inbound answering survives {condition}. "
        "Only the CREDIT condition changed on 8 Sep 2026 (D-551); this one still stops "
        "outbound dialling and nothing else, so the reassurance is true and load-bearing."
    )
