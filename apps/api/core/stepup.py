"""One step-up confirmation check, for every realm that needs one (BACKEND-PATTERNS §7).

Step-up in this codebase is TWO obligations answered by two kinds of evidence, and this
module is where both are demanded together so that no dangerous route can end up with one:

    X-Confirm-Action                       INTENT   — this screen meant to send THIS action
    a second factor proved in the last 5m  PRESENCE — the person at the keyboard is still them

The header half — the value must ECHO the action being taken — is what stops a screen
sending a dangerous request it did not mean to, and stops a confirmation captured for one
action being replayed against another. It is not a second factor and never claimed to be
one; a stolen live cookie satisfies it trivially, because the refusal prints the exact
string to send, on purpose.

The presence half (`authn/stepup.py`, D-178) is the part AUTH-MIGRATION C-09 named as not
built. It is built now, and it is demanded HERE rather than route-by-route for the same
reason the echo check is: a dangerous mutation that took only one of the two would be a
gate with a way around it, and the way around it would be an omission nobody could see.

This lived as `ops/routes.py::_require_step_up` while `ops` was the only realm with a
switch dangerous enough to want it. The admin realm now has one too — loosening a
client's spend ceiling (`admin/routes.py::record_commercial_terms`), which the role
table in `core/rbac.py` names as a superadmin action "which additionally needs step-up
confirmation" — so the check moved here and the ops routes import it. A second copy in
`admin/` would be the drift this repo treats as a defect even when both copies work.

The ACTION STRINGS deliberately stay with their routes. They are ops procedures printed
in runbooks and pinned literal-by-literal by tests (`platform_confirmation`,
`spend_cap_confirmation`, `outbox_replay_confirmation`, `spend_ceiling_confirmation`);
what is shared is the comparison and the refusal, not the vocabulary.

WHY THIS IS ASYNC AND TAKES THE REQUEST. Freshness is read off the session row, which is a
database read, and the session is identified by a cookie on the request. The alternative —
carrying `mfa_verified_at` on `core.context.Principal` — was rejected because that object is
built by the credential verifier, and a route reading a REQUEST here cannot be handed a
freshness value by anything upstream that got it wrong. The order is intent first: the echo
check costs nothing, so a caller that forgot the header is told so without a round trip to
the session store.
"""

from __future__ import annotations

from fastapi import Request

from apps.api.core.errors import ProblemError


async def require_step_up(confirm: str | None, action: str, *, request: Request) -> None:
    """Refuse unless the caller echoed `action` in `X-Confirm-Action` AND re-proved a factor.

    Raises a 403 `step_up_required` whose remediation prints the exact header to send — an
    operator mid-incident must not have to find the source to learn the string — or a 403
    `reauthentication_required` naming the two calls that refresh the factor.

    Both refusals happen BEFORE any work, so a caller that sees either knows nothing changed.
    """
    if confirm != action:
        raise ProblemError(
            kind="permission",
            code="step_up_required",
            title="Confirmation required",
            detail="This action needs an explicit confirmation.",
            remediation=f"Repeat the request with the header X-Confirm-Action: {action}",
        )
    # Imported here, not at module scope: `authn.stepup` reaches the session store and the
    # cookie layer, and `core.stepup` is imported by five route modules that
    # `core/bootstrap.py` assembles — a module-level import would make the credential layer
    # part of every one of those import chains.
    from apps.api.authn.stepup import require_fresh_second_factor

    await require_fresh_second_factor(request, action)


__all__ = ["require_step_up"]
