"""The egress guard: what a tenant may point our delivery worker at, and who we tell.

The defect this file pins. `POST /v1/integrations/endpoints` validated a tenant-supplied
URL as a `HttpUrl` and nothing else, and `integrations.service.deliver` signs a lead's
NAME AND PHONE NUMBER into a body and POSTs it wherever that URL says. Any tenant
`owner` could therefore register `http://169.254.169.254/latest/meta-data/` or an RFC
1918 address and get two things: an internal port scanner whose results are published
back to them on `GET /v1/integrations/deliveries`, and a PII egress channel into the
private network. Registration also wrote NO `audit_log` row while deactivation wrote
one — the act that starts lead PII leaving the tenant was the act with no record of who
performed it.

Four properties, and the third is the one that is easy to ship broken:

1. the guard judges the RESOLVED ADDRESS, not the spelling — so `http://2130706433/`,
   `http://0177.0.0.1/` and `http://[::ffff:127.0.0.1]/` are all refused without any of
   them being special-cased anywhere;
2. every refusal class says which one it is, so a client can act on it;
3. the check runs AGAIN immediately before the request, so a name that answered publicly
   at registration and privately afterwards (DNS rebinding) is refused at delivery —
   these tests assert the resolver was CONSULTED, because a guard test that passes
   because nothing was ever resolved proves nothing;
4. creating an endpoint writes an audit row naming the HOST — never the URL, whose query
   routinely carries the receiver's own API key.

The suite's session fixture (`tests/conftest.py::_reserved_test_domains_resolve`) makes
RFC 2606 reserved names resolve to one fixed PUBLIC address, so fixture URLs behave like
real public endpoints. Tests here override that per test to script the answer they need.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
import pytest
from apps.api.core.logging import JsonFormatter
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import egress_guard, service
from apps.api.integrations.egress_guard import EgressRefusedError, assert_public_http_url
from apps.api.integrations.routes import ENDPOINT_CREATED
from apps.api.main import app
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from arq import Retry
from sqlalchemy import text
from tests.api_security_test import _make_tenant

SECRET = "whsec_egress_guard_secret"
PUBLIC = "93.184.215.14"


class _Resolver:
    """A scripted resolver that REMEMBERS what it was asked.

    The memory is the point. Every assertion below about a refusal is paired with one
    about `calls`, because a guard that returned "refused" without ever looking up the
    host would pass a naive test while being exactly the bug — a string blocklist — that
    the resolved-address design exists to avoid.
    """

    def __init__(self, *answers: tuple[str, ...]) -> None:
        # One tuple per call; the last one repeats for any further calls, so a test that
        # scripts a single answer does not have to count the worker's attempts.
        self.answers = list(answers)
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> tuple[str, ...]:
        self.calls.append((host, port))
        index = min(len(self.calls) - 1, len(self.answers) - 1)
        return self.answers[index]


def _resolves(monkeypatch: pytest.MonkeyPatch, *answers: tuple[str, ...]) -> _Resolver:
    resolver = _Resolver(*answers)
    monkeypatch.setattr(egress_guard, "resolve_addresses", resolver)
    return resolver


def _deployed(monkeypatch: pytest.MonkeyPatch, env: str = "prod") -> None:
    """Run the guard as a DEPLOYED environment rather than a laptop.

    The suite itself runs under `APP_ENV=local`, where loopback is a legitimate
    destination on purpose (`egress_guard.loopback_is_allowed` argues why). Patching the
    settings rather than the predicate keeps the predicate itself under test — the
    relaxation and its boundary are both real code here, not a stub.
    """
    settings = get_settings().model_copy(update={"app_env": env})
    monkeypatch.setattr(egress_guard, "get_settings", lambda: settings)


# ------------------------------------------------------------- spelling vs address


@pytest.mark.parametrize(
    ("url", "spelling"),
    [
        ("http://2130706433/hook", "decimal"),
        ("http://0177.0.0.1/hook", "octal"),
        ("http://0x7f000001/hook", "hex"),
        ("http://[::ffff:127.0.0.1]/hook", "ipv4-mapped ipv6"),
        ("http://[::1]/hook", "ipv6 loopback"),
        ("http://localhost/hook", "name"),
    ],
)
async def test_every_spelling_of_this_machine_is_refused_because_the_address_is_judged(
    monkeypatch: pytest.MonkeyPatch, url: str, spelling: str
) -> None:
    """THE REAL RESOLVER, deliberately — no stub anywhere in this test.

    Every one of these is a documented SSRF filter bypass, and not one of them is
    special-cased in `egress_guard`. They are refused because glibc's `getaddrinfo`
    parses them with the same legacy `inet_aton` rules the connection would use, and the
    guard judges what comes back. A string filter has to know all six spellings (and the
    ones nobody has written down yet); this has to know none of them.
    """
    _deployed(monkeypatch)
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url(url)
    assert excinfo.value.code == "webhook_url_not_public", spelling
    assert "loopback" in excinfo.value.detail, spelling


async def test_the_guard_asks_the_resolver_for_the_host_and_port_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resolution is not incidental — it IS the check. A guard that decided from the
    string would leave this list empty and every refusal test above would still pass."""
    resolver = _resolves(monkeypatch, (PUBLIC,))
    vetted = await assert_public_http_url("https://Hooks.Crm.EXAMPLE/path?k=v")
    assert resolver.calls == [("hooks.crm.example", 443)], "lowercased host, scheme's port"
    assert vetted.host == "hooks.crm.example"
    assert vetted.addresses == (PUBLIC,)


