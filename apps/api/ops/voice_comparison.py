"""A blind listening comparison of our Cartesia and Sarvam own-key voices (D-946).

Admin only, and no client is touched: no agent, rung, price or client workspace changes. The
founder hears the same Telugu sentences on up to three voices of each provider, rates each
side of a pair without knowing which provider spoke it, and only then sees which was which.

WHERE EACH PROVIDER SPEAKS. ThinnestAI holds ONE voice key per workspace ("A workspace holds
its keys once", `PUT /byok/credentials` is "Add or replace a key";
`thinnest-findings/mirror/snapshots/2026-10-29/pages/api-reference/bring-your-own-keys.md:
83,229-244`), and an agent on that key "speaks with the new provider's standard voice" once the
key moves to another provider (:373-375). Our developer workspace holds the Cartesia key that
free-trial Studio agents speak on (D-727), so installing Sarvam there would move every one of
them off Cartesia. The Sarvam key therefore goes into a workspace of its own: a ThinnestAI
customer workspace we create for this and nothing else (`VOICE_LAB_REF`), with no agents in it,
switched on for the voice only (`PATCH /byok {scope: voice}`, :266-279) because a preview is
refused with 409 in a workspace not on its own keys. Cartesia voices are spoken where Studio
voices are already previewed (`hosted_voices.studio_listing_workspace`).

BLINDING. A trial names its two voices by index into the round's `voices`; the round view the
page renders before the round is finished carries the sentence, the scores and the trial id,
never a voice, a label or a provider. The audio is fetched by trial id and side. What it does
not hide: Sarvam previews come back as WAV and Cartesia ones as MP3 (bring-your-own-keys.md:
321), so a listener reading the response headers in developer tools could tell them apart.

COST. Each provider charges our own account per character spoken ("your provider charges you
for every character", :323); ThinnestAI's own charge for a preview, if any, is UNKNOWN (the page
is silent). Clips are cached by provider, voice, language and text, and each round counts the
characters it sent each provider. No rupee figure is computed: Cartesia is a plan with an
allotment, and no Sarvam voice price is attested here.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.spoken_style import placed_call_opening, style_for
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.hosted_voices import (
    STUDIO_VOICE_PROVIDER,
    list_hosted_voices,
    studio_listing_workspace,
)
from apps.api.billing.plans import IST
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.core.spreadsheet_safety import disarm_for_csv
from apps.api.engine.catalogue import HostedVoice, HostsVoices, OwnVoiceKeyState
from apps.api.engine.thinnest_customers import thinnest_customers
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.ops.models import PlatformVoiceComparisonRound, PlatformVoiceComparisonTrial

log = get_logger(__name__)

Provider = Literal["cartesia", "sarvam"]
Side = Literal["a", "b"]
Preference = Literal["a", "b", "none"]

#: ThinnestAI's provider id for Sarvam's voices (bring-your-own-keys.md:156, ids "in lower
#: case", :240).
SARVAM_PROVIDER: Final = "sarvam"
CARTESIA_PROVIDER: Final = STUDIO_VOICE_PROVIDER
#: The credential the comparison workspace speaks Sarvam on.
SARVAM_VOICE_SECRET: Final = "sarvam_voice_api_key"
#: Our reference for the comparison workspace (`externalId`, 1-128 of letters, digits, `.`,
#: `_`, `:`, `-`). A client's is `calevate-<uuid>` (`tenancy/engine_workspace.external_ref_for`),
#: so this can never be taken for one.
VOICE_LAB_REF: Final = "calevate-voice-lab"
VOICE_LAB_NAME: Final = "Calevate voice comparison (admin only, no agents)"
_LAB_TIMEZONE: Final = "Asia/Kolkata"

DEFAULT_LANGUAGE: Final = "te-IN"
MAX_VOICES_PER_PROVIDER: Final = 3
MAX_SENTENCES: Final = 20
#: The vendor's preview cap (bring-your-own-keys.md:322-323).
MAX_SENTENCE_CHARS: Final = 200
#: Pairs in one round: every Cartesia voice against every Sarvam voice on every sentence.
MAX_TRIALS: Final = 120
MAX_ROUNDS_LISTED: Final = 50
#: Stored under the voice-preview prefix, so the store's existing read and lifecycle apply.
_CLIP_NAMESPACE: Final = "voice-comparison"
_PROVIDERS: Final[tuple[Provider, ...]] = ("cartesia", "sarvam")
_RANDOM: Final = secrets.SystemRandom()


# --- the comparison workspace ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LabState:
    key_stored: bool
    #: The comparison workspace's id, or None before it is set up.
    workspace: str | None
    #: The workspace speaks on our Sarvam key, voice only.
    ready: bool
    #: The voice provider whose key it holds, as the platform reports it.
    voice_provider: str | None
    #: Where Cartesia voices are previewed answers ready on our key.
    cartesia_ready: bool


def sarvam_key() -> str | None:
    return (get_settings().sarvam_voice_api_key or "").strip() or None


def lab_ready(state: OwnVoiceKeyState) -> bool:
    return state.speaks_on_own_voice and state.voice_provider == SARVAM_PROVIDER


def _never_the_developer_workspace() -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code="voice_comparison_workspace_is_ours",
        title="The comparison workspace resolved to our main workspace",
        detail="Sarvam is never installed in the workspace free-trial agents speak in.",
        remediation="Check the customer with the reference calevate-voice-lab on ThinnestAI.",
    )


async def find_voice_lab() -> str | None:
    """The comparison workspace's id, or None before it exists. Our own id is read first so
    a lookup that somehow named it is refused rather than written to."""
    customers = thinnest_customers()
    developer = await customers.developer_workspace_id()
    found = await customers.find(VOICE_LAB_REF)
    if found is None:
        return None
    if found.workspace_id == developer:
        raise _never_the_developer_workspace()
    return found.workspace_id


async def _find_or_create_lab() -> str:
    workspace = await find_voice_lab()
    if workspace is not None:
        return workspace
    customers = thinnest_customers()
    try:
        created = await customers.create(
            name=VOICE_LAB_NAME, external_id=VOICE_LAB_REF, timezone=_LAB_TIMEZONE
        )
    except EngineRejectedError as exc:
        if exc.vendor_status == 402:
            raise ProblemError(
                kind="business_rule",
                code="voice_comparison_workspace_cap",
                title="The voice platform has no room for another workspace",
                detail="Our plan's customer workspace limit is reached, so the comparison "
                "workspace could not be made.",
                remediation="Ask ThinnestAI to raise the customer workspace limit.",
            ) from exc
        if exc.vendor_status != 409:
            raise
        # Our reference is taken: a create that raced this one. Read it.
        workspace = await find_voice_lab()
        if workspace is None:
            raise
        return workspace
    return created.workspace_id


async def lab_state(engine: HostsVoices) -> LabState:
    workspace = await find_voice_lab()
    provider: str | None = None
    ready = False
    if workspace is not None:
        with in_workspace(workspace):
            state = await engine.own_key_state()
        provider, ready = state.voice_provider, lab_ready(state)
    return LabState(
        key_stored=sarvam_key() is not None,
        workspace=workspace,
        ready=ready,
        voice_provider=provider,
        cartesia_ready=await studio_listing_workspace(engine) is not None,
    )


def _no_sarvam_key() -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code="voice_comparison_no_sarvam_key",
        title="No Sarvam voice key is stored",
        detail="The comparison speaks Sarvam voices on our own Sarvam key.",
        remediation="Save the Sarvam Voice API Key in Settings, Credentials, then set up again.",
    )


async def install_sarvam_key(engine: HostsVoices, workspace: str, api_key: str) -> None:
    """The key into the comparison workspace, the voice switched on, and the answer read back.
    The platform asks Sarvam before it stores a key (`400` when refused, :246-250). No model
    is sent, so the key starts on Sarvam's usual voice model (:242)."""
    with in_workspace(workspace):
        await engine.install_own_voice_key(provider=SARVAM_PROVIDER, api_key=api_key, model=None)
        await engine.enable_own_voice_key()
        state = await engine.own_key_state()
    if not lab_ready(state):
        log.warning(
            "voice_comparison_lab_not_ready",
            extra={
                "enabled": state.enabled,
                "scope": state.scope,
                "using": state.using,
                "voice_provider": state.voice_provider,
            },
        )
        raise ProblemError(
            kind="business_rule",
            code="voice_comparison_lab_not_ready",
            title="The comparison workspace is not on our Sarvam key",
            detail="The key was sent, but the voice platform does not report the workspace "
            "speaking on it for the voice.",
            remediation="Set up again. If it repeats, check Settings, Your keys in that "
            "workspace on ThinnestAI.",
        )


