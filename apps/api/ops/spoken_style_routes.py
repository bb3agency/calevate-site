"""Ops > Spoken style: the founder reviews how agents speak each language (D-744).

    GET  /v1/ops/spoken-style                       every language: review state and counts
    GET  /v1/ops/spoken-style/{language}            one language: every entry, its working
                                                     copy, what is published, and the history
    POST /v1/ops/spoken-style/{language}/entries    approve, edit, add or retire one entry
    POST /v1/ops/spoken-style/{language}/publish    publish the reviewed set; step-up
                                                     `publish_spoken_style:<language>`

An entry change touches the working copy only, so it takes no step-up (it is the screen's
primary action, repeated entry by entry) and is audited. Publishing is what reaches callers:
it is step-up confirmed, audited, and queues a platform live-apply (D-720) in the same
transaction, so every live agent is republished with the reviewed words.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from calevate_shared.languages import find_language
from calevate_shared.spoken_style import (
    EntryKind,
    StyleEntry,
    default_entries,
    languages,
    normalize_value,
    style_for,
)
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.live_apply import queue_live_apply
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.ops import spoken_style_store as store

router = APIRouter(prefix="/v1/ops/spoken-style", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
StyleOperator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]
LanguageTag = Annotated[str, Path(max_length=16, pattern=r"^[a-z]{2,3}-[A-Z]{2}$")]

EntryStatus = Literal["approved", "needs_review", "retired"]
EntryAction = Literal["approve", "edit", "add", "retire"]

#: Kinds a reviewer may add a new entry of. A register line, an opening per direction and
#: an example per business type already exist for every language; they are edited instead.
ADDABLE: frozenset[str] = frozenset({"swap", "filler", "number_rule", "punctuation", "example"})
#: The most entries a reviewer may add to one language, so the review screen's list stays
#: bounded (`scripts/check_list_bounds`) and the writers' guide stays readable.
MAX_ADDED_ENTRIES = 200
#: Kinds that cannot be retired: a language always has its register line.
REQUIRED: frozenset[str] = frozenset({"register"})


def publish_confirmation(language: str) -> str:
    """The step-up string, bound to the language."""
    return f"publish_spoken_style:{language}"


class TurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: Literal["caller", "agent"]
    text: str = Field(max_length=300)


class EntryValue(BaseModel):
    """One entry's value; which fields are set depends on the kind (register, opening,
    number_rule, punctuation: `text`; filler: `text` and `use`; swap: `formal`, `spoken`
    and `in_prompt`; example: `turns`)."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=600)
    use: str | None = Field(default=None, max_length=300)
    formal: str | None = Field(default=None, max_length=120)
    spoken: str | None = Field(default=None, max_length=120)
    in_prompt: bool | None = None
    turns: list[TurnBody] | None = Field(default=None, max_length=10)


class EntryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EntryKind
    key: str
    status: EntryStatus
    #: `file` for an entry the shipped table has, `added` for one a reviewer added.
    origin: Literal["file", "added"]
    #: The working copy; null when retired.
    value: EntryValue | None
    #: What agents read now; null when the published set does not have it.
    published_value: EntryValue | None
    #: True when the working copy differs from what is published.
    unpublished: bool


class PublicationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_name: str
    reviewed_on: str
    published_at: datetime
    #: The admin account that published it.
    published_by: UUID
    note: str | None


class LanguageSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str
    name: str
    register_name: str
    #: `native_reviewed` once a published set has every entry approved.
    review: Literal["needs_native_review", "native_reviewed"]
    #: The stamp: "Reviewed by <reviewed_by> on <reviewed_on>", from the newest publication.
    reviewed_by: str | None
    reviewed_on: str | None
    total: int
    approved: int
    #: Entry changes made since the last publication.
    unpublished_changes: int


class LanguageOut(LanguageSummaryOut):
    entries: list[EntryOut]
    history: list[PublicationOut]
    #: The step-up string `POST .../publish` needs.
    publish_confirmation: str


class SpokenStyleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[LanguageSummaryOut]


class EntryChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EntryKind
    action: EntryAction
    #: The entry's key. For a new swap it is the formal word; for a new example the
    #: business type; for a new filler, number rule or punctuation note leave it out.
    key: str | None = Field(default=None, max_length=120)
    value: EntryValue | None = None


class PublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The native speaker who reviewed it, as the stamp should show them.
    reviewer_name: str = Field(min_length=2, max_length=80)
    note: str | None = Field(default=None, max_length=500)


def _value_out(value: dict[str, Any] | None) -> EntryValue | None:
    if value is None:
        return None
    return EntryValue.model_validate(value)


def _language_name(tag: str) -> str:
    language = find_language(tag)
    return language.english_name if language is not None else tag


def _known(tag: str) -> str:
    if tag not in languages():
        raise ProblemError.not_found("Spoken style language")
    return tag


