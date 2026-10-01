import type { ReactNode } from "react";

import { StatusPill, Tag } from "./kit";

/**
 * One small piece of real UI per capability, so each card in "What it does" SHOWS the job
 * rather than decorating it with an icon. Each vignette is drawn from the console screen
 * named in its comment; people and times are illustrative.
 */

/** A row in a small list: the same rhythm in every vignette. */
function Line({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={`flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-[12px] shadow-card ${className}`}
    >
      {children}
    </span>
  );
}

/**
 * Answering — "Call logs": calls across a whole day, the late one included. The times are
 * the point (the agent answers at every hour unless told otherwise,
 * `apps/api/agents/business_hours.py`), so they lead each row.
 */
export function AnsweringVignette() {
  const calls = [
    { time: "7:02 AM", summary: "Wants the first slot tomorrow" },
    { time: "2:15 PM", summary: "Asked if Saturday is open" },
    { time: "11:47 PM", summary: "Toothache — booked a morning visit", late: true },
  ] as const;
  return (
    <span className="flex flex-col gap-1.5">
      {calls.map(({ time, summary, ...rest }, i) => (
        <Line key={time} className={`mk-rise mk-s${i + 1} ${"late" in rest ? "ring-1 ring-brand/30" : ""}`}>
          <span className="w-16 shrink-0 font-mono text-[11px] font-semibold text-ink">{time}</span>
          <span className="min-w-0 flex-1 truncate text-ink">{summary}</span>
          <Tag tone="emerald" className="hidden min-[420px]:inline-flex">
            completed
          </Tag>
        </Line>
      ))}
      <span className="mt-1 text-[11px] text-ink-muted">Captured after hours, counted on your dashboard</span>
    </span>
  );
}

/**
 * Follow-up — a campaign contact's attempts: the retry ladder working a no-answer
 * (`apps/workers/campaign_dispatch.py`), contact states as `campaigns` prints them.
 */
export function FollowUpVignette() {
  return (
    <span className="flex flex-col gap-1.5">
      <Line>
        <span className="min-w-0 flex-1 truncate font-semibold text-ink">Sneha Rao</span>
        <span className="text-[11px] text-ink-muted">Website form</span>
      </Line>
      <span className="ml-4 flex flex-col gap-1.5 border-l border-dashed border-ink/20 pl-3">
        <span className="mk-rise mk-s1 flex items-center justify-between gap-2 text-[12px]">
          <span className="text-ink-muted">First call</span>
          <Tag tone="amber">no answer</Tag>
        </span>
        <span className="mk-rise mk-s2 flex items-center justify-between gap-2 text-[12px]">
          <span className="text-ink-muted">Retry</span>
          <Tag tone="emerald">connected</Tag>
        </span>
      </span>
    </span>
  );
}

/**
 * Qualification — two leads, sorted, each with the captured field that put it there, and
 * the console's own history line for the alert (`apps/api/crm/service.py`).
 */
export function QualificationVignette() {
  return (
    <span className="flex flex-col gap-1.5">
      <Line className="mk-rise mk-s1">
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate font-semibold text-ink">Ravi Kumar</span>
          <span className="truncate text-[11px] text-ink-muted">Urgency: emergency</span>
        </span>
        <StatusPill status="hot" />
      </Line>
      <Line className="mk-rise mk-s2">
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate font-semibold text-ink">Sneha Rao</span>
          <span className="truncate text-[11px] text-ink-muted">Urgency: this week</span>
        </span>
        <StatusPill status="interested" />
      </Line>
      <span className="mk-rise mk-s3 flex items-center gap-2 px-1 text-[11px] text-ink-muted">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
        Hot-lead alert sent by WhatsApp
      </span>
    </span>
  );
}

/** Appointments — a booked slot and a call-back, as the call's outcome records them. */
export function AppointmentsVignette() {
  return (
    <span className="flex flex-col gap-1.5">
      <Line className="mk-rise mk-s1">
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate font-semibold text-ink">Tue, 6:00 PM</span>
          <span className="truncate text-[11px] text-ink-muted">Check-up · Priya Reddy</span>
        </span>
        <Tag tone="emerald">Booked</Tag>
      </Line>
      <Line className="mk-rise mk-s2">
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate font-semibold text-ink">Tomorrow, 11:00 AM</span>
          <span className="truncate text-[11px] text-ink-muted">Call-back · Karthik Varma</span>
        </span>
        <Tag tone="sky">Call-back</Tag>
      </Line>
    </span>
  );
}

/**
 * Your own tools — the integrations "Delivery log", with its real states (`delivered`,
 * `failed`, from `integrations/DeliveryLog.tsx`) and a failure that was retried.
 */
export function ToolsVignette() {
  const rows = [
    { to: "Google Sheet", lead: "Priya Reddy", status: "delivered" },
    { to: "Your CRM", lead: "Ravi Kumar", status: "failed" },
    { to: "Your CRM", lead: "Ravi Kumar · retried", status: "delivered" },
  ] as const;
  return (
    <span className="flex flex-col gap-1.5">
      {rows.map(({ to, lead, status }, i) => (
        <Line key={lead} className={`mk-rise mk-s${i + 1}`}>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate font-semibold text-ink">{to}</span>
            <span className="truncate text-[11px] text-ink-muted">{lead}</span>
          </span>
          <Tag tone={status === "delivered" ? "emerald" : "amber"}>{status}</Tag>
        </Line>
      ))}
    </span>
  );
}

/**
 * Your answers — facts on the knowledge screen, live on the agent ("Live",
 * `knowledge/SubmittedList.tsx`). There is no review state to show for what the business
 * adds (D-658).
 */
export function AnswersVignette() {
  return (
    <span className="flex flex-col gap-1.5">
      <Line className="mk-rise mk-s1 items-start">
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="font-semibold text-ink">Are you open on Sundays?</span>
          <span className="text-ink-muted">Sundays 10 AM to 1 PM, by appointment only.</span>
        </span>
        <Tag tone="emerald">Live</Tag>
      </Line>
      <Line className="mk-rise mk-s2 items-start">
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="font-semibold text-ink">Do you do braces for adults?</span>
          <span className="text-ink-muted">Yes — consultation first, with Dr. Rao.</span>
        </span>
        <Tag tone="emerald">Live</Tag>
      </Line>
    </span>
  );
}
