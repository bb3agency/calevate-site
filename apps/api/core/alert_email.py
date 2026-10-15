"""The operator alarm email and its "cleared" follow-up, as subject + text + HTML.

ONE composer for both closers of an episode (`alerting._handle_resolve` and
`workers/alerts.sweep_alert_clears`) and for the onset and reminder mails, so the four can
never describe one alarm four ways.

The reader is an operator, often on a phone. The mail therefore leads with a plain
headline, who is affected and what to do (`core/alarm_guide`), then the episode's timing in
IST, then the ids, and keeps the code, stage and severity last: still in the subject for
mail filters, still in the body for a log search, no longer the first thing read.

**WHAT REACHES THE MAIL.** `detail` and every id kwarg go through `redact_mapping`, the
redaction the logger uses, because `detail` is routinely an upstream error string and an
id is whatever a call site passed (hard rule 6). Everything else is our own text. All of
it is HTML-escaped by `email_layout`, or here before markup is added to it.

Both parts are multipart alternatives of one message. The text part keeps the line shapes
an operator greps for and a pager gateway forwards: `code:`, `stage:`, the `note:` lines,
`dropped:` and "Search the logs for code=...".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import TYPE_CHECKING, Any, Final

from apps.api.core import alarm_guide, brand, console_links
from apps.api.core import email_layout as layout
from apps.api.core.logging import LOG_TIMEZONE, redact_mapping

if TYPE_CHECKING:
    from apps.api.core.alarm_severity import Severity
    from apps.api.core.alerting import AlertNotice


@dataclass(frozen=True, slots=True)
class AlertEmail:
    subject: str
    text: str
    html: str


@dataclass(frozen=True, slots=True)
class EpisodeView:
    """What the `platform_alerts` row says about the episode this mail belongs to."""

    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int


_BADGE: Final[dict[str, tuple[str, layout.Tone]]] = {
    "page": ("Action needed", "danger"),
    "attention": ("Needs attention", "warn"),
    "record": ("For the record", "neutral"),
}
_OPS_ALERTS_LABEL: Final = "Ops > Alerts"
_FOOTER: Final = (
    "Calevate operator alert. Only alarms classed as needing action now are emailed; "
    "every alarm is listed on Ops > Alerts in the admin console.",
)


def ist(instant: datetime) -> str:
    """`15 Oct 2026, 03:12 IST`. Instants are stored UTC; people read IST (D-709).

    `logging.LOG_TIMEZONE` is the same `Asia/Kolkata` zone as `billing.plans.IST`, and is
    used rather than it because voice-runtime raises alarms and `logging` is already
    resident there, where `billing` is a business module it never otherwise loads.
    """
    return f"{instant.astimezone(LOG_TIMEZONE):%d %b %Y, %H:%M} IST"


def _env_tag(app_env: str, service: str) -> str:
    return f"calevate/{app_env}/{service}"


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_TICKED = re.compile(r"`([^`]+)`")
#: A sentence ends at . ! or ? followed by space and a capital, a backtick or a bracket.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z`(])")


def _markdown_html(cell: str) -> str:
    """The index's inline markdown (bold, backticks) as escaped HTML."""
    escaped = escape(cell)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    return _TICKED.sub(lambda m: layout.inline_code(m.group(1)), escaped)


def _plain(cell: str) -> str:
    return cell.replace("**", "")


def _steps(what_to_do: str) -> list[str]:
    """The index's "What to do" cell as separate steps, one per sentence, bold dropped:
    a step list is already the emphasis, and a bold span can straddle a sentence break."""
    text = _plain(what_to_do).strip()
    parts = [part.strip() for part in _SENTENCE_END.split(text) if part.strip()] if text else []
    # Many rows open with a bare runbook path; as a step it needs a verb.
    return [f"Follow {part}" if part.startswith("`runbooks/") else part for part in parts]


def _redacted(detail: str | None, ids: dict[str, str]) -> tuple[str, list[tuple[str, str]]]:
    safe = redact_mapping({"detail": detail or "", **ids})
    redacted_detail = str(safe.pop("detail", ""))
    return redacted_detail, [(str(key), str(value)) for key, value in sorted(safe.items())]