# --------------------------------------------------- the parser, which is not the race
#
# D-129 weighed IP pinning against a TOCTOU window and kept the window. Underneath that
# trade was a hole needing no race at all: the guard decided the destination with
# `urlsplit` + `getaddrinfo` while the request was made by httpx, and the two do not
# encode a hostname the same way. `socket.getaddrinfo` runs a `str` host through the
# STDLIB `idna` codec (IDNA 2003); httpx runs it through the `idna` package (IDNA 2008 /
# UTS-46). Where they disagree, the name we vetted is not the name we connect to.


def test_the_two_idna_standards_really_do_disagree_and_this_is_the_premise() -> None:
    """THE MECHANISM, pinned separately from the behaviour.

    If a future interpreter or a future httpx makes these agree, the guard's parser check
    becomes a no-op — and a suite that only asserted "the guard refuses `faß…`" would go
    on passing while proving nothing. This test is the one that would go red and say the
    premise moved, which is the honest place to learn it.
    """
    ours = egress_guard._wire_host("faß.example.com")
    theirs = httpx.URL("https://faß.example.com/hook").raw_host
    assert ours == b"fass.example.com", "IDNA 2003 folds ß to ss — what our lookup asks for"
    assert theirs == b"xn--fa-hia.example.com", "IDNA 2008 keeps it — what httpx connects to"
    assert ours != theirs, "the whole reason the check below exists"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://crm.example/hook", (b"crm.example", 443)),
        ("http://crm.example/hook", (b"crm.example", 80)),
        ("https://crm.example:8443/hook", (b"crm.example", 8443)),
        # httpx drops a default port from `.port`; the comparison is against the port the
        # connection USES, so the default has to be filled back in or every plain
        # `https://host/` URL would look like a disagreement.
        ("https://crm.example:443/hook", (b"crm.example", 443)),
        ("https://faß.example.com/hook", (b"xn--fa-hia.example.com", 443)),
        # None means "the transport will not connect at all", which the caller must treat
        # as a refusal and never as agreement. Three ways to get there:
        ("http://0177.0.0.1/hook", None),  # httpx will not parse it
        ("https:///hook", None),  # parses, names no host
        ("gopher://crm.example/hook", None),  # a scheme with no port we know
    ],
)
def test_the_transport_target_is_read_off_the_transport_and_fails_closed(
    raw: str, expected: tuple[bytes, int] | None
) -> None:
    """Every branch of the thing the agreement check compares against.

    Unit-level on purpose: the last three are unreachable through
    `assert_public_http_url` — the scheme and host clauses refuse them earlier — so a
    behaviour test could never show that they answer None rather than something that
    would read as agreement. A fail-closed branch nobody exercises is a fail-open branch
    waiting for its first caller.
    """
    assert egress_guard._transport_target(raw) == expected


def test_a_host_we_cannot_encode_is_not_silently_treated_as_agreeing() -> None:
    """`_wire_host` returns None for a label the IDNA encoder rejects, and None can never
    equal a `(bytes, int)` tuple — so an unencodable host is a refusal by construction
    rather than by a clause somebody has to remember to write."""
    assert egress_guard._wire_host("a" * 64) is None
    assert egress_guard._wire_host("crm.example") == b"crm.example"


