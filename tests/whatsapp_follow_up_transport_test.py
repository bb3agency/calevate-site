"""The leads screen's WhatsApp follow-up when Meta does not answer.

A connect failure, a read timeout or the send deadline used to escape `swipe._send` as a
raw exception: a 500 on the leads screen with no timeline row, and in a Follow-up step a
failed idempotency claim whose retry could send the message twice. It is now an answer.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from apps.api.actions import execution
from apps.api.crm import swipe


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), TimeoutError()],
    ids=["connect", "read_timeout", "deadline"],
)
async def test_no_answer_from_meta_is_none_not_a_raise(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    async def _raise(request: Any, *, client: httpx.AsyncClient) -> httpx.Response:
        raise failure

    monkeypatch.setattr(execution, "send_prepared", _raise)
    assert await swipe._send(object()) is None


async def test_an_unanswered_send_is_a_failed_answer_that_says_check_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = swipe.WhatsAppTemplateChoiceOut(
        id=uuid4(),
        name="order_ready",
        language="en",
        category="UTILITY",
        body="Hello {{1}}",
        variables=[{"label": "Name", "example": "Ravi"}],
    )
    account = type(
        "Account", (), {"id": uuid4(), "phone_number_id": "123", "credential_id": uuid4()}
    )()

    async def _account(session: Any) -> Any:
        return account

    async def _approved(session: Any, account_id: Any) -> list[swipe.WhatsAppTemplateChoiceOut]:
        return [template]

    async def _gate(session: Any, **kwargs: Any) -> str:
        return "+919000000001"

    async def _token(session: Any, **kwargs: Any) -> str:
        return "token"

    async def _no_answer(request: Any) -> None:
        return None

    monkeypatch.setattr(swipe, "connected_account", _account)
    monkeypatch.setattr(swipe, "_approved", _approved)
    monkeypatch.setattr(swipe, "_gate", _gate)
    monkeypatch.setattr(swipe.accounts, "account_token", _token)
    monkeypatch.setattr(swipe, "_send", _no_answer)

    out, name, message_id = await swipe.send_whatsapp_follow_up(
        object(),  # type: ignore[arg-type]
        tenant_id=uuid4(),
        lead_id=uuid4(),
        payload=swipe.WhatsAppSendIn(template_id=template.id, values=["Ravi"]),
    )
    assert out.status == "failed"
    assert out.rule == swipe.UNANSWERED_RULE
    assert out.reason is not None and "again" in out.reason
    assert name == "order_ready"
    assert message_id is None