def compose_alert(
    notice: AlertNotice,
    *,
    service: str,
    app_env: str,
    episode: EpisodeView | None,
    now: datetime,
    repeat_window_s: float,
    rate_budget_per_hour: float,
    reminder_every_s: float | None,
) -> AlertEmail:
    """The onset or reminder mail for one alarm. `episode` is None when the alarm record
    could not be read (the mail fails open and goes anyway); the timing then says so."""
    code = notice.code
    severity: Severity = notice.severity
    summary = alarm_guide.summary_for(code)
    row = alarm_guide.index_row(code)
    headline = alarm_guide.headline_for(code)
    badge_label, tone = _BADGE.get(severity, _BADGE["page"])
    prefix = "Still open" if notice.reminder else badge_label
    subject = f"[{_env_tag(app_env, service)}] {prefix}: {headline} ({code})"
    detail, ids = _redacted(notice.detail, notice.ids)
    link = console_links.ops_alerts_link()

    steps = _steps(row.what_to_do) if row is not None else []
    final_step = (
        f"Open {_OPS_ALERTS_LABEL} to see the full history and whether it is still happening."
    )

    if episode is not None:
        timing = [
            ("First seen", ist(episode.first_seen_at)),
            ("Last seen", ist(episode.last_seen_at)),
            ("Occurrences", str(episode.occurrences)),
        ]
    else:
        timing = [
            ("Seen", ist(now)),
            ("Occurrences", f"{notice.suppressed + 1} (the alarm history could not be read)"),
        ]
    if notice.reminder:
        every = (reminder_every_s or 0.0) / 60
        status = f"Still open. Reminder, sent every {every:.0f} minutes until it clears."
    else:
        status = "Open. One more email follows when it clears."
    timing.append(("Status", status))

    notes: list[str] = []
    if notice.suppressed:
        notes.append(
            f"{notice.suppressed} further occurrence(s) of this alert were suppressed in "
            f"the last {repeat_window_s / 60:.0f} minutes."
        )
    if notice.rate_limited:
        notes.append(
            f"{notice.rate_limited} other alert(s) were dropped by the rate limit "
            f"({rate_budget_per_hour:.0f}/hour) since the last delivery."
        )
    # The codes are ours, not a caller's, so they need no redaction, and they are the only
    # way the operator learns WHICH alarm the bucket ate.
    dropped = (
        ", ".join(f"{c} x{count}" for c, count in notice.rate_limited_codes)
        if notice.rate_limited
        else ""
    )

    technical = [
        ("code", code),
        ("stage", notice.stage),
        ("severity", severity),
        ("service", service),
        ("environment", app_env),
    ]

    # --- text -------------------------------------------------------------------------
    lines = [f"{prefix.upper()} — {_env_tag(app_env, service)}", "", headline, ""]
    if summary is not None:
        lines += [summary.affects, ""]
    if row is not None and row.meaning:
        lines += ["What happened", _plain(row.meaning), ""]
    lines.append("What to do now")
    lines += [f"{n}. {step}" for n, step in enumerate([*steps, final_step], start=1)]
    lines += [f"   {link}", "", "When (IST)"]
    lines += [f"{label + ':':<13} {value}" for label, value in timing]
    if notes or dropped:
        lines.append("")
        lines += [f"note:    {note}" for note in notes]
        if dropped:
            lines.append(f"dropped: {dropped}")
    if ids or detail:
        lines += ["", "Reference ids"]
        lines += [f"{key}: {value}" for key, value in ids]
        if detail:
            lines.append(f"detail:  {detail}")
    lines += ["", "Technical"]
    lines += [f"{label + ':':<8} {value}" for label, value in technical]
    lines.append(f"Search the logs for code={code} for the full context.")
    text = "\n".join(lines) + "\n"

    # --- html -------------------------------------------------------------------------
    badges = layout.badge(badge_label, tone=tone)
    if notice.reminder:
        badges += layout.badge("Still open · reminder", tone="warn")
    body = [badges, layout.heading(headline)]
    if summary is not None:
        body.append(layout.paragraph(summary.affects, size=15, margin=4))
    if row is not None and row.meaning:
        body += [
            layout.section_label("What happened"),
            layout.paragraph_html(_markdown_html(row.meaning), size=14, margin=4),
        ]
    body += [
        layout.section_label("What to do now"),
        layout.steps([_markdown_html(step) for step in steps] + [escape(final_step)]),
        layout.button(f"Open {_OPS_ALERTS_LABEL}", link),
        layout.section_label("When (IST)"),
        layout.facts(timing),
    ]
    if notes or dropped:
        note_markup = "<br>".join(escape(note) for note in notes)
        if dropped:
            note_markup += (
                ("<br>" if note_markup else "") + "dropped: " + layout.inline_code(escape(dropped))
            )
        body.append(layout.callout(markup=note_markup, tone="warn", margin_top=12))
    if ids or detail:
        body.append(layout.section_label("Reference ids"))
        if ids:
            body.append(layout.facts(ids, mono_values=True))
        if detail:
            body.append(layout.paragraph("Detail, redacted", size=12, margin=4))
            body.append(layout.mono_block(detail))
    body += [
        layout.divider(margin=18),
        layout.paragraph("Technical", color=brand.TEXT, size=13, margin=6),
        layout.facts(technical, mono_values=True),
        layout.paragraph(
            f"Search the logs for code={code} for the full context.",
            size=12,
            margin=0,
        ),
    ]
    preheader = summary.affects if summary is not None else f"{headline} on {service}."
    html = layout.shell(preheader=preheader, body="".join(body), footer=_FOOTER)
    return AlertEmail(subject=subject, text=text, html=html)


