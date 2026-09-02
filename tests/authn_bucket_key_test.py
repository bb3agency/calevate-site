"""`session_cookie_value` — the rate-limit bucket key, which had no test at all.

`core/middleware.RateLimitMiddleware._subjects` calls it on EVERY request that carries no
`Authorization` header, which since D-177 is every production request: the credential is a
`__Host-` cookie. So this one pure function decides which bucket the whole authenticated
API counts a caller in, and until this file nothing drove it.

WHAT IT GOT WRONG, and why the wrongness was invisible. Its docstring justified returning
the FIRST cookie in header order on the ground that "a browser sends at most one of ours
per request (the two realms are two hostnames)" and that "a request carrying both is
already outside the model". `authn/cookies.py`'s own module docstring says the opposite
eighty lines above: both consoles talk to ONE API host, both cookies land on that host,
and "the two names exist so that being signed into both consoles at once works at all".
The case ruled out as illegitimate is the case the two names were introduced to support —
an operator with `admin.` and `app.` open at once, which on this product is the founder on
any day they look at a client's screen.

The cost was a bucket that moved when nothing about the caller did: RFC 6265 §5.4 orders
equal-path cookies by creation time, so which cookie answered depended on which console
had been signed into first, and signing into that one again re-created it and silently
moved the pair somewhere else. That is `charge_tenant_quota`'s "a limiter that does not
mean what it says" (D-131) arriving through the cookie arm.

The three properties below are what replaced it, and each fails if the old spelling comes
back. Nothing here touches Redis or the database — the function is pure, and a bucket-key
property proved through a rate limiter would be proving the limiter instead.
"""

from __future__ import annotations

import pytest
from apps.api.authn.cookies import COOKIE_NAMES, cookie_name, session_cookie_value
from apps.api.authn.models import AUTHN_REALMS

ADMIN = COOKIE_NAMES["admin"]
CLIENT = COOKIE_NAMES["client"]


def test_a_single_session_is_its_own_bucket() -> None:
    """The ordinary case: one console, one cookie, one key that depends on the value."""
    one = session_cookie_value(f"{CLIENT}=alpha")
    two = session_cookie_value(f"{CLIENT}=beta")
    assert one is not None and two is not None
    assert one != two, "two different sessions must not share a bucket"
    assert "alpha" in one


def test_both_consoles_at_once_is_one_bucket_whatever_order_the_browser_sends_them() -> None:
    """THE CORRECTION. Header order is a browser's business and must not pick a bucket.

    Ordered one way this used to answer the client session and the other way the admin
    one — two keys for one caller, chosen by which console had been signed into first.
    """
    forwards = session_cookie_value(f"{CLIENT}=c-token; {ADMIN}=a-token")
    backwards = session_cookie_value(f"{ADMIN}=a-token; {CLIENT}=c-token")
    assert forwards == backwards, "the bucket must not depend on Cookie: header order"
    assert forwards is not None
    # BOTH values are in the key, so the pair is its own bucket rather than an alias of
    # either half — which is what makes signing into the second console cost a mint
    # against the address rather than inheriting the first console's spent budget.
    assert "a-token" in forwards and "c-token" in forwards


def test_being_signed_in_twice_never_buys_a_second_budget() -> None:
    """`_subjects`' own doctrine: presenting a credential never buys more room than
    presenting none. Two live sessions are ONE caller, so the pair's key is neither
    session's key — a caller cannot move between the three at will to reset a counter,
    because each move costs the address one mint unit.
    """
    admin_only = session_cookie_value(f"{ADMIN}=a-token")
    client_only = session_cookie_value(f"{CLIENT}=c-token")
    both = session_cookie_value(f"{ADMIN}=a-token; {CLIENT}=c-token")
    assert len({admin_only, client_only, both}) == 3


def test_a_quoted_value_is_the_same_session_as_an_unquoted_one() -> None:
    """RFC 6265 permits a quoted cookie-value. One session must not occupy two buckets
    because a browser chose to quote it."""
    assert session_cookie_value(f'{ADMIN}="q"') == session_cookie_value(f"{ADMIN}=q")


@pytest.mark.parametrize(
    "header",
    [
        "",
        "unrelated=1; other=2",
        # The near-miss `session_cookie_present`'s substring test would accept and this
        # one must not: a different cookie whose NAME merely contains ours.
        f"x{CLIENT}_backup=stolen",
        # Present but empty is not a session; it must fall through to the address bucket
        # rather than putting every such caller in one shared "" bucket.
        f"{ADMIN}=",
    ],
)
def test_a_header_carrying_none_of_ours_has_no_bucket_of_its_own(header: str) -> None:
    assert session_cookie_value(header) is None
    assert session_cookie_value(None) is None


def test_the_stripped_local_name_is_read_too() -> None:
    """`read_token` honours the un-prefixed name on a plain-HTTP request (D-198), so a
    local deployment still has to be bucketed. This layer cannot see the scheme, and
    over-approximating here is safe: the value is a bucket key, never a credential."""
    for realm in AUTHN_REALMS:
        stripped = cookie_name(realm, secure=False)
        assert session_cookie_value(f"{stripped}=local") is not None
