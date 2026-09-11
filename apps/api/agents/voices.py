"""The voice catalog: which TTS voices an agent may speak in, as DATA.

`agents.tts_voice` is a free-text column (`agents/models.py`, DATA-MODEL §2 lists it
among the "config strings"). Free text is fine for the DB — model choices are config,
not code (D-04/D-20/D-36) — but it is not fine for the UI or the API: an operator who
types `bulbul-v3` or `Anushka` gets a row that looks saved, publishes cleanly, and is
discovered to be wrong at CALL TIME, on a real client's phone. This module is the
allowlist that turns that runtime failure into a 422.

TWO VOICE TIERS, ONE CATALOGUE (D-547 — supersedes the single-tier decision)
------------------------------------------------------------------------------
The single-tier decision collapsed the old premium/value ladder (D-36/D-35/D-34) into ONE
Sarvam quality. D-547 (`docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md`) re-opens the dimension
in a different shape: a **second PROVIDER**, Cartesia `sonic-3.5`, chosen **per agent**,
priced **per credit lot** at that lot's rate for the agent's tier. So a `Voice` now carries
`provider: sarvam | cartesia`, and `voice_tier()` below is the ONE derivation of an
agent's tier — a pure function of its chosen voice's provider (plan §2.3 invariant 7:
there is no way to hold a Cartesia voice and a Sarvam tier, because the tier is not
stored anywhere it could disagree).

**NO PRICE IS WRITTEN IN THIS MODULE.** It used to say "₹5.00/min, ₹30 per 10k chars"
in this docstring and in every entry's note. A rate card belongs to `billing/` — under
D-547 a minute's price is the rate frozen on the credit lot it draws from, and there
are two of them per lot — so a figure here would be a second, stale definition of a
number that reaches money (hard rule 7). What this module says about cost is the TIER,
which is the only pricing fact a voice has.

**"Two providers" is still not "two qualities of Sarvam".** Bulbul v2 stays withdrawn;
clients choose a PERSONA within a provider. The `Voice` model keeps its persona fields.

⚠ THE CATALOGUE IS NO LONGER COMPILED. IT IS READ FROM THE ENGINE (D-585, 11 Sep 2026)
--------------------------------------------------------------------------------------
This module used to BE the catalogue: 44 speaker names copied from Sarvam's own SDK, and
`CATALOG` was a frozen tuple built from them. **Both halves of that were wrong in a way
only a live call could show.**

1. **We do not publish to Sarvam; we publish through the ENGINE**, whose Sarvam provider
   offers a DIFFERENT SUBSET. A live publish on 11 Sep 2026 returned `400 POST /v2/agent` —
   *"Provided voice: Anushka is not available for the provider: sarvam"*. `anushka` is the
   FIRST name in the vendor SDK's enum. A catalogue compiled from the model vendor is a
   picker that saves a row, publishes, and fails on a client's phone line.
2. **A CLONED voice cannot be in a compiled `Literal` at all, by construction.** The
   founder clones a voice after this code ships; its id exists only on the engine account.
   No amount of care with a hand-written list reaches it.

So the voices in force now come from `agents/voice_sync.py`, which reads the engine's own
two-step voice-config API (`VoiceEngine.list_voices`), caches the rows in
`platform_voice_catalog`, and installs them here as a process snapshot
(`install_voice_catalogue`). **`catalogue()` — never a constant — is what a reader asks.**

⚠ **AND THE LAST COMPILED VOICE IS GONE TOO (D-588, 11 Sep 2026).** D-585 left a SEED
behind — nine speaker names a live engine read had returned — as the fallback for the
window before the first sync, plus the vendor's 44-name `Speaker` Literal it was typed
from. Both are deleted. The founder's requirement is that **only the voices an operator has
ENABLED in the console are selectable by anyone**, and a compiled fallback is by
construction a list nobody enabled: it put voices in front of a client that no operator had
ever looked at, on precisely the deployments (a fresh one, a broken credential) where
nobody was watching. So a process that has never synced offers NOTHING — `catalogue()` is
`()` and `catalogue_source()` is `"unsynced"` — and every surface that renders a picker
says what to do about it in a sentence. That is the correct answer, not an outage.

**CURATION IS NOT IN THIS MODULE, AND THAT IS DELIBERATE.** `catalogue()` answers "what ids
exist and what does each one mean" — it is the LOOKUP layer, and it is on the publish path
(`speech_for_voice_id`, `get_voice`). Whether a voice may be OFFERED to somebody is
`agents/voice_offer.py`'s fourth ground. Filtering the disabled out of here instead would
make an operator's console click un-resolve the id a LIVE agent is already speaking:
`speech_for_voice_id` would stop recognising it, pass the whole `bulbul:v3:priya` string
through in the speaker slot, and the next republish or drift sweep would send the engine a
speaker no vendor has ever heard of. The vocabulary a curation state is written in lives
here (`CurationState`) because it is a fact about a voice; the verdict does not.

WHERE A NEW VOICE COMES FROM: AN OPERATOR TYPES IT, AND WE CHECK IT (D-590)
----------------------------------------------------------------------------
⚠ **THE PARAGRAPH BELOW USED TO CONCLUDE "so the admin console's Voices page is a CURATION
surface and says so". THAT CONCLUSION IS SUPERSEDED; ITS PREMISE IS NOT.** Bolna's voice
API really is read-only, and nothing in this repository can clone or import a voice on their
platform. What D-588 got wrong is that adding a voice to *their* platform and adding a voice
to *this product's catalogue* are two different acts, and only the first needs a write they
do not offer. The second needs a read.

So `agents/voice_admission.py` takes the facts an operator types for ONE cloned voice — the
provider, the model, the id the platform knows it by, the name it shows, and which of our
three languages it serves — VERIFIES every one of them against the platform's own listing,
and writes the row itself (`origin="operator"`, arriving ENABLED, because typing a voice's
facts IS the decision to offer it). A synced row and an added row are the same shape and the
same `Voice`; `VoiceOrigin` is the only thing that tells them apart.

**BOLNA'S VOICE API IS READ-ONLY.** Their entire published API surface has exactly two
voice routes and both are GET: `GET /api/v1/voice-config/tts` (providers and their models)
and `GET /api/v1/voice-config/tts/voices` (paginated voices for a provider + model). There
is no create, no update and no delete for a voice anywhere in it (VERIFIED-VENDOR-DOCS,
hash-pinned mirror, every page enumerated 11 Sep 2026:
`bolna-findings/mirror/pages/api-reference/voice/overview.md:17-18`, and the method sweep
over `pages/api-reference/` returns those two lines and nothing else).

ADDING a voice ON THEIR PLATFORM is therefore a DASHBOARD act, in their Playground (Voice
Lab, `https://platform.bolna.ai/voices` — VERIFIED-VENDOR-DOCS,
`bolna-findings/mirror/pages/clone-voices.md:86`), and it is one of two:
IMPORT by voice id (`pages/import-voices.md`, with an optional connected-account toggle for
a voice cloned on your own provider account) or CLONE from a 1-2 minute audio sample
(`pages/clone-voices.md`, which names **ElevenLabs or Cartesia** as the cloning providers).
Nothing in this repository can do either, and no amount of console is going to change that.
What our console does is the step AFTER it: the operator brings back the id and the name,
and we admit the voice to this catalogue once the platform's own list confirms both.

WHAT IS GROUNDED, AND WHERE
---------------------------
- **The model string is `bulbul:v3`.** VERIFIED-VENDOR-SDK: same wheel,
  `types/text_to_speech_model.py` (`Literal["bulbul:v2", "bulbul:v3"]`), and Bolna's own
  example posts it (VERIFIED-VENDOR-REPO, `bolna-ai/skills@28b24aa`,
  `create-agent/SKILL.md`: `"provider_config": {"model": "bulbul:v3", "voice": "Ashutosh",
  "voice_id": "ashutosh"}`). Sarvam's dashboard Model Catalogue lists ONLY `bulbul:v3` —
  no v2 row, no v4 — even though the SDK enum still carries `bulbul:v2`
  (VENDOR-PUBLISHED (Sarvam dashboard Model Catalogue, indus.sarvam.ai/model-catalogue,
  read by the founder 27 Aug 2026)). `TtsModel` carries no second Sarvam member on that
  basis; its second member is Cartesia's.
- **Telugu on the TTS leg** is the SDK's `types/text_to_speech_language.py`, which lists 11
  codes INCLUDING `te-IN`, `hi-IN` and `en-IN` (same wheel, same date). That enum is the
  citation, not the marketing count: the founder could not find a dashboard-rendered list
  naming `te-IN` against Bulbul v3 specifically, so the claim stays scoped to the enum.
  `languages` below carries the three the PRODUCT sells (`CreateOrgIn.language`), Telugu
  first, which is a subset of the enum rather than a re-statement of a count.

THE ID SPELLING, WHICH IS A DATA-SHAPE CONTRACT
------------------------------------------------
An id is `<tts_model>:<speaker>` — `bulbul:v3:ashutosh` — composed by `voice_id_for()`,
which is the ONE place the spelling exists. This is the shape this file predicted before
it could be built ("an id becomes `bulbul:v3:<speaker>` while `tts_model` stays
`bulbul:v3`"), and it is why `id`, `tts_model` and `speaker` are three fields: several
personas share one model, and the id has to stay unique across a future second model.

`agents.tts_voice` holds the ID. `ModelConfig.tts_model` / `ModelConfig.tts_voice` hold
the SPLIT — the model and the speaker, one per vendor slot — because the adapter must not
have to know how we spell an id (hard rule 2). `speech_for_voice_id()` is the splitter and
`voice_id_of()` is its inverse, used by `publish_agent` to record what it sent.

WHAT IS STILL PROVISIONAL (read this before quoting the catalog at anyone)
--------------------------------------------------------------------------
1. **`verified` is True on every entry now, and it means one narrow thing**: the ENGINE's
   own voice-config API listed this voice for a model we offer, on our own account. It is
   not an ear test and not a claim that anybody has heard it. Nothing here can be
   `verified=False` any more, because nothing here is typed by hand.
2. **Which speaker sounds best in Telugu is an EAR TEST, not a spec fact** (docs/BRD.md:242
   R-10, docs/TRD.md:478), and this module no longer has an opinion about it. There is no
   `DEFAULT_SPEAKER` and no `is_default`: the voices on offer are the ones an operator
   enabled, in the engine's own picker order, and which of them a screen pre-selects is a
   rendering choice rather than a platform constant. A placeholder default named in source
   was the last hardcoded persona in this tree.
3. **`gender` is `None` on every entry, on purpose.** The SDK carries NO gender metadata for
   speakers — the field is a bare name Literal — and a name is not evidence of a voice. The
   persona field stays because a future vendor enumeration may carry it; guessing "female"
   from "priya" would be exactly the laundering hard rule 11 forbids.

THE CARTESIA HALF: NO SHAPE HERE EITHER, AND THAT IS THE FIX (D-547 §0 Q1, D-588)
----------------------------------------------------------------------------------
Cartesia's voice library is behind a login (`play.cartesia.ai/voices`, egress-blocked
here), so no voice id can be typed into this file without inventing one — and an invented
id publishes an agent that 422s on a client's phone. This module used to ship the SHAPE of
a hand-loaded Cartesia list (`CartesiaVoiceRecord`, an empty `CARTESIA_CATALOG_SOURCE`,
`_cartesia_entry`, `cartesia_catalogue`) waiting for a research report to fill it in.

**That whole apparatus is deleted, because the engine already enumerates Cartesia.** Its
voice-config API answers for EVERY provider its account carries, keyed on a `model_id`
string (VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/api-reference/voice/
get_providers.md`, read 11 Sep 2026), so a Cartesia voice reaches the catalogue through the
same sync as a Sarvam one, with ids somebody READ. A second loader over Cartesia's own API
would be a second way to do one thing — the defect this repo treats as real even when both
halves work — and it was the one that could put an invented id on a phone line.

**`sonic-3` IS DELIBERATELY ABSENT, AND NOW FOR TWO REASONS RATHER THAN ONE.** Bolna
lists three Cartesia models and says which to run: *"use `sonic-3.5` for production
agents that need stable output"* (VERIFIED-VENDOR-DOCS,
`bolna-findings/mirror/pages/providers/voice/cartesia.md:57-67`). And the model vendor
has now DATED it: `sonic-3` (snapshot `sonic-3-2025-10-27`) is deprecated with a
**sunset of 20 Oct 2026**, shared with `sonic-2` and `sonic-turbo` — VENDOR-PUBLISHED
(`docs.cartesia.ai/build-with-cartesia/tts-models/api-changes`, read 7 Sep 2026 and
relayed in `docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md` ADDENDUM 1; the host is
egress-blocked from this container, so it was not read here). It was recorded as
REPORTED until that reading; it is not on Bolna's page, and `TTS_MODEL_LIFECYCLE`
carries it beside the row it explains.

**`sonic-preview` (Sonic 3.6) IS ABSENT ON A CONTRADICTION WE DO NOT GET TO RESOLVE.**
Bolna calls it *"Sonic 3.6 (Beta)"* whose *"output may change"* (`cartesia.md:58-66`);
Cartesia calls `sonic-3.6` stable with no announced retirement (same ADDENDUM 1
reading). **We send the id BOLNA accepts**, because Bolna is what parses it, so the
catalogue stays on `sonic-3.5` (snapshot `sonic-3.5-2026-05-04`, stable, no announced
retirement). The disagreement is recorded in `TTS_MODEL_LIFECYCLE`, not resolved, and
gate 52 is where it is revisited.

**TELUGU IS ON CARTESIA'S LIST; TELUGU-ENGLISH CODE-MIXING IS NOT VOUCHED FOR.** `te`
appears on the per-snapshot language list of `sonic-3.5-2026-05-04` (42 languages) and of
`sonic-3.6-2026-08-27` (44) — same reading. On MIXING, their multilingual guide says it in
their own words: *"Mixing languages inside a single generation works where it's common,
such as Hindi (Hinglish) and Tagalog (Taglish). Outside those cases the speech may sound
accented."* Telugu-English is not among the cases they name. **That is not "unsupported"
and it is not "supported"** — it is outside the two they vouch for, with an accent warning
attached by the vendor. No surface may promise Telugu-English mixing on this tier;
`_CARTESIA_NOTE` carries the caveat so it travels with every entry.

**A CARTESIA VOICE IS PUBLISHABLE — WHAT IS MISSING IS THE IDS, NOT THE WIRE SHAPE.** The
`provider_config` keys are absent from the pinned MIRROR (`api-reference/agent/v2/
create.md:640-644` enumerates only `[polly, elevenlabs, deepgram, styletts]`, already
narrower than what their own provider pages ship) — but they are declared in Bolna's OSS,
which was read: `CartesiaConfig(StandardVoiceConfig)` = `{voice, voice_id, model, language,
speed}` (VERIFIED-OSS, `bolna-ai/bolna`@`ae03977fa2a9ecec3171b45c6cac6d00236b957f`,
`bolna/models.py`; plan ADDENDUM 3 §3.1). `engine/bolna.py::_cartesia_synthesizer_config`
builds that block, works around three defects in that same repository, and refuses ONE
case by name: a Cartesia agent with no voice id — which is exactly what this empty
catalogue produces. ⚠ Whether the HOSTED platform runs that commit is UNKNOWN, so
OPERATIONS §2 gate 52 is narrowed rather than closed: it now asks whether the hosted
platform accepts these fields, not what the fields are.

WHETHER THIS CATALOGUE IS OFFERABLE AT ALL IS A SEPARATE QUESTION (D-93)
------------------------------------------------------------------------
Everything above assumes the engine lets us choose a voice. That is Bolna's answer, not
every engine's: an orchestrator whose TTS is its own product takes its voice id and its
own model, with no provider field to put `sarvam` in, and our `tts_voice` addresses
nothing on it. Against such an engine this catalogue is not a shortened list — it is a
list of voices the caller will never hear, and rendering it is a screen that lies.

So the catalogue is DATA, and `voice_selection_capability()` below is the one selector
that says whether it may be offered. It asks the engine's own `EngineCapabilities`
descriptor rather than a settings flag, for the reason `lead_retrieval_capability` gives:
a capability DERIVED from the thing that implements it cannot disagree with it, while two
independent reads of the same settings eventually do. The picker, the write endpoint and
the publish path all ask this one function.

`SpeechControl` is deliberately carried on the answer rather than reduced to a boolean.
"You may not choose a voice because this engine supplies its own" and "you may not choose
a voice because something is broken" have the same shape and opposite meanings, and only
the first is a sentence a client should be shown calmly.

Engine isolation (hard rule 2) note: these strings are engine-FACING config, but they
are not a vendor payload shape. This module reaches `apps.api.engine` only through the
factory and the capability selector — never an adapter — so the adapter still owns the
only knowledge of where the string is pasted into the vendor's JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, cast, get_args

from calevate_shared.engine import SpeechControl, VoiceEngine
from calevate_shared.model_lifecycle import TTS_MODEL_LIFECYCLE, TtsProvider
from pydantic import BaseModel, ConfigDict

from apps.api.billing.rates import voice_tier_label

# The languages the PRODUCT sells today (`CreateOrgIn.language`), Telugu first — we are
# Telugu-first (BRD §1), so the ordering here is the ordering a picker should render.
# A subset of the vendor's own 11-code TTS enum (VERIFIED-VENDOR-SDK: sarvamai==0.1.31
# (PyPI wheel), `types/text_to_speech_language.py`, read 27 Aug 2026), not a claim about
# the other eight.
Language = Literal["te-IN", "hi-IN", "en-IN"]

# The TTS models this product runs on — one per provider. Not an exhaustive list of what
# either vendor sells; kept as a Literal (rather than a bare str) so a catalogue entry cannot
# name a model we do not offer, and so `calevate_shared.model_lifecycle.TTS_MODEL_LIFECYCLE`
# can be checked against exactly this set (`scripts/check_model_lifecycle`).
#
# `sonic-3.5` and not `sonic-3`: the module docstring carries the vendor's line and the
# REPORTED sunset, in that order of standing.
TtsModel = Literal["bulbul:v3", "sonic-3.5"]

#: Who synthesises a voice — and, by plan §2.3 invariant 7, the agent's VOICE TIER. ONE
#: definition, shared with the lifecycle registry so the two cannot spell a provider
#: differently. `voice_tier()` returns it; nothing stores it beside the voice.
VoiceProvider = TtsProvider

#: The tier vocabulary a consumer (the pipeline's `meta.voice_tier`, the lot debit, the
#: runway) reads. The SAME type as the provider on purpose: the tier IS the provider, and a
#: second Literal would be the place the two could be made to disagree.
#:
#: **IT IS `meta.voice_tier` AND NOT `meta.tts_tier`, AND THIS COMMENT NAMED THE WRONG KEY.**
#: `usage_events.meta.tts_tier` is the PLAN'S OVERAGE RUNG (`BASE_OVERAGE_RUNG`, the
#: `plans.overage_rate` / `overage_rate_second` pair), which is a different fact about the
#: same call; the money lane stamps the two separately and says why in as many words
#: (`apps/workers/pipeline.py`, beside `"tts_tier"`). No code here read it wrongly — the
#: comment was the only thing that would have misled the next reader into folding them.
VoiceTier = VoiceProvider

Gender = Literal["female", "male", "neutral"]

#: WHAT A CURATED VOICE'S STATE IS, in the vocabulary the console writes and the offer
#: seam reads (D-588). It lives here rather than in `voice_offer.py` because it is a fact
#: ABOUT A VOICE — stored on `platform_voice_catalog`, checked by a DB constraint, rendered
#: in a table — while the VERDICT it feeds is the offer seam's.
#:
#: * `enabled`   — an operator has chosen to offer this voice. The ONLY offerable state.
#: * `disabled`  — synced and known, deliberately not offered. The state a voice ARRIVES in
#:                 (the column default), so a voice the vendor adds to their platform never
#:                 reaches a client without somebody deciding.
#: * `archived`  — retired by an operator: not offered, and filed away from the working
#:                 list. It is not a delete, because the row is also what stops a returning
#:                 voice re-arriving as a fresh un-curated one.
#:
#: **`archived` AND `disabled` DIFFER TO A HUMAN AND NOT TO THE OFFER SEAM.** Neither is
#: offerable; the distinction is which list an operator finds it in and which sentence they
#: read. Collapsing them to a boolean was the first shape and it lost the only thing the
#: founder asked for beyond on/off — a way to put a voice away without it cluttering the
#: screen every time the vendor's list is re-read.
CurationState = Literal["enabled", "disabled", "archived"]

#: The state a NEWLY SYNCED voice arrives in. Named once so the column default, the sync's
#: reasoning and the console's empty state cannot come to disagree about it.
#:
#: DISABLED, and this is the whole of the founder's requirement in one constant: *only the
#: voices they add there are selectable*. A voice defaulting to `enabled` would mean the
#: vendor adding a persona to their platform silently puts it in front of every client of
#: every tenant, with no operator in the loop — the failure direction that cannot be undone
#: by noticing it later, because by then somebody's agent is speaking it.
ARRIVAL_CURATION_STATE: Final[CurationState] = "disabled"

#: The state a voice an OPERATOR TYPED arrives in (D-590). ENABLED, and the asymmetry with
#: `ARRIVAL_CURATION_STATE` above is the whole point rather than an inconsistency.
#:
#: A SYNCED row arrives because the vendor listed it; nobody asked for it, so it arrives off.
#: An ADDED row arrives because a person filled in five fields about one cloned voice and the
#: platform confirmed every one of them — the act IS the decision to offer it, and making
#: them press Enable afterwards would be a second confirmation of the thing they just did.
ADDED_CURATION_STATE: Final[CurationState] = "enabled"

#: WHY A CATALOGUE ROW EXISTS (D-590). `synced` — a sync read it off the voice platform's
#: list; `operator` — somebody typed its facts and they were verified against that list.
#:
#: The two are IDENTICAL everywhere else on purpose: one row shape, one `Voice`, one picker,
#: one publish path, so nothing downstream branches on provenance. What it buys is the two
#: things provenance is actually needed for — a console that opens with the voices an
#: operator added rather than with the vendor's whole catalogue, and a sync that cannot
#: reclassify a typed row as a cache line it may overwrite.
VoiceOrigin = Literal["synced", "operator"]

#: The provenance a row gets when nothing says otherwise — the column default, and what the
#: sync produces. Named so the migration, the model and the sync cannot disagree.
DEFAULT_VOICE_ORIGIN: Final[VoiceOrigin] = "synced"


#: The model every SARVAM persona runs on, and the default voice's model. Named so
#: `voice_id_for` and the migration's backfill cannot disagree about which model the
#: default id carries. The default is Sarvam by decision (plan §0 Q9): Cartesia is chosen,
#: never inherited, because a default that costs the client more per minute must be a
#: choice they made.
DEFAULT_TTS_MODEL: Final[TtsModel] = "bulbul:v3"

#: The one Cartesia model this product offers — see `TtsModel` for why not `sonic-3`.
CARTESIA_TTS_MODEL: Final[TtsModel] = "sonic-3.5"


#: The id the migration backfills a bare `bulbul:v3` row to, and the one the picker
def voice_id_for(tts_model: str, speaker: str) -> str:
    """THE id spelling, in one place: `<tts_model>:<speaker>`.

    Every catalogue id, the migration's backfill target and `publish_agent`'s mirror write
    all come through here or through `voice_id_of` below. A second `f"{model}:{speaker}"`
    anywhere is a second definition of a value stored on agent rows — i.e. a data
    migration waiting to be caused by a typo.
    """
    return f"{tts_model}:{speaker}"


def voice_id_of(tts_model: str | None, speaker: str | None) -> str | None:
    """`voice_id_for`'s inverse-facing partner: the catalogue id a published `ModelConfig`
    TTS pair names, or None when it names no voice at all.

    `publish_agent` records what it SENT in `agents.live_tts_voice`, and what it sent is
    the split pair — while the column, `agents.tts_voice` and `publishing.py`'s divergence
    check are all written in catalogue IDs. Recomposing here rather than re-reading the row
    keeps `publish_agent`'s own rule (record the config you just handed the engine, never a
    re-read that a concurrent `set_agent_voice` could have moved underneath you).

    A speaker with no model — the unrecognised free-text id `speech_for_voice_id` passes
    through — recomposes to itself, so a legacy row still round-trips to the value it holds
    instead of gaining a prefix nothing wrote.
    """
    if speaker is None:
        return None
    if tts_model is None:
        return speaker
    return voice_id_for(tts_model, speaker)


def speech_for_voice_id(voice_id: str | None) -> tuple[str | None, str | None]:
    """`(tts_model, speaker)` for a stored voice id — THE splitter, and the only one.

    CATALOGUE LOOKUP, NEVER STRING SURGERY, and the difference is a live defect rather
    than a preference. Splitting on the last colon turns the legacy value `bulbul:v3` into
    model `bulbul` and speaker `v3` — two strings the vendor has never heard of, sent
    confidently. The catalogue knows which ids it composed; anything else is not ours to
    take apart.

    An id we do not recognise returns `(None, voice_id)`: it travels in the speaker slot
    exactly as it did before this split existed. That is deliberate and is the same
    argument `_agent_voice` makes in `publishing.py` — `agents.tts_voice` is free text, and
    a value we no longer offer must read back as itself rather than be dropped or guessed
    at. Migration `f1c9d4a72b06` backfills the rows this repository actually wrote.
    """
    if not voice_id:
        return (None, None)
    voice = _snapshot.by_id.get(voice_id)
    if voice is None:
        return (None, voice_id)
    return (voice.tts_model, voice.speaker)


class Voice(BaseModel):
    """One selectable voice. Doubles as the API response model — the catalog IS the
    contract, so there is nothing to keep in sync."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Written VERBATIM into `agents.tts_voice`. Stable: it is stored on agent rows, so
    # renaming one is a data migration, not an edit to this file. `<tts_model>:<speaker>`,
    # composed by `voice_id_for` — see the module docstring for why the pair is spelled
    # into one string here and split back apart in `ModelConfig`.
    id: str
    # What a human picks from. A persona label (speaker), NOT a tier — the tier is
    # `provider`, and price is a question the credit lot answers, not this field.
    #
    # ⚠ IT IS ALSO A WIRE VALUE, NOT ONLY A HUMAN ONE, AND THAT CHANGED ON 11 SEP 2026.
    # Bolna's synthesizer block REQUIRES a `voice` key beside `voice_id` (their validator:
    # "Voice > Voice: This field is required"), and `voice` is the platform's own NAME for
    # the voice. The adapter used to derive it as `speaker.capitalize()`, which is correct
    # for every Sarvam persona and structurally impossible for a CLONED voice — their own
    # example pairs `voice_id: "sXlZ9Juk5Ji8sZiFjRUV"` with `name: "my-custom-voice"`
    # (VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/api-reference/voice/
    # get_all.md:102-112`). So this field now TRAVELS: `in_call_speech` puts it on
    # `ModelConfig.tts_voice_label` and the adapter decides which key it lands in (hard
    # rule 2 intact — the KEY is still a vendor payload fact; the NAME never was).
    label: str
    #: Who synthesises it — and therefore the agent's voice tier (`voice_tier()`).
    provider: VoiceProvider
    # Which model serves this voice. Separate from `id` so that named speakers
    # do not each become their own model.
    tts_model: TtsModel
    # THE SPEAKER, which is the half that was missing and the whole of D-358's second
    # defect: the model string used to be sent in the vendor's speaker slot.
    #
    # A BARE `str`, and it is the honest type. The two providers name a voice
    # differently — a Sarvam speaker is a persona name, a Cartesia voice is a generated id,
    # a CLONE is whatever the founder called it — and none of the three is a set this
    # repository is entitled to enumerate. It was a `Literal` of the model vendor's 44
    # names until D-588; that Literal was the defect, not the guarantee.
    speaker: str
    # Telugu first. The three languages the product offers, a subset of the vendor's own
    # 11-code TTS enum — not a claim about the other eight.
    languages: tuple[Language, ...]
    # ALWAYS None, and it is a decision rather than a gap. The SDK's speaker type is a bare
    # name Literal carrying NO gender metadata, so there is nothing to state and a name is
    # not evidence. The field stays for the day a vendor enumeration carries one.
    gender: Gender | None = None
    # TRUE ON EVERY ENTRY NOW, AND IT MEANS ONE NARROW THING: the ENGINE's own
    # voice-config API listed this voice, on our own account, for a model we offer. It is
    # not an ear test. The field survives the seed's deletion because it is the only place
    # that distinction is stated on the wire, and because an entry that is ever built from
    # anything other than a live listing must be able to say so.
    verified: bool = False
    # One line an operator can read in a dropdown, with the cost consequence in it.
    note: str


