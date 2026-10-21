"""The operator's in-call model comparison (D-739): it switches the agent's model at the
vendor, talks the standard callers through, scores them with the test loop's hard checks,
switches again when the drift sweep moved the model back, and reports one row per model."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from apps.api.engine.catalogue import CatalogueModel
from apps.api.engine.test_chat import TestChatTurn
from apps.api.engine.thinnest_agent_model import ThinnestAgentModel
from scripts import compare_in_call_models as compare


async def test_the_model_client_reads_and_switches_one_field() -> None:
    seen: list[tuple[str, str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"id": "ag_1", "model": "gpt-oss-120b"})

    client = httpx.AsyncClient(
        base_url="https://vendor.test/api/v1", transport=httpx.MockTransport(handler)
    )
    models = ThinnestAgentModel(api_key="k", client=client)
    assert await models.held("ag_1") == "gpt-oss-120b"
    await models.switch("ag_1", None)
    assert seen[1] == ("PATCH", "/api/v1/agents/ag_1", {"model": None})


class _Models:
    def __init__(self, held: str | None) -> None:
        self.now = held
        self.switches: list[str | None] = []

    async def held(self, ref: str) -> str | None:
        return self.now

    async def switch(self, ref: str, model_id: str | None) -> None:
        self.switches.append(model_id)
        self.now = model_id or "prana-voice"


class _Chat:
    def __init__(self, models: _Models) -> None:
        self.models = models
        self.calls = 0

    async def test_chat(
        self, ref: str, message: str, *, session: str | None = None, call_mode: bool = False
    ) -> TestChatTurn:
        self.calls += 1
        if self.calls == 2:
            # The drift sweep put the agent back on its published model.
            self.models.now = "published-model"
        reply = (
            "Which one? How much? [It is 11:03 am now.]"
            if self.models.now == "bad-model"
            else "ఉందండి. మీకు ఎంత కావాలి?"
        )
        return TestChatTurn(session="vr_1", reply=reply, tools=())


async def test_each_model_is_scored_and_switched_back_after_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compare, "PAUSE_S", 0)
    models = _Models("published-model")
    chat = _Chat(models)
    scenarios = compare.standard_scenarios("te-IN", "inbound")[:3]
    bad = CatalogueModel(
        model_id="bad-model",
        label="Bad",
        call_capable=True,
        plan_allows=True,
        surcharge="premium",
        console_latency_ms=800,
    )
    result = await compare._run_model(
        bad,
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        ref="ag_1",
        scenarios=scenarios,
        engine=chat,
        models=models,  # type: ignore[arg-type]
        judge=False,
        language="te-IN",
    )
    # Switched at the start, and again after the sweep moved it.
    assert models.switches.count("bad-model") >= 2
    assert result.conversations == 3
    assert result.hard_failed >= 1
    assert result.problems["brackets"] >= 1
    table = compare._table([result])
    assert "| Bad | Premium band ₹2.50/min | ~800 ms |" in table


def test_the_run_refuses_without_the_no_calls_promise(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        compare.main(["run", "--tenant", str(uuid.uuid4()), "--agent", str(uuid.uuid4())])
    assert "--agent-takes-no-calls" in capsys.readouterr().err
