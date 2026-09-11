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


def _flatten(source: str) -> str:
    """One line, single-spaced. JSX wraps prose at a column, so a phrase this guard looks
    for is routinely split by a newline and an indent that no reader ever sees."""
    return " ".join(source.split())


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
    # ⚠ RE-AIMED, not dropped, for the reason the note below gives: the client home was
    # split by subject too, so the tile's own copy and the fact the assistant is told about
    # it now live in two files and BOTH are guarded.
    (
        "apps/web/src/app/c/[slug]/CallingCreditTile.tsx",
        "export function CallingCreditTile",
        None,
    ),
    ("apps/web/src/app/c/[slug]/DashboardScreen.tsx", "calling_credit", None),
    ("apps/web/src/app/c/[slug]/billing/page.tsx", '"outbound_stopped"', None),
    # ⚠ BOTH SCREENS WERE SPLIT BY SUBJECT (UX-DOCTRINE §6, Sep 2026) and these two
    # anchors moved out of their `page.tsx` with the copy they name. The guard is re-aimed
    # rather than dropped, exactly as its own failure message instructs.
    (
        "apps/web/src/app/c/[slug]/leads/CallControl.tsx",
        'rule === "no_credits"',
        'rule === "spend_cap"',
    ),
    ("apps/web/src/app/c/[slug]/campaigns/blockerCopy.tsx", "  no_credits: {", "  spend_cap: {"),
    # ⚠ WIDENED TO THE WHOLE FILE (D-577). It used to start at `result.stops_dialling` —
    # the correction OUTCOME panel — which is one of four places this screen tells an
    # operator what an empty wallet does, and the only one that was ever corrected. The
    # other three said "for a self-serve or trial client" and "outbound dialling" until
    # 10 Sep 2026 and passed this sweep for the worst possible reason: they said nothing
    # about inbound at all, so no withdrawn phrase appeared in them.
    #
    # The whole file is safe to hold because every sentence in it is about THE WALLET.
    # None of the four conditions that genuinely leave inbound answering alone — the
    # client's own spend cap, a suspended account, the big red switch, a maintenance
    # window — has any copy here; each is pinned in `UNCHANGED_CONDITIONS` below, in the
    # file that does say it.
    #
    # THE SIBLING `TrialPanel.tsx` (and its two forms) IS DELIBERATELY NOT IN THIS SWEEP,
    # and that is the same judgement rather than an omission. A trial is the one state on
    # this screen where an empty wallet genuinely stops NOTHING — the credit gate is
    # bypassed for its whole length (D-536) — so "their calling is unaffected" is TRUE
    # there, and forbidding the withdrawn phrasings in that file would fail a correct
    # sentence with a message telling its author to say something false. What the trial
    # control must say instead is pinned by `apps/web/tests/adminTrial.test.tsx`.
    (
        "apps/web/src/app/admin/tenants/[tenantId]/credits/page.tsx",
        "export default function CreditsPage",
        None,
    ),
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


# ───── the operator console: BOTH halves, and the tier that owns a wallet (D-577) ─────

#: The three places the ADMIN credits screen tells an operator what an empty — or
#: below-zero — wallet does to a client, with the region each sentence lives in.
#:
#: The sweep above only forbids the eight WITHDRAWN sentences, and these three passed it
#: for the worst reason available: until 10 Sep 2026 they said nothing about inbound at
#: all. They said *"an empty wallet stops outbound dialling for a self-serve or trial
#: client"*, which was wrong twice over — D-551 stopped inbound answering as well, and the
#: tier half omitted `prepaid`, the DEFAULT every account is created on
#: (`tenancy/models.py`) and a member of `billing/rates.PREPAID_TIERS` with the other two.
#: An operator reading it concluded a payment was not urgent while it was holding a
#: client's phone line down.
#:
#: So each region is held to the SAME three facts the backend surfaces are held to, in the
#: same vocabulary — one guard, one set of accepted spellings, no second definition of what
#: correct credit copy says.
WEB_CREDIT_BOTH_HALVES: tuple[tuple[str, str, str, str], ...] = (
    (
        "apps/web/src/app/admin/tenants/[tenantId]/credits/page.tsx",
        "Below the low-balance line",
        "</NoticeBox>",
        "the low-balance notice on the balance panel",
    ),
    (
        "apps/web/src/app/admin/tenants/[tenantId]/credits/page.tsx",
        "A correction may take the balance",
        "Recorded in the audit log",
        "the consequence stated above the Correct button",
    ),
    (
        "apps/web/src/app/admin/tenants/[tenantId]/credits/page.tsx",
        "TOO MUCH was credited",
        "TOO LITTLE was credited",
        "the \u201cif a credit was wrong\u201d card",
    ),
)


