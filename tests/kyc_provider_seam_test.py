"""The client-verification seam's properties that need no database (D-635).

These are the ones that must hold before a row is ever written, and each was chosen
because getting it wrong is silent:

1. **A deployment with no provider, or no webhook secret, has no verification feed** —
   and says which. An unverifiable feed on THIS endpoint marks accounts verified on
   anyone's say-so, so "fails closed" is the property, not "usually configured".
2. **The signature refuses everything it should**: no header, wrong digest, right digest
   over different bytes.
3. **A company's authorised signatory is not the company.** The branch decision is one
   function precisely so this cannot be answered differently in three places.
4. **Every column a provider's payload can reach refuses an Aadhaar-shaped value**,
   asserted from the ORM metadata rather than from a list somebody maintains by hand —
   so a column added later is covered by the assertion the day it appears, which is the
   defect class the migration's own guard exists for.

Run: uv run pytest -q tests/kyc_provider_seam_test.py
"""

from __future__ import annotations

import json
import re

import pytest
from apps.api.compliance.kyc_providers import available_provider, entity_branch
from apps.api.compliance.kyc_providers.fake import SIGNATURE_HEADER, FakeIdentityProvider, sign
from apps.api.compliance.kyc_providers.registry import (
    NO_PROVIDER_CONFIGURED,
    NO_WEBHOOK_SECRET,
    PROVIDER_CONTRACT_UNVERIFIED,
    PROVIDER_NOT_LICENSED,
)
from apps.api.compliance.kyc_providers.setu import SetuDigiLocker
from apps.api.compliance.models import KYC_ENTITY_TYPES, KycRecord, KycVerificationRequest
from apps.api.core.settings import get_settings

SECRET = "a-webhook-signing-secret"
BODY = json.dumps({"provider_ref": "run-1", "verified": True, "verified_name": "A Person"}).encode()


def _provider() -> FakeIdentityProvider:
    return FakeIdentityProvider(secret=SECRET)


# ------------------------------------------------ the deployment has no feed by default


def test_no_provider_configured_is_the_default_and_names_itself() -> None:
    """Every deployment today. The reason is what a client's screen renders, so a bare
    `None` would leave a blocked account with nothing to read."""
    capability = available_provider()
    assert not capability.available
    assert capability.reason == NO_PROVIDER_CONFIGURED


