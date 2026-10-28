"""Guardrail: no response grows with a caller's row count (D-302).

The rule: a route whose response can contain a LIST must either take a `limit` the
schema bounds, or be written down here with what bounds it instead.

WHY IT IS A GUARDRAIL AND NOT A REVIEW NOTE. Every unbounded list in this API was
written by somebody who knew the list was short — and every one of them was right on
the day they wrote it. `GET /v1/members` is a picker, `GET /v1/kb/sources` is "the
handful of documents this clinic uploaded", `GET /v1/agents` is two rows. The failure
is not that somebody was careless; it is that "short today" is a fact about the FIRST
tenant and the check for it happens exactly once, in a review, against an empty
database. The whole result is materialised in Python and serialised to JSON, so the
first client who succeeds at using the product is the one who finds out.

THE DISTINCTION THIS ENCODES, which is the part worth arguing. Not every list needs a
ceiling. What needs one is a list whose length is CALLER-CONTROLLED: rows a tenant can
mint (members, invitations, endpoints, knowledge sources, campaigns) or that accumulate
per tenant without anybody minting them (`prompt_versions` is append-only). What does
NOT need one is a list bounded by something we provision or declare — the voice
catalogue, the permission set of a role, the configuration registry, the seven days of a
week, the number of CLIENTS the platform has signed. The second kind is bounded by an
operational number that has an alarm on it (`client_health`'s walk budget), not by an
attacker's patience, and truncating it would silently drop an account from a triage
board — a worse failure than the one this check exists to prevent.

So the registry below is not an allowlist of things we got around to: each entry names
the OTHER bound, and the check verifies the entry still names a live route.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
* **It does not read SQL.** A `LIMIT` literal inside a service is invisible here, and
  that is the right answer rather than a limitation: a ceiling the schema does not state
  is indistinguishable, from outside, from a client who really does have that many rows.
  `GET /v1/campaigns` had exactly that — `LIMIT 100` buried in a service — and the fix
  was to make the number a parameter, not to teach this check to find it.
* **It does not judge the SIZE of the ceiling.** Whether 200 is right for a team picker
  is a product question. Whether there is one at all is not.
* **It does not look at `offset`.** Deep pagination is a performance question this repo
  answers per route (`crm.service.MAX_PAGE`); an unbounded page is a memory question,
  and only the second one can take a process down.

Run: `uv run python -m scripts.check_list_bounds`
"""

from __future__ import annotations

import sys
import typing
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cost is paid only when the check runs
    from fastapi import FastAPI
    from fastapi.routing import APIRoute

_MIN_REASON = 40

#: How deep to walk a response model looking for a list. Three levels covers every shape
#: in this app (`Out.items[].sub[]`) and stops a recursive model from hanging the check.
_MAX_DEPTH = 3

#: Parameter names that mean "how many rows may come back". `days` is here because
#: `GET /v1/performance` bounds its response that way — the list is one entry per hour
#: of the window — and a rule that only knew the word `limit` would have demanded a
#: second, meaningless parameter beside it.
_BOUNDING_PARAMS = frozenset({"limit", "days"})


@dataclass(frozen=True, slots=True)
class BoundedByConstruction:
    """A list route with no `limit`, and the thing that bounds it instead.

    `by` must name the mechanism — a constant, a schema ceiling, a CHECK constraint, a
    registry — not merely assert that the list is short. "It is always small" is the
    belief this check exists to stop trusting.
    """

    by: str


#: The lead-detail suggestion routes (D-889) share one bound.
_ONE_PLAN = BoundedByConstruction(
    by=(
        "one plan; its only list is `exclusions`, the reasons targets were left out, at most "
        "`copilot/plan_schemas.MAX_EXCLUSION_REASONS` (the rest are in the targets page)."
    )
)

_LEAD_SUGGESTIONS = BoundedByConstruction(
    by=(
        "the open suggestions on ONE agent, at most `agents/models.MAX_FIELD_SUGGESTIONS` "
        "(six), enforced by `workers/field_suggestions` when it writes them; a suggestion's "
        "`values` are choices of one field, at most "
        "`agents/field_suggestions.MAX_CHOICES` (the model's `max_length`)."
    )
)

#: Tell my team (D-904): the contact list and one agent's rule.
_TEAM_CONTACTS = BoundedByConstruction(
    by=(
        "the account's team addresses, at most `team_alerts/service.MAX_CONTACTS` (ten, refused "
        "past it and read with that LIMIT), and its own WhatsApp connections, read with LIMIT 20."
    )
)
_TEAM_RULE = BoundedByConstruction(
    by=(
        "ONE agent's rule: its business outcomes and choice fields (the agent's own lists, "
        "bounded where they are written), the watched fields at most "
        "`team_alerts/service.MAX_FIELD_TRIGGERS`, each field's values by the request model."
    )
)

