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
    #: Which HTTP statuses mean "the vendor refused THIS credential". 401 and 403 are the
    #: two ways an API says no to a key, and for most vendors both are exactly that.
    #:
    #: PER PROBE because one vendor splits them, and getting it wrong costs the mistake
    #: this whole file exists to avoid. Resend answers **403 `invalid_api_key`** for a
    #: wrong key but **401 `restricted_api_key`** for a REAL key that is scoped to sending
    #: only — and sending-only is the least-privilege key this platform asks the operator
    #: to create. Reporting that 401 as a refusal would tell them to rotate a working key.
    #: A status outside this tuple that is not a success falls through to `unreachable`,
    #: whose sentence is already "this credential has NOT been checked", which is the
    #: honest answer for a read a valid key is simply not allowed to make.
    refusal_statuses: tuple[int, ...] = (401, 403)
    #: Appended to the `unreachable` sentence, when this probe knows why a non-refusal
    #: rejection is expected. `None` for probes with nothing to add.
    inconclusive_detail: str | None = None


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
    # THE EMAIL CREDENTIAL, TESTABLE FOR THE FIRST TIME. `smtp_password` never had a probe
    # and could not have one: a probe is an HTTP request and SMTP AUTH is a different
    # protocol, so a wrong mail password was always discovered at the first hot lead.
    # Moving email onto an HTTP API is what makes "wrong key, refused at the screen"
    # possible here at all.
    #
    # `GET /domains` rather than a send: it is a LIST, it changes nothing, and it is the
    # cheapest authenticated read Resend documents. It is NOT a check that the sender
    # domain is verified — this file reads a status code and never a body, so it cannot
    # see which domains came back. That check is the operator's, in the Resend dashboard.
    #
    # Host and auth header are READ AT SOURCE from `apps/workers/transport.py`'s
    # `RESEND_SEND_URL` and its `Authorization: Bearer` header — the same evidence the
    # other three probes use, which is what keeps a probe from authenticating differently
    # from the thing it tests. The `/domains` PATH is REPORTED, NOT READ
    # (`resend.com` is refused by this environment's egress proxy).
    # STILL PROBEABLE THOUGH NO LONGER STORABLE, and that is deliberate rather than an
    # oversight left behind by the env-only move. `/test` takes a CANDIDATE the caller
    # already holds and stores nothing, so "check this key before I put it in the host's
    # environment" is exactly the question it answers — and it is the only chance to
    # catch a wrong Resend key before a deploy, since the console can no longer set it.
    # `manageable_secret_keys` excludes it; `probe_credential` deliberately does not.
    "resend_api_key": Probe(
        method="GET",
        url="https://api.resend.com/domains",
        headers=_bearer,
        source=(
            "apps/workers/transport.py (RESEND_SEND_URL host, Bearer auth); "
            "the /domains path and the 401-vs-403 split are REPORTED, NOT READ"
        ),
        verified=False,
        refusal_statuses=(403,),
        inconclusive_detail=(
            "A Resend key with `Sending access` cannot read the domain list, and that is "
            "the key type this platform asks for — so a refusal of THIS read is expected "
            "and is not evidence the key is wrong."
        ),
    ),
    # ⚠ THE TWO DECLARED LLM LEGS (D-456 — `openai`, `google`) DELIBERATELY HAVE NO PROBE,
    # and it is not an omission. `scripts/check_model_residency.py` BANS the string
    # `api.openai.com` outside the OpenAI leg's own builder, and bans
    # `generativelanguage.googleapis.com` from EVERY literal in the tree (its comment: "ZERO
    # LITERALS IN THIS TREE MAY NAME IT") — because a hostname naming a model-inference host
    # is a residency claim the posture governs. A probe URL is exactly such a literal, so a
    # `/test` for either key cannot exist without violating the posture. The Azure key has no
    # probe either (its endpoint needs the per-deployment resource name). All three LLM
    # credentials therefore answer `no_probe` — "storing it is still safe, it simply will
    # not be verified until first use" — which is the honest state, not a gap.
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
    # `refusal_statuses` is the vendor saying no to THIS credential — 401/403 for every
    # probe but Resend's, which splits them (see the field's own comment). Everything else
    # that is not a success is the vendor having a bad day, or a read this key is not
    # allowed to make, and conflating either with a refusal would tell an operator to
    # rotate a working key.
    if status in probe.refusal_statuses:
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
        if probe.inconclusive_detail:
            detail = f"{detail} {probe.inconclusive_detail}"
    log.info("secret_probe", extra={"config_key": key, "outcome": outcome, "status": status})
    return ProbeResult(
        outcome=outcome,
        status=status,
        detail=detail,
        verified=probe.verified,
        source=probe.source,
    )


__all__ = ["PROBES", "Probe", "ProbeOutcome", "ProbeResult", "probe_credential"]
