"use client";

import { useMemo, useState, type ReactNode } from "react";
import { MailWarning } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { Drawer } from "@/components/console/drawer";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  MonoValue,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatCountOf,
  formatIST,
} from "@/components/ui";
import {
  DEFAULT_WINDOW_DAYS,
  SEVERITY_MEANINGS,
  SEVERITY_ORDER,
  WINDOW_CHOICES,
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
 * Everything the platform has raised an alarm about, and whether any of it is still
 * happening — the console half of `GET /v1/ops/alerts` (D-591). The inbox gets only the
 * loudest kind (`apps/api/core/alarm_severity.py`); this board gets all of it.
 *
 * It is a report, not a control:
 *
 * - Nothing is derived. "Open" is the server's `cleared_at === null` and "emailed" is the
 *   transport's own `emailed`. Deriving the second from the severity would paint a `page`
 *   whose SMTP failed — the most important row on the screen — as delivered.
 * - The counts come from `open_by_severity`, computed over the whole table, so "is
 *   anything broken" cannot change with the row limit; a truncated list says so.
 * - There is no acknowledge, snooze or mute. Each would hide a row while its condition
 *   carries on. An episode ends only when the condition stops
 *   (`workers/alerts.sweep_alert_clears`); a code that is too loud is fixed in
 *   `alarm_severity.py`, in a reviewed diff.
 *
 * `ops:manage` (superadmin only) is asked of `GET /v1/admin/me` and gates the READ: the
 * screen is one GET, so a refused session gets the reason instead of a 403 that reads
 * like an outage.
 */
export function AlertsScreen() {
  const [days, setDays] = useState(DEFAULT_WINDOW_DAYS);
  const access = useAdminAccess("ops:manage", "read the platform's alerts");
  const report = useAlerts(days, !access.refused);
  const data = report.data;

  /*
   * `platform_alerts` carries no tenant_id, and `detail`/`ids` are redacted at the write
   * with the alert email's own function (`core/alert_records.py`, hard rule 6), so nothing
   * here is attributable to a client or quotes a caller. The window is the one writable
   * field, refused against the four declared options rather than sent as a value the
   * endpoint would 422.
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
    <div className="max-w-4xl space-y-10 pb-12">
      <PageHeader
        description={
          <>
            Each row is one condition. Only the loudest kind is emailed.{" "}
            <InfoTip label="How alarms are counted">
              <p>
                A row counts every time its condition happened, says when it started and when
                it was last seen, and stays open until it has been quiet for an hour.
              </p>
              <p>Everything that is not emailed is here and nowhere else, which is the point.</p>
            </InfoTip>
          </>
        }
      />

      {access.refused ? (
        // Instead of the board, never beside it: a window picker over a red box would
        // describe an outage where a permission is working as designed.
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          {/* The row that must never be quiet: an alarm loud enough to email that did not
              email means the one mechanism that tells the operator failed. */}
          {data !== undefined && data.open_unmailed_pages > 0 && (
            <NoticeBox
              tone="stop"
              icon={<MailWarning aria-hidden className="h-5 w-5" />}
              title="Some alarms that should have emailed did not"
            >
              <p className="mt-1">
                {formatCountOf(data.open_unmailed_pages, "alarm")} of the emailed kind{" "}
                {data.open_unmailed_pages === 1 ? "is" : "are"} still
                happening and no email was sent for them — the message failed, or no alert
                mailbox is configured. Check the rows marked &ldquo;not sent&rdquo; below, and
                check that alerts have somewhere to go.
              </p>
            </NoticeBox>
          )}

          <SegmentedControl
            label="Window"
            value={String(days)}
            onValueChange={(value) => setDays(Number(value))}
            options={WINDOW_CHOICES.map((choice) => ({
              value: String(choice),
              label: `Last ${windowLabel(choice)}`,
            }))}
          />

          {report.error != null && (
            <ProblemNotice error={report.error} onRetry={() => void report.refetch()} />
          )}

          {/* §52: in flight gets a skeleton; failed is the refusal above and nothing else. */}
          {!data ? (
            report.error ? null : (
              <div>
                <Skeleton rows={6} label="Loading the platform's alerts" />
              </div>
            )
          ) : (
            <Board report={data} />
          )}
        </>
      )}
    </div>
  );
}