#: Every list-shaped route that legitimately has no `limit`, keyed `"METHOD /path"`.
BOUNDED_LISTS: dict[str, BoundedByConstruction] = {
    "GET /v1/team-alerts/contacts": _TEAM_CONTACTS,
    "POST /v1/team-alerts/contacts": _TEAM_CONTACTS,
    "POST /v1/team-alerts/contacts/{contact_id}/code": _TEAM_CONTACTS,
    "POST /v1/team-alerts/contacts/{contact_id}/verify": _TEAM_CONTACTS,
    "POST /v1/team-alerts/contacts/{contact_id}/default": _TEAM_CONTACTS,
    "GET /v1/agents/{agent_id}/team-alert": _TEAM_RULE,
    "PUT /v1/agents/{agent_id}/team-alert": _TEAM_RULE,
    "GET /v1/calls/live": BoundedByConstruction(
        by=(
            "the calls among the ids asked for, read with `ids[:crm/live_calls.MAX_LIVE_IDS]` "
            "(twenty), one row per id (D-886)."
        )
    ),
    "GET /v1/trial/calls": BoundedByConstruction(
        by=("today's test calls read with `LIMIT` `agents/test_call_reads.RECENT_TEST_CALLS`.")
    ),
    "GET /v1/agents/{agent_id}/lead-suggestions": _LEAD_SUGGESTIONS,
    "POST /v1/agents/{agent_id}/lead-suggestions/check": _LEAD_SUGGESTIONS,
    "POST /v1/agents/{agent_id}/lead-suggestions/{suggestion_id}/accept": _LEAD_SUGGESTIONS,
    "POST /v1/agents/{agent_id}/lead-suggestions/{suggestion_id}/dismiss": _LEAD_SUGGESTIONS,
    "GET /v1/admin/tenants/{tenant_id}/agents/{agent_id}/lead-suggestions": _LEAD_SUGGESTIONS,
    (
        "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/lead-suggestions/check"
    ): _LEAD_SUGGESTIONS,
    (
        "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}"
        "/lead-suggestions/{suggestion_id}/accept"
    ): _LEAD_SUGGESTIONS,
    (
        "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}"
        "/lead-suggestions/{suggestion_id}/dismiss"
    ): _LEAD_SUGGESTIONS,
    "GET /v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt/layers": BoundedByConstruction(
        by=(
            "one entry per `calevate_shared.engine.PromptLayer` (twelve), the layers "
            "`engine_prompt_layers` composes, whatever the agent holds (D-882)."
        )
    ),
    # --- the UI wave's backend lane (D-869, D-870) ------------------------------------------
    "GET /v1/agents/{agent_id}/readiness": BoundedByConstruction(
        by=(
            "one component per key of `agents/readiness.MAX_POINTS` (six) and at most one fix "
            "per component, so both lists are fixed by the formula, not by any row count."
        )
    ),
    "GET /v1/billing/voice-tiers": BoundedByConstruction(
        by=(
            "one entry per `billing/rates.VOICE_TIERS` (two), each with the fixed copy lines "
            "of `billing/tier_routes.TIER_INCLUDES`."
        )
    ),
    "GET /v1/leads/{lead_id}/whatsapp": BoundedByConstruction(
        by=(
            "approved templates of ONE connected account, read with `LIMIT` "
            "`whatsapp/templates.MAX_TEMPLATES_PER_ACCOUNT`; a template's blanks are at most "
            "`templates.MAX_VARIABLES`."
        )
    ),
    # --- clients' WhatsApp (D-784) ---------------------------------------------------------
    "GET /v1/whatsapp": BoundedByConstruction(
        by=(
            "accounts are read with `LIMIT` `whatsapp/accounts.MAX_ACCOUNTS_PER_TENANT` x 3 "
            "and a WABA is live on one client at a time (`ux_whatsapp_accounts_live_waba`)."
        )
    ),
    **{
        key: BoundedByConstruction(
            by=(
                "templates are capped per account at `whatsapp/templates."
                "MAX_TEMPLATES_PER_ACCOUNT` by the writer, and the list reads with `LIMIT` "
                "that times `whatsapp/accounts.MAX_ACCOUNTS_PER_TENANT`; a template's blanks "
                "are at most `templates.MAX_VARIABLES`."
            )
        )
        for key in ("GET /v1/whatsapp/templates", "POST /v1/whatsapp/templates")
    },
    "GET /v1/admin/whatsapp": BoundedByConstruction(
        by=(
            "the clients listed are cut to `whatsapp/admin_routes.MAX_CLIENTS` (the most "
            "recently heard from) and each client's accounts are read with "
            "`whatsapp/accounts.list_accounts`' `LIMIT`."
        )
    ),
    # --- call handling (D-751, F3, F9): filler lines and the sound choices -----------------
    **{
        key: BoundedByConstruction(
            by=(
                "filler lines capped at `agents.models.FILLER_LINES_MAX` by the writer and "
                "a CHECK on `cardinality`; the sound choices are `agents.models.AMBIENCES`, "
                "three values declared in code; the account read's agents with their own "
                "values are read with `LIMIT` `agents/call_handling.AGENTS_WITH_OWN_MAX`."
            )
        )
        for key in (
            "GET /v1/agents/{agent_id}/call-handling",
            "PATCH /v1/agents/{agent_id}/call-handling",
            "GET /v1/organization/call-handling",
            "PUT /v1/organization/call-handling",
            "POST /v1/organization/call-handling/all-agents",
            "GET /v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling",
            "PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling",
            "POST /v1/agents/{agent_id}/call-handling/give-callers-time",
            "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling/give-callers-time",
            "GET /v1/admin/organizations/{org_id}/call-handling",
            "PUT /v1/admin/organizations/{org_id}/call-handling",
        )
    },
    # --- Studio voice tuning (D-767): the choices offered ------------------------------------
    **{
        key: BoundedByConstruction(
            by=(
                "the emotions and voice models offered are `agents.models.STUDIO_VOICE_EMOTIONS` "
                "and `STUDIO_VOICE_MODELS`, eight and five values declared in code."
            )
        )
        for key in (
            "GET /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice-tuning",
            "PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice-tuning",
            "GET /v1/agents/{agent_id}/voice-tuning",
            "PATCH /v1/agents/{agent_id}/voice-tuning",
        )
    },
    # --- do-not-call: the evidence shown before an opt-out is restored ---------------------
    "GET /v1/dnc/{entry_id}/evidence": BoundedByConstruction(
        by="`compliance.dnc.MAX_OPTOUT_EVIDENCE` in the LIMIT, and the schema's `max_length`."
    ),
    # --- forwarded lines (D-746) ------------------------------------------------------------
    "GET /v1/forwarding": BoundedByConstruction(
        by=(
            "lines capped at `forwarding.models.MAX_LINES` per client, refused at create; "
            "Calevate numbers by `forwarding.service.MAX_CALEVATE_NUMBERS` in the LIMIT."
        )
    ),
    "GET /v1/forwarding/codes": BoundedByConstruction(
        by="the carrier catalogue declared in code, `forwarding.codes.GUIDES`, five carriers."
    ),
    # --- the teach box and the improvement loop (founder decisions 9 and 11) ---------------
    "GET /v1/kb/knows": BoundedByConstruction(
        by=(
            "facts capped by `teach.facts.MAX_FACTS` in the LIMIT, and uploads by "
            "`kb.uploads.MAX_UPLOADS_PAGE` in theirs."
        )
    ),
    "GET /v1/kb/notes": BoundedByConstruction(
        by="one row per note name, `LIMIT 200` in `kb.store._NOTES_SQL`."
    ),
    "GET /v1/kb/uploads/{upload_id}/text": BoundedByConstruction(
        by=(
            "one reading page: one PDF page or `kb.store.CHUNKS_PER_PART` chunks "
            "(`kb.store._paged`), each chunk at most `kb.service.MAX_CHUNK_CHARS`."
        )
    ),
    "GET /v1/teach/questions": BoundedByConstruction(
        by="`teach.questions.MAX_QUESTIONS` gap topics in the LIMIT plus at most three "
        "practice and setup questions."
    ),
    "GET /v1/agents/{agent_id}/known-facts": BoundedByConstruction(
        by=(
            "facts by heart capped by `agents.hot_facts.MAX_ITEMS` when chosen, looked-up "
            "facts by `hot_facts.LOOKED_UP_SHOWN` in the read (D-896)."
        )
    ),
    "GET /v1/kb/teach/{teaching_id}": BoundedByConstruction(
        by="one teaching's items, at most `workers.kb_teach.MAX_ITEMS` and 30 on save (`SaveIn`)."
    ),
    "GET /v1/kb/teach/open": BoundedByConstruction(
        by="at most one teaching, the same shape as `GET /v1/kb/teach/{teaching_id}`."
    ),
    "POST /v1/kb/teach/upload": BoundedByConstruction(
        by="the same one teaching as `GET /v1/kb/teach/{teaching_id}`."
    ),
    "POST /v1/kb/teach/{teaching_id}/discard": BoundedByConstruction(
        by="the same one teaching as `GET /v1/kb/teach/{teaching_id}`."
    ),
    "GET /v1/agents/{agent_id}/script/proposed-rules": BoundedByConstruction(
        by="LIMIT 100, and `teach.rules.MAX_PENDING_RULES` pending per agent on write."
    ),
    "GET /v1/agents/{agent_id}/test-cases": BoundedByConstruction(
        by=(
            "`teach.test_cases.MAX_CASES_PER_AGENT` (refused on write, and the LIMIT), each "
            "with at most `MAX_CASE_LINES` lines and as many answers."
        )
    ),
    "POST /v1/agents/{agent_id}/test-cases/run": BoundedByConstruction(
        by="the same list as `GET /v1/agents/{agent_id}/test-cases`."
    ),
    "POST /v1/agents/{agent_id}/test-cases": BoundedByConstruction(
        by="one test case: at most `MAX_CASE_LINES` lines (CHECK and `TestCaseIn`)."
    ),
    "POST /v1/calls/{call_id}/test-case": BoundedByConstruction(
        by="one test case: at most `MAX_CASE_LINES` lines (CHECK and `TestCaseIn`)."
    ),
    "GET /v1/calls/{call_id}/test-case-draft": BoundedByConstruction(
        by="the call's first `teach.models.MAX_CASE_LINES` caller turns, in the LIMIT."
    ),
    # --- founder decision 15: business-neutral lead details --------------------------------
    "GET /v1/lead-fields": BoundedByConstruction(
        by=(
            "the fixed core (`calevate_shared.lead_fields.CORE_LEAD_FIELDS`), one type's "
            "standard set from `scripts/seed`, the draft's at most `MAX_DRAFTED_FIELDS`, and "
            "agents capped by `agents.lead_fields.MAX_AGENTS` in the LIMIT, each holding at "
            "most `extraction_routes.MAX_EXTRACTION_FIELDS` fields (refused on write)."
        )
    ),
    "GET /v1/call-outcomes": BoundedByConstruction(
        by=(
            "agents capped by `agents.lead_fields.MAX_AGENTS` in the LIMIT, each holding at "
            "most `calevate_shared.business_outcomes.MAX_BUSINESS_OUTCOMES` outcomes (the "
            "`ck_agents_business_outcomes_shape` CHECK and the response model's `max_length`)."
        )
    ),
    "PUT /v1/agents/{agent_id}/call-outcomes": BoundedByConstruction(
        by=(
            "one agent's outcomes, at most `MAX_BUSINESS_OUTCOMES` (the request and response "
            "models' `max_length` and the column's CHECK)."
        )
    ),
    "POST /v1/agents/{agent_id}/call-outcomes/draft": BoundedByConstruction(
        by=(
            "one agent's outcomes, at most `MAX_BUSINESS_OUTCOMES` (the response model's "
            "`max_length` and the column's CHECK)."
        )
    ),
    "GET /v1/business-copy": BoundedByConstruction(
        by=(
            "one row per account, its lists capped by `tenancy.business_copy.GeneratedCopy` "
            "(at most MAX_STEPS steps, MAX_CHIPS details, MAX_QUESTIONS questions) and again "
            "by the response model's `max_length`."
        )
    ),
    "GET /v1/admin/tenants/{tenant_id}/business-copy": BoundedByConstruction(
        by="the same render as `GET /v1/business-copy`, for one named tenant."
    ),
    "POST /v1/admin/tenants/{tenant_id}/business-copy/refresh": BoundedByConstruction(
        by="the same render as `GET /v1/business-copy`, for one named tenant."
    ),
    "GET /v1/admin/tenants/{tenant_id}/lead-fields": BoundedByConstruction(
        by="the same render as `GET /v1/lead-fields`, for one named tenant."
    ),
    "POST /v1/admin/tenants/{tenant_id}/lead-fields/draft": BoundedByConstruction(
        by=(
            "the one draft row, whose fields are at most "
            "`workers.lead_fields_draft.MAX_DRAFTED_FIELDS`."
        )
    ),
    "GET /v1/leads/{lead_id}/captured": BoundedByConstruction(
        by=(
            "one lead's own captured values: the core plus the fields of the version that "
            "captured them, and any other key in `leads.data`, which only an extraction "
            "against one of the agent's schemas (each at most `MAX_EXTRACTION_FIELDS`) writes."
        )
    ),
    # --- D-701 the auto-healer --------------------------------------------------------------
    "GET /v1/ops/healer": BoundedByConstruction(
        by="one row per playbook in `healer.playbooks.PLAYBOOKS`, a fixed registry in code."
    ),
    "GET /v1/public/status": BoundedByConstruction(
        by=(
            "a fixed set of components, and incident history capped by "
            "`healer.status.HISTORY_LIMIT` in the query's LIMIT."
        )
    ),
    "POST /v1/healer/incidents/{incident_id}/restore": BoundedByConstruction(
        by="the callers to ring back, capped by `healer.routes.CALL_BACKS_MAX` in the LIMIT."
    ),
    # --- D-697 the shared free-trial number -------------------------------------------------
    "GET /v1/ops/trial-number": BoundedByConstruction(
        by=(
            "the numbers our ONE developer workspace holds unrecorded: what we rent, which "
            "the ThinnestAI plan bounds, read through the engine's capped listing walk "
            "(`engine/thinnest.py` `_LISTING_MAX_PAGES`)."
        )
    ),
    # --- D-699 Razorpay payments ----------------------------------------------------------
    "GET /v1/admin/payments/status": BoundedByConstruction(
        by=(
            "`subscribed_events` is the constant `billing.payments.SUBSCRIBED_EVENTS` (16); "
            "`alarms` is a filter over `ops.alerts_service.alert_report(days=7, limit=500)`."
        )
    ),
    "POST /v1/admin/payments/reconcile": BoundedByConstruction(
        by=(
            "one pass over `razorpay_reconciliation_days` (at most 30) of Razorpay's own "
            "listings; the id lists are what that window holds, and the window is the bound."
        )
    ),
    # --- bounded by a constant or a registry in this repo ---------------------------
    # --- D-694 the assistant's background jobs -------------------------------------------
    "GET /v1/copilot/jobs/{job_id}": BoundedByConstruction(
        by=(
            "one job; its `progress` keeps the newest `copilot.models.MAX_JOB_PROGRESS` (200) "
            "entries, trimmed on every append and CHECKed by `ck_copilot_jobs_progress_cap`."
        )
    ),
    "POST /v1/copilot/jobs/{job_id}/cancel": BoundedByConstruction(
        by="the same one job and its 200-entry progress cap."
    ),
    # --- D-694 the assistant's routines ----------------------------------------------------
    "POST /v1/copilot/routines": BoundedByConstruction(
        by=(
            "one routine; its only list is `schedule.days`, at most the seven weekdays "
            "(`CopilotRoutineSchedule.days` max_length=7, distinct)."
        )
    ),
    "PATCH /v1/copilot/routines/{routine_id}": BoundedByConstruction(
        by="the same one routine and its seven-day schedule."
    ),
    # --- D-893 plans ------------------------------------------------------------------
    "GET /v1/copilot/plans/{plan_id}": _ONE_PLAN,
    "POST /v1/copilot/plans/{plan_id}/approve": _ONE_PLAN,
    "POST /v1/copilot/plans/{plan_id}/cancel": _ONE_PLAN,
    "POST /v1/copilot/plans": _ONE_PLAN,
    "POST /v1/callbacks/bulk": BoundedByConstruction(
        by="one result per submitted id, and `callbacks/routes.MAX_PAGE` (200) bounds the request."
    ),
    # --- D-693 a client's own voice workspace -----------------------------------------
    "GET /v1/numbers/own/available": BoundedByConstruction(
        by=(
            "one page of the vendor's search, at most twenty numbers "
            "(`phone-numbers/search-available-phone-numbers.md:7`); further pages by `cursor`."
        )
    ),
    "GET /v1/admin/engine-workspaces/tenants/{tenant_id}/numbers/available": (
        BoundedByConstruction(by="the same one vendor search page of at most twenty numbers.")
    ),
    "GET /v1/numbers/own/cities": BoundedByConstruction(
        by=(
            "the vendor's list of Indian cities with numbers in stock, one page by definition "
            "(`phone-numbers/list-available-cities.md:7`, `nextCursor` always null)."
        )
    ),
    "GET /v1/admin/engine-workspaces/tenants/{tenant_id}/numbers/cities": (
        BoundedByConstruction(by="the same one-page vendor city list, never more than one page.")
    ),
    "GET /v1/admin/engine-workspaces/tenants/{tenant_id}": BoundedByConstruction(
        by=(
            "`purchase_blockers` names at most the four purchase gates "
            "(`engine_number_purchase._BLOCKER_STEP`)."
        )
    ),
    "GET /v1/admin/engine-workspaces/summary": BoundedByConstruction(
        by=(
            "`failures` is cut at 50 in the handler and `by_status` has the six states of "
            "the `tenant_engine_workspaces.status` CHECK."
        )
    ),
    "POST /v1/admin/engine-workspaces/tenants/{tenant_id}/provision": BoundedByConstruction(
        by=(
            "`purchase_blockers` names at most the four purchase gates "
            "(`engine_number_purchase._BLOCKER_STEP`)."
        )
    ),
    "POST /v1/admin/engine-workspaces/tenants/{tenant_id}/offboard": BoundedByConstruction(
        by="the same four-gate `purchase_blockers` list."
    ),
    # --- D-692 KYC: `documents` is the CURRENT file per slot, and there are two slots ----
    "GET /v1/compliance/kyc": BoundedByConstruction(
        by=(
            "`documents` lists the current file per slot; `kyc_documents` has two slots "
            "(`business`, `owner_id`, a CHECK) and `ux_kyc_documents_current_per_slot` allows "
            "one current row each, so at most two entries."
        )
    ),
    "PUT /v1/compliance/kyc/details": BoundedByConstruction(
        by="the same two-slot `documents` list as `GET /v1/compliance/kyc`."
    ),
    "POST /v1/compliance/kyc/submit": BoundedByConstruction(
        by="the same two-slot `documents` list as `GET /v1/compliance/kyc`."
    ),
    "POST /v1/compliance/kyc/verification/complete": BoundedByConstruction(
        by="the same two-slot `documents` list as `GET /v1/compliance/kyc`."
    ),
    "GET /v1/admin/tenants/{tenant_id}/kyc": BoundedByConstruction(
        by="the same two-slot `documents` list as `GET /v1/compliance/kyc`."
    ),
    "POST /v1/admin/tenants/{tenant_id}/kyc/review": BoundedByConstruction(
        by="the same two-slot `documents` list as `GET /v1/compliance/kyc`."
    ),
    "POST /v1/admin/tenants/{tenant_id}/kyc/digilocker-requirement": BoundedByConstruction(
        by="the same two-slot `documents` list as `GET /v1/compliance/kyc`."
    ),
    "GET /v1/ops/spoken-style": BoundedByConstruction(
        by=(
            "one row per language row in `calevate_shared/spoken_style.json` "
            "(`spoken_style.languages()`), a file shipped with the code."
        )
    ),
    **{
        route: BoundedByConstruction(
            by=(
                "`entries` is the language's rows in `spoken_style.json` plus at most "
                "`spoken_style_routes.MAX_ADDED_ENTRIES` added on the review screen (refused "
                "beyond it); `history` is `spoken_style_store.HISTORY_LIMIT` (10) passed as "
                "the SQL LIMIT; an example's `turns` is `spoken_style.MAX_TURNS`."
            )
        )
        for route in (
            "GET /v1/ops/spoken-style/{language}",
            "POST /v1/ops/spoken-style/{language}/entries",
            "POST /v1/ops/spoken-style/{language}/publish",
        )
    },
    "GET /v1/ops/engine-minute-prices": BoundedByConstruction(
        by=(
            "one row per engine in `billing/engine_minutes.ATTESTED_MINUTE_ENGINES` times "
            "`PRICED_RATE_KEYS` (the route keys and the carrier's fee, a CHECK on "
            "`rate_key`), each the rate in force now, never the history."
        )
    ),
    "GET /v1/ops/engine-model-bands": BoundedByConstruction(
        by=(
            "the selected engine's own model list (`HoldsCatalogue.read_catalogue`), which the "
            "adapter walks at most `_LISTING_MAX_PAGES` pages of; one row per model, each the "
            "band in force, never the history."
        )
    ),
    "GET /v1/billing/platform-fee": BoundedByConstruction(
        by=(
            "`charges` is the newest `platform_fee_routes.HISTORY_MONTHS` (12) months, a "
            "code constant passed as the SQL LIMIT; one fee per client per month is a "
            "unique index on `monthly_fee_charges`."
        )
    ),
    "GET /v1/admin/tenants/{tenant_id}/platform-fee": BoundedByConstruction(
        by="the same twelve-month `charges` list as `GET /v1/billing/platform-fee`."
    ),
    "PUT /v1/admin/tenants/{tenant_id}/platform-fee/waiver": BoundedByConstruction(
        by="the same twelve-month `charges` list as `GET /v1/billing/platform-fee`."
    ),
    "DELETE /v1/admin/tenants/{tenant_id}/platform-fee/waiver": BoundedByConstruction(
        by="the same twelve-month `charges` list as `GET /v1/billing/platform-fee`."
    ),
    "GET /v1/ops/inr-llm-prices": BoundedByConstruction(
        by=(
            "one row per model in `billing/rates.INR_PRICED_LLMS`, a code constant, each "
            "carrying only the attestation in force now, never the history."
        )
    ),
    "GET /v1/agents/engine-catalogue": BoundedByConstruction(
        by=(
            "the voices an operator added and enabled out of `platform_voice_catalog`'s hosted "
            "rows (D-687), which are the vendor account's own Studio band and clones plus our "
            "voice key's voices, tens of rows; and the vendor's model list read through "
            "`ThinnestEngine._walk`, which stops at `_LISTING_MAX_PAGES` (20) pages."
        )
    ),
    "GET /v1/ops/voices/hosted": BoundedByConstruction(
        by=(
            "the hosted rows of `platform_voice_catalog` (D-687): one per voice our ONE "
            "vendor account lists in the band we sell, its clones (10 on Pro, 20 on Scale) "
            "and our Cartesia key's voices. It takes no `limit` deliberately: it is "
            "the operator's curation table, and a page of it would be a subset passing for "
            "the whole. `scope` is a lens, not a page."
        )
    ),
    "GET /v1/admin/numbers/tenants/{tenant_id}/engine": BoundedByConstruction(
        by=(
            "the platform's numbers read through `ThinnestEngine._walk` (20-page cap), and "
            "the client's published agents by `_ENGINE_PUBLISHED_AGENTS` with LIMIT 200."
        )
    ),
    "GET /v1/ops/tts-prices/plan-fees": BoundedByConstruction(
        by=(
            "one slot per entry of `ops/model_pricing.PLAN_BILLED_TTS_PROVIDERS`, a constant "
            "frozenset in this repo, for the one month the request names."
        )
    ),
    "GET /v1/ops/kb-orphans": BoundedByConstruction(
        by=(
            "`kb/orphans.MAX_ORPHAN_ROWS` (200), applied inside `reconcile_account_kb` "
            "where the findings are assembled — so the bound is the SWEEP's and the route "
            "and the daily cron cannot come to disagree about how much of an answer they "
            "each saw. It takes no `limit` DELIBERATELY: the COUNTS beside the rows "
            "(`accounted`/`unrecorded`/`unclaimed`/`stranded`) are exact whatever the cut, "
            "and `truncated` says when one happened, so a reader is never shown a subset "
            "that could pass for the whole. A page size here would let an operator decide "
            "what to do about a client's document having seen part of the account, which "
            "is the one thing a list you are RECONCILING may never do. The upstream bound is "
            "the vendor's own paging cap, and `listing_complete` carries the adapter's "
            "verdict on it unchanged rather than letting a truncated walk read as clean."
        )
    ),
    "GET /v1/me": BoundedByConstruction(
        by="`permissions` is the role's permission set — at most `len(get_args(Permission))`."
    ),
    "GET /v1/admin/me": BoundedByConstruction(
        by="`permissions` is the role's permission set — at most `len(get_args(Permission))`."
    ),
    "GET /v1/billing/wallet": BoundedByConstruction(
        by="`minutes_left` is one row per voice rung (`billing/rates.VoiceTier`, two members), "
        "the only list on the summary."
    ),
    "GET /v1/billing/wallet/topups": BoundedByConstruction(
        by=(
            "`billing/wallet.ATTEMPT_LIMIT`, applied inside `read_attempts`. It takes no "
            "`limit` DELIBERATELY: this is the 'what happened just now' list, not a "
            "history — an older attempt is answered by the ledger if it became money and "
            "by nothing if it did not — and offering a page size would invite a screen to "
            "ask for a year of failed cards."
        )
    ),
    "PATCH /v1/admin/tenants/{tenant_id}": BoundedByConstruction(
        by=(
            "`changed` is a list of FIELD NAMES, not of anybody's rows — the fields this "
            "call actually moved. Its ceiling is the number of fields the route can edit, "
            'which the request model fixes at two (`EditTenantIn`, `extra="forbid"`), and '
            "an unchanged save returns `[]`. A page size would be meaningless here: there "
            "is nothing to page THROUGH, and a `limit` on it would imply the caller could "
            "be told about fewer changes than were made, which is the one thing an audit "
            "response must never do."
        )
    ),
    "GET /v1/agents/{agent_id}/handoff": BoundedByConstruction(
        by=(
            "both lists on the response, by two constants. `members` is capped at "
            "`agents/handoff.MAX_HANDOFF_MEMBERS` — the roster is what a client TYPES and "
            "the request model refuses an eleventh — and `recent` at "
            "`agents/handoff_routes.RECENT_ATTEMPTS`, applied as the LIMIT in the query. "
            "Neither takes a page size deliberately: this is a configuration screen "
            "answering 'who takes calls, and is it working', not a call history — the "
            "whole history is per-call and belongs on the calls list."
        )
    ),
    "PUT /v1/agents/{agent_id}/handoff": BoundedByConstruction(
        by=(
            "it returns the same object `GET` does, from the same renderer, so the same "
            "two constants bound it. The REQUEST is bounded independently: "
            "`HandoffIn.members` carries `max_length=MAX_HANDOFF_MEMBERS`, so a client "
            "pasting a contact export is refused at the boundary rather than turning one "
            "publish into a thousand-row scan."
        )
    ),
    "GET /v1/agents/languages": BoundedByConstruction(
        by="`agents/languages.BUILT_LANGUAGES`, a constant of seven tags (D-855)."
    ),
    "GET /v1/agents/lanes": BoundedByConstruction(
        by="the publishing lanes, a constant tuple in `agents/publishing.py`."
    ),
    # "Meet your agent" (D-855): every route answers the one first run, whose lists are its
    # questions (`first_run/models.MAX_QUESTIONS`), the four build steps
    # (`first_run/models.BUILD_STEPS`), a trade's fixed choices (`first_run/questions.
    # TRADE_CHOICES`, six each) and the languages it speaks (`JobIn.languages_extra`, three).
    **{
        route: BoundedByConstruction(
            by=(
                "the ONE first run of the caller's account: at most `MAX_QUESTIONS` questions, "
                "the four `BUILD_STEPS`, a trade's fixed `TRADE_CHOICES`, at most three "
                "extra languages and at most `MAX_DOCUMENTS` (three) documents, a CHECK on "
                "the row."
            )
        )
        for route in (
            "GET /v1/first-run",
            "PUT /v1/first-run/job",
            "PUT /v1/first-run/brief",
            "PUT /v1/first-run/name",
            "POST /v1/first-run/answers",
            "POST /v1/first-run/build",
            "POST /v1/first-run/finish",
            "POST /v1/first-run/dismiss",
            "POST /v1/first-run/documents",
            "DELETE /v1/first-run/documents/{upload_id}",
        )
    },
    # The go-live guide (D-859): the account's agents' move, sliced to
    # `go_live/moves.MAX_LISTED_AGENTS` with the full count beside it.
    **{
        route: BoundedByConstruction(
            by=(
                "the ONE guide of the caller's account; its agents are sliced to "
                "`go_live/moves.MAX_LISTED_AGENTS` (50) and `total` counts the rest."
            )
        )
        for route in ("GET /v1/go-live", "POST /v1/go-live/finish", "POST /v1/go-live/dismiss")
    },
    "GET /v1/agents/starters": BoundedByConstruction(
        by=(
            "`agents/starters.STARTER_JOBS` (three jobs), each with the constant steps of its "
            "catalogue row and the one vertical template's fields from `scripts/seed.py`."
        )
    ),
    "GET /v1/integrations/events": BoundedByConstruction(
        by="`integrations.service.EVENT_TYPES`, the events an endpoint may subscribe to."
    ),
    "POST /v1/integrations/endpoints": BoundedByConstruction(
        by="`events` of the ONE endpoint just created, a subset of `EVENT_TYPES`."
    ),
    "POST /v1/integrations/endpoints/sheets": BoundedByConstruction(
        by="`events` of the ONE endpoint just created, a subset of `EVENT_TYPES`."
    ),
    "PATCH /v1/integrations/endpoints/{endpoint_id}": BoundedByConstruction(
        by="`events` of the ONE endpoint just edited, a subset of `EVENT_TYPES`."
    ),
    "GET /v1/admin/tenants/{tenant_id}/profile": BoundedByConstruction(
        by=(
            "`verticals` is `get_args(admin/routes.Vertical)` — the same closed `Literal` "
            "the PATCH validates against, currently five members. It grows only when "
            "somebody edits that type, never with a client's data, and it is DERIVED from "
            "the type rather than retyped so the dropdown and the 422 cannot disagree."
        )
    ),
    "GET /v1/admin/tenants/{tenant_id}/feature-flags": BoundedByConstruction(
        by="the flag registry in `flags/service.py` — one row per DECLARED flag."
    ),
    "POST /v1/admin/tenants/{tenant_id}/commercial-terms": BoundedByConstruction(
        by=(
            "`margin.below_target_margin` names the RATES a bundle sets, and "
            "`rates.CommittedPlanMargin._judged` enumerates exactly two of them "
            "('committed', 'overage') — so the list is at most 2 entries, whatever the "
            "terms say."
        )
    ),
    "GET /v1/ops/config": BoundedByConstruction(
        by="the console-managed field registry in `core/platform_config.py`."
    ),
    "PUT /v1/ops/config/{key}": BoundedByConstruction(
        by="the ONE field written, and its `options` list from the same registry."
    ),
    "DELETE /v1/ops/config/{key}": BoundedByConstruction(
        by="the ONE field reset, and its `options` list from the same registry."
    ),
    # The model picker (D-454, widened to three legs). `available` is one row per member of
    # `calevate_shared.engine.SELECTABLE_LLM_MODELS` — derived from `LLM_MODELS`, whose keys
    # are the union of three closed `Literal`s — so its length is decided by a decision-log
    # entry and never by anybody's row count. The client's two verbs answer in TIERS
    # (`ClientLlmDefaultsOut`, D-680), the admin's two in models (`LlmDefaultsOut`); the write
    # paths are declared too because each returns the freshly-read state.
    #
    # ⚠ THE BOUND MOVED FROM `AZURE_OPENAI_MODELS` TO THE WHOLE CATALOGUE AND IS STILL A
    # BOUND, which is the only property this file is about. Widening a closed set does not
    # weaken a bounded-by-construction claim; unclosing one would, and nothing here did.
    # Note that a row per SELECTABLE model is the right ceiling even though the picker marks
    # some rows unavailable: an unofferable model is PRESENT and marked (see
    # `agents/llm_models.SelectableModel`), because a missing row tells an operator nothing
    # and a row that says why tells them the one thing they can act on.
    # Agreements & readiness. Both verbs answer with the same `LegalReadinessOut`, and
    # both of its lists are bounded by constants in this repo: `documents` is one row per
    # member of `legal.catalogue.DOCUMENTS` (the published legal set), and `blockers` is
    # at most one row per organisation-level rule `legal.readiness.readiness_rows` can
    # emit — a fixed sequence of predicates, not a query over anything a client can grow.
    # The POST is declared too because it returns the freshly-read screen rather than an
    # acknowledgement, which is argued at its call site.
    "GET /v1/legal/readiness": BoundedByConstruction(
        by=(
            "`documents` is one row per `legal.catalogue.DOCUMENTS` entry and `blockers` "
            "one per organisation-level rule `legal.readiness.readiness_rows` asks."
        )
    ),
    "POST /v1/legal/acceptances": BoundedByConstruction(
        by="the same `LegalReadinessOut` the readiness GET returns, bounded identically."
    ),
    "GET /v1/usage": BoundedByConstruction(
        by=(
            "`llm_surcharge_tiers` names the tiers of the models this month's minutes "
            "actually ran on, one entry each, so it is bounded by `LLM_MODEL_NAMES` — the "
            "union of three closed Literals — and not by how much the tenant called. It is a "
            "DISTINCT over the same month the totals are read from, so it cannot outgrow "
            "the catalogue even for a tenant that switched model every day of the month. "
            "Stated over the CATALOGUE rather than the selectable set because a historical "
            "month can name a model that has since been withdrawn — which is exactly why "
            "`LLM_MODELS` is keyed by `str` and keeps entries the Literals no longer carry."
        )
    ),
    "GET /v1/organization/llm-defaults": BoundedByConstruction(
        by="`available` is one row per `llm_tiers.LLM_TIERS` member — three client-facing tiers."
    ),
    "PUT /v1/organization/llm-defaults": BoundedByConstruction(
        by="the same tier `available`, read back after the write — same closed set."
    ),
    "GET /v1/admin/organizations/{org_id}/llm-defaults": BoundedByConstruction(
        by=(
            "`available` is one row per `SELECTABLE_LLM_MODELS` member, and `agents` is "
            "capped by `roster.AGENT_ROSTER_LIMIT` in its query."
        )
    ),
    "PUT /v1/admin/organizations/{org_id}/llm-defaults": BoundedByConstruction(
        by="the same `available` and `agents`, read back after the write — same bounds."
    ),
    # The agent's extraction VARIABLES (D-460). `fields` is a curated CONFIG list — the
    # schema an operator or a client owner hand-writes for one agent. It used to be entered
    # here as "bounded by nature — a config surface, not a data feed", and that reading
    # EXPIRED with D-460: once a client OWNER writes the list, its length is
    # caller-controlled, which is precisely the class this registry says needs a real
    # ceiling. It now has one, on the `actions` pattern below — a constant enforced by the
    # request model, not a belief about how many variables a person would type.
    "GET /v1/agents/{agent_id}/extraction-schema": BoundedByConstruction(
        by="`fields` is bounded by `agents.extraction_routes.MAX_EXTRACTION_FIELDS` (50, "
        "the `max_length` on the write model that is the only thing that can grow it)."
    ),
    "PUT /v1/agents/{agent_id}/extraction-schema": BoundedByConstruction(
        by="the same `fields` read back after the write — `MAX_EXTRACTION_FIELDS` "
        "(`ExtractionSchemaIn.fields` max_length) is the request-model ceiling."
    ),
    "PUT /v1/admin/tenants/{tenant_id}/agents/{agent_id}/extraction-schema": BoundedByConstruction(
        by="the admin view of the same `fields` — same `MAX_EXTRACTION_FIELDS` request-model "
        "ceiling, since both realms take one `ExtractionSchemaIn`."
    ),
    # The in-call Actions/tools feature. A tenant mints tools like it mints endpoints, so the
    # lists are caller-controlled and NOT bounded-by-nature — the bound is a real ceiling:
    # `actions.service.MAX_TOOLS_PER_AGENT` on the tool count (enforced at create) and
    # `actions.service.MAX_TOOL_PARAMS` on each tool's param list (the request-model
    # `max_length`). Every verb answers with the SAME shape read back, which is why the writes
    # are declared too.
    "GET /v1/agents/{agent_id}/actions": BoundedByConstruction(
        by="`tools` is bounded by `actions.service.MAX_TOOLS_PER_AGENT` (100, enforced at "
        "create) and each `ToolOut.params` by `MAX_TOOL_PARAMS` (50, request-model max_length)."
    ),
    "PUT /v1/agents/{agent_id}/actions/enabled": BoundedByConstruction(
        by="the same `ActionsSettingsOut`, read back after the write — `MAX_TOOLS_PER_AGENT` "
        "tools, `MAX_TOOL_PARAMS` params each."
    ),
    "POST /v1/agents/{agent_id}/actions": BoundedByConstruction(
        by="one tool's `ToolOut`; `params` is bounded by `actions.service.MAX_TOOL_PARAMS` "
        "(50), the request-model `max_length` on `ToolIn.params`."
    ),
    "PUT /v1/agents/{agent_id}/actions/{tool_id}": BoundedByConstruction(
        by="one tool's `ToolOut` — the same `MAX_TOOL_PARAMS` bound as its POST above."
    ),
    "PUT /v1/agents/{agent_id}/actions/{tool_id}/enabled": BoundedByConstruction(
        by="one tool's `ToolOut` — the same `MAX_TOOL_PARAMS` bound on `params`."
    ),
    "GET /v1/integrations/credentials": BoundedByConstruction(
        by="one row per saved credential, bounded by `actions.credentials."
        "MAX_CREDENTIALS_PER_TENANT` (100), enforced at create — not by call volume."
    ),
    # The structured call-script builder (D-21). A script is one hand-curated config document
    # whose every authored list is bounded on the request model by a `max_length` in
    # `calevate_shared.call_script` (`MAX_SCRIPT_STEPS`/`_FAQS`/`_VARIABLES`/`MAX_END_CALL_RULES`);
    # `standard_variables` is the `STANDARD_VARIABLES` constant.
    "GET /v1/agents/{agent_id}/script": BoundedByConstruction(
        by="one agent's `CallScript`, every list bounded by the `max_length` ceilings in "
        "`calevate_shared.call_script`; `standard_variables` is the `STANDARD_VARIABLES` constant."
    ),
    "GET /v1/agents/{agent_id}/script/proposal": BoundedByConstruction(
        by="one suggestion: two `CallScript`s under the `call_script` ceilings, and "
        "`unplaced`, lines of one hand-written script (`raw_override`, at most 20,000 "
        "characters; only lines of three words or more are listed)."
    ),
    "POST /v1/agents/{agent_id}/script/versions/{version}/restore": BoundedByConstruction(
        by="one version copied into the draft: a `CallScript` under the same "
        "`calevate_shared.call_script` `max_length` ceilings as `GET .../script`."
    ),
    "POST /v1/agents/{agent_id}/script/preview": BoundedByConstruction(
        by="one composed prompt's size: `layers` is one row per prompt layer and "
        "`script_parts` one row per `CallScript` section, both fixed sets in "
        "`agents/prompt_size.py`, never a caller's row count."
    ),
    "GET /v1/agents/{agent_id}/script/tests": BoundedByConstruction(
        by="one run's `results`, at most `MAX_GENERATED` scenarios, `MAX_REAL_QUESTIONS` "
        "questions from real calls, `MAX_SAVED` saved "
        "tests and six re-asked failures, each of at most `MAX_TURNS` turns, `history`, "
        "at most `HISTORY_RUNS` runs (`agents.test_conversations` constants), and the run's "
        "improvement: at most `MAX_EDITS` edits (`agents/script_edits`) and `MAX_FACTS` facts "
        "(`workers/agent_test_ai.proposal_from_model`) and `for_keys`, the keys of one run's "
        "scenarios."
    ),
    "POST /v1/agents/{agent_id}/script/tests/{run_id}/results/{key}/wrong": BoundedByConstruction(
        by="the same shape as `GET .../script/tests`, read back after the label is written."
    ),
    "POST /v1/agents/{agent_id}/script/tests/{run_id}/improvement/settle": BoundedByConstruction(
        by="the same shape as `GET .../script/tests`, read back after the proposal is settled."
    ),
    "POST /v1/agents/{agent_id}/script/tests/{run_id}/improvement/apply": BoundedByConstruction(
        by="one `CallScript` under the `calevate_shared.call_script` ceilings, and `skipped`, "
        "ids of the kept edits sent, at most `script_edits.MAX_EDITS` (`ApplyEditsIn.edits` "
        "max_length)."
    ),
    "POST /v1/agents/{agent_id}/script/tests": BoundedByConstruction(
        by="the same shape as `GET .../script/tests`: one run's scenarios under "
        "`agents.test_conversations` constants and at most `HISTORY_RUNS` history rows."
    ),
    # Calling setup (D-716): one plan per client.
    "GET /v1/lead-calling": BoundedByConstruction(
        by="one client's plan: `days` is at most the seven weekdays, `holidays` at most 60 "
        "(`LeadCallingIn` max_length and `lead_policy.validated`), `always_applied` the "
        "`policy_routes.ALWAYS_APPLIED` constant."
    ),
    "PUT /v1/lead-calling": BoundedByConstruction(
        by="the same one plan as `GET /v1/lead-calling`, read back after the save."
    ),
    # Studio per-client BYOK (D-717): an operator's switch-off decision reads the whole set.
    "GET /v1/ops/voices/studio-voices": BoundedByConstruction(
        by="`missing` is at most the five readiness steps in `StudioReadiness.missing`; "
        "`workspaces` is one row per signed client running Studio in its own workspace "
        "(`tenancy.engine_workspace.studio_workspaces`, LIMIT 1000), bounded by the clients "
        "we provision rather than by anything a client mints. A page would hide a workspace "
        "from the operator deciding whether the developer switch can go off."
    ),
    # The Voices page writes (D-721): each answers with ONE voice. Its only list is that
    # voice's `languages`, the handful the vendor's listing gives it.
    "POST /v1/ops/voices/hosted": BoundedByConstruction(
        by="one `HostedVoiceOut`; `languages` is the one voice's vendor-listed languages."
    ),
    "PATCH /v1/ops/voices/hosted": BoundedByConstruction(
        by="one `HostedVoiceOut`; `languages` is the one voice's vendor-listed languages."
    ),
    "PATCH /v1/ops/voices/hosted/display-name": BoundedByConstruction(
        by="one `HostedVoiceOut`; `languages` is the one voice's vendor-listed languages."
    ),
    "PATCH /v1/ops/voices/hosted/person-clone": BoundedByConstruction(
        by="one `HostedVoiceOut`; `languages` is the one voice's vendor-listed languages."
    ),
    "POST /v1/ops/voices/hosted/clone-consent": BoundedByConstruction(
        by="one `HostedVoiceOut`; `languages` is the one voice's vendor-listed languages."
    ),
    "POST /v1/ops/voices/hosted/preview": BoundedByConstruction(
        by="one `HostedVoiceOut`; `languages` is the one voice's vendor-listed languages."
    ),
    "POST /v1/ops/voices/hosted/preview/fetch": BoundedByConstruction(
        by="one `HostedVoiceOut`; `languages` is the one voice's vendor-listed languages."
    ),
    "POST /v1/ops/voices/clones": BoundedByConstruction(
        by="one `HostedVoiceOut` for the clone just made; `languages` is that voice's own."
    ),
    # D-720: the surfaces besides the phone the engine reports for one agent.
    "GET /v1/agents/{agent_id}/engine-state": BoundedByConstruction(
        by="`answers_also_on` is the engine's `voice.surfaces` for ONE agent less the phone: "
        "a vendor enum of channels (website call button, WhatsApp), never a row count."
    ),
    # D-722: `choices` is every business type, a static seed table, never a row count.
    "GET /v1/admin/tenants/{tenant_id}/business-type": BoundedByConstruction(
        by="`choices` is one row per `scripts/seed.BUSINESS_TYPE_LABELS` entry, a fixed "
        "product list whose size is a product decision."
    ),
    "POST /v1/admin/tenants/{tenant_id}/business-type/confirm": BoundedByConstruction(
        by="`choices` is one row per `scripts/seed.BUSINESS_TYPE_LABELS` entry, a fixed "
        "product list whose size is a product decision."
    ),
    "POST /v1/admin/tenants/{tenant_id}/business-type/suggest": BoundedByConstruction(
        by="`choices` is one row per `scripts/seed.BUSINESS_TYPE_LABELS` entry, a fixed "
        "product list whose size is a product decision."
    ),
    "POST /v1/ops/voices/studio-voices/enable": BoundedByConstruction(
        by="the same `StudioVoicesOut` as `GET /v1/ops/voices/studio-voices`, re-read after "
        "the switch."
    ),
    "GET /v1/ops/voices/own-model": BoundedByConstruction(
        by="`missing` is at most the four readiness steps in `OwnModelReadiness.missing`; "
        "`offerable_models` is a subset of the Google models `calevate_shared.engine."
        "GoogleDirectModel` declares; `workspaces` is one row per signed client on our model "
        "(`tenancy.engine_workspace.own_model_workspaces`, LIMIT 1000), bounded by the clients "
        "we provision."
    ),
    "POST /v1/ops/voices/own-model/enable": BoundedByConstruction(
        by="the same `OwnModelOut` as `GET /v1/ops/voices/own-model`, re-read after the act."
    ),
    "POST /v1/ops/voices/own-model/developer": BoundedByConstruction(
        by="the same `OwnModelOut` as `GET /v1/ops/voices/own-model`, re-read after the act."
    ),
    "GET /v1/billing/topups/packs": BoundedByConstruction(
        by="`packs` is one row per member of `billing.credit_packs.PACK_CATALOGUE`, a static "
        "tuple whose size is a pricing decision, never a caller's row count."
    ),
    "GET /v1/public/rate-card": BoundedByConstruction(
        by="the same `CreditPacksOut` the `/packs` read returns, from the same builder "
        "(`payment_routes.rate_card_out`) — one row per `PACK_CATALOGUE` member."
    ),
    "GET /v1/ops/secrets": BoundedByConstruction(
        by="the vendor-credential registry in `ops/secrets.py` — one row per known key."
    ),
    "GET /v1/ops/model-prices": BoundedByConstruction(
        by="one row per model in `calevate_shared.engine.LLM_MODELS`, a closed catalogue "
        "whose size is a decision-log entry — never a caller's row count."
    ),
    "POST /v1/ops/rate-card": BoundedByConstruction(
        by="the card the operator just recorded, echoed back — one cell per credit pack in "
        "`billing/credit_packs.PACK_CATALOGUE` times one per voice tier in "
        "`billing/rates.VOICE_TIERS`, both committed constants a reviewed commit changes. "
        "The REQUEST is bounded too (`RateCardIn.cells` has a `max_length`), and a body "
        "carrying anything but exactly those twelve cells is refused by name before "
        "anything is written."
    ),
    "GET /v1/ops/rate-card": BoundedByConstruction(
        by="`cells` is the CARD — one cell per credit pack in `billing/credit_packs"
        ".PACK_CATALOGUE` times one per voice tier in `billing/rates.VOICE_TIERS`, both "
        "committed constants a reviewed commit changes. Twelve rows today. There is no "
        "page size DELIBERATELY: an operator commits a price against the whole ladder, "
        "and a card read back one page at a time is the one thing they must not be able "
        "to do. `pending` is bounded separately by `list_rates.PENDING_CARD_LIMIT`, in the "
        "SQL rather than in Python: a scheduled card can only be minted by a step-up "
        "confirmed operator write, so it is a sanity ceiling on our own writes and not a "
        "page size on somebody's rows."
    ),
    "GET /v1/ops/dashboard-data-use": BoundedByConstruction(
        by="one row per DECLARED LLM leg — `get_args(calevate_shared.engine.LlmProvider)`, "
        "a three-member Literal a reviewed commit widens, never a caller's row count."
    ),
    "GET /v1/ops/in-call-data-use": BoundedByConstruction(
        by="one row per provider in `ops/in_call_data_use_routes.IN_CALL_PROVIDERS`, a "
        "constant tuple (our own model's provider), never a caller's row count."
    ),
    "GET /v1/ops/voices/own-model/cache-shares": BoundedByConstruction(
        by="at most one row per `call_id` the request names, and `call_id` is "
        "`Query(max_length=200)`; `ops/own_model_cache.MAX_CALLS` caps the read too."
    ),
    "POST /v1/ops/secrets/kek/rewrap": BoundedByConstruction(
        by="`unreadable` is at most one entry per registry key, same registry as above."
    ),
    "GET /v1/ops/platform": BoundedByConstruction(
        by="`by_job` is one entry per registered ARQ job (`workers/settings.FUNCTIONS`)."
    ),
    "POST /v1/ops/platform": BoundedByConstruction(
        by="`by_job` is one entry per registered ARQ job (`workers/settings.FUNCTIONS`)."
    ),
    "GET /v1/ops/audit/verify": BoundedByConstruction(
        by="`compliance.audit._MAX_REPORTED_BREAKS` caps the reported breaks at 20; the "
        "full count rides as `breaks_found`, an integer."
    ),
    "GET /v1/dashboard": BoundedByConstruction(
        by="`daily_7d` is seven days — the window is a constant in the query, not a "
        "parameter, so there is nothing a caller can widen."
    ),
    "POST /v1/auth/signup": BoundedByConstruction(
        by="`next_steps` is the fixed onboarding checklist in `tenancy/signup.py`."
    ),
    "GET /v1/compliance/caller-notice": BoundedByConstruction(
        by="one entry per declared collection purpose and retention class — both constants."
    ),
    "GET /v1/campaigns/{campaign_id}/launch-check": BoundedByConstruction(
        by="`blockers` is at most one per launch-gate RULE, a fixed set."
    ),
    "GET /v1/admin/tenants/{tenant_id}": BoundedByConstruction(
        by="`holds` is at most one per compliance hold rule (`admin/holds.py`), a fixed set."
    ),
    "GET /v1/agents/{agent_id}/experiment": BoundedByConstruction(
        by="two variants by construction, and `metrics` is the CONVERSION_METRICS constant."
    ),
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/experiment": BoundedByConstruction(
        by="`variant_ids` is the two arms this call just created."
    ),
    "POST /v1/campaigns/{campaign_id}/recurrence": BoundedByConstruction(
        by="`days` is ISO weekdays — seven, enforced by the request model."
    ),
    "GET /v1/campaigns/{campaign_id}": BoundedByConstruction(
        by=(
            "`recurrence.days` is seven; `schedule_blocked_rules`, `not_calling` and "
            "`retry_policy.gaps_minutes` are one per gate rule and at most four gaps."
        )
    ),
    "GET /v1/campaigns/{campaign_id}/results": BoundedByConstruction(
        by=(
            "`recent_leads` is `campaigns.results.RECENT_LEADS` in the LIMIT; the maps are "
            "keyed by the outcome, outcome-tag and sentiment enums."
        )
    ),
    "POST /v1/lead-sources/{webhook_id}/test": BoundedByConstruction(
        by="`steps` is the fixed dry-run ladder in `ingest/service.py`."
    ),
    "POST /v1/leads/views": BoundedByConstruction(
        by="`stale_*_keys` are bounded by `MAX_VIEW_FILTER_KEYS` (10) on the view itself."
    ),
    "PATCH /v1/leads/views/{view_id}": BoundedByConstruction(
        by="`stale_*_keys` are bounded by `MAX_VIEW_FILTER_KEYS` (10) on the view itself."
    ),
    "GET /v1/leads/views": BoundedByConstruction(
        by="`crm.schemas.MAX_SAVED_VIEWS_PER_USER` (50), enforced at create time, and the "
        "list is scoped to the caller's own views."
    ),
    "GET /v1/calls/views": BoundedByConstruction(
        by="`crm.schemas.MAX_SAVED_VIEWS_PER_USER` (50) per screen, enforced at create time, "
        "and the list is scoped to the caller's own Calls views."
    ),
    "GET /v1/leads/facets": BoundedByConstruction(
        by="`crm.service.MAX_FACET_FIELDS` (8) x `MAX_FACET_VALUES` (50)."
    ),
    "POST /v1/leads/facets": BoundedByConstruction(
        by="`crm.service.MAX_FACET_FIELDS` (8) x `MAX_FACET_VALUES` (50)."
    ),
    "POST /v1/leads/bulk": BoundedByConstruction(
        by="`failures` is at most one per submitted id, and `MAX_BULK_LEADS` (500) bounds "
        "the request."
    ),
    "GET /v1/agents/{agent_id}": BoundedByConstruction(
        by="`extraction_fields` is one agent's extraction schema, bounded by the schema "
        "editor's own field ceiling."
    ),
    # The two D-440 writes answer with the SAME `AgentOut` — one agent, read back through
    # the one roster query — so they inherit the bound above rather than needing a page.
    "POST /v1/agents": BoundedByConstruction(
        by="one agent's `AgentOut`; `extraction_fields` is that agent's extraction schema, "
        "bounded by the schema editor's own field ceiling (and empty on a fresh agent)."
    ),
    "PATCH /v1/agents/{agent_id}": BoundedByConstruction(
        by="one agent's `AgentOut` — the same bound as its GET immediately above."
    ),
    "GET /v1/agents/{agent_id}/pending": BoundedByConstruction(
        by="one entry per publishable ATTRIBUTE of one agent — a fixed list of fields."
    ),
    "GET /v1/kb/sources/{source_id}/preview": BoundedByConstruction(
        by="`SubmitIn.body` is capped at 200,000 characters and `kb.service.MAX_CHUNK_CHARS` "
        "is 700, so one source is at most ~286 chunks."
    ),
    "GET /v1/calls/{call_id}": BoundedByConstruction(
        by="the turns of ONE call, and `agents.models.CALL_CAP_MAX_S` (3600) bounds how "
        "long a call may be."
    ),
    "GET /v1/calls/{call_id}/transcript/raw": BoundedByConstruction(
        by="the turns of ONE call, bounded by `CALL_CAP_MAX_S` (3600) like the redacted twin."
    ),
    "GET /v1/admin/qa-samples/{sample_id}": BoundedByConstruction(
        by="the turns of ONE call, bounded by `CALL_CAP_MAX_S` (3600)."
    ),
    "GET /v1/admin/tenants/{tenant_id}/invoice": BoundedByConstruction(
        by="line items are one per metered UNIT KIND and taxes one per GST component — "
        "both fixed by the rate card, not by usage volume."
    ),
    "GET /v1/billing/invoice": BoundedByConstruction(
        by="line items are one per metered UNIT KIND and taxes one per GST component — "
        "both fixed by the rate card, not by usage volume."
    ),
    # --- D-695 the business profile ------------------------------------------------------
    "GET /v1/business-profile": BoundedByConstruction(
        by="one profile, whose every list is capped by the model that writes it "
        "(`tenancy/business_profile.MAX_*`: 20 branches, 100 services, 50 FAQs, 50 staff, "
        "10 contacts, 6 languages), seven days of hours, eight setup steps, and at most one "
        "blocker per go-live rule."
    ),
    "PATCH /v1/business-profile": BoundedByConstruction(
        by="the same one capped profile the GET returns, after the save."
    ),
    "POST /v1/business-profile/setup": BoundedByConstruction(
        by="the same one capped profile the GET returns, after the step moves."
    ),
    "GET /v1/admin/tenants/{tenant_id}/business-profile": BoundedByConstruction(
        by="the same one capped profile, plus `merge_notes`, written once by the D-695 "
        "data move: at most one note per field it merged."
    ),
    "GET /v1/admin/tenants/{tenant_id}/commercial-terms": BoundedByConstruction(
        by="`history` is one row per re-pricing of one client, written by an operator "
        "through `POST` on the same path — a commercial event, not a data volume."
    ),
    "GET /v1/campaigns/numbers": BoundedByConstruction(
        by="the numbers WE provision for a tenant; a client cannot mint one "
        "(`POST /v1/numbers/purchase` is `org:manage` and provisions through the engine)."
    ),
    "GET /v1/campaigns/templates": BoundedByConstruction(
        by="DLT templates, which only an operator can file (`POST /v1/admin/tenants/"
        "{tenant_id}/dlt-templates`) and which the regulator's own registration bounds."
    ),
    # --- bounded by the number of PEOPLE WE EMPLOY ----------------------------------
    "GET /v1/admin/operators": BoundedByConstruction(
        by="one row per LIVE operator account — an allowlist only a superadmin can add "
        "to (`POST /v1/admin/operators`, `admin:operators`), so its length is a hiring "
        "decision and never a caller's row count. Revoked rows accumulate and are "
        "deliberately NOT listed: they survive because eight tables reference them as "
        "the record of who decided what, and 'who was removed and when' is the audit "
        "log's question. A LIMIT would hide an administrator from the only screen that "
        "lists who can administer the platform."
    ),
    # --- bounded by the number of CLIENTS, which we provision -----------------------
    "GET /v1/admin/tenants/{tenant_id}/readiness": BoundedByConstruction(
        by="one row per account-level compliance gate, from a closed vocabulary the code "
        "declares (`check_docs_drift` counts the same names in SEC-COMP \u00a73). It does not "
        "grow with a client's data, and a page of it would be meaningless: the question "
        "is 'what is blocking this account', which a truncated answer gets wrong."
    ),
    "GET /v1/admin/client-health": BoundedByConstruction(
        by="one row per signed client, ranked worst-first — a LIMIT would truncate BEFORE "
        "the triage sort and hide the account most in trouble. Watched by "
        "`WALK_BUDGET_S`, same as the directory above."
    ),
    "GET /v1/admin/client-health/{tenant_id}": BoundedByConstruction(
        by="ONE client's judgement from `admin/health.tenant_health`: `signals` holds at most one "
        "entry per signal rule, each appended at most once from that function's closed set, "
        "and each signal's `causes` are the gates' own rule names (`read_tenant_holds` plus "
        "the PE, spend-cap and credit gates). Neither grows with the client's data."
    ),
    "GET /v1/admin/spend": BoundedByConstruction(
        by="one row per live client, ranked worst-margin-first — a LIMIT would truncate "
        "BEFORE that sort and hide the account we are losing the most on, which is the "
        "one an operator opened the board for. Watched by `FLEET_BUDGET_S` in "
        "`billing/spend_routes.py`, the same trade `GET /v1/admin/client-health` makes."
    ),
    "GET /v1/admin/spend/tts-speaking-rate": BoundedByConstruction(
        by="`by_provider` is one row per VOICE VENDOR — `ops/model_pricing.TTS_PROVIDERS`, "
        "a two-member tuple this repo widens by a reviewed commit and never by anyone's "
        "row count. The measurement itself is already pooled into one summary before it "
        "reaches the response, so nothing here grows with the call volume it read."
    ),
    "GET /v1/admin/compliance/holds": BoundedByConstruction(
        by="one row per signed client currently held by a human gate — a work queue that "
        "is empty in the steady state and is bounded by the client count in the worst."
    ),
    "GET /v1/admin/onboarding/unfinished": BoundedByConstruction(
        by="one row per signed client whose wizard is incomplete — bounded by the client "
        "count, and the whole point of the screen is that nothing is missed."
    ),
    # --- bounded by one data subject's own history ----------------------------------
    "POST /v1/compliance/subject-export": BoundedByConstruction(
        by="one PERSON's own record, keyed on their phone number. Completeness is the "
        "legal obligation (DPDP access request) — a truncated subject-access document "
        "is a non-compliant one, so the bound is the subject's own call history rather "
        "than a page size."
    ),
    "POST /v1/compliance/deletion-requests": BoundedByConstruction(
        by="the erasure proof for ONE subject: what was erased and what was not, bounded "
        "by that subject's own rows. The proof is evidence and must be whole."
    ),
    "GET /v1/compliance/deletion-requests/{request_id}": BoundedByConstruction(
        by="the erasure proof for ONE subject — see the POST above."
    ),
    "POST /v1/admin/tenants/{tenant_id}/erasure": BoundedByConstruction(
        by="the erasure proof for ONE tenant wind-down: limitations and unerased "
        "references, which are evidence and must be whole."
    ),
    "GET /v1/admin/tenants/{tenant_id}/erasure/{request_id}": BoundedByConstruction(
        by="the erasure proof for ONE tenant wind-down — see the POST above."
    ),
}


