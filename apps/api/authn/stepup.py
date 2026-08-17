"""Step-up re-authentication: has this operator proved a second factor RECENTLY (C-09).

`core/stepup.py` owns the OTHER half of the same control — the `X-Confirm-Action` echo,
which binds a request to the action it claims to be. This module owns freshness, and the
two are deliberately separate obligations answered by separate evidence:

    X-Confirm-Action   "this screen meant to send THIS action"     — intent
    step-up            "the person at the keyboard is still them"  — presence

Neither substitutes for the other. A stolen live cookie passes the echo check trivially
(the attacker can read the action string out of the refusal itself, which prints it on
purpose). A confirmed action from a session whose owner walked away from an unlocked laptop
two hours ago is exactly the case a re-check is for.

═══ WHY THIS BECAME BUILDABLE, HAVING NOT BEEN ═══

`core/auth.py` records the reason freshness was NOT enforced on the Clerk credential, and
the reason was good: Clerk models freshness as "reverification", this repo had no browser
flow to raise the prompt, and "gating an incident lever on a flow that does not exist would
be a control that gets switched off". D-170 built the flow. The emailed OTP challenge is a
second factor an operator can answer at 3am from the same screen they were refused on, so
the objection is spent and AUTH-MIGRATION C-09 can close.

═══ WHAT IS CHECKED, AND WHAT THE ABSENT CASE MEANS ═══

The evidence is `auth_sessions.mfa_verified_at` on the session that authenticated this
request — the same column `service.complete_second_factor` stamps and `rotate_session`
carries forward. Older than `REAUTH_MAX_AGE`, or absent on a realm that requires a second
factor, and the mutation is refused with a 403 that names the two endpoints which fix it.

A REQUEST CARRYING NO FIRST-PARTY ADMIN SESSION IS NOT REFUSED HERE, and that needs saying
plainly rather than being discovered. It is not "the check passes when the header is
absent" (the argument that killed the CSRF token's server half): freshness is a property OF
A CREDENTIAL, and a request that presents no first-party session presented some other
credential, which has its own gates — today `core/auth.py`'s Clerk `fva[1] >= 0`, plus the
`X-Confirm-Action` echo that applies to both. Once AUTH-MIGRATION §5 step 6 deletes Clerk
there IS no other credential, so this gate becomes universal with no further edit, which is
the direction a transitional check has to point. `tests/authn_stepup_test.py` pins the
refusal on the branch that exists today rather than trusting that sentence.

═══ FIVE MINUTES ═══

`REAUTH_MAX_AGE` is five minutes: long enough that an operator working through a runbook —
read the current value, decide, send the change — is not challenged twice inside one task,
short enough that an abandoned session is not a usable one. It is deliberately much shorter
than the admin realm's 30-minute idle bound, because the whole point is to be a tighter
clock than the session's own; a step-up window at or above the idle window would be
satisfied by every session that is live at all, which is a control that never fires.

NIST SP 800-63B has no number for this and says so implicitly — reauthentication intervals
there are session-level (12 h / 30 min inactivity for AAL2), not per-action — so five
minutes is our judgement about ONE operator action, recorded as a decision (D-178) rather
than presented as a standard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from fastapi import Request

from apps.api.authn.cookies import read_token
from apps.api.authn.sessions import VerifiedSession, verify_session
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: The realm dangerous mutations live in. Step-up is declared on the admin router only
#: (`authn/routes.py`), so this is not a parameter — a client-realm step-up endpoint would
#: be a route nobody calls, and a client-realm freshness check would have no `mfa_verified_at`
#: to read because `service.MFA_REQUIRED_REALMS` does not include that realm.
STEP_UP_REALM: Final = "admin"

#: How recently a second factor must have been proved. See the module docstring.
REAUTH_MAX_AGE: Final = timedelta(minutes=5)


async def current_admin_session(request: Request) -> VerifiedSession | None:
    """The first-party admin session behind this request, or `None` if there is not one.

    `None` covers both "no cookie" and "a cookie that no longer verifies" — an expired,
    revoked or replayed token is not a session whose second factor could be fresh, and
    telling the two apart here would duplicate `verify_session`'s refusal vocabulary at a
    second site. A caller whose session died gets the ordinary `unauthorized` from whatever
    dependency authenticated the route; this returns `None` and lets that stand.
    """
    token = read_token(request, STEP_UP_REALM)
    if not token:
        return None
    outcome = await verify_session(token=token, realm=STEP_UP_REALM)
    return outcome.session


def reauthentication_required(action: str) -> ProblemError:
    """The refusal, with the two calls that clear it printed in it.

    An operator mid-incident must not have to find the source — or the frontend — to learn
    how to get past this, for the same reason `core/stepup.StepUp.require` prints the
    header it wants. Logged here rather than at the call site because this function is
    constructed only on the refusing branch: a stale second factor on a dangerous route is
    something an operator investigating "why did that 403" needs in the log, and the action
    string is safe to carry (it is an ops procedure, not a secret).
    """
    log.warning("step_up_reauthentication_required", extra={"action": action})
    return ProblemError(
        kind="permission",
        code="reauthentication_required",
        title="Confirm it is still you",
        detail=(
            "This action needs a second factor proved in the last "
            f"{int(REAUTH_MAX_AGE.total_seconds() // 60)} minutes."
        ),
        remediation=(
            "POST /v1/auth/admin/step-up to have a code emailed, POST the code to "
            f"/v1/auth/admin/step-up/verify, then repeat this request with "
            f"X-Confirm-Action: {action}"
        ),
    )


def is_fresh(verified_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Was a second factor proved inside the window? `None` — never proved — is NOT fresh.

    Takes the instant rather than the session, so `core/stepup.StepUp` (which holds the
    instant and not the row) applies THIS comparison rather than a second copy of it.
    """
    if verified_at is None:
        return False
    return (now or datetime.now(UTC)) - verified_at <= REAUTH_MAX_AGE


__all__ = [
    "REAUTH_MAX_AGE",
    "STEP_UP_REALM",
    "current_admin_session",
    "is_fresh",
    "reauthentication_required",
]
