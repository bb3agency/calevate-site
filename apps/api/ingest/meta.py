"""Meta Lead Ads — the native receiver (SURFACES §2b).

Until now `meta_lead_ads` was a string in the `inbound_webhooks.source` CHECK
constraint and nothing else, and SURFACES said so in as many words: *"a native Meta
Lead Ads integration — their `X-Hub-Signature-256` verification and the form-field
mapping — is NOT built, so do not claim it in sales copy yet"*. This module is that
claim made true, up to exactly one boundary that this deployment cannot cross, which
is stated below rather than papered over.

RESEARCHED, NOT RECALLED
------------------------
`developers.facebook.com` is blocked by this sandbox's egress policy (403 at the
proxy on every attempt), so every statement below is sourced from indexed copies of
Meta's documentation and from independent implementations, and is marked the way TRD
§5 marks the Bolna surface: verified-from-docs vs pilot gate. The single live
confirmation still owed is a real delivery from a real Meta app (OPERATIONS §2 gate).

- **Signature.** Every POST carries `X-Hub-Signature-256: sha256=<hex>`, the
  HMAC-SHA256 of the **raw request body bytes**, keyed with the **Meta App Secret**.
  Not the verify token (that is the handshake string), not a Page access token (that
  is the read credential) — three different things that are routinely confused.
  Verify before parsing: Meta escapes non-ASCII in the bytes it signs, so a receiver
  that re-serializes the parsed JSON compares a digest against something the sender
  never sent.
  <https://developers.facebook.com/docs/graph-api/webhooks/getting-started> (via
  <https://hookdeck.com/webhooks/platforms/guide-to-whatsapp-webhooks-features-and-best-practices>
  and <https://hookdeck.com/webhooks/guides/how-to-implement-sha256-webhook-signature-verification>)
- **Handshake.** On subscribe, Meta GETs the callback URL with `hub.mode=subscribe`,
  `hub.verify_token=<the string you configured>` and `hub.challenge=<random>`. Echo
  the challenge as plain text with 200 when the mode and token both match; answer 403
  otherwise.
  <https://developers.facebook.com/docs/graph-api/webhooks/getting-started> (via
  <https://webhookrelay.com/blog/ingesting-facebook-webhooks/>)
- **Payload.** A leadgen notification is a CHANGE NOTIFICATION and carries no answers:
  `{"object":"page","entry":[{"id":…,"time":…,"changes":[{"field":"leadgen","value":
  {"leadgen_id":…,"page_id":…,"form_id":…,"adgroup_id":…,"ad_id":…,"created_time":…}}]}]}`
  — ids rendered as JSON numbers. The person's name and phone come from a SEPARATE
  Graph read, `GET /{leadgen_id}?fields=field_data`, which requires a **Page access
  token** with the `leads_retrieval` permission.
  <https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-leadgen/>
  · <https://developers.facebook.com/documentation/ads-commerce/marketing-api/guides/lead-ads/retrieving>
- **Delivery.** At-least-once with exponential backoff for up to ~36 hours; duplicates
  are expected and ordering is not guaranteed. Continued failure gets the app
  unsubscribed from the Page with a "Webhooks Disabled" alert — which is why a
  PERMANENT refusal here is acked rather than 5xx'd (WEBHOOKS §1.5 makes the same
  argument in the other direction: retrying a verdict only delays it). A TRANSIENT
  failure is the opposite case and gets the 503 it deserves: that ~36-hour ladder is
  the retry, and the `leadgen_id` claim is what makes redelivery free.
  <https://developers.facebook.com/community/threads/1838783773155149/>

THE GRAPH READ EXISTS NOW, AND WHAT IS STILL OWED
-------------------------------------------------
`apps/api/ingest/graph.py` is the adapter and holds every claim about Graph's request
shape, its version pin and its error codes, with its own sourcing block. This module
keeps the SEAM: the Protocol, the capability selector, the reason vocabulary and the
`field_data` → flat-map normalization. `LEAD_RETRIEVAL_IMPLEMENTED` is now `True`
because an adapter is written — it says a thing about the CODE, not about a deployment,
which is why nothing reads it to decide whether a lead can actually be fetched. That
question is `lead_retrieval_capability(source_id=…)`, and it is asked per lead source.

Still owed, and not pretended: **no live delivery from a real Meta app has ever been
read.** `developers.facebook.com` and `graph.facebook.com` are both egress-blocked here,
so the Graph half is documentation- and first-party-SDK-sourced throughout, in the same
state TRD §5 puts an unverified Bolna surface in. OPERATIONS §2b is the gate.

What was already right and is unchanged:

- the signature check, the handshake, and the refusals (an attacker only ever
  exercises these);
- durable dedupe **keyed on `leadgen_id`** — one lead is the unit of work, not one
  HTTP body. D-40 is the cautionary tale: an inbox keyed on the wrong unit silently
  never ran. Keying on the body would break the moment Meta batches two leads into
  one delivery or re-batches a retry, and one poison lead would block its siblings;
- the field mapping, which is the second half of the SURFACES claim;
- a refusal that is **recorded against the leadgen_id and visible in the client's
  activity view**, and that `claim_inbox_event` can re-claim by CAS — so a lead we
  could not read is a claim nobody completed, not a lead nobody will ever see again.

WHERE THE PAGE ACCESS TOKEN LIVES (SEC-COMP §5, and hard rule 1)
----------------------------------------------------------------
A Page access token is per-tenant, per-Page, and it arrives during a client's onboarding
rather than at deploy time — which is what makes it a harder question than the Sheets
key next door. The answer this repo takes:

- **The token is not in the database and there is no reference column either.** It lives
  in `META_PAGE_ACCESS_TOKENS`, one secrets-manager entry injected into the process
  environment like every other vendor credential, as a JSON object keyed by LEAD SOURCE
  ID (`inbound_webhooks.id`). There is nowhere else for key material to live: this
  deployment has no runtime secret-fetching client and inventing one for this would be a
  second way to hold a secret (`calevate_shared/config.py` argues that for Sheets).
- **The reference is DERIVED, not stored** — it is the lead source's own primary key.
  A `page_token_ref` column would be a stored copy of a value computed from the row's id,
  i.e. a second thing that can drift, and the same reasoning `verify_token_for` gives for
  deriving the hub verify token rather than storing a second secret beside the first.
  So there is no migration in this slice, and the tenant row holds exactly what it held.
- **Keyed by lead source, never by Meta Page id.** The Page id arrives INSIDE a
  notification, and a notification is signed with the app secret of the tenant it was
  sent to. Honouring a Page id from the payload would let tenant A — who legitimately
  holds their own app secret — sign a notification naming tenant B's Page, have B's token
  read B's lead, and receive it in A's CRM. Keying on the lead source id makes that
  unexpressible: the id is in the callback URL, we minted it, and it already resolves to
  one tenant under RLS. The credential is then ALSO the boundary at the vendor — a token
  that cannot read another Page's leads cannot leak them however we ask.
- **Who can write it: nobody in the application.** No route accepts a token and none
  accepts a secrets-manager path — `ingest/routes.py` says in as many words that the
  `sm://` credential attachment is the admin realm's and "no client may ever name" it.
  Attaching one is an operator step against the secrets manager (OPERATIONS §2b).
- **Expiry.** A long-lived Page token carries no expiry date, but it IS invalidated by
  the admin's password change, by the app's permissions being revoked, and by app-review
  or Page-role changes — reported consistently by independent integrators; Meta's own
  page is blocked here. So "it expired" is a real state and it has a name:
  `meta_page_token_invalid`, which alerts and refuses rather than retrying into a wall.
  Rotation is an edit to that one secret — no database write, no release.

TENANCY (hard rule 1)
---------------------
The callback URL carries our own `{webhook_id}`, so the tenant is resolved from a row
addressed by an unguessable UUID we minted — the `ingest_config_session` doctrine,
one row, no widening. `engine_agent_routes`' deliberately-global routing table is the
precedent for the OTHER situation: a vendor that can only call ONE URL and identifies
its own object (`engine_agent_ref`), leaving us to map a stranger's id onto a tenant.
Meta does not force that on us — a Meta app's callback URL is per-app configuration,
so each lead source gets its own URL and its own app secret, and no global page_id →
tenant table is needed. If Calevate ever runs ONE Meta app for every client, that
changes and the `engine_agent_routes` pattern (global table, no admin role, written
reasoning) is what to copy.

Hard rule 6: a lead's answers and phone number never reach a log line here. Ids,
reason codes and counts only — `leadgen_id`, `form_id` and `page_id` are Meta's own
object ids, not personal data, and they are the only things an operator can act on.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable
from uuid import UUID

from fastapi import Request

from apps.api.core.settings import get_settings
from apps.api.ingest.service import NO_CONSENT_FIELD_RULE as _NO_CONSENT_FIELD_RULE

# --- the wire contract ---------------------------------------------------------

SIGNATURE_HEADER: Final = "X-Hub-Signature-256"
SIGNATURE_PREFIX: Final = "sha256="

# The `changes[].field` that means "somebody filled in a lead form", and the value a
# client subscribes their Page to in the Meta App Dashboard. One constant, both uses.
LEADGEN_FIELD: Final = "leadgen"

# The only `object` a Page subscription delivers. Anything else is a subscription we
# did not ask for and do not read.
PAGE_OBJECT: Final = "page"

# Handshake query parameters, spelled once.
HUB_MODE_SUBSCRIBE: Final = "subscribe"

# The largest body we will buffer for a caller whose signature we have not checked yet
# — and we cannot check it without the body, so the cap comes first. Same reasoning and
# same number as `apps/voice-runtime/webhook_routes.py::_MAX_BODY_BYTES`: a batch of
# leadgen notifications is a few hundred bytes each, so a megabyte is already absurd,
# and buffering whatever a stranger sends is an unbounded allocation.
MAX_BODY_BYTES: Final = 1_048_576

# Meta's dashboard caps the challenge at a short random string; echoing an unbounded
# body back to whoever asked is a reflection primitive, so it is bounded here.
MAX_CHALLENGE_LEN: Final = 1024


# --- the capability seam -------------------------------------------------------
#
# Mirrors `billing/payments.py::payment_capability` and
# `workers/sheets_sync.py::get_sheets_transport`: ONE selector, authored reason codes,
# never vendor prose (a provider's error string is untrusted text that may quote the
# lead we just refused, and these land in an alert and in a client-visible field).

# Is there a Graph adapter in this repository at all? YES — `apps/api/ingest/graph.py`.
#
# A constant rather than a comment so the claim stays greppable and testable, and it
# says exactly one thing: someone wrote the adapter. It is NOT a statement that any
# deployment can fetch a lead, and nothing reads it to decide that — a client with no
# Page access token attached is unavailable no matter what this says, which is the
# distinction `payments.PROVIDER_CREATES_ORDERS` draws between having credentials and
# having code. `tests/meta_graph_test.py` fails the moment this and the adapter
# disagree in either direction.
LEAD_RETRIEVAL_IMPLEMENTED: Final = True

#: The provider name that selects the Graph adapter (`META_LEAD_RETRIEVER=graph`).
#: Defined in the SEAM and imported by the adapter, so a rename cannot leave the
#: selector looking for a provider that nothing answers to.
GRAPH_PROVIDER: Final = "graph"
#: The fixture adapter (`apps/api/ingest/recorded.py`), refused outside `local`.
RECORDED_PROVIDER: Final = "recorded"

#: This deployment has no lead-retrieval adapter selected at all. Unchanged spelling on
#: purpose: it is what an unconfigured deployment reported before the adapter existed,
#: it is what one reports now, and SURFACES/WEBHOOKS/the client's setup card all quote
#: it. What it no longer means is "nobody has written this".
NO_RETRIEVER_REASON: Final = "meta_lead_retrieval_unavailable"
#: A retriever exists, and THIS lead source has no Page access token attached. The
#: per-tenant half of the seam: one client being unconfigured says nothing about another.
NO_TOKEN_REASON: Final = "meta_page_token_not_configured"
#: `META_LEAD_RETRIEVER` names something with nothing behind it — loudly, rather than a
#: deployment that looks configured and refuses after the client has wired up an app.
PROVIDER_NOT_IMPLEMENTED_REASON: Final = "provider_not_implemented"
#: The fixture adapter, asked for outside `local`. See `recorded.py`: it would fabricate
#: a person and hand them to the compliance gate, which has no way to doubt they exist.
RECORDED_OUTSIDE_LOCAL_REASON: Final = "meta_recorded_retriever_refused"
NO_ANSWERS_REASON: Final = "meta_lead_had_no_answers"

#: The recorded refusals that ATTACHING A CREDENTIAL makes readable — the ones a re-drive
#: can act on (`POST /v1/lead-sources/{id}/meta/redrive`).
#:
#: Both are the capability selector saying "not configured", so both are undone by the
#: operator step that configures it, and the lead behind them is intact at Meta's end:
#: nothing was fetched, so nothing was lost. Everything else this module records is a
#: VERDICT about the lead itself — deleted at Meta, no answers on the form, no dialable
#: number, no published agent — and re-running one of those would spend a Graph call to
#: reach the same refusal.
#:
#: Two of the selector's own reasons are deliberately NOT here.
#: `RECORDED_OUTSIDE_LOCAL_REASON` and `PROVIDER_NOT_IMPLEMENTED_REASON` name a
#: deployment configured WRONG rather than one not configured yet, they have never been
#: reachable in production (`META_LEAD_RETRIEVER` is `graph` or unset), and the second
#: carries a `:provider` suffix so it is not an exact match at all — a `LIKE` in the
#: candidate query for a state no deployment has been in is a wider predicate than the
#: fix needs. Adding one is one line here plus one test.
REDRIVABLE_REASONS: Final[tuple[str, ...]] = (NO_TOKEN_REASON, NO_RETRIEVER_REASON)

# Re-exported, not redefined: the rule belongs to the ingest flow that raises it
# (`service.ingest_lead`), and two spellings of one rule name is how a support runbook
# and a timeline entry end up disagreeing.
NO_CONSENT_FIELD_RULE: Final = _NO_CONSENT_FIELD_RULE


class RetrievalStatus(StrEnum):
    """Three answers, because two would force a lie.

    The missing third is what the honest-hole version could not express: "ask again".
    Collapsing a Graph timeout into the same bucket as a deleted lead would either lose
    the lead (acked, never retried) or retry a verdict for 36 hours and end with Meta
    unsubscribing the client's Page. `routes.meta_leadgen` maps them to a 200 and a 503
    respectively, and the 503 is not an error page — it is us using Meta's own
    at-least-once ladder as the retry it already is.
    """

    RETRIEVED = "retrieved"
    #: This lead will not become readable by trying again. Record the refusal, ack.
    PERMANENT = "permanent"
    #: The moment was wrong, not the request. Leave the claim re-claimable, ask Meta to
    #: redeliver.
    TRANSIENT = "transient"


@dataclass(frozen=True, slots=True)
class RetrievedLead:
    """What an adapter hands back: OUR status, OUR reason, OUR flat answers.

    Deliberately NOT Meta's `field_data`. An earlier draft of this Protocol returned the
    vendor list and left normalization to the caller, which read well until there was a
    second thing to report — a `field_data` list has nowhere to put "the token is dead".
    Now `flatten_field_data` runs inside the adapters (both of them), and nothing outside
    `graph.py`/`recorded.py` has ever seen a vendor shape, which is hard rule 2's rule
    applied to a vendor that is just as replaceable as the voice engine.

    `reason` is non-None exactly when `status` is not `RETRIEVED`, and it is an AUTHORED
    code every time.
    """

    status: RetrievalStatus
    answers: dict[str, str] = field(default_factory=dict)
    reason: str | None = None


@runtime_checkable
class LeadRetriever(Protocol):
    """`GET /{leadgen_id}?fields=field_data`, per lead source.

    `source_id` is `inbound_webhooks.id` — the lead source in the callback URL, which is
    also the key its Page access token is held under. It is a PARAMETER rather than
    constructor state because one process serves every tenant, and an adapter that
    closed over one client's credential would need one instance per client and a cache
    to go with it.
    """

    #: The provider name that selected this adapter. Logged, never a decision input.
    name: str

    def holds_credential_for(self, source_id: UUID) -> bool: ...

    async def fetch_answers(self, *, source_id: UUID, leadgen_id: str) -> RetrievedLead: ...


@dataclass(frozen=True, slots=True)
class RetrievalCapability:
    """What this deployment can do about ONE lead source's answers, as one answer.

    `reason` is non-None exactly when `available` is False, and it is OUR code.
    `retriever` is non-None exactly when it is True — carried HERE rather than fetched
    separately so that a caller cannot conclude "retrieval is available" from one read
    and then obtain a retriever from another. That is the same argument
    `PaymentCapability.creates_orders` makes: two facts, one lookup, one object.
    """

    available: bool
    reason: str | None = None
    retriever: LeadRetriever | None = None


def lead_retrieval_capability(*, source_id: UUID) -> RetrievalCapability:
    """THE selector. Every surface asks this; nothing decides for itself.

    `source_id` is REQUIRED, and that is the whole design. A deployment-level answer
    ("we have an adapter") is not a question any surface should be able to ask, because
    the answer a client needs is about THEIR lead source: an adapter with no token for
    them is unavailable to them, and a setup card that said otherwise would send someone
    into the Meta App Dashboard for twenty minutes to configure something that will
    refuse every delivery. The capability is still DERIVED from the retriever itself
    rather than asserted by a settings flag — `holds_credential_for` is the retriever
    answering about its own credentials — so "we are configured" and "we can retrieve"
    cannot disagree.

    Settings are re-read on every call rather than cached, exactly like
    `get_sheets_transport`: rotating a token is then an edit to one secret plus a
    restart-free redeploy, and the cost is one `json.loads` of a small map against a
    call that is about to make an HTTPS round trip.
    """
    settings = get_settings()
    provider = (settings.meta_lead_retriever or "").strip().lower()
    if not provider:
        return RetrievalCapability(available=False, reason=NO_RETRIEVER_REASON)

    retriever: LeadRetriever
    if provider == GRAPH_PROVIDER:
        # Imported HERE, not at module scope: a deployment that has not selected the
        # Graph adapter never imports httpx for it, and `graph.py` imports this module
        # for the Protocol and the reason vocabulary — a top-level import would be a
        # cycle. The seam depends on nothing; the adapter depends on the seam.
        from apps.api.ingest.graph import GraphLeadRetriever

        retriever = GraphLeadRetriever(settings.meta_page_access_tokens or "")
    elif provider == RECORDED_PROVIDER:
        if settings.app_env != "local":
            return RetrievalCapability(available=False, reason=RECORDED_OUTSIDE_LOCAL_REASON)
        from apps.api.ingest.recorded import RecordedLeadRetriever

        retriever = RecordedLeadRetriever()
    else:
        return RetrievalCapability(
            available=False, reason=f"{PROVIDER_NOT_IMPLEMENTED_REASON}:{provider}"
        )

    if not retriever.holds_credential_for(source_id):
        return RetrievalCapability(available=False, reason=NO_TOKEN_REASON)
    return RetrievalCapability(available=True, retriever=retriever)


# --- authenticity --------------------------------------------------------------


def verify_signature(*, app_secret: str, body: bytes, header: str | None) -> bool:
    """HMAC-SHA256 of the RAW body, keyed with the app secret, constant-time compared.

    Fail-closed on every shape that is not exactly `sha256=<hex>`: an unprefixed
    digest, a `sha1=` header (the legacy `X-Hub-Signature`, which we do not accept —
    SHA-1 is not a signature we want to be the weakest link), an empty secret. An
    empty `app_secret` matters more than it looks: `secret_ref` is nullable in spirit
    if never configured, and `hmac.new(b"", …)` produces a perfectly valid digest that
    anyone can compute, so "no secret" would otherwise mean "signed by everybody".

    The comparison is on the hex text, lowercased, via `compare_digest` — so a wrong
    signature leaks no timing information about how much of it was right, and a
    gateway that upper-cases the header does not break a genuine delivery.
    """
    if not app_secret or not header:
        return False
    presented = header.strip()
    if not presented.lower().startswith(SIGNATURE_PREFIX):
        return False
    digest = presented[len(SIGNATURE_PREFIX) :].strip().lower()
    if not digest:
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected)


def verify_token_for(*, webhook_id: UUID, app_secret: str) -> str:
    """The `hub.verify_token` for this endpoint — DERIVED, not stored.

    The established shape is "the developer invents a string and pastes it into both
    systems". We generate it instead, which is what the better webhook products do,
    and here it buys three things worth more than the familiarity: (1) no second
    secret in the database — `secret_ref` is already one plaintext interim too many
    (SEC-COMP §5), and a verify token in the `mapping` JSONB would be a second; (2) it
    is per-endpoint, so learning one client's token subscribes nothing of another's;
    (3) it rotates with the app secret automatically, so a rotated secret cannot leave
    a stale token still able to complete a subscription.

    It is HMAC, not a hash of the secret, so the token discloses nothing about the
    secret it is derived from — which matters because we hand the token to the client
    to paste into the Meta App Dashboard.
    """
    return hmac.new(
        app_secret.encode(), f"meta-verify:{webhook_id}".encode(), hashlib.sha256
    ).hexdigest()


def handshake_matches(*, mode: str | None, token: str | None, expected: str) -> bool:
    """`hub.mode == "subscribe"` AND `hub.verify_token` matches, in constant time.

    Both halves are required by Meta's handshake and both are checked: a request that
    echoes the challenge for any mode would confirm a live endpoint to anyone who
    guessed the URL.
    """
    if mode != HUB_MODE_SUBSCRIBE or not token:
        return False
    return hmac.compare_digest(token.encode(), expected.encode())


# --- the payload, normalized ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeadNotification:
    """OUR shape for one leadgen change. Nothing downstream sees a vendor payload.

    Every field is a string even though Meta renders these as JSON numbers, because
    the id is used as a dedupe key and `7` and `"7"` must not be two different leads.
    Normalizing here is also what makes the inbox `payload_hash` stable: hashing the
    vendor dict would make a retry that quoted the ids differently look like a
    doctored replay and raise `webhook_payload_mismatch` at a genuine sender.
    """

    leadgen_id: str
    page_id: str = ""
    form_id: str = ""
    ad_id: str = ""
    adgroup_id: str = ""
    created_time: str = ""

    def provenance(self) -> dict[str, str]:
        """The "which ad produced this lead" half, for `leads.data`.

        Ours, not the sender's: the per-source field mapping deliberately drops
        unmapped keys (an unmapped field is unknown data from an external party), and
        this is not one of those — it is what we know about where the lead came from,
        and no client should have to map it to keep it.
        """
        return {k: v for k, v in asdict(self).items() if v}


def _as_id(value: Any) -> str:
    """A Meta object id as a string. Numbers, strings, nothing else.

    `bool` is excluded before `int` because `True` is an `int` in Python and would
    become the id `"True"`. Floats are excluded because an id that arrived as a float
    has already lost precision — 15-digit ids do not survive it — so accepting one
    would key a lead on a number that is not the lead's.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""


