"""Every caller that writes or destroys a password also ends the subject's sessions.

`authn/credentials.py` states the contract twice — at `set_password` ("THE CALLER MUST
REVOKE THE SUBJECT'S SESSIONS in the same transaction … It is not done here on purpose")
and again at `delete_password` — and the placement decision behind it is right: a password
set during ONBOARDING (nobody is signed in) and one set during a SUSPECTED COMPROMISE (sign
everything out) want opposite answers, so the caller chooses. What was missing is the
executable half. That same file's docstring is the indictment of leaving it in prose: *"A
rule enforced per-endpoint is enforced by whoever remembered, which is precisely how the
reference implementation ended up with … an enumeration oracle on `check-identifier`."*

THE FAILURE THIS CATCHES is the ASVS session-management classic (5.0 §7.4.3, "the
application gives the option to terminate all other active sessions after a successful
change or removal of any authentication factor" —
https://github.com/OWASP/ASVS/blob/master/5.0/en/0x16-V7-Session-Management.md, read
2026-09-07): a fifth caller lands — an admin "reset this user's password" action, a new
self-service change — the revoke is forgotten, and somebody holding a stolen `__Host-`
cookie keeps access AFTER the victim changed their password, which is the one act a person
takes specifically to end that access. Nothing errors. Nothing is red. The account is just
still open.

A SOURCE WALK, IN THE SHAPE THIS REPO ALREADY USES FOR CALL-SITE CENSUSES
(`tests/authn_session_test.py::test_the_only_rotation_callers_are_the_three_recorded_here`,
and `tests/authz_audit_test.py`'s registry tests for routes): the property is about which
code EXISTS, not about which code ran under one fixture. A behavioural test can only cover
the callers somebody remembered to write a test for, which is the same weakness as the rule
being in a docstring.

IT RUNS BOTH WAYS. A new caller with no revocation fails; an exemption naming a function
that no longer calls the store fails too, so this cannot quietly become the place defects
go to be forgotten.

`scripts/` IS OUT OF SCOPE, deliberately and not by omission: `scripts/seed_dev.py` sets
three passwords on a local fixture database where no session exists and none is wanted, and
it is not a request path. The walk covers `apps/api`, which is where every reachable caller
lives.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: The two writes that owe a revocation, and the call that pays it. Spelled as the bare
#: names because every caller in this tree imports them by name (`from apps.api.authn.
#: credentials import set_password`); an aliased import would slip past, which is why the
#: import-shape assertion below exists rather than being assumed.
_GUARDED_CALLS = frozenset({"set_password", "delete_password"})
_REVOCATION = "revoke_subject_sessions"

#: Callers that legitimately write a password WITHOUT revoking, each with the reason it is
#: safe. Keyed `<path relative to the repo root>::<function>` so two functions with one
#: name in two modules cannot share an exemption.
#:
#: THE BAR FOR AN ENTRY: there must be no session that could be signed in as this subject
#: at the moment the password is written. "Onboarding" is not a password on the exemption —
#: it is the claim that the account is not yet usable, and it has to be true of the code.
_EXEMPT: dict[str, str] = {
    "apps/api/authn/invitations.py::accept_with_password": (
        "The redemption of an invitation, and it writes a password only under `if not "
        "await has_password(...)` — so it never REPLACES a credential, it installs the "
        "first one for an account that has never had one. A subject with no password has "
        "no way to have signed in, so there is no session for a revocation to end: the "
        "call would revoke zero rows on every path that reaches it. The branch where a "
        "password already exists does not write one, and D-185's unverified-account "
        "refusal above it is what stops that branch being a takeover. The session this "
        "flow issues is minted AFTER, at the foot of the function, and revoking it would "
        "sign the new member out of the redemption they just completed."
    ),
}


def _direct_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """The names this function calls ITSELF, not counting functions nested inside it.

    `ast.walk` would attribute a nested handler's calls to its enclosing factory, which
    matters here rather than being pedantry: `authn/routes.py` defines every route handler
    inside `_realm_router`, so a walk would let one handler's revocation vouch for another
    handler's `set_password`.
    """
    found: set[str] = set()
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        if isinstance(current, ast.Call) and isinstance(current.func, ast.Name):
            found.add(current.func.id)
        stack.extend(ast.iter_child_nodes(current))
    return found


def _api_root() -> Path:
    return Path(__file__).resolve().parent.parent / "apps" / "api"


def _callers() -> dict[str, set[str]]:
    """`<relative path>::<function>` → the names it calls, for every guarded caller.

    `authn/credentials.py` is excluded: it DEFINES the two functions, and its own
    docstrings name them repeatedly.
    """
    root = _api_root().parent.parent
    callers: dict[str, set[str]] = {}
    for path in sorted(_api_root().rglob("*.py")):
        if path.name == "credentials.py" and path.parent.name == "authn":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            calls = _direct_calls(node)
            if calls & _GUARDED_CALLS:
                callers[f"{path.relative_to(root)}::{node.name}"] = calls
    return callers


def test_the_password_store_is_only_reached_by_name() -> None:
    """The census matches on a bare `Name`, so an aliased or attribute-style import would
    be invisible to it. This asserts the premise instead of trusting it: every import of
    the two guarded functions in `apps/api` binds them under their own name.

    An `import ... as` or a `credentials.set_password(...)` call site is not forbidden by
    anything — it would just have to be handled here, and finding out from a silent
    exemption is the failure mode this repo writes censuses to avoid.
    """
    root = _api_root().parent.parent
    offenders: list[str] = []
    for path in sorted(_api_root().rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _GUARDED_CALLS and alias.asname not in (None, alias.name):
                        offenders.append(
                            f"{path.relative_to(root)} imports {alias.name} as {alias.asname}"
                        )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _GUARDED_CALLS
            ):
                offenders.append(f"{path.relative_to(root)} calls {node.func.attr} as an attribute")
    assert not offenders, (
        "the revocation census matches `set_password(`/`delete_password(` by bare name, and "
        f"{offenders} would be invisible to it. Import them by name, or teach "
        "`_direct_calls` the other shape — do not leave the census half-blind."
    )


def test_every_password_write_is_paired_with_a_session_revocation() -> None:
    """The census. A caller that writes a password must end the subject's sessions."""
    unguarded = {
        caller: sorted(calls & _GUARDED_CALLS)
        for caller, calls in _callers().items()
        if _REVOCATION not in calls and caller not in _EXEMPT
    }
    assert not unguarded, (
        f"{sorted(unguarded)} write a password without calling `{_REVOCATION}`. "
        "`authn/credentials.set_password` states the contract in its docstring: the caller "
        "revokes, in the same transaction, because onboarding and suspected compromise want "
        "opposite answers. A live session does not consult the password store, so without "
        "this a stolen cookie outlives the password change made to kill it (ASVS 5.0 "
        "§7.4.3). Either add the revocation, or add an entry to `_EXEMPT` here with the "
        "reason no session can exist at that moment."
    )