class ListBoundsError(RuntimeError):
    """The check could not be run — a broken premise, not a verdict."""


def build_app() -> FastAPI:
    from apps.api.main import app

    return app


def _returns_a_list(route: APIRoute) -> bool:
    """Can this route's declared response contain a list, at any depth?

    Reads the RESPONSE MODEL rather than the handler, because the model is the thing
    that is serialised — a route whose service returns a generator still materialises
    it here.
    """
    from pydantic import BaseModel

    model = route.response_model
    if model is None:
        return False
    if typing.get_origin(model) is list:
        return True

    seen: set[type] = set()

    def walk(candidate: object, depth: int) -> bool:
        if depth > _MAX_DEPTH:
            return False
        if not (isinstance(candidate, type) and issubclass(candidate, BaseModel)):
            return False
        if candidate in seen:
            return False
        seen.add(candidate)
        # A model that names a class defined below it is left with unresolved field types
        # until something rebuilds it, so the answer would depend on which test ran first.
        if not candidate.__pydantic_complete__:
            candidate.model_rebuild()
        for field in candidate.model_fields.values():
            annotation = field.annotation
            args = typing.get_args(annotation)
            if typing.get_origin(annotation) is list:
                return True
            for arg in args:
                if typing.get_origin(arg) is list:
                    return True
                if walk(arg, depth + 1):
                    return True
            if walk(annotation, depth + 1):
                return True
        return False

    return walk(model, 0)


