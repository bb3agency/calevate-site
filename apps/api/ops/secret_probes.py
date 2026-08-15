"""Ask a vendor whether a CANDIDATE credential works, before it goes live (§7).

    "Setting a wrong key today fails silently until a call drops. The test route asks
     the vendor a cheap authenticated question with the *candidate* value before storing
     it, and reports our own reason code. Wrong key, refused at the screen, is the
     difference between this console being a convenience and being a new outage source."

## What a probe is allowed to be

**A status code, and nothing else.** Every probe sends one authenticated request and
reads `response.status_code`. No probe parses a body, imports a vendor SDK, or names a
vendor field. That is what keeps this file compatible with hard rule 2 (engine
isolation): a vendor PAYLOAD SHAPE never enters our code, so nothing here can leak one
upward. `apps/api/engine/` remains the only module that may see one.

It also keeps the probes honest about what they prove. `200` means the vendor accepted
this credential for this request. It does not mean the key has the right scopes, the
account has balance, or the number is provisioned — and the console says so rather than
rendering a green tick that means more than it can.

## Why this runs in a request handler

CLAUDE.md forbids calling model providers from request handlers, and this deliberately
does. The exception is argued rather than assumed: the whole POINT of `/test` is that an
operator, at a keyboard, gets an answer BEFORE the value is stored — deferring it to a
worker would mean storing the candidate first (which is the outage this prevents) or
inventing a job whose result the console polls for. It is admin-realm, `platform:secrets`,
manually triggered, one outbound request, and bounded by `_TIMEOUT_S`. The rule exists to
keep vendor latency off tenant-facing and latency-critical paths; this is neither.

## Verified vs unverified, per OPERATIONS §2

The repo's doctrine is that vendor behaviour is verified, never assumed. Every probe below
carries `verified`, and the honest state of most of them today is FALSE: the endpoints are
read from this repo's own adapters (which do call them in production) but the specific
STATUS a bad credential produces has not been observed against the live vendor from this
build. `verified=False` does not weaken the probe — a probe still distinguishes "accepted"
from "rejected" — it changes what the console SAYS, and it is what stops an unverified
premise being invisible.

A key with NO probe answers `no_probe`, not a green tick. That distinction is the whole
file: "we could not check this" and "this works" must never render the same.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

import httpx

from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: One outbound request, bounded. An operator waiting on a screen will not wait longer,
#: and a vendor that is slow to answer is itself an answer worth reporting.
_TIMEOUT_S = 8.0

#: What we tell the operator. OUR codes, never the vendor's — a vendor's own error string
#: is a payload we would then be parsing, and the console has to switch on something
#: stable.
ProbeOutcome = Literal["accepted", "rejected", "unreachable", "no_probe"]


@dataclass(frozen=True, slots=True)
class Probe:
    """How to ask ONE vendor whether a credential authenticates.

    Declarative on purpose: a probe is a URL, a header shape and a timeout, so adding one
    is a data change that a reviewer can check against the vendor's documentation rather
    than a new code path with its own failure modes.
    """

    #: The cheapest authenticated read the vendor offers. A LIST endpoint wherever
    #: possible — it changes nothing, it is idempotent, and a wrong key is rejected
    #: before any resource is touched.
    method: str
    url: str
    #: Builds the auth header(s) from the candidate value. A function rather than a
    #: template because vendors disagree about the shape (`Bearer`, `X-API-Key`,
    #: query-string), and hiding that behind a format string would make the differences
    #: invisible at review time.
    headers: Callable[[str], dict[str, str]]
    #: Where the endpoint and the header shape were read from.
    source: str
    #: Has the REFUSAL been observed against the live vendor from this build? See the
    #: module docstring. False is the honest default and is reported to the operator.
    verified: bool


def _bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


#: The probes this build has. A key absent from here answers `no_probe`.
#:
#: Every endpoint and header shape below is READ FROM THIS REPO'S OWN ADAPTERS — the code
#: that already calls these vendors in production — rather than from memory, so a probe
#: cannot be authenticating differently from the thing it is testing.
PROBES: Mapping[str, Probe] = {
    # `apps/api/engine/bolna.py`: BASE_URL and `Authorization: Bearer` on every call;
    # `GET /v2/agent/all` is the listing the adapter itself uses.
    "bolna_api_key": Probe(
        method="GET",
        url="https://api.bolna.ai/v2/agent/all",
        headers=_bearer,
        source="apps/api/engine/bolna.py (BASE_URL, _request auth header, GET /v2/agent/all)",
        verified=False,
    ),
    # `apps/api/engine/cartesia.py`: BASE_URL and `X-API-Key`, both read at source and
    # cited there. `/voices` is a listing that costs nothing.
    "cartesia_api_key": Probe(
        method="GET",
        url="https://api.cartesia.ai/voices",
        headers=lambda value: {"X-API-Key": value, "Cartesia-Version": "2024-06-10"},
        source="apps/api/engine/cartesia.py (BASE_URL, API_KEY_HEADER)",
        verified=False,
    ),
    # `apps/workers/extraction.py`: SARVAM_CHAT_URL with `Authorization: Bearer`. The
    # models listing is the cheapest authenticated read on the same host.
    "sarvam_api_key": Probe(
        method="GET",
        url="https://api.sarvam.ai/v1/models",
        headers=_bearer,
        source="apps/workers/extraction.py (SARVAM_CHAT_URL host, Bearer auth)",
        verified=False,
    ),
}


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What we asked, what came back, and how much it is worth.

    `status` is the vendor's HTTP status and is the ONLY thing we take from them — see
    the module docstring on why nothing parses a body.
    """

    outcome: ProbeOutcome
    #: The vendor's HTTP status, when there was one.
    status: int | None
    #: Our own sentence for the operator. Never a vendor error string: that would be a
    #: payload, and it can contain anything including the credential we just sent.
    detail: str
    #: False when this probe's refusal behaviour has not been observed against the live
    #: vendor from this build (OPERATIONS §2). The console renders the difference.
    verified: bool
    #: Where the endpoint came from, so a reviewer can check it.
    source: str | None


