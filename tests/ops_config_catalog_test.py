"""The configuration screen's option lists, sections and labels.

The defect this file exists for: `platform_llm_model` and the three `llm_tier_*_model`
settings are typed `LlmModelName`, a union of three `Literal`s, and the console offered
only the first branch's two Azure models. The platform's own default
(`gemini-2.5-flash-lite`) was not among the options, so it could not be chosen and the
dialog pre-selected a value that was not the current one. Every test below states a
property over EVERY managed field, so the next closed type with the same shape is caught
without anyone remembering to list it.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from apps.api.agents.llm_models import unofferable_reason
from apps.api.core import platform_config as pc
from apps.api.core.settings import ENV_ONLY_DISPLAY, get_settings
from apps.api.engine.pipecat import PIPECAT_CAPABILITIES
from apps.api.engine.thinnest import THINNEST_CAPABILITIES
from apps.api.ops import config_catalog as catalog
from apps.api.ops.config_routes import _options, _out, _sections
from calevate_shared.config import Settings
from calevate_shared.engine import (
    AZURE_OPENAI_MODELS,
    LLM_MODEL_NAMES,
    PLATFORM_DEFAULT_LLM_MODEL,
)
from pydantic import ValidationError

MODEL_FIELDS = (
    "platform_llm_model",
    "llm_tier_standard_model",
    "llm_tier_plus_model",
    "llm_tier_pro_model",
)


def _fields() -> list[pc.ConfigField]:
    return pc.describe(get_settings())


def _closed_fields() -> list[pc.ConfigField]:
    return [field for field in _fields() if field.options]


def _admits(field: pc.ConfigField, value: Any) -> bool:
    return value in field.options or (value is None and field.nullable)


# --- the option list IS the validator's set ----------------------------------------


@pytest.mark.parametrize("key", MODEL_FIELDS)
def test_model_settings_offer_every_model_the_validator_accepts(key: str) -> None:
    field = next(f for f in _fields() if f.key == key)
    assert field.kind == "enum"
    assert set(field.options) == LLM_MODEL_NAMES
    assert PLATFORM_DEFAULT_LLM_MODEL in field.options
    assert any(option.startswith("gemini-") for option in field.options)


def test_the_azure_model_setting_offers_exactly_the_azure_models() -> None:
    field = next(f for f in _fields() if f.key == "azure_openai_model")
    assert set(field.options) == AZURE_OPENAI_MODELS


def test_every_option_validates_and_nothing_outside_the_options_does() -> None:
    closed = _closed_fields()
    assert closed, "no closed field found — the premise of this test has moved"
    for field in closed:
        for option in field.options:
            assert pc.validate_value(field.key, option) == option, (field.key, option)
        with pytest.raises(ValidationError):
            pc.validate_value(field.key, "definitely-not-an-option")


def test_options_are_derived_from_the_annotation_not_a_schema_branch() -> None:
    """The union of `Literal`s and a plain `Literal` both enumerate in full."""
    members = pc._literal_members(Settings.model_fields["llm_tier_standard_model"].annotation)
    assert members is not None and set(members) == LLM_MODEL_NAMES
    assert pc._literal_members(Settings.model_fields["smtp_host"].annotation) is None


def test_every_closed_field_offers_its_default_and_its_current_value() -> None:
    """THE GUARD for this class of defect: a select must contain what it is showing."""
    defaults = Settings.model_fields
    for field in _closed_fields():
        info = defaults[field.key]
        if not info.is_required():
            default = info.get_default(call_default_factory=True)
            assert _admits(field, default), f"{field.key}: default {default!r} is not an option"
        assert _admits(field, field.value), f"{field.key}: current {field.value!r} not an option"


def test_a_stored_override_is_still_among_the_options() -> None:
    """The current value after a write, through the same projection the write route uses."""
    for field in _closed_fields():
        for option in field.options:
            settings, _ = pc.project({field.key: pc.typed_value(field.key, option)})
            projected = next(f for f in pc.describe(settings) if f.key == field.key)
            assert projected.value in projected.options, (field.key, option)


def test_nullable_is_read_from_the_annotation() -> None:
    by_key = {field.key: field for field in _fields()}
    assert by_key["alerts_email"].nullable is True
    assert by_key["llm_tier_standard_model"].nullable is False
    assert by_key["engine"].nullable is False


# --- model options carry the offer seam's verdict ------------------------------------


def test_model_options_carry_the_offer_seams_reason_verbatim() -> None:
    field = next(f for f in _fields() if f.key == "llm_tier_standard_model")
    options = _options(field)
    assert [option.value for option in options] == list(field.options)
    for option in options:
        assert option.provider in {"azure_openai", "openai", "google"}
        assert option.unavailable_reason == unofferable_reason(option.value)
    # A model this repository withholds on merit is never reported as offerable.
    withheld = next(o for o in options if o.value.startswith("gemini-3"))
    assert withheld.unavailable_reason is not None


def test_non_model_options_carry_no_offer_state() -> None:
    field = next(f for f in _fields() if f.key == "engine")
    for option in _options(field):
        assert option.provider is None
        assert option.unavailable_reason is None


# --- every field has a section ------------------------------------------------------


def test_every_managed_field_has_a_catalogue_entry_and_no_entry_is_stale() -> None:
    managed = set(pc.managed_fields())
    assert managed - set(catalog.FIELD_META) == set(), "add these to ops/config_catalog"
    assert set(catalog.FIELD_META) - managed == set(), "these are no longer managed"


def test_every_entry_points_at_a_declared_section_and_subsection() -> None:
    declared = {section.id: {sub.id for sub in section.subsections} for section in catalog.SECTIONS}
    for key, meta in catalog.FIELD_META.items():
        assert meta.section in declared, key
        assert meta.subsection in declared[meta.section], key
        assert meta.section != catalog.OTHER_SECTION, f"{key} is filed under Other"


def test_served_sections_cover_every_field_and_skip_empty_ones() -> None:
    engine = ("pipecat", PIPECAT_CAPABILITIES)
    fields = [_out(field, engine) for field in _fields()]
    sections = _sections(fields)
    served = {(s.id, sub.id) for s in sections for sub in s.subsections}
    for field in fields:
        assert (field.section, field.subsection) in served, field.key
    # Nothing is unfiled today, so "Other" is not offered.
    assert catalog.OTHER_SECTION not in {s.id for s in sections}
    ids = [s.id for s in sections]
    assert ids == [s.id for s in catalog.SECTIONS if s.id in ids], "catalogue order is kept"


def test_an_unknown_key_lands_in_other_with_a_readable_label() -> None:
    meta = catalog.meta_for("brand_new_llm_api_url")
    assert meta.section == catalog.OTHER_SECTION
    assert meta.label == "Brand new LLM API URL"


# --- labels -------------------------------------------------------------------------

_ACRONYMS = {spelling.lower(): spelling for spelling in catalog.FIXED_SPELLINGS}


def _miscased(label: str) -> list[str]:
    words = re.findall(r"[A-Za-z]+", label)
    return [w for w in words if w.lower() in _ACRONYMS and w != _ACRONYMS[w.lower()]]


def test_labels_spell_acronyms_correctly() -> None:
    for key, meta in catalog.FIELD_META.items():
        assert _miscased(meta.label) == [], (key, meta.label)
    for key in ENV_ONLY_DISPLAY:
        assert _miscased(catalog.meta_for(key).label) == [], key
    assert catalog.humanise("llm_tier_standard_model") == "LLM tier standard model"
    assert catalog.humanise("platform_kek_retired") == "Platform KEK retired"


def test_descriptions_are_one_plain_line() -> None:
    for key, meta in catalog.FIELD_META.items():
        assert meta.label.strip() and meta.description.strip(), key
        assert "\n" not in meta.description, key
        assert meta.description.endswith("."), key
        assert len(meta.description) <= 160, (key, len(meta.description))


# --- engine scope -------------------------------------------------------------------


def test_engine_scoped_settings_follow_the_engine_in_force() -> None:
    by_key = {field.key: field for field in _fields()}
    thinnest_only = by_key["thinnest_max_concurrent_calls"]
    runtime_only = by_key["carrier_cps"]
    unscoped = by_key["inbound_reserve_ratio"]

    on_pipecat = ("pipecat", PIPECAT_CAPABILITIES)
    assert _out(thinnest_only, on_pipecat).used_by_current_engine is False
    assert _out(runtime_only, on_pipecat).used_by_current_engine is True

    on_thinnest = ("thinnest", THINNEST_CAPABILITIES)
    assert _out(thinnest_only, on_thinnest).used_by_current_engine is True
    assert _out(runtime_only, on_thinnest).used_by_current_engine is False
    assert _out(by_key["sarvam_stt_model"], on_thinnest).used_by_current_engine is False

    for engine in (on_pipecat, on_thinnest, ("pipecat", None)):
        assert _out(unscoped, engine).used_by_current_engine is True
    # Unreadable capabilities hide nothing.
    assert _out(thinnest_only, ("pipecat", None)).used_by_current_engine is True
    assert _out(thinnest_only, on_pipecat).engine_scope is not None
