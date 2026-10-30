"""Which model an ACCOUNT runs, read once, for the dashboard-assist selector.

WHY THIS IS ITS OWN FILE, in one paragraph. `workers/extraction.assist_capability` needs
the tenant's chosen model as a VALUE (it is a pure function of its arguments and must stay
one), and `agents/llm_models` turns a model into a `TenantModelLeg` but reads no database —
that is a stated invariant of both modules, and both are load-bearing. Something has to run
the one-row query in between. Spelling it at each of the three assist surfaces would be the
same SELECT in three places, which is the D-103 defect on the smallest possible scale; this
is the one place the column name is written.

RLS DOES THE SCOPING, exactly as `agents/llm_routes._read_defaults` argues at length: the
`organizations` policy matches on `id`, so this reads the account the session is scoped to
and a wrong id is zero rows rather than a neighbour's. No `WHERE` on the tenant is wanted —
one would be a second, weaker expression of the isolation the policy already enforces.
`deleted_at IS NULL` is not scoping and is not redundant with it; it is the same predicate
every other reader of this row carries.

**IT ANSWERS AT THE ACCOUNT LEVEL, NOT THE AGENT LEVEL, AND THAT IS DELIBERATE.** An agent
may name its own model (`resolve_llm_model`'s first rung), but the assist surfaces this
serves are not per-agent: the copilot is a floating panel over whatever screen is open, and
the re-summarise route acts on a call whose agent may since have been re-pointed. The
question the selector actually asks is "may Calevate run the assistant on the provider this
CLIENT is on", which the account's own choice answers and an agent's override only
narrows. Passing an agent model would make one client's assistant leg change depending on
which call they opened, with no sentence anywhere explaining why.
"""

from __future__ import annotations

from calevate_shared.engine import leg_for_model
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.llm_models import (
    NO_DATA_USE_ATTESTATION_REASON,
    off_call_offerable_models,
    resolve_llm_model,
    tenant_dashboard_leg,
    unofferable_reason,
)
from apps.api.core.alerting import alert
from apps.api.core.settings import get_settings
from apps.workers.extraction import GOOGLE_PROVIDER, TenantModelLeg

#: The account's own choice. `id` is not needed — nothing here quotes a plan or a price.
_ORG_MODEL = "SELECT default_llm_model FROM organizations WHERE deleted_at IS NULL"


async def account_assist_leg(session: AsyncSession) -> TenantModelLeg:
    """The model this session's account runs, and whether the assistant may run on it.

    NO `None` RETURN AND NO REFUSAL FOR A MISSING ROW. `resolve_llm_model`'s third rung is
    the platform's own model and is always there, so "this account has not chosen one" and
    "this account row is not visible" both resolve to the platform model — which is exactly
    what the assistant would have run before this seam existed. A refusal here would turn a
    closed account's stale browser tab into a 404 on the assistant instead of the ordinary
    refusal the surface behind it already produces.
    """
    row = (await session.execute(text(_ORG_MODEL))).first()
    chosen: str | None = row[0] if row is not None else None
    resolved = resolve_llm_model(agent_model=None, organization_model=chosen)
    # **THE RUNG TRAVELS WITH THE MODEL, AND DROPPING IT WAS A CLIENT-FACING FALSEHOOD.**
    # This passed the resolved identifier alone, so an account that had chosen nothing was
    # described to the assist ladder as having a provider of its own — and on the
    # substitution rung the client read "not the AI model you chose for your account". They
    # chose nothing; we chose for them. That is a PLATFORM fact stated as a fact about their
    # account, the defect class `NO_CREDENTIAL_REASON`'s own note exists to prevent, and
    # D-530 made it the DEFAULT path by moving the platform model to a leg this dashboard
    # cannot serve.
    #
    # ⚠ **THE SHORTCUT IS `tenant_leg=None` ON THE PLATFORM RUNG, AND IT IS WRONG.** `None`
    # means "no account in hand", which skips `assist_capability`'s rung-1 Gemini arm
    # entirely (it requires a leg) — so a deployment whose Gemini leg is attested and keyed,
    # running the platform default, would be silently moved onto Azure with no disclosure,
    # because `serves_dashboard` was never consulted. The leg is still passed; only the
    # sentence changes.
    if leg_for_model(resolved.model).provider == GOOGLE_PROVIDER:
        return google_assist_leg()
    own = tenant_dashboard_leg(model=resolved.model, source=resolved.source)
    if own.serves_dashboard:
        return own
    # Gemini is the platform's main model (founder, 27 Oct 2026): an account whose own leg
    # cannot serve the assistant gets the platform's Gemini leg before the optional Azure rung
    # and the disclosed Sarvam standby. When Gemini cannot serve either, the account's own leg
    # is kept so the ladder's refusal names the account's ground.
    platform = google_assist_leg()
    return platform if platform.serves_dashboard else own


