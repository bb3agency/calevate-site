"""The copilot's ACTION framework: what an action is, who may run one, and — the part
everything else hangs off — WHICH TIER it is in.

This module holds no action. It holds the vocabulary `write_tools.py` (the four tools that
shipped first) and `agent_actions.py` (build, publish, launch) both speak, so that there is
ONE mechanism rather than two that agree today. It was extracted rather than invented: every
type below was already in `write_tools.py` and is unchanged apart from the two fields
§"THE TIER" and §"WHAT AN APPROVAL HAS TO SAY" add.

═══ THE TIER, AND WHY IT IS A FIELD WITH NO DEFAULT ═══

The founder's decision (D-500) is that not every action needs a click:

* `immediate` — reversible, reaches no caller, spends no money. Runs inside the answer.
* `confirm`   — reaches a caller or moves money. Runs only after a person clicks Confirm
                on a second, separately authenticated request.

Speed is what that buys and the price is precise: **a mis-tiered action is an incident.** A
campaign launched without a click is calls to strangers that cannot be recalled. So the tier
is a REQUIRED field on the tool definition with NO DEFAULT — a new action that forgets to
state its tier fails to construct, rather than inheriting the permissive one — and it is
read only from the registry. It is never computed at runtime, never derived from the
arguments, and never anything the model says: `service.py` dispatches on `tool.tier` and on
nothing else, `plan_write` refuses to mint a token for an `immediate` tool, and
`run_immediate` refuses to run a `confirm` one. Both refusals are code, both fail closed,
and `actions_test.py` enumerates the registry to assert that every action that can reach a
caller or move money is `confirm` — derived from the registry, not retyped.

The tier is NOT a permission and does not replace one. `ActionTool.permission` is still the
one the equivalent BUTTON declares, still checked twice (advisory at propose time, binding
at the door), and a Tier 1 action checks it exactly as hard as a Tier 2 one. Tier answers
"does a human have to click?"; permission answers "may this human do it at all?".

═══ WHAT AN APPROVAL HAS TO SAY ═══

`Plan` gained `cost` and `reversal`, both required. An "Approve / Deny" button with a verb
on it gets a worse decision than one that states what changes, what it costs and whether it
can be taken back — and the two facts a person most needs before a launch are exactly the
two nothing in the old shape could carry. Required rather than optional for the tier's own
reason: an action whose author did not think about reversibility is an action whose author
did not think about it, and `None` is a legitimate answer for `cost` ("nothing") but never
for `reversal`.

═══ WHERE THE MODEL IS NOT TRUSTED ═══

Unchanged and worth restating because the surface just grew: a planner READS. It resolves
ids under the caller's own RLS session, normalises the arguments itself, and returns the
canonical dict — so what executes is what was described, not what the model asked for. The
vendor of a tool-calling model documents the failure this defends against in as many words:
"If the user's prompt doesn't include enough information to fill all the required parameters
for a tool ... it might also infer a reasonable value", illustrated with a `get_weather` call
carrying a `location` and a `unit` the user never supplied
(platform.claude.com/docs/en/agents-and-tools/tool-use/overview, "When required parameters
are missing", read 1 Sep 2026). A model that infers a missing argument is a model that will
infer a missing agent id.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.prompt import function_tool
from apps.api.core.context import Principal
from apps.api.core.rbac import MUTATING_PERMISSIONS, Permission, role_has

# The one predicate for "may this person curate knowledge" — the role table PLUS the
# owner's per-account switch. Imported rather than re-derived so the assistant and the
# Add-Knowledge form cannot come to disagree about one person (see `may_act`).
from apps.api.kb.curation import CURATE_PERMISSION, may_curate_knowledge

#: WHICH GATE AN ACTION STANDS BEHIND. See the module docstring — required on every tool,
#: no default, and the only thing `service.py` dispatches on.
#:
#: `immediate` is NOT "unaudited" and NOT "unchecked": it writes an `audit_log` row naming
#: the person, it checks the same permission, it runs the same service function, and it
#: claims an idempotency record first. What it skips is the CLICK, and only because the
#: act it performs is reversible, reaches no caller and spends nothing.
ActionTier = Literal["immediate", "confirm"]

#: Every tier, so a test can enumerate them rather than retyping the union.
ACTION_TIERS: Final[tuple[ActionTier, ...]] = ("immediate", "confirm")


class WriteRefusedError(Exception):
    """The model asked for something this request cannot do, in a way it could FIX.

    Sibling of `service.FillRefusedError` and it exists for the same reason: the refusal is
    handed BACK to the model as a tool result so it can correct itself inside the turn cap,
    rather than surfacing to a person as a dead end. A `ProblemError` raised by a service
    function underneath (a 404 agent, a 409 campaign, a blocked launch) is NOT this — that
    is a fact about the world the model cannot argue with. It reaches the person, and — see
    `service._run_action_call` — it is also reported back so the assistant can relay the
    refusal and its remediation instead of retrying around it.

    `reason` names ids and shapes, never a value (hard rule 6): it reaches a log line and a
    prompt.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class ToolActor:
    """Who an action is run for. Ids only (hard rule 6).

    A narrowed `Principal`: the two fields the copilot cannot work without are Optional on
    that dataclass (an admin-realm principal has no tenant), and threading `UUID | None`
    into a signing function is how a `None` ends up in a `sub` claim. `actor_for` is the one
    place the narrowing happens and it refuses rather than defaults.
    """

    tenant_id: UUID
    user_id: UUID
    role: str
    impersonating: bool


