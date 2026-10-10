"""How the console edits each platform setting: the control, derived from the field.

`GET /v1/ops/config` serves a `control` beside every setting so the console renders a switch
for a `bool`, a choice for a `Literal`, a bounded number with its unit, a picker fed live
from the thing a value names — never a bare text box for a value that has a shape.

The control is DERIVED from the `Settings` field the server validates against (its type,
its `ge`/`le`/`gt`, its `pattern`, its `max_length`), so a field whose type changes moves its
control with it. `ops/config_catalog.CONTROL_HINTS` adds only what the annotation cannot
carry: words for an option, a unit, the live source of an entity picker. The control GUIDES
input; the server's validation (`core/platform_config.validate_value`) stays the only check.

A plain string field becomes a text box only when it is listed in `FREE_TEXT`, with the
reason no better control exists. `tests/ops_config_controls_test.py` fails on any setting
that would otherwise fall through to free text unexplained.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from calevate_shared.config import Settings
from calevate_shared.engine import LLM_MODEL_NAMES

from apps.api.core.platform_config import ConfigField
from apps.api.engine.thinnest_customers import PLAN_CUSTOMER_CAPS
from apps.api.healer.playbooks import PLAYBOOKS
from apps.api.ops.config_catalog import CONTROL_HINTS, HIGH_RISK, ControlHint, OptionLabel

#: Every kind the console knows how to draw. A kind outside this set is a server defect the
#: test suite catches, never something the console has to guess about.
CONTROL_KINDS: Final[frozenset[str]] = frozenset(
    {
        "switch",
        "segmented",
        "select",
        "multi_select",
        "entity_picker",
        "number",
        "money_inr",
        "duration",
        "percent",
        "phone_in",
        "phone",
        "url",
        "email",
        "text",
    }
)

#: A closed choice with at most this many options is shown side by side; more is a list.
SEGMENTED_MAX: Final = 3

#: Strings with no closed set and no format beyond their pattern: identifiers another
#: system issues and no API here lists, or prose printed verbatim. Each says why.
FREE_TEXT: Final[dict[str, str]] = {
    "thinnest_in_call_default_model": (
        "a model id or console name from ThinnestAI's live list, checked when it is saved"
    ),
    "object_store_bucket": "a bucket name chosen when the storage was created",
    "cartesia_from_number_id": "an id from Cartesia's console; no API here lists them",
    "vobiz_callback_ips": "a list of network addresses Vobiz publishes",
    "azure_openai_resource": "the resource name chosen in the Azure portal",
    "azure_openai_deployment": "a deployment id chosen in the Azure portal",
    "azure_openai_deployments": "model=deployment pairs chosen in the Azure portal",
    "azure_openai_embedding_deployment": "a deployment id chosen in the Azure portal",
    "supermemory_embedding_model": "whatever model the self-hosted install was set up with",
    "razorpay_key_id": "a key id issued in the Razorpay dashboard",
    "gst_supplier_legal_name": "our legal name, printed verbatim",
    "gst_supplier_address": "our registered address, printed verbatim",
    "gst_supplier_gstin": "a registration number issued by the GST portal",
    "gst_supply_sac": "a code the accountant chooses",
    "kyc_verification_client_id": "an id issued in the KYC provider's dashboard",
    "google_oauth_client_id": "an id issued in the Google Cloud console",
    "google_cloud_project_number": "a number shown in the Google Cloud console",
    "zoho_oauth_client_id": "an id issued in the Zoho API console",
    "hubspot_oauth_client_id": "an id issued in the HubSpot developer account",
    "smtp_host": "the mail server's host name",
    "smtp_username": "the mail server's login",
    "whatsapp_template_hot_lead": "a template name registered with Meta",
    "whatsapp_template_locale": "the language tag a template was registered with",
    "whatsapp_template_healer_page": "a template name registered with Meta",
    "whatsapp_template_line_notice": "a template name registered with Meta",
    "whatsapp_template_line_restored": "a template name registered with Meta",
    "whatsapp_cloud_phone_number_id": "an id from the Meta console",
    "whatsapp_cloud_graph_version": "a Graph API version Meta publishes",
    "release_version": "a name the deploy chooses",
    "tls_origin_address": "a host and port",
}

_EMAIL_KEYS: Final = frozenset({"notifications_from", "notifications_reply_to"})
_INDIAN_MOBILE_PATTERN: Final = r"^\+91\d{10}$"
_CONSTRAINT_ATTRS: Final = ("ge", "gt", "le", "lt", "min_length", "max_length", "pattern")


@dataclass(frozen=True, slots=True)
class Choice:
    value: str
    label: str
    hint: str | None


@dataclass(frozen=True, slots=True)
class Control:
    kind: str
    unit: str | None
    #: Bounds as decimal strings, so money is never a float on its way to the browser.
    minimum: str | None
    #: True when the minimum itself is refused (`gt`), not only values below it.
    minimum_exclusive: bool
    maximum: str | None
    step: str | None
    min_length: int | None
    max_length: int | None
    #: The server's own pattern, so the console can say "not the right format" as you type.
    pattern: str | None
    placeholder: str | None
    help: str | None
    #: The live read an `entity_picker` is fed from (`config_catalog.ENTITY_SOURCES`).
    source: str | None
    multiple: bool
    #: "high" asks the operator to type the new value back; "standard" is one click.
    risk: str
    risk_reason: str | None


def _constraints(key: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for item in Settings.model_fields[key].metadata:
        # annotated_types' Ge/Gt/Le/Lt/MinLen/MaxLen each carry one attribute of this name,
        # and pydantic's general metadata carries `pattern`.
        for attr in _CONSTRAINT_ATTRS:
            value = getattr(item, attr, None)
            if value is not None:
                found[attr] = value
    return found


def _num(value: Any) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)), "f")


def _is_unit_ratio(bounds: dict[str, Any]) -> bool:
    return bounds.get("ge") == 0 and bounds.get("le") == 1


def _derived_kind(field: ConfigField, bounds: dict[str, Any]) -> str:
    if field.kind == "decimal":
        return "money_inr"
    if field.kind == "boolean":
        return "switch"
    if field.kind == "enum":
        return "segmented" if len(field.options) <= SEGMENTED_MAX else "select"
    if field.kind == "integer":
        return "number"
    if field.kind == "number":
        return "percent" if _is_unit_ratio(bounds) else "number"
    pattern = bounds.get("pattern", "")
    if pattern == _INDIAN_MOBILE_PATTERN:
        return "phone_in"
    if pattern.startswith(r"^\+"):
        return "phone"
    if pattern.startswith(("^https?://", "^https://")) or field.key.endswith(("_url", "_uri")):
        return "url"
    if field.key.endswith("email") or field.key in _EMAIL_KEYS:
        return "email"
    if field.key == "object_store_endpoint" or field.key.endswith("_endpoint"):
        return "url"
    return "text"


def control_for(field: ConfigField) -> Control:
    """The control for one managed setting."""
    hint = CONTROL_HINTS.get(field.key, ControlHint())
    bounds = _constraints(field.key)
    kind = hint.kind or _derived_kind(field, bounds)
    numeric = kind in {"number", "money_inr", "duration", "percent"}
    minimum = bounds.get("ge", bounds.get("gt"))
    return Control(
        kind=kind,
        unit=hint.unit,
        minimum=_num(minimum) if numeric else None,
        minimum_exclusive=numeric and "gt" in bounds,
        maximum=_num(bounds.get("le", bounds.get("lt"))) if numeric else None,
        step="0.01" if kind == "money_inr" else "1" if numeric else None,
        min_length=None if numeric else bounds.get("min_length"),
        max_length=None if numeric else bounds.get("max_length"),
        pattern=None if numeric else bounds.get("pattern"),
        placeholder=hint.placeholder,
        help=hint.help,
        source=hint.source,
        multiple=hint.multiple,
        risk="high" if field.key in HIGH_RISK else "standard",
        risk_reason=HIGH_RISK.get(field.key),
    )


def model_label(model: str) -> str:
    """`gpt-4.1-mini` → "GPT-4.1 mini", `gemini-2.5-flash-lite` → "Gemini 2.5 Flash Lite"."""
    if model.startswith("gpt-"):
        head, *rest = model.removeprefix("gpt-").split("-")
        return " ".join([f"GPT-{head}", *rest])
    if model.startswith("gemini-"):
        words = model.removeprefix("gemini-").split("-")
        return " ".join(["Gemini", *(w if w[:1].isdigit() else w.capitalize() for w in words)])
    return model


def _value_label(value: str) -> str:
    if value in LLM_MODEL_NAMES:
        return model_label(value)
    words = [word for word in re.split(r"[-_:]", value) if word]
    if not words:
        return value
    return " ".join([words[0][:1].upper() + words[0][1:], *words[1:]])


def _plan_hint(value: str) -> str | None:
    cap = PLAN_CUSTOMER_CAPS.get(value)
    return None if cap is None else f"Up to {cap:,} client workspaces."


def choices_for(field: ConfigField) -> list[Choice]:
    """What a choice control offers, each with the words an operator reads.

    For a closed field: exactly the validator's set, in the annotation's order. For a
    string field the code reads as a closed set: the catalogue's list. For the healer's
    paused playbooks: every playbook that may be paused, by its title.
    """
    hint = CONTROL_HINTS.get(field.key, ControlHint())
    labelled: dict[str, OptionLabel] = {option.value: option for option in hint.options}
    if field.key == "healer_paused_playbooks":
        return [Choice(p.key, p.title, None) for p in PLAYBOOKS if p.pausable]
    values = list(field.options) if field.options else [option.value for option in hint.options]
    out: list[Choice] = []
    for value in values:
        known = labelled.get(value)
        extra = _plan_hint(value) if field.key == "thinnest_customer_plan" else None
        out.append(
            Choice(
                value=value,
                label=known.label if known else _value_label(value),
                hint=(known.hint if known else None) or extra,
            )
        )
    return out


__all__ = [
    "CONTROL_KINDS",
    "FREE_TEXT",
    "SEGMENTED_MAX",
    "Choice",
    "Control",
    "choices_for",
    "control_for",
    "model_label",
]