@pytest.mark.parametrize("rel,start,end,what", WEB_CREDIT_BOTH_HALVES)
def test_the_operator_console_states_both_halves_wherever_it_names_the_stop(
    rel: str, start: str, end: str, what: str
) -> None:
    source = _copy_only(_read(rel))
    begin = source.find(start)
    assert begin >= 0, (
        f"{rel}: the anchor \u201c{start}\u201d is gone, so this guard was reading nothing. "
        f"Re-aim it at {what} wherever it lives now \u2014 do not delete the case."
    )
    stop = source.find(end, begin)
    assert stop > begin, (
        f"{rel}: the end anchor \u201c{end}\u201d no longer follows the start anchor"
    )
    # FLATTENED first: this is JSX, so a sentence wraps mid-phrase at the printer's
    # column and "until you add\ncredit" would read as a missing fact rather than as a
    # line break. The copy is not changed to suit the guard; the guard reads it the way a
    # person does.
    region = _flatten(source[begin:stop])
    _assert_not_withdrawn(region, f"{rel} ({what})")
    _assert_three_facts(region, f"{rel} ({what})")


#: The tier phrasing that is WRONG about money, and where it is wrong.
#:
#: SCOPED TO ONE FILE ON PURPOSE, and that is the whole care in this guard. "A self-serve
#: or trial account" is CORRECT wherever the question is *did a stranger sign this account
#: up unattended* \u2014 `compliance/service.SELF_SERVE_TIERS`, which is what the
#: subscriber-KYC dial gate (D-47) and the first-campaign hold (D-51) key on, and both
#: `admin/tenants/[tenantId]/kyc/page.tsx` and `lib/legal/acceptableUse.ts` say it there
#: and must go on saying it. The credits console asks the OTHER question \u2014 *does this
#: account pay from a wallet* \u2014 which D-521 split off as `PREPAID_TIERS`, and answering
#: it with the identity set excuses `prepaid`, i.e. essentially every client.
STALE_WALLET_TIER_COPY = ("self-serve or trial",)


def test_the_credits_console_does_not_name_the_identity_tiers_for_a_money_rule() -> None:
    """The half of D-577 that outlives the three sentences it corrected.

    Comments are stripped first, so the warning notes on this screen that RECORD the
    withdrawn wording \u2014 the convention every corrected file in this sweep follows \u2014
    are not what this reads. Only what an operator can see is scanned.
    """
    rel = "apps/web/src/app/admin/tenants/[tenantId]/credits/page.tsx"
    lowered = _copy_only(_read(rel)).lower()
    for phrase in STALE_WALLET_TIER_COPY:
        assert phrase not in lowered, (
            f"{rel} tells an operator that an empty wallet stops calling for a "
            f"\u201c{phrase}\u201d client. That is the IDENTITY set (`SELF_SERVE_TIERS` "
            "\u2014 who signed up unattended), not the MONEY set: "
            "`billing/rates.PREPAID_TIERS` is (prepaid, self_serve, trial) and `prepaid` "
            "is the default tier every account is created on, so the sentence excuses "
            "almost every client on the platform. Name the motion instead \u2014 every "
            "client but a managed one pays from a wallet."
        )


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
        # The panel moved out of the route module when /admin/ops was split by subject
        # (UX-DOCTRINE §6). Same sentence, same switch, one file down.
        "apps/web/src/app/admin/ops/OutboundHaltPanel.tsx",
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