#: The shared half of every Sarvam entry's `note`. One sentence, composed once: 44
#: hand-written notes would be 44 chances to drift. It carries NO price — it used to say
#: "₹30 per 10k characters", which was a rate card in a dropdown string (see the module
#: docstring); the tier is the cost fact, and it is the `provider` field.
#:
#: **THE TIER IS NAMED BY `billing/rates.voice_tier_label`, NOT SPELLED HERE.** This string
#: reaches a CLIENT — it rides `OfferedVoiceOut.note` on `GET /v1/agents/voices`, which is
#: `agents:read` in either realm — and it used to read "the Sarvam voice tier", which names
#: the vendor as the product tier the founder's 7 Sep 2026 decision says a client never
#: reads. Composed from the one definition rather than corrected in place, because a typed
#: name here would be the second copy that drifts the day the labels change.
#: ⚠ **THIS SENTENCE WAS STALE ON BOTH OF ITS FACTS AND A CLIENT WAS READING IT.** It said
#: "the speaker list is Sarvam's own; Bolna's acceptance of it is confirmed by
#: GET /me/voices", which described the compiled catalogue that D-585 deleted: the list is
#: now the ENGINE ACCOUNT's, either synced from it or typed by an operator and verified
#: against it at that moment (D-590) — and `GET /me/voices` is not an endpoint the vendor
#: has. It also carried the pilot-gate-3 ear test into a CLIENT-facing dropdown, which is
#: our internal verification schedule and not something a clinic can act on.
#:
#: What is left is what a client can use: which vendor synthesises it, which tier it is,
#: and the three languages. The tier name comes through `voice_tier_label` rather than
#: being spelled here, so it cannot drift from the rate card.
_NOTE: Final = (
    f"Sarvam Bulbul v3 — the {voice_tier_label('sarvam')} voice tier. Speaks Telugu, Hindi "
    "and Indian English."
)

