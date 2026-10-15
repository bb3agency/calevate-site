"use client";

/**
 * Clients' WhatsApp, for the operator (D-784): whether Calevate's Meta app is set up, how
 * many new clients Meta's weekly limit has left, when Meta last delivered a webhook, and
 * each client's numbers with their templates.
 *
 * The weekly limit is Meta's: 10 new business customers in a rolling 7 days until business
 * verification, app review and access verification are done, then 200
 * (embedded-signup/overview.md, read 15 Oct 2026). The count is ours (successful connects in
 * the audit log); WhatsApp Manager > Partner overview shows Meta's own.
 */

import { ChecklistRows, type ChecklistRow } from "@/components/console/checklist";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { ProgressBar } from "@/components/interior/progress-bar";
import { ProblemNotice, RestrictionNote, Skeleton, formatIST } from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import { useAdminWhatsApp, type AdminWhatsApp } from "@/lib/api/whatsapp";
import { useCopilotSurface } from "@/lib/copilot/registry";

/** A webhook silence longer than this, with clients connected, is worth a look. */
const QUIET_HOURS = 24;

function hoursSince(at: string | null | undefined): number | null {
  if (!at) return null;
  return (Date.now() - new Date(at).getTime()) / 3_600_000;
}

function setupRows(data: AdminWhatsApp): ChecklistRow[] {
  return [
    {
      id: "app",
      label: "Meta app ID and Embedded Signup configuration",
      status: data.configured ? "done" : "not_started",
      statusText: data.configured ? "Saved" : "Not saved",
      info: "Ops > Config > Integrations > Clients' WhatsApp. Steps 1 and 3 of runbooks/whatsapp-tech-provider.md.",
    },
    {
      id: "secret",
      label: "Meta app secret",
      status: data.app_secret_set ? "done" : "not_started",
      statusText: data.app_secret_set ? "Saved" : "Not saved",
      info: "Ops > Secrets. Signs every webhook and exchanges each client's signup code.",
    },
    {
      id: "token",
      label: "Webhook verify token",
      status: data.verify_token_set ? "done" : "not_started",
      statusText: data.verify_token_set ? "Saved" : "Not saved",
      info: `Ops > Secrets, then the same string in Meta with the callback URL https://api.calevate.tech${data.callback_path}.`,
    },
    {
      id: "coexistence",
      label: "Coexistence for WhatsApp Business app users",
      status: data.coexistence ? "done" : "waiting",
      statusText: data.coexistence ? "On" : "Off until Meta confirms India",
      info: "Off until Meta confirms coexistence is available for Indian numbers and app-sent messages can be shown.",
    },
  ];
}

