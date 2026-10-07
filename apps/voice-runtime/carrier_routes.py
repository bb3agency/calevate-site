"""The carrier's HTTP leg: answer documents and transfer documents, per carrier (D-610).

A carrier fetches an *answer document* over HTTP before any WebSocket exists; the
document names the socket it should then connect to. This module renders that document,
the `<Dial>` document a live transfer is redirected to, and the authenticity checks every
carrier route shares (`authenticate`, `admit`). It reads no database, no Redis and no
queue: the whole cost of an answer is a ref parse, a small form read and an ElementTree
render.

`Settings.carrier` picks the carrier the platform DIALS on and binds numbers to. It does
not pick what is SERVED: every carrier in `calevate_shared.carrier.CARRIERS` keeps its
routes, so a number still pointed at the other carrier keeps answering until it is
rebound. Paths are `calevate_shared.carrier.answer_path` / `transfer_path`.

WHY HERE AND NOT IN `apps/voice-worker`. The worker container has no HTTP server, and the
route cannot import the worker: `voice_worker` drags `pipecat-ai`, ONNX turn detection and
three vendor SDKs, which hard rule 3 forbids on this service
(`tests/voice_runtime_import_surface_test.py` measures it). Hard rule 2 sanctions vendor
payload shapes here as the engine's voice-runtime twin.

HARD RULE 1 — THE ROUTE IS THE URL, NEVER THE DIALLED NUMBER (D-603). The agent ref is a
path segment of the URL the operator binds to the number, so no row is read to decide
whose call it is. The calling party this route reads is CARRIED, never routed on: the ref
names the tenant before any parameter is looked at.

HARD RULE 6. No number is ever logged here. Log lines carry tenant and agent ids, the
authenticity method, and the caller's STATE and GROUND — strings written in this module,
never built from wire data. A number leaves this module only SEALED on the stream URL for
the worker to open (`stream_url`), and inside a transfer `<Dial>` sent to the carrier that
asked for it.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import UUID
from xml.etree.ElementTree import Element, tostring

from apps.api.core.alerting import alert, record_webhook_ack_ms
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from calevate_shared.carrier import (
    CALLBACK_SECRET_PARAM,
    CALLBACK_SECRET_SETTINGS,
    RECORDED_SEGMENT,
    VOBIZ_CALLBACK_IPS,
    CarrierName,
    accepted_callback_secrets,
    callback_secret_for,
    events_path,
    is_carrier,
    with_callback_secret,
)
from calevate_shared.carrier_token import open_sealed, usable_secret
from calevate_shared.client_address import client_ip
from calevate_shared.engine import EngineAgentRef, parse_owned_runtime_agent_ref
from calevate_shared.events import CallDirection
from calevate_shared.worker_api import (
    CALL_CLAIM_EXPIRES_PARAM,
    CALL_CLAIM_MAC_PARAM,
    CALL_DIRECTION_PARAM,
    CALL_ID_PARAM,
    CALLER_CLAIM_TTL_S,
    CALLER_SEAL_PARAM,
    CallerIdentityState,
    call_claim_mac,
    seal_caller_claim,
    usable_caller_claim_key,
)
from carrier_auth import (
    VOBIZ_SIGNATURE_V3,
    AuthMethod,
    SignatureScheme,
    check_callback_secret,
    check_signature,
    ip_in,
    parse_networks,
    signed_base_urls,
    split_list,
)
from engine_intake import keyable, scalar_hint
from fastapi import APIRouter, Request, Response
from webhook_routes import AckMeter, read_bounded, stamp_ack

log = get_logger(__name__)

router = APIRouter(prefix="/carrier/v1", tags=["carrier"])

#: The telephony leg's rate. Declared rather than imported because the other copy
#: (`voice_worker/pipeline.TELEPHONY_SAMPLE_RATE_HZ`) is in a container this one may not
#: import; both are pinned to vendor sources by test rather than to each other.
TELEPHONY_SAMPLE_RATE_HZ: Final[int] = 8000

#: Pipecat's runner answers its own template with this type (`runner/run.py:1456`), and
#: Vobiz requires `application/xml` or `text/xml` (`vobiz-findings/mirror/pages/xml/
#: request.md:11-18`).
ANSWER_DOCUMENT_CONTENT_TYPE: Final = "application/xml"

#: Evidence classes, hard rule 11's vocabulary, spelled as a type so a row cannot omit one.
EvidenceClass = Literal["VERIFIED-VENDOR-DOCS", "VENDOR-PUBLISHED", "REPORTED", "UNKNOWN"]

#: The query parameters the control plane puts on the stream URL, read back by
#: `voice_worker.carrier.claim_from_stream_url`. Declared in both deployables because
#: neither may import the other; `tests/carrier_answer_identity_test.py` asserts they agree.
#: The sealed number rides `worker_api.CALLER_SEAL_PARAM`, which both import.
CLAIM_CARRIER_PARAM: Final = "carrier"
CLAIM_CALLER_STATE_PARAM: Final = "caller_state"

#: Every parameter a claim may set. A base URL carrying one of these names has it dropped,
#: so a value in the configured base can never stand in for a claim the worker believes.
_STREAM_CLAIM_PARAMS: Final = frozenset(
    {
        CLAIM_CARRIER_PARAM,
        CLAIM_CALLER_STATE_PARAM,
        CALLER_SEAL_PARAM,
        CALL_ID_PARAM,
        CALL_DIRECTION_PARAM,
        CALL_CLAIM_EXPIRES_PARAM,
        CALL_CLAIM_MAC_PARAM,
    }
)

#: The one problem every refusal on these routes answers with. A distinct status, code
#: or sentence per cause would tell a prober which half of its guess was right (the ref,
#: the address, the signature); the cause is in the log, where only an operator reads.
_REFUSAL_CODE: Final = "carrier_ref_unknown"

_MIRROR: Final = "vobiz-findings/mirror/pages/"


def carrier_label(carrier: str) -> str:
    """`carrier` if this build knows it, else `"unknown"` — the URL segment is a stranger's
    string on every refusal, and it becomes a metric label and an alert field."""
    return carrier if is_carrier(carrier) else "unknown"


#: The carrier HTTP surface's limits. Bodies are small form posts (an answer request, a
#: status callback), so the cap is far below the engine receiver's megabyte; the two
#: deadlines are that receiver's numbers and reasons (`webhook_routes`). Vobiz wants a
#: callback acked within 3 s and retries a non-200 up to three times
#: (`concepts/callbacks.md:125-126`); the ack alert stays hard rule 3's 500 ms.
CARRIER_ACK: Final = AckMeter(
    record=record_webhook_ack_ms,
    slow_code="webhook_ack_slow",
    body_timeout_code="webhook_body_timeout",
    max_body_bytes=64 * 1024,
    body_deadline_s=2.0,
    durable_deadline_s=2.0,
    label=carrier_label,
)


@dataclass(frozen=True, slots=True)
class CarrierAnswerContract:
    """What we know about ONE carrier's HTTP requests to us, with the evidence for each cell.

    Every cell carries its own evidence class so a not-finding cannot be read later as a
    vendor fact (D-631): an empty `calling_party` means "nobody has read the vendor's
    page", never "the carrier sends nothing".
    """

    carrier: str

    #: Parameter names, in preference order, carrying the CALLING party on the answer
    #: request. EMPTY means UNKNOWN, and the request body is then not read at all.
    calling_party: tuple[str, ...]
    calling_party_evidence_class: EvidenceClass
    calling_party_evidence: str

    #: Published source addresses or CIDRs. EMPTY means none is declared, and
    #: `verify_answer_source` reports method `"none"` rather than refusing every call.
    source_ip_allowlist: tuple[str, ...]
    source_ip_evidence_class: EvidenceClass
    source_ip_evidence: str

    #: How the carrier signs its requests. `None` means UNKNOWN, and nothing is verified:
    #: a guessed HMAC would reject every real call for a reason nobody could debug.
    signature_scheme: SignatureScheme | None
    signature_evidence_class: EvidenceClass
    signature_evidence: str

    #: Does the carrier echo parameters we attach to `<Stream>` back in the WebSocket
    #: `start` event? `None` is UNKNOWN. It is the cell that would let the caller number
    #: leave the stream URL (see `stream_url`).
    echoes_stream_parameters: bool | None
    echoes_stream_parameters_evidence: str

    #: The parameter naming the CALLED party. On an outbound dial the called party is the
    #: person we rang, so that is whose number the worker needs; the calling party is ours.
    called_party: tuple[str, ...] = ()

    #: `Settings` fields read per request: a runtime override of the allowlist (comma
    #: separated), the signing key, and whether a missing signature is a refusal. Named
    #: here so the seam stays a table rather than a branch per carrier.
    source_ip_override_setting: str | None = None
    signing_key_setting: str | None = None
    signature_required_setting: str | None = None

    #: Whether a live transfer is served as this carrier's `<Dial>` document.
    dial_transfer: bool = False
    dial_evidence: str = ""

    #: Whether status/hangup callbacks are accepted on the events route. Off for a carrier
    #: whose callback grammar is unread: its worker job could only refuse, so accepting
    #: would turn an unauthenticated POST into an inbox row, a queued job and an alarm.
    status_callbacks: bool = False
    status_callbacks_evidence: str = ""

    #: Whether the answer document can ask the carrier to record the whole call alongside
    #: a bidirectional stream. Off for a carrier whose recording grammar is unread.
    session_recording: bool = False
    session_recording_evidence: str = ""

    @property
    def signature_header(self) -> str | None:
        return self.signature_scheme.header if self.signature_scheme is not None else None


#: Plivo's cells are UNKNOWN because `www.plivo.com` is egress-blocked from the build
#: container (`curl: (56) CONNECT tunnel failed, response 403`, HTTP 000, 19 Sep 2026).
#: Vobiz's cells are read from the hash-pinned mirror (`docs/evidence/vobiz-api-contract.md`).
CARRIER_ANSWER_CONTRACT: Final[Mapping[str, CarrierAnswerContract]] = {
    "plivo": CarrierAnswerContract(
        carrier="plivo",
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
        signature_scheme=None,
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
            "UNKNOWN — docs/evidence/carrier-caller-identity.md §5(c). Twilio's answer "
            "document supplies parameters that arrive as `start.customParameters` "
            "(pipecat/runner/utils.py:232,240-241), so the shape exists for another carrier."
        ),
    ),
    "vobiz": CarrierAnswerContract(
        carrier="vobiz",
        calling_party=("From",),
        calling_party_evidence_class="VERIFIED-VENDOR-DOCS",
        calling_party_evidence=(
            f"{_MIRROR}xml/request.md:30 — `From`: the caller's caller ID inbound, our "
            "`from` outbound."
        ),
        called_party=("To",),
        source_ip_allowlist=VOBIZ_CALLBACK_IPS,
        source_ip_evidence_class="VERIFIED-VENDOR-DOCS",
        source_ip_evidence=(
            f"{_MIRROR}concepts/ip-whitelisting.md:93-107 (HTTP callbacks, India); "
            "'subject to change' (:27-29), so VOBIZ_CALLBACK_IPS overrides it at runtime."
        ),
        source_ip_override_setting="vobiz_callback_ips",
        signature_scheme=VOBIZ_SIGNATURE_V3,
        signature_evidence_class="VERIFIED-VENDOR-DOCS",
        signature_evidence=(
            f"{_MIRROR}concepts/validating-callbacks.md:15-52; sent only when the callback "
            "URL has auth credentials configured (:56-64), which is why a missing signature "
            "is refused only under VOBIZ_SIGNATURE_REQUIRED."
        ),
        signing_key_setting="vobiz_auth_token",
        signature_required_setting="vobiz_signature_required",
        echoes_stream_parameters=None,
        echoes_stream_parameters_evidence=(
            f"UNKNOWN — `extraHeaders` exists ({_MIRROR}xml/stream.md:48) but only the empty "
            "`extra_headers` form is ever shown (xml/stream/stream-events.md:95,175)."
        ),
        dial_transfer=True,
        dial_evidence=f"{_MIRROR}xml/dial.md:40-60",
        status_callbacks=True,
        status_callbacks_evidence=f"{_MIRROR}concepts/callbacks.md:70-105",
        session_recording=True,
        session_recording_evidence=(
            f"{_MIRROR}xml/record/stream-with-record.md:9-25,54-78 (a self-closing "
            '`<Record recordSession="true" redirect="false"/>` before a bidirectional '
            "`<Stream>`; `RecordStop` to `callbackUrl`); attributes xml/record.md:13-29."
        ),
    ),
}

#: `<Record>` limits, in seconds. Both are set to Vobiz's own default call `time_limit`
#: (`call/make-call.md:71`), the longest call the carrier carries unasked: `maxLength`
#: defaults to 60 s and `timeout` ends a recording after 60 s of silence
#: (`xml/record.md:19-20`), and either default would cut a conversation's recording short
#: while the call went on.
RECORDING_MAX_LENGTH_S: Final = 14_400
RECORDING_SILENCE_TIMEOUT_S: Final = 14_400

#: MP3 is the vendor's default and its recommendation (`xml/record.md:17`,
#: `call/record-calls.md:66`); the container is sniffed from the bytes when it is copied,
#: because it may not match (`recording.md:24-37`).
RECORDING_FILE_FORMAT: Final = "mp3"

#: The one key that ends the carrier's recording (founder, 3 Oct 2026: a keypress must never
#: stop it). `finishOnKey` admits only digits, `#` and `*` and defaults to all twelve
#: (`xml/record.md:22`); no page documents a value that disables it, and an undocumented one
#: (an empty string, "none") risks the carrier refusing the whole answer document, which
#: would fail every recorded call rather than shorten one recording. So the set is narrowed
#: to one key, as the vendor itself advises (`:147`), and the key is `*` rather than `#`:
#: `#` is the conventional end-of-entry key, the one the vendor's own examples have callers
#: press after typing digits (`xml/record.md:82,85`, `blogs/what-is-multi-level-ivr.md:170`).
#: Our agents ask for no keypress at all. A caller who presses `*` still ends the recording;
#: `carrier_recording_ended_early` alarms with `FinishedOnKey`, and gate V-11(b) checks it.
RECORDING_FINISH_ON_KEY: Final = "*"


@dataclass(frozen=True, slots=True)
class AnswerCallerIdentity:
    """Who the carrier said the other party is, on ITS request for the answer document.

    The state vocabulary is `calevate_shared.worker_api.CallerIdentityState`, the same
    four words the worker and `apps/api/worker/tools.py` speak. `e164` is PII and is
    carried, never logged; `ground` is written in this module and cannot carry a number.
    """

    state: CallerIdentityState
    ground: str
    e164: str | None = None


#: What a calling-party value must look like to be a number at all: digits, optionally led by
#: `+`, E.164's 7-15 length, not all zeros. NOT `_E164` below, which demands the `+`: Vobiz
#: documents `From` both with it and without it (`xml/request.md:30` says "including the
#: country code"; `xml/stream.md:98` shows `From=918071387423`), and a form-encoded `+` that
#: was not percent-encoded arrives as a space, which the caller strips. A carrier's word for a
#: withheld number ("anonymous", "private", "restricted") fails this and is read as withheld.
_CALLER_NUMBER: Final = re.compile(r"^\+?(?!0+$)\d{7,15}$")


def caller_identity_from_answer_request(
    carrier: str, params: Mapping[str, str], *, direction: CallDirection = "inbound"
) -> AnswerCallerIdentity:
    """The remote party on the carrier's own HTTP request, as an explainable state.

    Inbound, the remote party is the CALLING party; outbound, it is the CALLED party —
    the calling party of a dial we placed is our own number, and keying an opt-out on it
    would suppress ourselves.

    No number is normalised here: `calevate_shared.extraction.normalize_phone` is the one
    canonicaliser and it runs in the worker, on the value forwarded verbatim.
    """
    contract = CARRIER_ANSWER_CONTRACT.get(carrier)
    if contract is None:
        return AnswerCallerIdentity(
            state="unparsed_by_client",
            ground=(
                f"carrier {carrier!r} has no row in CARRIER_ANSWER_CONTRACT, so nothing "
                "here knows which parameter of its request carries the other party"
            ),
        )
    names = contract.called_party if direction == "outbound" else contract.calling_party
    if not names:
        return AnswerCallerIdentity(
            state="unparsed_by_client",
            ground=(
                f"no {direction} remote-party parameter is declared for {carrier!r}: "
                f"{contract.calling_party_evidence}"
            ),
        )
    for name in names:
        value = params.get(name, "").strip()
        if not value:
            continue
        if not _CALLER_NUMBER.match(value):
            # The value is not quoted in the ground: it is wire data, and it may be a number
            # in a shape we refuse (hard rule 6).
            return AnswerCallerIdentity(
                state="withheld_by_carrier",
                ground=f"the {carrier} answer request carried {name} with no number in it",
            )
        return AnswerCallerIdentity(
            state="known",
            ground=f"the {carrier} answer request carried {name}",
            e164=value,
        )
    return AnswerCallerIdentity(
        state="withheld_by_carrier",
        ground=(
            f"the {carrier} answer request declares {'/'.join(names)} "
            f"({contract.calling_party_evidence_class}) and carried no value in it"
        ),
    )


@dataclass(frozen=True, slots=True)
class AnswerSourceVerdict:
    """Whether a request's source address is the carrier's, and by which method."""

    ok: bool
    method: Literal["source_ip", "none"]
    reason: str


def _allowlist(contract: CarrierAnswerContract) -> tuple[str, ...] | None:
    """The allowlist in force: the runtime override when one is set, else the table's.

    `None` when an override is set and holds no valid entry — refused by the caller, since
    falling back to "no allowlist" would turn a typo in an operator's paste into an open
    door.
    """
    override = (
        split_list(getattr(get_settings(), contract.source_ip_override_setting))
        if contract.source_ip_override_setting is not None
        else ()
    )
    if not override:
        return contract.source_ip_allowlist
    networks, _invalid = parse_networks(override)
    return override if networks else None


def verify_answer_source(carrier: str, source_ip: str | None) -> AnswerSourceVerdict:
    """Is this request from the carrier's published addresses? Answered from the table.

    Data-driven: the day a row holds an address, a request from anywhere else is refused,
    with no switch to remember. An EMPTY allowlist is method `"none"` rather than a
    refusal — enforced, it would refuse every call with no remedy an operator could apply,
    because the remedy is a vendor fact. What a stranger gets from a served document is a
    stream URL they could have built from the ref they already hold; it carries no secret,
    and the worker refuses a socket whose token names no agent.
    """
    contract = CARRIER_ANSWER_CONTRACT.get(carrier)
    if contract is None:
        return AnswerSourceVerdict(
            ok=True,
            method="none",
            reason=f"carrier {carrier!r} has no row in CARRIER_ANSWER_CONTRACT",
        )
    allowlist = _allowlist(contract)
    if allowlist is None:
        return AnswerSourceVerdict(
            ok=False, method="source_ip", reason="callback ip override holds no valid address"
        )
    if not allowlist:
        return AnswerSourceVerdict(
            ok=True, method="none", reason="no source-ip allowlist is declared for this carrier"
        )
    if source_ip is None:
        # The EDGE broke, not the vendor — a different runbook entry, so a different reason.
        return AnswerSourceVerdict(ok=False, method="source_ip", reason="client ip not established")
    networks, _invalid = parse_networks(allowlist)
    if ip_in(source_ip, networks):
        return AnswerSourceVerdict(ok=True, method="source_ip", reason="source ip allowlisted")
    return AnswerSourceVerdict(ok=False, method="source_ip", reason="source ip not allowlisted")


@dataclass(frozen=True, slots=True)
class CarrierAuthVerdict:
    """The combined answer of the source check and the signature check."""

    ok: bool
    method: AuthMethod
    reason: str


def _callback_secret_verdict(carrier: str, request: Request) -> CarrierAuthVerdict | None:
    """The shared-secret check (D-673): a refusal, an admission by secret, or `None` when
    this carrier carries no secret.

    A carrier with a secret setting and no usable value is refused outside `local`: the
    source addresses are shared by every customer of the carrier, so admitting on them alone
    is the exposure this check closes, and a missing secret is a misconfiguration the deploy
    gate and `/healthz/ready` both name. `local` admits, so a developer's carrier double
    needs no secret.
    """
    if carrier not in CALLBACK_SECRET_SETTINGS:
        return None
    settings = get_settings()
    outcome = check_callback_secret(
        request.query_params.getlist(CALLBACK_SECRET_PARAM),
        accepted_callback_secrets(carrier, settings),
    )
    if outcome == "matched":
        return CarrierAuthVerdict(
            ok=True, method="callback_secret", reason="callback secret matched"
        )
    if outcome == "unconfigured":
        if settings.app_env == "local":
            return None
        return CarrierAuthVerdict(
            ok=False, method="callback_secret", reason="callback secret not configured"
        )
    reason = "callback secret missing" if outcome == "absent" else "callback secret invalid"
    return CarrierAuthVerdict(ok=False, method="callback_secret", reason=reason)


def authenticate(carrier: str, request: Request) -> CarrierAuthVerdict:
    """Source address, then our callback secret, then signature. All that apply must pass;
    the strongest is reported.

    The secret does not replace the address check or the signature: a request from outside
    the carrier's published range is refused whatever it carries, and a present signature
    that fails is refused whatever secret came with it.

    SIGNATURE POLICY, for a carrier whose row declares a scheme:

    * signing required and no key configured — refused: a misconfiguration, and the only
      safe reading of "required" is that nothing is admitted until it is fixed;
    * a signature presented and a key configured — it must verify, or the request is
      refused;
    * a signature presented and no key — admitted on the source check alone (it cannot
      be checked, and refusing would make the vendor's default an outage);
    * no signature — refused only when required. The vendor sends signatures only once
      the URL has auth credentials configured (`concepts/validating-callbacks.md:56-64`),
      so requiring them before that console step refuses every call.

    The signed URL is rebuilt from `Settings.webhook_base_url` plus the request path
    (`carrier_auth.signed_base_urls`), never from `request.url`.
    """
    settings = get_settings()
    source = verify_answer_source(
        carrier,
        client_ip(
            request.client.host if request.client else None,
            request.headers,
            app_env=settings.app_env,
        ),
    )
    if not source.ok:
        return CarrierAuthVerdict(ok=False, method=source.method, reason=source.reason)
    secret = _callback_secret_verdict(carrier, request)
    if secret is not None and not secret.ok:
        return secret
    admitted = secret or CarrierAuthVerdict(ok=True, method=source.method, reason=source.reason)
    contract = CARRIER_ANSWER_CONTRACT.get(carrier)
    if contract is None or contract.signature_scheme is None:
        return admitted

    key = (
        getattr(settings, contract.signing_key_setting) or None
        if contract.signing_key_setting is not None
        else None
    )
    required = bool(
        contract.signature_required_setting is not None
        and getattr(settings, contract.signature_required_setting)
    )
    if required and not key:
        return CarrierAuthVerdict(
            ok=False, method="signature", reason="signature required but no signing key is set"
        )
    outcome = check_signature(
        request.headers,
        contract.signature_scheme,
        key=key,
        base_urls=signed_base_urls(
            settings.webhook_base_url,
            raw_path=request.scope.get("raw_path"),
            path=request.scope.get("path", ""),
        ),
    )
    if outcome == "verified":
        return CarrierAuthVerdict(ok=True, method="signature", reason="signature verified")
    if outcome == "invalid":
        return CarrierAuthVerdict(ok=False, method="signature", reason="signature invalid")
    if outcome == "absent" and required:
        return CarrierAuthVerdict(ok=False, method="signature", reason="signature required")
    reason = "unsigned" if outcome == "absent" else "signature present but no key to check it"
    return CarrierAuthVerdict(ok=True, method=admitted.method, reason=reason)


def refuse(reason: str, *, carrier: str, surface: str) -> ProblemError:
    """The one refusal every carrier route answers with. Never echoes the ref or token."""
    log.warning(
        "carrier_request_refused",
        extra={"carrier": carrier_label(carrier), "surface": surface, "reason": reason},
    )
    return ProblemError(
        kind="not_found",
        code=_REFUSAL_CODE,
        title="That is not an agent of this platform",
        detail="The URL does not carry an owned-runtime agent ref.",
        remediation=(
            "Point the number at the answer URL the agent's screen shows, from an address "
            "in the carrier's published range (docs/PIPECAT-MIGRATION.md §6 step 6)."
        ),
    )


def admit(
    carrier: str, request: Request, *, surface: str
) -> tuple[CarrierAnswerContract, CarrierAuthVerdict]:
    """Every carrier route's first step: a known carrier, then `authenticate`.

    Runs before the ref is parsed and before any body byte is read, so an inauthentic
    caller is turned away before it can make us allocate or mint anything.
    """
    contract = CARRIER_ANSWER_CONTRACT.get(carrier) if is_carrier(carrier) else None
    if contract is None:
        raise refuse("carrier_unknown", carrier=carrier, surface=surface)
    verdict = authenticate(carrier, request)
    if not verdict.ok:
        # Alerted, not only logged: a vendor renumber or a rotated token refuses EVERY
        # call, and this is the line that tells an operator which. The source address is
        # a machine's, not a caller's (hard rule 6).
        alert(
            "ROUTE_HANDLER",
            "carrier_source_rejected",
            detail=verdict.reason,
            carrier=carrier,
            surface=surface,
            method=verdict.method,
            source_ip=client_ip(
                request.client.host if request.client else None,
                request.headers,
                app_env=get_settings().app_env,
            )
            or "unknown",
        )
        raise refuse(verdict.reason, carrier=carrier, surface=surface)
    return contract, verdict


def parse_ref(ref: str, *, carrier: str, surface: str) -> tuple[UUID, UUID]:
    """The (tenant, agent) a path ref names, or the refusal."""
    parsed = parse_owned_runtime_agent_ref(ref)
    if parsed is None:
        raise refuse("ref_names_no_agent", carrier=carrier, surface=surface)
    return parsed


def parse_call_id(call_id: str, *, carrier: str, surface: str) -> str:
    """Our call id from an outbound path, canonicalised, or the refusal."""
    try:
        return str(UUID(call_id))
    except ValueError:
        raise refuse("call_id_malformed", carrier=carrier, surface=surface) from None


#: Form-encoded is what carriers send (Vobiz: `xml/request.md:11`). JSON is accepted too
#: because Vobiz's callbacks page prints JSON under a form-encoded label
#: (`concepts/callbacks.md:37-55`). Multipart is not parsed: it needs `python-multipart`
#: on a 500 ms path and no carrier has been read as using it.
_FORM_CONTENT_TYPE: Final = "application/x-www-form-urlencoded"
_JSON_CONTENT_TYPE: Final = "application/json"


def carrier_params(
    query: Mapping[str, str], content_type: str, raw: bytes
) -> tuple[dict[str, str], bool]:
    """The carrier's parameters — query first, body wins on a clash — and whether the body
    was readable. A GET carries everything in the query (`xml/request.md:11`)."""
    params: dict[str, str] = dict(query)
    kind = content_type.split(";", 1)[0].strip().lower()
    if not raw:
        return params, True
    if kind == _FORM_CONTENT_TYPE:
        params.update(parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True))
        return params, True
    if kind == _JSON_CONTENT_TYPE:
        try:
            decoded: Any = json.loads(raw)
        except (ValueError, RecursionError):
            return params, False
        if not isinstance(decoded, dict):
            return params, False
        for name, value in decoded.items():
            text = scalar_hint(value)
            if text is not None:
                params[str(name)] = text
        return params, True
    return params, False


async def read_params(request: Request, *, carrier: str) -> tuple[dict[str, str], bool]:
    """Read and parse a carrier request's body, bounded in size and in time."""
    raw = await read_bounded(request, engine=carrier, meter=CARRIER_ACK)
    if raw is None:
        alert("ROUTE_HANDLER", "webhook_payload_too_large", engine=carrier)
        raise ProblemError(
            kind="validation",
            code="payload_too_large",
            title="Too much data was sent",
            detail="This call event carried more data than this address accepts.",
            status=413,
        )
    params, readable = carrier_params(
        request.query_params, request.headers.get("content-type", ""), raw
    )
    # Ours, already checked by `authenticate`: kept out of the job payload and the replay
    # fingerprint, where it would be stored and would split one delivery across a rotation.
    params.pop(CALLBACK_SECRET_PARAM, None)
    return params, readable


def stream_url(
    base_wss_url: str,
    ref: EngineAgentRef,
    *,
    carrier: str | None = None,
    caller: AnswerCallerIdentity | None = None,
    claim_secret: str | None = None,
    now: float | None = None,
    call_id: str | None = None,
    direction: CallDirection | None = None,
) -> str:
    """The URL to hand the carrier for one agent: the base, then the ref as a path segment.

    The ref is the LAST path segment, quoted with no safe characters (its colons become
    `%3A`), because `apps/voice-worker/bot.py::_route_token` reads `path.rsplit("/", 1)`.
    Everything else rides the query.

    THE NUMBER TRAVELS ONLY SEALED (`worker_api.seal_caller_claim`, AES-GCM), so neither an
    edge log nor anything else between the carrier and the worker can read it (hard rule 6),
    and the worker believes it only when it opens for this ref. Our call id and direction
    travel under an HMAC (`call_claim_mac`); they are not personal data, only claims the
    worker must be able to authenticate. With no usable secret both are left off: the worker
    would not believe them.

    The base may carry a query of its own: Pipecat Cloud's telephony endpoint is
    `wss://<region>.api.pipecat.daily.co/ws/plivo?serviceHost=<agent>.<org>`
    (docs.pipecat.ai/pipecat-cloud/guides/telephony/plivo-websocket and /guides/regions, read
    5 Oct 2026). So the ref goes on the base's PATH and the base's own parameters are kept
    ahead of ours; concatenating onto the whole string would bury the ref inside
    `serviceHost` and leave a second `?` in the URL.
    """
    base = urlsplit(base_wss_url.strip())
    url_path = f"{base.path.rstrip('/')}/{quote(ref, safe='')}"
    base_params = [
        (name, value)
        for name, value in parse_qsl(base.query, keep_blank_values=True)
        if name not in _STREAM_CLAIM_PARAMS
    ]
    claim: dict[str, str] = {}
    if carrier is not None:
        claim[CLAIM_CARRIER_PARAM] = carrier
    instant = time.time() if now is None else now
    expires_at = int(instant) + CALLER_CLAIM_TTL_S
    secret = usable_secret(claim_secret)
    claim_key = usable_caller_claim_key(claim_secret)
    if caller is not None:
        claim[CLAIM_CALLER_STATE_PARAM] = caller.state
        if caller.e164 is not None and secret is not None:
            claim[CALLER_SEAL_PARAM] = seal_caller_claim(
                secret, ref=ref, e164=caller.e164, now=instant
            )
    if call_id is not None and direction is not None and claim_key is not None:
        claim[CALL_ID_PARAM] = call_id
        claim[CALL_DIRECTION_PARAM] = direction
        claim[CALL_CLAIM_EXPIRES_PARAM] = str(expires_at)
        claim[CALL_CLAIM_MAC_PARAM] = call_claim_mac(
            claim_key, ref=ref, call_id=call_id, direction=direction, expires_at=expires_at
        )
    query = urlencode([*base_params, *claim.items()])
    return urlunsplit((base.scheme, base.netloc, url_path, query, ""))


@dataclass(frozen=True, slots=True)
class SessionRecording:
    """Record the whole call. `callback_url` is where `RecordStop` goes; None when this
    deployment has no callback base, in which case the carrier still records and
    `carrier_recordings.reconcile_carrier_recordings` finds the recording by call id."""

    callback_url: str | None


def record_element(recording: SessionRecording) -> Element:
    """`<Record/>` for a whole-session recording beside a bidirectional stream.

    The shape is the vendor's (`xml/record/stream-with-record.md:11,19-21`): self-closing,
    BEFORE the `<Stream>`, `recordSession="true"` so it runs while the stream holds the
    call, `redirect="false"` so the recording event cannot take call control from the
    stream. No `action`: a `recordSession` flow may use `callbackUrl` alone
    (`xml/record.md:15,145`), and the initial event carries nothing we keep.

    No beep (founder, 3 Oct 2026): `playBeep="false"` overrides the vendor's default of
    `true` (`xml/record.md:21`), so the agent's spoken recording notice is the only signal a
    caller gets. `finishOnKey` is `RECORDING_FINISH_ON_KEY`, whose comment says why it is one
    key rather than none.
    """
    attributes = {
        "recordSession": "true",
        "redirect": "false",
        "fileFormat": RECORDING_FILE_FORMAT,
        "maxLength": str(RECORDING_MAX_LENGTH_S),
        "timeout": str(RECORDING_SILENCE_TIMEOUT_S),
        "playBeep": "false",
        "finishOnKey": RECORDING_FINISH_ON_KEY,
    }
    if recording.callback_url is not None:
        attributes["callbackUrl"] = recording.callback_url
        attributes["callbackMethod"] = "POST"
    return Element("Record", attributes)


def answer_document(stream_url: str, *, recording: SessionRecording | None = None) -> str:
    """The XML a carrier is served when a call is answered.

        <Response><Stream bidirectional="true" keepCallAlive="true"
                          contentType="audio/x-mulaw;rate=8000">wss://.../ws</Stream></Response>

    Pipecat's own template (`runner/run.py:1435-1438`), and valid Vobiz grammar: all three
    attributes are in `xml/stream.md:42-50`, and Vobiz's Pipecat guide serves exactly this
    shape (`integrations/pipecat.md:572-590`). Built with a serializer, never an f-string:
    the URL carries `&` and `%`. With `recording`, `record_element` goes first.
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
    if recording is not None:
        response.append(record_element(recording))
    response.append(stream)
    return _xml(response)


def _xml(root: Element) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode")


def _xml_response(document: str) -> Response:
    # Per-call routing that nothing should keep a copy of: not a CDN, not a proxy, not
    # the carrier's own cache.
    return Response(
        content=document,
        media_type=ANSWER_DOCUMENT_CONTENT_TYPE,
        headers={"Cache-Control": "no-store"},
    )


def _stream_base_url() -> str:
    """Where the worker's WebSocket lives, or a refusal an operator can act on.

    Not a default: a guessed host would serve a document pointing at nothing — a call that
    connects, rings and dies in silence. A refusal is retried by the carrier and read by
    an operator.
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


def _unsigned_outbound_refusal(carrier: str, *, call_id: str, tenant_id: UUID) -> ProblemError:
    """The refusal for a call WE dialled when there is no usable `CARRIER_CLAIM_SECRET`.

    Refused rather than served unsigned. Served, the worker could not verify our call id,
    would run the call as inbound under an id of its own, and the dialled `calls` row would
    never receive its transcript, settlement or lead while the person we rang talked to an
    agent. A refused answer ends the call before anybody speaks. The error handler raises the
    alarm under this code (every 5xx does); this line adds the ids it cannot carry.
    """
    log.error(
        "carrier_call_claim_key_missing",
        extra={"carrier": carrier_label(carrier), "call_id": call_id, "tenant_id": str(tenant_id)},
    )
    return ProblemError(
        kind="dependency",
        code="carrier_call_claim_key_missing",
        title="This deployment cannot run a dialled call yet",
        detail="CARRIER_CLAIM_SECRET is not usable, so the call could not be handed to the worker.",
        remediation=(
            "Set the same CARRIER_CLAIM_SECRET (at least 32 bytes) on the VPS and in the "
            "Pipecat worker's secret set (docs/DEPLOYMENT.md §12.2)."
        ),
    )


def session_recording_for(
    contract: CarrierAnswerContract, ref: str, *, call_id: str | None, recorded: bool
) -> SessionRecording | None:
    """Whether to record this call, and where the carrier reports the finished recording.

    All three must hold: the agent was PUBLISHED announcing a recording (`recorded`, a
    signed path segment the control plane wrote from `AgentConfig.call_is_recorded`), the
    carrier's recording grammar is read (`session_recording`), and the operator has not
    switched recording off (`carrier_recording_enabled`, read per request). The first is
    what keeps hard rule 5 true in the dangerous direction: a call is never recorded for
    an agent that told the caller it is not.

    The callback is this agent's events route — the hangup's own URL, so `RecordStop`
    rides the same source and signature checks and the same inbox (`carrier_events`).
    """
    settings = get_settings()
    if not (recorded and contract.session_recording and settings.carrier_recording_enabled):
        return None
    base = (settings.webhook_base_url or "").strip().rstrip("/")
    if not base:
        # Recorded all the same: the agent has already told the caller it is, and the
        # sweep finds an un-reported recording by the carrier's call id.
        alert(
            "ROUTE_HANDLER",
            "carrier_recording_callback_unset",
            detail="WEBHOOK_BASE_URL is unset, so the carrier cannot report the recording",
            carrier=contract.carrier,
        )
        return SessionRecording(callback_url=None)
    path = events_path(cast(CarrierName, contract.carrier), ref, call_id=call_id)
    return SessionRecording(
        callback_url=with_callback_secret(
            base + path, callback_secret_for(contract.carrier, settings)
        )
    )


async def _answer(
    carrier: str, ref: str, call_id: str | None, request: Request, *, recorded: bool = False
) -> Response:
    """Authenticity, then the ref, then the identity read, then the URL.

    The order is the security property: an inauthentic or unknown caller is turned away
    before anything is read from its request and before the worker's address is minted.
    The body is read only for a carrier whose row declares a parameter name to look in.
    """
    started = time.perf_counter()
    surface = "answer"
    contract, verdict = admit(carrier, request, surface=surface)
    tenant_id, agent_id = parse_ref(ref, carrier=carrier, surface=surface)
    ours = parse_call_id(call_id, carrier=carrier, surface=surface) if call_id else None
    direction: CallDirection = "outbound" if ours is not None else "inbound"
    params: Mapping[str, str] = {}
    if contract.calling_party or contract.called_party:
        params, _readable = await read_params(request, carrier=carrier)
    caller = caller_identity_from_answer_request(carrier, params, direction=direction)
    claim_secret = get_settings().carrier_claim_secret
    if ours is not None and usable_caller_claim_key(claim_secret) is None:
        raise _unsigned_outbound_refusal(carrier, call_id=ours, tenant_id=tenant_id)
    recording = session_recording_for(contract, ref, call_id=ours, recorded=recorded)
    document = answer_document(
        stream_url(
            _stream_base_url(),
            ref,
            carrier=carrier,
            caller=caller,
            claim_secret=claim_secret,
            call_id=ours,
            direction="outbound" if ours is not None else None,
        ),
        recording=recording,
    )
    response = _xml_response(document)
    ack_ms = stamp_ack(response, started, carrier, meter=CARRIER_ACK)
    log.info(
        "carrier_answer_served",
        extra={
            "carrier": carrier,
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "call_id": ours,
            # The carrier's id for this call: the key its hangup, its CDR and the worker's
            # `start.callId` all carry, so one search joins the three legs' logs.
            "carrier_call_id": keyable(params.get("CallUUID", "")),
            "direction": direction,
            "ack_ms": ack_ms,
            "auth_method": verdict.method,
            # The signature outcome under the secret ("unsigned", "signature verified", ...),
            # which gate 55 records for the answer request.
            "auth_reason": verdict.reason,
            "caller_identity": caller.state,
            "caller_identity_ground": caller.ground,
            "recorded": recording is not None,
        },
    )
    return response


@router.api_route("/{carrier}/answer/{ref}", methods=["GET", "POST"], include_in_schema=False)
async def carrier_answer(carrier: str, ref: str, request: Request) -> Response:
    """The answer document for an inbound call to one agent.

    `include_in_schema=False`: no browser and no generated client calls this, and
    `tests/kb_tiers_test.py` pins the schema's route inventory.
    """
    return await _answer(carrier, ref, None, request)


@router.api_route(
    "/{carrier}/answer/{ref}/outbound/{call_id}", methods=["GET", "POST"], include_in_schema=False
)
async def carrier_answer_outbound(
    carrier: str, ref: str, call_id: str, request: Request
) -> Response:
    """The answer document for a call WE dialled: our call id is a path segment, because
    Vobiz signs the URL with its query stripped (`concepts/validating-callbacks.md:35-52`)."""
    return await _answer(carrier, ref, call_id, request)


@router.api_route(
    f"/{{carrier}}/answer/{{ref}}/{RECORDED_SEGMENT}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def carrier_answer_recorded(carrier: str, ref: str, request: Request) -> Response:
    """An inbound call to an agent published announcing a recording (`answer_path(recorded=
    True)`); recorded when `session_recording_for` agrees."""
    return await _answer(carrier, ref, None, request, recorded=True)


@router.api_route(
    f"/{{carrier}}/answer/{{ref}}/outbound/{{call_id}}/{RECORDED_SEGMENT}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def carrier_answer_outbound_recorded(
    carrier: str, ref: str, call_id: str, request: Request
) -> Response:
    """A call we dialled for an agent published announcing a recording."""
    return await _answer(carrier, ref, call_id, request, recorded=True)


#: The `<Hangup>` reason the fallback document gives. Vobiz invokes the fallback only when
#: the answer URL is unreachable, times out or returns no valid XML, and "with no fallback
#: set, the call drops" (`applications/create-application.md:34`, `call/make-call.md:44`).
#:
#: `busy` rather than a spoken apology: a `<Hangup>` placed first rejects an inbound call
#: WITHOUT answering or billing it, and `busy` gives the caller a busy tone
#: (`xml/hangup.md:13-21,37-46`), the one "try again later" signal that needs no language —
#: `<Speak>` offers only European and American voices (`xml/speak.md:62-80`), none a caller
#: of a Telugu-first product would be addressed in. On a call that is already answered (an
#: outbound dial) the vendor ignores the reason and ends it as a normal hangup (`:20-21`).
FALLBACK_HANGUP_REASON: Final = "busy"


def fallback_document() -> str:
    """`<Response><Hangup reason="busy"/></Response>`. Static: it must not depend on
    anything the failed answer depended on, and `infra/nginx/calevate.conf.template` serves
    the same bytes when voice-runtime itself is down."""
    response = Element("Response")
    response.append(Element("Hangup", {"reason": FALLBACK_HANGUP_REASON}))
    return _xml(response)


@router.api_route("/{carrier}/fallback", methods=["GET", "POST"], include_in_schema=False)
async def carrier_fallback(carrier: str, request: Request) -> Response:
    """The document the carrier fetches when an answer URL failed (D-675).

    A request that fails `authenticate` is still served the document, with a warning and no
    alarm: the commonest reason a REAL call's answer fails is the same misconfiguration that
    would fail it here (a rotated secret, a renumbered carrier), and a caller is better
    turned away with a busy tone than dropped. The document is static and names nothing,
    so serving it to a stranger tells them nothing. An authentic request alarms, because it
    means a caller was turned away.
    """
    started = time.perf_counter()
    surface = "fallback"
    if not is_carrier(carrier) or carrier not in CARRIER_ANSWER_CONTRACT:
        raise refuse("carrier_unknown", carrier=carrier, surface=surface)
    verdict = authenticate(carrier, request)
    response = _xml_response(fallback_document())
    if not verdict.ok:
        log.warning(
            "carrier_request_refused",
            extra={"carrier": carrier, "surface": surface, "reason": verdict.reason},
        )
        stamp_ack(response, started, carrier, meter=CARRIER_ACK)
        return response
    params, _readable = await read_params(request, carrier=carrier)
    carrier_call_id = keyable(params.get("CallUUID", ""))
    direction = params.get("Direction", "").strip()
    alert(
        "ROUTE_HANDLER",
        "carrier_answer_fallback_served",
        detail="the answer URL failed, so the caller was turned away with a busy hangup",
        carrier=carrier,
        carrier_call_id=carrier_call_id or "unknown",
        direction=direction if direction in ("inbound", "outbound") else "unknown",
    )
    ack_ms = stamp_ack(response, started, carrier, meter=CARRIER_ACK)
    log.warning(
        "carrier_answer_fallback_served",
        extra={
            "carrier": carrier,
            "carrier_call_id": carrier_call_id,
            "auth_method": verdict.method,
            "ack_ms": ack_ms,
        },
    )
    return response


_E164: Final = re.compile(r"^\+[1-9]\d{6,14}$")
#: Seconds. `timeout` covers ringing (vendor default 120 s), `timeLimit` the connected
#: bridge (default 14400 s) — `xml/dial.md:51-52`.
_DIAL_TIMEOUT_RANGE: Final = range(1, 601)
_DIAL_TIME_LIMIT_RANGE: Final = range(1, 86401)


@dataclass(frozen=True, slots=True)
class TransferOrder:
    """A transfer token's payload, validated. `to` and `caller_id` are PII (hard rule 6)."""

    to: str
    caller_id: str
    timeout_s: int
    time_limit_s: int
    call_id: str | None
    confirm_sound_url: str | None


def _bounded_int(value: Any, allowed: range) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value in allowed:
        return value
    return None


def transfer_order(payload: Mapping[str, Any]) -> TransferOrder | None:
    """The order a sealed token carries, or None when any field is not one we mint."""
    to, caller_id = payload.get("to"), payload.get("caller_id")
    timeout_s = _bounded_int(payload.get("timeout_s"), _DIAL_TIMEOUT_RANGE)
    time_limit_s = _bounded_int(payload.get("time_limit_s"), _DIAL_TIME_LIMIT_RANGE)
    call_id, sound = payload.get("call"), payload.get("confirm_sound_url")
    if not (isinstance(to, str) and _E164.match(to)):
        return None
    if not (isinstance(caller_id, str) and _E164.match(caller_id)):
        return None
    if timeout_s is None or time_limit_s is None:
        return None
    if call_id is not None and not isinstance(call_id, str):
        return None
    if sound is not None and not (isinstance(sound, str) and sound.startswith("https://")):
        return None
    return TransferOrder(
        to=to,
        caller_id=caller_id,
        timeout_s=timeout_s,
        time_limit_s=time_limit_s,
        call_id=call_id,
        confirm_sound_url=sound,
    )


def dial_document(order: TransferOrder) -> str:
    """`<Response><Dial callerId timeout timeLimit [confirmSound]>NUMBER</Dial></Response>`.

    VERIFIED-VENDOR-DOCS, `xml/dial.md:38-60`: a number placed directly inside `<Dial>` is
    the documented shorthand, and `callerId` must be a number the account owns (`:11-15`).
    `confirmSound` is the whisper; `confirmKey` is not emitted because the vendor calls its
    enforcement unverified (`:56`).
    """
    attributes = {
        "callerId": order.caller_id,
        "timeout": str(order.timeout_s),
        "timeLimit": str(order.time_limit_s),
    }
    if order.confirm_sound_url is not None:
        attributes["confirmSound"] = order.confirm_sound_url
    dial = Element("Dial", attributes)
    dial.text = order.to
    response = Element("Response")
    response.append(dial)
    return _xml(response)


@router.api_route("/{carrier}/transfer/{token}", methods=["GET", "POST"], include_in_schema=False)
async def carrier_transfer(carrier: str, token: str, request: Request) -> Response:
    """The `<Dial>` document a live call is redirected to for a human handoff.

    The destination is inside an AES-GCM token minted by the API
    (`calevate_shared.carrier_token`), because this route may not read the database and a
    number in a URL lands in access logs. Off unless `CARRIER_TRANSFER_ENABLED`, and served
    only for a carrier whose row declares a `<Dial>` grammar: no Dial is ever served
    otherwise.
    """
    surface = "transfer"
    contract, _verdict = admit(carrier, request, surface=surface)
    settings = get_settings()
    if not contract.dial_transfer:
        raise refuse("transfer_not_supported", carrier=carrier, surface=surface)
    if not settings.carrier_transfer_enabled:
        raise refuse("transfer_disabled", carrier=carrier, surface=surface)
    payload = open_sealed(settings.carrier_claim_secret, "transfer", token)
    if payload is None:
        raise refuse("transfer_token_invalid", carrier=carrier, surface=surface)
    order = transfer_order(payload)
    if order is None:
        # Authenticated by the key, so a malformed order is OUR minter's bug, not a probe.
        log.error("carrier_transfer_order_malformed", extra={"carrier": carrier})
        raise refuse("transfer_order_malformed", carrier=carrier, surface=surface)
    log.info(
        "carrier_transfer_served",
        extra={
            "carrier": carrier,
            "call_id": order.call_id,
            "whisper": order.confirm_sound_url is not None,
        },
    )
    return _xml_response(dial_document(order))


__all__ = [
    "ANSWER_DOCUMENT_CONTENT_TYPE",
    "CARRIER_ACK",
    "CARRIER_ANSWER_CONTRACT",
    "CLAIM_CALLER_STATE_PARAM",
    "CLAIM_CARRIER_PARAM",
    "FALLBACK_HANGUP_REASON",
    "RECORDING_FILE_FORMAT",
    "RECORDING_FINISH_ON_KEY",
    "RECORDING_MAX_LENGTH_S",
    "RECORDING_SILENCE_TIMEOUT_S",
    "TELEPHONY_SAMPLE_RATE_HZ",
    "AnswerCallerIdentity",
    "AnswerSourceVerdict",
    "CarrierAnswerContract",
    "CarrierAuthVerdict",
    "EvidenceClass",
    "SessionRecording",
    "TransferOrder",
    "admit",
    "answer_document",
    "authenticate",
    "caller_identity_from_answer_request",
    "carrier_label",
    "carrier_params",
    "dial_document",
    "fallback_document",
    "parse_call_id",
    "parse_ref",
    "read_params",
    "record_element",
    "refuse",
    "router",
    "session_recording_for",
    "stream_url",
    "transfer_order",
    "verify_answer_source",
]
