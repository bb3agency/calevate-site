"""The blind voice comparison (D-946) — admin realm, `ops:manage`. No client is affected.

    GET   /v1/ops/voice-comparison/setup                 the Sarvam key, the comparison
                                                         workspace and Cartesia's readiness
    POST  /v1/ops/voice-comparison/setup                 set up Sarvam voices (step-up, audited)
    GET   /v1/ops/voice-comparison/voices                the Cartesia and Sarvam candidates
    GET   /v1/ops/voice-comparison/sentences             the default Telugu sentences
    GET   /v1/ops/voice-comparison/rounds                the latest rounds
    POST  /v1/ops/voice-comparison/rounds                start a round (audited)
    GET   /v1/ops/voice-comparison/rounds/{id}           a round as the listener sees it: BLIND
    POST  /v1/ops/voice-comparison/rounds/{id}/finish    close it (audited)
    GET   /v1/ops/voice-comparison/rounds/{id}/summary   the reveal, once finished
    GET   /v1/ops/voice-comparison/rounds/{id}/export    the CSV, once finished (audited)
    GET   /v1/ops/voice-comparison/trials/{id}/audio     one side of one pair
    PUT   /v1/ops/voice-comparison/trials/{id}           rate one pair (audited)

STEP-UP ON THE SET-UP ALONE: it creates a workspace on the voice platform and hands it one of
our credentials. A round and its ratings touch no agent, call or client.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Final, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.disposition import attachment_disposition
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices
from apps.api.ops import voice_comparison as vc
from apps.api.ops.models import PlatformVoiceComparisonRound, PlatformVoiceComparisonTrial

router = APIRouter(prefix="/v1/ops/voice-comparison", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
Listener = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]

SETUP_CONFIRMATION: Final = "set_up_sarvam_voices"
_AUDIO_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    200: {
        "description": "The clip.",
        "content": {
            "audio/mpeg": {"schema": {"type": "string", "format": "binary"}},
            "audio/wav": {"schema": {"type": "string", "format": "binary"}},
        },
    }
}
_CSV_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    200: {"description": "Every pair.", "content": {"text/csv": {"schema": {"type": "string"}}}}
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceComparisonSetupOut(Strict):
    #: `sarvam_voice_api_key` is stored.
    sarvam_key_stored: bool
    #: The comparison workspace exists on the voice platform.
    workspace_made: bool
    #: It speaks on our Sarvam key, voice only.
    sarvam_ready: bool
    #: The voice provider whose key that workspace holds.
    voice_provider: str | None
    #: A workspace where Cartesia voices are previewed answers ready.
    cartesia_ready: bool
    #: What is still to do, in order; empty when a round can start.
    steps: list[str]

    @classmethod
    def of(cls, state: vc.LabState) -> VoiceComparisonSetupOut:
        steps: list[str] = []
        if not state.key_stored:
            steps.append("Save sarvam_voice_api_key in Settings, Credentials.")
        if not state.ready:
            steps.append("Choose Set up Sarvam voices.")
        if not state.cartesia_ready:
            steps.append("Run Studio ready under Voices, so Cartesia voices can be heard.")
        return cls(
            sarvam_key_stored=state.key_stored,
            workspace_made=state.workspace is not None,
            sarvam_ready=state.ready,
            voice_provider=state.voice_provider,
            cartesia_ready=state.cartesia_ready,
            steps=steps,
        )


class VoiceComparisonCandidateOut(Strict):
    vendor_id: str
    label: str
    language: str | None
    gender: str | None


class VoiceComparisonVoicesOut(Strict):
    cartesia: list[VoiceComparisonCandidateOut]
    sarvam: list[VoiceComparisonCandidateOut]
    #: False when the platform said the Sarvam list may be short.
    sarvam_complete: bool
    #: Why Sarvam voices could not be listed, or null.
    sarvam_note: str | None


class VoiceComparisonSentencesOut(Strict):
    language: str
    sentences: list[str]
    max_sentences: int
    max_chars: int


class VoiceComparisonRoundIn(Strict):
    title: str = Field(default="", max_length=80)
    language: str = Field(default=vc.DEFAULT_LANGUAGE, pattern=r"^[a-z]{2}-[A-Z]{2}$")
    cartesia_voice_ids: list[str] = Field(min_length=1, max_length=vc.MAX_VOICES_PER_PROVIDER)
    sarvam_voice_ids: list[str] = Field(min_length=1, max_length=vc.MAX_VOICES_PER_PROVIDER)
    sentences: list[str] = Field(min_length=1, max_length=vc.MAX_SENTENCES)


class VoiceComparisonBlindTrialOut(Strict):
    """One pair as the listener sees it before the reveal: no voice, label or provider."""

    id: UUID
    position: int
    sentence: str
    rating_a: int | None
    rating_b: int | None
    preference: Literal["a", "b", "none"] | None
    rated: bool


class VoiceComparisonRoundOut(Strict):
    id: UUID
    title: str
    language: str
    created_at: datetime
    finished_at: datetime | None
    pairs: int
    rated: int
    #: How many voices of each provider are in the round, not which.
    cartesia_voices: int
    sarvam_voices: int
    trials: list[VoiceComparisonBlindTrialOut]


class VoiceComparisonRoundListItem(Strict):
    id: UUID
    title: str
    created_at: datetime
    finished_at: datetime | None
    pairs: int
    rated: int


class VoiceComparisonRoundsOut(Strict):
    rounds: list[VoiceComparisonRoundListItem]


class VoiceComparisonRateIn(Strict):
    rating_a: int = Field(ge=1, le=5)
    rating_b: int = Field(ge=1, le=5)
    preference: Literal["a", "b", "none"]


class VoiceComparisonVoiceResultOut(Strict):
    provider: Literal["cartesia", "sarvam"]
    vendor_id: str
    label: str
    heard: int
    mean_naturalness: float | None
    preferred: int
    not_preferred: int
    no_preference: int


class VoiceComparisonProviderResultOut(Strict):
    provider: Literal["cartesia", "sarvam"]
    voices: int
    heard: int
    mean_naturalness: float | None
    preferred: int
    preferred_share: float | None
    #: Characters this round sent the provider to speak (cached clips add none).
    characters: int


class VoiceComparisonSummaryOut(Strict):
    round_id: UUID
    finished_at: datetime
    pairs: int
    no_preference: int
    voices: list[VoiceComparisonVoiceResultOut]
    providers: list[VoiceComparisonProviderResultOut]
    #: What the characters cost is not computed, and why.
    cost_note: str


COST_NOTE: Final = (
    "Each provider bills our own account per character spoken. No rupee figure is shown: "
    "Cartesia is a plan with an allotment, and no Sarvam voice price is attested here. "
    "Whether the voice platform itself charges for a preview is not stated in its docs."
)


def _engine() -> HostsVoices:
    engine = get_engine()
    if not isinstance(engine, HostsVoices) or engine.capabilities.is_ours("tts"):
        raise ProblemError(
            kind="business_rule",
            code="voices_not_hosted",
            title="This voice platform does not host its own voices",
            detail="The comparison runs on a voice platform that speaks own-key voices.",
        )
    return engine


async def _audit(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    *,
    action: str,
    object_type: str,
    object_id: str | None,
    summary: dict[str, object],
) -> None:
    await write_audit(
        session,
        action=action,
        actor=principal,
        object_type=object_type,
        object_id=object_id,
        ip=client_request_ip(request),
        summary=summary,
    )


def _actor(principal: Principal) -> UUID:
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="voice_comparison_actor_unknown",
            title="This session has no admin identity",
            detail="A rating has to be attributable to an operator.",
        )
    return principal.user_id


def _blind(
    round_: PlatformVoiceComparisonRound, trials: list[PlatformVoiceComparisonTrial]
) -> VoiceComparisonRoundOut:
    providers = [str(v["provider"]) for v in round_.voices]
    return VoiceComparisonRoundOut(
        id=round_.id,
        title=round_.title,
        language=round_.language,
        created_at=round_.created_at,
        finished_at=round_.finished_at,
        pairs=len(trials),
        rated=sum(1 for t in trials if t.rated_at is not None),
        cartesia_voices=providers.count(vc.CARTESIA_PROVIDER),
        sarvam_voices=providers.count(vc.SARVAM_PROVIDER),
        trials=[
            VoiceComparisonBlindTrialOut(
                id=t.id,
                position=t.position,
                sentence=str(round_.sentences[t.sentence_index]),
                rating_a=t.rating_a,
                rating_b=t.rating_b,
                preference=cast("vc.Preference | None", t.preference),
                rated=t.rated_at is not None,
            )
            for t in trials
        ],
    )


@router.get(
    "/setup",
    response_model=VoiceComparisonSetupOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Whether Sarvam and Cartesia voices can be compared yet (admin realm)",
)
async def get_setup(_: Listener) -> VoiceComparisonSetupOut:
    return VoiceComparisonSetupOut.of(await vc.lab_state(_engine()))


@router.post(
    "/setup",
    response_model=VoiceComparisonSetupOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Set up Sarvam voices for the comparison (step-up, audited)",
    description=(
        "Makes our comparison workspace on the voice platform if it does not exist, installs "
        "`sarvam_voice_api_key` there and switches it on for the voice only, then reads it "
        "back. It holds no agents. Our main workspace and every client workspace are left as "
        "they are. Idempotent. Requires `X-Confirm-Action: set_up_sarvam_voices`."
    ),
)
async def post_setup(
    session: GlobalSession,
    request: Request,
    principal: Listener,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> VoiceComparisonSetupOut:
    step_up.require(x_confirm_action, SETUP_CONFIRMATION)
    state = await vc.set_up_voice_lab(_engine())
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_comparison_set_up",
        object_type="voice_comparison_workspace",
        object_id=state.workspace,
        summary={"sarvam_ready": state.ready, "voice_provider": state.voice_provider},
    )
    return VoiceComparisonSetupOut.of(state)


@router.get(
    "/voices",
    response_model=VoiceComparisonVoicesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="The Cartesia and Sarvam voices a round may use (admin realm)",
    description=(
        "Cartesia: the Studio voices added under Voices. Sarvam: the voices our Sarvam key "
        "reaches, as the voice platform lists them in the comparison workspace."
    ),
)
async def get_voices(session: GlobalSession, _: Listener) -> VoiceComparisonVoicesOut:
    engine = _engine()
    cartesia = await vc.cartesia_voices(session)
    sarvam: list[vc.CandidateVoice] = []
    complete, note = True, None
    try:
        sarvam, complete = await vc.sarvam_voices(engine)
    except ProblemError as exc:
        complete, note = False, exc.detail

    def out(voices: list[vc.CandidateVoice]) -> list[VoiceComparisonCandidateOut]:
        return [
            VoiceComparisonCandidateOut(
                vendor_id=v.vendor_id, label=v.label, language=v.language, gender=v.gender
            )
            for v in voices
        ]

    return VoiceComparisonVoicesOut(
        cartesia=out(cartesia), sarvam=out(sarvam), sarvam_complete=complete, sarvam_note=note
    )


@router.get(
    "/sentences",
    response_model=VoiceComparisonSentencesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="The default test sentences, from our spoken style (admin realm)",
)
async def get_sentences(
    _: Listener,
    language: Annotated[str, Query(pattern=r"^[a-z]{2}-[A-Z]{2}$")] = vc.DEFAULT_LANGUAGE,
) -> VoiceComparisonSentencesOut:
    return VoiceComparisonSentencesOut(
        language=language,
        sentences=vc.default_sentences(language),
        max_sentences=vc.MAX_SENTENCES,
        max_chars=vc.MAX_SENTENCE_CHARS,
    )


@router.get(
    "/rounds",
    response_model=VoiceComparisonRoundsOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="The latest comparison rounds (admin realm)",
)
async def get_rounds(
    session: GlobalSession,
    _: Listener,
    limit: Annotated[int, Query(ge=1, le=vc.MAX_ROUNDS_LISTED)] = vc.MAX_ROUNDS_LISTED,
) -> VoiceComparisonRoundsOut:
    return VoiceComparisonRoundsOut(
        rounds=[
            VoiceComparisonRoundListItem(
                id=r.id,
                title=r.title,
                created_at=r.created_at,
                finished_at=r.finished_at,
                pairs=pairs,
                rated=rated,
            )
            for r, pairs, rated in await vc.list_rounds(session, limit=limit)
        ]
    )


@router.post(
    "/rounds",
    response_model=VoiceComparisonRoundOut,
    status_code=201,
    openapi_extra=permission_meta("ops:manage"),
    summary="Start a blind round (audited)",
    description=(
        "Every Cartesia voice against every Sarvam voice on every sentence, at most 120 "
        "pairs, which provider is Voice A drawn at random for each pair and the order "
        "shuffled. The answer names no voice or provider."
    ),
)
async def post_round(
    payload: VoiceComparisonRoundIn, session: GlobalSession, request: Request, principal: Listener
) -> VoiceComparisonRoundOut:
    round_ = await vc.create_round(
        session,
        _engine(),
        title=payload.title,
        language=payload.language,
        cartesia_ids=payload.cartesia_voice_ids,
        sarvam_ids=payload.sarvam_voice_ids,
        sentences=payload.sentences,
        actor_id=_actor(principal),
    )
    trials = await vc.round_trials(session, round_.id)
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_comparison_started",
        object_type="platform_voice_comparison_rounds",
        object_id=str(round_.id),
        summary={
            "pairs": len(trials),
            "cartesia_voices": len(payload.cartesia_voice_ids),
            "sarvam_voices": len(payload.sarvam_voice_ids),
            "sentences": len(round_.sentences),
        },
    )
    await session.refresh(round_)
    return _blind(round_, trials)


@router.get(
    "/rounds/{round_id}",
    response_model=VoiceComparisonRoundOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="A round as the listener sees it, blind (admin realm)",
)
async def get_round(round_id: UUID, session: GlobalSession, _: Listener) -> VoiceComparisonRoundOut:
    round_ = await vc.read_round(session, round_id)
    return _blind(round_, await vc.round_trials(session, round_id))


@router.post(
    "/rounds/{round_id}/finish",
    response_model=VoiceComparisonRoundOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Finish a round once every pair is rated (audited)",
)
async def post_finish(
    round_id: UUID, session: GlobalSession, request: Request, principal: Listener
) -> VoiceComparisonRoundOut:
    round_ = await vc.finish_round(session, round_id)
    trials = await vc.round_trials(session, round_id)
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_comparison_finished",
        object_type="platform_voice_comparison_rounds",
        object_id=str(round_id),
        summary={"pairs": len(trials)},
    )
    return _blind(round_, trials)


@router.get(
    "/rounds/{round_id}/summary",
    response_model=VoiceComparisonSummaryOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Which provider spoke each voice, and how each was rated (once finished)",
)
async def get_summary(
    round_id: UUID, session: GlobalSession, _: Listener
) -> VoiceComparisonSummaryOut:
    round_ = await vc.read_round(session, round_id)
    finished_at = vc.require_finished(round_)
    summary = vc.summarise(round_, await vc.round_trials(session, round_id))
    return VoiceComparisonSummaryOut(
        round_id=round_.id,
        finished_at=finished_at,
        pairs=summary.pairs,
        no_preference=summary.no_preference,
        voices=[VoiceComparisonVoiceResultOut(**asdict(v)) for v in summary.voices],
        providers=[VoiceComparisonProviderResultOut(**asdict(p)) for p in summary.providers],
        cost_note=COST_NOTE,
    )


@router.get(
    "/rounds/{round_id}/export",
    response_class=Response,
    openapi_extra=permission_meta("ops:manage"),
    summary="Every pair of a finished round as CSV (audited)",
    responses=_CSV_RESPONSES,
)
async def get_export(
    round_id: UUID, session: GlobalSession, request: Request, principal: Listener
) -> Response:
    round_ = await vc.read_round(session, round_id)
    vc.require_finished(round_)
    trials = await vc.round_trials(session, round_id)
    body = vc.export_csv(round_, trials)
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_comparison_exported",
        object_type="platform_voice_comparison_rounds",
        object_id=str(round_id),
        summary={"rows": len(trials)},
    )
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": attachment_disposition(f"voice-comparison-{round_id}.csv")},
    )


@router.get(
    "/trials/{trial_id}/audio",
    response_class=Response,
    openapi_extra=permission_meta("ops:manage"),
    summary="One side of one pair, spoken and cached (admin realm)",
    description=(
        "Spoken by the voice platform on our own key the first time and cached after, so a "
        "pair heard again costs nothing. The provider bills its characters to our account."
    ),
    responses=_AUDIO_RESPONSES,
)
async def get_audio(
    trial_id: UUID,
    session: GlobalSession,
    _: Listener,
    side: Annotated[Literal["a", "b"], Query()],
) -> Response:
    clip = await vc.trial_audio(session, _engine(), trial_id, side)
    return Response(
        content=clip.data,
        media_type=clip.content_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@router.put(
    "/trials/{trial_id}",
    response_model=VoiceComparisonBlindTrialOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Rate one pair: naturalness 1-5 for each side and a preference (audited)",
)
async def put_rating(
    trial_id: UUID,
    payload: VoiceComparisonRateIn,
    session: GlobalSession,
    request: Request,
    principal: Listener,
) -> VoiceComparisonBlindTrialOut:
    trial = await vc.rate_trial(
        session,
        trial_id,
        rating_a=payload.rating_a,
        rating_b=payload.rating_b,
        preference=payload.preference,
        actor_id=_actor(principal),
    )
    round_ = await vc.read_round(session, trial.round_id)
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_comparison_rated",
        object_type="platform_voice_comparison_trials",
        object_id=str(trial_id),
        summary={
            "round_id": str(trial.round_id),
            "rating_a": payload.rating_a,
            "rating_b": payload.rating_b,
            "preference": payload.preference,
        },
    )
    return VoiceComparisonBlindTrialOut(
        id=trial.id,
        position=trial.position,
        sentence=str(round_.sentences[trial.sentence_index]),
        rating_a=trial.rating_a,
        rating_b=trial.rating_b,
        preference=payload.preference,
        rated=True,
    )


__all__ = ["SETUP_CONFIRMATION", "router"]
