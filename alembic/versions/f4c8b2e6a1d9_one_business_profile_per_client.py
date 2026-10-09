"""one business profile per client (D-695)

Revision ID: f4c8b2e6a1d9
Revises: e6c2a9d41f07
Create Date: 2026-10-09 12:00:00.000000

The client's business facts — hours, branches, services and prices, FAQs, staff and how to
say their names, booking rules, escalation contacts and languages — move into ONE profile
per client, which the client fills in a skippable setup wizard and every agent of that
client reads.

Before this revision the facts lived in four places: the admin wizard's answer sheet on
`organizations.intake`, and three per-agent derivatives written by its submit
(`agents.business_hours`, `agents.languages_extra`, `agent_handoff_members`). Only the
agent the operator submitted through ever received them; a second agent of the same client
knew nothing.

**Two tables rather than the `organizations.intake` column.** The sheet column argued well
for itself (c1f3a7d92b46), but three things it cannot carry decide it:

* escalation contacts become rows an agent's handover list POINTS AT (`contact_id`), which
  needs a key, not a JSON array element;
* `organizations` is widened to `app.admin` for the cross-tenant directory (b57e2f9c4a13),
  so every column on it is readable there; staff names and mobiles belong behind the plain
  tenant policy;
* the wizard's progress is a per-client record with its own timestamps.

`business_profiles` (one row per client, created on first write) and `business_contacts`
both carry `tenant_id` and the FORCEd `tenant_isolation` policy.

**The data move** runs per tenant, in Python, between `NO FORCE` / `FORCE` brackets on
every table it reads or writes:

* The answer sheet, when one exists, is the source for every field; it is what the
  operator typed and the only record of the prose. A day answered with one time only is
  left unanswered (the old compiler read it as closed) and noted.
* With no sheet, hours come from the agents' own columns, oldest agent first. When two
  agents disagree about a day, the oldest agent's value is kept and the others are written
  to `merge_notes` and printed — nothing is dropped.
* Contacts are the union of every agent's handover members, de-duplicated by number
  (first label kept, others noted), then any sheet contact not already present. Each member
  row is pointed at its contact; `contact_id` is then NOT NULL.
* Languages: the sheet's list; with no sheet, every language of every agent that had
  extras.
* A section that ends up holding data is marked done in the setup progress, so a client
  who was onboarded the old way is not walked through it again.

Nothing is deleted: `organizations.intake`, `agents.business_hours` and
`agents.languages_extra` stay, unread, for one release (hard rule 8).

**Downgrade** writes the profile back into `organizations.intake` (as a v1 sheet) and into
every agent's `business_hours` and `languages_extra`, then drops `contact_id`, both tables
and the two invitation columns. Member labels and numbers are already current, because the
upgrade's writer keeps them equal to their contact.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4c8b2e6a1d9"
down_revision: str | None = "e6c2a9d41f07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILES = "business_profiles"
CONTACTS = "business_contacts"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SECTION_FIELDS = {
    "hours": "hours",
    "branches": "branches",
    "services": "services",
    "faqs": "faqs",
    "staff": "staff",
    "booking": "booking_rules",
    "languages": "languages",
}
_E164 = re.compile(r"^\+[1-9][0-9]{7,18}$")
_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")



def _policy(table: str) -> str:
    return (
        f"CREATE POLICY tenant_isolation ON {table} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def _lift() -> None:
    # Spelled out per table, not looped: `tests/migration_rls_bracket_test.py` reads the
    # literal statements.
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_handoff_members NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE business_profiles NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE business_contacts NO FORCE ROW LEVEL SECURITY")


def _restore() -> None:
    op.execute("ALTER TABLE business_contacts FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE business_profiles FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_handoff_members FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        PROFILES,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("hours", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "branches", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "services", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("faqs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("staff", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("booking_rules", sa.Text(), nullable=True),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "setup_steps", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("setup_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("setup_dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merge_notes", postgresql.JSONB(), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_business_profiles_tenant"),
        sa.CheckConstraint("jsonb_typeof(hours) = 'object'", name="ck_business_profiles_hours"),
        sa.CheckConstraint(
            "jsonb_typeof(branches) = 'array' AND jsonb_typeof(services) = 'array' "
            "AND jsonb_typeof(faqs) = 'array' AND jsonb_typeof(staff) = 'array'",
            name="ck_business_profiles_lists",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(setup_steps) = 'object'", name="ck_business_profiles_setup_steps"
        ),
    )
    op.create_index(op.f("ix_business_profiles_tenant_id"), PROFILES, ["tenant_id"])

    op.create_table(
        CONTACTS,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_business_contacts_position"),
        sa.CheckConstraint("length(btrim(label)) > 0", name="ck_business_contacts_label_nonempty"),
        sa.CheckConstraint(
            r"phone_e164 ~ '^\+[1-9][0-9]{7,18}$'", name="ck_business_contacts_phone_e164"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "phone_e164",
            name="uq_business_contacts_phone",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(op.f("ix_business_contacts_tenant_id"), CONTACTS, ["tenant_id"])

    for table in (PROFILES, CONTACTS):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_policy(table))

    op.add_column(
        "agent_handoff_members",
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{CONTACTS}.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("invitations", sa.Column("invitee_name", sa.Text(), nullable=True))
    op.add_column("invitations", sa.Column("invitee_phone", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_invitations_invitee_phone",
        "invitations",
        r"invitee_phone IS NULL OR invitee_phone ~ '^\+[1-9][0-9]{7,18}$'",
    )

    _lift()
    bind = op.get_bind()
    tenants = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT DISTINCT o.id FROM organizations o "
                "LEFT JOIN agents a ON a.tenant_id = o.id "
                "LEFT JOIN agent_handoff_members m ON m.tenant_id = o.id "
                "WHERE o.intake IS NOT NULL OR a.business_hours IS NOT NULL "
                "   OR a.languages_extra IS NOT NULL OR m.id IS NOT NULL"
            )
        )
    ]
    for tenant_id in tenants:
        _move_tenant(bind, tenant_id)
    orphans = bind.execute(
        sa.text("SELECT count(*) FROM agent_handoff_members WHERE contact_id IS NULL")
    ).scalar()
    _restore()
    if orphans:
        raise RuntimeError(f"{orphans} handover members could not be matched to a contact")
    op.alter_column("agent_handoff_members", "contact_id", nullable=False)
    op.create_index(
        "uq_agent_handoff_members_contact",
        "agent_handoff_members",
        ["agent_id", "contact_id"],
        unique=True,
    )


# --------------------------------------------------------------------------- the move


def _sheet_answers(sheet: Any) -> dict[str, Any] | None:
    if not isinstance(sheet, dict) or sheet.get("version") != 1:
        return None
    answers = sheet.get("answers")
    return answers if isinstance(answers, dict) else None


def _hours_from_sheet(rows: Any, notes: list[dict[str, Any]]) -> dict[str, Any]:
    hours: dict[str, Any] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("day") not in DAYS:
            continue
        opens, closes = row.get("opens"), row.get("closes")
        if row.get("closed"):
            hours[row["day"]] = None
        elif isinstance(opens, str) and isinstance(closes, str) and _HHMM.match(opens) and _HHMM.match(closes):
            hours[row["day"]] = {"opens": opens, "closes": closes}
        else:
            notes.append({"field": f"hours.{row['day']}", "kept": None, "set_aside": [row]})
    return hours


def _merge_agent_hours(
    agents: list[tuple[Any, Any]], notes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Per day, the oldest agent's answer; disagreeing answers go to `notes`."""
    merged: dict[str, Any] = {}
    from_agent: dict[str, str] = {}
    for agent_id, hours in agents:
        if not isinstance(hours, dict):
            continue
        for day in DAYS:
            if day not in hours:
                continue
            value = hours[day]
            if day not in merged:
                merged[day] = value
                from_agent[day] = str(agent_id)
            elif merged[day] != value:
                notes.append(
                    {
                        "field": f"hours.{day}",
                        "kept": merged[day],
                        "kept_from_agent": from_agent[day],
                        "set_aside": [value],
                        "set_aside_from_agent": str(agent_id),
                    }
                )
    return merged