/** "7 days", and "1 day" rather than "1 days". */
function windowLabel(days: number): string {
  return `${formatCount(days)} ${days === 1 ? "day" : "days"}`;
}

const PARTIAL_NOTE =
  "More alarms happened in this window than fit on one page — the list below is the most recent and the loudest.";

/** The board, given a report that arrived — it cannot see `undefined`, so cannot claim from it. */
function Board({ report }: { report: AlertReport }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const counts = openCounts(report);
  const openTotal = counts.reduce((total, row) => total + row.total, 0);
  const opened = report.episodes.find((episode) => episode.id === openId);
  const columns = useMemo(() => COLUMNS(setOpenId), []);

  return (
    <div className="space-y-10">
      <section aria-labelledby="alerts-open-heading" className="space-y-3">
        <div className="flex items-center gap-1">
          <h2 id="alerts-open-heading" className="text-body font-semibold text-ink">
            Still happening
          </h2>
          <InfoTip label="What each kind means">
            {SEVERITY_ORDER.map((severity) => (
              <p key={severity}>
                <span className="font-medium text-ink">{severityLabel(severity)}:</span>{" "}
                {lookup(SEVERITY_MEANINGS, severity)}
              </p>
            ))}
          </InfoTip>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          {counts.map((row) => (
            <Metric
              key={row.severity}
              label={severityLabel(row.severity)}
              value={formatCount(row.total)}
              tone={
                row.total === 0
                  ? "default"
                  : row.severity === "page"
                    ? "danger"
                    : row.severity === "attention"
                      ? "warn"
                      : "default"
              }
            />
          ))}
          {/* The window the SERVER answered for, not the one the control asked for. */}
          <Metric label="Window" value={windowLabel(report.window_days)} />
        </div>
      </section>

      {openTotal === 0 && report.episodes.length > 0 && (
        <NoticeBox tone="ok" title="Nothing is happening right now">
          <p className="mt-1">Every alarm below has stopped. They are kept so you can see how often.</p>
        </NoticeBox>
      )}

      {report.episodes.length === 0 ? (
        <div>
          <EmptyState
            message={
              <>
                No alarms in this window{" "}
                <InfoTip label="An empty board">
                  This is the platform&apos;s own record, so an empty board means the alarms did
                  not fire — not that nobody read them.
                </InfoTip>
              </>
            }
          />
        </div>
      ) : (
        <div>
          {!report.complete && (
            <p className="border-b border-line px-4 py-2.5 text-meta text-warn">{PARTIAL_NOTE}</p>
          )}
          <DataTable
            rows={report.episodes}
            columns={columns}
            getRowId={episodeId}
            label={`Every alarm raised in the last ${windowLabel(report.window_days)}, still happening first and loudest first`}
            partialNote={report.complete ? undefined : "Sorted within the alarms on this page only."}
          />
        </div>
      )}

      <Drawer
        open={opened !== undefined}
        onClose={() => setOpenId(null)}
        title={opened?.code ?? ""}
        description={opened ? `${severityLabel(opened.severity)} · ${openLine(opened)}` : undefined}
        initialFocus="container"
      >
        {opened && <EpisodeDetail episode={opened} />}
      </Drawer>
    </div>
  );
}

function episodeId(episode: AlertEpisode): string {
  return episode.id;
}

function openLine(episode: AlertEpisode): string {
  return episode.cleared_at === null ? "still happening" : `stopped ${formatIST(episode.cleared_at)}`;
}