async def set_up_voice_lab(engine: HostsVoices) -> LabState:
    """Make the comparison workspace if it does not exist, put our Sarvam key in it and switch
    it on for the voice. Idempotent; it never touches the developer workspace or a client's."""
    api_key = sarvam_key()
    if api_key is None:
        raise _no_sarvam_key()
    workspace = await _find_or_create_lab()
    await install_sarvam_key(engine, workspace, api_key)
    return await lab_state(engine)


async def _ready_lab(engine: HostsVoices) -> str:
    workspace = await find_voice_lab()
    if workspace is not None:
        with in_workspace(workspace):
            state = await engine.own_key_state()
        if lab_ready(state):
            return workspace
    raise ProblemError(
        kind="business_rule",
        code="voice_comparison_lab_not_set_up",
        title="Sarvam voices are not set up yet",
        detail="The comparison workspace does not speak on our Sarvam key yet.",
        remediation="Choose Set up Sarvam voices first.",
    )


async def _cartesia_workspace(engine: HostsVoices) -> str | None:
    found = await studio_listing_workspace(engine)
    if found is None:
        raise ProblemError(
            kind="business_rule",
            code="studio_preview_no_workspace",
            title="No workspace runs Studio yet",
            detail="Cartesia voices are spoken on our key in a workspace where it is "
            "switched on, and none answers as ready.",
            remediation="Run Studio ready under Voices, then try again.",
        )
    return found.workspace


