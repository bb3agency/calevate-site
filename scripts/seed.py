"""Idempotent seed: reserved slugs (global) + the per-tenant defaults onboarding applies.

Run: `uv run python -m scripts.seed` (also invoked by `make db-reset`).

Only ONE thing here is a global row: `reserved_slugs`. Vertical templates and
retention policies are tenant-scoped tables (`extraction_schemas.tenant_id`,
`retention_policies.tenant_id`), so they cannot exist without an organization —
they live here as the canonical DEFAULTS that the new-client onboarding flow
(ROADMAP M1, admin wizard) applies when it creates a tenant. Keeping them in one
place stops the wizard and the docs drifting apart.

Safe to re-run: inserts use ON CONFLICT DO NOTHING and the script never updates
or deletes existing rows.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from apps.api.db.session import untenanted_session
from sqlalchemy import text

# --- Global: reserved slugs -------------------------------------------------
# Slugs a tenant may never claim: our own subdomains/routes, plus the usual
# impersonation bait. DATA-MODEL §2 (`organizations.slug` is immutable once set).
RESERVED_SLUGS: tuple[str, ...] = (
    # our surfaces
    "admin",
    "api",
    "app",
    "www",
    "hooks",
    "accounts",
    "auth",
    "login",
    "logout",
    "signup",
    "register",
    "onboarding",
    "dashboard",
    "settings",
    "billing",
    "support",
    "help",
    "docs",
    "status",
    "static",
    "assets",
    "cdn",
    "media",
    # brand / trust-sensitive
    "calevate",
    "bb3",
    "builtbythree",
    "security",
    "abuse",
    "legal",
    "privacy",
    "terms",
    "dpa",
    "compliance",
    "trai",
    "dlt",
    # generic traps
    "test",
    "demo",
    "example",
    "root",
    "system",
    "internal",
    "null",
    "undefined",
)

# --- Per-tenant defaults (applied by onboarding, NOT inserted here) ---------
# Retention: SEC-COMP §1. The DB enforces a 90-day floor on `recording`
# (CheckConstraint recording_ttl_floor) — do not lower it here, it will fail.
DEFAULT_RETENTION_POLICIES: tuple[dict[str, Any], ...] = (
    {"data_category": "recording", "ttl_days": 90, "action": "delete"},
    {"data_category": "transcript", "ttl_days": 365, "action": "anonymize"},
    {"data_category": "lead", "ttl_days": 1095, "action": "anonymize"},
    # consent_log is an append-only ledger (hard rule 4) — retained, never purged
    # on a timer; kept here so the category is explicit rather than forgotten.
    {"data_category": "consent_log", "ttl_days": 2555, "action": "anonymize"},
)

# Extraction-schema starting points per vertical. Shape validated by Pydantic on
# write; see DATA-MODEL §3 for the field contract.
VERTICAL_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "clinic": [
        {
            "key": "symptom",
            "label": "Symptom / reason",
            "type": "text",
            "description": "What the caller says is wrong",
            "required": True,
        },
        {
            "key": "preferred_doctor",
            "label": "Preferred doctor",
            "type": "text",
            "description": "Named doctor if the caller asks for one",
            "required": False,
        },
        {
            "key": "urgency",
            "label": "Urgency",
            "type": "enum",
            "enum_values": ["emergency", "same_day", "this_week", "routine"],
            "required": True,
        },
        {
            "key": "preferred_slot",
            "label": "Preferred slot",
            "type": "text",
            "description": "Day/time the caller wants",
            "required": False,
        },
        {
            "key": "insurance",
            "label": "Insurance",
            "type": "text",
            "description": "Insurer or cash payment",
            "required": False,
        },
    ],
    "real_estate": [
        {
            "key": "budget",
            "label": "Budget",
            "type": "number",
            "description": "Property budget in lakhs",
            "required": True,
        },
        {
            "key": "preferred_location",
            "label": "Location",
            "type": "text",
            "description": "Area/locality the caller wants",
            "required": True,
        },
        {
            "key": "bhk_size",
            "label": "BHK",
            "type": "enum",
            "enum_values": ["1BHK", "2BHK", "3BHK", "4BHK+"],
            "required": False,
        },
        {
            "key": "timeline",
            "label": "Timeline",
            "type": "text",
            "description": "When they intend to buy",
            "required": False,
        },
        {
            "key": "site_visit_interest",
            "label": "Site visit",
            "type": "bool",
            "description": "Whether they agreed to a site visit",
            "required": False,
        },
    ],
    "insurance": [
        {
            "key": "policy_type",
            "label": "Policy type",
            "type": "enum",
            "enum_values": ["health", "life", "motor", "other"],
            "required": True,
        },
        {
            "key": "sum_assured",
            "label": "Sum assured",
            "type": "number",
            "description": "Cover amount in lakhs",
            "required": False,
        },
        {
            "key": "renewal_due",
            "label": "Renewal due",
            "type": "date",
            "description": "Existing policy renewal date if mentioned",
            "required": False,
        },
        {"key": "existing_insurer", "label": "Existing insurer", "type": "text", "required": False},
    ],
    "education": [
        {
            "key": "course_interest",
            "label": "Course",
            "type": "text",
            "description": "Course or stream the caller asked about",
            "required": True,
        },
        {"key": "student_class", "label": "Class / year", "type": "text", "required": False},
        {
            "key": "fee_concern",
            "label": "Fee concern",
            "type": "bool",
            "description": "Whether cost was raised as a blocker",
            "required": False,
        },
        {"key": "demo_booked", "label": "Demo booked", "type": "bool", "required": False},
    ],
}


async def seed_reserved_slugs() -> int:
    """Insert reserved slugs. Returns the number newly inserted."""
    async with untenanted_session() as session:
        before = (await session.execute(text("SELECT count(*) FROM reserved_slugs"))).scalar_one()
        await session.execute(
            # The ::text[] cast is required — without it Postgres cannot resolve which
            # unnest() overload to use and errors with "could not choose a best candidate".
            text(
                "INSERT INTO reserved_slugs (slug) "
                "SELECT unnest(CAST(:slugs AS text[])) ON CONFLICT DO NOTHING"
            ),
            {"slugs": list(RESERVED_SLUGS)},
        )
        after = (await session.execute(text("SELECT count(*) FROM reserved_slugs"))).scalar_one()
        await session.commit()
        return int(after) - int(before)


async def main() -> None:
    inserted = await seed_reserved_slugs()
    print(f"seed: reserved_slugs +{inserted} (total defined: {len(RESERVED_SLUGS)})")
    print(
        f"seed: {len(VERTICAL_TEMPLATES)} vertical templates and "
        f"{len(DEFAULT_RETENTION_POLICIES)} retention defaults are tenant-scoped — "
        "applied by the onboarding flow, not inserted globally."
    )


if __name__ == "__main__":
    # Windows defaults to ProactorEventLoop, which psycopg's async mode cannot use.
    # tests/conftest.py applies the same override via its event_loop_policy fixture —
    # any standalone async entrypoint needs it too.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