async def test_a_host_two_parsers_read_as_two_names_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bypass, end to end, with the attacker's own DNS scripted.

    `fass.example.com` is public (so the address judgement is satisfied and cannot be the
    thing doing the refusing) and `xn--fa-hia.example.com` is the attacker's — 127.0.0.1,
    never looked at, and where the lead would have gone. Deterministic: no TTL, no race,
    no second lookup. The refusal has to come from the parser check or not at all.
    """
    _deployed(monkeypatch)
    resolver = _resolves(monkeypatch, (PUBLIC,))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("https://faß.example.com/hook")
    assert excinfo.value.code == "webhook_url_ambiguous"
    assert resolver.calls == [("faß.example.com", 443)], (
        "the address WAS judged and passed — this refusal is the parser's, not the classifier's"
    )
    assert excinfo.value.as_problem()["fields"][0]["rule"] == "ambiguous"


async def test_a_url_the_transport_will_not_parse_is_refused_here_rather_than_thrown_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An embedded tab: `urlsplit` strips it (CPython does this deliberately, bpo-43882),
    httpx raises. Two reasons this must be OUR refusal:

    `httpx.InvalidURL` is NOT an `httpx.HTTPError` — asserted below rather than asserted
    about — so neither `deliver`'s `except httpx.HTTPError` nor `copy_recording`'s catches
    it. Left to the transport it is an unhandled exception on tenant- or vendor-supplied
    input: a 500 on one path and a dead worker job on the other.
    """
    assert not issubclass(httpx.InvalidURL, httpx.HTTPError), (
        "the reason this cannot be left to the caller's except clause"
    )
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("https://crm.example\t/hook")
    assert excinfo.value.code == "webhook_url_ambiguous"


async def test_an_ambiguous_destination_never_reaches_the_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asserted on what was ASKED. A refusal after the request is not a refusal, and a
    guard test that passes because no request was ever possible proves nothing — so the
    transport here is live and would have answered 200."""
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await service.deliver(
            url="https://faß.example.com/hook",
            secret=SECRET,
            event="lead.created",
            envelope={"id": str(uuid7()), "data": {"phone": "+919876500001"}},
            client=client,
        )

    assert asked == [], "the lead was posted to a host the guard never resolved"
    assert result.error == "webhook_url_ambiguous"
    assert result.transient is False and result.sent_body is None


async def test_a_label_too_long_to_encode_is_refused_and_is_not_a_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`UnicodeError` out of the resolver is refused, not raised past.

    A DNS label over 63 bytes makes `socket.getaddrinfo` raise from its IDNA encoder
    before a nameserver is contacted — and `UnicodeError` is a `ValueError`, NOT an
    `OSError`, so it used to walk straight past the fail-closed clause and out of the
    route as a 500. An unhandled exception on a tenant-supplied string is the defect class
    this whole module exists to remove rather than relocate.

    Scripted the way `test_a_name_we_cannot_resolve_fails_closed` scripts its `OSError`,
    and the FIRST assertion is why that substitution is honest: the error really is what
    the stdlib encoder raises for this host. Written as a `.example` URL against the real
    resolver instead, this test would have passed through the suite's session double —
    which answers reserved names without calling `getaddrinfo` at all — and proved nothing
    about the clause it is named after.
    """
    too_long = "a" * 64
    with pytest.raises(UnicodeError):
        f"{too_long}.example".encode("idna")

    async def encoder_refuses(host: str, port: int) -> tuple[str, ...]:
        raise UnicodeError("label empty or too long")

    monkeypatch.setattr(egress_guard, "resolve_addresses", encoder_refuses)
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url(f"https://{too_long}.example/hook")
    assert excinfo.value.code == "webhook_url_unresolvable"


async def test_what_was_vetted_is_the_string_that_is_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard trims before it parses, so a caller posting the UNTRIMMED original would
    hand httpx a string the guard never looked at. `VettedDestination.url` closes that by
    construction rather than by everyone remembering to `.strip()`."""
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await service.deliver(
            url="  https://crm.example/hooks/calevate  ",
            secret=SECRET,
            event="lead.created",
            envelope={"id": str(uuid7()), "data": {"lead_id": "1"}},
            client=client,
        )
    assert result.delivered is True
    assert asked == ["https://crm.example/hooks/calevate"]


async def test_a_public_ipv6_only_answer_is_a_destination_we_will_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every IPv6 case above is a REFUSAL, and a classifier that refused all of them would
    satisfy the lot. A name that answers only AAAA is ordinary and must still work."""
    _deployed(monkeypatch)
    _resolves(monkeypatch, ("2606:2800:220:1:248:1893:25c8:1946",))
    vetted = await assert_public_http_url("https://v6.example/hook")
    assert vetted.addresses == ("2606:2800:220:1:248:1893:25c8:1946",)


