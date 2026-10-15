"""The operator alarm email: what it says, in both parts, and what it must never carry.

`core/alert_email.compose_alert` is called with an `AlertNotice` directly; the delivery
path around it (queue, bucket, episode rows) is `tests/alert_delivery_test.py`'s subject.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import UTC, datetime
from types import SimpleNamespace

from apps.api.core import alarm_guide, console_links
from apps.api.core.alert_email import AlertEmail, EpisodeView, compose_alert, compose_clear
from apps.api.core.alerting import AlertNotice

CODE = "engine_dial_setup_refused"
PHONE = "+919876543210"
#: 21:42 UTC on 14 Oct is 03:12 IST on 15 Oct: the date changes, which is the point.
FIRST = datetime(2026, 10, 14, 21, 42, tzinfo=UTC)
LAST = datetime(2026, 10, 14, 22, 10, tzinfo=UTC)


def _notice(**overrides: object) -> AlertNotice:
    fields: dict[str, object] = {
        "stage": "CORE_LOGIC",
        "code": CODE,
        "severity": "page",
        "detail": "vendor said calling_not_set_up",
        "ids": {"tenant_id": "019f-abc", "agent_id": "019f-def"},
        "suppressed": 0,
        "rate_limited": 0,
    }
    fields.update(overrides)
    return AlertNotice(**fields)  # type: ignore[arg-type]


def _compose(notice: AlertNotice | None = None) -> AlertEmail:
    return compose_alert(
        notice or _notice(),
        service="api",
        app_env="prod",
        episode=EpisodeView(FIRST, LAST, 14),
        now=LAST,
        repeat_window_s=900.0,
        rate_budget_per_hour=20.0,
        reminder_every_s=3600.0,
    )


def _visible(markup: str) -> str:
    """What a reader sees: the body only (no hidden preheader), tags dropped, entities folded."""
    body = markup.split("</div>", 1)[1]
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def _words(text: str) -> set[str]:
    return {
        word.strip(".,:;()`'\"").lower()
        for word in re.split(r"[\s/]+", re.sub(r"https?://\S+", " ", text))
        if word.strip(".,:;()`'\"")
    }


def test_the_subject_is_human_and_keeps_the_code_for_mail_filters() -> None:
    subject = _compose().subject
    summary = alarm_guide.ALARM_SUMMARIES[CODE]
    assert subject == f"[calevate/prod/api] Action needed: {summary.headline} ({CODE})"


def test_the_mail_leads_with_what_happened_who_is_affected_and_what_to_do() -> None:
    message = _compose()
    summary = alarm_guide.ALARM_SUMMARIES[CODE]
    row = alarm_guide.index_row(CODE)
    assert row is not None, "the alarm index row is the source of the meaning and the steps"
    seen = _visible(message.html)
    for part in (message.text, seen):
        assert summary.headline in part
        assert summary.affects in part
        assert "What happened" in part
        assert "What to do now" in part
    # The order is the design: headline, impact, then the technical code last.
    assert (
        seen.index(summary.headline)
        < seen.index("What to do now")
        < seen.index(f"Search the logs for code={CODE}")
    )
    assert f'href="{console_links.ops_alerts_link()}"' in message.html
    assert console_links.ops_alerts_link() in message.text
    assert "Action needed" in seen


def test_the_technical_lines_keep_their_greppable_shape() -> None:
    text = _compose().text
    for line in (f"code:    {CODE}", "stage:   CORE_LOGIC", "severity: page", "service: api"):
        assert line in text.splitlines(), line
    assert f"Search the logs for code={CODE} for the full context." in text


def test_times_are_shown_in_ist_in_both_parts() -> None:
    message = _compose()
    for part in (message.text, _visible(message.html)):
        assert "15 Oct 2026, 03:12 IST" in part
        assert "15 Oct 2026, 03:40 IST" in part
        assert "Occurrences" in part
    assert "21:42" not in message.text, "a UTC clock reading leaked into the mail"


def test_a_reminder_says_it_is_still_open_and_how_often_it_repeats() -> None:
    message = _compose(_notice(reminder=True))
    assert "] Still open: " in message.subject
    assert message.text.startswith("STILL OPEN")
    for part in (message.text, _visible(message.html)):
        assert "every 60 minutes until it clears" in part
    assert "Still open · reminder" in _visible(message.html)


def test_suppressed_and_rate_limited_counts_are_in_both_parts() -> None:
    message = _compose(
        _notice(
            suppressed=13,
            rate_limited=4,
            rate_limited_codes=(("postcall_pipeline_stalled", 3), ("outbox_dead_letter", 1)),
        )
    )
    dropped = "dropped: postcall_pipeline_stalled x3, outbox_dead_letter x1"
    assert dropped in message.text.splitlines()
    seen = _visible(message.html)
    assert dropped in seen
    for part in (message.text, seen):
        assert "13 further occurrence(s)" in part and "last 15 minutes" in part
        assert "4 other alert(s) were dropped by the rate limit (20/hour)" in part


def test_an_unreadable_alarm_history_is_said_rather_than_invented() -> None:
    message = compose_alert(
        _notice(suppressed=2),
        service="api",
        app_env="prod",
        episode=None,
        now=LAST,
        repeat_window_s=900.0,
        rate_budget_per_hour=20.0,
        reminder_every_s=None,
    )
    assert "3 (the alarm history could not be read)" in message.text
    assert "15 Oct 2026, 03:40 IST" in message.text
    assert "First seen" not in message.text


def test_a_phone_number_in_detail_or_ids_reaches_neither_part() -> None:
    message = _compose(
        _notice(detail=f"could not reach {PHONE}", ids={"tenant_id": "019f-abc", "to": PHONE})
    )
    for part in (message.subject, message.text, message.html):
        assert PHONE not in part
        assert "9876543210" not in part
    assert "019f-abc" in message.text and "019f-abc" in message.html


def test_every_value_is_escaped_in_the_html() -> None:
    message = _compose(
        _notice(detail="<script>alert(1)</script>", ids={"tenant_id": '"><img src=x>'})
    )
    assert "<script>" not in message.html
    assert "<img" not in message.html
    assert "&lt;script&gt;" in message.html


def test_the_html_fetches_nothing_and_pins_a_light_scheme() -> None:
    markup = _compose().html.lower()
    for tag in ("<img", "<link", "<script", "@import", "url("):
        assert tag not in markup
    assert 'name="color-scheme" content="light"' in markup


def test_the_text_part_says_nothing_the_html_does_not() -> None:
    """Parity: a word in the text part is in the HTML a reader sees, bar the text-only
    line prefixes (`note:`, `detail:`) and URLs, which are the button's href."""
    message = _compose(
        _notice(suppressed=2, rate_limited=1, rate_limited_codes=(("outbox_dead_letter", 1),))
    )
    missing = {
        word
        for word in _words(message.text) - _words(_visible(message.html))
        if not word.startswith("http") and word not in {"note", "detail", "—"}
    }
    assert not missing, f"only in the text part: {sorted(missing)}"


