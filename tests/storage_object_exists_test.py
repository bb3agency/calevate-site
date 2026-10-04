"""`storage.object_exists` keeps "not there" apart from "could not ask" (D-670).

The one-day expiry deletes the carrier's copy of a recording only after this HEAD says ours
is present, so a store outage must raise rather than read as either answer.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.workers import storage
from botocore.exceptions import ClientError, EndpointConnectionError


class _Head:
    def __init__(self, outcome: Exception | None) -> None:
        self.outcome = outcome
        self.asked: list[dict[str, Any]] = []

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.asked.append(kwargs)
        if self.outcome is not None:
            raise self.outcome
        return {"ContentLength": 1}


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "HeadObject")


@pytest.fixture
def head(monkeypatch: pytest.MonkeyPatch) -> Any:
    def install(outcome: Exception | None) -> _Head:
        fake = _Head(outcome)
        monkeypatch.setattr(storage, "_client", lambda: fake)
        return fake

    return install


async def test_a_present_object_is_true_and_asked_by_key(head: Any) -> None:
    fake = head(None)
    assert await storage.object_exists("recordings/t/c.wav") is True
    assert fake.asked[0]["Key"] == "recordings/t/c.wav"


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
async def test_an_absent_object_is_false(head: Any, code: str) -> None:
    head(_client_error(code))
    assert await storage.object_exists("recordings/t/c.wav") is False


@pytest.mark.parametrize(
    "outcome",
    [_client_error("403"), _client_error("SlowDown"), EndpointConnectionError(endpoint_url="x")],
)
async def test_a_store_that_does_not_answer_raises(head: Any, outcome: Exception) -> None:
    head(outcome)
    with pytest.raises(storage.StorageUnavailableError):
        await storage.object_exists("recordings/t/c.wav")
