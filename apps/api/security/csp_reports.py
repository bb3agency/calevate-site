"""What a Content-Security-Policy violation report is allowed to become, in our logs.

A report arrives from a stranger's browser with no credential — see `routes.py` for the
admission control — and it carries three URL-shaped fields that hard rule 6 governs
directly. This module is the pure half: parse either wire shape, throw away everything
that must not be kept, and hand back a small frozen record. No I/O, so it is unit-testable
without a request and the redaction can be asserted field by field.

═══════════════════════════════════════════════════════════════════════════════
THE TWO WIRE SHAPES, AND WHY BOTH ARE ACCEPTED
═══════════════════════════════════════════════════════════════════════════════
`report-uri` posts ONE object under a `csp-report` key with kebab-case members
(`blocked-uri`, `violated-directive`), content type `application/csp-report`. `report-to`
(the Reporting API) posts an ARRAY of envelopes, each `{type, age, url, body}`, with
camelCase members (`blockedURL`, `effectiveDirective`), content type
`application/reports+json`. The policy this collects for emits both directives, because
`report-to` is not implemented everywhere and `report-uri` is deprecated everywhere — so
the collector must read both or it silently drops half its audience.

EVIDENCE CLASS: **REPORTED, corroborated across independent secondaries** (5 Sep 2026).
`developer.mozilla.org` is egress-blocked from this container, so nobody here has read the
spec pages this session. The consequence is deliberately contained: the parser treats
every member as OPTIONAL and never raises on a shape it does not recognise — an unread
field costs a `None` in a log line, never a 500 on a public endpoint.

═══════════════════════════════════════════════════════════════════════════════
WHAT IS KEPT, AND WHAT IS THROWN AWAY (hard rule 6)
═══════════════════════════════════════════════════════════════════════════════
The console serves `/c/{slug}/leads/{leadId}?q=…`. A full `document-uri` therefore carries
a tenant slug, record ids and whatever a user typed into a filter, and `referrer` carries
the same for the PREVIOUS page. None of that may reach a log line. So:

* `document-uri` → **origin plus the FIRST path segment, and nothing else.** The first
  segment is the realm (`/c`, `/admin`, `/auth`, or empty for the landing page); the
  SECOND is the tenant slug. Keeping one segment answers "which console" — which is what
  a CSP fix needs — and keeping two would identify the client.
* `referrer` → **dropped entirely.** It is a whole URL from a page we are not even being
  told about, and it answers no question that fixing a policy asks.
* `blocked-uri` → **origin only** when it is a URL, verbatim when it is one of the CSP
  keywords (`inline`, `eval`, `data`, `blob`, `self`) — those are the vocabulary, not
  data. The origin is the whole point of the field: it names the host to admit or refuse.
* `source-file` → **origin only**, same reasoning. The line and column numbers are kept;
  they are integers about our own bundle.
* `script-sample` → **dropped.** It is up to 40 characters OF THE OFFENDING SCRIPT OR
  STYLE, chosen by whatever produced the violation. On a page rendering a call transcript
  that is a caller's words; on an injected script it is an attacker's payload, which is
  not a thing to concatenate into an operator's mail.
* `original-policy` → **dropped, and this one is a secret rather than PII.** It is the
  full policy we served, WHICH CONTAINS THAT REQUEST'S NONCE. Logging it would publish
  the one value the whole nonce scheme depends on staying unguessable, into the log
  aggregation of a system whose logs more people can read than can read the traffic.
* `effective-directive` / `violated-directive` / `disposition` / `status-code` → kept.
  Ours, bounded, and the fields that actually identify the breakage.

Every kept string is length-bounded on the way out: the sender chooses these bytes and a
log line is memory somebody else is spending.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

#: The CSP source keywords that appear in `blocked-uri` instead of a URL. Kept verbatim
#: because they are our vocabulary — `inline` is the single most useful value this
#: endpoint can report, since it is what an injected `<script>` looks like from here.
BLOCKED_URI_KEYWORDS: frozenset[str] = frozenset(
    {"inline", "eval", "self", "data", "blob", "filesystem", "wasm-eval", "unsafe-eval"}
)

#: Schemes a browser EXTENSION loads from. Reports naming one are the loudest source of
#: noise any enforced CSP has — an ad blocker or a password manager injecting into our
#: page trips `script-src` on every navigation — and they say nothing about our policy or
#: our security: the extension runs with the user's own permission, not through a hole in
#: ours. Dropped before anything is recorded or alerted, and COUNTED so the drop is
#: visible rather than silent.
EXTENSION_SCHEMES: frozenset[str] = frozenset(
    {
        "chrome-extension",
        "moz-extension",
        "safari-extension",
        "safari-web-extension",
        "ms-browser-extension",
        # Safari reports an extension's URL as this opaque placeholder rather than as a
        # scheme naming the extension, so the same noise arrives under a second spelling.
        "webkit-masked-url",
    }
)

#: The longest any kept string may be. Generous for a directive name, far shorter than
#: anything a sender could use this endpoint to store.
MAX_FIELD_CHARS = 120

#: How many envelopes one `application/reports+json` POST may carry before the rest are
#: ignored. The Reporting API batches, and the batch size is the sender's choice.
MAX_REPORTS_PER_POST = 20


@dataclass(frozen=True, slots=True)
class CspViolation:
    """One violation, already stripped. Everything here is safe to log (hard rule 6)."""

    #: The directive that actually refused it (`script-src`, `media-src`, …).
    effective_directive: str
    #: The origin (or CSP keyword) of what was refused. `None` when the report omitted it.
    blocked_origin: str | None
    #: Our own origin plus one path segment — the realm, never the tenant.
    document_realm: str | None
    #: Where in OUR bundle it happened, when the browser said.
    source_origin: str | None
    line_number: int | None
    #: `enforce` or `report`. Present only on the Reporting API shape and on newer
    #: `report-uri` senders; `None` means the browser did not say.
    disposition: str | None

    @property
    def fingerprint(self) -> str:
        """What makes two violations "the same one" for an operator.

        The directive and the blocked origin, and deliberately NOT the page: one bad
        origin on forty screens is one fix, and forty alarms for it is the flood this
        endpoint would otherwise become.
        """
        return f"{self.effective_directive}|{self.blocked_origin or '-'}"


def _clip(value: object) -> str | None:
    """A sender-supplied string, bounded, or None for anything that is not one."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:MAX_FIELD_CHARS] if text else None