#: The shared half of every Cartesia entry's `note`, for the same reason and through the
#: same label. The Telugu sentence is not decoration: Cartesia documents Hinglish
#: code-switching and says NOTHING about Telugu-English, so a screen that let a client infer
#: it from "Telugu is supported" would be promising something no page states (module
#: docstring, hard rule 11).
#:
#: IT NO LONGER RESTATES THE THREE OFFERABILITY GROUNDS ("offered only once the Cartesia key
#: is installed, its price attested and the cap not reached"). That sentence named two of our
#: own settings to a client, and it was a SECOND, un-forked copy of an answer
#: `agents/voice_offer.unofferable_reason` already gives per voice, per audience and per
#: deployment — a catalogue note cannot know whether the key is installed, so its version was
#: also the one that could be wrong.
_CARTESIA_NOTE: Final = (
    f"Cartesia Sonic 3.5 — the {voice_tier_label('cartesia')} voice tier, billed at the "
    "higher per-minute rate on every credit lot. Telugu is on Cartesia's language list for "
    "this model. Mixing Telugu and English inside one sentence is NOT one of the cases "
    'Cartesia vouches for (they name Hinglish and Taglish, and say speech outside those "may '
    'sound accented"), so do not promise it.'
)


def catalogue_note(provider: VoiceProvider) -> str:
    """THE one line an operator or client reads beside a voice, per provider.

    Public because `agents/voice_sync.py` builds every catalogue entry from the ENGINE's
    rows and needs one sentence per provider — a second string composed there would be the
    copy that drifts the day the tier labels change, which is the whole reason `_NOTE` is
    composed from `voice_tier_label` rather than typed.
    """
    return _NOTE if provider == "sarvam" else _CARTESIA_NOTE


