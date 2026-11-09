"""Deep audit D5 (10 Nov 2026): running it and telling the truth about it.

Each test names the failure it guards against and failed on the code before its fix.
"""

from __future__ import annotations

import pytest
from apps.api.agents import starter_plans
from apps.api.db.session import tenant_session
from apps.api.teach import facts as fact_store
from apps.api.tenancy import profile_wording
from apps.workers import profile_wording as wording_worker
from apps.workers import starter_steps as steps_worker
from sqlalchemy import text
from tests.agent_starters_test import _starters, _tenant
from tests.deploy_swap_gates_test import _components
from tests.profile_wording_test import _answer as _wording_answer
from tests.profile_wording_test import _describe
from tests.profile_wording_test import _raw as _wording_raw
from tests.starter_steps_test import _all_raw, _known, _services
from tests.starter_steps_test import _answer as _steps_answer
from tests.teach_questions_test import _list, _queued
from tests.teach_questions_test import _tenant as _teach_tenant

# --- D5-01: a return to an earlier description never asked again (round-4 X3 P3) ----------


@pytest.mark.rls
async def test_steps_return_to_an_earlier_list_are_written_for_it_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")

    async def change_to(services: str, prefix: str) -> None:
        await _services(tenant_id, services)
        async with tenant_session(tenant_id) as session:
            assert await starter_plans.maybe_write_starter_steps(session, tenant_id=tenant_id)
        monkeypatch.setattr(steps_worker, "ask_json", _steps_answer(_all_raw(prefix)))
        payload = {"tenant_id": str(tenant_id), "known": await _known(tenant_id)}
        assert await steps_worker.write_starter_steps({}, payload) == "written"

    await change_to('[{"name": "Crop records"}]', "Crop")
    await change_to('[{"name": "Crop records"}, {"name": "Soil tests"}]', "Soil")
    # Back to the first list: on the old key (`starter-steps:<tenant>:<digest>`) this ask was
    # spent, nothing was queued, and the Soil steps stayed on a business that no longer sells it.
    await change_to('[{"name": "Crop records"}]', "Crop")
    code, body = await _starters(token, "?job=answer_calls")
    assert code == 200, body
    assert body["starters"][0]["step_titles"][0].startswith("Crop")

    # Asked twice before the draft lands, still one job.
    await _services(tenant_id, '[{"name": "Rice"}]')
    async with tenant_session(tenant_id) as session:
        assert await starter_plans.maybe_write_starter_steps(session, tenant_id=tenant_id)
        assert not await starter_plans.maybe_write_starter_steps(session, tenant_id=tenant_id)


@pytest.mark.rls
async def test_wording_return_to_an_earlier_description_is_written_for_it_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _token = await _tenant("custom", "Rytu Khata")

    async def change_to(services: str, offer_label: str) -> None:
        known = await _describe(tenant_id, services)
        async with tenant_session(tenant_id) as session:
            assert await profile_wording.maybe_write_profile_wording(session, tenant_id=tenant_id)
        monkeypatch.setattr(
            wording_worker, "ask_json", _wording_answer(_wording_raw(offer_label=offer_label))
        )
        payload = {"tenant_id": str(tenant_id), "known": known}
        assert await wording_worker.write_profile_wording({}, payload) == "written"

    await change_to('[{"name": "Crop records"}]', "Plan")
    await change_to('[{"name": "Crop records"}, {"name": "Soil tests"}]', "Test")
    await change_to('[{"name": "Crop records"}]', "Plan")
    async with tenant_session(tenant_id) as session:
        assert (await profile_wording.stored_wording(session, tenant_id=tenant_id)).offer_label == (
            "Plan"
        )


@pytest.mark.rls
async def test_a_teach_draft_is_queued_again_when_its_inputs_return_to_earlier_ones() -> None:
    tenant_id, _agent_id, _ = await _teach_tenant()
    first = await _list(tenant_id, queue_drafts=True)
    count = len(first.items)
    assert count > 0

    async with tenant_session(tenant_id) as session:
        await fact_store.add_facts(
            session,
            tenant_id=tenant_id,
            texts=["We sell only organic spices."],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )
    await _list(tenant_id, queue_drafts=True)
    assert await _queued(tenant_id) == 2 * count

    # The owner removes the fact: the inputs are the first ones again. The rows now say
    # `queued` for them; on the old once-per-fingerprint key no job came and the question
    # waited for a draft for ever.
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE kb_facts SET removed_at = now()"))
    listed = await _list(tenant_id, queue_drafts=True)
    assert all(q.drafting for q in listed.items)
    assert await _queued(tenant_id) == 3 * count
    # A read without a change queues nothing.
    await _list(tenant_id, queue_drafts=True)
    assert await _queued(tenant_id) == 3 * count


# --- D5-02: a runbook change shipped nowhere -------------------------------------------------


def test_a_runbook_change_redeploys_the_services_that_read_it_but_not_the_receiver() -> None:
    # `core/alarm_guide` reads alarm-index.md from the image at send time and the admin Pip
    # searches runbooks/; the path map had no arm for it, so a `--changed` deploy of a
    # runbook edit printed "nothing to deploy" and alarm mails kept the old instructions.
    assert _components("runbooks/alarm-index.md") == ["api", "workers", "workers-bulk"]