async def test_the_guard_vets_a_name_and_the_caller_connects_by_that_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE KNOWN LIMIT, asserted rather than only described.

    `egress_guard`'s PINNING paragraph says the residual is the gap between our
    `getaddrinfo` and httpx's — and that sentence is only true while callers connect by
    NAME. This pins both halves of it: the vetted addresses exist, and none of them is
    what goes on the wire. The day someone implements pinning, this test is what tells
    them the docstring is now wrong, which is the whole reason a limit gets a test rather
    than a paragraph.
    """
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json={"ok": True})

    vetted = await assert_public_http_url("https://crm.example/hook")
    assert vetted.addresses == (PUBLIC,), "an address WAS proved public"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await service.deliver(
            url="https://crm.example/hook",
            secret=SECRET,
            event="lead.created",
            envelope={"id": str(uuid7()), "data": {"lead_id": "1"}},
            client=client,
        )
    assert [r.url.host for r in asked] == ["crm.example"], "connected by name — the residual"
    assert PUBLIC not in str(asked[0].url), "and not by the address that was vetted"


# ------------------------------------------------------------------ refusal classes


@pytest.mark.parametrize(
    ("address", "rule", "phrase"),
    [
        ("169.254.169.254", "link_local", "link-local"),
        ("fe80::1", "link_local", "link-local"),
        ("10.0.0.1", "private", "private address"),
        ("192.168.1.50", "private", "private address"),
        ("172.16.9.9", "private", "private address"),
        ("fc00::1", "private", "private address"),
        ("127.0.0.1", "loopback", "loopback"),
        ("0.0.0.0", "unspecified", "unspecified"),
        ("239.1.1.1", "multicast", "multicast"),
        ("ff02::1", "multicast", "multicast"),
        # 240.0.0.0/4 is `is_private` AND `is_reserved` in Python; the more specific
        # category wins, which is why the order in `_CATEGORY_ORDER` is part of the
        # contract rather than an implementation detail.
        ("240.0.0.1", "private", "private address"),
        ("100.64.0.1", "not_globally_routable", "not routable"),
        ("2002:7f00:1::", "loopback", "loopback"),
        ("2002:a9fe:a9fe::", "link_local", "link-local"),
        ("::ffff:169.254.169.254", "link_local", "link-local"),
        ("64:ff9b::7f00:1", "reserved", "reserved"),
    ],
)
async def test_each_class_of_internal_address_is_refused_with_its_own_message(
    monkeypatch: pytest.MonkeyPatch, address: str, rule: str, phrase: str
) -> None:
    """One code the client can switch on, one sentence they can act on.

    The last four are the wrappers a single `is_global` test misses or answers wrongly:
    6to4 and IPv4-mapped carry an IPv4 destination inside an IPv6 address, and the NAT64
    well-known prefix reports `is_global == True` on this interpreter. Each is reported
    as what it actually reaches — `2002:a9fe:a9fe::` is the METADATA service, and saying
    "reserved" would hide that from the person who has to fix it.
    """
    _deployed(monkeypatch)
    _resolves(monkeypatch, (address,))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("https://receiver.example/hook")
    problem = excinfo.value.as_problem()
    assert problem["status"] == 422
    assert problem["type"].rsplit("/", 1)[-1] == "webhook_url_not_public"
    assert phrase in problem["detail"], problem["detail"]
    assert problem["fields"] == [{"field": "url", "rule": rule, "message": excinfo.value.detail}], (
        "the field and the class are both named, so a form can point at the box"
    )


async def test_one_private_answer_in_a_record_set_refuses_the_whole_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A name that answers with a public AND a private address is a rebinding attack that
    needs no second lookup — the connection picks. Every answer is vetted, not the first.
    """
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC, "10.1.2.3"))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("https://roundrobin.example/hook")
    assert excinfo.value.code == "webhook_url_not_public"
    assert "private" in excinfo.value.detail


async def test_a_public_destination_on_a_public_port_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legitimate case, asserted explicitly. A guard that refused everything would
    pass every other test in this file."""
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    for url in ("https://crm.example/hooks/calevate", "http://crm.example/hooks/calevate"):
        vetted = await assert_public_http_url(url)
        assert vetted.addresses == (PUBLIC,)
    assert (await assert_public_http_url("https://crm.example:443/h")).port == 443
    assert (await assert_public_http_url("http://crm.example:80/h")).port == 80


@pytest.mark.parametrize("port", [22, 6379, 8080, 5432, 3000])
async def test_a_port_that_is_not_80_or_443_is_refused(
    monkeypatch: pytest.MonkeyPatch, port: int
) -> None:
    """One accepted destination must not become a port sweep of an otherwise legitimate
    host, with the results published on the delivery screen."""
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url(f"https://crm.example:{port}/hook")
    assert excinfo.value.code == "webhook_url_port_not_allowed"
    assert str(port) in excinfo.value.detail


async def test_a_port_of_zero_is_refused_rather_than_becoming_the_scheme_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`urlsplit(...).port` returns 0 for `:0`, and `port or 443` would have vetted 443
    while the request went to a port nothing listens on. The guard must vet the port the
    request will use, or it is vetting a different destination."""
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("https://crm.example:0/hook")
    assert excinfo.value.code == "webhook_url_port_not_allowed"
    assert "Port 0" in excinfo.value.detail