def _int_or_none(value: object) -> int | None:
    """Line/column numbers, which some senders give as strings. Bounded to a plausible
    file so a sender cannot put an arbitrary integer in a log line."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 10_000_000 else None
    if isinstance(value, str) and value.isdigit():
        return _int_or_none(int(value))
    return None


def scheme_of(raw: str | None) -> str | None:
    """The scheme of a report-supplied URL, lowercased, or None."""
    if raw is None:
        return None
    scheme = urlsplit(raw).scheme.lower()
    return scheme or None


def origin_only(raw: object) -> str | None:
    """`https://cdn.example/evil.js?k=v` → `https://cdn.example`.

    A CSP keyword passes through unchanged; anything unparseable becomes None rather than
    being kept "just in case", because "just in case" is how a query string reaches a log.
    """
    text = _clip(raw)
    if text is None:
        return None
    if text.lower() in BLOCKED_URI_KEYWORDS:
        return text.lower()
    parts = urlsplit(text)
    if not parts.scheme:
        return None
    # An opaque scheme (`data:`, `chrome-extension:` with no netloc) has no origin worth
    # printing and its body is the payload. The scheme alone is the whole safe answer.
    if not parts.netloc:
        return parts.scheme.lower()
    return f"{parts.scheme.lower()}://{parts.netloc}"[:MAX_FIELD_CHARS]


def document_realm(raw: object) -> str | None:
    """`https://app.calevate.tech/c/acme/leads/018f?q=x` → `https://app.calevate.tech/c`.

    One segment, never two: the second is the tenant slug. See the module docstring.
    """
    text = _clip(raw)
    if text is None:
        return None
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return None
    first = next((segment for segment in parts.path.split("/") if segment), "")
    origin = f"{parts.scheme.lower()}://{parts.netloc}"
    return f"{origin}/{first}" if first else origin


def _from_report_uri_body(body: dict[str, Any]) -> CspViolation | None:
    """The legacy `application/csp-report` shape: kebab-case, under `csp-report`."""
    directive = _clip(body.get("effective-directive")) or _clip(body.get("violated-directive"))
    if directive is None:
        return None
    return CspViolation(
        # `violated-directive` historically carried the whole source list on some
        # browsers ("script-src 'self' https://…"); the directive NAME is the first token
        # and the rest is a copy of our own policy.
        effective_directive=directive.split(" ", 1)[0],
        blocked_origin=origin_only(body.get("blocked-uri")),
        document_realm=document_realm(body.get("document-uri")),
        source_origin=origin_only(body.get("source-file")),
        line_number=_int_or_none(body.get("line-number")),
        disposition=_clip(body.get("disposition")),
    )


def _from_reporting_api_body(body: dict[str, Any]) -> CspViolation | None:
    """The Reporting API shape: camelCase, inside an envelope's `body`."""
    directive = _clip(body.get("effectiveDirective"))
    if directive is None:
        return None
    return CspViolation(
        effective_directive=directive.split(" ", 1)[0],
        blocked_origin=origin_only(body.get("blockedURL")),
        document_realm=document_realm(body.get("documentURL")),
        source_origin=origin_only(body.get("sourceFile")),
        line_number=_int_or_none(body.get("lineNumber")),
        disposition=_clip(body.get("disposition")),
    )


def parse_reports(payload: object) -> list[CspViolation]:
    """Every violation in one POST, stripped. Never raises on a shape it does not know.

    Both wire shapes are tried on every payload rather than being selected by the content
    type, because the content type is a header a sender chooses and the body is the thing
    we can actually read. A payload that is neither yields an empty list, which the caller
    counts and answers 204 to — an unauthenticated endpoint must not be an oracle for
    which JSON shapes it understands.
    """
    if isinstance(payload, dict):
        inner = payload.get("csp-report")
        if isinstance(inner, dict):
            found = _from_report_uri_body(inner)
            return [found] if found else []
        # A `report-to` sender that posted a bare envelope rather than an array.
        payload = [payload]
    if not isinstance(payload, list):
        return []
    violations: list[CspViolation] = []
    for envelope in payload[:MAX_REPORTS_PER_POST]:
        if not isinstance(envelope, dict):
            continue
        if envelope.get("type") not in (None, "csp-violation"):
            continue  # A Reporting API endpoint receives deprecation and NEL reports too.
        body = envelope.get("body")
        if isinstance(body, dict):
            found = _from_reporting_api_body(body) or _from_report_uri_body(body)
        else:
            found = _from_report_uri_body(envelope)
        if found:
            violations.append(found)
    return violations


def is_extension_noise(violation: CspViolation) -> bool:
    """A violation caused by something running in the user's own browser, not by us."""
    return scheme_of(violation.blocked_origin) in EXTENSION_SCHEMES


__all__ = [
    "BLOCKED_URI_KEYWORDS",
    "EXTENSION_SCHEMES",
    "MAX_FIELD_CHARS",
    "MAX_REPORTS_PER_POST",
    "CspViolation",
    "document_realm",
    "is_extension_noise",
    "origin_only",
    "parse_reports",
    "scheme_of",
]