def actor_for(principal: Principal) -> ToolActor | None:
    """The copilot actor behind this principal, or None if there is not one.

    None is not an error here: `service.run_copilot` is reachable in tests and from callers
    that hold no principal, and a tool that cannot name an actor simply refuses (see
    `plan_write` and `run_immediate`). Refusing INSIDE the tool rather than by dropping the
    tool from the schema is deliberate — the tool list is the cacheable prompt prefix
    (`prompt.py`, point 1) and must be byte-identical on every request.
    """
    if principal.tenant_id is None or principal.user_id is None or principal.role is None:
        return None
    return ToolActor(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        role=principal.role,
        impersonating=principal.impersonating,
    )


def actor_realm(actor: ToolActor) -> str:
    """Which realm this actor came from, DERIVED rather than assumed.

    `actor_for` refuses a principal with no tenant, and an ADMIN principal carries a tenant
    only inside a D-22 view-as session — so an actor is admin-realm precisely when it is
    impersonating. Returning `"client"` unconditionally would have been one word and would
    have handed a client-writable column (`organizations.staff_may_curate_knowledge`) the
    power to widen an ADMIN principal.
    """
    return "admin" if actor.impersonating else "client"


async def may_act(session: AsyncSession, actor: ToolActor, permission: Permission) -> bool:
    """`core/auth.requires`'s ladder, in a form a non-route caller can ask.

    NOT a re-derivation: the role table is `rbac.role_has` and the D-22 clause is
    `MUTATING_PERMISSIONS`, both imported. A second copy of either would be a second answer
    to "may this person do this", and the two would diverge on the day one of them was
    updated.

    **AND `kb:write` IS DELEGATED RATHER THAN ANSWERED HERE, FOR THAT SAME REASON.** Since
    the founder's "give the staff perms allowing option to owner", who may curate knowledge
    is the role table PLUS one per-account switch an owner controls, and
    `kb/curation.may_curate_knowledge` is the one predicate that knows it — the same one
    `POST /v1/kb/sources` spends. Answering `kb:write` from `role_has` alone here would have
    made the assistant and the Add-Knowledge form disagree about one person in one account.

    THIS IS WHY THE FUNCTION TAKES A SESSION AND IS ASYNC. Every caller already has one, so
    the cost is a parameter rather than a connection.
    """
    if permission == CURATE_PERMISSION:
        return await may_curate_knowledge(
            session,
            realm=actor_realm(actor),
            role=actor.role,
            impersonating=actor.impersonating,
        )
    if not role_has(actor.role, permission):
        return False
    return not (actor.impersonating and permission in MUTATING_PERMISSIONS)


@dataclass(frozen=True, slots=True)
class Plan:
    """A described intent. Produced by a READ, and by nothing else.

    `current` and `proposed` are the pair the whole design turns on: a person confirming
    "set this to hot" without being shown that it is already hot, or that it is currently
    won, is not making an informed decision, and a proposal that omitted them would be a
    button with a label instead of a description.

    `cost` and `reversal` are the two an approval card could not say before, and they are
    the two a person most needs in front of a launch. `cost is None` means "this costs
    nothing", which is a real answer and the reason that field is nullable; `reversal` is
    NOT nullable, because "can this be taken back" always has an answer and an action whose
    author did not write one is an action whose author did not think about it. Both are
    plain sentences a person reads, composed by US from what the planner READ — never by the
    model. **`reversal` must be honest in the negative direction**: "calls already placed
    cannot be recalled" is the sentence, not a softer one, because the UI offers an Undo for
    field fills and a person who has learned that Undo exists will assume it here.

    `args` is the CANONICAL argument dict — normalised by the tool, not the model's raw JSON
    — and it is what gets signed. So what executes is what was described, not what was asked
    for.
    """

    object_id: str
    title: str
    summary: str
    current: str | None
    proposed: str
    #: What this costs the account, in a sentence, or None for "nothing".
    cost: str | None
    #: Whether and how it can be taken back. Never None, never softened.
    reversal: str
    args: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Executed:
    """What one action did.

    `applied` is False when the world was ALREADY in the requested state — a real outcome
    and not a failure, the same distinction `set_campaign_status` and `set_lead_status` make
    (D-65). It is reported rather than smoothed over because "I did nothing because it was
    already done" and "I did it" are different answers to the person who asked.

    `object_id` is the id the act PRODUCED, when the act produced one — an
    `agent_create` does not know the agent's id until it has run, and a person told "created"
    with nothing to open has been told half of it. `None` means "the object named at plan
    time is still the object", which is every other action.
    """

    applied: bool
    detail: str
    audit_summary: dict[str, Any]
    object_id: str | None = None