async def test_an_address_we_cannot_parse_is_refused_and_not_a_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An answer we cannot read is an answer we cannot vet.

    `getaddrinfo` can return a scoped form and a resolver can be replaced; letting the
    `ValueError` escape would turn a tenant-controlled URL into an unhandled exception,
    which is the shape of defect this module exists to remove rather than relocate.
    """
    _deployed(monkeypatch)
    _resolves(monkeypatch, ("not-an-address",))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("https://weird.example/hook")
    assert excinfo.value.code == "webhook_url_not_public"


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "gopher://crm.example/x", "ftp://crm.example/x", "crm.example"]
)
async def test_only_http_and_https_can_receive_a_lead(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    resolver = _resolves(monkeypatch, (PUBLIC,))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url(url)
    assert excinfo.value.code == "webhook_url_scheme_not_allowed"
    assert resolver.calls == [], "a scheme we will never speak is refused before any lookup"


def test_the_codes_the_integration_contract_publishes_are_the_codes_we_raise() -> None:
    """docs/WEBHOOKS.md §1.6 tells a client exactly which refusals to expect, and a
    published error code is part of the contract. Renaming one without the doc leaves a
    client switching on a string we no longer send — the same class of silent drift the
    docs-drift guardrail exists for, one level below what it can see.
    """
    import pathlib

    contract = pathlib.Path("docs/WEBHOOKS.md").read_text(encoding="utf-8")
    source = pathlib.Path("apps/api/integrations/egress_guard.py").read_text(encoding="utf-8")
    for code in (
        "webhook_url_not_public",
        "webhook_url_port_not_allowed",
        "webhook_url_unresolvable",
    ):
        assert code in contract, f"{code} is raised but not published"
        assert f'code="{code}"' in source, f"{code} is published but not raised"


def test_the_resolver_seam_is_substituted_by_tests_and_by_nothing_that_ships() -> None:
    """`resolve_addresses` exists as a module-level function so a test can replace it, and
    a seam is only safe while nothing in the shipped tree uses it as one.

    Asserted over `apps/` rather than argued: `conftest`'s session fixture and this file
    are the substitution sites, and a monkeypatch is a test tool. A production module
    reaching for this name would be a bypass wearing a seam's clothes — the "bypass for
    testing" hard rule 5 forbids in those words, arriving from the other direction.
    """
    import pathlib

    callers = sorted(
        str(path)
        for path in pathlib.Path("apps").rglob("*.py")
        if path.name != "egress_guard.py" and "resolve_addresses" in path.read_text("utf-8")
    )
    assert callers == [], f"the resolver seam is reachable from shipped code: {callers}"


async def test_a_name_we_cannot_resolve_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The half an attacker would otherwise control: whether we look at all.

    NXDOMAIN on our lookup and an A record on httpx's is a rebinding attack with an extra
    step, so a name we cannot vet is refused rather than attempted. Same doctrine as
    `parse_source_ip_allowlist` and `engine_intake.client_ip`.
    """

    async def refuse(host: str, port: int) -> tuple[str, ...]:
        raise OSError("Name or service not known")

    monkeypatch.setattr(egress_guard, "resolve_addresses", refuse)
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("https://nowhere.example/hook")
    assert excinfo.value.code == "webhook_url_unresolvable"


async def test_a_resolver_that_answers_with_nothing_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty answer is not a public answer. Without this the `for` loop below it runs
    zero times and an empty tuple sails through as "no bad addresses found"."""
    _resolves(monkeypatch, ())
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("https://empty.example/hook")
    assert excinfo.value.code == "webhook_url_unresolvable"


# ------------------------------------------------------------- the local exemption


async def test_localhost_works_for_development_and_only_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A developer's own receiver is a legitimate destination; their office LAN is not.

    Both halves are asserted because both are decisions: `127.0.0.1` is "this machine",
    which the person running the code indisputably controls, and the port rule goes with
    it because a dev receiver is on 9000. `192.168.x` is the shared network this guard
    exists to protect, and it stays refused even here.
    """
    _deployed(monkeypatch, env="local")
    _resolves(monkeypatch, ("127.0.0.1",))
    vetted = await assert_public_http_url("http://localhost:9000/hook")
    assert vetted.port == 9000, "a dev receiver is not on port 80"

    _resolves(monkeypatch, ("192.168.1.50",))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("http://nas.example/hook")
    assert excinfo.value.code == "webhook_url_not_public"

    _resolves(monkeypatch, ("169.254.169.254",))
    with pytest.raises(EgressRefusedError) as excinfo:
        await assert_public_http_url("http://metadata.example/hook")
    assert excinfo.value.code == "webhook_url_not_public", "metadata is refused on a laptop too"


