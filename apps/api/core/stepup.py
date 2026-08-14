"""One step-up confirmation check, for every realm that needs one (BACKEND-PATTERNS §7).

Step-up in this codebase is an `X-Confirm-Action` header whose value must ECHO the
action being taken. It is not a second factor and does not claim to be one: what it buys
is that a dangerous request cannot be sent by a screen that did not mean to send it, and
that the confirmation captured for one action cannot be replayed against another.

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
"""

from __future__ import annotations

from apps.api.core.errors import ProblemError


def require_step_up(confirm: str | None, action: str) -> None:
    """Refuse unless the caller echoed `action` in `X-Confirm-Action`.

    Raises a 403 `step_up_required` whose remediation prints the exact header to send —
    an operator mid-incident must not have to find the source to learn the string. The
    refusal happens BEFORE any work, so a caller that sees it knows nothing changed.
    """
    if confirm != action:
        raise ProblemError(
            kind="permission",
            code="step_up_required",
            title="Confirmation required",
            detail="This action needs an explicit confirmation.",
            remediation=f"Repeat the request with the header X-Confirm-Action: {action}",
        )


__all__ = ["require_step_up"]
