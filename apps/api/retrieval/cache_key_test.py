"""Normalisation, the PII gate and the key layout. No Redis: these are properties of the
KEY, and the key is where a tenancy leak or a logged phone number would come from.
"""

from __future__ import annotations

import uuid

import pytest
from calevate_shared.retrieval import RetrievalRequest

from apps.api.retrieval.cache import (
    KEY_PREFIX,
    TTL_S,
    QuestionNotCacheableError,
    cache_key,
    normalise,
)

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _request(
    question: str, *, tenant_id: uuid.UUID = TENANT_A, **kwargs: object
) -> RetrievalRequest:
    return RetrievalRequest(tenant_id=tenant_id, question=question, **kwargs)  # type: ignore[arg-type]


# --- normalisation: the same question typed differently is one question ----------------


@pytest.mark.parametrize(
    "question",
    [
        "What are your opening hours?",
        "what are your opening hours",
        "  WHAT ARE YOUR OPENING HOURS!! ",
        "What are your, opening hours ?",
    ],
)
def test_the_same_question_typed_differently_normalises_to_one_string(question: str) -> None:
    assert normalise(question) == "what are your opening hours"


def test_two_different_questions_do_not_normalise_together() -> None:
    """The reach of this tier is "the same question, typed differently" — deliberately NOT
    synonyms and NOT embeddings. A cache that thought these were one question would answer
    "do you take walk-ins" with the price list."""
    assert normalise("do you take walk ins") != normalise("what does it cost")


# --- the PII gate ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "call me back on 9876543210",
        "my email is someone@example.com",
    ],
)
def test_a_question_carrying_personal_data_is_refused_not_stripped(question: str) -> None:
    """Hard rule 6, at the one place it would otherwise be broken durably: a cache key is a
    string operators grep and dump, and a cached value is prose we read back.

    REFUSED, not stripped — `sanitize.assert_redacted`'s doctrine. A guard that silently
    repairs its input teaches its caller nothing and hides the defect that produced it.
    """
    with pytest.raises(QuestionNotCacheableError) as refused:
        normalise(question)
    assert "personal data" in refused.value.reason
    # The reason names KINDS, never the value.
    assert "9876543210" not in refused.value.reason
    assert "example.com" not in refused.value.reason


def test_a_long_digit_run_is_refused_on_its_own_ground() -> None:
    """An order or policy number is caller-specific: caching it is a key that can never be
    hit twice, and a durable string carrying somebody's reference."""
    with pytest.raises(QuestionNotCacheableError):
        normalise("what is the status of order 4471290")


def test_a_short_number_is_fine_because_it_is_a_price_not_a_person() -> None:
    assert normalise("is a root canal 8000 rupees") == "is a root canal 8000 rupees"


def test_a_question_of_only_punctuation_is_refused() -> None:
    with pytest.raises(QuestionNotCacheableError):
        normalise("???")


# --- the key layout -------------------------------------------------------------------


def test_the_tenant_is_the_first_element_and_is_not_hashed() -> None:
    """So a key is addressable only by a caller that already holds the tenant id, and so
    `invalidate_tenant` can scan one tenant without touching another's."""
    key = cache_key(_request("what are your hours"), epoch="1:3")
    assert key.startswith(f"{KEY_PREFIX}{TENANT_A}:")


def test_two_tenants_asking_the_identical_question_get_different_keys() -> None:
    """THE CROSS-TENANT PROOF AT THE KEY LEVEL (hard rule 1). The Redis half —
    that a write by A is not readable by B — is `tests/retrieval_tenancy_test.py`."""
    question = "what are your opening hours"
    assert cache_key(_request(question), epoch="1:3") != cache_key(
        _request(question, tenant_id=TENANT_B), epoch="1:3"
    )


def test_the_question_itself_never_appears_in_the_key() -> None:
    key = cache_key(_request("what are your opening hours"), epoch="1:3")
    assert "opening" not in key
    assert "hours" not in key


def test_the_epoch_changes_the_key() -> None:
    """THE INVALIDATION MECHANISM, asserted as the property it is: a knowledge change moves
    every question onto a new key, so nothing has to be deleted and no writer has to
    remember anything."""
    question = _request("what are your opening hours")
    assert cache_key(question, epoch="1:3") != cache_key(question, epoch="1:4")


def test_the_tier_and_k_change_the_key() -> None:
    """The same question at two tiers has two different right answers; one cached under the
    other's key is a wrong answer with no symptom."""
    base = _request("what is your refund policy")
    assert cache_key(base, epoch="1:3") != cache_key(
        _request("what is your refund policy", tier="t3"), epoch="1:3"
    )
    assert cache_key(base, epoch="1:3") != cache_key(
        _request("what is your refund policy", k=5), epoch="1:3"
    )


def test_the_agent_scope_changes_the_key() -> None:
    agent = uuid.uuid4()
    assert cache_key(_request("hours"), epoch="1:3") != cache_key(
        _request("hours", agent_id=agent), epoch="1:3"
    )


def test_the_ttl_is_a_ceiling_on_staleness_not_the_invalidation_mechanism() -> None:
    """A number, asserted so a later edit has to argue with this sentence: it bounds how
    long a bug in the epoch could serve a wrong answer. Fifteen minutes is short enough
    that such a bug is a bounded incident and long enough that a busy morning's repeated
    questions are hits."""
    assert TTL_S == 900