async def test_the_same_localhost_is_refused_once_it_is_deployed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exemption is `APP_ENV=local` and nothing else — the boundary, not the branch."""
    _resolves(monkeypatch, ("127.0.0.1",))
    for env in ("staging", "prod"):
        _deployed(monkeypatch, env=env)
        with pytest.raises(EgressRefusedError) as excinfo:
            await assert_public_http_url("http://localhost:9000/hook")
        assert excinfo.value.code == "webhook_url_not_public", env
        assert "loopback" in excinfo.value.detail


async def test_a_public_host_mixed_with_loopback_is_refused_even_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exemption covers a name that is ONLY loopback. A record set holding both is
    the rebinding shape, and letting it through locally would make the local path a
    different program from the deployed one."""
    _deployed(monkeypatch, env="local")
    _resolves(monkeypatch, ("127.0.0.1", PUBLIC))
    with pytest.raises(EgressRefusedError):
        await assert_public_http_url("http://mixed.example/hook")


# ------------------------------------------------------- the connect-time re-check


async def _endpoint(url: str) -> tuple[uuid.UUID, uuid.UUID]:
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Egress Clinic",
        slug=f"egress-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = created["id"]
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, :secret, "
                "ARRAY['lead.created'], true, now(), now())"
            ),
            {"id": endpoint_id, "tid": tenant_id, "url": url, "secret": SECRET},
        )
    return tenant_id, endpoint_id


async def test_a_name_that_rebinds_after_registration_is_refused_at_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE POINT OF THE WHOLE PART.

    The endpoint row can be months old and the tenant owns the DNS for the name in it, so
    a registration-time check alone is defeated by answering publicly once and privately
    afterwards. The resolver here does exactly that: the first lookup (registration) is
    `93.184.215.14`, every later one is `127.0.0.1`.

    Asserted three ways, because each could be true without the others: the registration
    SUCCEEDS (so the refusal is not "we refuse everything"), the delivery is refused with
    the guard's own code, and the resolver was consulted MORE THAN ONCE (so the refusal
    came from a fresh lookup rather than from a cached verdict).
    """
    resolver = _resolves(monkeypatch, (PUBLIC,), ("127.0.0.1",))
    _deployed(monkeypatch)
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "apps.workers.outbound_webhooks.alert", lambda stage, code, **kw: fired.append((code, kw))
    )

    vetted = await assert_public_http_url("https://rebind.example/hook")
    assert vetted.addresses == (PUBLIC,), "registration passes — the name looked public"
    tenant_id, endpoint_id = await _endpoint("https://rebind.example/hook")

    delivery_id = uuid7()
    outcome = await deliver_outbound_webhook(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": "lead.created",
            "data": {"lead_id": "1", "phone": "+919876500001", "name": "Priya"},
            "delivery_id": str(delivery_id),
        },
    )

    assert len(resolver.calls) >= 2, "the destination was re-resolved at delivery, not trusted"
    assert resolver.calls[-1] == ("rebind.example", 443)
    assert outcome == "rejected webhook_url_not_public"
    assert [code for code, _ in fired] == ["outbound_webhook_exhausted"]
    assert "permanent" in fired[0][1]["detail"], "a rebound host is not a blip; do not retry"

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, reason, attempts FROM webhook_deliveries WHERE id = :id"),
                {"id": delivery_id},
            )
        ).first()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "webhook_url_not_public", "the client's own screen says why, in our vocabulary"


async def test_a_refused_destination_never_reaches_the_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No bytes on a socket, no body composed, and no exception out of `deliver`.

    `deliver`'s contract is that it raises nothing, so the refusal has to arrive as a
    `DeliveryResult` — and `sent_body` must stay None, because the delivery-body
    retention would otherwise file a copy of a lead's personal data against a delivery
    that never happened.
    """
    _deployed(monkeypatch)
    _resolves(monkeypatch, ("169.254.169.254",))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await service.deliver(
            url="https://metadata.example/hook",
            secret=SECRET,
            event="lead.created",
            envelope={"id": str(uuid7()), "data": {"phone": "+919876500001"}},
            client=client,
        )

    assert seen == [], "a caller-supplied client is not a way around the guard"
    assert result.delivered is False
    assert result.error == "webhook_url_not_public"
    assert result.transient is False, "it will resolve to the same private address in 30s"
    assert result.sent_body is None, "nothing was composed, so there is nothing to retain"


