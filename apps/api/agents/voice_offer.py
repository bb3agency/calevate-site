"""Is a minute on this voice provider's tier billable here, and is its key installed?

Two grounds every Studio voice is asked before it can be sold:

1. **An attested TTS price** — hard rule 7: an unpriced minute is unmetered spend, not a
   free one, and the only place the refusal is free is the selection. The predicate is
   INJECTED: `ops/pricing_snapshot.py` installs a reader over the attested-price store
   (`ops/model_pricing.tts_price_is_billable`) at startup and refreshes it on the same
   30-second poll the LLM price readers use, so attesting a Cartesia price in the ops
   console makes the tier offerable within one poll. `default_tts_price_is_billable` is
   what answers before that has happened.
2. **An installed key** — `cartesia_credential_installed`, the key ThinnestAI's own-key
   voice scope is given (`agents/studio_voices.py`).
"""

from __future__ import annotations

from collections.abc import Callable

from apps.api.agents.voices import VoiceProvider
from apps.api.core.settings import get_settings

#: A sync predicate: is a minute on this provider's tier BILLABLE — attested, or read from
#: the vendor? The same contract `billing/rates.llm_price_is_billable` has for a model.
TtsPriceReader = Callable[[VoiceProvider], bool]


def default_tts_price_is_billable(provider: VoiceProvider) -> bool:
    """The answer BEFORE anything has been read from the price store: **never**.

    The voice leg is billed by its vendor on a plan this process cannot read, so with no
    attestation behind it nothing is billable — the same statement
    `ops/model_pricing.tts_price_is_billable` makes with an empty table.

    PUBLIC because `ops/pricing_snapshot.py` builds its cold snapshot from it (D-547): one
    definition is what stops the window between startup and the first read from having its
    own rule.
    """
    del provider
    return False


_price_reader: TtsPriceReader | None = None


def install_tts_price_reader(reader: TtsPriceReader | None) -> None:
    """Register where "is this tier priced" comes from. `None` uninstalls.

    The sibling of `agents/llm_models.install_llm_credential_reader` and
    `billing/rates.install_llm_price_attestations`: the offer must not import the ops
    console, and it must stay exercisable with no database.
    """
    global _price_reader
    _price_reader = reader


def tts_price_is_billable(provider: VoiceProvider) -> bool:
    """The price ground, in one place."""
    reader = _price_reader or default_tts_price_is_billable
    return reader(provider)


def cartesia_credential_installed() -> bool:
    """Is a Cartesia API key installed on this deployment?

    Read from `get_settings()`, into which the ops console's encrypted store is overlaid
    (`core/settings.apply_platform_overrides`), so a key pasted in the console and a key
    injected from the secrets manager both land here. Blank-stripped because an operator
    clearing the field leaves `""`.
    """
    return bool((get_settings().cartesia_api_key or "").strip())


__all__ = [
    "TtsPriceReader",
    "cartesia_credential_installed",
    "default_tts_price_is_billable",
    "install_tts_price_reader",
    "tts_price_is_billable",
]
