"""The TTS speaking rate, measured from transcripts — pilot gate 12's number (TRD §10.1).

Five properties, each of which is a way the number could be wrong while looking right:

- **The arithmetic is exact to the paise.** Chars come from `length(COALESCE(text_redacted,
  text))` over the AGENT's turns only; the rate is chars x 60 / seconds in Decimal; the
  rupee it implies is `rates.tts_inr_per_call_minute` over the live `TTS_INR_PER_10K_CHARS`
  and never a hardcoded 0.003. Fixtures are built so every expected figure can be done by
  hand on the margin of this file.
- **Below the threshold there is no figure.** A rate from three calls displayed as
  "measured" is the hard-rule-11 failure this repository keeps correcting, so under
  `TTS_SPEAKING_RATE_MIN_CALLS` the result carries the sample size, the reason and no
  rate — and the threshold's own justification (below it the "p95" is the maximum) is
  asserted as arithmetic rather than trusted as prose.
- **The cross-tenant read really sees more than one tenant.** `calls` and
  `transcript_turns` are FORCE-RLS'd; an untenanted read returns zero rows and reports
  success. The route walks one `tenant_session` per live client, and the test captures
  the samples it pooled and finds both seeded tenants' calls in them. The negative control
  — an untenanted `sample_tenant` returning nothing — is asserted too, because it is the
  reason the walk exists.
- **The assumed band has one home.** `TTS_ASSUMED_CHARS_PER_CALL_MINUTE` is pinned to TRD
  §10.1's numbers here AND diffed against the doc by `check_docs_drift` §4e, so a doc edit
  without a code edit fails in two places.
- **Money is Decimal end to end.** Every rate and rupee crosses the wire as a string.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal
from math import ceil
from pathlib import Path
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import spend_routes, tts_speaking_rate
from apps.api.billing.rates import (
    TTS_ASSUMED_CHARS_PER_CALL_MINUTE,
    TTS_INR_PER_10K_CHARS,
    tts_inr_per_call_minute,
)
from apps.api.billing.tts_speaking_rate import (
    TTS_SPEAKING_RATE_MIN_CALLS,
    CallSample,
    assumed_band,
    sample_tenant,
    summarize,
)
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from scripts import check_docs_drift as guard
from sqlalchemy import text

ROUTE = "/v1/admin/spend/tts-speaking-rate"
REPO_ROOT = Path(__file__).resolve().parent.parent
TRD_TEXT = (REPO_ROOT / "docs" / "TRD.md").read_text(encoding="utf-8")
#: The doc spells its band with U+2013; ruff refuses the literal character in source.
EN_DASH = "\u2013"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


async def _make_member(tenant_id: UUID) -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return f"dev:client:{user_id}"


async def _tenant() -> tuple[UUID, UUID]:
    created = await admin_service.create_organization(
        name="Speaking Rate Clinic",
        slug=f"ttsrate-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
        plan_tier="managed",
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    assert isinstance(tenant_id, UUID) and isinstance(agent_id, UUID)
    return tenant_id, agent_id


async def _call(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    seconds: int | None,
    turns: Sequence[tuple[str, str, str | None]] = (),
) -> UUID:
    """One completed call with `turns` as (speaker, text, text_redacted) rows."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, started_at, duration_s, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'inbound', '+919876500001', 'completed', now(), :d, now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "d": seconds,
            },
        )
        for idx, (speaker, raw, redacted) in enumerate(turns):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, :idx, :s, :raw, "
                    ":red, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "idx": idx,
                    "s": speaker,
                    "raw": raw,
                    "red": redacted,
                },
            )
    return call_id


def _sample(chars: int, seconds: int, tenant_id: UUID | None = None) -> CallSample:
    return CallSample(
        tenant_id=tenant_id or uuid.uuid4(),
        call_id=uuid7(),
        duration_s=seconds,
        agent_chars=chars,
    )


# --- the arithmetic ----------------------------------------------------------------