export function WhatsAppAdminScreen() {
  const access = useAdminAccess("admin:tenants", "read clients' WhatsApp");
  const report = useAdminWhatsApp();
  const data = report.data;
  const accounts = data?.clients.flatMap((c) => c.accounts) ?? [];
  const quietFor = hoursSince(data?.last_event_at);
  const connected = accounts.filter((a) => a.status === "connected").length;

  useCopilotSurface({
    route: "/admin/ops/whatsapp",
    title: "Clients' WhatsApp",
    realm: "admin",
    fields: [],
    // Nothing here is editable: the screen reads.
    apply: () => undefined,
    facts: data
      ? [
          { key: "week", label: "New connections in the last 7 days", value: `${data.week_count} of ${data.weekly_limit}` },
          { key: "configured", label: "Meta app configured", value: data.configured ? "yes" : "no" },
          { key: "clients", label: "Clients with WhatsApp", value: String(data.clients.length) },
          { key: "connected", label: "Numbers connected", value: String(connected) },
          { key: "last_event", label: "Last heard from Meta", value: data.last_event_at ? formatIST(data.last_event_at) : "never" },
        ]
      : [],
  });

  return (
    <div className="max-w-4xl space-y-10 pb-12">
      <PageHeader description="Each client's own WhatsApp, connected through Meta with Calevate as the Tech Provider." />
      <RestrictionNote reason={access.refused ? access.reason : null} />
      {report.isPending ? (
        <Skeleton rows={6} />
      ) : report.isError ? (
        <ProblemNotice error={report.error} onRetry={() => void report.refetch()} />
      ) : data ? (
        <>
          <Section
            title="New clients this week"
            description="Meta limits how many new businesses a Tech Provider connects in any 7 days."
          >
            <div className="max-w-md space-y-2">
              <ProgressBar
                value={data.week_count}
                max={data.weekly_limit}
                label="New WhatsApp connections in the last 7 days"
                completeLabel="Limit reached"
              />
              <p className="text-body text-ink">
                <span className="text-figure tabular-nums">{data.week_count}</span>
                <span className="text-ink-muted"> of {data.weekly_limit} used</span>
              </p>
              <p className="text-meta text-ink-muted">
                {data.weekly_limit <= 10
                  ? "Meta raises this to 200 after business verification, app review and access verification."
                  : "Meta's raised limit is in use."}
              </p>
            </div>
          </Section>

          <ChecklistRows heading="Calevate's Meta set-up" headingLevel={2} rows={setupRows(data)} />

          <Section
            title="Webhooks"
            description="Meta tells us about template reviews, account problems and failed messages."
          >
            <p className="flex flex-wrap items-center gap-3 text-body text-ink">
              <StatusPill
                tone={
                  data.last_event_at === null
                    ? connected > 0
                      ? "warn"
                      : "neutral"
                    : quietFor !== null && quietFor > QUIET_HOURS && connected > 0
                      ? "warn"
                      : "ok"
                }
              >
                {data.last_event_at === null ? "Nothing received yet" : `Last heard ${formatIST(data.last_event_at)}`}
              </StatusPill>
              <span className="text-meta text-ink-muted [overflow-wrap:anywhere]">
                Callback https://api.calevate.tech{data.callback_path}
              </span>
            </p>
          </Section>

          <Section title="Clients" description="Every client with a WhatsApp number connected through Meta.">
            {data.clients.length === 0 ? (
              <p className="text-body text-ink-muted">No client has connected WhatsApp through Meta yet.</p>
            ) : (
              <ul className="divide-y divide-line border-y border-line">
                {data.clients.flatMap((client) =>
                  client.accounts.map((a) => (
                    <li key={a.id} className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2 py-3.5">
                      <div className="min-w-0">
                        <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">
                          {client.name}
                          <span className="font-normal text-ink-muted"> · {a.verified_name ?? "name pending"}</span>
                        </p>
                        <p className="text-meta text-ink-muted">
                          {a.display_phone_number ?? "number pending"} · quality {a.quality_rating?.toLowerCase() ?? "unknown"} ·
                          limit {a.messaging_limit ?? "unknown"} · templates {a.templates_approved} approved,{" "}
                          {a.templates_pending} waiting, {a.templates_rejected} refused
                        </p>
                        {(a.setup_error || a.account_alert || a.last_send_error) && (
                          <p className="text-meta text-ink">
                            {[
                              a.setup_error && `Set-up: ${a.setup_error}`,
                              a.account_alert && `Meta: ${a.account_alert}`,
                              a.last_send_error && `Last failed send: ${a.last_send_error}`,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </p>
                        )}
                      </div>
                      <StatusPill
                        tone={a.status === "connected" ? "ok" : a.status === "needs_attention" ? "warn" : "neutral"}
                      >
                        {a.status === "connected"
                          ? "Connected"
                          : a.status === "needs_attention"
                            ? "Needs attention"
                            : a.status === "connecting"
                              ? "Setting up"
                              : "Disconnected"}
                      </StatusPill>
                    </li>
                  )),
                )}
              </ul>
            )}
          </Section>
        </>
      ) : null}
    </div>
  );
}