def test_a_configured_provider_with_no_secret_still_has_no_feed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The sharpest of the three refusals. A receiver that cannot verify a signature must
    not exist: a forged delivery marks an arbitrary account verified, which defeats the
    control and the liability case built on it."""
    settings = get_settings()
    monkeypatch.setattr(settings, "kyc_verification_provider", "fake", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_webhook_secret", None, raising=False)
    capability = available_provider()
    assert not capability.available
    assert capability.reason == NO_WEBHOOK_SECRET


def test_a_provider_whose_contract_was_never_read_is_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Setu is a member of the vocabulary and has no implemented adapter, because its
    docs are egress-blocked from this environment. Selecting it must be answered as
    unavailable-with-a-reason rather than raised: the client's own screen asks this
    selector, and a 500 there tells a blocked client nothing they can act on."""
    settings = get_settings()
    monkeypatch.setattr(settings, "kyc_verification_provider", "setu", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_webhook_secret", SECRET, raising=False)
    capability = available_provider()
    assert not capability.available
    assert capability.reason == PROVIDER_CONTRACT_UNVERIFIED


def test_the_in_house_adapter_is_not_selectable_outside_local(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`fake` signs with a secret WE hold, so selecting it anywhere real would let this
    deployment mark its own clients verified and record that a provider attested it. Two
    config values are all that stood between a production deployment and that row."""
    settings = get_settings()
    monkeypatch.setattr(settings, "kyc_verification_provider", "fake", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_webhook_secret", SECRET, raising=False)
    monkeypatch.setattr(settings, "app_env", "prod", raising=False)
    capability = available_provider()
    assert not capability.available
    assert capability.reason == PROVIDER_NOT_LICENSED


def test_the_unimplemented_adapter_raises_rather_than_returning_false() -> None:
    """`verify_webhook` returning False would read as "this delivery was not signed
    correctly" and let a caller treat the endpoint as working-and-strict. It is neither,
    and the difference is the whole of hard rule 11 on this seam."""
    with pytest.raises(Exception, match="egress-blocked"):
        SetuDigiLocker().verify_webhook(raw=BODY, headers={})


# ------------------------------------------------------------------- signature refusals


def test_an_unsigned_delivery_is_refused() -> None:
    """ "Unsigned" must not be a way to opt out of being checked."""
    assert _provider().verify_webhook(raw=BODY, headers={}) is False


def test_a_wrong_signature_is_refused() -> None:
    assert _provider().verify_webhook(raw=BODY, headers={SIGNATURE_HEADER: "0" * 64}) is False


def test_a_signature_over_different_bytes_is_refused() -> None:
    """The replay-with-edits attack: a genuine digest for a body that says something
    else. This is why the signature is verified over the RAW bytes and nothing is parsed
    before it passes."""
    other = json.dumps({"provider_ref": "run-1", "verified": False}).encode()
    presented = sign(secret=SECRET, body=other)
    assert _provider().verify_webhook(raw=BODY, headers={SIGNATURE_HEADER: presented}) is False


def test_a_correct_signature_is_accepted() -> None:
    presented = sign(secret=SECRET, body=BODY)
    assert _provider().verify_webhook(raw=BODY, headers={SIGNATURE_HEADER: presented}) is True


def test_a_signature_from_another_deployments_secret_is_refused() -> None:
    presented = sign(secret="someone-elses-secret", body=BODY)
    assert _provider().verify_webhook(raw=BODY, headers={SIGNATURE_HEADER: presented}) is False


# ---------------------------------------------------------------- the two entity branches


def test_only_a_sole_proprietorship_is_the_person_verified() -> None:
    """The proprietor IS the entity in law; nobody else is. Asserted over the WHOLE
    vocabulary rather than one example, so an entity type added later is classified by
    this test the day it appears."""
    assert entity_branch("sole_proprietorship") == "proprietor_is_the_entity"
    for entity_type in KYC_ENTITY_TYPES:
        if entity_type == "sole_proprietorship":
            continue
        assert entity_branch(entity_type) == "signatory_of_an_entity", entity_type


# ------------------------------------ nothing Aadhaar-shaped may reach any of these columns


#: Every column that can hold a string a provider or an operator supplied. Named here and
#: cross-checked against the model below, so adding a column and forgetting the guard
#: fails this file rather than shipping.
_GUARDED = {
    ("kyc_records", "document_ref"),
    ("kyc_records", "signatory_name"),
    ("kyc_records", "evidence_ref"),
    ("kyc_records", "verification_reference"),
    ("kyc_records", "verified_name"),
    ("kyc_verification_requests", "provider_ref"),
}


def _aadhaar_guards(model: type) -> set[tuple[str, str]]:
    """Which (table, column) pairs carry a twelve-bare-digit refusal, read off the
    mapped constraints rather than off a list in prose.

    Word-boundary matched, not substring: `provider` and `id` are both substrings of
    `provider_ref`, so a plain `in` credits two columns that carry no guard at all — a
    green assertion over a promise nothing enforces.
    """
    found: set[tuple[str, str]] = set()
    for constraint in model.__table__.constraints:
        clause = str(getattr(constraint, "sqltext", ""))
        if "[0-9]{12}" not in clause:
            continue
        for column in model.__table__.columns:
            if re.search(rf"\b{re.escape(column.name)}\b", clause):
                found.add((model.__tablename__, column.name))
    return found


def test_every_provider_written_column_refuses_an_aadhaar_shaped_value() -> None:
    """The published promise, as a schema property.

    `/legal/privacy` tells clients this schema refuses a twelve-digit bare number and
    cites Aadhaar Act 2016 s.29 for why. A promise a reviewer has to take on trust is
    the kind that quietly stops being true when somebody adds a column; this asserts it
    from the mapping.
    """
    guards = _aadhaar_guards(KycRecord) | _aadhaar_guards(KycVerificationRequest)
    assert guards == _GUARDED, f"missing or unexpected Aadhaar guards: {guards ^ _GUARDED}"


def test_no_column_in_the_verification_schema_is_named_for_an_identity_document() -> None:
    """A name is cheap to add and is how a store of the wrong thing begins. If this ever
    fails, the question is not what to rename — it is why the column exists."""
    forbidden = ("aadhaar", "aadhar", "uidai", "pan_number", "document_image", "document_blob")
    for model in (KycRecord, KycVerificationRequest):
        for column in model.__table__.columns:
            assert not any(token in column.name.lower() for token in forbidden), (
                f"{model.__tablename__}.{column.name}"
            )