function SeverityPill({ severity }: { severity: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-meta font-medium ${severityStyle(severity)}`}
    >
      {severityLabel(severity)}
    </span>
  );
}

/**
 * Three states, not two: "sent", "not sent" for an alarm that should have been, and "not
 * emailed" for a kind that was never going to be. Collapsing the last two would make every
 * ordinary `attention` row look like a delivery failure.
 */
function EmailState({ episode }: { episode: AlertEpisode }) {
  if (episode.emailed) return <span className="text-ink-muted">sent {formatIST(episode.emailed_at)}</span>;
  if (episode.severity === "page") return <span className="font-medium text-danger">not sent</span>;
  return <span className="text-ink-muted">not emailed</span>;
}

/*
 * One target per row (UX-DOCTRINE §4): the alarm code is a button stretched over the row,
 * and it opens the detail. "Still happening" is a word beside the code rather than a row
 * colour, because colour alone is not a status a screen reader can hear. Below `sm` the
 * dropped columns' facts stack under the code.
 */
const COLUMNS = (open: (id: string) => void): DataColumn<AlertEpisode>[] => [
  {
    id: "alarm",
    header: "Alarm",
    cell: (episode) => (
      <div className="min-w-0">
        <button
          type="button"
          onClick={() => open(episode.id)}
          className="rounded-sm text-left after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          <MonoValue className="break-all text-ink">{episode.code}</MonoValue>
        </button>
        <p className="mt-0.5 text-meta text-ink-muted">{openLine(episode)}</p>
        <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-meta sm:hidden">
          <SeverityPill severity={episode.severity} />
          <span className="text-ink-muted">{formatCount(episode.occurrences)}×</span>
          <EmailState episode={episode} />
        </p>
      </div>
    ),
  },
  {
    id: "kind",
    header: "Kind",
    hideBelow: "sm",
    cell: (episode) => <SeverityPill severity={episode.severity} />,
  },
  {
    id: "times",
    header: "Times",
    align: "right",
    hideBelow: "sm",
    sort: { value: (episode) => episode.occurrences, kind: "number", first: "desc" },
    cell: (episode) => <span className="tabular-nums">{formatCount(episode.occurrences)}</span>,
  },
  {
    id: "last",
    header: "Last seen",
    hideBelow: "md",
    sort: { value: (episode) => episode.last_seen_at, kind: "time", first: "desc" },
    cell: (episode) => <span className="text-meta text-ink-muted">{formatIST(episode.last_seen_at)}</span>,
  },
  {
    id: "email",
    header: "Email",
    hideBelow: "sm",
    cell: (episode) => (
      <span className="text-meta">
        <EmailState episode={episode} />
      </span>
    ),
  },
];

function EpisodeDetail({ episode }: { episode: AlertEpisode }) {
  // `ids` is optional on the generated type (omitted when a call site passed none).
  const ids = Object.entries(episode.ids ?? {});
  return (
    <dl className="divide-y divide-line text-body">
      <DetailRow label="Kind" value={<SeverityPill severity={episode.severity} />} />
      <DetailRow
        label="Where"
        value={
          <>
            <MonoValue>{episode.stage}</MonoValue>
            <span className="ml-2 text-ink-muted">{episode.service}</span>
          </>
        }
      />
      <DetailRow label="Times" value={formatCount(episode.occurrences)} />
      <DetailRow label="Started" value={formatIST(episode.first_seen_at)} />
      <DetailRow label="Last seen" value={formatIST(episode.last_seen_at)} />
      <DetailRow label="Email" value={<EmailState episode={episode} />} />
      <DetailRow
        label="What happened"
        value={
          <>
            <span className="break-words">{episode.detail ?? "—"}</span>
            {ids.length > 0 && (
              <span className="mt-1 block break-words text-meta text-ink-muted">
                {ids.map(([key, value]) => `${key}=${String(value)}`).join(" · ")}
              </span>
            )}
          </>
        }
      />
    </dl>
  );
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-3">
      <dt className="text-meta text-ink-muted">{label}</dt>
      <dd className="min-w-0 text-ink">{value}</dd>
    </div>
  );
}
