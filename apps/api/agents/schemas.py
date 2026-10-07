"""The agents module's wire models.

`crm/schemas.py`'s shape, and it exists for `crm/schemas.py`'s reason plus one that is
specific to this module.

**WHY `AgentOut` LEFT `routes.py`.** It was declared there, beside the roster query that
fills it and the mapper that builds it, which was correct while the only caller was an
endpoint. It stopped being correct when a second caller appeared that is not a request:
`copilot/tools.py::agents_list` answers "which agents do I have, and are they published?"
and had exactly two ways to get that answer — call the route handler (a layering inversion
this repo has no precedent for) or write a second copy of the roster SQL (the "two
spellings of one query" defect the quality bar names). Both were refused, and the read
tool was dropped rather than built on either. This file is the third option and it is the
one BACKEND-PATTERNS §1 already describes: the response model lives in `schemas.py`, the
query and the mapper live in `service.py`, and `routes.py` is thin. Nothing about the wire
contract changed in the move — `scripts/check_openapi_fresh.py` is what proves that.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from calevate_shared.engine import LlmTier
from calevate_shared.extraction import ExtractionField
from pydantic import BaseModel, ConfigDict

from apps.api.agents.languages import Language
from apps.api.agents.llm_models import LlmModelSource
from apps.api.agents.models import AgentDirection, AgentStatus


class AgentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    #: TYPED, not `str` (D-440). Both columns carry a CHECK constraint rendered from these
    #: exact Literals (`agents/models.py`), `tests/orm_schema_fidelity_test.py` proves the
    #: constraint is really in the database, and a generated TypeScript client that gets a
    #: union here can exhaustively switch on it instead of comparing strings. A row that
    #: somehow held anything else fails serialization loudly, which is the same trade
    #: `_load_agent`'s direction TypeGuard makes and for the same reason: a status the
    #: platform has never heard of, on an agent answering a client's phone, is not a thing
    #: to render.
    direction: AgentDirection
    #: `live` IS "active" and `paused` IS "inactive" — the labels are the UI's, the
    #: vocabulary is the database's, and `agents/models.AgentStatus` argues why they differ.
    status: AgentStatus
    #: Set only while `status == "archived"`; a CHECK constraint holds the pair together.
    archived_at: datetime | None
    #: TYPED for `direction`'s reason above, and it could not be until the column was
    #: bounded: `agents.language_primary` was a bare `Text` with no CHECK, so a row could
    #: hold anything and a Literal here would have turned a schema fault into a 500 on a
    #: roster read. Migration `c7a41e8b52d9` closes that end, `ck_agents_language_primary_
    #: offered` is the constraint, and the screens get an exhaustive union instead of a
    #: string they have to guard (`apps/web/src/lib/agentState.LANGUAGE_NAMES`).
    language_primary: Language
    # THE LEGACY BUNDLE, kept on the wire for step 1 of D-163's two-step deprecation:
    # both sentences joined whatever the toggles say. Read it as "the notices this agent
    # HAS", never as "what it says" — `opening_line` below is what it says.
    disclosure_line: str
    # THE SPLIT (D-163). Shown to the client verbatim: they are legally the Principal
    # Entity, so they need to be able to read what their agent announces — and, now that
    # each half is theirs to switch off, to see the two halves separately.
    ai_disclosure_line: str
    ai_disclosure_enabled: bool
    recording_notice_line: str
    recording_notice_enabled: bool
    #: SENTENCE THREE AND ITS ONLY SWITCH (D-507). The line is on file for every agent
    #: whether or not memory is on; `caller_memory_enabled` is what decides whether it is
    #: spoken, and there is deliberately no `caller_memory_notice_enabled` beside it — the
    #: state "remembers a caller and does not say so" is not constructible, and a screen
    #: that showed a switch for the sentence would be advertising one.
    #:
    #: BOTH FIELDS, not just the line: the client screen has to be able to say WHY the
    #: sentence appears in `opening_line`, and "because this agent remembers callers" is a
    #: fact only the flag carries.
    caller_memory_notice_line: str
    caller_memory_enabled: bool
    #: What a caller actually hears first, composed by the server from the two toggles.
    #: Empty string = this agent volunteers neither notice and opens on its script.
    #: Composed here rather than left to the screen because a UI that re-joined the two
    #: sentences itself would be a second implementation of a compliance rule.
    opening_line: str
    #: The one sentence no toggle reaches, in words a client can read. Server-composed for
    #: the same reason the lane table's `why` strings are: a screen that paraphrases this
    #: is a screen that can accidentally promise the opposite. REQUIRED rather than
    #: defaulted: its recording half depends on the engine (`truthful_answer_promise`), so
    #: a default would be a wording composed without the fact that decides it.
    truthful_answer_rule: str
    engine: str
    published: bool
    #: HOW MANY LINES THIS AGENT ANSWERS IN PARALLEL — the honest per-agent deployment
    #: fact, and deliberately the only one (D-440). Inbound concurrency is a per-number
    #: binding at the engine and the vendor documents no inbound limit, so a live agent
    #: bound to three numbers picks up three simultaneous calls. OUTBOUND concurrency is
    #: not a property of an agent at all: it is an account-level pool shared by every
    #: campaign on the platform (`workers/campaign_dispatch.py`), so there is no per-agent
    #: number that could be true, and this response does not invent one.
    #:
    #: Counts the numbers BOUND to the agent in our records. A non-live agent shows its
    #: bindings too — they are what activating it would start answering — and the engine
    #: is told to release them on deactivate and archive.
    inbound_number_count: int
    #: THE AGENT'S AI MODEL, AS THE TIER A CLIENT CHOSE IT BY (D-680) — never a model id or a
    #: provider (D-679); `agents/llm_tiers.py` maps the stored model to the tier it is shown as.
    #: `llm_tier` is what was chosen ON THIS AGENT, `null` meaning "inherit the account's
    #: default" (D-454), kept apart from the tier in force so a screen can tell an owner
    #: whether clearing it would change anything.
    llm_tier: LlmTier | None
    #: The tier in force after `agent -> organization -> platform`. Never null.
    llm_tier_effective: LlmTier
    llm_tier_label: str
    #: Which rung supplied it (`agents/llm_models.LlmModelSource`).
    llm_tier_source: LlmModelSource
    #: Does the plan's model surcharge apply to this agent's minutes — the model in force is
    #: an upgrade AND the client chose it (`billing/rates.llm_surcharge_applies`). The rupee
    #: figure is `upgrade_surcharge_inr_per_minute` on the account's model settings.
    llm_surcharged: bool
    #: A voice and a model from the voice platform's OWN catalogue (D-678), or `null` for
    #: the platform's default. Only meaningful where `GET /v1/agents/engine-catalogue`
    #: answers `available: true`. The model is the catalogue's OPAQUE id
    #: (`llm_tiers.engine_model_token`), never the engine's own model name.
    engine_voice_id: str | None = None
    engine_model_id: str | None = None
    extraction_fields: list[ExtractionField] = []


__all__ = ["AgentOut"]
