"""While a refresh of the business examples runs, the screen does not also show why the run
before it wrote nothing: the owner pressed "Refresh now" and read "Pip is writing them now"
beside "Not refreshed: AI help could not be reached", the old run's outcome."""

from __future__ import annotations

from apps.api.tenancy import business_copy as service
from apps.api.tenancy.business_copy_routes import render


def _state(*, running: bool) -> service.CopyState:
    return service.CopyState(
        copy=None,
        language=None,
        model=None,
        generated_at=None,
        cost_inr=None,
        absorbed=False,
        running=running,
        last_trigger="refresh",
        last_attempt_at=None,
        stop_reason="provider_unavailable",
    )


def test_a_running_refresh_hides_the_last_runs_failure() -> None:
    """FAILS IF: a run in progress is shown with the previous run's stop sentence."""
    shown = render(_state(running=True))
    assert shown.refreshing is True
    assert shown.stop_reason is None and shown.stop_message is None


def test_the_failure_is_shown_once_no_run_is_in_progress() -> None:
    shown = render(_state(running=False))
    assert shown.stop_reason == "provider_unavailable"
    assert shown.stop_message == service.STOP_MESSAGES["provider_unavailable"]