async def test_agent_characters_over_call_minutes_to_the_paise() -> None:
    """Three calls a reader can do by hand, and three that must not count at all.

    call 1: 60 s, agent 350 raw chars redacted to 300 -> the REDACTED length counts (300);
            a 500-char caller turn is ignored                          -> 300 chars/min
    call 2: 120 s, agent 900 chars with no redacted copy -> COALESCE falls back to `text`
                                                                        -> 450 chars/min
    call 3: 30 s, caller-only transcript -> the agent spoke nothing      -> 0 chars/min
    excluded: a 0-second call, a NULL-duration call, a call with no transcript.
    """
    tenant_id, agent_id = await _tenant()
    one = await _call(
        tenant_id,
        agent_id,
        seconds=60,
        turns=[("agent", "a" * 350, "a" * 300), ("caller", "c" * 500, "c" * 500)],
    )
    two = await _call(tenant_id, agent_id, seconds=120, turns=[("agent", "b" * 900, None)])
    three = await _call(tenant_id, agent_id, seconds=30, turns=[("caller", "hello", "hello")])
    await _call(tenant_id, agent_id, seconds=0, turns=[("agent", "z" * 100, None)])
    await _call(tenant_id, agent_id, seconds=None, turns=[("agent", "z" * 100, None)])
    await _call(tenant_id, agent_id, seconds=90)

    async with tenant_session(tenant_id) as session:
        samples = await sample_tenant(session, tenant_id=tenant_id)

    assert {s.call_id for s in samples} == {one, two, three}
    by_call = {s.call_id: s for s in samples}
    assert (by_call[one].agent_chars, by_call[one].duration_s) == (300, 60)
    assert (by_call[two].agent_chars, by_call[two].duration_s) == (900, 120)
    assert (by_call[three].agent_chars, by_call[three].duration_s) == (0, 30)

    rate = summarize(samples, minimum_calls=1)
    assert rate.measured and rate.reason is None
    assert (rate.calls, rate.clients, rate.minimum_calls) == (3, 1, 1)
    assert rate.p50 is not None and rate.p95 is not None and rate.pooled is not None
    # Sorted rates [0, 300, 450]; nearest-rank p50 is position ceil(1.5) = 2, p95 is
    # position ceil(2.85) = 3.
    assert rate.p50.chars_per_minute == Decimal("300.0000")
    assert rate.p50.tts_inr_per_minute == Decimal("0.9000")
    assert rate.p95.chars_per_minute == Decimal("450.0000")
    assert rate.p95.tts_inr_per_minute == Decimal("1.3500")
    # Pooled: 1,200 chars x 60 / 210 s = 342.857142... chars/min -> x ₹0.003 = ₹1.028571...
    assert rate.pooled.chars_per_minute == Decimal("342.8571")
    assert rate.pooled.tts_inr_per_minute == Decimal("1.0286")


def test_the_implied_rupee_is_the_live_rate_card_and_never_a_literal() -> None:
    """₹/min is TTS_INR_PER_10K_CHARS applied to the rate: 10,000 chars/min prices at
    exactly the card, so a card move moves every figure on the board with it."""
    assert tts_inr_per_call_minute(Decimal(10_000)) == TTS_INR_PER_10K_CHARS
    assert tts_inr_per_call_minute(Decimal(0)) == Decimal("0.0000")
    with pytest.raises(ValueError, match="cannot be negative"):
        tts_inr_per_call_minute(Decimal(-1))


# --- the threshold -----------------------------------------------------------------


def test_below_the_threshold_there_is_no_figure() -> None:
    rate = summarize([_sample(300, 60), _sample(900, 120), _sample(0, 30)])
    assert rate.measured is False
    assert (rate.p50, rate.p95, rate.pooled) == (None, None, None)
    assert rate.calls == 3 and rate.minimum_calls == TTS_SPEAKING_RATE_MIN_CALLS
    assert rate.reason is not None
    assert "3 calls" in rate.reason and str(TTS_SPEAKING_RATE_MIN_CALLS) in rate.reason
    # The band is always there — it is what stays in force.
    assert rate.assumed_low.chars_per_minute == Decimal("360.0000")
    assert rate.assumed_high.chars_per_minute == Decimal("540.0000")


def test_one_call_is_singular_and_zero_calls_is_a_refusal_too() -> None:
    one = summarize([_sample(300, 60)])
    assert one.reason is not None and "1 call with" in one.reason
    none = summarize([])
    assert none.measured is False and none.calls == 0 and none.clients == 0


def test_the_threshold_is_the_first_sample_size_whose_p95_is_not_the_maximum() -> None:
    """The constant's stated reason, as arithmetic: under nearest-rank ceil(0.95 x n) = n
    for every n below it, so a "p95" from fewer calls is the single longest-talking call
    wearing a percentile's name."""
    n = TTS_SPEAKING_RATE_MIN_CALLS
    assert all(ceil(Decimal("0.95") * k) == k for k in range(1, n))
    assert ceil(Decimal("0.95") * n) < n

    below = summarize([_sample(100 * k, 60) for k in range(1, n)])
    assert below.measured is False
    at = summarize([_sample(100 * k, 60) for k in range(1, n + 1)])
    assert at.measured is True and at.p95 is not None
    assert at.p95.chars_per_minute == Decimal(100 * (n - 1)), "second-highest, not the max"


# --- the cross-tenant read ---------------------------------------------------------