#: Where the voices currently in force came from. `"engine"` means a sync read them off the
#: engine account; `"unsynced"` means no sync has ever succeeded on this process, so there
#: are NO voices and nobody can be offered one. Carried on the API response so an operator
#: or a client reading an empty picker is told which of those two they are looking at,
#: instead of guessing at a bug.
#:
#: ⚠ **THE THIRD VALUE, `"seed"`, IS GONE (D-588)** — there is no compiled fallback any
#: more. A surface that still branches on it is reading a state this process cannot be in.
CatalogueSource = Literal["unsynced", "engine"]


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """The voices in force, their id index and where they came from — as ONE value.

    One object rather than three module globals for `VoiceSelectionCapability`'s reason: a
    reader that took the list from one place and the index from another could observe a
    half-applied refresh. Installing a snapshot is a single rebind, so every reader sees
    either the whole old catalogue or the whole new one.
    """

    voices: tuple[Voice, ...]
    by_id: dict[str, Voice]
    source: CatalogueSource


def _snapshot_of(voices: tuple[Voice, ...], source: CatalogueSource) -> _Snapshot:
    return _Snapshot(voices=voices, by_id={voice.id: voice for voice in voices}, source=source)


#: NO VOICES, BECAUSE NOBODY HAS SYNCED. The state a process boots in and the state it
#: returns to when the cache is empty — not an error, and not a shorter list.
_UNSYNCED_SNAPSHOT: Final = _snapshot_of((), "unsynced")