def extract_lead_notifications(payload: Any) -> list[LeadNotification]:
    """Meta's change notification → our lead notifications, defensively.

    Everything that is not a `page` object's `leadgen` change with a usable id is
    silently skipped rather than raising: a Page subscription can carry other fields
    (`feed`, `messages`) that are simply not ours to read, and a 4xx for them would
    make Meta retry a delivery that is perfectly fine.
    """
    if not isinstance(payload, dict) or payload.get("object") != PAGE_OBJECT:
        return []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []

    found: list[LeadNotification] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict) or change.get("field") != LEADGEN_FIELD:
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            leadgen_id = _as_id(value.get("leadgen_id"))
            if not leadgen_id:
                # No id, no unit of work: nothing to dedupe on and nothing to fetch.
                continue
            found.append(
                LeadNotification(
                    leadgen_id=leadgen_id,
                    page_id=_as_id(value.get("page_id")) or _as_id(entry.get("id")),
                    form_id=_as_id(value.get("form_id")),
                    ad_id=_as_id(value.get("ad_id")),
                    adgroup_id=_as_id(value.get("adgroup_id")),
                    created_time=_as_id(value.get("created_time")),
                )
            )
    return found


def flatten_field_data(field_data: Any) -> dict[str, str]:
    """Meta's `[{"name": …, "values": [...]}]` → the flat `{field: answer}` map the
    per-source mapping already knows how to rename.

    This is the "form-field mapping" half of the SURFACES claim, and it is the reason
    nothing else in this module has to know that Meta's answers are a list: once
    flattened, a Meta lead is the same shape as a website form POST and takes the same
    code path — `apply_mapping` → `ingest_lead` → the compliance gate. One way per
    problem.

    A multi-select answer is joined rather than truncated (dropping the second choice
    would quietly change what the person said); an empty `values` is dropped, because
    an unanswered optional question is not the answer "".
    """
    if not isinstance(field_data, list):
        return {}
    flat: dict[str, str] = {}
    for row in field_data:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        values = row.get("values")
        if not isinstance(name, str) or not name.strip() or not isinstance(values, list):
            continue
        answers = [str(v).strip() for v in values if v is not None and str(v).strip()]
        if not answers:
            continue
        flat[name.strip()] = ", ".join(answers)
    return flat