def test_no_exemption_outlives_the_caller_it_excuses() -> None:
    """The other direction. An exemption whose function no longer writes a password is a
    standing permission waiting for a function of that name to be reused — the same defect
    `scripts/check_public_routes` refuses for routes."""
    callers = _callers()
    stale = sorted(set(_EXEMPT) - set(callers))
    assert not stale, (
        f"{stale} are exempted from the password-revocation census, but no function of that "
        "name in that file calls `set_password`/`delete_password` any more. Delete the "
        "entry — an exemption that names nothing is one a future function inherits silently."
    )


def test_every_exemption_states_a_reason() -> None:
    """A reason short enough to be a label is not a reason. Same floor
    `scripts/check_public_routes._MIN_REASON` applies to an open route, and for the same
    purpose: the cost of the exemption is one reviewed paragraph, not one word."""
    thin = sorted(key for key, why in _EXEMPT.items() if len(why) < 120)
    assert not thin, f"{thin} are exempted with no argument for why no session can exist"


def test_the_four_known_callers_are_all_present_and_accounted_for() -> None:
    """The audit's own finding, pinned so it cannot silently stop being true.

    Not a duplicate of the census above: that one asserts a PROPERTY of whatever callers
    exist, and would stay green if three of these four were deleted. This asserts that the
    four surfaces that write a password are still the four we reasoned about — a reset, an
    operator revocation, an invitation redemption, a first-operator bootstrap, plus the
    self-service change this lane added.
    """
    assert set(_callers()) == {
        "apps/api/authn/service.py::confirm_password_reset",
        "apps/api/authn/service.py::change_password",
        "apps/api/authn/bootstrap.py::confirm_bootstrap",
        "apps/api/authn/invitations.py::accept_with_password",
        "apps/api/authn/operators.py::revoke_operator",
    }, (
        "the set of functions that write or destroy a password has changed. That is "
        "allowed — it is what the census above is for — but this list is the one a reader "
        "reasons from, so bring it with you."
    )
