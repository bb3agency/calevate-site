"""The streaming budget, pinned to nginx's number rather than to a comment.

`tests/assist_deadline_test.py` exists because `2 * ASSIST_TIMEOUT_S +
ASSIST_ROUTE_RESERVE_S` and `proxy_read_timeout` are two numbers in two languages in two
files that no build step relates. This route's budget is a DIFFERENT relationship to the
same nginx number — a stream is bounded by the gap between reads, not by its total length —
and the argument is worth exactly as little as the assist one was until something asserts
it.

WHAT WOULD HAVE HAPPENED WITHOUT THIS FILE: `TOTAL_BUDGET_S` is 90 and the api vhost's
`proxy_read_timeout` is 60. A reader who knew only `assist_deadline_test.py`'s arithmetic
would call that a defect and "fix" it by cutting the copilot's budget to under a minute,
which would cap a legitimate four-turn answer for no reason. The keep-alive interval is why
it is not a defect, and it lives inside an installed library where nobody would look.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.sse import _PING_INTERVAL

from apps.api.copilot import service

TEMPLATE = Path(__file__).resolve().parents[3] / "infra" / "nginx" / "calevate.conf.template"

_READ_TIMEOUT = re.compile(r"^\s*proxy_read_timeout\s+(\d+)(s|m)?\s*;", re.MULTILINE)


def _api_server_block() -> str:
    """The `api.` TLS server block, by brace depth. Lifted from
    `tests/assist_deadline_test.py` deliberately rather than imported: that file's helper
    is private to its own argument, and a shared parser would make one edit able to weaken
    two independent deadlines at once."""
    config = TEMPLATE.read_text(encoding="utf-8")
    for match in re.finditer(r"\bserver\s*\{", config):
        depth, index = 0, match.end() - 1
        while index < len(config):
            if config[index] == "{":
                depth += 1
            elif config[index] == "}":
                depth -= 1
                if depth == 0:
                    body = config[match.end() : index]
                    if "server_name api." in body and "listen 443" in body:
                        return body
                    break
            index += 1
    raise AssertionError("no api. TLS server block in calevate.conf.template")


def _proxy_read_timeout_s() -> float:
    matches = _READ_TIMEOUT.findall(_api_server_block())
    assert len(matches) == 1, (
        f"expected exactly one proxy_read_timeout in the api vhost, found {len(matches)}"
    )
    value, unit = matches[0]
    return float(value) * (60.0 if unit == "m" else 1.0)


def test_the_sse_keepalive_fits_inside_the_edge_read_timeout() -> None:
    """WHAT ACTUALLY BOUNDS A STREAM. `proxy_read_timeout` is the gap between two
    successive reads from the upstream, and FastAPI's SSE writer emits a `: ping` comment
    after `_PING_INTERVAL` seconds of producer silence — so the edge never waits longer
    than that even while a model is thinking.

    FAILS IF: the api vhost's `proxy_read_timeout` is lowered under FastAPI's ping
    interval, or a FastAPI upgrade raises that interval past it. The second is the one a
    reviewer would never look for, which is why the number is read out of the installed
    library rather than written down here.
    """
    assert _proxy_read_timeout_s() > _PING_INTERVAL


def test_the_per_frame_idle_budget_also_fits() -> None:
    """Our own read timeout on the UPSTREAM leg has to be shorter than the edge's on OURS,
    or the edge gives up on us before we give up on Azure — and the person gets a 504
    instead of the authored `copilot_interrupted` problem body."""
    assert _proxy_read_timeout_s() > service.STREAM_IDLE_S


def test_the_total_budget_is_deliberately_longer_than_the_edge_read_timeout() -> None:
    """AN ASSERTION IN THE UNUSUAL DIRECTION, because the property worth pinning is that
    somebody understood the difference. A four-turn tool-calling answer can legitimately
    outlast 60s of wall clock; it cannot legitimately go 60s without a byte. Cutting
    `TOTAL_BUDGET_S` to fit under the proxy would cap real answers for a constraint that
    does not apply to a stream.

    FAILS IF: somebody "fixes" the budget by making it smaller than the proxy timeout — at
    which point they should delete this test and say why in the commit, not quietly change
    the number.
    """
    assert _proxy_read_timeout_s() < service.TOTAL_BUDGET_S


def test_the_whole_loop_cannot_outlast_the_total_budget() -> None:
    """`MAX_TURNS` turns of `STREAM_IDLE_S` silence each is the worst case the httpx
    timeouts alone permit, and it has to be inside the wall clock `asyncio.timeout`
    enforces — otherwise the outer bound is decoration and a wedged provider holds the
    connection for `MAX_TURNS * STREAM_IDLE_S`."""
    assert service.MAX_TURNS * service.STREAM_IDLE_S <= service.TOTAL_BUDGET_S


def test_the_turn_cap_is_in_the_three_to_six_range_the_design_argues_for() -> None:
    """Fewer than three and a refused fill can never be corrected; more than six and one
    click can buy seven paid round trips.

    ⚠ **THE UPPER BOUND WAS FIVE AND WAS RAISED DELIBERATELY WITH THE READ TOOLS.** The
    shape that did not fit under five is the one those tools exist for: look something up,
    look something up that depended on the first answer, answer in prose — three turns
    before a word is written, with a refused fill and its correction still to come. Six is
    also where the arithmetic above stops giving: `MAX_TURNS * STREAM_IDLE_S <=
    TOTAL_BUDGET_S` is 90 <= 90 at six and is violated at seven, so the wall clock — the
    brake that actually bounds a wedged provider — is what caps this, not a taste for round
    numbers."""
    assert 3 <= service.MAX_TURNS <= 6


def test_every_budget_is_a_positive_number_of_seconds() -> None:
    """A zero or negative budget is a client that times out immediately, which presents as
    "the assistant never answers" rather than as a misconfiguration. The way to disable a
    timeout in httpx is `None`, and neither of these may be `None` — both are arguments in
    the arithmetic above."""
    for constant in (service.STREAM_IDLE_S, service.TOTAL_BUDGET_S):
        assert isinstance(constant, float) and constant > 0
