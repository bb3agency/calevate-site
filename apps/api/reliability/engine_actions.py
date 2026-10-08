"""Per-agent in-call actions: registered at publish, kept in shape, removed at unpublish.

On `ENGINE=thinnest` the four in-call tools the Pipecat worker reaches over `/v1/worker/
calls/{ref}/tools/*` (opt-out, call-back, call-back cancel, handoff) are ThinnestAI custom
actions instead: HTTPS calls from their platform to `worker/engine_actions.py`, carrying a
header whose value is ours (`engine/thinnest_actions.py` cites the vendor shapes). One
function answers "make this agent's actions exist, be ours and be switched on", and the
publish path and the drift sweep both use it, as `engine_webhooks.ensure_agent_webhook`
does for the results endpoint.

THE SECRET. Minted here (`secrets.token_urlsafe`), sealed under `PLATFORM_KEK` on the
agent's `engine_agent_routes` row (migration e8a4c2f17b39) and sent as the action header.
The vendor never returns a header value (create-action.md:7), so when we hold no usable
secret — first publish, a lost KEK, a downgraded column — a new one is minted and every
action's header set is replaced with it (update-action.md:7: sending headers replaces the
whole set), which leaves no action carrying a value we cannot verify.

WHY NO `test` BEFORE ENABLING AT PUBLISH, although the vendor recommends it
(create-action.md:7). A test makes the vendor call our endpoint, and our endpoint verifies
the header against the secret this publish has not committed yet: on a first publish every
test would fail. The drift sweep, which runs on committed state, makes that probe instead
(`check_agent_actions`).

DESCRIPTIONS ARE PLATFORM TEXT (hard rule 5, D-674). Nothing here is read from a client's
script or configuration: an action description is a prompt the model obeys, and a client
sentence there would sit outside the truthful-answer floor's protection.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Final, Literal
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.envelope import Envelope, seal, unseal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings, is_public_callback_base
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_actions import (
    ActionDefinition,
    ActionParam,
    ThinnestActions,
    thinnest_actions,
)

log = get_logger(__name__)

THINNEST: Final = "thinnest"

#: Engines whose in-call tools are vendor-side actions calling our API.
ACTION_ENGINES: Final = frozenset({THINNEST})

#: Where the actions land: `/v1/worker/` is already the in-call write surface (its rate
#: profile, its load-shed exemption and its nginx zone are what a caller waiting on a tool
#: needs), and `check_public_routes` declares each route under it by name.
ACTIONS_PATH: Final = "/v1/worker/engine-actions"
AGENT_QUERY_PARAM: Final = "agent"

#: Tool leaf -> the action name the model sees. Names are the vendor's pattern
#: `^[a-z][a-z0-9_]{2,39}$` (create-action.md:412) and avoid the reserved built-ins
#: (agent/custom-api.md:87-88) and the built-in call-back, which the adapter switches off.
OPT_OUT: Final = "opt-out"
CALLBACK: Final = "callback"
CALLBACK_CANCEL: Final = "callback-cancel"
HANDOFF: Final = "handoff"
ACTION_NAMES: Final[dict[str, str]] = {
    OPT_OUT: "record_do_not_call",
    CALLBACK: "schedule_call_back",
    CALLBACK_CANCEL: "cancel_call_back",
    HANDOFF: "request_human_handoff",
}

_OPT_OUT_DESCRIPTION = (
    "Call this the moment the caller asks not to be contacted again: 'stop calling me', "
    "'remove my number', 'don't call again', or the same in any language. It is what "
    "actually removes them, so call it before you promise anything. Do NOT call it when "
    "they only want a different time or no call-back about this one thing; use "
    "cancel_call_back for that. Read the answer's 'say' before you speak: it tells you "
    "whether they were really removed."
)
_CALLBACK_DESCRIPTION = (
    "Book a call back for this caller. Ask for the day and time and resolve it yourself "
    "into a calendar date (YYYY-MM-DD) and a 24-hour time (HH:MM) in Indian time; never "
    "pass their words. Call it FIRST with confirmed set to no, read the time in the "
    "answer back to them exactly, and only when they agree call it again with confirmed "
    "set to yes. If the answer refuses the time, offer what it suggests instead. Do what "
    "the answer's 'say' tells you."
)
_CALLBACK_CANCEL_DESCRIPTION = (
    "Call this when the caller no longer wants a call back they were promised: "
    "'actually, don't ring me back'. It cancels every call back waiting for them. It does "
    "NOT stop other calls: if they asked never to be called again, use record_do_not_call "
    "instead. Do what the answer's 'say' tells you."
)
_HANDOFF_DESCRIPTION = (
    "Call this when the caller needs a person, because they asked for one or your "
    "instructions say to hand the call over. Call it BEFORE you say anything about "
    "connecting, transferring or holding: whether anybody can be reached is not something "
    "you can know. Never tell the caller they are being connected unless the answer says "
    "so. Do what the answer's 'say' tells you."
)


def definitions(engine: str, engine_agent_ref: str) -> tuple[ActionDefinition, ...]:
    """The four actions this vendor agent should hold, in a fixed order."""
    base = (get_settings().engine_actions_base_url or "").strip().rstrip("/")
    query = urlencode({AGENT_QUERY_PARAM: engine_agent_ref})

    def url(leaf: str) -> str:
        return f"{base}{ACTIONS_PATH}/{engine}/{leaf}?{query}"

    return (
        ActionDefinition(
            name=ACTION_NAMES[OPT_OUT],
            description=_OPT_OUT_DESCRIPTION,
            url=url(OPT_OUT),
            parameters=(
                ActionParam(
                    "reason",
                    "A few of the caller's own words asking not to be called, in the "
                    "language they said them. Leave it empty if they gave none.",
                    False,
                ),
                ActionParam(
                    "language",
                    "BCP-47 code of the language they said it in, e.g. te-IN.",
                    False,
                ),
            ),
        ),
        ActionDefinition(
            name=ACTION_NAMES[CALLBACK],
            description=_CALLBACK_DESCRIPTION,
            url=url(CALLBACK),
            parameters=(
                ActionParam(
                    "callback_date", "The day, as YYYY-MM-DD. Never a relative word.", True
                ),
                ActionParam(
                    "callback_time",
                    "The time, as HH:MM on a 24-hour clock, Indian time. 4 PM is 16:00.",
                    True,
                ),
                ActionParam(
                    "confirmed",
                    "yes ONLY after you read the resolved time back to the caller and they "
                    "agreed to it; no on the first call.",
                    True,
                ),
                ActionParam(
                    "note",
                    "One short line on what the call back is for, for the person who makes "
                    "it, who has heard none of this conversation.",
                    False,
                ),
                ActionParam("language", "BCP-47 code of the caller's language, e.g. te-IN.", False),
            ),
        ),
        ActionDefinition(
            name=ACTION_NAMES[CALLBACK_CANCEL],
            description=_CALLBACK_CANCEL_DESCRIPTION,
            url=url(CALLBACK_CANCEL),
            parameters=(),
        ),
        ActionDefinition(
            name=ACTION_NAMES[HANDOFF],
            description=_HANDOFF_DESCRIPTION,
            url=url(HANDOFF),
            parameters=(
                ActionParam("reason", "One short line on why a person is needed.", False),
                ActionParam(
                    "summary",
                    "One or two lines on what the caller wants and what you have already "
                    "told them.",
                    False,
                ),
            ),
        ),
    )


# --- the secret ----------------------------------------------------------------------


def action_secret_context(engine: str, engine_agent_ref: str) -> str:
    """The AAD binding a sealed secret to ONE route row, so it cannot be moved to another
    agent's row and verify that agent's actions."""
    return f"engine_action_secret:{engine}:{engine_agent_ref}"


_SECRET_COLUMNS: Final = (
    "action_secret_ciphertext, action_secret_nonce, action_secret_dek_wrapped, "
    "action_secret_dek_nonce, action_secret_kek_version"
)


def envelope_of(row: tuple[Any, ...]) -> Envelope | None:
    """The five sealed columns as an envelope, or None when none is held."""
    if any(value is None for value in row):
        return None
    ct, nonce, dw, dn, kek = row
    return Envelope(
        ciphertext=bytes(ct),
        nonce=bytes(nonce),
        dek_wrapped=bytes(dw),
        dek_nonce=bytes(dn),
        kek_id=int(kek),
    )


def open_action_secret(envelope: Envelope, *, engine: str, engine_agent_ref: str) -> str | None:
    """The plaintext, or None when no configured key opens it (`unseal` has logged why)."""
    try:
        return unseal(envelope, context=action_secret_context(engine, engine_agent_ref))
    except ProblemError:
        return None


async def _store_secret(
    session: AsyncSession, *, engine: str, engine_agent_ref: str, secret: str
) -> None:
    envelope = seal(secret, context=action_secret_context(engine, engine_agent_ref))
    await session.execute(
        text(
            "UPDATE engine_agent_routes SET action_secret_ciphertext = :ct, "
            "action_secret_nonce = :n, action_secret_dek_wrapped = :dw, "
            "action_secret_dek_nonce = :dn, action_secret_kek_version = :kek, "
            "updated_at = now() WHERE engine = :engine AND engine_agent_ref = :ref"
        ),
        {
            "ct": envelope.ciphertext,
            "n": envelope.nonce,
            "dw": envelope.dek_wrapped,
            "dn": envelope.dek_nonce,
            "kek": envelope.kek_id,
            "engine": engine,
            "ref": engine_agent_ref,
        },
    )


async def _held_secret(
    session: AsyncSession, engine: str, engine_agent_ref: str
) -> tuple[bool, str | None]:
    """(route exists, usable secret). Locks the row so two publishes cannot both mint one."""
    row = (
        await session.execute(
            text(
                f"SELECT {_SECRET_COLUMNS} FROM engine_agent_routes "
                "WHERE engine = :engine AND engine_agent_ref = :ref FOR UPDATE"
            ),
            {"engine": engine, "ref": engine_agent_ref},
        )
    ).first()
    if row is None:
        return False, None
    envelope = envelope_of(tuple(row))
    if envelope is None:
        return True, None
    return True, open_action_secret(envelope, engine=engine, engine_agent_ref=engine_agent_ref)


# --- converge ------------------------------------------------------------------------

ActionsOutcome = Literal["not_applicable", "converged"]


@dataclass(frozen=True, slots=True)
class ActionsReconciliation:
    outcome: ActionsOutcome
    #: Actions that did not exist and were made.
    created: int = 0
    #: Actions that existed and differed from ours (or carried a header we no longer hold).
    repaired: int = 0
    #: Actions that matched but had been switched off.
    reenabled: int = 0
    #: A new secret was minted and every action's header replaced.
    rekeyed: bool = False

    @property
    def changed_live_agent(self) -> bool:
        """Something at the vendor had moved away from what we published."""
        return bool(self.repaired or self.reenabled)


def _refuse_private_base() -> None:
    if not is_public_callback_base(get_settings().engine_actions_base_url):
        raise ProblemError(
            kind="validation",
            code="engine_actions_url_not_public",
            title="The address for in-call actions is not reachable from the internet",
            detail=(
                "ENGINE_ACTIONS_BASE_URL must be the API's public, secure address before agents "
                "publish on this voice platform."
            ),
            remediation=(
                "Set ENGINE_ACTIONS_BASE_URL in the ops console to the API's public secure "
                "address, such as api.calevate.tech, and publish again."
            ),
        )


async def ensure_agent_actions(
    session: AsyncSession,
    *,
    engine: str,
    engine_agent_ref: str,
    client: ThinnestActions | None = None,
    live_handover: bool | None = False,
) -> ActionsReconciliation:
    """Make this vendor agent's actions exist, carry our header, and be switched on.

    Call it in the SAME tenant session that wrote the agent's `engine_agent_routes` row,
    after that write. A no-op on an engine whose tools are not vendor-side actions, so the
    publish path may call it for every engine. Converges by NAME, which the vendor keeps
    unique per agent (create-action.md:162-164), so a republish never makes a second one.

    `live_handover` says whether the agent hands callers to a person itself (the vendor's
    built-in `escalate_to_human`, D-690). Then our hand-over action is REMOVED: it can only
    record a request and say nobody can be put through, and an agent holding both would be
    told two contradicting things about the same caller. False keeps it (no destination is
    on duty, so recording the request is all there is); None, the drift sweep's reading,
    keeps whatever the last publish chose and repairs it if it is held.
    """
    if engine not in ACTION_ENGINES:
        return ActionsReconciliation(outcome="not_applicable")
    exists, secret = await _held_secret(session, engine, engine_agent_ref)
    if not exists:
        raise ProblemError(
            kind="conflict",
            code="engine_route_absent",
            title="The agent has no engine route yet",
            detail="In-call actions are registered against the agent's engine route.",
            remediation="Save the agent's engine route in this same transaction first.",
        )
    _refuse_private_base()
    actions = client or thinnest_actions()
    rekeyed = secret is None
    if secret is None:
        secret = secrets.token_urlsafe(32)
        await _store_secret(
            session, engine=engine, engine_agent_ref=engine_agent_ref, secret=secret
        )

    held = {action.name: action for action in await actions.list_actions(engine_agent_ref)}
    created = repaired = reenabled = 0
    handoff_name = ACTION_NAMES[HANDOFF]
    for wanted in definitions(engine, engine_agent_ref):
        current = held.get(wanted.name)
        if wanted.name == handoff_name and (
            live_handover or (live_handover is None and current is None)
        ):
            if live_handover and current is not None:
                await actions.delete(engine_agent_ref, current.action_id)
            continue
        if current is None:
            made = await actions.create(engine_agent_ref, wanted, secret=secret)
            await actions.update(engine_agent_ref, made.action_id, enabled=True)
            created += 1
        elif rekeyed or not current.matches(wanted):
            await actions.update(
                engine_agent_ref, current.action_id, definition=wanted, secret=secret, enabled=True
            )
            repaired += 1
        elif not current.enabled:
            await actions.update(engine_agent_ref, current.action_id, enabled=True)
            reenabled += 1
    result = ActionsReconciliation(
        outcome="converged",
        created=created,
        repaired=0 if rekeyed else repaired,
        reenabled=reenabled,
        rekeyed=rekeyed,
    )
    log.info(
        "engine_actions_converged",
        extra={
            "engine": engine,
            "actions_created": created,
            "actions_repaired": repaired,
            "actions_reenabled": reenabled,
            "rekeyed": rekeyed,
        },
    )
    return result


async def retire_agent_actions(
    *, engine: str, engine_agent_ref: str | None, client: ThinnestActions | None = None
) -> int:
    """Remove our actions from a vendor agent that is no longer published. Returns how many.

    Only OUR names are removed: an action somebody added in the vendor console is not ours
    to delete. The sealed secret stays on the route row, so a later publish reuses it.
    """
    if engine not in ACTION_ENGINES or not engine_agent_ref:
        return 0
    actions = client or thinnest_actions()
    ours = set(ACTION_NAMES.values())
    removed = 0
    for action in await actions.list_actions(engine_agent_ref):
        if action.name in ours:
            await actions.delete(engine_agent_ref, action.action_id)
            removed += 1
    log.info("engine_actions_retired", extra={"engine": engine, "removed": removed})
    return removed


#: The probe the drift check sends through the vendor's `test` endpoint: the call-back
#: cancel action, which every agent holds. A test has no conversation, so the platform sends
#: no call id (agent/custom-api.md:111-114) and the action finds no call and writes nothing:
#: a real call through every check the agent's own call passes costs one log line.
PROBE_TOOL: Final = CALLBACK_CANCEL


async def probe_agent_actions(
    *, engine: str, engine_agent_ref: str, client: ThinnestActions | None = None
) -> bool | None:
    """Can the vendor reach our endpoint with this agent's header? None when not applicable
    or the action is missing (the converge reports that); False is an alarm."""
    if engine not in ACTION_ENGINES:
        return None
    actions = client or thinnest_actions()
    name = ACTION_NAMES[PROBE_TOOL]
    target = next((a for a in await actions.list_actions(engine_agent_ref) if a.name == name), None)
    if target is None:
        return None
    result = await actions.test(engine_agent_ref, target.action_id, {})
    return result.ok and result.status == 200


ActionsDrift = Literal["in_sync", "repaired", "probe_failed", "unchecked"]


async def check_agent_actions(
    *, tenant_id: UUID, engine: str, engine_agent_ref: str, client: ThinnestActions | None = None
) -> ActionsDrift | None:
    """The drift sweep's leg for a live vendor agent's actions. None when not applicable.

    `repaired`: an action was missing, different, re-keyed or switched off at the vendor —
    a console edit, or a lost secret — and is ours again. `probe_failed`: the actions are in
    shape but a real call through the vendor did not reach us with this agent's header (a
    wrong `ENGINE_ACTIONS_BASE_URL`, a blocked route), so callers cannot use them.
    `unchecked`: the vendor or our settings could not be read; not evidence of drift.
    """
    if engine not in ACTION_ENGINES:
        return None
    try:
        async with tenant_session(tenant_id) as session:
            converged = await ensure_agent_actions(
                session,
                engine=engine,
                engine_agent_ref=engine_agent_ref,
                client=client,
                live_handover=None,
            )
        reachable = await probe_agent_actions(
            engine=engine, engine_agent_ref=engine_agent_ref, client=client
        )
    except ProblemError as exc:
        log.info("engine_actions_check_skipped", extra={"engine": engine, "reason": exc.code})
        return "unchecked"
    if converged.changed_live_agent or converged.created:
        return "repaired"
    if reachable is False:
        return "probe_failed"
    return "in_sync"


__all__ = [
    "ACTIONS_PATH",
    "ACTION_ENGINES",
    "ACTION_NAMES",
    "AGENT_QUERY_PARAM",
    "CALLBACK",
    "CALLBACK_CANCEL",
    "HANDOFF",
    "OPT_OUT",
    "ActionsDrift",
    "ActionsReconciliation",
    "action_secret_context",
    "check_agent_actions",
    "definitions",
    "ensure_agent_actions",
    "envelope_of",
    "open_action_secret",
    "probe_agent_actions",
    "retire_agent_actions",
]