async def probe_credential(key: str, candidate: str) -> ProbeResult:
    """Ask the vendor. Never raises, never logs the candidate, never stores it.

    The candidate is held for the duration of one request and is put into an
    `Authorization` header — which `core/logging.REDACT_KEYS` masks anywhere it could be
    logged, and which nothing here logs anyway.
    """
    probe = PROBES.get(key)
    if probe is None:
        return ProbeResult(
            outcome="no_probe",
            status=None,
            detail=(
                "This build has no way to test this credential with the vendor, so it "
                "has NOT been checked. Storing it is still safe — it simply will not be "
                "verified until the first real use."
            ),
            verified=False,
            source=None,
        )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.request(
                probe.method, probe.url, headers=probe.headers(candidate)
            )
    except Exception as exc:
        # The vendor, DNS, or our egress. Never the credential — a transport failure says
        # nothing about whether the key is right, and reporting it as "rejected" would
        # send an operator to rotate a key that was fine.
        log.warning(
            "secret_probe_unreachable", extra={"config_key": key, "reason": type(exc).__name__}
        )
        return ProbeResult(
            outcome="unreachable",
            status=None,
            detail=(
                "The vendor could not be reached, so this credential has NOT been "
                "checked. This says nothing about whether the key is correct."
            ),
            verified=probe.verified,
            source=probe.source,
        )

    status = response.status_code
    # 401/403 is the vendor saying no to THIS credential. Everything else that is not a
    # success is the vendor having a bad day, and conflating the two would tell an
    # operator to rotate a working key during someone else's outage.
    if status in (401, 403):
        outcome: ProbeOutcome = "rejected"
        detail = (
            "The vendor refused this credential. It is wrong, revoked, or lacks the "
            "access this endpoint needs — it has NOT been stored."
        )
    elif 200 <= status < 300:
        outcome = "accepted"
        detail = (
            "The vendor accepted this credential for one authenticated read. That does "
            "not prove it has every scope this platform uses, only that it authenticates."
        )
    else:
        outcome = "unreachable"
        detail = (
            f"The vendor answered {status}, which is neither an acceptance nor a "
            "refusal, so this credential has NOT been checked."
        )
    log.info("secret_probe", extra={"config_key": key, "outcome": outcome, "status": status})
    return ProbeResult(
        outcome=outcome,
        status=status,
        detail=detail,
        verified=probe.verified,
        source=probe.source,
    )


__all__ = ["PROBES", "Probe", "ProbeOutcome", "ProbeResult", "probe_credential"]
