"""The carrier's HTTP leg: the answer document that points Plivo at the worker (D-610,
`docs/PIPECAT-MIGRATION.md` §6 step 6).

**ONE ROUTE, AND IT IS THE ONLY THING BETWEEN A RINGING NUMBER AND THE MEDIA STREAM.**
A carrier fetches an *answer document* over HTTP before any WebSocket exists; the
document names the socket it should then connect to. This module renders that document
and nothing else: no database, no Redis, no queue, no vendor SDK.

WHY IT IS HERE AND NOT IN `apps/voice-worker`
=============================================
The renderer used to live in `voice_worker/carrier.py`, beside the transport that
consumes its result, with a docstring admitting the process that holds it *cannot serve
it* ("this container has no HTTP server"). The route that serves it cannot import it
either: `voice_worker` drags `pipecat-ai`, ONNX turn detection and three vendor SDKs, and
hard rule 3 forbids heavy imports on this service by name (`tests/
voice_runtime_import_surface_test.py` is what actually measures that). So the three
symbols moved HERE — the process that really serves them — rather than being copied,
because two renderers of one wire format is the "one way per problem" defect even while
both agree.

Hard rule 2 sanctions this location explicitly: *"only `apps/api/engine/`, its
voice-runtime twin, and `apps/voice-worker/` may … see vendor payload shapes"*. This is
the voice-runtime twin's second file, beside `engine_intake.py`.

WHAT IS VERIFIED, AND WHAT IS NOT
=================================
`www.plivo.com` is EGRESS-BLOCKED from the build container — re-measured 15 Sep 2026,
`curl https://www.plivo.com/docs/` → `curl: (56) CONNECT tunnel failed, response 403`. So
**no claim here is made from Plivo's own documentation.** The evidence class for the
document's shape is PIPECAT SOURCE: the shipped client of that protocol, at
`pipecat/runner/run.py:1435-1438` (the template) and `:1456` (the media type), from the
pinned `pipecat-ai==1.10.0`. `tests/voice_runtime_carrier_answer_test.py` extracts that
template from the installed tree and compares attribute for attribute, so a dependency
bump that changes the grammar fails CI rather than a phone call.

⚠ **FOUR THINGS ARE UNKNOWN AND ARE NOT INVENTED HERE.**

1. **Whether Plivo signs its request for the answer document, and how.** Nothing in the
   installed Pipecat tree verifies a Plivo request signature — the only Plivo REST
   endpoint in the whole package is the hangup (`serializers/plivo.py:184`). So no
   signature is verified here and none is invented; `verify_answer_source` argues in full
   why a guessed HMAC would be worse than none, why a MAC on the ref buys nothing, and why
   the control that IS seamed is the source-IP allowlist hard rule 3 already names. Today
   that allowlist is empty because the carrier's egress ranges are UNKNOWN for the same
   egress-blocked reason, so the method is `"none"` and the log line says so on every
   served document. Closing it is a gate, not a guess: OPERATIONS §2 gate 55.
   **The names in the founder's brief — `From`, `CallUUID`, `X-Plivo-Signature-V2` — are
   NOT written anywhere in this module.** They are plausible and unverified, and a name
   that is probably right is the defect class D-631 exists for.
2. **Which HTTP method the carrier uses.** An answer URL is configured on the number, and
   whether it is fetched with GET or POST is the vendor's to state. Both are registered and
   both are read the same way — query parameters always, a form-encoded body only once a
   parameter name is declared (`_answer_request_params`) — so the route is correct under
   both readings without a claim about which one happens. That is not the same class of
   guess as inventing a field name: the set of methods is two and we serve the same bytes
   for each.
3. **WHICH PARAMETER OF THAT REQUEST CARRIES THE CALLING PARTY.** The mechanism that
   reads, forwards and folds it is built end to end and driven by test; what is missing is
   one cell of `CARRIER_ANSWER_CONTRACT`, filled by one founder reading
   (`docs/evidence/carrier-caller-identity.md` §5(d)). Until then every answer carries the
   state `unparsed_by_client` with its ground, which is a named UNKNOWN and not a NULL.
4. **Whether Pipecat Cloud preserves the URL PATH of the WebSocket it terminates.** That
   is the other half of `bot.resolve_call_identity` and is recorded there, not here. Its
   QUERY is the other half of `carrier.claim_from_stream_url`; the same unknown covers
   both, and the claim is absent rather than wrong if the query is stripped.

HARD RULE 1 — THE ROUTE IS THE URL, NEVER THE DIALLED NUMBER
============================================================
D-603. The agent ref is a path segment of the answer URL the operator binds to the
number, so this handler reads NO row to decide whose call it is: it validates the ref it
was given and echoes it into the stream URL. Resolving a number to a tenant before a
tenant is known would be a cross-tenant read of `phone_numbers`, a FORCE-RLS'd table with
no exemption — and Pipecat's Plivo parser leaves `from`/`to` `None` anyway
(`runner/utils.py:257-262`), so the number is not even on the socket.

⚠ **AND THE CALLING PARTY THIS ROUTE NOW READS DOES NOT CHANGE THAT.** It is carried, and
it is never routed on: the route is decided by `parse_owned_runtime_agent_ref` before any
parameter of the request is looked at, and `caller_identity_from_answer_request` runs
after the ref has already named the tenant. A number that arrived on an attacker's request
can therefore mislabel a call's caller — which is why the worker records it as a CLAIM
with a state and a ground — but it can never reach another tenant's row.

HARD RULE 3 — WHY THERE IS NO `X-Ack-Ms` AND NO THIRD ACK SERIES
================================================================
`webhook_routes.AckMeter` exists because the receiver's ack can be made slow by something
outside it: an inbox claim, an enqueue, a body that arrives in pieces. This handler has
none of those — it performs no IO at all, and its whole cost is a UUID parse, a dict
lookup and an ElementTree render of two elements. It reads the request's QUERY, which the
ASGI server has already parsed out of the request line, and reads its BODY only once
`CARRIER_ANSWER_CONTRACT` declares a parameter name to look in — never today, and bounded
to one `parse_qsl` over already-buffered bytes when it happens (`_answer_request_params`).
A third percentile with no dependency behind it would be instrumentation that can only
ever report the same number, and a third
alert code in `alarm_severity.py` and `runbooks/alarm-index.md` that can never fire.
`tests/voice_runtime_carrier_answer_test.py` asserts the absence of IO instead, which is
the property the budget actually rests on.

HARD RULE 6
===========
⚠ **THIS SECTION USED TO OPEN "No phone number ever reaches this process", AND THAT IS NO
LONGER TRUE.** A calling party on the carrier's own request is exactly what this route now
reads, and the sentence would have gone stale the day a name landed in
`CARRIER_ANSWER_CONTRACT` rather than the day the code changed. What IS true, and is
asserted rather than promised: **no number is ever logged here.** What is logged is the
tenant and agent ids of a served document, the authenticity method, and the caller's STATE
and GROUND — two strings written in this module and never built from wire data, so neither
can carry a number. On a refusal: a reason and never the token, which is an
attacker-controlled string.

A number DOES leave this module in one place — the stream URL — and that is a decision with
a written ground rather than an oversight. `plivo_stream_url` argues it in full: what it
costs (an edge access log at two processors who already hold the call), what it buys (a
`known` state, without which every in-call opt-out answers `caller_number_unknown` for
ever), what bounds it, and what replaces it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import parse_qsl, quote, urlencode
from xml.etree.ElementTree import Element, tostring

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from calevate_shared.client_address import client_ip
from calevate_shared.engine import EngineAgentRef, parse_owned_runtime_agent_ref
from calevate_shared.worker_api import CallerIdentityState
from fastapi import APIRouter, Request, Response

log = get_logger(__name__)

router = APIRouter(prefix="/carrier/v1", tags=["carrier"])

#: The telephony leg's rate, in the one place this deployable needs it.
#:
#: DECLARED RATHER THAN IMPORTED, because the module that holds the other copy
#: (`voice_worker/pipeline.TELEPHONY_SAMPLE_RATE_HZ`) is in a container this one may not
#: import. It is not two answers to one question: BOTH are pinned to the same vendor
#: source by test rather than to each other — the worker's to the serializer
#: (`serializers/plivo.py:54`, `:145-147`), this one to the answer template's own
#: `contentType`, which the test parses out of `runner/run.py`. A bump that moved the rate
#: would fail on both sides independently.
TELEPHONY_SAMPLE_RATE_HZ: Final[int] = 8000

#: What `plivo_answer_document` must be served as. Pipecat's runner answers its own
#: template with `media_type="application/xml"` (`runner/run.py:1456`).
ANSWER_DOCUMENT_CONTENT_TYPE: Final = "application/xml"

#: THE CARRIER THIS DEPLOYMENT ANSWERS FOR, and the value the control plane CLAIMS on the
#: stream URL (issue 3). It is not detected here and never could be: the route path is
#: minted by us, one carrier per path, so the carrier's name is a fact of our own
#: configuration rather than something to sniff for.
ANSWER_CARRIER: Final = "plivo"

#: Evidence classes, hard rule 11's vocabulary, spelled as a type so a row cannot omit one.
EvidenceClass = Literal["VERIFIED-VENDOR-DOCS", "VENDOR-PUBLISHED", "REPORTED", "UNKNOWN"]

#: THE QUERY PARAMETERS THE CONTROL PLANE PUTS ON THE STREAM URL, read back by
#: `voice_worker.carrier.claim_from_stream_url`.
#:
#: DECLARED TWICE ON PURPOSE, exactly like `TELEPHONY_SAMPLE_RATE_HZ` above and for the
#: same reason: the worker may not be imported here (hard rule 3) and this may not be
#: imported there. `tests/carrier_answer_identity_test.py` asserts the two spellings equal
#: across the deployables, which is the only place that agreement can be checked.
CLAIM_CARRIER_PARAM: Final = "carrier"
CLAIM_CALLER_PARAM: Final = "caller"
CLAIM_CALLER_STATE_PARAM: Final = "caller_state"


@dataclass(frozen=True, slots=True)
class CarrierAnswerContract:
    """What we know about ONE carrier's request for the answer document, with its evidence.

    **THE WHOLE POINT OF THIS TYPE IS THAT EVERY CELL CARRIES ITS OWN EVIDENCE CLASS**, so
    a not-finding cannot be read later as a vendor fact. D-631 is the correction this
    repository already paid for: a previous session failed to locate a vendor page and
    recorded the absence as knowledge. An empty `calling_party` here means **"nobody has
    read the vendor's page"** and says nothing whatever about what the carrier sends.

    Keyed on the CARRIER rather than on Plivo, for the reason
    `voice_worker.carrier.CarrierIdentityParse` already gives: Plivo signup failed, a
    Telnyx ticket is open, and D-05 picks Exotel (`docs/ROADMAP.md:348`). A seam that
    answered only for Plivo would be thrown away with Plivo.

    ONE READING FILLS A ROW. `docs/evidence/carrier-caller-identity.md` §5(d) is the
    question whose answer fills `calling_party`; §5(e) fills `source_ip_allowlist`; §5(f)
    fills `signature_header`. Nothing here is a runtime switch an operator flips — it is a
    table of vendor facts, and a vendor fact arrives by being read.
    """

    carrier: str

    #: The parameter names, in preference order, that carry the CALLING party on the
    #: carrier's request for the answer document. EMPTY means UNKNOWN — never "absent".
    calling_party: tuple[str, ...]
    calling_party_evidence_class: EvidenceClass
    calling_party_evidence: str

    #: The carrier's published egress addresses, as `parse_source_ip_allowlist` spells
    #: them. EMPTY means no allowlist is declared, and `verify_answer_source` then reports
    #: method `"none"` rather than refusing — see there for why that is not a fail-open.
    source_ip_allowlist: tuple[str, ...]
    source_ip_evidence_class: EvidenceClass
    source_ip_evidence: str

    #: The header a carrier signs its request with, if it signs at all. `None` means
    #: UNKNOWN, and there is deliberately NO verifier here — see `verify_answer_source`.
    signature_header: str | None
    signature_evidence_class: EvidenceClass
    signature_evidence: str

    #: Does the carrier echo parameters WE attach to the `<Stream>` element back inside the
    #: WebSocket `start` event? `True` for a carrier that does; `None` for UNKNOWN. This is
    #: the cell that would let the calling party travel in the answer document's BODY
    #: instead of on the URL — see `plivo_stream_url`'s note on hard rule 6.
    echoes_stream_parameters: bool | None
    echoes_stream_parameters_evidence: str


#: ⚠ **EVERY PLIVO CELL BELOW IS `UNKNOWN`, AND THAT IS A MEASUREMENT, NOT A SHRUG.**
#: `www.plivo.com` and `api.plivo.com` are EGRESS-BLOCKED from this container: re-measured
#: 19 Sep 2026, `curl -sS -o /dev/null -w '%{http_code}' https://www.plivo.com/docs/` →
#: **`curl: (56) CONNECT tunnel failed, response 403`, HTTP code `000`** (a connection
#: failure, not a status). So no parameter name, no egress range and no signature algorithm
#: is written here, because the only honest alternative to a read page is a blank cell.
#:
#: The founder's brief named `From`, `CallUUID` and `X-Plivo-Signature-V2`. Those are
#: plausible and they are **not verified from here**, so they are not in this table. A name
#: that is probably right is the exact defect class D-631 exists for.
CARRIER_ANSWER_CONTRACT: Final[Mapping[str, CarrierAnswerContract]] = {
    ANSWER_CARRIER: CarrierAnswerContract(
        carrier=ANSWER_CARRIER,
        calling_party=(),
        calling_party_evidence_class="UNKNOWN",
        calling_party_evidence=(
            "UNKNOWN — www.plivo.com is egress-blocked here (CONNECT tunnel failed, "
            "response 403; HTTP 000, measured 19 Sep 2026). "
            "docs/evidence/carrier-caller-identity.md §5(d) is the question that fills this."
        ),
        source_ip_allowlist=(),
        source_ip_evidence_class="UNKNOWN",
        source_ip_evidence=(
            "UNKNOWN — whether Plivo publishes egress ranges for answer-URL requests has "
            "not been read; www.plivo.com is egress-blocked here (HTTP 000, 19 Sep 2026). "
            "docs/evidence/carrier-caller-identity.md §5(e)."
        ),
        signature_header=None,
        signature_evidence_class="UNKNOWN",
        signature_evidence=(
            "UNKNOWN — whether Plivo signs this request, under which header and with which "
            "canonical string and digest, has not been read; nothing in the pinned "
            "pipecat-ai==1.10.0 tree verifies a Plivo request signature (its only Plivo "
            "REST endpoint is the hangup, serializers/plivo.py:184). "
            "docs/evidence/carrier-caller-identity.md §5(f)."
        ),
        echoes_stream_parameters=None,
        echoes_stream_parameters_evidence=(
            "UNKNOWN — docs/evidence/carrier-caller-identity.md §5(c). The shape is known "
            "to exist for another carrier: Twilio's answer document supplies parameters "
            "that arrive as `start.customParameters`, which our pinned client reads at "
            "pipecat/runner/utils.py:232,240-241 (VERIFIED-VENDOR-DOCS, read 19 Sep 2026)."
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class AnswerCallerIdentity:
    """Who the carrier said is calling, on ITS request for the answer document.

    The state vocabulary is `calevate_shared.worker_api.CallerIdentityState` — the same
    four words the worker and `apps/api/worker/tools.py` already speak, because this is a
    FIFTH SOURCE for that one verdict and not a second vocabulary. `apps/api/worker/
    tools.py:150` answers an opt-out with `caller_number_unknown:<state>`, so the word
    chosen here reaches a sentence an agent says to a person. It is never guessed.

    HARD RULE 6: `e164` is PII and is carried, never logged. `ground` is written in this
    module and never built from wire data, so it cannot carry a number.
    """

    state: CallerIdentityState
    ground: str
    e164: str | None = None


def caller_identity_from_answer_request(
    carrier: str, params: Mapping[str, str]
) -> AnswerCallerIdentity:
    """The calling party on the carrier's own HTTP request, as a state that is explainable.

    **THIS IS THE STATE DROP, CLOSED AS FAR AS IT CAN BE CLOSED FROM THIS CONTAINER.** The
    carrier's request reaches a process we control and it is the only leg on which the
    calling party is plausibly available at all: the pinned client parses none for Plivo
    (`pipecat/runner/utils.py:257-262`), and a REST lookup is impossible under Model B
    because we hold no per-tenant carrier credential (`docs/evidence/
    carrier-caller-identity.md` §3). What remains is this request — and what is missing is
    only the NAME of its parameter, which is one founder reading.

    **NO NUMBER IS NORMALISED HERE.** `calevate_shared.extraction.normalize_phone` is the
    one canonicaliser (`leads.phone_e164`, `dnc_list.phone_e164` and the dispatch gate all
    key on its output) and it runs in the worker, on the value this leg forwards verbatim.
    A second normalisation on a 500ms path would be a second answer to one question and a
    suppression that suppresses nothing if the two ever disagreed.
    """
    contract = CARRIER_ANSWER_CONTRACT.get(carrier)
    if contract is None:
        return AnswerCallerIdentity(
            state="unparsed_by_client",
            ground=(
                f"carrier {carrier!r} has no row in CARRIER_ANSWER_CONTRACT, so nothing "
                "here knows which parameter of its request carries a calling party"
            ),
        )
    if not contract.calling_party:
        return AnswerCallerIdentity(
            state="unparsed_by_client",
            ground=(
                f"no calling-party parameter is declared for {carrier!r}: "
                f"{contract.calling_party_evidence}"
            ),
        )
    for name in contract.calling_party:
        value = params.get(name, "")
        if value.strip():
            return AnswerCallerIdentity(
                state="known",
                ground=f"the {carrier} answer request carried {name}",
                e164=value.strip(),
            )
    return AnswerCallerIdentity(
        state="withheld_by_carrier",
        ground=(
            f"the {carrier} answer request declares "
            f"{'/'.join(contract.calling_party)} ({contract.calling_party_evidence_class}: "
            f"{contract.calling_party_evidence}) and carried no value in it"
        ),
    )


@dataclass(frozen=True, slots=True)
class AnswerSourceVerdict:
    """Whether the request for an answer document is authentic, and by which method."""

    ok: bool
    method: Literal["source_ip", "none"]
    reason: str


def verify_answer_source(carrier: str, source_ip: str | None) -> AnswerSourceVerdict:
    """Is this request really the carrier's? — answered from the table, never from a guess.

    **WHY THERE IS NO SIGNATURE VERIFIER HERE, AND WHY THAT IS THE SECURE CHOICE.** The
    founder's brief named `X-Plivo-Signature-V2`. Verifying it needs the header's exact
    name, the canonical string and the digest, and `www.plivo.com` is egress-blocked from
    this container (HTTP 000, 19 Sep 2026). A guessed HMAC would reject every real call for
    a reason nobody could debug — strictly worse than none — so `signature_header` stays
    `None` in the table and this function has no branch for it. `engine_intake.verify_source`
    refuses an `hmac` engine it cannot verify for the identical reason; the difference is
    that there a verifier is DECLARED and missing, here nothing is declared at all.

    **WHY NOT A MAC ON THE REF (the brief's option (a)).** It buys nothing that is not
    already bought, and it cannot be built inside this change's fence. The ref is
    `pipecat:<uuid7>:<uuid7>` (`calevate_shared.engine.owned_runtime_agent_ref`) — two
    128-bit identifiers, so "guess a ref" is not an attack that works, and a MAC does not
    help against the attack that does work (a HARVESTED ref is equally usable whether or
    not it carries a tag). Minting lives in `apps/api/engine/pipecat.py` and the grammar in
    `packages/shared`, both outside this fence, so the change would also be a cross-cutting
    one for no gain.

    **SO THE CONTROL IS THE ONE THIS REPO ALREADY USES FOR UNSIGNED CALLERS** — a
    source-IP allowlist, hard rule 3's own answer, and the same shape as
    `engine_intake.verify_source`. It is DATA-DRIVEN rather than flag-driven: the day
    `source_ip_allowlist` holds an address, a request from anywhere else is REFUSED, with
    no code change and no switch to remember. Until then the method is `"none"` and the
    reason says so in the log line.

    **`"none"` IS NOT A FAIL-OPEN DRESSED UP, and the distinction is worth stating.** An
    empty allowlist enforced would refuse every call with no remedy available to an
    operator (`calevate_shared.config:396` makes the same argument: "an empty allowlist is
    an outage"), and the remedy — the carrier's published ranges — is a vendor fact, not a
    setting. What this route actually exposes to an unauthenticated stranger is bounded and
    is stated rather than assumed: the response is a stream URL the requester could have
    constructed from the ref they already had, it holds no secret, no PII and no number,
    and serving it warms NOTHING — a Pipecat Cloud container is started by a WebSocket
    connection, which a stranger can attempt with or without this route, and which
    `voice_worker.carrier.route_of` refuses when the token names no agent. The refusal
    below still comes before the URL is minted, so an unparseable ref learns nothing.
    """
    contract = CARRIER_ANSWER_CONTRACT.get(carrier)
    allowlist = contract.source_ip_allowlist if contract is not None else ()
    if not allowlist:
        return AnswerSourceVerdict(
            ok=True,
            method="none",
            reason=(
                "no source-ip allowlist is declared for this carrier"
                if contract is not None
                else f"carrier {carrier!r} has no row in CARRIER_ANSWER_CONTRACT"
            ),
        )
    if source_ip is None:
        # The EDGE broke, not the vendor — a different runbook entry, so a different
        # reason string (`engine_intake.verify_source` draws the same line).
        return AnswerSourceVerdict(ok=False, method="source_ip", reason="client ip not established")
    if source_ip in allowlist:
        return AnswerSourceVerdict(ok=True, method="source_ip", reason="source ip allowlisted")
    return AnswerSourceVerdict(ok=False, method="source_ip", reason="source ip not allowlisted")


def plivo_stream_url(
    base_wss_url: str,
    ref: EngineAgentRef,
    *,
    carrier: str | None = None,
    caller: AnswerCallerIdentity | None = None,
) -> str:
    """The URL to hand the carrier for one agent: the base, then the route as a path segment.

    `quote` with no safe characters, because the ref contains colons and a carrier that
    normalised them would hand us back a token `carrier.route_of` cannot parse. `%3A`
    round-trips through every ASGI server in this tree.

    A PATH SEGMENT rather than a query parameter or a header: Pipecat's own runner calls
    that the recommended form for telephony providers (`runner/run.py:1410-1414`), and a
    provider that drops a query string on a redirect is a failure with no error.

    **THE ROUTE STAYS THE LAST PATH SEGMENT AND THE CLAIM GOES IN THE QUERY**, because
    `apps/voice-worker/bot.py::_route_token` reads the ref as `path.rsplit("/", 1)[-1]` and
    a URL's query is not part of its path. A second path segment would have silently
    re-routed every call to a token that is not an agent ref.

    ⚠ **HARD RULE 6: A NUMBER IN A URL IS A NUMBER IN AN ACCESS LOG, AND THIS PUTS ONE
    THERE. THE DECISION, AND ITS GROUND.** Two parties see this URL: the carrier, whose own
    datum the number is, and Pipecat Cloud, which terminates the socket and already
    processes the entire audio of the call. Neither learns anything it does not hold — what
    changes is that the number lands in an EDGE LOG, retained on a schedule that is not the
    media's and is not ours. That is a real cost and it is accepted for a specific reason:
    the alternative is that `CallerIdentityState` can never be `known` on this engine, and
    `apps/api/worker/tools.py:150` then answers every in-call opt-out with
    `caller_number_unknown` — a caller who asks not to be called again is told we cannot
    identify them, on every call, for ever. A logging exposure to two processors who
    already hold the call does not outweigh a compliance path that never works.
    What is done to bound it: the parameter is OMITTED entirely when there is no number, so
    a URL never carries an empty PII slot; the value never reaches a log line of ours on
    either leg (asserted by test on both sides); and our own answer-URL path carries no
    number at all, so this service's access log is clean.
    **THE TARGET THAT REMOVES EVEN THAT** is the answer document's BODY — a carrier that
    echoes stream parameters back in its `start` event, the shape our pinned client already
    reads for Twilio (`pipecat/runner/utils.py:232,240-241`). That is
    `CarrierAnswerContract.echoes_stream_parameters`, UNKNOWN for Plivo, and
    `docs/evidence/carrier-caller-identity.md` §5(c) is the question that settles it. No
    `<Parameter>` element is emitted here, because its name and grammar would be a guess
    copied from a different vendor.
    """
    url = f"{base_wss_url.rstrip('/')}/{quote(ref, safe='')}"
    claim: dict[str, str] = {}
    if carrier is not None:
        claim[CLAIM_CARRIER_PARAM] = carrier
    if caller is not None:
        claim[CLAIM_CALLER_STATE_PARAM] = caller.state
        if caller.e164 is not None:
            claim[CLAIM_CALLER_PARAM] = caller.e164
    return f"{url}?{urlencode(claim)}" if claim else url


def plivo_answer_document(stream_url: str) -> str:
    """The XML a carrier is served when a call arrives, as one string.

    **THE SHAPE IS PIPECAT'S OWN TEMPLATE, NOT A GUESS** (`runner/run.py:1435-1438`):

        <Response><Stream bidirectional="true" keepCallAlive="true"
                          contentType="audio/x-mulaw;rate=8000">wss://.../ws</Stream></Response>

    Every attribute is copied from there and none is added. What each one MEANS is Plivo's
    documentation to state and that host is egress-blocked here, so this function is a
    renderer of a verified template rather than a claim about the vendor's grammar.

    **BUILT WITH AN XML SERIALIZER RATHER THAN AN f-STRING.** The URL carries a
    `%`-encoded ref; an f-string would put an unescaped `&` straight into a document a
    carrier must parse. This is a wire value, and hand-rolling the escaping of one is the
    class of defect the quality bar names.
    """
    stream = Element(
        "Stream",
        {
            "bidirectional": "true",
            "keepCallAlive": "true",
            "contentType": f"audio/x-mulaw;rate={TELEPHONY_SAMPLE_RATE_HZ}",
        },
    )
    stream.text = stream_url
    response = Element("Response")
    response.append(stream)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(response, encoding="unicode")


def _stream_base_url() -> str:
    """Where the worker's WebSocket lives, or a refusal an operator can act on.

    NOT A DEFAULT. A guessed hostname here would produce a *served* answer document
    pointing at nothing — a call that connects, rings, and dies silently — which is worse
    than a refusal the carrier retries and an operator can read. It is configuration
    (`PIPECAT_STREAM_BASE_URL`) because it is the address of a deployment that does not
    exist yet (BLOCKER-1), and because Pipecat Cloud's own hostname scheme is UNKNOWN from
    this container.
    """
    base = get_settings().pipecat_stream_base_url
    if not base:
        raise ProblemError(
            kind="dependency",
            code="carrier_stream_base_not_configured",
            title="This deployment cannot answer a call yet",
            detail=(
                "PIPECAT_STREAM_BASE_URL is unset, so there is no WebSocket address to "
                "send the carrier to."
            ),
            remediation=(
                "Set PIPECAT_STREAM_BASE_URL to the deployed voice worker's wss:// base "
                "(docs/PIPECAT-MIGRATION.md §6 step 6)."
            ),
        )
    return base


#: Only a form-encoded body is parsed, and only when a parameter name is declared.
#: `multipart/form-data` is deliberately NOT handled: Starlette needs `python-multipart`
#: for it, that is a dependency on a 500ms path, and no carrier has been read as using it.
_FORM_CONTENT_TYPE: Final = "application/x-www-form-urlencoded"


async def _answer_request_params(
    request: Request, contract: CarrierAnswerContract
) -> Mapping[str, str]:
    """The carrier's own parameters, query and form-encoded body alike.

    **THE BODY IS READ ONLY WHEN A PARAMETER NAME IS DECLARED**, which is never today. That
    is not timidity: `tests/voice_runtime_carrier_answer_test.py` asserts this handler does
    no IO, and that absence is the whole argument for the route having no third ack series
    (module docstring, hard rule 3). Reading a body nobody has a name to look in would
    spend the property and buy nothing. The day §5(d) fills the row, one small form read
    joins the path — bounded, `parse_qsl` over bytes already buffered by the ASGI server,
    and still no database, no Redis and no queue.

    `parse_qsl` rather than `await request.form()`: the form helper reaches for the
    multipart machinery and `python-multipart`, neither of which belongs on this path.

    Query parameters are read first and the body wins on a clash, because UNKNOWN 2 in the
    module docstring is live — whether the carrier fetches with GET or POST is the vendor's
    to state — and a carrier that sends both would mean the body is the considered one.
    """
    if not contract.calling_party:
        return {}
    params: dict[str, str] = dict(request.query_params)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == _FORM_CONTENT_TYPE:
        body = await request.body()
        params.update(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))
    return params


@router.api_route("/plivo/answer/{ref}", methods=["GET", "POST"], include_in_schema=False)
async def plivo_answer(ref: str, request: Request) -> Response:
    """Serve the answer document for one agent, or refuse without minting a stream URL.

    **THE REFUSAL COMES BEFORE THE URL, AND THAT ORDERING IS THE SECURITY PROPERTY.** An
    unparseable ref never reaches `plivo_stream_url`, so a stranger probing this path
    cannot get the worker's address out of it, and the carrier is never told to open a
    socket that the worker would then have to refuse.

    `include_in_schema=False`: no browser and no generated client calls this, and the
    OpenAPI snapshot in CI describes the surfaces a client consumes.

    **THE ORDER OF THE FOUR STEPS IS THE DESIGN.** Authenticity, then the ref, then the
    identity read, then the URL — so an inauthentic or unknown caller is turned away before
    anything is read from its request and before the worker's address is minted.

    **WHAT IT NOW FORWARDS.** The carrier's request is the one leg on which the calling
    party is plausibly available (`caller_identity_from_answer_request`), and the stream URL
    minted one line later is ours to shape. The verdict — and the number, when there is one
    — therefore rides that URL as an EXPLICIT CLAIM which
    `voice_worker.carrier.claim_from_stream_url` reads back, instead of the worker waking up
    with nothing and being told to sniff for it. `Request` is injected for exactly this:
    before, the parameters were structurally unreachable rather than merely unread.
    """
    source = verify_answer_source(
        ANSWER_CARRIER,
        client_ip(
            request.client.host if request.client else None,
            request.headers,
            app_env=get_settings().app_env,
        ),
    )
    if not source.ok:
        # The address IS in the line, and deliberately: this alert's whole use is telling a
        # vendor renumber from an edge fault (`webhook_routes` argues the same). It is not
        # PII of a caller — it is a machine's address.
        log.warning(
            "carrier_answer_refused",
            extra={"reason": source.reason, "method": source.method},
        )
        raise ProblemError(
            kind="not_found",
            code="carrier_source_not_allowlisted",
            title="That is not an agent of this platform",
            # SAME OUTWARD SHAPE AS AN UNKNOWN REF, on purpose: a distinct status or
            # sentence here would tell a prober that the ref it holds IS real and only its
            # address is wrong, which is precisely the half worth not confirming. The two
            # cases are told apart in the LOG, where only an operator reads.
            detail="The answer URL does not carry an owned-runtime agent ref.",
            remediation=(
                "Point the number at the answer URL the agent's screen shows, from an "
                "address in the carrier's published egress range "
                "(docs/PIPECAT-MIGRATION.md §6 step 6)."
            ),
        )
    parsed = parse_owned_runtime_agent_ref(ref)
    if parsed is None:
        # THE REF IS NEVER ECHOED (hard rule 6's neighbour: anything can GET a URL, and a
        # message quoting the segment would put an arbitrary string in an operator's log).
        log.warning("carrier_answer_refused", extra={"reason": "ref_names_no_agent"})
        raise ProblemError(
            kind="not_found",
            code="carrier_ref_unknown",
            title="That is not an agent of this platform",
            detail="The answer URL does not carry an owned-runtime agent ref.",
            remediation=(
                "Point the number at the answer URL the agent's screen shows "
                "(docs/PIPECAT-MIGRATION.md §6 step 6)."
            ),
        )
    tenant_id, agent_id = parsed
    contract = CARRIER_ANSWER_CONTRACT[ANSWER_CARRIER]
    caller = caller_identity_from_answer_request(
        ANSWER_CARRIER, await _answer_request_params(request, contract)
    )
    document = plivo_answer_document(
        plivo_stream_url(_stream_base_url(), ref, carrier=ANSWER_CARRIER, caller=caller)
    )
    # Ids and words (hard rule 6). This is the one line that says a real carrier reached
    # us. `caller.state` and `caller.ground` are written in THIS module and never built
    # from wire data, so neither can carry a number; `caller.e164` is deliberately absent
    # from this line and from every other line here.
    log.info(
        "carrier_answer_served",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "auth_method": source.method,
            "caller_identity": caller.state,
            "caller_identity_ground": caller.ground,
        },
    )
    return Response(
        content=document,
        media_type=ANSWER_DOCUMENT_CONTENT_TYPE,
        # The document now names a caller on a URL inside it. Nothing should keep a copy:
        # not a CDN, not a proxy, not the carrier's own cache. One header, no cost.
        headers={"Cache-Control": "no-store"},
    )


__all__ = [
    "ANSWER_CARRIER",
    "ANSWER_DOCUMENT_CONTENT_TYPE",
    "CARRIER_ANSWER_CONTRACT",
    "CLAIM_CALLER_PARAM",
    "CLAIM_CALLER_STATE_PARAM",
    "CLAIM_CARRIER_PARAM",
    "TELEPHONY_SAMPLE_RATE_HZ",
    "AnswerCallerIdentity",
    "AnswerSourceVerdict",
    "CarrierAnswerContract",
    "EvidenceClass",
    "caller_identity_from_answer_request",
    "plivo_answer_document",
    "plivo_stream_url",
    "router",
    "verify_answer_source",
]
