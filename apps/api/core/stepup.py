"""One step-up check, for every realm that needs one (BACKEND-PATTERNS §7).

Step-up in this codebase is TWO obligations answered by two kinds of evidence, and this
module is where both are demanded together so that no dangerous route can end up with one:

    X-Confirm-Action                         INTENT   — this screen meant to send THIS action
    a second factor inside `REAUTH_MAX_AGE`  PRESENCE — the person at the keyboard is still them

The header half — the value must ECHO the action being taken — is what stops a screen
sending a dangerous request it did not mean to, and stops a confirmation captured for one
action being replayed against another. It is not a second factor and never claimed to be
one; a stolen live cookie satisfies it trivially, because the refusal prints the exact
string to send, on purpose.

The presence half (`authn/stepup.py`, D-178) is the part AUTH-MIGRATION C-09 named as not
built. It is built now, and it is demanded HERE rather than route-by-route because a
dangerous mutation that took only one of the two would be a gate with a way around it, and
the way around it would be an omission nobody could see.

This lived as `ops/routes.py::_require_step_up` while `ops` was the only realm with a
switch dangerous enough to want it. The admin realm now has one too — loosening a
client's spend ceiling (`admin/routes.py::record_commercial_terms`), which the role
table in `core/rbac.py` names as a superadmin action "which additionally needs step-up
confirmation" — so the check moved here and the ops routes import it. A second copy in
`admin/` would be the drift this repo treats as a defect even when both copies work.

The ACTION STRINGS deliberately stay with their routes. They are ops procedures printed
in runbooks and pinned literal-by-literal by tests (`platform_confirmation`,
`spend_cap_confirmation`, `outbox_replay_confirmation`, `spend_ceiling_confirmation`,
`tenant_erasure_confirmation`, `view_as_confirmation`); what is shared is the comparison
and the refusal, not the vocabulary.

The gate also guards a DOOR rather than a mutation in one place — `admin/routes.py::
mint_impersonation_grant` (D-210). Entering a client's account is the single act behind
which every tenant-realm read an operator can reach sits, including the raw transcript
BACKEND-PATTERNS §7 names, so the second factor is asked for once at the door instead of
being bolted onto reads that have no admin-realm session to check it against. That route
is also the one call site where satisfying the gate is not the only way through: a console
extending a view-as session it already holds presents the live grant instead, bounded at
`core/impersonation.VIEW_AS_MAX_AGE` from the step-up that started it. The alternative
there is argued in that constant, not here.

═══ WHY THIS IS A DEPENDENCY AND THE CHECK ITSELF IS SYNCHRONOUS ═══

Freshness is read off the session row, which is a database read. The obvious shape — make
`require_step_up` async and let it open a `credential_session` where it is called — BREAKS
A LOAD-BEARING INVARIANT: `db/session.py` runs `max_overflow=0` and says in as many words
that this is safe "only because no code path here holds two sessions at once". Some call
sites (`admin/routes.py::record_commercial_terms`,
`billing/credit_routes.py`'s adjustment) sit INSIDE an open `tenant_session`, because the
action string is derived from a row they had to read first. A second checkout there is a
pool that can deadlock against itself under `pool_size` concurrent incidents — on the
routes an operator reaches during one.

So the read happens in a **dependency**, which FastAPI resolves before the handler body
runs and therefore before any transaction is open, and what reaches the call site is a
plain frozen value with a synchronous `require`. That also makes the pairing structural
rather than remembered: `gate.require(...)` cannot be written without a `gate`, and the
only source of one is `Depends(step_up_gate)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from apps.api.core.auth import dev_tokens_permitted
from apps.api.core.errors import ProblemError


@dataclass(frozen=True, slots=True)
class StepUp:
    """The evidence a dangerous mutation needs, resolved before the handler ran.

    `verified_at` is `None` for both "there is no first-party admin session on this
    request" and "there is one that never proved a second factor", and `present`
    distinguishes them — because the two mean opposite things. See `require`.
    """

    present: bool
    verified_at: datetime | None

    def require(self, confirm: str | None, action: str) -> None:
        """Refuse unless the caller echoed `action` AND re-proved a factor recently.

        Both refusals happen BEFORE any work, so a caller that sees either knows nothing
        changed. Intent is checked first: it costs nothing, so a caller who forgot the
        header is told so without being asked about anything else.
        """
        if confirm != action:
            raise _confirmation_required(action)
        from apps.api.authn.stepup import is_fresh, reauthentication_required

        if not self.present:
            # No first-party admin session behind a request that already authenticated as
            # an admin. Before D-177 that meant a Clerk token — a real credential with its
            # own gates — and this branch returned, because freshness is a property OF A
            # CREDENTIAL and that was not this one. The vendor is gone, so the branch no
            # longer covers a credential: the ONLY thing that now reaches an admin route
            # without our cookie is the local `dev:admin:<uuid>` token, which
            # `core/auth.dev_tokens_permitted` already confines to `APP_ENV=local` on a
            # deployment holding no `PLATFORM_KEK`.
            #
            # So it fails closed everywhere else rather than staying permissive. A
            # returning branch whose stated reason has expired is how a gate becomes
            # decorative — and this one guards the big red switch.
            if dev_tokens_permitted():
                return
            raise reauthentication_required(action)

        if not is_fresh(self.verified_at):
            raise reauthentication_required(action)


async def step_up_gate(request: Request) -> StepUp:
    """Read the first-party admin session, if any, before the handler opens a transaction.

    Imported lazily inside the function because `core.stepup` is imported by six route
    modules that `core/bootstrap.py` assembles, and `authn.stepup` reaches the credential
    layer — a module-level import would put that layer in every one of those chains.
    """
    from apps.api.authn.stepup import current_admin_session

    session = await current_admin_session(request)
    return StepUp(
        present=session is not None,
        verified_at=session.mfa_verified_at if session is not None else None,
    )


#: What a dangerous route declares. An `Annotated` alias rather than a `Depends(...)`
#: default, because that is this repo's idiom (`GlobalSession`, `SecretOperator`) and
#: because half these modules are not covered by the `B008` per-file ignore, which is
#: scoped to files literally named `routes.py`.
StepUpGate = Annotated[StepUp, Depends(step_up_gate)]


def _confirmation_required(action: str) -> ProblemError:
    return ProblemError(
        kind="permission",
        code="step_up_required",
        title="Confirmation required",
        detail="This action needs an explicit confirmation.",
        remediation=f"Repeat the request with the header X-Confirm-Action: {action}",
    )


@dataclass(frozen=True, slots=True)
class ActionCode:
    """A code entered FOR ONE ACTION, demanded by the few routes where a recent sign-in is
    not enough (D-730): minting a view-as grant, and on the client realm handing out
    exported data or storing a credential.

    `StepUp` asks "was a factor proved in the last half hour"; a console left open after
    sign-in answers yes. This asks "was a code typed for exactly this action", and the
    proof (`authn/stepup.record_action_proof`) is spent by the request it was typed for.

    `subject_id` is the first-party session's subject for `realm`, or `None` when the
    request carries no such cookie — which off a local box means it authenticated some
    other way and is refused, exactly as `StepUp.require` refuses.
    """

    realm: str
    subject_id: UUID | None

    async def require(self, confirm: str | None, action: str) -> None:
        if confirm != action:
            raise _confirmation_required(action)
        from apps.api.authn.stepup import action_code_required, spend_action_proof

        if self.subject_id is None:
            if dev_tokens_permitted():
                return
            raise action_code_required(action, realm=self.realm)
        if not await spend_action_proof(
            realm=self.realm, subject_id=self.subject_id, action=action
        ):
            raise action_code_required(action, realm=self.realm)


def client_confirmation(request: Request, verb: str) -> str:
    """`<verb>:<org slug>` — a client-realm action string bound to the account (D-730).

    The slug is the `X-Org-Slug` the principal's tenant was resolved from on this very
    request, so the binding and the authorisation cannot name different accounts, and the
    browser already holds it where it does not hold the tenant id.
    """
    from apps.api.core.context import ORG_HEADER

    return f"{verb}:{request.headers.get(ORG_HEADER, '')}"


async def _subject_for(request: Request, realm: str) -> UUID | None:
    from apps.api.authn.cookies import read_token
    from apps.api.authn.sessions import verify_session

    token = read_token(request, realm)
    if not token:
        return None
    outcome = await verify_session(token=token, realm=realm)
    return None if outcome.session is None else outcome.session.subject_id


async def admin_action_code(request: Request) -> ActionCode:
    return ActionCode(realm="admin", subject_id=await _subject_for(request, "admin"))


async def client_action_code(request: Request) -> ActionCode:
    return ActionCode(realm="client", subject_id=await _subject_for(request, "client"))


#: The two realms' declarations, resolved before the handler opens a transaction for the
#: reason the module docstring gives for `StepUpGate`.
AdminActionCode = Annotated[ActionCode, Depends(admin_action_code)]
ClientActionCode = Annotated[ActionCode, Depends(client_action_code)]


__all__ = [
    "ActionCode",
    "AdminActionCode",
    "ClientActionCode",
    "StepUp",
    "StepUpGate",
    "admin_action_code",
    "client_action_code",
    "client_confirmation",
    "step_up_gate",
]