async def test_a_redirect_is_not_followed_even_when_the_client_was_built_to_follow_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the pair the guard depends on.

    A vetted address is vetted for ONE hop: a 307 re-sends the signed body and our
    headers to whatever host `Location` names, which is an SSRF with the guard's own
    approval stamp on it. `deliver` passes `follow_redirects=False` on the REQUEST as
    well as on the client it builds, and this is the assertion that distinguishes the
    two — the client here is constructed to follow redirects, which is precisely the
    caller `deliver` must not trust.
    """
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "crm.example":
            return httpx.Response(307, headers={"Location": "http://169.254.169.254/latest/"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        result = await service.deliver(
            url="https://crm.example/hook",
            secret=SECRET,
            event="lead.created",
            envelope={"id": str(uuid7()), "data": {"lead_id": "1"}},
            client=client,
        )

    assert [r.url.host for r in seen] == ["crm.example"], "the redirect was not followed"
    assert result.delivered is False and result.status_code == 307


# ------------------------------------------------------------------- registration


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _rows(tenant_id: uuid.UUID) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list((await session.execute(text("SELECT url FROM outbound_webhooks"))).all())


async def _audit(tenant_id: uuid.UUID) -> list[tuple[str, str, str | None]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, object_type, ip FROM audit_log WHERE tenant_id = :t ORDER BY at"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), str(r[1]), None if r[2] is None else str(r[2])) for r in rows]


async def test_registering_an_internal_destination_is_refused_and_stores_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over HTTP, end to end: 422 problem+json, no endpoint row, and no audit row either.

    The stored-nothing half matters as much as the refusal. A row written before the
    check would be delivered from by the worker on the next lead, and a refusal that
    still audited would fill the ledger with attempts rather than acts.
    """
    _deployed(monkeypatch)
    _resolves(monkeypatch, ("169.254.169.254",))
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        refused = await http.post(
            "/v1/integrations/endpoints",
            json={"url": "http://metadata.example/latest/meta-data/", "events": ["lead.created"]},
            headers=_headers(slug, token),
        )

    assert refused.status_code == 422, refused.text
    assert refused.headers["content-type"].startswith("application/problem+json")
    problem = refused.json()
    assert problem["type"].rsplit("/", 1)[-1] == "webhook_url_not_public"
    assert problem["fields"][0]["field"] == "url"
    assert await _rows(tenant_id) == [], "nothing was stored to deliver from later"
    assert await _audit(tenant_id) == [], "a refused attempt is not an act to record"


async def test_registering_a_real_endpoint_is_audited_and_records_the_host_never_the_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 6 applied to our own ledger.

    Registration is the act that starts a client's lead PII leaving their tenant, and it
    wrote nothing while the DELETE that stops the flow wrote a row. It writes one now —
    in the same transaction as the INSERT, so an endpoint cannot exist without it.

    What the row may carry is the second half. A webhook URL's path and query are
    tenant-authored free text and routinely hold the receiver's own bearer credential;
    this fixture URL carries one on purpose. The summary names the HOST, which is the
    fact an investigator needs, and the credential appears nowhere.
    """
    tenant_id, slug, token = await _make_tenant()
    url = "https://hooks.crm.example.com/calevate?apikey=super-secret-value"
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            created = await http.post(
                "/v1/integrations/endpoints",
                json={"url": url, "events": ["lead.created"]},
                headers=_headers(slug, token),
            )
    assert created.status_code == 201, created.text

    assert await _audit(tenant_id) == [(ENDPOINT_CREATED, "outbound_webhook", "127.0.0.1")]

    summaries = [r for r in caplog.records if r.getMessage() == "audit"]
    assert summaries, "the summary is what carries the destination; it must be emitted"
    summary = summaries[-1]
    assert summary.host == "hooks.crm.example.com"  # type: ignore[attr-defined]
    assert summary.port == 443  # type: ignore[attr-defined]
    assert summary.kind == service.WEBHOOK_KIND  # type: ignore[attr-defined]
    # Through `JsonFormatter`, which is where `redact_mapping` actually runs — reading the
    # LogRecord alone would pass for a field shipping "[1 items]", which is what this
    # summary used to carry. Half of "where did the leads go" is WHICH events go there.
    emitted = json.loads(JsonFormatter().format(summary))
    assert emitted["events"] == "lead.created", emitted
    rendered = str(summary.__dict__)
    assert "super-secret-value" not in rendered, "the query is a credential, not an audit field"
    assert "/calevate?" not in rendered, "the path is not recorded either — the host is the fact"


async def test_a_sheets_endpoint_is_audited_by_the_same_action(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The other create route had the identical gap. One action for both, so "who pointed
    our leads outward, and where" does not depend on knowing which form was used.

    No SSRF check on this path, deliberately: `parse_spreadsheet_ref` has already reduced
    the input to a document id, delivery goes to Google's API, and nothing a client typed
    reaches a socket — so the destination recorded is the document, not a host.
    """
    from apps.api.integrations import routes as integration_routes

    monkeypatch.setattr(integration_routes, "sheets_delivery_available", lambda: True)
    # Google's own documented sample id. Deliberately a REAL-SHAPED one rather than a
    # made-up string of digits: `redact_mapping` masks phone-shaped digit runs on the way
    # into the log stream, so an id that happens to carry nine consecutive digits comes
    # back as `…[phone]…`. That is the shared sanitizer being conservative in the right
    # direction and it is not loosened for this field — the endpoint row still holds the
    # id in full — but a fixture built out of `0123456789` would have been asserting the
    # masker's threshold rather than the audit.
    sheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    tenant_id, slug, token = await _make_tenant()
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            created = await http.post(
                "/v1/integrations/endpoints/sheets",
                json={
                    "spreadsheet": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
                    "events": ["lead.created"],
                },
                headers=_headers(slug, token),
            )
    assert created.status_code == 201, created.text
    assert await _audit(tenant_id) == [(ENDPOINT_CREATED, "outbound_webhook", "127.0.0.1")]

    summary = [r for r in caplog.records if r.getMessage() == "audit"][-1]
    assert summary.kind == service.SHEET_KIND  # type: ignore[attr-defined]
    assert summary.spreadsheet_id == sheet_id  # type: ignore[attr-defined]