def compose_clear(episode: Any, *, app_env: str, status: str) -> AlertEmail:
    """The one "it cleared" mail. `episode` is anything with `ClosedEpisode`'s attributes
    (the sweep passes its SQL row); `status` says WHY it is over."""
    code = str(episode.code)
    service = str(episode.service)
    headline = alarm_guide.headline_for(code)
    minutes = (episode.last_seen_at - episode.first_seen_at).total_seconds() / 60
    subject = f"[{_env_tag(app_env, service)}] Cleared: {headline} ({code})"
    lead = f"This has stopped: {status}. Nothing is required."
    timing = [
        ("First seen", ist(episode.first_seen_at)),
        ("Last seen", ist(episode.last_seen_at)),
        ("Lasted", f"{minutes:.0f} minute(s), {episode.occurrences} occurrence(s)"),
    ]
    technical = [("code", code), ("stage", str(episode.stage)), ("service", service)]
    link = console_links.ops_alerts_link()

    lines = [
        f"CLEARED — {_env_tag(app_env, service)}",
        "",
        headline,
        "",
        lead,
        "",
        "When (IST)",
        *[f"{label + ':':<13} {value}" for label, value in timing],
        "",
        f"The full history is on {_OPS_ALERTS_LABEL}: {link}",
        "",
        "Technical",
        *[f"{label + ':':<8} {value}" for label, value in technical],
        f"status:  CLEARED — {status}",
    ]
    html = layout.shell(
        preheader=lead,
        footer=_FOOTER,
        body=(
            layout.badge("Cleared", tone="brand")
            + layout.heading(headline)
            + layout.paragraph(lead, margin=4)
            + layout.section_label("When (IST)")
            + layout.facts(timing)
            + layout.button(f"Open {_OPS_ALERTS_LABEL}", link)
            + layout.divider(margin=4)
            + layout.paragraph("Technical", color=brand.TEXT, size=13, margin=6)
            + layout.facts(technical, mono_values=True)
        ),
    )
    return AlertEmail(subject=subject, text="\n".join(lines) + "\n", html=html)


__all__ = ["AlertEmail", "EpisodeView", "compose_alert", "compose_clear", "ist"]
