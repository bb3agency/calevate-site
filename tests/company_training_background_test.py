"""Pip writes the company training in the background and saves it live (D-1034).

1. What queues a write: the client's first agent, a knowledge source going live or coming
   down, the business profile, the owner's overview; a burst of changes is one write, a
   change while one is written queues one more, and an early delivery defers itself.
2. The write: saved live from the business's own material, after a review whose quotes the
   code checks; repaired once, else not saved (the previous training stays) and an operator
   is alerted; shortened when it would not fit beside the longest script.
3. The owner's edits: told apart from Pip's words, given to the writer as constraints,
   checked to survive, and never overwritten by a rewrite started before the owner saved.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: the ladder is replaced.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import company_training, lifecycle, prompts
from apps.api.core.errors import ProblemError
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb import service as kb_service
from apps.api.tenancy.business_profile import ServiceItem
from apps.api.tenancy.profile_service import ProfilePatch, save_profile
from apps.workers import company_training_draft as worker
from apps.workers import training_sections
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.rls

OVERVIEW = "We are Sunrise Homes. We build flats in Kompally. A 2BHK starts at 60 lakh."
WRITTEN = "Sunrise Homes builds flats in Kompally.\nA 2BHK starts at 60 lakh."
#: Every line the fake writer answers rests on this passage of OVERVIEW, so the code's quote
#: check keeps it (`training_sections`).
QUOTE = "We build flats in Kompally"


def sections(text: str) -> dict[str, Any]:
    """A writer's answer holding `text`, one line per item, in the fixed sections' shape."""
    raw: dict[str, Any] = {key: [] for key, _heading in training_sections.SECTIONS}
    raw["business"] = [{"text": line, "quote": QUOTE} for line in text.splitlines() if line]
    return raw


def shown(text: str) -> str:
    """What agents read for `sections(text)`."""
    return f"About the business:\n{text}"


GROUNDED_CLAIM = {
    "said": "A 2BHK starts at 60 lakh.",
    "claim": "the 2BHK price",
    "evidence": "A 2BHK starts at 60 lakh",
}


async def _org() -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Sunrise Homes",
        slug=f"ctb-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and book a site visit.",
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id


async def _read(tenant: UUID) -> company_training.Training:
    async with tenant_session(tenant) as session:
        return await company_training.read_training(session, tenant)


async def _raw(tenant: UUID) -> Any:
    async with tenant_session(tenant) as session:
        return (
            await session.execute(
                text(
                    "SELECT proposal, pip_training, owner_edits, last_write FROM company_trainings"
                )
            )
        ).one()


async def _deliveries(proposal_id: UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :j "
                        "AND payload->>'proposal_id' = :p"
                    ),
                    {"j": worker.JOB_NAME, "p": str(proposal_id)},
                )
            ).scalar_one()
        )


async def _rewrite_now(tenant: UUID) -> UUID:
    async with tenant_session(tenant) as session:
        proposal = await company_training.request_rewrite(
            session, tenant_id=tenant, requested_by=None
        )
    return proposal.id


def _review(
    *, claims: list[dict[str, Any]] | None = None, edits: Any = (), problems: Any = ()
) -> dict[str, Any]:
    return {
        "claims": [GROUNDED_CLAIM] if claims is None else claims,
        "owner_edits": list(edits),
        "problems": list(problems),
    }


class Ladder:
    """The dashboard AI ladder, replaced: writes and reviews answered in order, each through
    the caller's own `parse`, so the code's checks run on them."""

    def __init__(self, writes: list[str], reviews: list[dict[str, Any]]) -> None:
        self.writes, self.reviews = writes, reviews
        self.asked: list[tuple[str, str]] = []
        self.during_write: Any = None

    async def __call__(self, request: str, instruction: str, **kwargs: Any) -> Any:
        self.asked.append((request, instruction))
        if instruction == worker.REVIEW_INSTRUCTION:
            raw: dict[str, Any] = self.reviews.pop(0)
        else:
            raw = sections(self.writes.pop(0))
            if self.during_write is not None:
                await self.during_write()
                self.during_write = None
        value = kwargs["parse"](raw)
        assert value is not None, raw
        return SimpleNamespace(
            value=value,
            capability=SimpleNamespace(disclosure=None),
            usage=None,
            model="gemini-2.5-flash-lite",
            earlier=(),
        )

    @property
    def writer_asks(self) -> list[tuple[str, str]]:
        return [a for a in self.asked if a[1] != worker.REVIEW_INSTRUCTION]


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None]]:
    raised: list[tuple[str, str | None]] = []

    def alert(_stage: str, code: str, *, episode: str | None = None, **_kw: Any) -> None:
        raised.append((code, episode))

    async def meter(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "alert", alert)
    monkeypatch.setattr(crm_assist, "meter_assist", meter)
    monkeypatch.setattr(crm_assist, "meter_earlier", meter)
    return raised


async def _run(
    monkeypatch: pytest.MonkeyPatch, tenant: UUID, proposal_id: UUID, ladder: Ladder
) -> str:
    monkeypatch.setattr(worker, "ask_json", ladder)
    payload = {"tenant_id": str(tenant), "proposal_id": str(proposal_id)}
    return await worker.draft_company_training({}, payload)


async def _with_overview(tenant: UUID) -> None:
    async with tenant_session(tenant) as session:
        await company_training.save_overview(session, tenant, OVERVIEW)


# --- 1. what queues a write -------------------------------------------------------------


async def test_the_first_agent_queues_the_first_training_and_a_later_one_does_not() -> None:
    tenant, _ = await _org()
    first = (await _read(tenant)).proposal
    assert first is not None and first.status == "queued"
    assert first.reasons == ("first_agent",)
    assert await _deliveries(first.id) == 1
    async with tenant_session(tenant) as session:
        await company_training.clear_proposal(session, tenant, first.id)
        await company_training.save_training(session, tenant, WRITTEN, saved_by=None)
        await lifecycle.create_agent(
            session,
            tenant_id=tenant,
            name="Ravi",
            direction="outbound",
            language_primary="en-IN",
        )
    assert (await _read(tenant)).proposal is None, "a client with a training is not rewritten"


async def test_a_client_with_no_agent_is_not_written_for() -> None:
    tenant, agent = await _org()
    async with tenant_session(tenant) as session:
        await session.execute(
            text("UPDATE agents SET archived_at = now(), status = 'archived' WHERE id = :a"),
            {"a": agent},
        )
        await session.execute(text("UPDATE company_trainings SET proposal = NULL"))
        assert (
            await company_training.schedule_write(session, tenant, reason="profile_changed") is None
        )
    assert (await _read(tenant)).proposal is None


async def test_a_burst_of_changes_is_one_write_pushed_back_but_never_past_the_cap() -> None:
    tenant, _ = await _org()
    first = (await _read(tenant)).proposal
    assert first is not None and first.due_at is not None
    async with tenant_session(tenant) as session:
        # The first change was long ago: the next may not push the write past the cap.
        long_ago = datetime.now(UTC) - timedelta(seconds=company_training.WRITE_MAX_WAIT_S - 5)
        await session.execute(
            text(
                "UPDATE company_trainings SET proposal = proposal || "
                "jsonb_build_object('first_at', CAST(:at AS text))"
            ),
            {"at": long_ago.isoformat()},
        )
        await company_training.schedule_write(session, tenant, reason="knowledge_changed")
        await company_training.schedule_write(session, tenant, reason="knowledge_changed")
        await company_training.schedule_write(session, tenant, reason="profile_changed")
    after = (await _read(tenant)).proposal
    assert after is not None and after.id == first.id
    assert after.reasons == ("first_agent", "knowledge_changed", "profile_changed")
    assert after.due_at is not None
    assert after.due_at <= long_ago + timedelta(seconds=company_training.WRITE_MAX_WAIT_S)
    assert await _deliveries(first.id) == 1, "one delivery for the whole burst"


async def test_knowledge_going_live_and_coming_down_queues_a_rewrite() -> None:
    tenant, _ = await _org()
    async with tenant_session(tenant) as session:
        await session.execute(text("UPDATE company_trainings SET proposal = NULL"))
        made = await kb_service.submit_source(
            session, tenant_id=tenant, name="Prices", body="A 3BHK is 90 lakh.", auto_approve=True
        )
        assert (await company_training.read_training(session, tenant)).proposal is None
        await kb_service.publish_source(session, tenant_id=tenant, source_id=UUID(str(made["id"])))
        published = (await company_training.read_training(session, tenant)).proposal
        assert published is not None and published.reasons == ("knowledge_changed",)
        await session.execute(text("UPDATE company_trainings SET proposal = NULL"))
        await kb_service.withdraw_source(session, tenant_id=tenant, source_id=UUID(str(made["id"])))
        withdrawn = (await company_training.read_training(session, tenant)).proposal
    assert withdrawn is not None and withdrawn.reasons == ("knowledge_changed",)


async def test_a_business_profile_change_queues_a_rewrite_and_a_resave_does_not() -> None:
    tenant, _ = await _org()
    patch = ProfilePatch(services=[ServiceItem(name="2BHK flats", price_inr="6000000")])
    async with tenant_session(tenant) as session:
        await session.execute(text("UPDATE company_trainings SET proposal = NULL"))
        await save_profile(session, tenant_id=tenant, patch=patch, user_id=None)
        changed = (await company_training.read_training(session, tenant)).proposal
        await session.execute(text("UPDATE company_trainings SET proposal = NULL"))
        await save_profile(session, tenant_id=tenant, patch=patch, user_id=None)
        resaved = (await company_training.read_training(session, tenant)).proposal
    assert changed is not None and changed.reasons == ("profile_changed",)
    assert resaved is None


def test_the_job_is_enqueued_and_deferred_under_one_name() -> None:
    assert worker.JOB_NAME == company_training.TRAINING_DRAFT_JOB


async def test_an_early_delivery_defers_itself_to_the_end_of_the_debounce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, _ = await _org()
    queued = (await _read(tenant)).proposal
    assert queued is not None and queued.due_at is not None
    deferred: list[dict[str, Any]] = []

    async def enqueue(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        deferred.append({"job": job, "payload": payload, **kwargs})
        return "j"

    monkeypatch.setattr(worker, "enqueue", enqueue)
    assert await _run(monkeypatch, tenant, queued.id, Ladder([], [])) == "deferred"
    assert deferred[0]["_defer_until"] == queued.due_at
    assert deferred[0]["payload"]["proposal_id"] == str(queued.id)
    still = (await _read(tenant)).proposal
    assert still is not None and still.status == "queued"


async def test_rewrite_now_is_refused_while_pip_is_writing() -> None:
    tenant, _ = await _org()
    async with tenant_session(tenant) as session:
        await session.execute(
            text(
                "UPDATE company_trainings SET proposal = proposal || jsonb_build_object("
                "'status', 'drafting', 'claimed_at', CAST(:at AS text))"
            ),
            {"at": datetime.now(UTC).isoformat()},
        )
        with pytest.raises(ProblemError) as busy:
            await company_training.request_rewrite(session, tenant_id=tenant, requested_by=None)
    assert busy.value.code == "company_training_in_progress"


# --- 2. the write -----------------------------------------------------------------------


async def test_pip_writes_the_training_live_from_the_business(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, _ = await _org()
    await _with_overview(tenant)
    proposal_id = await _rewrite_now(tenant)
    ladder = Ladder([WRITTEN], [_review()])
    assert await _run(monkeypatch, tenant, proposal_id, ladder) == "saved"
    # Delivered again by the outbox, written once.
    assert await _run(monkeypatch, tenant, proposal_id, Ladder([], [])) == "not_pending"
    read = await _read(tenant)
    assert (read.training, read.version, read.proposal, read.owner_edited) == (
        shown(WRITTEN),
        1,
        None,
        False,
    )
    assert read.last_write is not None
    assert read.last_write.reasons == ("first_agent", "owner_words", "owner_asked")
    assert "Kompally" in ladder.writer_asks[0][0]
    assert (await _raw(tenant)).pip_training == shown(WRITTEN)
    async with tenant_session(tenant) as session:
        reasons = (
            (
                await session.execute(
                    text("SELECT reasons FROM live_apply_runs WHERE tenant_id = :t"), {"t": tenant}
                )
            )
            .scalars()
            .all()
        )
    assert any("company_training" in str(r) for r in reasons), "live at once"
    assert alerts == []


async def test_nothing_is_written_without_material_to_write_from(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, _ = await _org()
    proposal_id = await _rewrite_now(tenant)
    assert await _run(monkeypatch, tenant, proposal_id, Ladder([], [])) == "no_material"
    read = await _read(tenant)
    assert (read.training, read.version, read.proposal) == ("", 0, None)


async def test_an_ungrounded_draft_is_repaired_once_then_kept_back(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, _ = await _org()
    await _with_overview(tenant)
    async with tenant_session(tenant) as session:
        await company_training.save_training(
            session, tenant, "The owner's training.", saved_by=None
        )
    proposal_id = await _rewrite_now(tenant)
    invented = {"said": "Free cab to the site.", "claim": "a free cab", "evidence": ""}
    ladder = Ladder(
        [WRITTEN + "\nFree cab to the site.", WRITTEN + "\nFree cab to the site."],
        [_review(claims=[invented]), _review(claims=[invented])],
    )
    assert await _run(monkeypatch, tenant, proposal_id, ladder) == "ungrounded"
    read = await _read(tenant)
    assert read.training == "The owner's training.", "the previous training stays"
    assert read.proposal is not None and read.proposal.status == "failed"
    assert read.proposal.reason == "ungrounded"
    assert "FIX THESE" in ladder.writer_asks[1][0] and "a free cab" in ladder.writer_asks[1][0]
    assert alerts == [("company_training_not_saved", "ungrounded")]


async def test_a_repaired_draft_is_saved(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, _ = await _org()
    await _with_overview(tenant)
    proposal_id = await _rewrite_now(tenant)
    stock = {"said": "We value every customer.", "detail": "fits any business"}
    ladder = Ladder(
        [WRITTEN + "\nWe value every customer.", WRITTEN],
        [_review(problems=[stock]), _review()],
    )
    assert await _run(monkeypatch, tenant, proposal_id, ladder) == "saved"
    assert (await _read(tenant)).training == shown(WRITTEN)
    assert alerts == []


async def test_a_draft_too_long_for_the_box_is_shortened_then_saved(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, agent = await _org()
    await _with_overview(tenant)
    proposal_id = await _rewrite_now(tenant)
    long = WRITTEN + "\nThe flats are near the ring road."

    async def overflow_of(_session: Any, _tenant: UUID, training: str) -> Any:
        if training != shown(long):
            return None
        return company_training.Overflow(
            over=10,
            detail="too long",
            remediation="shorten",
            extension=company_training.CompanyTrainingTooLong(agent_id=agent),
        )

    monkeypatch.setattr(company_training, "overflow_of", overflow_of)
    ladder = Ladder([long, WRITTEN], [_review(), _review()])
    assert await _run(monkeypatch, tenant, proposal_id, ladder) == "saved"
    read = await _read(tenant)
    assert read.training == shown(WRITTEN)
    assert read.last_write is not None and read.last_write.shortened
    assert "at most" in ladder.writer_asks[1][1]


# --- 3. the owner's edits ---------------------------------------------------------------


async def _pip_then_owner(tenant: UUID, owner_text: str) -> None:
    """Pip's saved training, then the owner's hand edit of it."""
    async with tenant_session(tenant) as session:
        version = (await company_training.read_training(session, tenant)).version
        await company_training.save_written(
            session,
            tenant,
            training=WRITTEN,
            base_version=version,
            owner_edits={},
            last_write={"at": datetime.now(UTC).isoformat(), "reasons": ["first_agent"]},
        )
        await company_training.save_training(session, tenant, owner_text, saved_by=None)


async def test_the_owners_edits_are_carried_into_the_rewrite_and_kept_for_the_next(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, _ = await _org()
    await _with_overview(tenant)
    await _pip_then_owner(tenant, WRITTEN + "\nWe close on Sundays.")
    assert (await _read(tenant)).owner_edited
    proposal_id = await _rewrite_now(tenant)
    rewritten = WRITTEN + "\nThe office is closed on Sundays."
    kept = {"edit": 1, "kept_in": "The office is closed on Sundays", "replaced_by": ""}
    sunday = {
        "said": "closed on Sundays",
        "claim": "Sunday closing",
        "evidence": "close on Sundays",
    }
    ladder = Ladder([rewritten], [_review(claims=[GROUNDED_CLAIM, sunday], edits=[kept])])
    assert await _run(monkeypatch, tenant, proposal_id, ladder) == "saved"
    request, instruction = ladder.writer_asks[0]
    assert "THE OWNER'S OWN EDITS:\n[1] We close on Sundays." in request
    assert worker.OWNER_EDITS_TAIL in instruction
    read = await _read(tenant)
    assert read.training == shown(rewritten) and not read.owner_edited
    assert read.last_write is not None and read.last_write.owner_edits_kept == 1
    stored = (await _raw(tenant)).owner_edits
    assert stored["said"] == [
        {"text": "We close on Sundays.", "where": "The office is closed on Sundays"}
    ]


async def test_an_owners_sentence_with_a_phone_number_is_kept_word_for_word_unread(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, _ = await _org()
    await _with_overview(tenant)
    private = "For delivery call 9876543210."
    await _pip_then_owner(tenant, f"{WRITTEN}\n{private}")
    proposal_id = await _rewrite_now(tenant)
    ladder = Ladder([WRITTEN], [_review()])
    assert await _run(monkeypatch, tenant, proposal_id, ladder) == "saved"
    assert all("9876543210" not in request for request, _ in ladder.asked)
    read = await _read(tenant)
    assert read.training == f"{shown(WRITTEN)}\n{private}"
    assert read.last_write is not None and read.last_write.owner_edits_kept == 1


async def test_a_rewrite_that_drops_an_owners_edit_is_not_saved(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, _ = await _org()
    await _with_overview(tenant)
    owner_text = WRITTEN + "\nWe close on Sundays."
    await _pip_then_owner(tenant, owner_text)
    proposal_id = await _rewrite_now(tenant)
    dropped = {"edit": 1, "kept_in": "", "replaced_by": ""}
    ladder = Ladder([WRITTEN, WRITTEN], [_review(edits=[dropped]), _review(edits=[dropped])])
    assert await _run(monkeypatch, tenant, proposal_id, ladder) == "ungrounded"
    assert "We close on Sundays." in ladder.writer_asks[1][0]
    assert (await _read(tenant)).training == owner_text


async def test_a_rewrite_never_overwrites_an_owner_save_made_while_it_was_written(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, _ = await _org()
    await _with_overview(tenant)
    proposal_id = await _rewrite_now(tenant)
    ladder = Ladder([WRITTEN], [_review()])

    async def owner_saves() -> None:
        async with tenant_session(tenant) as session:
            await company_training.save_training(session, tenant, "The owner's.", saved_by=None)

    ladder.during_write = owner_saves
    assert await _run(monkeypatch, tenant, proposal_id, ladder) == "superseded"
    read = await _read(tenant)
    assert read.training == "The owner's."
    again = read.proposal
    assert again is not None and again.status == "queued" and again.id != proposal_id
    assert "owner_asked" in again.reasons, "the change Pip was writing for is written again"


async def test_a_change_while_pip_writes_queues_one_more_write(
    monkeypatch: pytest.MonkeyPatch, alerts: list[Any]
) -> None:
    tenant, _ = await _org()
    await _with_overview(tenant)
    proposal_id = await _rewrite_now(tenant)
    ladder = Ladder([WRITTEN], [_review()])

    async def knowledge_changes() -> None:
        async with tenant_session(tenant) as session:
            await company_training.schedule_write(session, tenant, reason="knowledge_changed")

    ladder.during_write = knowledge_changes
    assert await _run(monkeypatch, tenant, proposal_id, ladder) == "saved"
    read = await _read(tenant)
    assert read.training == shown(WRITTEN)
    assert read.proposal is not None and read.proposal.status == "queued"
    assert read.proposal.reasons == ("knowledge_changed",)


def test_the_owners_edits_are_told_apart_from_pips_words() -> None:
    pip = "We build flats. Prices start at 60 lakh.\nCall us any day."
    live = "We build flats.  Prices start at 60 lakh.\nWe close on Sundays."
    assert worker.edits_since(pip, live) == (["We close on Sundays."], ["Call us any day."])
    # With nothing from Pip yet, all of it is the owner's.
    assert worker.edits_since(None, "We build flats. We close on Sundays.") == (
        ["We build flats.", "We close on Sundays."],
        [],
    )


def test_an_owners_fact_stays_theirs_until_they_take_it_out() -> None:
    stored = {"said": [{"text": "We close on Sundays.", "where": "Closed on Sundays"}]}
    pip = "We build flats. Closed on Sundays."
    kept = worker.carried_edits(stored, pip, "We build flats. Closed on Sundays.")
    assert [f.text for f in kept.said] == ["We close on Sundays."]
    taken_out = worker.carried_edits(stored, pip, "We build flats.")
    assert taken_out.said == [] and taken_out.removed == ["Closed on Sundays."]


def _checked(
    raw: dict[str, Any], training: str, edits: list[str], removed: tuple[str, ...] = ()
) -> worker.Findings | None:
    return worker.checked(
        raw,
        training=training,
        sources="WHAT IS KNOWN ABOUT THE BUSINESS:\nDelivery costs 80 rupees from 1 March.",
        edits=worker.OwnerEdits([worker.OwnerFact(e) for e in edits], list(removed)),
    )


def test_the_code_not_the_judge_decides_what_is_grounded_and_kept() -> None:
    edit = {"edit": 1, "kept_in": "Delivery is 50 rupees", "replaced_by": ""}
    found = _checked(
        _review(claims=[GROUNDED_CLAIM], edits=[edit]),
        "Delivery is 50 rupees.",
        ["Delivery costs 50 rupees."],
    )
    assert found is not None
    # The judge's quote is not in the sources, whatever it says.
    assert found.unsourced == [("A 2BHK starts at 60 lakh.", "the 2BHK price")]
    assert found.kept == {1: "Delivery is 50 rupees"} and not found.dropped
    # A quote the training does not hold, or a figure lost, is a dropped edit.
    lost = _checked(_review(claims=[], edits=[edit]), "Delivery is cheap.", ["Delivery costs 50."])
    assert lost is not None and lost.dropped == ["Delivery costs 50."]
    # Newer knowledge replaces an owner's fact only by a quote the sources hold.
    newer = {"edit": 1, "kept_in": "", "replaced_by": "Delivery costs 80 rupees"}
    replaced = _checked(
        _review(claims=[], edits=[newer]), "Delivery is 80 rupees.", ["Delivery is 50 rupees."]
    )
    assert replaced is not None and replaced.superseded == {1: "Delivery costs 80 rupees"}
    assert not replaced.failing


def test_what_the_owner_took_out_or_a_hidden_detail_fails_the_check() -> None:
    back = _checked(_review(claims=[]), "Call us any day.", [], ("Call us any day.",))
    assert back is not None and back.reinstated == ["Call us any day."] and back.failing
    masked = _checked(_review(claims=[]), "Call [phone ••10] to book.", [])
    assert masked is not None and masked.masked and masked.failing
    assert (
        worker.checked({"claims": []}, training="x", sources="", edits=worker.OwnerEdits()) is None
    )
