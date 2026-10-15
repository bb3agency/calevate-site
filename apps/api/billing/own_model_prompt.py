"""The prompt size the own-model cost floor is struck at (D-764).

`rates.own_model_floor_inr_per_min` prices `REFERENCE_CALL` with OUR prompt in place of its
900 tokens, because every agent's engine prompt is the client's script plus the platform's
fixed layers (`calevate_shared.engine.engine_prompt_layers`), resent on every turn. This
module decides that prompt size, best source first:

1. **Measured**: the input tokens ThinnestAI counted on our own-model calls
   (`usage_events.meta.llm_input_tokens`, written by `workers/pipeline` beside the
   `llm_ktok_in` row), once `MIN_CALLS` calls of at least a minute exist. Each call is
   turned into the prompt size that makes `REFERENCE_CALL`'s shape reproduce that call's
   input tokens (`effective_prompt_tokens`), and the floor takes the 95th percentile. p95
   and not the pooled mean, because prompt size is per-agent configuration rather than a
   per-minute fluctuation, and a floor must cover the agents with the long scripts, not the
   average one; not the maximum, so one anomalous call does not set every card's floor.
   Only this source sees what the engine adds to our prompt (its own rules, tool
   definitions, knowledge results). Only provider-reported counts are sampled: a call whose
   input count the engine estimated from the prompt's length (`inputTokensEstimated`,
   snapshots/2026-10-15/pages/api-reference/calls/get-call.md:1208-1217) would feed the
   floor the engine's guess at our prompt instead of a measurement of it (D-796).
2. **Published**: the largest engine prompt any live agent would publish now, composed by
   the publish path itself (`agents/prompt_size.publish_config`), in tokens.
3. **Ceiling**: the engine's own prompt ceiling (`THINNEST_LIMITS.prompt_chars`, which the
   publish refuses above), every character counted as a token. No published prompt can be
   larger, so it is the conservative figure for a caller with no basis at hand.

CHARACTERS TO TOKENS. Google: "For Gemini models, a token is equivalent to about 4
characters" (https://ai.google.dev/gemini-api/docs/tokens, read 13 Oct 2026; the page says
nothing about other scripts). That ratio is applied to ASCII characters only. Google
publishes no ratio for Telugu or Hindi script, so every other character is counted as one
whole token: `NON_ASCII_TOKENS_PER_CHAR` is an ASSUMPTION, chosen conservative, and the
measured path supersedes it.

WHY A CACHE. The measured and published sizes need every tenant's rows (`usage_events` and
`agents` FORCE RLS), so one figure is a walk of the client book. The hourly own-model sweep
(`workers/own_model_key.sweep_own_model_workspaces`) walks once and stores the basis in
Redis; the rate-card and bundle routes read it with one GET. A walk per rate-card read was
rejected: it is the shape that cost 8,480 session checkouts per read (D-556,
`ops/config_routes.read_rate_card`). A missing or expired basis reads as the ceiling, which
only ever raises a floor.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from math import ceil
from typing import Final, Literal, cast
from uuid import UUID

from calevate_shared.engine import VoiceEngine, compose_engine_prompt
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import REFERENCE_CALL
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.api.engine.hosted_platform import THINNEST_LIMITS

log = get_logger(__name__)

#: Google's documented ratio for Gemini (module docstring), applied to ASCII characters.
GEMINI_CHARS_PER_TOKEN: Final = 4
#: ASSUMPTION, conservative: one token per non-ASCII character (Telugu, Hindi, punctuation
#: outside ASCII). No vendor figure exists for these scripts; measured calls replace it.
NON_ASCII_TOKENS_PER_CHAR: Final = 1

#: The largest prompt any agent can send the engine, in characters and in tokens.
CEILING_PROMPT_CHARS: Final[int] = cast(int, THINNEST_LIMITS.prompt_chars)
CEILING_PROMPT_TOKENS: Final[int] = CEILING_PROMPT_CHARS * NON_ASCII_TOKENS_PER_CHAR

#: Own-model calls needed before the measured size replaces the published one. Twenty
#: because under nearest-rank ⌈0.95·n⌉ = n for every n < 20, so a smaller sample's "p95"
#: is its maximum (`billing/tts_speaking_rate.TTS_SPEAKING_RATE_MIN_CALLS` has the same bar).
MIN_CALLS: Final = 20
PERCENTILE: Final = Decimal("0.95")
#: A call shorter than a minute is not sampled: `REFERENCE_CALL` is defined from one minute,
#: and in a few seconds the greeting and the first turn dominate whatever the prompt is.
MIN_CALL_SECONDS: Final = 60

#: How long a computed basis stands. The sweep is hourly; three hours survives two missed
#: runs, after which the floor reverts to the ceiling rather than serving an old figure.
CACHE_TTL_S: Final = 3 * 3600
_CACHE_KEY: Final = "calevate:own_model_prompt_basis"

PromptSource = Literal["measured", "published", "ceiling"]


def prompt_tokens_of(prompt: str) -> int:
    """The tokens `prompt` counts as on Gemini, by the two ratios above, rounded up."""
    ascii_chars = sum(1 for ch in prompt if ord(ch) < 128)
    other = len(prompt) - ascii_chars
    return ceil(ascii_chars / GEMINI_CHARS_PER_TOKEN) + other * NON_ASCII_TOKENS_PER_CHAR


def effective_prompt_tokens(input_tokens: int, call_seconds: Decimal) -> Decimal:
    """The prompt size at which `REFERENCE_CALL`'s shape (its turns per minute and its
    history growth) reproduces a call's measured input tokens. Never below zero.

    Inverts the arithmetic `rates._reference_call_inr_per_minute` prices: over T turns the
    input is `T·prompt + turn_tokens·T(T-1)/2`. Struck with the reference shape rather than
    the call's transcript turn count, because the floor re-applies that same shape: a call
    priced back at this prompt size costs what the call was measured to cost."""
    turns = call_seconds / Decimal(60) * REFERENCE_CALL["turns_per_minute"]
    history = REFERENCE_CALL["turn_tokens"] * turns * (turns - 1) / 2
    return max((Decimal(input_tokens) - history) / turns, Decimal(0))


@dataclass(frozen=True, slots=True)
class PromptBasis:
    """A prompt size in tokens and where it came from. Admin-only: never shown to a client."""

    prompt_tokens: int
    source: PromptSource
    #: Own-model calls sampled, whichever source won.
    calls: int
    #: Live agents whose prompt was composed.
    agents: int
    #: When the walk ran; None for the ceiling a caller assumes with no basis at hand.
    computed_at: datetime | None

    @property
    def label(self) -> str:
        """One line an operator reads under the floor."""
        tokens = f"{self.prompt_tokens:,} prompt tokens"
        if self.source == "measured":
            return f"{tokens}: p95 of {self.calls} own-model calls' measured input"
        if self.source == "published":
            return (
                f"{tokens}: the largest of {self.agents} live agents' published prompts "
                f"({self.calls} of {MIN_CALLS} own-model calls measured)"
            )
        why = (
            "no live agent or own-model call yet"
            if self.computed_at is not None
            else "no prompt size computed in the last 3 hours"
        )
        return f"{tokens}: the engine's {CEILING_PROMPT_CHARS:,}-character prompt ceiling ({why})"


#: The basis a caller assumes when none was computed.
CEILING_BASIS: Final = PromptBasis(
    prompt_tokens=CEILING_PROMPT_TOKENS, source="ceiling", calls=0, agents=0, computed_at=None
)


def basis_from(
    measured: Sequence[Decimal], published: Sequence[int], *, computed_at: datetime
) -> PromptBasis:
    """The best source with a figure: measured calls past `MIN_CALLS`, else the largest
    published prompt, else the ceiling. Pure."""
    calls, agents = len(measured), len(published)
    if calls >= MIN_CALLS:
        ranked = sorted(measured)
        p95 = ranked[max(ceil(PERCENTILE * calls), 1) - 1]
        tokens = int(p95.to_integral_value(rounding=ROUND_CEILING))
        if tokens > 0:
            return PromptBasis(tokens, "measured", calls, agents, computed_at)
    if published:
        return PromptBasis(max(published), "published", calls, agents, computed_at)
    return PromptBasis(CEILING_PROMPT_TOKENS, "ceiling", calls, agents, computed_at)


# --- one tenant's rows --------------------------------------------------------------------

#: Every own-model call of the session's tenant with its counted input tokens and its
#: billed seconds (`telephony_s` carries `duration_s` as its quantity). A call whose count
#: the engine partly estimated (`llm_input_tokens_estimated` true) is left out; a call with
#: the flag absent or null, from before the engine reported it, is kept.
_OWN_MODEL_CALLS: Final = (
    "SELECT (m.meta->>'llm_input_tokens')::bigint AS input_tokens, t.qty AS seconds "
    "FROM usage_events m JOIN usage_events t "
    "ON t.call_id = m.call_id AND t.unit_type = 'telephony_s' "
    "WHERE m.unit_type = 'llm_ktok_in' AND m.call_id IS NOT NULL "
    "AND m.meta->>'own_model' IS NOT NULL AND m.meta->>'llm_input_tokens' IS NOT NULL "
    "AND m.meta->>'llm_input_tokens_estimated' IS DISTINCT FROM 'true' "
    "AND t.qty >= :min_seconds"
)
_LIVE_AGENTS: Final = "SELECT id FROM agents WHERE status = 'live' AND deleted_at IS NULL"


@dataclass(frozen=True, slots=True)
class TenantPrompts:
    measured: list[Decimal]
    published: list[int]


async def sample_tenant(
    session: AsyncSession, *, tenant_id: UUID, engine: VoiceEngine
) -> TenantPrompts:
    """One tenant's own-model calls and its live agents' prompt sizes. Tenant session only:
    RLS is the filter."""
    from apps.api.agents.prompt_size import publish_config

    rows = (await session.execute(text(_OWN_MODEL_CALLS), {"min_seconds": MIN_CALL_SECONDS})).all()
    measured = [effective_prompt_tokens(int(r.input_tokens), Decimal(r.seconds)) for r in rows]
    published: list[int] = []
    for (agent_id,) in (await session.execute(text(_LIVE_AGENTS))).all():
        try:
            cfg = await publish_config(
                session, tenant_id=tenant_id, agent_id=agent_id, engine=engine
            )
        except ProblemError as exc:
            # A live agent the publish path could not compose now (no script) would be
            # refused at its next publish too; its old prompt is not ours to read.
            log.warning(
                "own_model_prompt_agent_skipped",
                extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "reason": exc.code},
            )
            continue
        published.append(prompt_tokens_of(compose_engine_prompt(cfg)))
    return TenantPrompts(measured=measured, published=published)


# --- the walk and the cache -----------------------------------------------------------------

_DIRECTORY: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL"


async def compute_prompt_basis(engine: VoiceEngine) -> PromptBasis:
    """Walk every live tenant once (`admin_session` reads the directory only) and resolve
    the basis."""
    async with admin_session() as directory:
        tenants = [UUID(str(r[0])) for r in (await directory.execute(text(_DIRECTORY))).all()]
    measured: list[Decimal] = []
    published: list[int] = []
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            sample = await sample_tenant(session, tenant_id=tenant_id, engine=engine)
        measured += sample.measured
        published += sample.published
    return basis_from(measured, published, computed_at=datetime.now(UTC))


async def refresh_prompt_basis(engine: VoiceEngine) -> PromptBasis:
    """Compute the basis and store it for `CACHE_TTL_S`. The hourly sweep's step."""
    basis = await compute_prompt_basis(engine)
    payload = {
        "prompt_tokens": basis.prompt_tokens,
        "source": basis.source,
        "calls": basis.calls,
        "agents": basis.agents,
        "computed_at": basis.computed_at.isoformat() if basis.computed_at else None,
    }
    await get_redis().set(_CACHE_KEY, json.dumps(payload), ex=CACHE_TTL_S)
    log.info(
        "own_model_prompt_basis_refreshed",
        extra={"source": basis.source, "prompt_tokens": basis.prompt_tokens},
    )
    return basis