async def test_the_audit_row_and_the_endpoint_commit_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One transaction, so neither can exist without the other.

    Asserted by breaking the audit write and checking the ENDPOINT is gone too: if the
    row were written in a second transaction, the endpoint would survive its own failed
    audit and the ledger would be missing exactly the registrations that went wrong.
    """
    from apps.api.integrations import routes as integration_routes

    async def explode(*a: Any, **kw: Any) -> None:
        raise RuntimeError("audit chain unavailable")

    monkeypatch.setattr(integration_routes, "write_audit", explode)
    tenant_id, slug, token = await _make_tenant()
    # `raise_app_exceptions=False`: Starlette's `ServerErrorMiddleware` renders the 500
    # and then RE-RAISES, which is how an operator gets a traceback in the log. The
    # transport default would hand us that exception instead of the response, and the
    # response is what a client sees.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http:
        response = await http.post(
            "/v1/integrations/endpoints",
            json={"url": "https://crm.example/hook", "events": ["lead.created"]},
            headers=_headers(slug, token),
        )
    assert response.status_code == 500, response.text
    assert await _rows(tenant_id) == [], "the endpoint rolled back with its audit row"


# ------------------------------------------------------------------ the legitimate case


async def test_a_real_public_endpoint_still_registers_and_still_delivers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole feature, unbroken. Every other test here asserts a refusal, and a guard
    that refused everything would satisfy all of them."""
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        created = await http.post(
            "/v1/integrations/endpoints",
            json={"url": "https://crm.example/hooks/calevate", "events": ["lead.created"]},
            headers=_headers(slug, token),
        )
    assert created.status_code == 201, created.text
    endpoint_id = uuid.UUID(str(created.json()["id"]))

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    real = service.deliver

    async def routed(**kwargs: Any) -> service.DeliveryResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await real(**{**kwargs, "client": client})

    monkeypatch.setattr(service, "deliver", routed)
    outcome = await deliver_outbound_webhook(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": "lead.created",
            "data": {"lead_id": "1", "name": "Priya"},
            "delivery_id": str(uuid7()),
        },
    )
    assert outcome == "delivered 200"
    assert [r.url.host for r in seen] == ["crm.example"]


async def test_a_transient_delivery_failure_is_still_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must not have flattened the retry ladder. A 503 from a vetted public
    endpoint is a blip and still climbs it; only the REFUSAL is permanent."""
    _deployed(monkeypatch)
    _resolves(monkeypatch, (PUBLIC,))
    monkeypatch.setattr("apps.workers.outbound_webhooks.alert", lambda *a, **kw: None)
    tenant_id, endpoint_id = await _endpoint("https://flaky.example/hook")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    real = service.deliver

    async def routed(**kwargs: Any) -> service.DeliveryResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await real(**{**kwargs, "client": client})

    monkeypatch.setattr(service, "deliver", routed)
    with pytest.raises(Retry):
        await deliver_outbound_webhook(
            {"job_try": 1},
            {
                "tenant_id": str(tenant_id),
                "endpoint_id": str(endpoint_id),
                "event": "lead.created",
                "data": {"lead_id": "1"},
                "delivery_id": str(uuid7()),
            },
        )
