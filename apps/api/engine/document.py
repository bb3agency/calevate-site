"""The one place a vendor payload becomes bytes and stops being a shape (hard rule 2).

Every adapter answers `get_execution` with an `ExecutionSnapshot`, and D-126's archive
needs the vendor's OWN document for the same call to reach the post-call pipeline. This
module is the seam that lets both be true: the adapter hands the dict it already parsed
to `engine_document`, and what crosses the boundary is `bytes` — the same information,
with no key anyone above can read.

WHY A MODULE AND NOT A LINE IN EACH ADAPTER. Three adapters would otherwise each pick a
serializer, a size policy and a failure answer, and the three would drift on the leg
nobody reads — the defect `SARVAM_DEFAULT_LLM` and `WEBHOOK_AUTH_BY_ENGINE` both exist to
stop. It lives inside `apps/api/engine/` because it is the only package permitted to hold
a vendor payload at all, and it logs, which `calevate_shared` may not (import-linter:
"shared package imports no app code").
"""

from __future__ import annotations

import json
from typing import Any, Final

from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: The largest vendor document an adapter will carry out to the archive.
#:
#: DERIVED FROM WHAT THE DOCUMENT IS, not picked: a Bolna execution is its metadata plus
#: one call's transcript, and the platform refuses to run a call longer than
#: `CALL_CAP_MAX_S` (one hour). An hour of two-party speech is a few tens of thousands of
#: characters; Telugu in UTF-8 is three bytes a character, so 1 MiB is roughly an order of
#: magnitude of headroom over the longest call this platform can produce. Anything past it
#: is not a call transcript — it is a vendor field we have never seen, and putting an
#: unbounded third-party document into an object store on every completed call is the
#: shape `MAX_RECORDING_BYTES` and `MAX_RETAINED_BODY_BYTES` already refuse.
#:
#: REFUSED RATHER THAN TRUNCATED, which is the opposite of `store_delivery_body`'s answer
#: and the difference is what the artifact is FOR. A truncated delivered body still answers
#: "what did we send them" for the fields at the front. A truncated vendor document answers
#: nothing — it is unparseable JSON whose only use was being re-read when our mapping is
#: wrong — so half of one is a liability holding a caller's number rather than a partial
#: record. The refusal is LOUD (below) and costs the debug copy, never the call.
MAX_ENGINE_DOCUMENT_BYTES: Final = 1024 * 1024


def engine_document(payload: dict[str, Any], *, engine: str) -> bytes | None:
    """The vendor's answer as opaque bytes, or None when it must not be carried.

    `default=str` because a payload an adapter has already touched can hold a `datetime`
    or a `Decimal`, and a serializer that raised here would fail a CALL to save a debug
    copy — the tail wagging the dog that `archive_payload` refuses in the same words.

    Compact separators: the archive is bytes in a bucket, not a document anyone reads by
    eye, and whitespace is 10-15% of a JSON payload's size at no benefit.

    None on refusal, never a partial document and never an exception. The two refusals are
    an oversized payload and one that will not serialize at all; both are logged with the
    engine and a byte count and NEVER with one byte of the payload, which holds the
    caller's number and the transcript (hard rule 6).
    """
    try:
        encoded = json.dumps(payload, default=str, separators=(",", ":")).encode()
    except (TypeError, ValueError):
        # `default=str` makes this very hard to reach — a recursive structure is the
        # realistic way. Reported rather than raised: a debug artifact may not fail a call.
        log.warning("engine_document_unserializable", extra={"engine": engine})
        return None
    if len(encoded) > MAX_ENGINE_DOCUMENT_BYTES:
        log.warning(
            "engine_document_oversized",
            extra={"engine": engine, "bytes": len(encoded), "cap": MAX_ENGINE_DOCUMENT_BYTES},
        )
        return None
    return encoded


__all__ = ["MAX_ENGINE_DOCUMENT_BYTES", "engine_document"]
