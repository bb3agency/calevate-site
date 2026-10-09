"""Every platform setting is edited with a control that fits it (D-704).

The founder's complaint was that every setting in the ops console was a free-text box, even
a yes/no, a choice of three, a bounded number, a price or a number we rent. The control is
now derived from the `Settings` field (`ops/config_controls.py`), and these tests state the
property over EVERY managed field, so the next setting added cannot fall back to a text box
without somebody writing down why.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from apps.api.billing.payments import PROVIDER as PAYMENT_PROVIDER
from apps.api.campaigns.provisioning import KNOWN_PROVIDERS
from apps.api.compliance.models import KYC_PROVIDERS
from apps.api.core import platform_config as pc
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.pipecat import PIPECAT_CAPABILITIES
from apps.api.engine.thinnest import BASE_URL
from apps.api.engine.thinnest_customers import ThinnestCustomers, set_thinnest_customers
from apps.api.engine.thinnest_workspace import remember_developer_workspace
from apps.api.healer.playbooks import PLAYBOOKS
from apps.api.ingest.meta import GRAPH_PROVIDER, RECORDED_PROVIDER
from apps.api.ops import config_catalog as catalog
from apps.api.ops import config_controls as controls
from apps.api.ops.config_routes import _out
from apps.api.ops.config_sources import read_thinnest_workspace
from apps.workers.sheets_sync import CLIENT_ACCOUNT_PROVIDER
from apps.workers.sheets_sync import CONSOLE_PROVIDER as SHEETS_CONSOLE
from apps.workers.whatsapp import CLOUD_API_PROVIDER
from apps.workers.whatsapp import CONSOLE_PROVIDER as WHATSAPP_CONSOLE
from calevate_shared.config import SELECTABLE_EMAIL_PROVIDERS

CHOICE_KINDS = {"segmented", "select", "multi_select"}


def _fields() -> dict[str, pc.ConfigField]:
    return {field.key: field for field in pc.describe(get_settings())}


def _control(key: str) -> controls.Control:
    return controls.control_for(_fields()[key])


# --- every setting has a sensible control ---------------------------------------------


def test_every_setting_has_a_known_control_kind() -> None:
    for field in _fields().values():
        assert controls.control_for(field).kind in controls.CONTROL_KINDS, field.key


def test_no_setting_is_free_text_without_a_stated_reason() -> None:
    """THE GUARD: a setting that would fall through to a text box fails here until it is
    given a better control or a line in `FREE_TEXT` saying why none fits."""
    fields = _fields()
    unexplained = [
        key
        for key, field in fields.items()
        if controls.control_for(field).kind == "text" and key not in controls.FREE_TEXT
    ]
    assert unexplained == [], "give these a control, or a FREE_TEXT reason"
    for key, reason in controls.FREE_TEXT.items():
        assert key in fields, f"{key} is no longer managed"
        assert controls.control_for(fields[key]).kind == "text", f"{key} has a better control"
        assert reason.strip(), key


def test_types_map_to_their_controls() -> None:
    fields = _fields()
    for key, field in fields.items():
        kind = controls.control_for(field).kind
        if field.kind == "boolean":
            assert kind == "switch", key
        if field.kind == "decimal":
            assert kind == "money_inr", key
        if field.kind == "enum":
            assert kind in {"segmented", "select"}, key


def test_every_choice_control_offers_labelled_choices() -> None:
    for key, field in _fields().items():
        if controls.control_for(field).kind not in CHOICE_KINDS:
            continue
        choices = controls.choices_for(field)
        assert choices, f"{key} is a choice with nothing to choose"
        for choice in choices:
            assert choice.label.strip(), (key, choice.value)
            assert "_" not in choice.label, (key, choice.label)


def test_a_closed_field_offers_exactly_what_its_validator_accepts() -> None:
    for key, field in _fields().items():
        if field.options:
            assert [c.value for c in controls.choices_for(field)] == list(field.options), key


# --- the catalogue's hints are about real settings and real values ---------------------


def test_every_hint_names_a_managed_setting() -> None:
    managed = set(pc.managed_fields())
    assert set(catalog.CONTROL_HINTS) - managed == set()
    assert set(catalog.HIGH_RISK) - managed == set()


def test_labels_for_a_closed_field_name_values_its_validator_accepts() -> None:
    fields = _fields()
    for key, hint in catalog.CONTROL_HINTS.items():
        if fields[key].options:
            for option in hint.options:
                assert option.value in fields[key].options, (key, option.value)


@pytest.mark.parametrize(
    ("key", "readers"),
    [
        ("email_provider", set(SELECTABLE_EMAIL_PROVIDERS)),
        ("payment_provider", {PAYMENT_PROVIDER}),
        ("number_provider", set(KNOWN_PROVIDERS)),
        ("whatsapp_provider", {CLOUD_API_PROVIDER, WHATSAPP_CONSOLE}),
        ("google_sheets_provider", {CLIENT_ACCOUNT_PROVIDER, SHEETS_CONSOLE}),
        ("meta_lead_retriever", {GRAPH_PROVIDER, RECORDED_PROVIDER}),
        ("kyc_verification_provider", set(KYC_PROVIDERS)),
    ],
)
def test_a_provider_choice_offers_only_values_its_reader_acts_on(
    key: str, readers: set[str]
) -> None:
    offered = {choice.value for choice in controls.choices_for(_fields()[key])}
    assert offered and offered <= readers, (key, offered - readers)
    assert _control(key).kind == "select"


def test_entity_pickers_name_a_live_source() -> None:
    for key, field in _fields().items():
        control = controls.control_for(field)
        if control.kind == "entity_picker":
            assert control.source in catalog.ENTITY_SOURCES, key
    assert _control("trial_caller_number").source == "trial_numbers"
    assert _control("thinnest_developer_workspace_id").source == "thinnest_workspace"
    tenants = _control("retrieval_shadow_tenant_ids")
    assert tenants.source == "tenants" and tenants.multiple


def test_paused_playbooks_are_chosen_from_the_pausable_playbooks() -> None:
    field = _fields()["healer_paused_playbooks"]
    assert _control("healer_paused_playbooks").kind == "multi_select"
    assert [c.value for c in controls.choices_for(field)] == [
        p.key for p in PLAYBOOKS if p.pausable
    ]


# --- bounds, units and risk --------------------------------------------------------------


def test_bounds_come_from_the_field() -> None:
    seconds = _control("trial_call_max_seconds")
    assert (seconds.kind, seconds.unit, seconds.minimum, seconds.maximum) == (
        "duration",
        "seconds",
        "60",
        "1200",
    )
    rate = _control("usd_inr_rate")
    assert rate.kind == "money_inr" and rate.minimum == "0" and rate.minimum_exclusive
    assert rate.maximum == "1000" and rate.step == "0.01"
    assert _control("carrier_cps").minimum_exclusive is False


def test_a_share_from_zero_to_one_is_a_percentage() -> None:
    assert _control("inbound_reserve_ratio").kind == "percent"
    assert _control("otel_traces_sample_ratio").kind == "percent"


def test_formats_are_carried_for_checking_as_you_type() -> None:
    assert _control("healer_founder_whatsapp").kind == "phone"
    assert _control("webhook_base_url").kind == "url"
    assert _control("webhook_base_url").pattern == r"^https?://[^\s]+$"
    assert _control("alerts_email").kind == "email"
    assert _control("thinnest_clear_voice_band").kind == "segmented"


def test_only_the_dangerous_settings_ask_for_a_typed_confirmation() -> None:
    assert _control("engine").risk == "high"
    assert _control("engine").risk_reason
    assert _control("self_serve_inr_per_min").risk == "high"
    assert _control("trial_daily_call_cap").risk == "standard"
    assert _control("trial_daily_call_cap").risk_reason is None


def test_model_options_read_as_names() -> None:
    assert controls.model_label("gpt-4.1-mini") == "GPT-4.1 mini"
    assert controls.model_label("gemini-2.5-flash-lite") == "Gemini 2.5 Flash Lite"
    plan = next(
        c for c in controls.choices_for(_fields()["thinnest_customer_plan"]) if c.value == "pro"
    )
    assert plan.label == "Pro" and plan.hint == "Up to 100 client workspaces."


def test_the_route_serves_the_control_and_the_option_labels() -> None:
    out = _out(_fields()["engine"], ("pipecat", PIPECAT_CAPABILITIES))
    assert out.control.kind == "select"
    assert out.control.risk == "high"
    assert {option.value: option.label for option in out.options}["thinnest"] == "ThinnestAI"


# --- the workspace is read, not typed --------------------------------------------------


async def test_the_developer_workspace_is_read_from_thinnest() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "org_calevate", "name": "Calevate"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE_URL)
    set_thinnest_customers(ThinnestCustomers(api_key="ta_live_test", client=client))
    try:
        principal: Any = None
        out = await read_thinnest_workspace(principal)
    finally:
        set_thinnest_customers(None)
        remember_developer_workspace(None)
    assert (out.workspace_id, out.name) == ("org_calevate", "Calevate")
    assert seen[0].url.path.endswith("/workspace")
    assert "Thinnest-Workspace" not in seen[0].headers


async def test_an_unreachable_thinnest_is_a_problem_not_an_empty_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE_URL)
    set_thinnest_customers(ThinnestCustomers(api_key="ta_live_test", client=client))
    try:
        principal: Any = None
        with pytest.raises(ProblemError) as refused:
            await read_thinnest_workspace(principal)
    finally:
        set_thinnest_customers(None)
    assert refused.value.status >= 500


# --- the trial number is chosen from what ThinnestAI holds ----------------------------


async def test_trial_number_choices_carry_their_label_and_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.campaigns import engine_numbers as numbers_module
    from apps.api.ops import trial_number
    from calevate_shared.engine import ProvisionedNumber

    async def listed(workspace: str | None) -> list[ProvisionedNumber]:
        return [
            ProvisionedNumber(
                e164="+918041234567",
                engine_number_ref="918041234567",
                engine_owned=True,
                label="Front desk",
                answering_agent_ref="ag_front",
                calling_agent_ref="ag_unknown",
            ),
            ProvisionedNumber(e164="+918045678902", engine_owned=True),
        ]

    async def recorded() -> set[str]:
        return {"918045678902"}

    async def names(refs: set[str]) -> dict[str, str]:
        assert refs == {"ag_front", "ag_unknown"}
        return {"ag_front": "Reception"}

    monkeypatch.setattr(numbers_module, "vendor_numbers", listed)
    monkeypatch.setattr(trial_number, "_recorded_digits", recorded)
    monkeypatch.setattr(trial_number, "_agent_names", names)

    (only,) = await trial_number.trial_number_candidates(with_names=True)
    assert (only.e164, only.label, only.answering_agent, only.calling_agent) == (
        "+918041234567",
        "Front desk",
        "Reception",
        None,
    )
    assert only.answered and only.rented
