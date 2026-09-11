"use client";

import { useState } from "react";
import { BellRing, MailWarning, TriangleAlert } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import {
  Card,
  EmptyState,
  FilterChip,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  ScrollRegion,
  Skeleton,
  StatTile,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  SEVERITY_MEANINGS,
  WINDOW_CHOICES,
  DEFAULT_WINDOW_DAYS,
  openCounts,
  severityLabel,
  severityStyle,
  useAlerts,
  type AlertEpisode,
  type AlertReport,
} from "@/lib/api/alerts";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

/**
 * WHAT HAS GONE WRONG, AND WHETHER ANY OF IT IS STILL GOING WRONG — the console half of
 * `GET /v1/ops/alerts` (D-591).
 *
 * ## Why this screen exists
 *
 * There was no alert storage and no alerts screen, so the ONLY place an alarm had ever
 * been readable was the founder's inbox — and an inbox cannot answer the question you ask
 * an alert console: *is anything actually broken right now*. It sorts by arrival, so a
 * payment that did not apply at 03:12 sits under forty browser-extension reports from
 * 03:14, and an ongoing condition arrives as twenty-six identical copies of itself. The
 * instruction was exact: *"I need to see about failures in admin panel only. I want high
 * priority things only through mail."* `apps/api/core/alarm_severity.py` is the mail half.
 * This is the panel.
 *
 * ## It is a REPORT, not a control, and three things follow
 *
 * 1. **Nothing here is derived.** Whether an episode is OPEN is `cleared_at === null`, the
 *    server's field; whether it MAILED is `emailed`, what the transport said. Deriving the
 *    second from the severity is the tempting one and it is the wrong one: a `page` whose
 *    SMTP failed twice is `severity: "page"` with `emailed: false`, it is the most
 *    important row on the screen, and a derived column would paint it green. The banner at
 *    the top counts exactly those rows, from the server's own `open_unmailed_pages`.
 * 2. **The counts are over the whole table, not over this page.** `open_by_severity`
 *    arrives computed server-side. "Is anything broken" must not have an answer that
 *    changes with the row limit — and when the list IS truncated, `complete` says so in a
 *    sentence rather than leaving a subset looking whole.
 * 3. **§52 without exception.** Loading is a skeleton, a failed read is a refusal, and
 *    neither is "nothing has happened". "No alarms in this window" is a claim about the
 *    platform — the single most reassuring sentence this console can print — and a 500 is
 *    not evidence for it.
 *
 * ## What it deliberately does not offer
 *
 * **No acknowledge, no snooze, no mute.** Every one of those is a way to make a row stop
 * being visible while the thing it describes carries on, which is the defect this whole
 * decision exists to remove, re-introduced as a feature. An episode ends when the
 * CONDITION stops (`workers/alerts.sweep_alert_clears` closes it after an hour of quiet)
 * and in no other way. If a code is too loud, the fix is its severity in
 * `alarm_severity.py`, in a diff somebody reviews.
 *
 * ## Permission
 *
 * `ops:manage`, which only `superadmin` holds (`core/rbac.py`), asked of `GET /v1/admin/me`
 * rather than derived from this screen's own 403 — so an operator sent here is told why in
 * a sentence instead of a refusal that reads like an outage. The answer gates the READ,
 * as on `/admin/ops/engine-latency`: this screen is one GET, so a session the server
 * refuses has nothing left to look at.
 *
 * No `<h1>`: the shell derives the title from the nav list it also renders the sidebar
 * from (`app/admin/layout.tsx`).
 */