def test_a_code_with_no_summary_still_mails_a_readable_headline() -> None:
    message = _compose(_notice(code="unhandled_exception:IntegrityError", severity="page"))
    assert "Alarm unhandled_exception fired (unhandled_exception:IntegrityError)" in message.subject
    # The index row is found by the base code, so the steps still come through.
    assert "What happened" in message.text


def test_the_clear_mail_names_the_episode_in_ist() -> None:
    episode = SimpleNamespace(
        code=CODE,
        stage="CORE_LOGIC",
        service="api",
        occurrences=14,
        first_seen_at=FIRST,
        last_seen_at=LAST,
    )
    message = compose_clear(episode, app_env="prod", status="the condition reported recovery")
    headline = alarm_guide.ALARM_SUMMARIES[CODE].headline
    assert message.subject == f"[calevate/prod/api] Cleared: {headline} ({CODE})"
    for part in (message.text, _visible(message.html)):
        assert "reported recovery" in part
        assert "15 Oct 2026, 03:12 IST" in part
        assert "28 minute(s), 14 occurrence(s)" in part


def test_the_index_row_reader_respects_backticks_and_escaped_pipes() -> None:
    row = "| `a_code` | CORE_LOGIC | page | uses `x | y` and a \\| pipe | do it |"
    cells = alarm_guide._cells(row)
    assert cells == ["`a_code`", "CORE_LOGIC", "page", "uses `x | y` and a | pipe", "do it"]


def test_every_summarised_code_has_an_index_row_to_explain_it() -> None:
    missing = [code for code in alarm_guide.ALARM_SUMMARIES if alarm_guide.index_row(code) is None]
    assert not missing, f"no alarm-index row read for {missing}"
