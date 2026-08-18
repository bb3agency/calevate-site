"""One dead-man's-switch ping, in the two shapes this repo needs it (D-408).

WHY THIS MODULE EXISTS RATHER THAN A SECOND COPY. `scripts/host_heartbeat.py` argued the
whole dead-man pattern — the vendor, the rejected alternatives, and above all THE
ASYMMETRY (success emits, failure does not, a dead box cannot) — for the backup chain.
D-408 needs the identical mechanism for a second observer, and the two call sites cannot
share a transport call: the backup one is a synchronous subprocess launched from a shell
script on the database host with no event loop, and the new one is an `await` inside an
ARQ worker. What they CAN share is everything that makes the ping correct — the retry
policy, what counts as delivered, and the rule that the URL is a credential. Two copies of
those would be two things to get right (CLAUDE.md: one way per problem).

READ `scripts/host_heartbeat.py`'s module docstring for the reasoning. This file holds the
mechanism; that file holds the argument, and it is not repeated here because a second copy
of an argument rots exactly the way a second copy of a constant does.

WHAT A CALLER MUST PRESERVE, in one line, because it is the property that is easy to
destroy while "improving" this: **only success may ping.** A caller that pings on a
failure path has not added coverage, it has removed the alarm — the monitor is watching
for SILENCE, and a process that pings whatever happens is never silent.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Final

import httpx

# Bounded so no caller can hang on its own heartbeat: worst case is
# ATTEMPTS x (timeout + backoff) of about 21s. The vendor documents that a ping can be
# lost to plain packet loss and recommends retrying
# (https://healthchecks.io/docs/reliability_tips/), and a lost ping would eventually page
# a human out of hours for a healthy system — so retrying is noise reduction, not optimism.
PING_TIMEOUT_S: Final = 5.0
PING_ATTEMPTS: Final = 3
PING_BACKOFF_S: Final = 2.0

# The vendor answers 200 with a two-byte body. Anything else — a 404 for a deleted check,
# a 5xx, an HTML captive portal — is NOT a heartbeat, and treating it as one would be the
# "silent pass that looks configured" failure in its final form.
OK_STATUS: Final = 200

#: Sent on every ping so a vendor-side request log can tell the two checks apart without
#: either URL being quoted anywhere. Not authentication and not pretending to be.
USER_AGENT_PREFIX: Final = "calevate"


def check_ref(url: str) -> str:
    """A stable, non-reversible handle for one ping URL, for operator output.

    The URL is a bearer secret (anyone holding it can silence the alarm by pinging it),
    so it must never reach a log — but "which check did we ping" still has to be
    answerable when a rotation goes wrong, and a digest prefix answers it without
    carrying the secret.
    """
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def _classify(response: httpx.Response) -> tuple[bool, str] | None:
    """(delivered, reason) for a response that settles it, or None to retry.

    Shared by both transports so "what counts as delivered" is decided once. Split out
    rather than inlined twice because it is the one judgement in this file that a future
    reader might reasonably want to change, and it must change in both shapes at once.
    """
    if response.status_code == OK_STATUS:
        return (True, f"HTTP {response.status_code}")
    return None


def ping(url: str, *, agent: str) -> tuple[bool, str]:
    """One heartbeat from a synchronous context, retried. Returns (delivered, reason).

    `reason` is always safe to print: it names a status code or an exception TYPE, never
    a URL and never an exception's message (which can quote the URL it failed to reach).
    """
    reason = "no attempt was made"
    for attempt in range(1, PING_ATTEMPTS + 1):
        try:
            # follow_redirects=False on purpose: a redirect to somewhere else is not this
            # check, and silently following one would let a hijacked DNS answer
            # "delivered" forever. GET (not POST) so there is no body to get wrong.
            response = httpx.get(
                url,
                timeout=PING_TIMEOUT_S,
                follow_redirects=False,
                headers={"user-agent": f"{USER_AGENT_PREFIX}-{agent}"},
            )
        except httpx.HTTPError as exc:
            reason = f"{type(exc).__name__} on attempt {attempt}"
        else:
            settled = _classify(response)
            if settled is not None:
                return settled
            reason = f"HTTP {response.status_code} on attempt {attempt}"
        if attempt < PING_ATTEMPTS:
            time.sleep(PING_BACKOFF_S)
    return (False, reason)


async def ping_async(http: httpx.AsyncClient, url: str, *, agent: str) -> tuple[bool, str]:
    """One heartbeat from async code, retried. Returns (delivered, reason).

    Takes the client rather than making one: the caller is inside a worker that already
    holds a configured `AsyncClient`, and a second client per tick would be a second TLS
    handshake and a second place for timeouts to be set differently.

    THE TIMEOUT IS PASSED PER-REQUEST, not inherited, so this ping is bounded by
    `PING_TIMEOUT_S` regardless of what the caller's client was built with — a client
    configured for a slow vendor call must not turn a lost heartbeat into a long stall.
    """
    reason = "no attempt was made"
    for attempt in range(1, PING_ATTEMPTS + 1):
        try:
            response = await http.get(
                url,
                timeout=PING_TIMEOUT_S,
                follow_redirects=False,
                headers={"user-agent": f"{USER_AGENT_PREFIX}-{agent}"},
            )
        except httpx.HTTPError as exc:
            reason = f"{type(exc).__name__} on attempt {attempt}"
        else:
            settled = _classify(response)
            if settled is not None:
                return settled
            reason = f"HTTP {response.status_code} on attempt {attempt}"
        if attempt < PING_ATTEMPTS:
            await asyncio.sleep(PING_BACKOFF_S)
    return (False, reason)


__all__ = [
    "OK_STATUS",
    "PING_ATTEMPTS",
    "PING_BACKOFF_S",
    "PING_TIMEOUT_S",
    "USER_AGENT_PREFIX",
    "check_ref",
    "ping",
    "ping_async",
]