def _move_tenant(bind: sa.engine.Connection, tenant_id: Any) -> None:
    notes: list[dict[str, Any]] = []
    sheet = bind.execute(
        sa.text("SELECT intake FROM organizations WHERE id = :t"), {"t": tenant_id}
    ).scalar()
    answers = _sheet_answers(sheet)
    agents = bind.execute(
        sa.text(
            "SELECT id, business_hours, language_primary, languages_extra FROM agents "
            "WHERE tenant_id = :t AND deleted_at IS NULL ORDER BY created_at, id"
        ),
        {"t": tenant_id},
    ).all()

    agent_hours = _merge_agent_hours([(a[0], a[1]) for a in agents], notes)
    if answers is not None and answers.get("business_hours"):
        hours = _hours_from_sheet(answers.get("business_hours"), notes)
        if agent_hours and agent_hours != hours:
            notes.append({"field": "hours", "kept": "answer sheet", "set_aside": [agent_hours]})
    else:
        hours = agent_hours

    def listed(key: str) -> list[Any]:
        value = (answers or {}).get(key)
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    if answers is not None and isinstance(answers.get("languages"), list):
        languages = [tag for tag in answers["languages"] if isinstance(tag, str) and tag]
    else:
        languages = []
        for _, _, primary, extras in agents:
            if extras:
                for tag in [primary, *extras]:
                    if tag and tag not in languages:
                        languages.append(tag)
    booking = (answers or {}).get("booking_rules")
    booking = booking if isinstance(booking, str) and booking.strip() else None

    # --- contacts: every agent's members, then the sheet's own list -------------------
    members = bind.execute(
        sa.text(
            "SELECT m.id, m.label, m.phone_e164, m.note FROM agent_handoff_members m "
            "JOIN agents a ON a.id = m.agent_id WHERE m.tenant_id = :t "
            "ORDER BY a.created_at, a.id, m.position"
        ),
        {"t": tenant_id},
    ).all()
    contacts: dict[str, dict[str, Any]] = {}
    member_phone: list[tuple[Any, str]] = []
    for member_id, label, phone, note in members:
        member_phone.append((member_id, phone))
        if phone not in contacts:
            contacts[phone] = {"label": label, "note": note}
        elif contacts[phone]["label"] != label:
            notes.append(
                {"field": "contacts.label", "kept": contacts[phone]["label"], "set_aside": [label]}
            )
    for entry in listed("escalation_contacts"):
        phone = entry.get("phone_e164")
        name = (entry.get("name") or "").strip()
        if not isinstance(phone, str) or not _E164.match(phone) or not name:
            notes.append({"field": "contacts", "kept": None, "set_aside": [entry]})
            continue
        if phone not in contacts:
            contacts[phone] = {"label": name[:120], "note": entry.get("hours")}

    contact_ids: dict[str, Any] = {}
    for position, (phone, contact) in enumerate(contacts.items()):
        contact_ids[phone] = bind.execute(
            sa.text(
                f"INSERT INTO {CONTACTS} (id, tenant_id, position, label, phone_e164, note) "
                "VALUES (gen_random_uuid(), :t, :pos, :label, :phone, :note) RETURNING id"
            ),
            {
                "t": tenant_id,
                "pos": position,
                "label": contact["label"],
                "phone": phone,
                "note": contact["note"],
            },
        ).scalar()
    for member_id, phone in member_phone:
        bind.execute(
            sa.text(
                "UPDATE agent_handoff_members SET contact_id = :c, "
                f"label = (SELECT label FROM {CONTACTS} WHERE id = :c) WHERE id = :m"
            ),
            {"c": contact_ids[phone], "m": member_id},
        )

    profile = {
        "hours": hours,
        "branches": listed("branches"),
        "services": listed("services"),
        "faqs": listed("faqs"),
        "staff": listed("staff"),
        "booking_rules": booking,
        "languages": languages,
    }
    steps = {
        step: "done"
        for step, field in SECTION_FIELDS.items()
        if profile[field] not in (None, "", [], {})
    }
    if contacts:
        steps["contacts"] = "done"
    if not steps and not notes:
        return
    bind.execute(
        sa.text(
            f"INSERT INTO {PROFILES} (id, tenant_id, hours, branches, services, faqs, staff, "
            "booking_rules, languages, setup_steps, setup_started_at, merge_notes) VALUES "
            "(gen_random_uuid(), :t, CAST(:hours AS jsonb), CAST(:branches AS jsonb), "
            "CAST(:services AS jsonb), CAST(:faqs AS jsonb), CAST(:staff AS jsonb), :booking, "
            ":languages, CAST(:steps AS jsonb), CASE WHEN :started THEN now() END, "
            "CAST(:notes AS jsonb))"
        ),
        {
            "t": tenant_id,
            "hours": json.dumps(profile["hours"]),
            "branches": json.dumps(profile["branches"]),
            "services": json.dumps(profile["services"]),
            "faqs": json.dumps(profile["faqs"]),
            "staff": json.dumps(profile["staff"]),
            "booking": booking,
            "languages": languages,
            "steps": json.dumps(steps),
            "started": bool(steps),
            "notes": json.dumps(notes) if notes else None,
        },
    )
    if notes:
        # Ids and counts only: the notes hold staff names and numbers (hard rule 6).
        print(f"business profile {tenant_id}: {len(notes)} merge conflict(s) kept in merge_notes")