def _bounding_parameter(route: APIRoute) -> str | None:
    """The name of a bounded `limit`-like parameter, query or body, or None.

    BOUNDED, not merely present: `limit: int = Query(50)` with no `le` is a parameter a
    caller sets to a million. The upper bound may be written as `le=` on the `Query` or
    as an `annotated_types.Le` in the field's metadata, which is where Pydantic v2 puts
    it — both are read, because which one a route uses is a spelling choice.
    """
    from pydantic import BaseModel

    def upper_bound(field_info: object) -> bool:
        if getattr(field_info, "le", None) is not None:
            return True
        if getattr(field_info, "lt", None) is not None:
            return True
        return any(
            getattr(entry, "le", None) is not None or getattr(entry, "lt", None) is not None
            for entry in getattr(field_info, "metadata", ())
        )

    for param in route.dependant.query_params:
        if param.name in _BOUNDING_PARAMS and upper_bound(param.field_info):
            return param.name

    body = route.body_field
    if body is not None:
        annotation = body.field_info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            for name, field in annotation.model_fields.items():
                if name in _BOUNDING_PARAMS and upper_bound(field):
                    return name
    return None


def list_routes(app: FastAPI) -> dict[str, APIRoute]:
    """`"METHOD /path"` -> route, for every route whose response can hold a list."""
    from apps.api.core.rbac import iter_api_routes

    found: dict[str, APIRoute] = {}
    for route in iter_api_routes(app):
        if not _returns_a_list(route):
            continue
        for method in sorted(route.methods or []):
            found[f"{method} {route.path}"] = route
    return found