async def _view(session: AsyncSession, tag: str) -> LanguageOut:
    """The working copy beside what is published, entry by entry."""
    file_entries: dict[tuple[str, str], StyleEntry] = {
        (e.kind, e.key): e for e in default_entries(tag)
    }
    working = await store.entry_states(session, language=tag)
    publication = (await store.latest_publications(session)).get(tag)
    published = (
        await store.entry_states(session, language=tag, through=publication.through_revision)
        if publication is not None
        else {}
    )
    keys = list(file_entries) + sorted(k for k in working if k not in file_entries)
    entries: list[EntryOut] = []
    in_force: list[tuple[str, str]] = []
    for kind, key in keys:
        file_entry = file_entries.get((kind, key))
        file_value = dict(file_entry.value) if file_entry is not None else None
        state = working.get((kind, key))
        value = state.value if state is not None else file_value
        pub_state = published.get((kind, key))
        published_value = pub_state.value if pub_state is not None else file_value
        if published_value is not None:
            in_force.append((kind, key))
        status: EntryStatus = (
            "retired"
            if value is None
            else "approved"
            if state is not None and state.approved
            else "needs_review"
        )
        entries.append(
            EntryOut(
                kind=kind,  # type: ignore[arg-type]
                key=key,
                status=status,
                origin="file" if file_entry is not None else "added",
                value=_value_out(value),
                published_value=_value_out(published_value),
                unpublished=state is not None and (pub_state is None or pub_state.seq != state.seq),
            )
        )
    # Reviewed when a publication exists and every entry it puts in force carries the
    # reviewer's approval: the rule `calevate_shared.spoken_style` applies to the prompt.
    reviewed = publication is not None and all(
        k in published and published[k].approved for k in in_force
    )
    live = [e for e in entries if e.status != "retired"]
    history = await store.publication_history(session, language=tag)
    style = style_for(tag)
    return LanguageOut(
        language=tag,
        name=_language_name(tag),
        register_name=style.register_name if style is not None else tag,
        review="native_reviewed" if reviewed else "needs_native_review",
        reviewed_by=publication.reviewer_name if publication is not None else None,
        reviewed_on=publication.reviewed_on if publication is not None else None,
        total=len(live),
        approved=sum(1 for e in live if e.status == "approved"),
        unpublished_changes=sum(1 for e in entries if e.unpublished),
        entries=entries,
        history=[
            PublicationOut(
                reviewer_name=p.reviewer_name,
                reviewed_on=p.reviewed_on,
                published_at=p.published_at,
                published_by=p.published_by,
                note=p.note,
            )
            for p in history
        ],
        publish_confirmation=publish_confirmation(tag),
    )


def _summary(view: LanguageOut) -> LanguageSummaryOut:
    return LanguageSummaryOut.model_validate(
        view.model_dump(include=set(LanguageSummaryOut.model_fields))
    )


@router.get(
    "",
    response_model=SpokenStyleOut,
    summary="Every language's spoken style: review state and counts",
    openapi_extra=permission_meta("ops:manage"),
)
async def list_spoken_styles(session: GlobalSession, _operator: StyleOperator) -> SpokenStyleOut:
    return SpokenStyleOut(languages=[_summary(await _view(session, tag)) for tag in languages()])


@router.get(
    "/{language}",
    response_model=LanguageOut,
    summary="One language's spoken style, entry by entry",
    openapi_extra=permission_meta("ops:manage"),
)
async def read_spoken_style(
    session: GlobalSession, _operator: StyleOperator, language: LanguageTag
) -> LanguageOut:
    return await _view(session, _known(language))


def _refuse(code: str, title: str, detail: str) -> ProblemError:
    return ProblemError(kind="validation", code=code, title=title, detail=detail)


def _new_key(kind: str, change: EntryChangeIn) -> str:
    if kind == "swap":
        return " ".join((change.value.formal or "").split()) if change.value else ""
    if kind == "example":
        return (change.key or "").strip()
    return f"{kind.replace('_', '-')}-{secrets.token_hex(3)}"


def _no_actor() -> ProblemError:
    return ProblemError(
        kind="auth",
        code="spoken_style_actor_unknown",
        title="This session has no admin identity",
        detail="A spoken-style review has to be attributable to an operator.",
    )


