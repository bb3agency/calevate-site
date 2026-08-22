"""The app's routes and the edge's policy, pinned to each other (D-168).

`docs/evidence/raghava-deploy-teardown.md` §9 row 19 asks for our version of one test in
the reference project: theirs asserts that every multipart admin route appears in nginx's
`auth_request` exemption list, so a new upload route cannot be born broken at the edge
(`backend/nginx/client.conf.template:243-248`).

THEIR EXACT TEST HAS NO SUBJECT HERE. We have no `auth_request` anywhere — the
maintenance gate is a deliberate, documented gap (DEPLOYMENT §5, teardown §9 row 16) — and
no route in this repository takes a multipart upload. Writing their assertion would mean
inventing both sides of it, which is worse than not writing it.

WHAT WE HAVE INSTEAD is the same class of coupling with both halves already real: three
places where a fact about the application is ALSO written down in `infra/nginx/`, and
where the two drifting apart produces a failure that no test, no health check and no
deploy step can see. Each one below is a different direction of that drift.

Read-only over `infra/`: this file parses the template and asserts against it. If a check
here fails, the fix may well be in the template rather than in the app — the failure
message says which side it read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from apps.api.core.middleware import MAX_BODY_BYTES
from apps.api.core.rbac import iter_api_routes
from apps.api.main import app as api_app
from calevate_shared.config import SELECTABLE_ENGINES
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from tests.nginx_hooks_vhost_test import _server_blocks

REPO_ROOT = Path(__file__).resolve().parent.parent
NGINX_TEMPLATE = REPO_ROOT / "infra" / "nginx" / "calevate.conf.template"


@dataclass(frozen=True, slots=True)
class Location:
    modifier: str  # "", "=", "^~", "~"
    path: str
    body: str

    @property
    def proxies(self) -> bool:
        return "proxy_pass" in self.body

    @property
    def refuses(self) -> bool:
        return bool(re.search(r"\breturn\s+404\b", self.body))


@dataclass
class ServerBlock:
    names: tuple[str, ...] = ()
    locations: list[Location] = field(default_factory=list)
    max_body: str | None = None


_COMMENT = re.compile(r"#.*$")
_SERVER_NAME = re.compile(r"\bserver_name\s+([^;]+);")
_MAX_BODY = re.compile(r"\bclient_max_body_size\s+([^;]+);")
_LOCATION = re.compile(r"\blocation\s+(=|\^~|~\*?|)\s*(\S+)\s*\{")


def _strip_comments(text: str) -> str:
    return "\n".join(_COMMENT.sub("", line) for line in text.splitlines())


def _braced_body(text: str, opening: int) -> str:
    """The text between `text[opening] == '{'` and its matching brace.

    Depth-counted rather than "up to the next `}`", because a location may legitimately
    contain one (`if (...) { ... }`), and a body that stopped at the first closing brace
    would report a `proxy_pass` sitting after it as belonging to the NEXT location.
    """
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    return text[opening + 1 :]


def parse_server_blocks(text: str) -> list[ServerBlock]:
    """The template's `server { … }` blocks, each with its names, locations and body cap.

    THE BLOCK SPLITTER IS `nginx_hooks_vhost_test._server_blocks`, imported rather than
    rewritten. That file already answers "which server block is this line in" for a
    different question (no `/healthz` on `hooks.` may reach an upstream), and two brace
    counters over one file is the kind of second implementation this repo treats as a
    defect even when both work. What is added here is STRUCTURE — names, locations with
    their modifiers, the body cap — which its assertions do not need.

    Comments are stripped first: this template documents its own traps at length, and
    several of those paragraphs quote `location` lines that are not directives.
    """
    return [
        ServerBlock(
            names=tuple(match.group(1).split()) if (match := _SERVER_NAME.search(body)) else (),
            locations=[
                Location(
                    found.group(1),
                    found.group(2),
                    _braced_body(body, found.end() - 1),
                )
                for found in _LOCATION.finditer(body)
            ],
            max_body=cap.group(1).strip() if (cap := _MAX_BODY.search(body)) else None,
        )
        for body in _server_blocks(_strip_comments(text))
    ]


def blocks() -> list[ServerBlock]:
    return parse_server_blocks(NGINX_TEMPLATE.read_text(encoding="utf-8"))


def block_for(host: str) -> ServerBlock:
    """The TLS server block serving one subdomain. The port-80 redirect block names all
    four and proxies nothing, so it is excluded by requiring at least one location that
    proxies."""
    matches = [
        b
        for b in blocks()
        if any(name.startswith(f"{host}.") for name in b.names)
        and any(loc.proxies for loc in b.locations)
    ]
    assert len(matches) == 1, (
        f"expected exactly one proxying server block for {host}., got {matches}"
    )
    return matches[0]


def api_paths() -> set[str]:
    return {route.path for route in iter_api_routes(api_app)}


def voice_paths() -> set[str]:
    """Voice-runtime's mounted routes, from the app OBJECT rather than from its source.

    `from main import app` is how this repo already reaches that service in a test
    (`tests/engine_event_ordering_test.py`, `tests/ingest_ordering_test.py`):
    `apps/voice-runtime` is on the pytest path (`pyproject.toml::pythonpath`, D-18).
    """
    return {route.path for route in iter_api_routes(voice_app)}


def _size_to_bytes(value: str) -> int:
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    suffix = value[-1].lower()
    return int(value[:-1]) * units[suffix] if suffix in units else int(value)


# --- 1. the URL we hand the VENDOR must resolve on the deployable `hooks.` points at ----


def test_the_published_webhook_url_is_a_route_voice_runtime_serves() -> None:
    """The one drift here that loses data rather than requests.

    `agents/service._to_config` bakes `{webhook_base_url}/hooks/v1/engine/{engine}` into
    every agent's engine-side config at publish time, and `webhook_base_url` is
    `hooks.calevate.tech`, whose nginx block proxies to VOICE-RUNTIME. So that path is a
    contract between two deployables written down in a third place, and if it stops
    matching, the engine posts every call's outcome to a 404 — with no retry (D-31), no
    error on our side, and nothing but the ten-minute reconciliation poller between us and
    a lost lead. Asserted by CALLING the composer, not by grepping for the literal: a
    string search would pass on a copy that had moved into a comment.
    """
    from apps.api.agents.service import _to_config

    agent: dict[str, object] = {
        "id": uuid4(),
        "name": "Reception",
        "direction": "inbound",
        "language_primary": "te",
        "prompt": "You answer the clinic's phone.",
        "ai_disclosure_line": "This is an AI assistant.",
        "ai_disclosure_enabled": True,
        "recording_notice_line": "This call is recorded.",
        "recording_notice_enabled": True,
        "stt_provider": "sarvam",
        "stt_model": "saaras:v2",
        # NULL at both model rungs — the state every agent is in until somebody chooses,
        # and now the only state this fixture could describe: `ck_agents_llm_model_allowed`
        # (D-454) admits NULL or an allow-listed identifier, and `sarvam-m`, which stood
        # here, is neither.
        "llm_model": None,
        "organization_llm_model": None,
        "tts_provider": "sarvam",
        "tts_voice": "anushka",
        "max_call_duration_s": 600,
    }
    published = urlsplit(_to_config(uuid4(), agent).webhook_url).path
    served = voice_paths()
    assert any(
        published == route.replace("{engine}", engine)
        for route in served
        for engine in SELECTABLE_ENGINES
    ), (
        f"the engine callback URL publishes {published!r}, which voice-runtime does not "
        f"serve ({sorted(served)}). hooks.calevate.tech proxies to voice-runtime "
        "(infra/nginx/calevate.conf.template), so a mismatch is an at-most-once feed "
        "delivered to a 404."
    )


# --- 2. nothing the edge refuses is a route the app means to serve ---------------------


def test_no_voice_runtime_route_is_shadowed_by_the_edge_except_health() -> None:
    """Direction: APP → EDGE, which is the direction the reference's test guards too.

    The hooks vhost answers `^~ /healthz` with a 404 on purpose — the health routes are
    served on the loopback for the deploy poll and compose's healthcheck, and publishing
    them here dragged `httpx` and the engine adapter onto the event loop that has 500ms to
    ack (its comment carries the measurement). Every OTHER route this service mounts must
    reach it. A new route under a refused prefix would be a 404 in production and a 200 in
    every test, which is precisely the shape of failure a route list living in two places
    produces.
    """
    refused = [loc for loc in block_for("hooks").locations if loc.refuses]
    assert refused, "the hooks vhost refuses nothing — has the template moved?"
    shadowed = {
        path
        for path in voice_paths()
        for loc in refused
        if path == loc.path or path.startswith(loc.path.rstrip("/") + "/")
    }
    assert shadowed == {"/healthz", "/healthz/live", "/healthz/ready"}, (
        f"the edge 404s {sorted(shadowed)}. Only the health routes are deliberately "
        "loopback-only; anything else here is a route the app serves and the internet "
        "cannot reach."
    )


# --- 3. every policy prefix at the edge still names a route that exists -----------------


def test_every_edge_location_prefix_is_a_path_the_api_serves() -> None:
    """Direction: EDGE → APP, and the one the reference project got wrong.

    Each explicit `location` on the api vhost exists to give a path family its own
    `limit_req` zone — `/v1/auth/` at 20r/m, `/v1/admin/` at 180r/m, `/healthz` at 60r/m.
    Rename the route family and the zone keeps matching nothing: the config still reads
    like protection, the routes fall through to the general zone, and nobody finds out
    because nothing errors. `tests/rate_limit_census_test.py` already enforces this
    property for the APP's own limiter table; this is the same rule one layer out.
    """
    served = api_paths()
    for loc in block_for("api").locations:
        if not loc.proxies or loc.path == "/":
            continue
        if loc.modifier == "=":
            assert loc.path in served, (
                f"nginx pins an exact location {loc.path!r} the api does not serve"
            )
            continue
        prefix = loc.path
        assert any(path == prefix.rstrip("/") or path.startswith(prefix) for path in served), (
            f"nginx gives {prefix!r} its own rate zone, and the api serves no route under "
            "it. Either the routes moved and the zone is now a fossil, or the prefix is a "
            "typo — both leave that traffic in the general zone."
        )


# --- 4. the edge must never answer a request the app was going to explain ---------------


@pytest.mark.parametrize("host", ["api", "app", "admin", "hooks"])
def test_edge_body_cap_is_never_smaller_than_the_app_cap(host: str) -> None:
    """`BodyLimitMiddleware` refuses an oversized body with a problem+json naming the
    limit; nginx refuses one with a bare HTML 413 and no correlation id. Which of the two
    a caller meets is decided by two numbers written in different repositories' worth of
    context — `core/middleware.MAX_BODY_BYTES` and `client_max_body_size` — and only one
    ordering keeps the error part of our interface (CLAUDE.md).

    `core/ratelimit.py`'s docstring records that this pair was already misdescribed once:
    it claimed the edge applied the 2 MiB cap, and it does not.
    """
    cap = block_for(host).max_body
    assert cap is not None, f"{host}. declares no client_max_body_size"
    assert _size_to_bytes(cap) >= MAX_BODY_BYTES, (
        f"{host}. caps bodies at {cap}, below the app's own {MAX_BODY_BYTES} bytes — the "
        "edge would answer with a bare 413 before the app could explain the limit."
    )


# --- the parser itself, because a silent no-op is the failure mode here -----------------


def test_the_template_parses_into_the_blocks_this_file_assumes() -> None:
    """If `infra/nginx/` is restructured, THIS fails first and says so, rather than the
    three checks above quietly passing over an empty location list."""
    parsed = blocks()
    hosts = {name.split(".")[0] for b in parsed for name in b.names}
    assert {"api", "app", "admin", "hooks"} <= hosts, (
        f"{NGINX_TEMPLATE} parsed into server blocks for {sorted(hosts)}; the four "
        "subdomains this file reasons about are DEPLOYMENT §1's topology. Either the "
        "template moved or this parser no longer understands it — the checks in this file "
        "are inert until that is settled."
    )
    assert all(b.locations for b in parsed), "a server block parsed with no locations"


def test_parser_attributes_locations_to_the_right_server() -> None:
    """A negative control for the parser, so a bug that empties it cannot make every
    assertion above vacuously true."""
    parsed = parse_server_blocks(
        "server {\n"
        "  server_name one.example;\n"
        "  client_max_body_size 5m;\n"
        "  location ^~ /a/ { proxy_pass http://x; }\n"
        "}\n"
        "server {\n"
        "  server_name two.example;\n"
        "  location = /b { return 404; }\n"
        "}\n"
    )
    assert [b.names for b in parsed] == [("one.example",), ("two.example",)]
    assert [loc.path for b in parsed for loc in b.locations] == ["/a/", "/b"]
    assert parsed[0].locations[0].proxies and not parsed[0].locations[0].refuses
    assert parsed[1].locations[0].refuses
    assert parsed[0].max_body == "5m"