export default function AlertsPage() {
  const [days, setDays] = useState(DEFAULT_WINDOW_DAYS);
  const access = useAdminAccess("ops:manage", "read the platform's alerts");
  const report = useAlerts(days, !access.refused);
  const data = report.data;

  /*
   * THE ALERT BOARD, DECLARED TO THE SCREEN ASSISTANT.
   *
   * Platform-wide and attributable to no client: `platform_alerts` carries no tenant_id,
   * and `detail`/`ids` were redacted at the write with the same function the alert email
   * uses (`core/alert_records.py`, hard rule 6). So there is no cross-tenant question here
   * and nothing on this surface can quote a caller.
   *
   * The window IS writable — it is the screen's only control and a choice from four fixed
   * values, so a fill naming anything else is refused against the declared options rather
   * than setting a window the endpoint would 422.
   */
  useCopilotSurface({
    route: "/admin/ops/alerts",
    title: "Alerts",
    realm: "admin",
    fields: [
      {
        id: "alerts-window-days",
        label: "Window (days)",
        type: "select",
        value: String(days),
        options: WINDOW_CHOICES.map((choice) => ({
          value: String(choice),
          label: `Last ${windowLabel(choice)}`,
        })),
      },
    ],
    facts: access.refused
      ? [
          {
            key: "alerts",
            label: "The alert board",
            value: "withheld — this admin account may not read it",
          },
        ]
      : data
        ? [
            {
              key: "open",
              label: "Alarms still happening, by how loud they are",
              value:
                openCounts(data)
                  .map((row) => `${severityLabel(row.severity)}: ${row.total}`)
                  .join(", ") || "none",
            },
            {
              key: "unmailed",
              label: "Emailed-tier alarms still open that never actually emailed",
              value: String(data.open_unmailed_pages),
            },
            {
              key: "codes",
              label: "Alarm codes still happening",
              value:
                data.episodes
                  .filter((episode) => episode.cleared_at === null)
                  .map((episode) => episode.code)
                  .join(", ") || "none",
            },
            {
              key: "complete",
              label: "Did every episode in the window fit on this page",
              value: data.complete ? "yes" : "no, the list is truncated",
            },
          ]
        : [
            {
              key: "alerts",
              label: "The alert board",
              value: report.error ? "could not be read" : "still loading",
            },
          ],
    apply: (items) => {
      const window = items.find((item) => item.field_id === "alerts-window-days");
      if (window === undefined) return;
      const chosen = Number(asText(window.value));
      if (WINDOW_CHOICES.includes(chosen)) setDays(chosen);
    },
  });

  return (
    <div className="space-y-4 pb-12">
      <p className="text-sm text-ink-muted">
        Everything the platform has raised an alarm about. Each row is one condition, not
        one message: it counts every time the condition happened, says when it started and
        when it was last seen, and stays open until it has been quiet for an hour. Only the
        loudest kind is emailed — everything else is here and nowhere else, which is the
        point.
      </p>

      {access.refused ? (
        /* The refusal INSTEAD of the board, never beside it: this screen is one read, and
           a disabled window picker over a red box would describe an outage where a
           permission is working exactly as designed. */
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Choose a window"
          >
            {WINDOW_CHOICES.map((choice) => (
              <FilterChip
                key={choice}
                label={`Last ${windowLabel(choice)}`}
                active={choice === days}
                onClick={() => setDays(choice)}
              />
            ))}
          </div>

          {report.error != null && (
            <ProblemNotice error={report.error} onRetry={() => void report.refetch()} />
          )}

          {/* §52. `!data` covers all three ways to have no answer — in flight, failed, and
              the paused query a tab left open across a dropped connection produces
              (`lib/api/client.ts` calls that the normal case). Only the first gets a
              skeleton; the other two are answered by the refusal above. */}
          {!data ? (
            report.error ? null : (
              <Card>
                <Skeleton rows={6} label="Loading the platform's alerts" />
              </Card>
            )
          ) : (
            <Board report={data} days={days} />
          )}
        </>
      )}
    </div>
  );
}

/** "7 days", and "1 day" rather than "1 days" — one spelling for the chip and the tile. */
function windowLabel(days: number): string {
  return `${formatCount(days)} ${days === 1 ? "day" : "days"}`;
}

/**
 * The board, given a report that ARRIVED.
 *
 * Takes the payload rather than the query envelope for the reason every board in this
 * console does: each sentence below is a claim about what the platform did, and a
 * component that cannot see `undefined` cannot accidentally make one out of it.
 */
