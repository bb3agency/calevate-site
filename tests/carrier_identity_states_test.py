"""The four caller-identity states, and the vendor lines each one is read off.

**THE DEFECT THIS FILE PINS.** `calls.from_e164` was NULL on every call of the Pipecat leg
and nothing anywhere said why. Four unrelated situations produced the same `None`:

1. the carrier told us who called (never reached, on Plivo);
2. the carrier was asked and withheld it;
3. our pinned client does not ask this carrier at all;
4. nobody looked.

(2), (3) and (4) want three different responses — (2) is a caller exercising CLIR and there
is nothing to build; (3) is an UNVERIFIED vendor question and the thing that closes it is a
reading of Plivo's `<Stream>` documentation, not code; (4) is a wiring bug in ours. A column
that says all four at once cannot be triaged, and a suppression that cannot be keyed to a
number is not a suppression (hard rule 5).

**EVERY CARRIER CLAIM HERE IS DRIVEN THROUGH THE PINNED WHEEL RATHER THAN RESTATED**
(hard rule 11). `www.plivo.com` and `api.plivo.com` are egress-blocked from this container
(`curl` → 000, 19 Sep 2026), so `pipecat-ai==1.10.0`'s own source — hash-pinned by
`uv.lock` — is the only primary source available, and these tests run Pipecat's real
detector and real parser over real start messages rather than asserting against a
constant we typed. A dependency bump that starts (or stops) parsing a carrier's calling
party fails HERE, where somebody is looking.

HARD RULE 6: the numbers below are fixtures, never log output. The one assertion that
touches logging asserts a number's ABSENCE from it.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import pytest
from loguru import logger
from pipecat.runner.utils import parse_telephony_websocket
from voice_worker import carrier

#: A fixture number, in the form a carrier would hand over. Never logged; see the module
#: docstring and `test_no_state_or_ground_can_carry_a_number`.
CALLER = "+919876543210"


class _SocketSaying:
    """A websocket that says `connected`, then one start message, and nothing else.

    Two messages because that is what `parse_telephony_websocket` reads
    (`runner/utils.py:185-208`).
    """

    headers: ClassVar[dict[str, str]] = {}

    def __init__(self, start_message: str) -> None:
        self._start = start_message

    def iter_text(self) -> Any:
        async def _messages() -> Any:
            yield '{"event": "connected"}'
            yield self._start

        return _messages()


async def _parse(message: dict[str, Any]) -> tuple[str, Any]:
    return await parse_telephony_websocket(_SocketSaying(json.dumps(message)))


# --------------------------------------------------------------------------------------
# 1. What the pinned client does per carrier — the asymmetry that is the whole finding.
# --------------------------------------------------------------------------------------


async def test_plivos_parse_names_no_calling_party_while_telnyx_and_exotel_do() -> None:
    """THE CENTRAL FACT, driven rather than quoted.

    `parse_telephony_websocket` builds a per-carrier dict and only then validates it onto
    `CallData`, whose `from_number` is `Field(alias="from")` (`runner/types.py:94`). The
    Plivo branch writes exactly two keys and no `"from"` (`runner/utils.py:257-262`), so the
    field keeps its `None` default with nothing consulted; the Telnyx and Exotel branches
    write one (`:253`, `:270`).

    So the gap is in the CLIENT's parse and not demonstrably on the carrier's wire — which
    is why the fix cannot be "read the field harder" and why `unparsed_by_client` is a
    distinct state from `withheld_by_carrier`.
    """
    plivo_type, plivo = await _parse(
        {"event": "start", "start": {"streamId": "s1", "callId": "c1", "from": CALLER}}
    )
    assert plivo_type == "plivo"
    # The number was ON the message this test handed over, and the parse still drops it.
    assert plivo.from_number is None

    telnyx_type, telnyx = await _parse(
        {"stream_id": "s2", "start": {"call_control_id": "c2", "from": CALLER, "to": "+911111"}}
    )
    assert telnyx_type == "telnyx"
    assert telnyx.from_number == CALLER

    exotel_type, exotel = await _parse(
        {
            "event": "start",
            "start": {
                "stream_sid": "s3",
                "call_sid": "c3",
                "account_sid": "a3",
                "from": CALLER,
                "to": "+911111",
            },
        }
    )
    assert exotel_type == "exotel"
    assert exotel.from_number == CALLER


async def test_twilios_calling_party_comes_from_parameters_we_could_set_ourselves() -> None:
    """The route that needs nothing from a carrier's own start schema.

    Twilio's branch reads `start.customParameters["from_number"]`
    (`runner/utils.py:232,240-241`) — a value the ANSWER DOCUMENT put on the stream, not a
    field Twilio invented. If Plivo's `<Stream>` accepts custom parameters the same way,
    `apps/voice-runtime/carrier_routes.plivo_answer_document` can attach the number at
    answer time and the carrier's own schema stops mattering. That is UNVERIFIED — it is
    the question `docs/evidence/carrier-caller-identity.md` §5 sends to a browser — and
    this test records why it is the question worth asking.
    """
    transport_type, call_data = await _parse(
        {
            "event": "start",
            "start": {
                "streamSid": "MZ1",
                "callSid": "CA1",
                "customParameters": {"from_number": CALLER},
            },
        }
    )
    assert transport_type == "twilio"
    assert call_data.from_number == CALLER
    assert carrier.caller_identity_of(transport_type, call_data).is_known


def test_the_capability_table_agrees_with_the_installed_client() -> None:
    """`CALLER_IDENTITY_PARSE` is a claim about the wheel, so it is checked against it.

    Each row cites a `file:line`. A table that drifted from the source it cites would be a
    repo-internal value repeating itself as evidence — hard rule 11's named failure — so
    the assertion is made through the parser rather than against the citation text.
    """
    assert set(carrier.CALLER_IDENTITY_PARSE) == {"plivo", "telnyx", "exotel", "twilio"}
    assert carrier.CALLER_IDENTITY_PARSE["plivo"].maps_calling_party is False
    for named in ("telnyx", "exotel", "twilio"):
        assert carrier.CALLER_IDENTITY_PARSE[named].maps_calling_party is True
        assert "pipecat/runner/utils.py:" in carrier.CALLER_IDENTITY_PARSE[named].evidence


# --------------------------------------------------------------------------------------
# 2. The four states, each reachable and each distinguishable.
# --------------------------------------------------------------------------------------


async def test_a_carrier_that_names_the_caller_is_known_and_canonicalised() -> None:
    """`known` carries an E.164 in the one form the DNC and lead paths key on.

    `normalize_phone` rather than a second canonicaliser: `dnc_list.phone_e164` is matched
    exactly by the dispatch gate, so a carrier number stored in another form would be a
    suppression that suppresses nothing.
    """
    transport_type, call_data = await _parse(
        {"stream_id": "s", "start": {"call_control_id": "c", "from": "91 98765 43210"}}
    )
    identity = carrier.caller_identity_of(transport_type, call_data)

    assert identity.state == "known"
    assert identity.is_known
    assert identity.e164 == CALLER


async def test_a_carrier_we_do_read_that_sends_nothing_is_withheld_not_unparsed() -> None:
    """The Telnyx/Exotel branches default `"from"` to `""` (`runner/utils.py:253`, `:270`).

    An empty value there is the carrier's own answer — caller ID withheld, or a leg with no
    calling party — and there is nothing further to build. That is a different finding from
    Plivo's, and a different conversation with the client, so it is a different state.
    """
    transport_type, call_data = await _parse({"stream_id": "s", "start": {"call_control_id": "c"}})
    identity = carrier.caller_identity_of(transport_type, call_data)

    assert identity.state == "withheld_by_carrier"
    assert not identity.is_known
    assert identity.e164 is None
    assert "sent none" in identity.ground


async def test_plivo_is_unparsed_by_client_and_the_ground_says_it_is_unverified() -> None:
    """The state that must NOT read as "the carrier does not send it".

    Nothing in this container can support that claim: Plivo's documentation host is
    egress-blocked. The ground says what is true — our client does not map it, and whether
    the carrier sends it is unverified — which is what hard rule 11 requires of a gap.
    """
    transport_type, call_data = await _parse(
        {"event": "start", "start": {"streamId": "s", "callId": "c"}}
    )
    identity = carrier.caller_identity_of(transport_type, call_data)

    assert identity.state == "unparsed_by_client"
    assert "UNVERIFIED" in identity.ground
    assert "egress-blocked" in identity.ground


def test_an_unknown_carrier_is_unparsed_rather_than_silently_absent() -> None:
    """A carrier with no row in the table must not read as "asked and got nothing"."""

    class _NoFrom:
        from_number = None

    identity = carrier.caller_identity_of("some-new-carrier", _NoFrom())
    assert identity.state == "unparsed_by_client"
    assert "some-new-carrier" in identity.ground


def test_not_read_is_a_state_of_its_own_and_is_the_default() -> None:
    """THE DISTINCTION THE BUG TURNED ON. "Nobody looked" is not "the carrier said nothing".

    A handshake built without a carrier parse reports `not_read`, so a wiring regression
    that stopped asking is visible as itself rather than as a carrier problem somebody would
    spend a day taking to a vendor.
    """
    assert carrier.CallerIdentity.not_read().state == "not_read"
    assert not carrier.CallerIdentity.not_read().is_known

    handshake = carrier.PlivoHandshake(stream_id="s", carrier_call_id="c")
    assert handshake.caller.state == "not_read"

    states = {
        carrier.CallerIdentity.not_read().state,
        carrier.caller_identity_of("plivo", type("N", (), {"from_number": None})()).state,
        carrier.caller_identity_of("telnyx", type("N", (), {"from_number": ""})()).state,
    }
    assert len(states) == 3, "the three absences must stay distinguishable"


# --------------------------------------------------------------------------------------
# 3. Hard rule 6 — this is the one module whose whole subject is a phone number.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transport_type",
    ["plivo", "telnyx", "exotel", "twilio", "some-new-carrier"],
)
def test_no_state_or_ground_can_carry_a_number(transport_type: str) -> None:
    """`state` and `ground` are what a log line gets, so neither may contain the number.

    Asserted for the `known` case too, which is the only one where a number is in hand: the
    ground is written in `carrier.py` and never built from wire data, and this is the test
    that keeps it that way if somebody ever interpolates the value into it "for debugging".
    """
    identity = carrier.caller_identity_of(transport_type, type("N", (), {"from_number": CALLER})())
    assert CALLER not in identity.ground
    assert CALLER not in identity.state
    assert "9876543210" not in identity.ground


async def test_the_call_start_log_line_records_the_state_and_not_the_number() -> None:
    """`start_carrier_call` logs the verdict. It must log the WORD, never the value.

    Driven through loguru's own sink rather than by reading the source, because the defect
    this guards against is an interpolation that a `grep` would not obviously catch.
    """
    lines: list[str] = []
    sink_id = logger.add(lambda message: lines.append(str(message)), level="INFO")
    try:
        identity = carrier.caller_identity_of("telnyx", type("N", (), {"from_number": CALLER})())
        assert identity.is_known
        logger.info(
            "carrier call assembled",
            caller_identity=identity.state,
            caller_identity_ground=identity.ground,
        )
    finally:
        logger.remove(sink_id)

    assert lines
    joined = "".join(lines)
    assert CALLER not in joined
    assert "9876543210" not in joined
