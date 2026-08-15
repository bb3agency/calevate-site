"""Egress defects that are OPEN, recorded so they cannot be quietly rediscovered.

Both entries were found taking the CRM/ingest/outbound slice end to end. Neither is
waiting on a vendor, a regulator or a commercial term: each is waiting on a file this
slice was not allowed to write, and each names the file and the act.

**THE ASSERTION IS AN EQUALITY**, in the shape `tests/reliability_known_gaps_test.py`
established. Every key has a probe answering "is this still true?", and the test asserts
the still-open set EQUALS the recorded set. So an entry cannot outlive its defect — the
fix turns this red and forces the entry's deletion in the same change — and the probes
OUTLIVE their entries, so a gap that is closed and then reopened fails here with the same
message it was found with. A comment or a TODO can do none of that, which is why neither
is an option.

The third gap found in this slice — a consent-blocked lead that any dial path will still
ring — is recorded in `tests/lead_consent_carryover_test.py` instead, because its probe
needs the whole Meta receiver plus an HTTP dial and reads as a story rather than as a
predicate.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from apps.api.integrations import service as integrations

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Gap key → why it is open, and WHAT CLOSES IT. Delete an entry the moment its probe
#: stops finding the defect; the equality makes that mandatory rather than polite.
KNOWN_OPEN_EGRESS_GAPS: dict[str, str] = {
    "campaign_completed_is_subscribable_and_nobody_produces_it": (
        "`campaign.completed` is in `integrations.service.EVENT_TYPES`, in the endpoint "
        "route's `EventName` Literal and in the integrations screen's checkbox list as "
        "'A campaign finishes'. Nothing enqueues one — a client can tick it and wait "
        "forever. Its sibling `lead.updated` had the identical defect and was closed in "
        "this change (`crm.service.emit_lead_updated`); this one could not be, because "
        "the only place that knows a campaign finished is "
        "`apps/workers/campaign_dispatch.py`, outside this slice's write boundary. "
        "CLOSED BY: at the point `campaign_dispatch` logs `campaign_completed`, and in "
        "the SAME transaction as the campaign's terminal status write, call "
        "`integrations.enqueue_event(event='campaign.completed', data={campaign_id, "
        "name, contacts_total, contacts_reached, completed_at})` — aggregates only, no "
        "person, which is exactly why `service.body_subject` refuses to retain a body "
        "for this event. Then add the matching tuple to "
        "`integrations.service.DEFAULT_SHEET_COLUMNS`, which today has no entry for it, "
        "so a Sheets endpoint subscribed to it is refused with `no_column_order` "
        "(`sheets_endpoint_test` pins that refusal and would need to move with it)."
    ),
    "a_meta_lead_refused_for_want_of_a_token_is_only_recoverable_while_meta_retries": (
        "A verified leadgen notification we cannot read is recorded `failed` against its "
        "`leadgen_id` in `webhook_inbox_events`, and `claim_inbox_event` re-claims a "
        "failed row by CAS — so attaching a Page access token DOES recover the lead, but "
        "only for as long as Meta keeps redelivering (~36 hours, then the Page is "
        "unsubscribed). After that the `leadgen_id` is still durable and nothing can act "
        "on it: no route, no job and no screen re-drives a recorded refusal, and the "
        "activity view does not even render the `event_key`. So the lead is not lost "
        "from the DATABASE, it is lost from the PRODUCT. CLOSED BY: a re-drive that "
        "reuses the existing path rather than adding a second one — `POST "
        "/v1/lead-sources/{webhook_id}/meta/redrive` (org:manage, audited) selecting "
        "this source's `webhook_inbox_events` rows with status='failed' and "
        "last_error IN (meta.NO_TOKEN_REASON, meta.NO_RETRIEVER_REASON), and calling the "
        "SAME `_absorb_leadgen` with a `LeadNotification` rebuilt from the row, so the "
        "claim, the capability selector, the consent branch and the compliance gate are "
        "the ones production already runs. It is not built here because it needs the "
        "activity view to show which leads are recoverable and the Meta setup card to "
        "offer the button, and half of it — a route with no affordance — is the "
        "half-wired feature this file exists to refuse."
    ),
}


def _event_has_no_producer(event: str) -> bool:
    """No line under `apps/` fans this event out, though a client may subscribe to it.

    Scanned across the app rather than asserted about one file, so a producer landing
    ANYWHERE closes the gap — and a producer that lands and is later deleted reopens it —
    without this predicate having to know where it went. The call is matched over a small
    window of following lines because `enqueue_event(...)` is routinely wrapped, and the
    event name alone is not enough: `EVENT_TYPES`, the route's Literal and
    `DEFAULT_SHEET_COLUMNS` all NAME every event without producing any of them.
    """
    for directory in ("apps/api", "apps/workers", "apps/voice-runtime"):
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            body = path.read_text(encoding="utf-8")
            if event not in body:
                continue
            lines = body.splitlines()
            for index, line in enumerate(lines):
                if "enqueue_event" in line and any(
                    event in following for following in lines[index : index + 8]
                ):
                    return False
    return True


def _campaign_completed_has_no_producer() -> bool:
    assert "campaign.completed" in integrations.EVENT_TYPES, (
        "the event was removed rather than implemented; delete this entry AND its probe"
    )
    return _event_has_no_producer("campaign.completed")


def _no_route_can_redrive_a_recorded_meta_refusal() -> bool:
    """No mounted path lets an operator or a client re-run a refused `leadgen_id`."""
    from apps.api.core.rbac import iter_api_routes
    from apps.api.main import app

    return not any(
        "redrive" in route.path or "replay" in route.path
        for route in iter_api_routes(app)
        if "meta" in route.path or "lead-sources" in route.path
    )


#: key → the probe. A superset of the entries above ON PURPOSE: an entry with no probe is
#: a TODO, and a probe with no entry is a CLOSED gap whose predicate keeps answering
#: False — which is the regression test the fix earned.
PROBES: dict[str, Callable[[], bool]] = {
    "campaign_completed_is_subscribable_and_nobody_produces_it": (
        _campaign_completed_has_no_producer
    ),
    "a_meta_lead_refused_for_want_of_a_token_is_only_recoverable_while_meta_retries": (
        _no_route_can_redrive_a_recorded_meta_refusal
    ),
    # Closed in this change, probe kept: `lead.updated` had no producer either, and
    # `crm.service.emit_lead_updated` is now called from the single-lead PATCH and from
    # the bulk action. If this ever answers True again it fails on the line below rather
    # than being rediscovered by the next slice.
    "lead_updated_is_subscribable_and_nobody_produces_it": (
        lambda: _event_has_no_producer("lead.updated")
    ),
}


def test_every_recorded_egress_gap_is_still_open_and_no_other_is() -> None:
    """The equality. Closing a gap fails here until its entry is deleted; recording one
    that is not real fails here at once; and a closed gap that breaks again fails here
    because its probe was kept."""
    still_open = {key for key, probe in PROBES.items() if probe()}

    unprobed = set(KNOWN_OPEN_EGRESS_GAPS) - set(PROBES)
    assert not unprobed, f"recorded with nothing to check them: {sorted(unprobed)}"

    assert still_open == set(KNOWN_OPEN_EGRESS_GAPS), (
        "the recorded set and the real set disagree.\n"
        f"  fixed but still recorded (delete the entry): "
        f"{sorted(set(KNOWN_OPEN_EGRESS_GAPS) - still_open)}\n"
        f"  open but not recorded (record it, with what closes it): "
        f"{sorted(still_open - set(KNOWN_OPEN_EGRESS_GAPS))}"
    )


def test_every_entry_names_what_closes_it() -> None:
    """A registry entry without a remedy is a TODO with better formatting."""
    for key, reason in KNOWN_OPEN_EGRESS_GAPS.items():
        assert "CLOSED BY:" in reason, f"{key} records a defect and no act that ends it"
        assert len(reason) > 200, f"{key}'s reason is too short to name a file and an act"
