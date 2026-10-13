"""What `webhook_deliveries` can and cannot answer about INBOUND traffic (R-9, D-219).

The table is named as the forensic trail by SEC-COMP §4 and by the breach runbook, and
its two directions are not the same kind of record. OUT is complete — `record_delivery`
upserts a row per delivery id whatever the outcome. IN holds only what we CLAIMED: the
receiver writes its row inside `if claimed:`, so a delivery refused at the source-IP
check, refused over the size cap, refused as unkeyable, or abandoned at the claim
deadline leaves nothing behind. The population an intrusion investigation most wants is
exactly the population the table does not contain.

**THIS GAP IS NOT CLOSED AND THIS FILE DOES NOT ASK FOR IT TO BE.** What it pins is that
the platform keeps telling the truth about it, in the three places an investigator will
actually look, and that the argument for leaving it open stays the CURRENT one:

* the reason used to be "closing it needs a bounded, aggregated counter, which needs the
  metrics pipeline `DEPLOYMENT.md` §8 defers". D-204 falsified that half while it stood —
  `platform_engine_health` IS a bounded minute-bucket counter, in Postgres, shipped with
  no metrics pipeline — so a deferral resting on it was resting on nothing. The reasons
  now are hard rule 3 (all four refusals are DB writes on the receiver's ack path, three
  of them before a body is read at all) and that the write rate on an unauthenticated
  endpoint belongs to the caller, which is the objection that rejected a row per refusal
  rather than an answer to it.
* the refusal alert codes are DERIVED from one constant rather than re-typed into two
  documents, because `scripts/check_alarm_wiring.py` exists for exactly the defect of a
  prose list of alarm codes drifting from the code that raises them.
* `duplicate` is NOT one of the gaps. R-9 listed it; `webhook_inbox_events.duplicate_count`
  counts every one, so a replay burst is queryable evidence.

No database: every claim here is about source text and one constant. That is deliberate —
these are claims about what we have WRITTEN DOWN, and a runtime probe cannot fail when a
document goes stale.
"""

from __future__ import annotations

import re
from pathlib import Path

from apps.api.integrations import service as integrations

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIVER = REPO_ROOT / "apps" / "voice-runtime" / "webhook_routes.py"


def test_every_named_refusal_alert_is_actually_raised_by_the_receiver() -> None:
    """The list is only worth pointing an investigator at if the codes exist.

    RED IF A CODE IS INVENTED OR RENAMED. An operator reading OPERATIONS §7 at 3am and
    grepping for `webhook_claim_timeout` must find it; a forensic pointer to a string
    nothing emits is worse than no pointer, because it reads as "we looked and there was
    nothing".
    """
    receiver = RECEIVER.read_text(encoding="utf-8")
    missing = [code for code in integrations.INBOUND_REFUSAL_ALERTS if f'"{code}"' not in receiver]
    assert not missing, f"INBOUND_REFUSAL_ALERTS names codes the receiver does not raise: {missing}"


def test_the_receiver_raises_no_refusal_alert_the_list_has_missed() -> None:
    """The other direction, which is the one that goes stale silently.

    A fifth refusal added to the receiver without being added here would be a hole in the
    inbound trail that every document still claims is covered — the same shape as the 44
    alarms `check_alarm_wiring` found in no document at all.

    `webhook_payload_mismatch` is deliberately NOT expected here: it is raised by the
    INBOX on a same-key-different-hash replay, which means the delivery was claimed and
    therefore DOES leave a row. This list is the refusals that leave nothing.
    """
    receiver = RECEIVER.read_text(encoding="utf-8")
    # The whole `alert(` call, not the line: two of the four are written inline
    # (`alert("ROUTE_HANDLER", "webhook_unkeyable", engine=engine)`) and a line-oriented
    # scan finds only the two that are wrapped — which is a probe that passes because it
    # cannot see, the failure mode `check_alarm_wiring` was written to avoid.
    raised = set(re.findall(r'alert\(\s*"[A-Z_]+"\s*,\s*"(webhook_[a-z_]+)"', receiver))
    assert len(raised) >= len(integrations.INBOUND_REFUSAL_ALERTS), (
        f"the scan found only {sorted(raised)} — it has stopped matching the receiver's "
        "alert calls, so its silence proves nothing"
    )
    # `webhook_payload_mismatch` would be a claimed delivery (see the docstring), so
    # anything the receiver raises OUTSIDE the claim and outside this list is a new hole.
    unlisted = raised - set(integrations.INBOUND_REFUSAL_ALERTS)
    assert not unlisted, (
        "the receiver raises inbound alert codes that the forensic pointer does not "
        f"name, so an investigation would not know to look for them: {sorted(unlisted)}"
    )


def test_the_receiver_still_writes_its_forensic_row_only_when_it_claims() -> None:
    """The premise every sentence above is about, asserted at the source.

    If the receiver ever started writing a row for a refused delivery, the documents
    would be understating the table instead of overstating it — and this test failing is
    how that gets noticed, rather than the sentences quietly becoming wrong in the other
    direction.
    """
    receiver = RECEIVER.read_text(encoding="utf-8")
    claimed_at = receiver.index("if claimed:")
    insert_at = receiver.index("INSERT INTO webhook_deliveries")
    assert claimed_at < insert_at, (
        "the inbound forensic row is no longer written under `if claimed:`; every "
        "document describing what this table holds needs re-reading"
    )
