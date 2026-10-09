"""Copy and starting data meant for any business do not assume a clinic.

A client that is not a clinic (a shop, a travel agent, a coaching centre) must not be handed
clinic CRM columns or read clinic examples in what the API sends it.
"""

from __future__ import annotations

import re

from apps.api.actions import in_call
from apps.api.actions import service as actions_service
from apps.api.admin import service as admin_service
from scripts.seed import CUSTOM_EXTRACTION_FIELDS, VERTICAL_TEMPLATES

CLINICAL = re.compile(
    r"\b(?:clinic|hospital|patients?|doctors?|dentists?|dental|appointments?|symptoms?)\b", re.I
)


def test_custom_business_starts_with_neutral_fields() -> None:
    fields = admin_service.starting_fields("custom")
    assert fields == CUSTOM_EXTRACTION_FIELDS
    assert fields is not VERTICAL_TEMPLATES["clinic"]
    for field in fields:
        assert not CLINICAL.search(f"{field['key']} {field['label']} {field.get('reason', '')}")


def test_each_template_keeps_its_own_fields() -> None:
    for vertical, fields in VERTICAL_TEMPLATES.items():
        assert admin_service.starting_fields(vertical) is fields


def test_in_call_booking_guidance_names_no_clinic() -> None:
    assert not CLINICAL.search(in_call._OK_SAY["booked"])


def test_the_suggested_calendar_action_name_is_one_the_api_accepts() -> None:
    assert actions_service._NAME_RE.match("book_a_slot")
