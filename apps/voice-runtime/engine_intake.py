"""The voice-runtime's engine twin (hard rule 2's "and its voice-runtime twin").

Deliberately tiny. The receiver has one job — decide whether an event is authentic
and what its dedupe key is — and hard rule 3 forbids paying for anything else on this
path: no HTTP client, no cost arithmetic, no transcript parsing, no ORM. The full
adapter (`apps/api/engine/`) does all of that later, in a worker, where a 200ms import
costs nothing.

So this module extracts exactly three fields and refuses to interpret the rest. The
payload is a HINT (D-31); the worker's authenticated Get Execution is the truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from calevate_shared.config import SOURCE_IP_ALLOWLIST_BY_ENGINE
from calevate_shared.engine import WEBHOOK_AUTH_BY_ENGINE, WebhookAuthMethod

log = get_logger(__name__)

# Bolna's static egress IP is their ONLY webhook authenticity control (D-31, TRD §5),
# and it is enforced at nginx AND here: nginx config drifts, this does not.
#
# THE SET ITSELF IS NOT DEFINED HERE. It comes from `BOLNA_WEBHOOK_SOURCE_IPS` via
# `calevate_shared.config.bolna_source_ips`, which is the ONE resolver — the adapter's
# `verify_webhook` reads the same function, so an operator who rotates the variable
# during a vendor renumber (the documented recovery path, and the whole reason the
# setting exists) moves the receiver's answer and the adapter's verdict together. This
# module used to resolve the value once at import into a `BOLNA_SOURCE_IPS` global while
# the adapter matched a hardcoded constant; that pair agreed only until the recovery
# path was used, which is exactly when nobody is re-reading two files.
#
# Resolution stays O(1) per delivery: `get_settings` and the parse are both cached.

# WHERE `client_ip` WENT, AND WHY IT IS NOT HERE ANY MORE. It was defined in this file,
# together with `is_trusted_peer` and `TRUSTED_PROXY_CIDRS`, and `apps/api` had a SECOND
# answer to the same question (`core/auth.py::_request_ip` read the socket peer, which
# behind the edge is nginx's address). Two answers to one question is a defect even when
# both work, so the definition moved to `calevate_shared.client_address` — importable by
# both deployables, importing neither, and still nothing heavier than `ipaddress` on this
# 500ms path (hard rule 3). The callers here pass `app_env` because the shared module may
# not import `apps.api.core.settings` (import-linter: "shared package imports no app
# code").
#
# The engines this service will answer for at all — the SAME set `verify_source` below
# consults, so "known" and "has an authenticity story" are provably one answer rather than
# two that agree today (`tests/engine_name_drift_test.py` asserts the equality both ways).
#
# THIS FILE USED TO DEFINE THE SET ITSELF, and that is the defect D-103 closes. It was
# `EngineName = Literal["bolna", "fake"]` here plus `Literal["fake", "bolna", "cartesia"]`
# in `calevate_shared.config` — a second copy of a union, which drifted the moment
# `cartesia` was added to the first and this one was not. Nothing could see it: the two
# lived in different deployables, `check_wiring` looks at routers and migration heads, and
# the receiver went on refusing every Cartesia delivery for the RIGHT reason (no signature
# verifier, below) while labelling the refusals `unknown` — the one word that makes a
# self-inflicted refusal storm look exactly like a stranger probing the URL.
#
# `WEBHOOK_AUTH_BY_ENGINE` is the right source rather than `config.SELECTABLE_ENGINES`
# because the question this set answers is "does this name have an authenticity story",
# not "may an operator select it". The conformance fixture `fake-restricted` is the case
# that separates them: it is deliberately unselectable, it is the only engine in the tree
# that declares `hmac`, and the receiver must still answer for it identically or the one
# test that exercises the signature branch would be testing a different code path from the
# one production runs.
#
# What the set BOUNDS is anything the URL's `{engine}` segment is allowed to become — a
# metric label, in particular: on the refusal path that segment is an unauthenticated
# stranger's string, and an unbounded label is a way to blind our own monitoring.
KNOWN_ENGINES: frozenset[str] = frozenset(WEBHOOK_AUTH_BY_ENGINE)


@dataclass(frozen=True, slots=True)
class IntakeVerdict:
    ok: bool
    # `WebhookAuthMethod`, not a local `Literal["hmac", "source_ip", "none"]` — which is
    # what this was, character for character. Two spellings of one vocabulary is how the
    # receiver ends up reporting a method the adapter cannot express (D-103).
    method: WebhookAuthMethod
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IntakeEvent:
    """The three fields the receiver needs and nothing more."""

    execution_id: str
    raw_status: str
    engine_agent_ref: str | None


def verify_source(engine: str, source_ip: str | None) -> IntakeVerdict:
    """`source_ip` is None when `calevate_shared.client_address.client_ip` could not
    establish one — see there.

    That is a REFUSAL for an allowlisted engine, with its own reason string so the alert
    tells an operator which half broke: "not allowlisted" is a vendor renumber (rotate
    `BOLNA_WEBHOOK_SOURCE_IPS`), "client ip not established" is the EDGE (real_ip or the
    `CF-Connecting-IP` line in `calevate-proxy.conf` is gone, or something is reaching the
    container without going through nginx). Two very different runbook entries, and an
    unsigned engine cannot afford them to look alike.

    WHICH METHOD APPLIES IS LOOKED UP, NOT HARD-CODED (D-93). This function used to open
    `if engine == "bolna":` — a vendor name compiled into the latency-critical receiver,
    so adopting an engine that SIGNS its webhooks meant editing this service and
    redeploying it in lockstep with the adapter, which hard rule 3's last clause exists to
    prevent. `WEBHOOK_AUTH_BY_ENGINE` is the one table both readers share (the adapters'
    own declarations are asserted equal to it by the conformance suite), and reading it
    costs one dict lookup on a path that must ack in under 500ms.

    It stays a TABLE rather than an import of the adapter's descriptor because hard rule 3
    forbids the heavy import here: reaching `EngineCapabilities` through
    `apps.api.engine` would pull httpx and the vendor client into the ack path.
    """
    method = WEBHOOK_AUTH_BY_ENGINE.get(engine)
    if method == "source_ip":
        # WHOSE ALLOWLIST, and the answer is not "whoever asked" (P2.6). The METHOD is
        # looked up per engine; the ADDRESSES were not — this read `bolna_source_ips` for
        # any engine declaring `source_ip`, so a second such engine would have been
        # authenticated against Bolna's egress. That is the identical defect the `hmac`
        # branch below spends a paragraph refusing ("an allowlist is evidence about a
        # DIFFERENT engine's egress"), left live one branch above it. Inert today, because
        # `bolna` is the only engine declaring the method — which is exactly why it was
        # invisible, and exactly why a lookup with no entry must refuse rather than fall
        # back to the one entry that exists.
        resolver = SOURCE_IP_ALLOWLIST_BY_ENGINE.get(engine)
        if resolver is None:
            return IntakeVerdict(
                ok=False, method="source_ip", reason="no source ip allowlist for this engine"
            )
        if source_ip is not None and source_ip in resolver(get_settings()):
            # `source_ip`, not `hmac`: the caller must keep treating this as a hint.
            return IntakeVerdict(ok=True, method="source_ip")
        return IntakeVerdict(
            ok=False,
            method="source_ip",
            reason="source ip not allowlisted"
            if source_ip is not None
            else "client ip not established",
        )
    if method == "hmac":
        # DECLARED BY AN ADAPTER, NOT IMPLEMENTED HERE — and refused rather than waved
        # through, which is the only safe direction. Writing a signature verifier for an
        # engine we have not adopted would mean inventing the header, the canonical string
        # and the digest, and an unverified vendor contract is exactly what D-31/D-32
        # forbid; getting any of the three wrong would produce a receiver that rejects
        # every real delivery and accepts nothing but our own test vectors.
        #
        # THE PREVIOUS COMMENT HERE SAID THIS WAS UNREACHABLE — "no signing engine is
        # selectable as `ENGINE=`" — and that stopped being true when D-93 put `cartesia`
        # in `config.EngineName`. It is reachable now, on purpose, and the answer is the
        # same one: `CartesiaEngine.verify_webhook` fails closed for the identical reason
        # (`SIGNATURE_UNIMPLEMENTED_REASON`), so the receiver and the adapter refuse
        # together rather than one of them deciding to be helpful.
        #
        # WHY THE REFUSAL MUST OUTLIVE THE TEMPTATION TO SOFTEN IT. `webhook_routes`
        # derives the forensic row's `signature_valid` from `verdict.method == "hmac"`, so
        # a wave-through here would not merely accept a forgery — it would FILE one as
        # signed, and a later investigation would read the strongest evidence we can
        # record next to a payload nobody checked. Falling back to the source-IP allowlist
        # would be the same defect in a friendlier shape: an allowlist is evidence about a
        # DIFFERENT engine's egress, and reusing it here would authenticate Cartesia
        # deliveries against Bolna's addresses.
        #
        # The cost of refusing is bounded and known: every delivery 401s and the 10-minute
        # reconciliation poller stays the guarantee of record (D-31). The cost of the other
        # direction is not bounded at all.
        return IntakeVerdict(
            ok=False, method="hmac", reason="signature verification not implemented"
        )
    if method == "none":
        # An engine that declares NO authenticity control at all. Today that is the fake
        # engine, and it is by design — that is how the whole pipeline runs offline
        # (DEV-SETUP §3). Which makes this route an unauthenticated write endpoint, and
        # the route table is identical in every environment: on a prod box running
        # ENGINE=bolna, `/hooks/v1/engine/fake` would hand any stranger who found the URL
        # an inbox claim, a forensic row and an ARQ job.
        #
        # So the door is open exactly where that engine IS this deployment's engine.
        # Matched against the declared method and the requested name rather than against
        # the literal `"fake"`, which is what this used to do: a hard-coded vendor name in
        # the latency-critical receiver is the thing D-93 removed from the branch above,
        # and leaving one here meant the same class of drift survived in the same
        # function. The generalisation changes no answer today — `fake` is the only
        # engine declaring `none` — and it makes the gate follow the declaration.
        if get_settings().engine == engine:
            return IntakeVerdict(ok=True, method="none", reason="fake engine")
        return IntakeVerdict(
            ok=False, method="none", reason="fake engine is not enabled in this environment"
        )
    return IntakeVerdict(ok=False, method="none", reason="unknown engine")


# The longest a keyable field may be. Bolna's execution ids are uuid-shaped (36 chars)
# and its status enum's longest member is `call-disconnected` (17), so 128 is several
# times either — generous enough that a vendor change does not start dropping real
# events, and far under the ~2704-byte ceiling a btree index tuple has.
#
# THE CEILING IS NOT COSMETIC. `execution_id` and `raw_status` are concatenated into
# `webhook_inbox_events.event_key`, which carries a UNIQUE index: a long enough value in
# either position makes Postgres answer `index row size N exceeds btree version 4
# maximum` and the whole ack becomes an unhandled 500. Same story for a NUL byte, which
# psycopg refuses outright. Both are worth exactly one 500 to learn, and at an endpoint
# whose vendor delivers at-most-once and never retries (D-31), that 500 is a lost call.
_MAX_KEY_FIELD = 128

# C0 + DEL. A control character has no business in an execution id or a status; NUL
# cannot be stored in a Postgres text column at all, and the rest are log- and
# key-injection material for a value we copy verbatim into a dedupe key and a job id.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


#: The three spellings a payload may name its execution by, in the order we trust them.
#: The tool payload's shape is an ASSUMPTION about the engine's custom-function mechanism
#: (OPERATIONS §2 gate 8), not a verified contract, so betting on one spelling would be a
#: guess with no fallback; the webhook path has always accepted the first two.
_EXECUTION_ID_FIELDS = ("execution_id", "id", "call_id")


def _keyable(value: str) -> str | None:
    """The part of `value` that can safely become a durable key, or None if none of it can.

    SURROUNDING WHITESPACE IS STRIPPED, NOT REJECTED, and that is the point rather than a
    tidiness: this value is concatenated into `webhook_inbox_events.event_key` and into the
    ARQ job id, so `"exec_1 "` and `"exec_1"` were TWO units of work for one transition —
    two inbox rows, two jobs, and a post-call pipeline that runs twice on a call whose
    `usage_events` are append-only (hard rule 4, where a double charge is uncorrectable by
    construction). `raw_status` was already half-normalised (`.lower()` in `extract`) and
    that is exactly the shape of bug a half-normalisation leaves behind. Padding is free to
    produce at an unsigned endpoint, so this is a control and not a courtesy.
    """
    trimmed = value.strip()
    if not trimmed or len(trimmed) > _MAX_KEY_FIELD or _CONTROL_CHARS.search(trimmed):
        return None
    return trimmed


def execution_key(payload: dict[str, Any]) -> str | None:
    """The execution id a payload can be keyed by, or None if it names none we can store.

    Split out of `extract` so the in-call tool route (`tool_routes.py`) can ask the same
    question without the status half — a tool call carries no lifecycle status, and
    inventing one for it would put a fictional transition into a dedupe key.

    EACH SPELLING IS TRIED, rather than `a or b or c` then one type check. That chain read
    the first field that was merely TRUTHY and then discarded the payload if it was not a
    string, so `{"execution_id": 12345, "call_id": "exec_abc"}` — a vendor sending a
    numeric id in one field and a usable one in another — was answered `unkeyable` with a
    perfectly good key sitting one field to the right. The fallback existed precisely for
    a payload shape we have not verified; a fallback that only survives a FALSY first
    field is not one.
    """
    for field in _EXECUTION_ID_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and (keyed := _keyable(value)) is not None:
            return keyed
    return None


def extract(payload: dict[str, Any]) -> IntakeEvent | None:
    """Pull the dedupe key and the status. Returns None when the payload carries no
    execution id — an event we cannot key is an event we cannot dedupe, and processing
    it twice would double-meter a call.

    "Carries no execution id" now includes "carries one we refuse to store". The caller's
    answer to an unkeyable payload is already the right answer to an unstorable one: ack
    it, alert `webhook_unkeyable`, and let the 10-minute reconciliation poller be the
    truth (D-31). That is a deliberate answer; a 500 out of the database driver is not.
    """
    keyed_id = execution_key(payload)
    if keyed_id is None:
        return None
    raw_status = _keyable(str(payload.get("status") or "unknown").lower())
    if raw_status is None:
        return None
    # NOT fatal, unlike the two above: the ref is a hint the worker uses to resolve a
    # tenant, not part of any key, and the authenticated Get Execution is what actually
    # says which agent this was. An implausible one is dropped and the event still flows
    # — otherwise a junk field could suppress a real call's event entirely.
    agent_ref = payload.get("agent_id")
    return IntakeEvent(
        execution_id=keyed_id,
        raw_status=raw_status,
        engine_agent_ref=_keyable(str(agent_ref)) if agent_ref else None,
    )


__all__ = [
    "KNOWN_ENGINES",
    "IntakeEvent",
    "IntakeVerdict",
    "execution_key",
    "extract",
    "verify_source",
]