# --- the two catalogues ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateVoice:
    provider: Provider
    vendor_id: str
    label: str
    language: str | None
    gender: str | None


def _candidate(provider: Provider, voice: HostedVoice) -> CandidateVoice:
    return CandidateVoice(
        provider=provider,
        vendor_id=voice.voice_id,
        label=voice.label,
        language=voice.language,
        gender=voice.gender,
    )


async def sarvam_voices(engine: HostsVoices) -> tuple[list[CandidateVoice], bool]:
    """Sarvam's voices as `GET /byok/voices` lists them in the comparison workspace
    (bring-your-own-keys.md:281-309), and whether the listing is whole."""
    workspace = await _ready_lab(engine)
    with in_workspace(workspace):
        listing = await engine.list_own_key_voices()
    if listing.provider != SARVAM_PROVIDER:
        raise ProblemError(
            kind="business_rule",
            code="voice_comparison_wrong_provider",
            title="The comparison workspace lists another provider's voices",
            detail="Its voice key is not Sarvam's, so its voices cannot be compared as Sarvam.",
            remediation="Choose Set up Sarvam voices again.",
        )
    return [_candidate("sarvam", v) for v in listing.voices], listing.complete


async def cartesia_voices(session: AsyncSession) -> list[CandidateVoice]:
    """The Studio (Cartesia) voices an operator added under Voices and the platform still
    lists: the ones Studio would actually sell."""
    rows = await list_hosted_voices(session, scope="added")
    return [
        CandidateVoice(
            provider="cartesia",
            vendor_id=row.vendor_id,
            label=row.vendor_label,
            language=row.accent,
            gender=row.gender,
        )
        for row in rows
        if row.source == "byok" and row.provider == CARTESIA_PROVIDER and row.withdrawn_at is None
    ]


# --- the default sentences ------------------------------------------------------------

#: A quoted phrase in a number rule: what an agent says, in the language's letters.
_QUOTED: Final = re.compile(r"\"([^\"]+)\"")


def default_sentences(language: str = DEFAULT_LANGUAGE) -> list[str]:
    """Lines from our spoken style for `language`, never written here: the two placed-call
    openings, the agent's side of the approved in-call examples, the quoted phrases of each
    number rule joined into one line (on Telugu: prices, big amounts, quantities, times,
    days and digits), and the spelled web address. Each is held to the preview cap."""
    style = style_for(language)
    if style is None:
        return []
    lines: list[str] = [
        placed_call_opening(language, business="Calevate"),
        placed_call_opening(language, business="Calevate", introduced=True),
    ]
    for exchange in style.prompt_examples:
        lines.extend(turn.text for turn in exchange if turn.speaker == "agent")
    for rule in style.number_rules:
        phrases = _QUOTED.findall(rule)
        if phrases:
            lines.append(", ".join(phrases))
    if style.spelled_address:
        lines.append(style.spelled_address)
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if line and line not in seen and len(line) <= MAX_SENTENCE_CHARS:
            seen.add(line)
            out.append(line)
    return out[:MAX_SENTENCES]