async def current_prompt_basis() -> PromptBasis:
    """The stored basis, or `CEILING_BASIS` when none is stored or Redis cannot answer: the
    ceiling only raises a floor, so an outage cannot make a card look cheaper."""
    try:
        raw = await get_redis().get(_CACHE_KEY)
    except RedisError as exc:
        log.warning("own_model_prompt_basis_unreadable", extra={"error": type(exc).__name__})
        return CEILING_BASIS
    if raw is None:
        return CEILING_BASIS
    stored = json.loads(raw)
    return PromptBasis(
        prompt_tokens=int(stored["prompt_tokens"]),
        source=stored["source"],
        calls=int(stored["calls"]),
        agents=int(stored["agents"]),
        computed_at=datetime.fromisoformat(stored["computed_at"]),
    )


async def floor_prompt_basis() -> PromptBasis | None:
    """The basis a floor-judging route strikes the model half at while our model is switched
    on, else None (no model half, so no Redis read). The route passes `prompt_tokens` as
    `own_model_prompt_tokens` and shows `label` to the operator."""
    if not get_settings().thinnest_own_model:
        return None
    return await current_prompt_basis()


def tokens_of(basis: PromptBasis | None) -> int | None:
    return None if basis is None else basis.prompt_tokens


__all__ = [
    "CACHE_TTL_S",
    "CEILING_BASIS",
    "CEILING_PROMPT_CHARS",
    "CEILING_PROMPT_TOKENS",
    "GEMINI_CHARS_PER_TOKEN",
    "MIN_CALLS",
    "MIN_CALL_SECONDS",
    "NON_ASCII_TOKENS_PER_CHAR",
    "PERCENTILE",
    "PromptBasis",
    "PromptSource",
    "TenantPrompts",
    "basis_from",
    "compute_prompt_basis",
    "current_prompt_basis",
    "effective_prompt_tokens",
    "floor_prompt_basis",
    "prompt_tokens_of",
    "refresh_prompt_basis",
    "sample_tenant",
    "tokens_of",
]