#: THE CATALOGUE IN FORCE. Rebound by `install_voice_catalogue`; never mutated in place.
_snapshot: _Snapshot = _UNSYNCED_SNAPSHOT


def install_voice_catalogue(voices: tuple[Voice, ...] | None) -> None:
    """Install the synced catalogue for this process. `None` or `()` means "none in force".

    THE SAME SHAPE AS EVERY OTHER PLATFORM-SCOPED FACT THIS TREE SERVES OFF A SNAPSHOT —
    `voice_offer.install_tts_price_reader`, `billing/rates.install_llm_price_attestations`,
    `ops/pricing_snapshot.install_pricing_readers`. It is deliberately NOT an async read
    per request: `get_voice`, `speech_for_voice_id` and `voice_tier` are called from the
    publish path, the splitter and the money lane, all of which are synchronous by design
    and some of which hold no session. Turning them async to fetch platform-scoped rows
    that change when an operator presses a button would be a database round trip on every
    agent publish for a value that moves monthly.

    `agents/voice_sync.load_voice_catalogue` is the one caller in production (at API and
    worker startup, and after every sync); tests drive it directly and reset with `None`.

    ⚠ **AN EMPTY TUPLE USED TO RAISE, AND NOW INSTALLS.** The refusal existed to protect a
    SEED — "a picker with no voices is indistinguishable from a platform with no voices" was
    true only while a compiled fallback meant the second could not happen. D-588 deleted the
    seed, so "no voices in force" became a real, correct and reachable state: a deployment
    where nobody has synced. Refusing it would leave a process serving whatever it happened
    to load last, forever, with no way to observe that the cache behind it is empty.

    **What the refusal actually protected has NOT moved and has NOT weakened.** A SYNC that
    reads nothing is still refused at the place that can tell the difference —
    `voice_sync.sync_voice_catalogue` alerts (`voice_catalogue_empty`) and writes nothing, so
    a revoked credential or a moved route leaves the TABLE standing and this function is
    never called with `()` on that path. Only an honestly empty table reaches here.
    """
    global _snapshot
    if not voices:
        _snapshot = _UNSYNCED_SNAPSHOT
        return
    _snapshot = _snapshot_of(voices, "engine")


