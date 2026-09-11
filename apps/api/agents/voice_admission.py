"""ADDING ONE CLONED VOICE, BY TYPING ITS FACTS AND HAVING THEM CHECKED (D-590).

WHY THIS MODULE EXISTS, AND WHAT IT SUPERSEDES
-----------------------------------------------
D-588 built a CURATION screen over the synced catalogue: 418 voices read off the voice
platform, 414 of which an operator had to switch off one at a time. The founder's answer was
that the catalogue is not the product — *"we will not actually be using any voices provided
by either sarvam or cartesia and will only be using cloned voices … I should be able to add
voices and build out thing in that way where I can provide you everything that you need a
voice to be added and working"*.

D-588 concluded the "add" half was unbuildable, and it got the premise right and the
conclusion wrong. **The premise stands: Bolna's voice API is READ-ONLY** — their whole
published API has two voice routes and both are GET (VERIFIED-VENDOR-DOCS, hash-pinned
mirror, `bolna-findings/mirror/pages/api-reference/voice/overview.md:10-18`, read 11 Sep
2026). Cloning happens in their Playground's Voice Lab (`https://platform.bolna.ai/voices`,
`pages/clone-voices.md:86`), from a 1-2 minute sample, on **ElevenLabs or Cartesia**
(`pages/clone-voices.md`, the "Select Provider" step); importing takes a voice id and an
optional connected-account toggle (`pages/import-voices.md`). None of that is ours.

**But adding a voice to THEIR platform and adding a voice to THIS product's catalogue are
two different acts, and only the first needs a write they do not offer.** The second needs
the operator's five facts and one read. That is this module.

THE FIVE FACTS ARE THE WIRE'S, NOT A FORM DESIGNER'S
------------------------------------------------------
They are derived from `engine/bolna.py::_synthesizer_config` and its Cartesia twin, which
between them need exactly four things in the vendor's synthesizer block — `model`,
`voice_id`, `voice` (the platform's own display NAME, which is **not derivable from the id**
for a cloned voice) and `language` — plus the one fact that decides the money:

* **provider** — `voices.VoiceProvider`. It IS the agent's voice tier (`voices.voice_tier`,
  plan §2.3 invariant 7, hard rule 7), and it is asked for rather than inferred so the
  operator's own statement can be cross-checked against the model they picked.
* **tts_model** — the vendor's `model` key. `voices.TtsModel`.
* **engine_voice_id** — the vendor's `voice_id`: the persona name, or a clone's generated id.
* **label** — the vendor's `voice` key. A WIRE value as well as a human one.
* **languages** — which of the three languages this product sells the voice serves. Not a
  wire key (the agent's own language is what travels), but the thing that decides which
  pickers the voice appears on.

**THE TIER IS STILL DERIVED AND IS NOT TAKEN FROM THE FORM.** `voice_id_for` composes
`<tts_model>:<engine_voice_id>`, and `voices.voice_tier` reads the tier back off that id's
model prefix through `TTS_MODEL_LIFECYCLE`. The `provider` field is an ATTESTATION that is
checked against the model and then thrown away: a form that could set a tier independently
of the id would be the one place an agent could hold a Cartesia voice and a Sarvam rate.

VERIFICATION IS THE POINT, NOT A NICETY
-----------------------------------------
A voice must be in the voice platform's own catalogue before a publish succeeds. That is not
a guess; it is a live `400 POST /v2/agent` on 11 Sep 2026 — *"Provided voice: Anushka is not
available for the provider: sarvam"* — which cost this project six publish attempts against
a real account. An unverified id is a row that saves, publishes, and fails on a client's
phone line, and the operator finds out from a caller.

So `admit_voice` reads the platform's list (`VoiceEngine.list_voices`, the same seam the
sync uses — hard rule 2: no vendor JSON leaves `apps/api/engine/`) and refuses unless the
id is really there, under the model claimed, with the name claimed, for the languages
claimed. Four refusals, each naming what the platform actually says, so the operator can fix
the field rather than guess which one was wrong.

**WHEN THE PLATFORM CANNOT BE READ, WE REFUSE AND SAY SO.** Three options were available:
accept unverified, accept-and-mark-unverified, or refuse. Accepting unverified is the one
this module exists to prevent — it is exactly the pre-D-585 state, with the failure moved
from a form the operator is looking at to a call they are not. Accept-and-mark is worse than
it sounds: the mark would have to block offering (or it protects nothing), so the voice
would sit in the console looking added and be unusable for reasons nobody is watching for.
Refusing costs one retry of a form that is already filled in, and a voice platform we cannot
read is one we also cannot publish against, so nothing is lost by waiting. The refusal is
`kind="dependency"` — RETRYABLE, which is what makes the console offer a retry rather than a
correction.

An INCOMPLETE listing is refused separately from a complete one that lacks the voice, and
the distinction is the same one `voice_sync` refuses to prune on: a page we could not read
looks exactly like a shorter catalogue, so "we did not find it" and "it is not there" are
different sentences and only the second is an accusation about the operator's typing.

WHAT AN ADDED ROW IS
----------------------
The SAME ROW a sync writes — `platform_voice_catalog`, same columns, same `Voice`, same
picker, same publish path — with `origin="operator"` and `curation_state="enabled"`. Two
consequences worth stating:

* **It does not require a sync to have happened.** The operator types the facts and the row
  exists. On a deployment that has never synced, adding a voice is still the whole flow.
* **Adding a voice that is already cached ADOPTS it** rather than failing on the primary
  key: the row's provenance becomes `operator`, its state becomes `enabled`, and any
  withdrawal stamp is cleared because we have just read the voice on the platform. That is
  the honest meaning of "I am attesting this voice", and it is idempotent, which is what a
  double-submitted form needs.

ELEVENLABS IS REFUSED BY NAME, AND THAT REFUSAL IS THE POINT
--------------------------------------------------------------
Bolna clones on **ElevenLabs or Cartesia**. This product's `TtsModel` is `bulbul:v3`
(Sarvam) and `sonic-3.5` (Cartesia) — there is no ElevenLabs model, therefore no
`TTS_MODEL_LIFECYCLE` row, therefore no provider, therefore no voice tier, therefore no
price for a minute of it (hard rule 7). A form that silently omitted ElevenLabs would let an
operator clone a voice there, come back, find no way to add it, and conclude the console is
broken. So it is OFFERED and REFUSED, with the reason, which is the only version of this
that tells them something they need before they spend a sample on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, get_args

from calevate_shared.engine import EngineVoice, EngineVoiceListing, VoiceEngine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voice_curation import CuratedVoice, read_one_curated_voice
from apps.api.agents.voices import (
    ADDED_CURATION_STATE,
    Language,
    TtsModel,
    VoiceProvider,
    provider_of_tts_model,
    tts_models_for_provider,
    voice_id_for,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: WHERE AN OPERATOR CLONES A VOICE. Printed in every refusal that sends them back there, so
#: the sentence and the URL cannot drift apart across four error bodies.
#: VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/clone-voices.md:86` ("Voice Lab"),
#: corroborated at `pages/guides/writing-prompts-in-non-english-languages.md:116`, read
#: 11 Sep 2026 in the hash-pinned mirror.
VOICE_LAB_URL: Final = "https://platform.bolna.ai/voices"

#: Providers the VOICE PLATFORM will clone on but this product cannot publish. ElevenLabs is
#: the whole of it today: Bolna's clone flow offers ElevenLabs or Cartesia
#: (VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/clone-voices.md`, "Select Provider"),
#: and we run Sarvam `bulbul:v3` and Cartesia `sonic-3.5`.
#:
#: SEPARATE FROM "a provider we have never heard of", because the two are different
#: mistakes: one is an operator who has just spent a voice sample on the wrong vendor and
#: needs telling why, the other is a typo.
UNPUBLISHABLE_CLONING_PROVIDERS: Final[frozenset[str]] = frozenset({"elevenlabs"})

#: The providers this product actually runs, DERIVED from the model registry rather than
#: typed — so a refusal message listing "what exists" cannot come to disagree with what the
#: catalogue offers. Ordered as `TtsModel` is (Sarvam, the default and cheaper tier, first).
OUR_PROVIDERS: Final[tuple[VoiceProvider, ...]] = tuple(
    dict.fromkeys(
        provider
        for model in get_args(TtsModel)
        if (provider := provider_of_tts_model(model)) is not None
    )
)


def unpublishable_provider_reason(provider: str) -> str:
    """WHY A VOICE CLONED ON THIS PROVIDER CANNOT BE ADDED — the sentence, in one place.

    It says the consequence first (this voice cannot be published or priced) and the cause
    second, because the operator reading it is holding a finished clone and needs to know
    whether to re-do it, not to learn our model catalogue.
    """
    return (
        f"{provider} is one of the two providers the voice platform will clone a voice on, "
        "but it is not a provider this product runs: there is no ElevenLabs TTS model in "
        "our catalogue, so a minute spoken on it has no voice tier and no price, and no "
        "agent could be published on it. Clone the voice again on Cartesia in the voice "
        f"platform's Voice Lab ({VOICE_LAB_URL}) and add it here as a Cartesia voice."
    )


@dataclass(frozen=True, slots=True)
class VoiceFacts:
    """THE FIVE FACTS AN OPERATOR TYPES for one voice — see the module docstring for why
    these five and no others.

    A dataclass rather than the route's Pydantic model so this module is drivable from a
    test with no HTTP, and so the route layer owns the bounds (length, membership) while
    this layer owns the TRUTH (does the platform agree).
    """

    #: The operator's claim about who synthesises the voice. Cross-checked against
    #: `tts_model` and then discarded — see the module docstring on why the tier is derived.
    provider: str
    #: The vendor's `model` key.
    tts_model: str
    #: The vendor's `voice_id` key. Never parsed, never normalised — an opaque vendor string.
    engine_voice_id: str
    #: The vendor's `voice` key: the platform's own display NAME for the voice.
    label: str
    #: Which of this product's languages the voice serves.
    languages: tuple[Language, ...]


def _normalised(label: str) -> str:
    """A display name reduced to what a comparison may fairly ignore: surrounding and
    repeated whitespace, and case.

    NOT a normalisation of what we STORE — the platform's own spelling is what goes in the
    row and onto the wire. This exists only so an operator who typed `raghava clone` is not
    refused over a capital R while an operator who typed a different voice's name still is.
    """
    return " ".join(label.split()).casefold()


def _refuse_unknown_provider(provider: str) -> ProblemError:
    """A provider that is neither ours nor a known cloning provider — a typo, most likely."""
    ours = ", ".join(OUR_PROVIDERS)
    return ProblemError.business_rule(
        "voice_provider_unknown",
        f"This product has no voice provider called {provider!r}. It runs {ours}.",
        remediation=f"Choose one of: {ours}.",
    )


def check_provider(provider: str) -> None:
    """Ground 1: is this a provider this product can publish and price at all?

    Ordered so the INFORMATIVE refusal comes first: an operator naming ElevenLabs has made a
    real, expensive mistake and gets the sentence that explains it, while an operator naming
    `sarvem` gets the list of what exists. Collapsing the two into "unknown provider" would
    be the silent omission the founder must not be given.
    """
    if provider.strip().casefold() in UNPUBLISHABLE_CLONING_PROVIDERS:
        raise ProblemError.business_rule(
            "voice_provider_not_published_here",
            unpublishable_provider_reason(provider.strip().casefold()),
            remediation=(
                "Re-clone the voice on Cartesia in the voice platform's Voice Lab, then add "
                "it here as a Cartesia voice."
            ),
        )
    if not tts_models_for_provider(provider):
        raise _refuse_unknown_provider(provider)


def check_model_matches_provider(*, provider: str, tts_model: str) -> TtsModel:
    """Ground 2: does the model the operator named belong to the provider they named?

    Returns the model NARROWED to `TtsModel`, which is the only way a `TtsModel` is produced
    in this module — no `cast`, for `voice_sync._offered_model`'s reason: what arrives here
    is a string a person typed, and narrowing it on evidence is the whole job.

    The cross-check exists because the two fields are two statements about one voice and a
    disagreement between them means the operator is not holding the voice they think they
    are. Today each provider has exactly one model, so this can only fail on a swap; it is
    written against the general case because `tts_models_for_provider` is.
    """
    offered = tts_models_for_provider(provider)
    for model in offered:
        if model == tts_model:
            return model
    listed = ", ".join(offered)
    raise ProblemError.business_rule(
        "voice_model_not_on_provider",
        f"{provider} does not run the model {tts_model!r} on this product. It runs {listed}.",
        remediation=f"Choose {listed} for a {provider} voice, or change the provider.",
    )


async def read_platform_listing(engine: VoiceEngine) -> EngineVoiceListing:
    """The voice platform's own list, or a RETRYABLE refusal — never a shrug.

    Wrapped here rather than at the route so every caller of `admit_voice` gets the same
    verdict, and so the one thing that must not happen — a transport failure read as "the
    voice is not there" — is impossible by construction rather than by care.

    A `ProblemError` from the seam itself is re-raised untouched: `require_capability` uses
    one to say "this engine supplies its own voices", which is a product fact and not an
    outage, and burying it under a retry message would tell an operator to try again forever.
    """
    try:
        return await engine.list_voices()
    except ProblemError:
        raise
    except Exception as exc:
        log.warning(
            "voice_admission_listing_failed",
            extra={"engine": engine.name, "reason": type(exc).__name__},
        )
        raise ProblemError(
            kind="dependency",
            code="voice_check_unavailable",
            title="The voice platform could not be read",
            detail=(
                "A voice can only be added once the voice platform confirms it exists on "
                "our account, and its voice list could not be read just now. Nothing was "
                "saved."
            ),
            remediation=(
                "Try again in a moment. If it keeps failing, check the voice platform "
                "credential in the ops console — a voice platform we cannot read is also "
                "one we cannot publish agents against."
            ),
        ) from exc


def find_on_platform(
    listing: EngineVoiceListing, *, tts_model: TtsModel, engine_voice_id: str
) -> EngineVoice:
    """The platform's own row for this voice — or the refusal that says why not.

    **THE TWO NOT-FOUND CASES ARE DIFFERENT SENTENCES AND DIFFERENT KINDS**, which is the
    whole reason `EngineVoiceListing.complete` is carried across the seam. A COMPLETE listing
    that does not name the voice is a statement about the voice: it is not there, the
    operator mistyped the id or is looking at another account, and no retry fixes it
    (`business_rule`, not retryable). An INCOMPLETE listing is a statement about our READ:
    we stopped part way, so the voice may well be there (`dependency`, retryable).

    Collapsing them would produce the worst possible message — telling an operator their
    correctly-typed voice id does not exist because a pagination cap was hit.
    """
    for voice in listing.voices:
        if voice.tts_model == tts_model and voice.voice_id == engine_voice_id:
            return voice
    if not listing.complete:
        raise ProblemError(
            kind="dependency",
            code="voice_check_incomplete",
            title="The voice platform's list could not be read in full",
            detail=(
                f"We did not find {engine_voice_id!r} under {tts_model}, but the voice "
                "platform's list came back incomplete, so it may simply be on a page we "
                "could not read. Nothing was saved, and nothing was concluded about the "
                "voice."
            ),
            remediation="Try again in a moment.",
        )
    raise ProblemError.business_rule(
        "voice_not_on_platform",
        (
            f"The voice platform does not list {engine_voice_id!r} for {tts_model} on our "
            "account, so an agent published on it would be refused at create time with "
            '"not available for the provider". Nothing was saved.'
        ),
        remediation=(
            "Check the voice id against the voice platform's Voice Lab "
            f"({VOICE_LAB_URL}) — it is the provider-specific id, not the voice's name. If "
            "you have only just cloned or imported it there, press Refresh here first."
        ),
    )


def check_label(entry: EngineVoice, *, label: str) -> str:
    """Ground 4: does the name the operator typed match the platform's own name?

    Returns the PLATFORM'S spelling, which is what gets stored and sent — `label` is a WIRE
    value (`_synthesizer_config` puts it in the vendor's required `voice` key), so ours must
    be theirs byte for byte.

    **WHY THIS IS A REFUSAL RATHER THAN A SILENT OVERWRITE.** Taking the platform's name and
    ignoring what was typed was the first shape and it is the wrong one: the typed name is
    the operator's statement that they are adding the voice they think they are, and it is
    the only check that catches a voice id which is valid but belongs to a DIFFERENT voice —
    the one mistake verification would otherwise wave through. A mismatch prints the exact
    string to use, so the correction costs one paste.

    Case and whitespace are forgiven (`_normalised`) because refusing over a capital letter
    teaches an operator that the check is noise.
    """
    if _normalised(entry.label) != _normalised(label):
        raise ProblemError.business_rule(
            "voice_name_mismatch",
            (
                f"The voice platform lists {entry.voice_id!r} under the name "
                f"{entry.label!r}, not {label!r}. That name travels to the engine on every "
                "publish, so it has to be the platform's own — and a name that does not "
                "match usually means the voice id belongs to a different voice."
            ),
            remediation=f"Use the name {entry.label!r}, or check the voice id.",
        )
    return entry.label


def check_languages(entry: EngineVoice, *, languages: tuple[Language, ...]) -> tuple[Language, ...]:
    """Ground 5: does the platform list this voice for every language the operator claimed?

    The operator's list is allowed to be NARROWER than the platform's — choosing not to offer
    a voice in Hindi is a product decision, and this function returns what they chose, in the
    product's own picker order. It may not be WIDER: a language the platform does not list is
    a language the voice will not be synthesised in, and putting it on a Telugu picker would
    reproduce the exact class of failure (a row that saves and fails on a call) that
    verification exists to end.
    """
    listed = set(entry.languages)
    missing = [language for language in languages if language not in listed]
    if missing:
        available = ", ".join(entry.languages) or "no language this product sells"
        raise ProblemError.business_rule(
            "voice_language_not_listed",
            (
                f"The voice platform lists {entry.voice_id!r} for {available}, not for "
                f"{', '.join(missing)}."
            ),
            remediation=f"Choose from: {available}.",
        )
    return languages


async def admit_voice(
    session: AsyncSession,
    engine: VoiceEngine,
    facts: VoiceFacts,
    *,
    now: datetime | None = None,
) -> CuratedVoice:
    """ADD ONE VOICE, having checked every fact against the voice platform. IDEMPOTENT.

    The five checks run in the order an operator can act on them — their own two fields
    first (provider, model), then the platform read, then the three facts only the platform
    can settle — so a form with two mistakes in it reports the one they can fix without
    waiting on a vendor call.

    **THE CALLER COMMITS** (BACKEND-PATTERNS §4), so the row and its `audit_log` entry are
    one act. The provenance of a typed row is the single fact in this table that re-running
    the sync cannot reconstruct, and a row saying an operator attested a voice with no record
    of which operator would be worse than no row.

    Idempotent at the row: an id already in the cache is ADOPTED (`origin` becomes
    `operator`, the state becomes `enabled`, any withdrawal stamp is cleared because we have
    just read the voice on the platform). A double-submitted form is one outcome, not a
    primary-key error.
    """
    check_provider(facts.provider)
    model = check_model_matches_provider(provider=facts.provider, tts_model=facts.tts_model)
    listing = await read_platform_listing(engine)
    entry = find_on_platform(listing, tts_model=model, engine_voice_id=facts.engine_voice_id)
    label = check_label(entry, label=facts.label)
    languages = check_languages(entry, languages=facts.languages)

    stamp = now or datetime.now(UTC)
    voice_id = voice_id_for(model, facts.engine_voice_id)
    row = {
        "voice_id": voice_id,
        "engine_voice_id": facts.engine_voice_id,
        "label": label,
        "tts_model": model,
        # DERIVED FROM THE MODEL, never taken from the form — see the module docstring. The
        # operator's `provider` field was an attestation, checked above and discarded here,
        # so there is exactly one path from a voice to its billing tier (hard rule 7).
        "provider": _one_provider(model),
        "languages": list(languages),
        # THE ENGINE'S OWN `source` ENUM, carried rather than assumed. An operator adding a
        # STOCK persona by hand is legitimate and this must not call it a clone.
        "is_custom": entry.is_custom,
        # WE JUST READ THIS VOICE ON THE PLATFORM, so "when did a read last see it" is now.
        "synced_at": stamp,
        "curation_state": ADDED_CURATION_STATE,
        "curated_at": stamp,
        "withdrawn_at": None,
        "origin": "operator",
    }
    statement = insert(PlatformVoiceCatalogEntry).values([row])
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[PlatformVoiceCatalogEntry.voice_id],
            # EVERY COLUMN, `curation_state` and `origin` INCLUDED — the opposite of the
            # sync's upsert, and deliberately. A sync reports what the vendor has and may
            # not touch an operator's decision; this IS the operator's decision, so adopting
            # a cached row over-writes the provenance and the state on purpose.
            set_={key: statement.excluded[key] for key in row if key != "voice_id"},
        )
    )
    log.info(
        "voice_admitted",
        extra={"voice_id": voice_id, "tts_model": model, "is_custom": entry.is_custom},
    )
    return await read_one_curated_voice(session, voice_id=voice_id)


def _one_provider(model: TtsModel) -> VoiceProvider:
    """The provider of a model that is known to have one — `TTS_MODEL_LIFECYCLE`, through the
    same door every other reader uses.

    It cannot return None for a member of `TtsModel` (`scripts/check_model_lifecycle` holds
    the registry to exactly that set), and it raises rather than defaulting if it ever does:
    a voice whose provider we guessed is a minute billed at a rate nobody chose.
    """
    from apps.api.agents.voices import provider_of_tts_model

    provider = provider_of_tts_model(model)
    if provider is None:  # pragma: no cover - held by check_model_lifecycle
        raise ProblemError.business_rule(
            "voice_model_unknown",
            f"{model} has no provider in the model registry, so its voice tier is unknown.",
        )
    return provider


__all__ = [
    "OUR_PROVIDERS",
    "UNPUBLISHABLE_CLONING_PROVIDERS",
    "VOICE_LAB_URL",
    "VoiceFacts",
    "admit_voice",
    "check_label",
    "check_languages",
    "check_model_matches_provider",
    "check_provider",
    "find_on_platform",
    "read_platform_listing",
    "unpublishable_provider_reason",
]
