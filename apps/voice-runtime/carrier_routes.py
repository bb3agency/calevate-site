"""The carrier's HTTP leg: the answer document that points Plivo at the worker (D-610,
`docs/PIPECAT-MIGRATION.md` §6 step 6).

**ONE ROUTE, AND IT IS THE ONLY THING BETWEEN A RINGING NUMBER AND THE MEDIA STREAM.**
A carrier fetches an *answer document* over HTTP before any WebSocket exists; the
document names the socket it should then connect to. This module renders that document
and nothing else: no database, no Redis, no queue, no body read, no vendor SDK.

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

⚠ **THREE THINGS ARE UNKNOWN AND ARE NOT INVENTED HERE.**

1. **Whether Plivo signs its request for the answer document, and how.** Nothing in the
   installed Pipecat tree verifies a Plivo request signature — the only Plivo REST
   endpoint in the whole package is the hangup (`serializers/plivo.py:184`). So this route
   is UNAUTHENTICATED, which is safe *for this document specifically* and for a reason
   rather than by default: it holds no secret and no PII, and it discloses only a stream
   URL built from the ref the requester supplied in its own path. A stranger who guesses a
   ref learns a URL they could have constructed themselves, and the socket at the far end
   refuses anything that is not a published agent. It is NOT a licence for a second route
   here. Closing it is a gate, not a guess: OPERATIONS §2 gate 55.
2. **Which HTTP method the carrier uses.** An answer URL is configured on the number, and
   whether it is fetched with GET or POST is the vendor's to state. Both are registered
   and the body is never read on either, so the route is correct under both readings
   without a claim about which one happens. That is not the same class of guess as
   inventing a field name: the set of methods is two and we serve the same bytes for each.
3. **Whether Pipecat Cloud preserves the URL PATH of the WebSocket it terminates.** That
   is the other half of `bot.resolve_call_identity` and is recorded there, not here.

HARD RULE 1 — THE ROUTE IS THE URL, NEVER THE DIALLED NUMBER
============================================================
D-603. The agent ref is a path segment of the answer URL the operator binds to the
number, so this handler reads NO row to decide whose call it is: it validates the ref it
was given and echoes it into the stream URL. Resolving a number to a tenant before a
tenant is known would be a cross-tenant read of `phone_numbers`, a FORCE-RLS'd table with
no exemption — and Pipecat's Plivo parser leaves `from`/`to` `None` anyway
(`runner/utils.py:257-262`), so the number is not even on the socket.

HARD RULE 3 — WHY THERE IS NO `X-Ack-Ms` AND NO THIRD ACK SERIES
================================================================
`webhook_routes.AckMeter` exists because the receiver's ack can be made slow by something
outside it: an inbox claim, an enqueue, a body that arrives in pieces. This handler has
none of those — it performs no IO at all, reads no body, and its whole cost is a UUID
parse and an ElementTree render of two elements. A third percentile with no dependency
behind it would be instrumentation that can only ever report the same number, and a third
alert code in `alarm_severity.py` and `runbooks/alarm-index.md` that can never fire.
`tests/voice_runtime_carrier_answer_test.py` asserts the absence of IO instead, which is
the property the budget actually rests on.

HARD RULE 6
===========
No phone number ever reaches this process, and none is logged. What is logged is the
tenant and agent ids of a served document, and — on a refusal — a reason and never the
token, which is an attacker-controlled string.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import quote
from xml.etree.ElementTree import Element, tostring

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from calevate_shared.engine import EngineAgentRef, parse_owned_runtime_agent_ref
from fastapi import APIRouter, Response

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


def plivo_stream_url(base_wss_url: str, ref: EngineAgentRef) -> str:
    """The URL to hand the carrier for one agent: the base, then the route as a path segment.

    `quote` with no safe characters, because the ref contains colons and a carrier that
    normalised them would hand us back a token `carrier.route_of` cannot parse. `%3A`
    round-trips through every ASGI server in this tree.

    A PATH SEGMENT rather than a query parameter or a header: Pipecat's own runner calls
    that the recommended form for telephony providers (`runner/run.py:1410-1414`), and a
    provider that drops a query string on a redirect is a failure with no error.
    """
    return f"{base_wss_url.rstrip('/')}/{quote(ref, safe='')}"


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


@router.api_route("/plivo/answer/{ref}", methods=["GET", "POST"], include_in_schema=False)
async def plivo_answer(ref: str) -> Response:
    """Serve the answer document for one agent, or refuse without minting a stream URL.

    **THE REFUSAL COMES BEFORE THE URL, AND THAT ORDERING IS THE SECURITY PROPERTY.** An
    unparseable ref never reaches `plivo_stream_url`, so a stranger probing this path
    cannot get the worker's address out of it, and the carrier is never told to open a
    socket that the worker would then have to refuse.

    `include_in_schema=False`: no browser and no generated client calls this, and the
    OpenAPI snapshot in CI describes the surfaces a client consumes.
    """
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
    document = plivo_answer_document(plivo_stream_url(_stream_base_url(), ref))
    # Ids only (hard rule 6). This is the one line that says a real carrier reached us.
    log.info(
        "carrier_answer_served",
        extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
    )
    return Response(content=document, media_type=ANSWER_DOCUMENT_CONTENT_TYPE)


__all__ = [
    "ANSWER_DOCUMENT_CONTENT_TYPE",
    "TELEPHONY_SAMPLE_RATE_HZ",
    "plivo_answer_document",
    "plivo_stream_url",
    "router",
]
