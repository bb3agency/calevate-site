"""Egress defects that are OPEN, recorded so they cannot be quietly rediscovered.

**THE REGISTRY IS EMPTY, AND THE PROBES ARE NOT.** Both entries this file was created
with have been closed, and the equality below is what forced their deletion in the same
change as the fix:

- `campaign.completed` now has a producer — `apps.workers.campaign_dispatch`'s
  `emit_campaign_completed`, in the transaction that writes the terminal status
  (`tests/campaign_completed_event_test.py`);
- a Meta lead refused for want of a token is re-drivable long after Meta has
  unsubscribed the Page — `POST /v1/lead-sources/{id}/meta/redrive`, with the activity
  view saying which rows are recoverable and the setup card offering the button
  (`tests/meta_redrive_test.py`).

An empty dict here is not an empty file. Every probe is kept, so each of those defects
now fails HERE, by its original name and with its original message, if it is ever
reintroduced — which is the regression test the fix earned, and the reason a comment or
a TODO was never an option. A future slice that finds a new egress gap it cannot close
adds it back, with what closes it.

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
KNOWN_OPEN_EGRESS_GAPS: dict[str, str] = {}


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
    # Closed, probe kept: the producer is `emit_campaign_completed`, called from
    # `_dispatch_for_campaign` in the transaction that writes `status = 'completed'`.
    # Deleting the producer answers True here again and fails on the line below.
    "campaign_completed_is_subscribable_and_nobody_produces_it": (
        _campaign_completed_has_no_producer
    ),
    # Closed, probe kept: `POST /v1/lead-sources/{webhook_id}/meta/redrive` is mounted.
    # Unmounting it — or renaming the path out of the shape this looks for — reopens the
    # gap here rather than leaving a screen with a button and no route behind it.
    "a_meta_lead_refused_for_want_of_a_token_is_only_recoverable_while_meta_retries": (
        _no_route_can_redrive_a_recorded_meta_refusal
    ),
    # Closed by the previous slice, probe kept: `lead.updated` had no producer either, and
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