def catalogue() -> tuple[Voice, ...]:
    """THE voices in force — synced from the engine, or EMPTY until one lands.

    Every reader goes through here rather than through a module constant, because the
    catalogue is now DATA THAT MOVES: an operator clones a voice on the voice platform,
    refreshes, enables it, and the picker has to show it without a deploy.

    ⚠ **THIS IS THE LOOKUP LAYER, NOT THE OFFER LAYER.** It answers with every voice the
    engine account lists, INCLUDING ones an operator has disabled or archived, because its
    callers are `get_voice`, `speech_for_voice_id` and the publish path — which must keep
    resolving the id a live agent is already speaking however the console has been clicked
    since. Who may be offered what is `agents/voice_offer.offered_catalogue`.
    """
    return _snapshot.voices


def catalogue_source() -> CatalogueSource:
    """`"unsynced"` or `"engine"` — see `CatalogueSource` for why a caller must be able to
    tell an empty picker on a fresh deployment from a broken one."""
    return _snapshot.source


def get_voice(voice_id: str) -> Voice | None:
    """The catalog entry for `voice_id`, or None if we do not offer it.

    Exact match, no normalisation: `agents.tts_voice` is pasted into a vendor request
    verbatim, so accepting `Bulbul:V3` here would store a string that differs from the
    one we tested, which is the entire failure this module exists to prevent.
    """
    return _snapshot.by_id.get(voice_id)


