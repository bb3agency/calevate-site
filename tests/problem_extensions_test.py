"""Typed problem+json extension members (RFC 9457 §3.2): the one way a problem carries data
beside its sentence (`core.errors.ProblemExtension`), published in the OpenAPI document so
the generated client types it."""

from __future__ import annotations

import uuid
from typing import ClassVar

import pytest
from apps.api.agents.company_training import CompanyTrainingTooLong
from apps.api.core.errors import (
    PROBLEM_EXTENSIONS,
    ProblemError,
    ProblemExtension,
    problem_responses,
)
from apps.api.main import app


def test_members_sit_at_the_top_level_and_absent_ones_are_left_out() -> None:
    campaign = uuid.uuid4()
    body = ProblemError.business_rule(
        "company_training_too_long",
        "Too long.",
        extensions=CompanyTrainingTooLong(campaign_id=campaign),
    ).as_problem()
    assert body["campaign_id"] == str(campaign)
    assert "inbound_line_id" not in body and "agent_id" not in body
    assert body["type"].endswith("/company_training_too_long")
    assert body["remediation"]


def test_an_extension_is_refused_on_a_problem_it_does_not_extend() -> None:
    with pytest.raises(ValueError):
        ProblemError.business_rule("something_else", "No.", extensions=CompanyTrainingTooLong())
    with pytest.raises(ValueError):
        ProblemError.conflict(
            "company_training_too_long", "No.", extensions=CompanyTrainingTooLong()
        )


def test_an_extension_may_not_reuse_a_member_every_problem_has() -> None:
    with pytest.raises(TypeError):

        class _Shadow(ProblemExtension):
            code: ClassVar[str] = "w3p_shadow"
            status: ClassVar[int] = 422
            detail: str

    with pytest.raises(TypeError):

        class _Again(ProblemExtension):
            code: ClassVar[str] = "company_training_too_long"
            status: ClassVar[int] = 422
            other_id: str | None = None

    assert PROBLEM_EXTENSIONS["company_training_too_long"] is CompanyTrainingTooLong


def test_a_route_declares_each_problem_under_its_own_status() -> None:
    from apps.api.follow_ups.service import FollowUpChanged, FollowUpInvalid

    declared = problem_responses(FollowUpInvalid, FollowUpChanged, CompanyTrainingTooLong)
    assert set(declared) == {409, 422}
    refs = declared[422]["content"]["application/problem+json"]["schema"]["oneOf"]
    assert refs == [
        {"$ref": "#/components/schemas/FollowUpInvalid"},
        {"$ref": "#/components/schemas/CompanyTrainingTooLong"},
    ]


def test_the_openapi_document_types_the_refusal_for_the_client() -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    assert "ProblemBody" in schemas
    too_long = schemas["CompanyTrainingTooLong"]
    assert too_long["allOf"][0] == {"$ref": "#/components/schemas/ProblemBody"}
    assert set(too_long["allOf"][1]["properties"]) == {
        "agent_id",
        "inbound_line_id",
        "campaign_id",
    }
    put = spec["paths"]["/v1/company-training/training"]["put"]
    refs = put["responses"]["422"]["content"]["application/problem+json"]["schema"]["oneOf"]
    assert {"$ref": "#/components/schemas/CompanyTrainingTooLong"} in refs