function Board({ report, days }: { report: AlertReport; days: number }) {
  const counts = openCounts(report);
  const openTotal = counts.reduce((total, row) => total + row.total, 0);
  return (
    <div className="space-y-4">
      {/* THE ROW THAT MUST NEVER BE QUIET. An alarm loud enough to email that did not
          email means the operator was never told, by the one mechanism that tells them —
          so it is stated at the top, in the server's own number, above everything else. */}
      {report.open_unmailed_pages > 0 && (
        <NoticeBox
          tone="stop"
          icon={<MailWarning aria-hidden className="h-5 w-5" />}
          title="Some alarms that should have emailed did not"
        >
          <p className="mt-1">
            {formatCount(report.open_unmailed_pages)} alarm(s) of the emailed kind are still
            happening and no email was sent for them — the message failed, or no alert
            mailbox is configured. Check the rows marked &ldquo;not sent&rdquo; below, and
            check that alerts have somewhere to go.
          </p>
        </NoticeBox>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {counts.map((row) => (
          <StatTile
            key={row.severity}
            label={`${severityLabel(row.severity)} — still happening`}
            value={formatCount(row.total)}
            tone={row.severity === "page" && row.total > 0 ? "strong" : undefined}
            icon={
              row.severity === "page" ? (
                <BellRing aria-hidden className="h-5 w-5" />
              ) : (
                <TriangleAlert aria-hidden className="h-5 w-5" />
              )
            }
            hint={lookup(SEVERITY_MEANINGS, row.severity)}
          />
        ))}
        {/* The window the SERVER answered for, not the one the chips asked for. */}
        <StatTile
          label="Window"
          value={windowLabel(report.window_days)}
          hint={
            report.complete
              ? "Every alarm in this window is listed below."
              : "More alarms happened in this window than fit on one page — the list below is the most recent and the loudest."
          }
        />
      </div>

      {openTotal === 0 && report.episodes.length > 0 && (
        <NoticeBox tone="ok" title="Nothing is happening right now">
          <p className="mt-1">
            Every alarm below has stopped. They are kept so you can see what happened and
            how often.
          </p>
        </NoticeBox>
      )}

      {report.episodes.length === 0 ? (
        <Card>
          <EmptyState
            title="No alarms in this window"
            hint={`Nothing has gone wrong in the last ${windowLabel(days)}. This is the platform's own record, so an empty board means the alarms did not fire — not that nobody read them.`}
          />
        </Card>
      ) : (
        <Card>
          <ScrollRegion label="Alarms raised in this window">
            <table className="w-full min-w-[1000px] text-sm">
              <caption className="sr-only">
                Every alarm raised in the last {windowLabel(report.window_days)}, still
                happening first and loudest first
              </caption>
              <thead>
                <tr className="border-b border-line text-left text-xs font-medium text-ink-muted">
                  <th scope="col" className="py-2 pr-3">
                    Alarm
                  </th>
                  <th scope="col" className="py-2 pr-3">
                    Kind
                  </th>
                  <th scope="col" className="py-2 pr-3">
                    Where
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    Times
                  </th>
                  <th scope="col" className="py-2 pr-3">
                    Started
                  </th>
                  <th scope="col" className="py-2 pr-3">
                    Last seen
                  </th>
                  <th scope="col" className="py-2 pr-3">
                    Email
                  </th>
                  <th scope="col" className="py-2">
                    What happened
                  </th>
                </tr>
              </thead>
              <tbody>
                {report.episodes.map((episode) => (
                  <Row key={episode.id} episode={episode} />
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        </Card>
      )}
    </div>
  );
}

/**
 * One episode.
 *
 * `open` is the server's `cleared_at === null` and is rendered as a WORD beside the code
 * rather than as a row colour, because colour alone is not a status an assistive reader
 * can hear — and because "still happening" is the single fact the reader is scanning for.
 */
function Row({ episode }: { episode: AlertEpisode }) {
  const open = episode.cleared_at === null;
  // `ids` is optional on the generated type (the API omits it when a call site passed
  // none), so the empty object is spelled here rather than trusted from the wire.
  const ids = Object.entries(episode.ids ?? {});
  return (
    <tr className="border-b border-line/60 align-top last:border-0">
      <td className="py-3 pr-3">
        <MonoValue>{episode.code}</MonoValue>
        <p className="mt-0.5 text-xs text-ink-muted">
          {open ? "still happening" : `stopped ${formatIST(episode.cleared_at)}`}
        </p>
      </td>
      <td className="py-3 pr-3">
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${severityStyle(episode.severity)}`}
        >
          {severityLabel(episode.severity)}
        </span>
      </td>
      <td className="py-3 pr-3 text-xs text-ink-muted">
        <MonoValue>{episode.stage}</MonoValue>
        <p className="mt-0.5">{episode.service}</p>
      </td>
      <td className="py-3 pr-3 text-right tabular-nums">{formatCount(episode.occurrences)}</td>
      <td className="py-3 pr-3 text-xs text-ink-muted">{formatIST(episode.first_seen_at)}</td>
      <td className="py-3 pr-3 text-xs text-ink-muted">{formatIST(episode.last_seen_at)}</td>
      <td className="py-3 pr-3 text-xs">
        {/* THREE STATES, NOT TWO. "sent", "not sent" for an alarm that should have been,
            and "not emailed" for a rung that was never going to be — collapsing the last
            two would make every ordinary `attention` row look like a delivery failure. */}
        {episode.emailed ? (
          <span className="text-ink-muted">sent {formatIST(episode.emailed_at)}</span>
        ) : episode.severity === "page" ? (
          <span className="font-medium text-rose-700 dark:text-rose-300">not sent</span>
        ) : (
          <span className="text-ink-faint">not emailed</span>
        )}
      </td>
      <td className="py-3 text-xs text-ink-muted">
        <p className="max-w-[38ch] break-words">{episode.detail ?? "—"}</p>
        {ids.length > 0 && (
          <p className="mt-1 max-w-[38ch] break-words text-ink-faint">
            {ids.map(([key, value]) => `${key}=${String(value)}`).join(" · ")}
          </p>
        )}
      </td>
    </tr>
  );
}