async def test_the_route_walks_every_live_tenant_and_pools_both_tenants_calls() -> None:
    """The proof is the samples the route actually summarised, not the totals: both seeded
    calls are in the pool, each stamped with its own tenant. An untenanted read of the same
    table returns nothing — the trap the walk exists to avoid — and is asserted beside it."""
    a_tenant, a_agent = await _tenant()
    b_tenant, b_agent = await _tenant()
    a_call = await _call(a_tenant, a_agent, seconds=60, turns=[("agent", "a" * 300, None)])
    b_call = await _call(b_tenant, b_agent, seconds=60, turns=[("agent", "b" * 600, None)])
    token = await _make_admin()

    async with untenanted_session() as session:
        assert await sample_tenant(session, tenant_id=a_tenant) == [], (
            "an untenanted read of a FORCE-RLS table returns zero rows and reports success"
        )

    pooled: list[CallSample] = []
    real_summarize = tts_speaking_rate.summarize

    def recording(samples: list[CallSample], **kwargs: object) -> tts_speaking_rate.TtsSpeakingRate:
        pooled.extend(samples)
        return real_summarize(samples)

    with pytest.MonkeyPatch.context() as patch:
        # Lifted for the same reason `fleet_spend`'s tests lift it: the walk's cost is a
        # property of how many tenants a shared development database happens to hold.
        patch.setattr(spend_routes, "FLEET_BUDGET_S", 3600.0)
        patch.setattr(tts_speaking_rate, "summarize", recording)
        async with _client() as http:
            response = await http.get(ROUTE, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    body = response.json()

    seen = {s.call_id: s.tenant_id for s in pooled}
    assert seen[a_call] == a_tenant and seen[b_call] == b_tenant
    assert body["calls"] == len(pooled) >= 2
    assert body["clients"] >= 2
    assert body["minimum_calls"] == TTS_SPEAKING_RATE_MIN_CALLS
    assert body["tts_inr_per_10k_chars"] == str(TTS_INR_PER_10K_CHARS)
    assert body["assumed_low"] == {"chars_per_minute": "360.0000", "tts_inr_per_minute": "1.0800"}
    assert body["assumed_high"] == {"chars_per_minute": "540.0000", "tts_inr_per_minute": "1.6200"}
    if body["measured"]:
        for key in ("p50", "p95", "pooled"):
            assert isinstance(body[key]["chars_per_minute"], str)
            assert isinstance(body[key]["tts_inr_per_minute"], str)
    else:
        assert body["p50"] is None and body["reason"]


async def test_the_route_is_operator_only() -> None:
    tenant_id, _ = await _tenant()
    token = await _make_member(tenant_id)
    async with _client() as http:
        response = await http.get(ROUTE, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code in (401, 403), response.text


async def test_a_walk_over_budget_is_logged_with_a_remedy_and_still_answers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = await _make_admin()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(spend_routes, "FLEET_BUDGET_S", -1.0)
        with caplog.at_level(logging.WARNING):
            async with _client() as http:
                response = await http.get(ROUTE, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert any(r.message == "tts_speaking_rate_walk_over_budget" for r in caplog.records)


# --- the assumed band has one home -------------------------------------------------


def test_the_assumed_band_is_pinned_to_trd_10_1() -> None:
    """A doc edit without a code edit fails HERE; a code edit without a doc edit fails in
    `check_docs_drift` §4e. Both directions, two places."""
    assert (Decimal("360"), Decimal("540")) == TTS_ASSUMED_CHARS_PER_CALL_MINUTE
    assert f"360{EN_DASH}540 TTS characters per call-minute" in TRD_TEXT
    low, high = assumed_band()
    # §10.1's per-call-minute cell for the TTS leg, derived rather than restated.
    assert (low.tts_inr_per_minute, high.tts_inr_per_minute) == (
        Decimal("1.0800"),
        Decimal("1.6200"),
    )
    assert f"₹1.08{EN_DASH}1.62" in TRD_TEXT


def test_the_drift_check_reads_the_real_doc_and_names_a_moved_band() -> None:
    assert guard.doc_tts_speaking_rate_bands(), "§4e is reading nothing"
    assert not guard.tts_speaking_rate_band_drift()
    band = f"360{EN_DASH}540 TTS characters per call-minute"
    moved = TRD_TEXT.replace(band, band.replace("540", "600"), 1)
    offenders = guard.tts_speaking_rate_band_drift(moved)
    assert offenders and any("600" in line for line in offenders), offenders
    assert guard.tts_speaking_rate_band_drift("no band stated anywhere"), (
        "a doc that states no band leaves the constant guarding nothing"
    )