# --------------------------------------------------------------------------- downgrade


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _lift()
    op.execute(
        f"""
        UPDATE organizations o SET intake = jsonb_build_object(
            'version', 1,
            'agent_id', (SELECT a.id FROM agents a WHERE a.tenant_id = o.id
                         AND a.deleted_at IS NULL ORDER BY a.created_at LIMIT 1),
            'saved_at', to_jsonb(now()),
            'answers', jsonb_build_object(
                'business_hours', (
                    SELECT coalesce(jsonb_agg(CASE WHEN h.value = 'null'::jsonb
                        THEN jsonb_build_object('day', h.key, 'closed', true)
                        ELSE jsonb_build_object('day', h.key, 'closed', false,
                             'opens', h.value->>'opens', 'closes', h.value->>'closes') END),
                        '[]'::jsonb)
                    FROM jsonb_each(p.hours) AS h),
                'branches', p.branches, 'services', p.services, 'faqs', p.faqs,
                'staff', p.staff, 'booking_rules', p.booking_rules,
                'languages', to_jsonb(p.languages),
                'escalation_contacts', (
                    SELECT coalesce(jsonb_agg(jsonb_build_object('name', c.label,
                        'phone_e164', c.phone_e164, 'hours', c.note) ORDER BY c.position),
                        '[]'::jsonb)
                    FROM {CONTACTS} c WHERE c.tenant_id = o.id)))
            || CASE WHEN o.intake ? 'submitted_at'
                    THEN jsonb_build_object('submitted_at', o.intake->'submitted_at')
                    ELSE '{{}}'::jsonb END
        FROM {PROFILES} p WHERE p.tenant_id = o.id
        """
    )
    op.execute(
        f"""
        UPDATE agents a SET
            business_hours = CASE WHEN p.hours = '{{}}'::jsonb THEN a.business_hours
                                  ELSE p.hours END,
            languages_extra = coalesce(
                nullif(array_remove(p.languages, a.language_primary), '{{}}'::text[]),
                a.languages_extra)
        FROM {PROFILES} p WHERE p.tenant_id = a.tenant_id AND a.deleted_at IS NULL
        """
    )
    _restore()
    op.drop_index("uq_agent_handoff_members_contact", table_name="agent_handoff_members")
    op.drop_column("agent_handoff_members", "contact_id")
    op.drop_constraint("ck_invitations_invitee_phone", "invitations", type_="check")
    op.drop_column("invitations", "invitee_phone")
    op.drop_column("invitations", "invitee_name")
    for table in (CONTACTS, PROFILES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_index(op.f(f"ix_{table}_tenant_id"), table_name=table)
        op.drop_table(table)