def is_supported_voice(voice_id: str) -> bool:
    """Is this a voice we support? — the question the API must be able to answer
    BEFORE a string reaches an agent row and, from there, the engine."""
    return voice_id in _snapshot.by_id


def voice_ids() -> tuple[str, ...]:
    """Every id we accept, in catalog order — for error remediation text and tests."""
    return tuple(_snapshot.by_id)


def provider_of_tts_model(tts_model: str) -> VoiceProvider | None:
    """Which vendor synthesises this model — from the ONE registry that knows, or None.

    `calevate_shared.model_lifecycle.TTS_MODEL_LIFECYCLE` maps a model string to its
    provider and is already the table `scripts/check_model_lifecycle` holds `TtsModel` to,
    so there is exactly one place a model's provider is written down. A second mapping here
    (a dict beside `TtsModel`, a `startswith("sonic")`) would be the place the two could
    come to disagree about which tier a minute bills at.
    """
    row = TTS_MODEL_LIFECYCLE.get(tts_model)
    return row.provider if row is not None else None


def tts_models_for_provider(provider: str) -> tuple[TtsModel, ...]:
    """Every model WE OFFER on this provider, in `TtsModel` order — the inverse of
    `provider_of_tts_model`, and derived from the same one registry.

    The add form (D-590) asks an operator for a provider AND a model and then cross-checks
    the pair, so it needs to be able to say "this provider runs `sonic-3.5` here" without a
    second mapping beside `TTS_MODEL_LIFECYCLE`. Today each provider has exactly one model,
    which is a fact about our catalogue and not a fact this function is allowed to assume:
    it answers with a tuple so a second Sarvam model reaches the form by existing.

    Returns `()` for a provider this product does not have — which is a real answer and is
    what `voice_admission.py` turns into the ElevenLabs refusal.
    """
    return tuple(model for model in get_args(TtsModel) if provider_of_tts_model(model) == provider)


def tts_model_of_voice_id(voice_id: str | None) -> TtsModel | None:
    """The MODEL half of a stored voice id, read from the id ITSELF — no catalogue.

    `voice_id_for` composes `<tts_model>:<speaker>`, and every model we offer is a member
    of `TtsModel`, so the model is recoverable from the string by asking which member it is
    prefixed with. Deliberately NOT `rsplit(":", 1)`: `bulbul:v3:ashutosh` would split to
    the model `bulbul:v3` correctly and the legacy free-text row `bulbul:v3` would split to
    the model `bulbul`, which is a string no vendor has ever heard of. Matching against
    `get_args(TtsModel)` can only ever answer with a model we actually offer.

    None for a free-text id that names none of our models — which is a real answer and the
    caller must treat it as one (see `voice_tier`).
    """
    if not voice_id:
        return None
    for model in get_args(TtsModel):
        if voice_id == model or voice_id.startswith(f"{model}:"):
            # `get_args` is untyped to mypy; the comparison is what narrows it, and the
            # members it iterates ARE `TtsModel` by construction.
            return cast("TtsModel", model)
    return None