@router.post(
    "/{language}/entries",
    response_model=LanguageOut,
    summary="Approve, edit, add or retire one spoken-style entry (audited)",
    description=(
        "Changes the working copy only; nothing reaches an agent until the language is "
        "published. An edit or an addition counts as the reviewer's approval."
    ),
    openapi_extra=permission_meta("ops:manage"),
)
async def change_entry(
    change: EntryChangeIn,
    session: GlobalSession,
    request: Request,
    principal: StyleOperator,
    language: LanguageTag,
) -> LanguageOut:
    tag = _known(language)
    if principal.user_id is None:
        raise _no_actor()
    kind = change.kind
    file_entries = {(e.kind, e.key): e for e in default_entries(tag)}
    working = await store.entry_states(session, language=tag)

    def current(key: str) -> dict[str, Any] | None:
        state = working.get((kind, key))
        if state is not None:
            return state.value
        entry = file_entries.get((kind, key))
        return dict(entry.value) if entry is not None else None

    if change.action == "add" and kind not in ADDABLE:
        raise _refuse(
            "spoken_style_not_addable",
            "That kind cannot be added",
            "A language has one register line and one opening per direction; edit them.",
        )
    key = _new_key(kind, change) if change.action == "add" else (change.key or "").strip()
    if not key:
        raise _refuse("spoken_style_key_missing", "Which entry?", "Name the entry to change.")
    existing = current(key)
    if change.action != "add" and existing is None:
        raise ProblemError.not_found("Spoken style entry")
    if change.action == "add" and existing is not None:
        raise _refuse(
            "spoken_style_entry_exists",
            "That entry already exists",
            "Edit the existing entry instead of adding it again.",
        )
    added = sum(1 for k in working if k not in file_entries)
    if change.action == "add" and added >= MAX_ADDED_ENTRIES:
        raise _refuse(
            "spoken_style_too_many",
            "This language has as many added entries as it can hold",
            f"Retire or edit one of the {MAX_ADDED_ENTRIES} added entries instead.",
        )

    value: dict[str, Any] | None
    if change.action == "retire":
        if kind in REQUIRED:
            raise _refuse(
                "spoken_style_required",
                "This entry cannot be retired",
                "Every language keeps its register line; edit it instead.",
            )
        value = None
    elif change.action == "approve":
        value = existing
    else:
        if change.value is None:
            raise _refuse("spoken_style_value_missing", "Nothing to save", "Send the new value.")
        raw = change.value.model_dump(exclude_none=True)
        if kind == "swap":
            raw.setdefault("formal", key)
            raw.setdefault("in_prompt", bool(existing and existing.get("in_prompt")))
        try:
            value = normalize_value(kind, key, raw)
        except ValueError as exc:
            raise _refuse(
                "spoken_style_value_invalid", "That entry is not valid", str(exc)
            ) from exc
    seq = await store.add_revision(
        session,
        language=tag,
        kind=kind,
        key=key,
        value=value,
        approved=change.action != "retire",
        actor_id=principal.user_id,
    )
    await write_audit(
        session,
        action=f"platform.spoken_style_{change.action}",
        actor=principal,
        object_type="spoken_style_revisions",
        object_id=str(seq),
        ip=client_request_ip(request),
        summary={"language": tag, "kind": kind, "key": key},
    )
    return await _view(session, tag)


@router.post(
    "/{language}/publish",
    response_model=LanguageOut,
    summary="Publish a language's reviewed spoken style to every live agent (step-up, audited)",
    description=(
        "Every entry change of this language so far becomes what prompts, starters and the "
        "script writer read, stamped with the reviewer's name, and every live agent is "
        "republished with it (live apply, scope platform). Requires `X-Confirm-Action: "
        "publish_spoken_style:<language>`."
    ),
    openapi_extra=permission_meta("ops:manage"),
)
async def publish_spoken_style(
    payload: PublishIn,
    session: GlobalSession,
    request: Request,
    principal: StyleOperator,
    language: LanguageTag,
    step_up: StepUpGate,
    tasks: BackgroundTasks,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> LanguageOut:
    tag = _known(language)
    step_up.require(x_confirm_action, publish_confirmation(tag))
    if principal.user_id is None:
        raise _no_actor()
    through = await store.last_revision(session, language=tag)
    previous = (await store.latest_publications(session)).get(tag)
    if through == 0 or (previous is not None and previous.through_revision == through):
        raise ProblemError(
            kind="conflict",
            code="spoken_style_nothing_to_publish",
            title="Nothing new to publish",
            detail="Approve, edit, add or retire an entry first; then publish.",
        )
    publication = await store.add_publication(
        session,
        language=tag,
        through_revision=through,
        reviewer_name=" ".join(payload.reviewer_name.split()),
        note=payload.note.strip() if payload.note and payload.note.strip() else None,
        actor_id=principal.user_id,
    )
    run_id = await queue_live_apply(
        session,
        scope="platform",
        reason=f"spoken_style:{tag}",
        requested_by=principal.user_id,
    )
    await write_audit(
        session,
        action="platform.spoken_style_published",
        actor=principal,
        object_type="spoken_style_publications",
        object_id=str(publication.seq),
        ip=client_request_ip(request),
        summary={
            "language": tag,
            "through_revision": through,
            "reviewer_name": publication.reviewer_name,
            "live_apply_run": str(run_id),
        },
    )
    # This process reads the new words at once; every other within its poll, and the
    # live-apply walk refreshes before it publishes.
    tasks.add_task(store.refresh_spoken_style)
    return await _view(session, tag)


__all__ = ["publish_confirmation", "router"]