async def read_bounded_body(request: Request) -> bytes | None:
    """The raw body, or None if the caller exceeded `MAX_BODY_BYTES`.

    Streamed rather than `await request.body()` so an oversized POST is abandoned after
    a megabyte instead of after all of it, and the declared length is checked first so
    the common attack reads nothing at all.

    This is a second implementation of `apps/voice-runtime/webhook_routes.py`'s
    `_read_bounded`, and deliberately so: that module is in the other deployable and
    `apps/api` importing from it would couple the two deploys, which hard rule 3
    forbids in exactly those words. The dependency arrow only runs the other way.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def inbox_provider(webhook_id: UUID) -> str:
    """The `webhook_inbox_events.provider` for this endpoint.

    Distinct from the `ingest:` prefix of the shared-secret path: the same lead source
    could in principle be posted to both, and one `leadgen_id` colliding with another
    sender's body hash would be a cross-source dedupe. Both prefixes carry the
    `webhook_id`, so no two tenants share a keyspace either.
    """
    return f"meta:{webhook_id}"


__all__ = [
    "GRAPH_PROVIDER",
    "HUB_MODE_SUBSCRIBE",
    "LEADGEN_FIELD",
    "LEAD_RETRIEVAL_IMPLEMENTED",
    "MAX_BODY_BYTES",
    "MAX_CHALLENGE_LEN",
    "NO_ANSWERS_REASON",
    "NO_CONSENT_FIELD_RULE",
    "NO_RETRIEVER_REASON",
    "NO_TOKEN_REASON",
    "PAGE_OBJECT",
    "PROVIDER_NOT_IMPLEMENTED_REASON",
    "RECORDED_OUTSIDE_LOCAL_REASON",
    "RECORDED_PROVIDER",
    "REDRIVABLE_REASONS",
    "SIGNATURE_HEADER",
    "SIGNATURE_PREFIX",
    "LeadNotification",
    "LeadRetriever",
    "RetrievalCapability",
    "RetrievalStatus",
    "RetrievedLead",
    "extract_lead_notifications",
    "flatten_field_data",
    "handshake_matches",
    "inbox_provider",
    "lead_retrieval_capability",
    "read_bounded_body",
    "verify_signature",
    "verify_token_for",
]