def voice_tier(tts_voice: str | None) -> VoiceTier:
    """THE agent's voice tier: the provider of the voice on its row, and nothing else.

    Plan §2.3 invariant 7 and §3.3: the tier is DERIVED, never stored, so an agent cannot
    hold a Cartesia voice and a Sarvam tier. This is the one function that derives it —
    the pipeline's `meta.voice_tier`, the credit-lot debit and the runway all ask here.
    NOT `meta.tts_tier`, which this line used to name: that key carries the plan's OVERAGE
    RUNG and is stamped separately on purpose (see `VoiceTier` above).

    ⚠ **IT IS DERIVED FROM THE ID, NOT FROM CATALOGUE MEMBERSHIP, AND THAT CHANGED ON
    11 SEP 2026 (D-585) — THE CHANGE REACHES MONEY.** This used to look the id up in
    `CATALOG` and return `"sarvam"` when it was absent. That was safe only while the
    catalogue was a frozen compiled constant: every id that could exist was in it. The
    catalogue is now CACHED FROM THE ENGINE (`agents/voice_sync.py`), so "absent" became a
    state a live Cartesia agent can be in — a cache not yet synced, a sync that pruned a
    voice the vendor withdrew, a clone renamed. In every one of those, a Cartesia agent
    would have billed at the SARVAM rate, silently, on an append-only ledger (hard rule 7).

    So the tier comes from the id's own model prefix and the one model→provider registry.
    `bulbul:v3:…` is Sarvam and `sonic-3.5:…` is Cartesia whether or not a row for that
    voice exists anywhere, which is the property the money lane needs.

    `sarvam` for an empty id or one naming none of our models, and that is a decision
    rather than a fallback: an agent with no voice speaks the engine's default Sarvam
    persona, and a legacy free-text row (`bulbul:v3`, the pre-split spelling) is a Sarvam
    row. Cartesia is chosen, never inherited (Q9) — the only way onto the dearer tier is an
    id that names the Cartesia model.
    """
    model = tts_model_of_voice_id(tts_voice)
    provider = provider_of_tts_model(model) if model is not None else None
    return provider if provider is not None else "sarvam"


# --- the capability seam (D-93) -------------------------------------------------
#
# Authored reason codes, never vendor prose: they name OUR state and are stable enough to
# be alert labels and UI branches.

#: The engine supplies its own voices, so ours are not a choice set on it. This is a
#: PRODUCT FACT, not a fault — nothing is broken and nothing needs fixing.
ENGINE_DICTATES_TTS_REASON: Final = "engine_dictates_tts"


@dataclass(frozen=True, slots=True)
class VoiceSelectionCapability:
    """Whether a voice may be chosen here, and what may be chosen, as ONE answer.

    `voices` is carried on the same object rather than fetched separately — the argument
    `PaymentCapability.creates_orders` and `RetrievalCapability.retriever` both make: two
    facts, one lookup, one object. A caller that read "selection is available" from here
    and the list from `catalogue()` could render a picker on an engine that dictates its
    voices, which is the precise failure this seam exists to prevent.

    `reason` is non-None exactly when `available` is False.
    """

    available: bool
    #: Who chooses the TTS leg on the engine actually selected. Carried so a surface can
    #: say WHY calmly ("this platform supplies its own voices") instead of rendering an
    #: error, and so the two unavailable-for-different-reasons cases stay distinguishable.
    control: SpeechControl
    reason: str | None = None
    voices: tuple[Voice, ...] = ()


def voice_selection_capability(engine: VoiceEngine | None = None) -> VoiceSelectionCapability:
    """THE selector. The catalogue endpoint, the write endpoint and the publish path all
    ask this; nothing decides for itself whether a voice is choosable.

    Derived from the engine's own descriptor rather than asserted by config, so "we offer
    a voice picker" and "the engine will accept a voice" cannot disagree. When they did,
    the disagreement was invisible: the picker saved a row, the publish sent it, the
    engine ignored it, and the only place the truth appeared was a caller's handset.
    """
    # Imported here rather than at module scope: this module is imported by
    # `agents/publishing.py` and the route layer, and pulling the engine factory (and
    # through it httpx) in at import time would put a vendor client on the import path of
    # every agents module. The seam depends on nothing; the callers depend on the seam.
    from apps.api.engine import engine_capabilities

    control = engine_capabilities(engine).speech_control("tts")
    if control != "ours":
        return VoiceSelectionCapability(
            available=False, control=control, reason=ENGINE_DICTATES_TTS_REASON
        )
    return VoiceSelectionCapability(available=True, control=control, voices=catalogue())


__all__ = [
    "ADDED_CURATION_STATE",
    "ARRIVAL_CURATION_STATE",
    "CARTESIA_TTS_MODEL",
    "DEFAULT_TTS_MODEL",
    "DEFAULT_VOICE_ORIGIN",
    "ENGINE_DICTATES_TTS_REASON",
    "CatalogueSource",
    "CurationState",
    "Gender",
    "Language",
    "TtsModel",
    "Voice",
    "VoiceOrigin",
    "VoiceProvider",
    "VoiceSelectionCapability",
    "VoiceTier",
    "catalogue",
    "catalogue_note",
    "catalogue_source",
    "get_voice",
    "install_voice_catalogue",
    "is_supported_voice",
    "provider_of_tts_model",
    "speech_for_voice_id",
    "tts_model_of_voice_id",
    "tts_models_for_provider",
    "voice_id_for",
    "voice_id_of",
    "voice_ids",
    "voice_selection_capability",
    "voice_tier",
]