#: A tool's read half: session (tenant-scoped) → described plan. READS ONLY, on every tier.
Planner = Callable[[AsyncSession, "ToolActor", Mapping[str, Any]], Awaitable[Plan]]
#: A tool's write half. Reached from `confirm` (tier 2) or `run_immediate` (tier 1) and
#: from nowhere else.
Executor = Callable[[AsyncSession, "ToolActor", Mapping[str, Any]], Awaitable[Executed]]


@dataclass(frozen=True, slots=True)
class ActionTool:
    """One action the assistant can take.

    The `permission` is the one the HUMAN's route already declares for the same act, read
    off that route rather than chosen here: `PATCH /v1/leads/{id}` is `leads:write`,
    `POST /v1/dnc` and `POST /v1/campaigns/{id}/pause` are both `leads:dispatch`,
    `POST /v1/agents` and `POST /v1/agents/{id}/activate` are `org:manage`,
    `POST /v1/campaigns/{id}/launch` is `leads:dispatch`. Picking a different one would be
    this feature quietly disagreeing with the console about who may do what.

    `tier` has no default. See the module docstring — this is the field a mis-set value
    turns into an incident, so the language refuses to guess it.
    """

    name: str
    #: NO DEFAULT. A new action states its tier or fails to register.
    tier: ActionTier
    permission: Permission
    object_type: str
    audit_action: str
    schema: Mapping[str, Any]
    plan: Planner
    execute: Executor
    #: Where the result lives, as a person would find it ("under Agents in your dashboard").
    #: The founder's cross-screen rule: act from wherever they are, then SAY where it went,
    #: rather than navigating them or pre-filling a form for them to save.
    where: str


def parse_args[M: BaseModel](model: type[M], args: Mapping[str, Any]) -> M:
    """Tool arguments as a typed object, or a refusal the model can act on.

    Pydantic's own message is not forwarded: it names internal field paths and can quote the
    offending VALUE, and this string becomes both a log line and a prompt.
    """
    try:
        return model.model_validate(dict(args))
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        named = ", ".join(f"`{field}`" for field in fields) or "the arguments"
        raise WriteRefusedError(f"{named} was missing or the wrong shape") from exc


def action_schema(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    """One action's definition in the subset openai-python's `to_strict_json_schema`
    preserves (`prompt.set_fields_tool` argues the subset; this is the same shape so that a
    reader comparing the two finds one convention).

    A FUNCTION rather than dict literals so the envelope — `strict`, every property
    required, `additionalProperties: false` — cannot drift between the tools. The ORDER of
    keys is insertion order and is pinned by `write_tools_test.py`, because the tool block
    is part of the cacheable prompt prefix and a reordering is a cache miss on every request.

    WHAT IS THIS FUNCTION'S AND WHAT IS `prompt.function_tool`'s: the ENVELOPE is
    `function_tool`, spelled once for `set_fields`, for the read tools and for these. What
    stays here is the PARAMETERS object, because "every property is REQUIRED" is a fact
    about the action tools specifically — and it is a statement about the `required` array,
    not about optionality. A genuinely optional argument is spelled `anyOf: [T, null]` AND
    listed in `required`, which is the same shape a read tool uses and the only one
    `to_strict_json_schema` accepts: strict mode has no way to say "may be absent", so an
    absent argument is a null one.
    """
    return function_tool(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    )


#: Said at the end of every TIER 2 tool's description. The confirmation trigger is in code —
#: this sentence is not what makes it true — but a model that believes it has ACTED will tell
#: the person it has, and that lie is the one thing the code cannot prevent.
PROPOSES_ONLY: Final = (
    " This does NOT do it. It shows the person exactly what would change and waits for them "
    "to confirm. Say that you have suggested it, never that you have done it."
)

#: Said at the end of every TIER 1 tool's description. The opposite sentence, for the
#: opposite reason: an action that really has run must not be described as a suggestion, or
#: the person goes looking for a Confirm button that will never appear.
DOES_IT: Final = (
    " This DOES it, immediately — there is no confirmation step. Only call it when the "
    "person has asked for it. Afterwards, say plainly what you did and where to find it."
)