def unbounded(routes: dict[str, APIRoute]) -> list[str]:
    """A list route with neither a bounded parameter nor a declaration."""
    problems: list[str] = []
    for key, route in sorted(routes.items()):
        if _bounding_parameter(route) is not None:
            continue
        if key in BOUNDED_LISTS:
            continue
        problems.append(
            f"{key} can return a list, takes no bounded `limit`, and is in no BOUNDED_LISTS entry"
        )
    return problems


def stale_declarations(routes: dict[str, APIRoute]) -> list[str]:
    """A declaration outliving its route, or one that stopped being needed.

    The second half matters as much as the first: a route that GAINED a `limit` keeps
    an entry here saying it does not need one, and the next reader believes the entry.
    """
    problems: list[str] = []
    for key in sorted(BOUNDED_LISTS):
        route = routes.get(key)
        if route is None:
            problems.append(
                f"{key} is declared bounded-by-construction but is not a live list route "
                "— delete the entry"
            )
            continue
        parameter = _bounding_parameter(route)
        if parameter is not None:
            problems.append(
                f"{key} now takes a bounded `{parameter}`, so its BOUNDED_LISTS entry is "
                "a false statement about the route — delete it"
            )
    return problems


def thin_reasons() -> list[str]:
    return sorted(
        f"{key}: reason is {len(entry.by.strip())} characters; {_MIN_REASON} is the floor"
        for key, entry in BOUNDED_LISTS.items()
        if len(entry.by.strip()) < _MIN_REASON
    )


def audit(app: FastAPI) -> list[str]:
    routes = list_routes(app)
    if not routes:
        raise ListBoundsError(
            "no list-returning routes found. Either route discovery is broken or the "
            "response-model walk is — a clean report from a check that found nothing to "
            "check is not a clean report."
        )
    return [*unbounded(routes), *stale_declarations(routes), *thin_reasons()]


def main() -> int:
    try:
        problems = audit(build_app())
    except ListBoundsError as exc:
        print(f"FAIL check_list_bounds: {exc}", file=sys.stderr)
        return 2

    if problems:
        print("FAIL check_list_bounds — a response can grow with somebody's data:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\n  Either take a bounded page (`limit: int = Query(50, ge=1, le=200)`, and "
            "put the LIMIT in the query) or add a BOUNDED_LISTS entry naming what bounds "
            "the list instead.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK check_list_bounds: {len(BOUNDED_LISTS)} lists bounded by construction, "
        "every other list route takes a bounded page"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