# --- rounds ---------------------------------------------------------------------------


def _invalid(code: str, title: str, detail: str) -> ProblemError:
    return ProblemError(kind="validation", code=code, title=title, detail=detail)


def clean_sentences(sentences: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in sentences:
        line = " ".join(raw.split())
        if not line:
            continue
        if len(line) > MAX_SENTENCE_CHARS:
            raise _invalid(
                "voice_comparison_sentence_too_long",
                "A sentence is too long",
                f"Each sentence may be at most {MAX_SENTENCE_CHARS} characters, the voice "
                "platform's limit for a preview.",
            )
        if line not in cleaned:
            cleaned.append(line)
    if not cleaned or len(cleaned) > MAX_SENTENCES:
        raise _invalid(
            "voice_comparison_sentences",
            "Choose between 1 and 20 sentences",
            f"A round reads 1 to {MAX_SENTENCES} different sentences.",
        )
    return cleaned


def _pick(
    wanted: list[str], available: list[CandidateVoice], provider: Provider
) -> list[CandidateVoice]:
    if not 1 <= len(wanted) <= MAX_VOICES_PER_PROVIDER or len(set(wanted)) != len(wanted):
        raise _invalid(
            "voice_comparison_voice_count",
            "Choose 1 to 3 voices of each provider",
            f"Pick between 1 and {MAX_VOICES_PER_PROVIDER} different {provider} voices.",
        )
    by_id = {voice.vendor_id: voice for voice in available}
    missing = [voice_id for voice_id in wanted if voice_id not in by_id]
    if missing:
        raise _invalid(
            "voice_comparison_unknown_voice",
            "A chosen voice is not listed",
            f"{len(missing)} chosen {provider} voice(s) are not in the provider's current list.",
        )
    return [by_id[voice_id] for voice_id in wanted]


def plan_trials(
    cartesia: int, sarvam: int, sentences: int, *, rng: Any = _RANDOM
) -> list[tuple[int, int, int]]:
    """`(sentence index, voice A, voice B)` for every Cartesia voice against every Sarvam voice
    on every sentence, which provider takes side A drawn for each pair, in a shuffled order.
    Cartesia voices are indexes `0..cartesia-1` and Sarvam voices follow them."""
    trials: list[tuple[int, int, int]] = []
    for sentence in range(sentences):
        for c in range(cartesia):
            for s in range(cartesia, cartesia + sarvam):
                a, b = (c, s) if rng.random() < 0.5 else (s, c)
                trials.append((sentence, a, b))
    rng.shuffle(trials)
    return trials


async def create_round(
    session: AsyncSession,
    engine: HostsVoices,
    *,
    title: str,
    language: str,
    cartesia_ids: list[str],
    sarvam_ids: list[str],
    sentences: list[str],
    actor_id: UUID,
) -> PlatformVoiceComparisonRound:
    lines = clean_sentences(sentences)
    pairs = len(cartesia_ids) * len(sarvam_ids) * len(lines)
    if pairs > MAX_TRIALS:
        raise _invalid(
            "voice_comparison_too_many_pairs",
            "This round would be too long to rate",
            f"It would be {pairs} pairs; a round is at most {MAX_TRIALS}. Choose fewer "
            "voices or sentences.",
        )
    cartesia = _pick(cartesia_ids, await cartesia_voices(session), "cartesia")
    sarvam = _pick(sarvam_ids, (await sarvam_voices(engine))[0], "sarvam")
    voices = [
        {"provider": v.provider, "vendor_id": v.vendor_id, "label": v.label}
        for v in (*cartesia, *sarvam)
    ]
    round_ = PlatformVoiceComparisonRound(
        title=" ".join(title.split()) or "Telugu voices",
        language=language,
        voices=voices,
        sentences=lines,
        created_by=actor_id,
    )
    session.add(round_)
    await session.flush()
    for position, (sentence, a, b) in enumerate(
        plan_trials(len(cartesia), len(sarvam), len(lines)), start=1
    ):
        session.add(
            PlatformVoiceComparisonTrial(
                round_id=round_.id,
                position=position,
                sentence_index=sentence,
                voice_a=a,
                voice_b=b,
            )
        )
    await session.flush()
    return round_


async def read_round(session: AsyncSession, round_id: UUID) -> PlatformVoiceComparisonRound:
    found = await session.get(PlatformVoiceComparisonRound, round_id)
    if found is None:
        raise ProblemError.not_found("Comparison round")
    return found


async def round_trials(session: AsyncSession, round_id: UUID) -> list[PlatformVoiceComparisonTrial]:
    return list(
        (
            await session.execute(
                select(PlatformVoiceComparisonTrial)
                .where(PlatformVoiceComparisonTrial.round_id == round_id)
                .order_by(PlatformVoiceComparisonTrial.position)
                .limit(MAX_TRIALS)
            )
        )
        .scalars()
        .all()
    )


async def list_rounds(
    session: AsyncSession, *, limit: int = MAX_ROUNDS_LISTED
) -> list[tuple[PlatformVoiceComparisonRound, int, int]]:
    """The latest rounds, each with its pairs and pairs rated."""
    trials = PlatformVoiceComparisonTrial
    rated = func.count(trials.rated_at)
    rows = (
        await session.execute(
            select(PlatformVoiceComparisonRound, func.count(trials.id), rated)
            .join(trials, trials.round_id == PlatformVoiceComparisonRound.id)
            .group_by(PlatformVoiceComparisonRound.id)
            .order_by(PlatformVoiceComparisonRound.created_at.desc())
            .limit(min(limit, MAX_ROUNDS_LISTED))
        )
    ).all()
    return [(row[0], int(row[1]), int(row[2])) for row in rows]


def _finished_already() -> ProblemError:
    return ProblemError.conflict(
        "voice_comparison_finished",
        "This round is finished, so its ratings are final.",
        remediation="Start a new round to listen again.",
    )


async def _trial(
    session: AsyncSession, trial_id: UUID
) -> tuple[PlatformVoiceComparisonTrial, PlatformVoiceComparisonRound]:
    trial = await session.get(PlatformVoiceComparisonTrial, trial_id)
    if trial is None:
        raise ProblemError.not_found("Comparison pair")
    return trial, await read_round(session, trial.round_id)


async def _lock_round(session: AsyncSession, round_id: UUID) -> PlatformVoiceComparisonRound:
    """The round row under FOR UPDATE, so a rating and a finish on the same round take turns:
    without it a rating read before the finish commits could land after the reveal."""
    found = (
        await session.execute(
            select(PlatformVoiceComparisonRound)
            .where(PlatformVoiceComparisonRound.id == round_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if found is None:
        raise ProblemError.not_found("Comparison round")
    return found


async def rate_trial(
    session: AsyncSession,
    trial_id: UUID,
    *,
    rating_a: int,
    rating_b: int,
    preference: Preference,
    actor_id: UUID,
) -> PlatformVoiceComparisonTrial:
    trial, round_ = await _trial(session, trial_id)
    round_ = await _lock_round(session, round_.id)
    if round_.finished_at is not None:
        raise _finished_already()
    trial.rating_a, trial.rating_b, trial.preference = rating_a, rating_b, preference
    trial.rated_by, trial.rated_at = actor_id, datetime.now(UTC)
    await session.flush()
    return trial


async def finish_round(session: AsyncSession, round_id: UUID) -> PlatformVoiceComparisonRound:
    """Close the round so its providers can be shown. Every pair must be rated first; a
    round already finished stays as it was."""
    round_ = await _lock_round(session, round_id)
    if round_.finished_at is not None:
        return round_
    left = sum(1 for t in await round_trials(session, round_id) if t.rated_at is None)
    if left:
        raise ProblemError.conflict(
            "voice_comparison_unrated",
            f"{left} pair(s) are not rated yet.",
            remediation="Rate every pair, then finish the round.",
        )
    # CAS on `finished_at`, so two finishes cannot both stamp it.
    await session.execute(
        update(PlatformVoiceComparisonRound)
        .where(
            PlatformVoiceComparisonRound.id == round_id,
            PlatformVoiceComparisonRound.finished_at.is_(None),
        )
        .values(finished_at=func.now())
    )
    await session.refresh(round_)
    return round_


def require_finished(round_: PlatformVoiceComparisonRound) -> datetime:
    """When the round was finished; refused while it is not, so nothing reveals early."""
    if round_.finished_at is None:
        raise ProblemError.conflict(
            "voice_comparison_not_finished",
            "Which provider spoke each voice is shown only once the round is finished.",
            remediation="Rate every pair and finish the round first.",
        )
    return round_.finished_at


# --- audio ----------------------------------------------------------------------------


def clip_identity(provider: str, vendor_id: str, language: str, text: str) -> str:
    """What a cached clip is: the same provider, voice, language and words always sound the
    same, so a second round re-uses the clip and the provider is not paid twice."""
    digest = hashlib.sha256(text.encode()).hexdigest()
    return f"{_CLIP_NAMESPACE}:{provider}:{vendor_id}:{language}:{digest}"


@dataclass(frozen=True, slots=True)
class Clip:
    data: bytes
    content_type: str


async def trial_audio(
    session: AsyncSession, engine: HostsVoices, trial_id: UUID, side: Side
) -> Clip:
    """One side of one pair, from the cache or spoken now and cached."""
    from apps.api.ops.hosted_voice_routes import sniff_preview_type
    from apps.workers.storage import read_voice_preview, store_voice_preview, voice_preview_key

    trial, round_ = await _trial(session, trial_id)
    voice = round_.voices[trial.voice_a if side == "a" else trial.voice_b]
    provider = str(voice["provider"])
    vendor_id = str(voice["vendor_id"])
    text = str(round_.sentences[trial.sentence_index])
    key = voice_preview_key(clip_identity(provider, vendor_id, round_.language, text))
    cached = await read_voice_preview(key)
    if cached is not None and (kind := sniff_preview_type(cached)) is not None:
        return Clip(data=cached, content_type=kind)
    workspace = (
        await _ready_lab(engine)
        if provider == SARVAM_PROVIDER
        else await _cartesia_workspace(engine)
    )
    with in_workspace(workspace):
        audio = await engine.preview_own_key_voice(
            voice_id=vendor_id, text=text, language=round_.language
        )
    kind = sniff_preview_type(audio.data)
    if kind is None:
        raise ProblemError(
            kind="business_rule",
            code="voice_comparison_audio_unplayable",
            title="The voice platform's audio cannot be played",
            detail="The clip it returned is not MP3 or WAV audio.",
            remediation="Try the pair again.",
        )
    await store_voice_preview(key=key, data=audio.data, content_type=kind)
    column = (
        PlatformVoiceComparisonRound.sarvam_chars
        if provider == SARVAM_PROVIDER
        else PlatformVoiceComparisonRound.cartesia_chars
    )
    # One statement, so two clips spoken at once both count.
    await session.execute(
        update(PlatformVoiceComparisonRound)
        .where(PlatformVoiceComparisonRound.id == round_.id)
        .values({column: column + len(text)})
    )
    log.info(
        "voice_comparison_clip_spoken",
        extra={"round_id": str(round_.id), "provider": provider, "chars": len(text)},
    )
    return Clip(data=audio.data, content_type=kind)


# --- the reveal -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VoiceResult:
    provider: Provider
    vendor_id: str
    label: str
    heard: int
    mean_naturalness: float | None
    preferred: int
    not_preferred: int
    no_preference: int


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider: Provider
    voices: int
    heard: int
    mean_naturalness: float | None
    preferred: int
    #: Share of all pairs where this provider's side was preferred, 0-1.
    preferred_share: float | None
    characters: int


@dataclass(frozen=True, slots=True)
class RoundSummary:
    pairs: int
    no_preference: int
    voices: list[VoiceResult]
    providers: list[ProviderResult]


def _mean(scores: list[int]) -> float | None:
    return round(sum(scores) / len(scores), 2) if scores else None


def summarise(
    round_: PlatformVoiceComparisonRound, trials: list[PlatformVoiceComparisonTrial]
) -> RoundSummary:
    voices = round_.voices
    scores: dict[int, list[int]] = defaultdict(list)
    tally: dict[int, dict[str, int]] = defaultdict(lambda: {"won": 0, "lost": 0, "tie": 0})
    ties = 0
    for t in trials:
        if t.rated_at is None or t.rating_a is None or t.rating_b is None:
            continue
        scores[t.voice_a].append(t.rating_a)
        scores[t.voice_b].append(t.rating_b)
        if t.preference == "none":
            ties += 1
            tally[t.voice_a]["tie"] += 1
            tally[t.voice_b]["tie"] += 1
        else:
            winner, loser = (
                (t.voice_a, t.voice_b) if t.preference == "a" else (t.voice_b, t.voice_a)
            )
            tally[winner]["won"] += 1
            tally[loser]["lost"] += 1
    per_voice = [
        VoiceResult(
            provider=voice["provider"],
            vendor_id=str(voice["vendor_id"]),
            label=str(voice["label"]),
            heard=len(scores[i]),
            mean_naturalness=_mean(scores[i]),
            preferred=tally[i]["won"],
            not_preferred=tally[i]["lost"],
            no_preference=tally[i]["tie"],
        )
        for i, voice in enumerate(voices)
    ]
    rated = sum(1 for t in trials if t.rated_at is not None)
    chars = {"cartesia": round_.cartesia_chars, "sarvam": round_.sarvam_chars}
    providers: list[ProviderResult] = []
    for provider in _PROVIDERS:
        mine = [i for i, voice in enumerate(voices) if voice["provider"] == provider]
        won = sum(tally[i]["won"] for i in mine)
        providers.append(
            ProviderResult(
                provider=provider,
                voices=len(mine),
                heard=sum(len(scores[i]) for i in mine),
                mean_naturalness=_mean([s for i in mine for s in scores[i]]),
                preferred=won,
                preferred_share=round(won / rated, 3) if rated else None,
                characters=chars[provider],
            )
        )
    return RoundSummary(pairs=rated, no_preference=ties, voices=per_voice, providers=providers)


CSV_COLUMNS: Final = (
    "pair",
    "sentence",
    "voice_a_provider",
    "voice_a_label",
    "voice_a_id",
    "naturalness_a",
    "voice_b_provider",
    "voice_b_label",
    "voice_b_id",
    "naturalness_b",
    "preference",
    "preferred_provider",
    "rated_at_ist",
    "rated_by",
)


def export_csv(
    round_: PlatformVoiceComparisonRound, trials: list[PlatformVoiceComparisonTrial]
) -> str:
    """Every pair with both voices named, after the round is finished. Each cell is disarmed
    for a spreadsheet, since a sentence is typed by an operator."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    voices = round_.voices
    for t in trials:
        a, b = voices[t.voice_a], voices[t.voice_b]
        preferred = {"a": a["provider"], "b": b["provider"]}.get(t.preference or "", "")
        row = (
            t.position,
            round_.sentences[t.sentence_index],
            a["provider"],
            a["label"],
            a["vendor_id"],
            t.rating_a if t.rating_a is not None else "",
            b["provider"],
            b["label"],
            b["vendor_id"],
            t.rating_b if t.rating_b is not None else "",
            t.preference or "",
            preferred,
            t.rated_at.astimezone(IST).isoformat(timespec="seconds") if t.rated_at else "",
            str(t.rated_by) if t.rated_by else "",
        )
        writer.writerow([disarm_for_csv(str(cell)) for cell in row])
    return out.getvalue()


__all__ = [
    "CARTESIA_PROVIDER",
    "CSV_COLUMNS",
    "DEFAULT_LANGUAGE",
    "MAX_ROUNDS_LISTED",
    "MAX_SENTENCES",
    "MAX_SENTENCE_CHARS",
    "MAX_TRIALS",
    "MAX_VOICES_PER_PROVIDER",
    "SARVAM_PROVIDER",
    "SARVAM_VOICE_SECRET",
    "VOICE_LAB_REF",
    "CandidateVoice",
    "Clip",
    "LabState",
    "ProviderResult",
    "RoundSummary",
    "VoiceResult",
    "cartesia_voices",
    "clean_sentences",
    "clip_identity",
    "create_round",
    "default_sentences",
    "export_csv",
    "find_voice_lab",
    "finish_round",
    "install_sarvam_key",
    "lab_ready",
    "lab_state",
    "list_rounds",
    "plan_trials",
    "rate_trial",
    "read_round",
    "require_finished",
    "round_trials",
    "sarvam_key",
    "sarvam_voices",
    "set_up_voice_lab",
    "summarise",
    "trial_audio",
]
