"""Every model a route reads or answers with forbids unknown fields (BACKEND-PATTERNS §3).

An input model that ignores an unknown field turns a misspelt field into a silent no-op:
the request "succeeds" and nothing the caller meant was saved. A response model that
ignores one lets a dict carrying a column nobody chose to expose be built without a
complaint, which is the whitelist the redaction-exposure guardrail relies on.

`KNOWN_RESPONSE_OFFENDERS` is the set that predates this test. It only shrinks: a model
that starts forbidding extras must leave it, so the set cannot quietly keep a name that
no longer needs the exemption.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Any

from apps.api.core.rbac import iter_api_routes
from apps.api.main import app
from pydantic import BaseModel

KNOWN_RESPONSE_OFFENDERS: frozenset[str] = frozenset(
    {
        "apps.api.agents.routes.AgentLanguageOut",
        "apps.api.agents.routes.AgentLanguagesOut",
        "apps.api.crm.schemas.CallQualityOut",
        "apps.api.ops.alerts_service.AlertEpisode",
        "apps.api.ops.alerts_service.AlertReport",
        "apps.api.ops.reply_times.AgentReplyTimes",
        "apps.api.ops.reply_times.AgentTurnSplit",
        "apps.api.ops.reply_times.ClientReplyTimes",
        "apps.api.ops.reply_times.DayReplyTimes",
        "apps.api.ops.reply_times.ReplyTimeFigures",
        "apps.api.ops.reply_times.ReplyTimeReport",
        "apps.api.ops.reply_times.SettingReplyTimes",
        "apps.api.ops.reply_times.SlowCall",
        "apps.api.ops.reply_times.TierReplyTimes",
        "apps.api.ops.reply_times.TurnSplit",
        "apps.api.ops.routes.KbOrphanReportOut",
        "apps.api.ops.routes.KbOrphanRowOut",
    }
)

#: Models we own. A framework or library model is not ours to configure.
_OURS = ("apps.", "calevate_shared")


def _models(annotation: Any, seen: set[type[BaseModel]]) -> Iterator[type[BaseModel]]:
    """Every model reachable from `annotation`, through generics and nested fields."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return
        seen.add(annotation)
        yield annotation
        for field in annotation.model_fields.values():
            yield from _models(field.annotation, seen)
    for arg in getattr(annotation, "__args__", None) or ():
        yield from _models(arg, seen)


def _name(model: type[BaseModel]) -> str:
    return f"{model.__module__}.{model.__qualname__}"


def _ignores_extras(model: type[BaseModel]) -> bool:
    return model.__module__.startswith(_OURS) and model.model_config.get("extra") != "forbid"


def _offenders() -> tuple[set[str], set[str]]:
    inputs: set[str] = set()
    responses: set[str] = set()
    for route in iter_api_routes(app):
        for parameter in inspect.signature(route.endpoint).parameters.values():
            found = _models(parameter.annotation, set())
            inputs.update(_name(m) for m in found if _ignores_extras(m))
        responses.update(
            _name(m) for m in _models(route.response_model, set()) if _ignores_extras(m)
        )
    return inputs, responses


def test_every_route_input_model_forbids_unknown_fields() -> None:
    inputs, _ = _offenders()
    assert not inputs, f"input models that accept unknown fields: {sorted(inputs)}"


def test_no_new_response_model_ignores_unknown_fields() -> None:
    _, responses = _offenders()
    new = responses - KNOWN_RESPONSE_OFFENDERS
    assert not new, f"add model_config = ConfigDict(extra='forbid') to: {sorted(new)}"


def test_the_known_offender_set_only_shrinks() -> None:
    _, responses = _offenders()
    fixed = KNOWN_RESPONSE_OFFENDERS - responses
    assert not fixed, f"these now forbid extras; remove them from the set: {sorted(fixed)}"


def test_the_walk_sees_a_model_that_ignores_extras() -> None:
    """The guard is only worth its pass if it can see an offender through a list and a
    nested field — the shapes route models actually take."""

    class Inner(BaseModel):
        value: int

    class Outer(BaseModel):
        inner: list[Inner]

    Inner.__module__ = Outer.__module__ = "apps.example"
    found = {m.__qualname__ for m in _models(list[Outer], set()) if _ignores_extras(m)}
    assert {"test_the_walk_sees_a_model_that_ignores_extras.<locals>.Inner"} <= found
