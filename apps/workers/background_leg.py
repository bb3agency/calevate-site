"""The model a background assist job runs on: Gemini first, Azure only if configured.

Pip's memory distillation and the knowledge glosses run with nobody waiting and no account
choosing a model, so they take the platform's leg in the founder's order (D-899: Gemini is
Calevate's main model; Azure is used only when it is configured). There is no Sarvam rung:
both jobs write durable rows that are read back into later prompts, and the standby's terms
permit training on its inputs (CLAUDE.md, "Language models outside the call").

The Gemini arm needs exactly what Pip's needs, through `google_assist_leg`: the key, an
attested price (so the meter cannot raise after Google was paid, hard rule 7) and the Google
data-use attestation, whose absence raises `assistant_gemini_unavailable` naming what to
record.

On Gemini these jobs ask on the Flex tier first (D-930, `workers/model_tiers.py`); Azure
has no such tier.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from calevate_shared.engine import azure_openai_base_url, google_openai_compat_base_url

from apps.api.core.settings import get_settings
from apps.workers import chat
from apps.workers.model_tiers import FlexAllowance


@dataclass(frozen=True, slots=True)
class BackgroundLeg:
    leg: chat.ChatLeg
    #: What the call is priced as. On Azure this is the model SETTING, never the deployment
    #: id the call is addressed to (D-410/D-417), which no rate is published for.
    meter_model: str
    #: This job's Flex allowance, one per tick; None on Azure.
    flex: FlexAllowance | None = None

    @property
    def is_gemini(self) -> bool:
        return self.leg.dialect == "google"

    async def complete(
        self, messages: Sequence[chat.ChatMessage], *, timeout_s: float, **kwargs: Any
    ) -> tuple[chat.ChatOutcome, chat.ServiceTier]:
        """`chat.complete` on this leg, on Flex while the allowance gives a wait; returns
        the answer and the tier that served it, which is what the meter records."""
        asked = None if self.flex is None else self.flex.request(standard_timeout_s=timeout_s)
        outcome = await chat.complete(self.leg, messages, timeout_s=timeout_s, flex=asked, **kwargs)
        if self.flex is None or asked is None:
            return outcome, "standard"
        self.flex.note(asked, outcome)
        return outcome, outcome.service_tier


def background_leg(azure: tuple[str, str, str] | None, *, call: str) -> BackgroundLeg | None:
    """`azure` is the caller's `extraction.azure_credentials()`, passed in so each job keeps
    one reader of the Azure settings it can stub. `call` names the job in
    `model_tiers.MODEL_CALLS`. None when neither leg can serve."""
    from apps.api.agents.assist_leg import google_assist_leg

    settings = get_settings()
    gemini = google_assist_leg()
    if gemini.serves_dashboard and settings.gemini_api_key:
        return BackgroundLeg(
            chat.ChatLeg(
                url=f"{google_openai_compat_base_url()}/chat/completions",
                api_key=settings.gemini_api_key,
                wire_model=gemini.model,
                dialect="google",
            ),
            gemini.model,
            FlexAllowance(call),
        )
    if azure is None:
        return None
    resource, api_key, deployment = azure
    return BackgroundLeg(
        chat.ChatLeg(
            url=f"{azure_openai_base_url(resource)}/chat/completions",
            api_key=api_key,
            wire_model=deployment,
            dialect="openai",
        ),
        settings.azure_openai_model,
    )