def google_assist_leg() -> TenantModelLeg:
    """The Google arm of the dashboard assists, on the assistant's fast model (D-786), or
    on the other Pip model when the fast one is not priced (`google_leg_for`).

    NOT the account's own Gemini id. Under ThinnestAI an account's model is only an id
    (the engine runs its own), so what this leg sends to Google on OUR key is a platform
    choice, and the account default, `gemini-2.5-flash-lite`, 404s on a Google project that
    never used 2.5 (ai.google.dev/gemini-api/docs/models, updated 2026-10-13)."""
    return google_leg_for(get_settings().copilot_fast_model)


def pip_gemini_models() -> tuple[str, ...]:
    """The Gemini models Pip and the dashboard assists may run on, fast first."""
    settings = get_settings()
    return tuple(dict.fromkeys((settings.copilot_fast_model, settings.copilot_planning_model)))


def google_leg_for(model: str) -> TenantModelLeg:
    """`model` as a Google dashboard leg; else another Pip Gemini model that can serve; else
    `model`'s leg saying why it cannot.

    The founder does not require every Pip model to be priced (30 Oct 2026): an unpriced
    model is simply never CALLED (hard rule 7 — `off_call_offerable_models()` holds only
    models with a key and an attested price, and an unpriced model that answered would raise
    on the meter after Google was paid), and the priced one answers in its place, metered on
    its own attested price. That swap is the same provider under the same data-use
    attestation, so the client is told nothing; the operator gets a record-level notice. Only
    when no Pip Gemini model can serve does the selector move to Azure or the standby."""
    wanted = _google_leg(model)
    if wanted.serves_dashboard:
        return wanted
    keyed = bool(get_settings().gemini_api_key)
    for other in pip_gemini_models():
        if other == model:
            continue
        stand_in = _google_leg(other)
        if stand_in.serves_dashboard:
            if keyed:
                _note_gemini_substituted(model, other, wanted.blocked_reason or "")
            return stand_in
    # A deployment holding no Gemini key was not given Gemini at all (a dev box, a test run);
    # one that holds it and still cannot use it is missing a record an operator can add.
    if keyed:
        _alarm_gemini_unavailable(model, wanted.blocked_reason or "")
    return wanted


def _google_leg(model: str) -> TenantModelLeg:
    """One Gemini model as a dashboard leg. Price and key are asked first: `serves_dashboard`
    answers only the data-use question."""
    if model not in off_call_offerable_models():
        return TenantModelLeg(
            model=model,
            provider=GOOGLE_PROVIDER,
            serves_dashboard=False,
            blocked_reason=unofferable_reason(model, off_call=True)
            or "this model is not offerable here",
            account_chose_model=False,
        )
    return tenant_dashboard_leg(model=model, source="platform")


#: Raised when no Pip Gemini model can serve, so the assistant answers on the Sarvam standby
#: (or Azure, when configured) instead of Gemini.
GEMINI_UNAVAILABLE_ALARM = "assistant_gemini_unavailable"

#: Recorded when the Gemini model Pip wanted cannot serve and another Pip Gemini model
#: answers instead. Informational: Pip is working.
GEMINI_SUBSTITUTED_NOTICE = "assistant_gemini_model_substituted"


def _where_to_fix(reason: str) -> str:
    return (
        "Record it in Admin → Ops → Dashboard data use."
        if reason == NO_DATA_USE_ATTESTATION_REASON
        else "Fix it in Admin → Ops (AI models and prices)."
    )


def _alarm_gemini_unavailable(model: str, reason: str) -> None:
    """Tell an operator exactly what to record. The alert path suppresses repeats, so a
    request that hits this every time raises one notice per window."""
    alert(
        "CORE_LOGIC",
        GEMINI_UNAVAILABLE_ALARM,
        detail=(
            "No Gemini model Pip uses can serve the dashboard, so Pip and the dashboard "
            f"assists answer on a backup: {model}: {reason}. {_where_to_fix(reason)}"
        ),
        model=model,
    )


def _note_gemini_substituted(model: str, used: str, reason: str) -> None:
    alert(
        "CORE_LOGIC",
        GEMINI_SUBSTITUTED_NOTICE,
        detail=(
            f"Pip is using {used} because {model} cannot be used here ({reason}). "
            f"Nothing is wrong with Pip. To use {model}: {_where_to_fix(reason)}"
        ),
        model=model,
        used=used,
    )


__all__ = [
    "GEMINI_SUBSTITUTED_NOTICE",
    "GEMINI_UNAVAILABLE_ALARM",
    "account_assist_leg",
    "google_assist_leg",
    "google_leg_for",
    "pip_gemini_models",
]
