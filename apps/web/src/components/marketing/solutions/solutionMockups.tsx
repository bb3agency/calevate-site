import type { ReactNode } from "react";

import { ArrowRight, Check, FileText, Search } from "lucide-react";

import { FollowUpMini, CampaignBoardMock } from "@/components/marketing/home/mockups/featureMockups";
import {
  Avatar,
  Chip,
  MaskedPhone,
  Panel,
  StatusPill,
  Tag,
  Window,
  type LeadStatus,
} from "@/components/marketing/home/mockups/kit";

/**
 * One console screen per job on `/solutions`, drawn at marketing scale from the screen
 * named above each function and filled with illustrative data (`home/mockups/kit.tsx`
 * states the rules: masked numbers, no rate or score, the console's words rather than its
 * wire values). Each composition stacks below `lg` and never overlaps its own panels.
 */

/** A toggle drawn in the console's `ToggleSwitch` shape. Static: nothing here is pressable. */
function Toggle({ on }: { on: boolean }) {
  return (
    <span
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full ${
        on ? "bg-brand-strong" : "bg-ink/15"
      }`}
    >
      <span
        className={`absolute h-4 w-4 rounded-full bg-white shadow-card ${on ? "left-[18px]" : "left-0.5"}`}
      />
    </span>
  );
}

/** A small card heading, in the console's card-title register. */
function CardTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <span className="flex items-center justify-between gap-3">
      <span className="text-[13px] font-semibold text-ink">{children}</span>
      {aside}
    </span>
  );
}

/* --------------------------------------------------------------------- answering */

/**
 * Answering — "Call log" (`app/c/[slug]/calls/CallsScreen.tsx`: outcome words with the
 * underscores replaced, as that screen prints them) beside the agent's opening-notice
 * toggles (`agents/panels/openingNotices.tsx`) and its handover switch
 * (`agents/panels/handover.tsx`), shown OFF because this platform cannot put a caller
 * through; the switch's own help line says what happens instead.
 */
export function AnsweringMock() {
  const calls = [
    { time: "6:12 AM", tail: "417", summary: "Wants the first slot tomorrow", outcome: "resolved", after: true },
    { time: "10:05 AM", tail: "208", summary: "Asked if Saturday is open", outcome: "resolved", after: false },
    { time: "1:40 PM", tail: "553", summary: "Asked for the manager — call-back offered", outcome: "needs follow up", after: false },
    { time: "9:52 PM", tail: "731", summary: "Toothache — booked a morning visit", outcome: "resolved", after: true },
    { time: "11:47 PM", tail: "096", summary: "Asked about braces for adults", outcome: "needs follow up", after: true },
  ] as const;
  return (
    <span className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] lg:items-start">
      <Window title="Call log" actions={<Chip tone="brand">Telugu</Chip>}>
        <span className="flex items-center gap-3 border-b border-line bg-app/60 px-4 py-2 text-[11px] font-semibold text-ink-muted">
          <span className="w-16 shrink-0">Time</span>
          <span className="hidden w-28 shrink-0 sm:block">Caller</span>
          <span className="min-w-0 flex-1">Summary</span>
          <span className="hidden w-28 shrink-0 min-[480px]:block">Outcome</span>
        </span>
        {calls.map(({ time, tail, summary, outcome, after }, i) => (
          <span
            key={time}
            className={`mk-rise mk-s${i + 1} flex items-center gap-3 border-b border-line px-4 py-2.5 text-[12px] last:border-b-0 ${
              after ? "bg-brand-soft/40" : ""
            }`}
          >
            <span className="flex w-16 shrink-0 flex-col">
              <span className="font-mono text-[11px] font-semibold text-ink">{time}</span>
              {after && <span className="text-[10px] font-medium text-brand-strong">after hours</span>}
            </span>
            <MaskedPhone tail={tail} className="hidden w-28 shrink-0 sm:block" />
            <span className="min-w-0 flex-1 truncate text-ink">{summary}</span>
            <span className="hidden w-28 shrink-0 min-[480px]:block">
              <Tag tone={outcome === "resolved" ? "brand" : "amber"}>{outcome}</Tag>
            </span>
          </span>
        ))}
        <span className="grid grid-cols-1 gap-2 border-t border-line bg-app/50 p-3 min-[400px]:grid-cols-2">
          <span className="flex flex-col rounded-lg border border-line bg-surface px-3 py-2">
            <span className="text-[11px] text-ink-muted">Calls today</span>
            <span className="text-lg leading-tight font-semibold text-ink tabular-nums">14</span>
          </span>
          <span className="flex flex-col rounded-lg border border-line bg-surface px-3 py-2">
            <span className="text-[11px] text-ink-muted">Captured after hours</span>
            <span className="text-lg leading-tight font-semibold text-ink tabular-nums">5</span>
          </span>
        </span>
      </Window>

      <span className="flex flex-col gap-4">
        <Panel elevation="raised" className="mk-rise mk-s2 flex flex-col gap-3 p-4">
          <CardTitle>Opening notices</CardTitle>
          {[
            ["Say it is an AI assistant", "Spoken first, before anything else, in your language."],
            ["Say the call is being recorded", "Spoken with the line above, at the start of the call."],
          ].map(([label, help]) => (
            <span key={label} className="flex items-start gap-3 rounded-lg border border-line px-3 py-2.5">
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-[12px] font-semibold text-ink">{label}</span>
                <span className="text-[11px] leading-snug text-ink-muted">{help}</span>
              </span>
              <Toggle on />
            </span>
          ))}
        </Panel>
        <Panel elevation="raised" className="mk-rise mk-s3 flex flex-col gap-2 p-4">
          <CardTitle>Handover</CardTitle>
          <span className="flex items-start gap-3 rounded-lg border border-line px-3 py-2.5">
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="text-[12px] font-semibold text-ink">Let this agent put callers through</span>
              <span className="text-[11px] leading-snug text-ink-muted">
                Off means callers who ask for a person are offered a call-back instead.
              </span>
            </span>
            <Toggle on={false} />
          </span>
        </Panel>
      </span>
    </span>
  );
}

/* --------------------------------------------------------------------- follow-up */

/**
 * Follow-up — the "New campaign" form's contact box (`campaigns/NewCampaignFlow.tsx`:
 * "Contact list", "Paste your CSV, or one number per line.", "Calls at the same time"),
 * a web enquiry becoming a first call (the homepage's `FollowUpMini`), and the running
 * campaign (`CampaignBoardMock`, `campaigns/CampaignDetail.tsx`).
 */
export function FollowUpMock() {
  const pasted = ["417", "208", "553", "731", "096"] as const;
  return (
    <span className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] lg:items-start">
      <span className="flex flex-col gap-4">
        <Panel elevation="raised" className="mk-rise mk-s1 flex flex-col gap-3 p-4">
          <CardTitle>New campaign</CardTitle>
          <span className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold text-ink-muted">Contact list</span>
            <span className="flex flex-col gap-0.5 rounded-lg border border-line bg-app/60 px-3 py-2">
              {pasted.map((tail) => (
                <MaskedPhone key={tail} tail={tail} />
              ))}
            </span>
            <span className="text-[11px] text-ink-muted">Paste your CSV, or one number per line.</span>
          </span>
          <span className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2 text-[12px]">
            <span className="text-ink-muted">Calls at the same time</span>
            <span className="font-semibold text-ink tabular-nums">5</span>
          </span>
          <span className="flex justify-end">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-strong px-4 py-1.5 text-[12px] font-semibold text-white">
              Create campaign
            </span>
          </span>
        </Panel>
        <Panel elevation="raised" className="mk-rise mk-s2 p-4">
          <FollowUpMini />
        </Panel>
      </span>
      <span className="mk-rise mk-s3 min-w-0">
        <CampaignBoardMock />
      </span>
    </span>
  );
}

/* ----------------------------------------------------------------- qualification */

/**
 * Qualification — "Leads" (`app/c/[slug]/leads`: the search placeholder, the six status
 * words, the property template's columns from `scripts/seed.py`) beside the performance
 * screen's funnel card "From calls to customers" (`performance/PerformanceCharts.tsx`).
 * Counts only, no rate: the console's own rate tiles are left out of a public page.
 */
export function QualificationMock() {
  const rows: readonly { name: string; status: LeadStatus; budget: string; area: string; bhk: string; visit: string }[] = [
    { name: "Kiran Reddy", status: "hot", budget: "80", area: "Gachibowli", bhk: "3BHK", visit: "Yes" },
    { name: "Lakshmi Prasad", status: "interested", budget: "65", area: "Kondapur", bhk: "2BHK", visit: "Yes" },
    { name: "Suresh Babu", status: "contacted", budget: "120", area: "Kokapet", bhk: "4BHK+", visit: "No" },
    { name: "Farhan Ali", status: "new", budget: "45", area: "Miyapur", bhk: "2BHK", visit: "No" },
    { name: "Divya Teja", status: "won", budget: "90", area: "Narsingi", bhk: "3BHK", visit: "Yes" },
    { name: "Ramesh Goud", status: "lost", budget: "—", area: "Not sure yet", bhk: "—", visit: "No" },
  ];
  const funnel = [
    { label: "Calls in the period", n: "186", w: "w-full" },
    { label: "Of those, connected", n: "142", w: "w-[76%]" },
    { label: "Turned into leads", n: "118", w: "w-[63%]" },
    { label: "Leads qualified", n: "37", w: "w-[20%]" },
  ] as const;
  const statuses: readonly LeadStatus[] = ["new", "contacted", "interested", "hot", "won", "lost"];
  return (
    <span className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] lg:items-start">
      <Window title="Leads" actions={<Chip>Export this view as CSV</Chip>}>
        <span className="flex flex-col gap-2.5 border-b border-line px-4 py-3">
          <span className="flex items-center gap-2 rounded-lg border border-line bg-app/60 px-3 py-1.5 text-[12px] text-ink-muted">
            <Search aria-hidden className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">What did they ask for? e.g. 3BHK in Gachibowli</span>
          </span>
          <span className="flex flex-wrap gap-1.5">
            <Chip tone="brand">All</Chip>
            {statuses.map((status) => (
              <StatusPill key={status} status={status} />
            ))}
          </span>
        </span>
        <span className="flex items-center gap-3 border-b border-line bg-app/60 px-4 py-2 text-[11px] font-semibold text-ink-muted">
          <span className="min-w-0 flex-1 sm:w-36 sm:flex-none">Name</span>
          <span className="w-20 shrink-0">Status</span>
          <span className="hidden w-24 shrink-0 min-[480px]:block">Budget (lakhs)</span>
          <span className="hidden min-w-0 flex-1 sm:block">Location</span>
          <span className="hidden w-14 shrink-0 md:block">BHK</span>
          <span className="hidden w-16 shrink-0 xl:block">Site visit</span>
        </span>
        {rows.map((row, i) => (
          <span
            key={row.name}
            className={`mk-rise mk-s${i + 1} flex items-center gap-3 border-b border-line px-4 py-2.5 text-[12px] last:border-b-0 ${
              i === 0 ? "bg-amber-50/70" : ""
            }`}
          >
            <span className="flex min-w-0 flex-1 items-center gap-2 sm:w-36 sm:flex-none">
              <Avatar name={row.name} className="h-6 w-6" tone={i === 0 ? "brand" : "base"} />
              <span className="truncate font-semibold text-ink">{row.name}</span>
            </span>
            <span className="w-20 shrink-0">
              <StatusPill status={row.status} />
            </span>
            <span className="hidden w-24 shrink-0 text-ink tabular-nums min-[480px]:block">{row.budget}</span>
            <span className="hidden min-w-0 flex-1 truncate text-ink sm:block">{row.area}</span>
            <span className="hidden w-14 shrink-0 text-ink-muted md:block">{row.bhk}</span>
            <span className="hidden w-16 shrink-0 text-ink-muted xl:block">{row.visit}</span>
          </span>
        ))}
      </Window>

      <span className="flex flex-col gap-4">
        <Panel elevation="raised" className="mk-rise mk-s2 flex flex-col gap-3 p-4">
          <CardTitle aside={<span className="text-[11px] text-ink-muted">Last 30 days</span>}>
            From calls to customers
          </CardTitle>
          {funnel.map(({ label, n, w }) => (
            <span key={label} className="flex flex-col gap-1">
              <span className="flex items-center justify-between gap-3 text-[12px]">
                <span className="text-ink-muted">{label}</span>
                <span className="font-semibold text-ink tabular-nums">{n}</span>
              </span>
              <span className="block h-2 overflow-hidden rounded-full bg-slate-100">
                <span className={`block h-full rounded-full bg-brand ${w}`} />
              </span>
            </span>
          ))}
        </Panel>
        <Panel elevation="overlay" className="mk-rise mk-s4 flex items-center gap-3 border-amber-200 p-3">
          <span className="h-2 w-2 shrink-0 rounded-full bg-amber-500" />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="text-[12px] font-semibold text-ink">Hot lead · Kiran Reddy</span>
            <span className="truncate text-[11px] text-ink-muted">Wants to buy this month, site visit Saturday</span>
          </span>
          <StatusPill status="hot" />
        </Panel>
      </span>
    </span>
  );
}

/* ------------------------------------------------------------------ appointments */

/**
 * Appointments — "Call-backs" (`app/c/[slug]/callbacks/page.tsx`: the group words
 * "Waiting", "Calling now", "Called", the "They said:" note, "Call it off", "Too late to
 * stop") beside a day of the clinic's Google Calendar: what the agent asked about (busy and
 * free, the `calendar.freebusy` scope) and the one event it added (`calendar.events`).
 */
export function AppointmentsMock() {
  const callbacks = [
    { heading: "Calling now", tail: "731", when: "Today, 4:00 PM", note: null, action: "Too late to stop" },
    { heading: "Waiting", tail: "417", when: "Tue, 4:00 PM", note: "Ring me Tuesday at four", action: "Call it off" },
    { heading: "Waiting", tail: "208", when: "Wed, 11:30 AM", note: "After my shift ends", action: "Call it off" },
    { heading: "Called", tail: "553", when: "Yesterday, 6:15 PM", note: null, action: null },
  ] as const;
  const day = [
    { time: "4 PM", kind: "busy", label: "Busy" },
    { time: "5 PM", kind: "free", label: "Free" },
    { time: "6 PM", kind: "new", label: "Check-up · Priya Reddy" },
    { time: "7 PM", kind: "free", label: "Free" },
  ] as const;
  return (
    <span className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:items-start">
      <Window title="Call-backs" actions={<Chip>Show only the ones still to come</Chip>}>
        {callbacks.map(({ heading, tail, when, note, action }, i) => (
          <span
            key={tail}
            className={`mk-rise mk-s${i + 1} flex items-start gap-3 border-b border-line px-4 py-3 last:border-b-0`}
          >
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="flex flex-wrap items-center gap-x-2 text-[12px] text-ink">
                <MaskedPhone tail={tail} className="text-ink" />
                <span className="text-ink-muted">·</span>
                <span>{when}</span>
              </span>
              <span className="text-[11px] font-medium text-ink-muted">{heading}</span>
              {note && <span className="text-[11px] text-ink-muted italic">They said: {note}</span>}
            </span>
            {action && (
              <span
                className={`shrink-0 text-[12px] font-medium text-ink-muted ${
                  action === "Call it off" ? "underline underline-offset-2" : ""
                }`}
              >
                {action}
              </span>
            )}
          </span>
        ))}
      </Window>

      <Panel elevation="raised" className="mk-rise mk-s3 flex flex-col gap-3 p-4">
        <CardTitle aside={<Tag tone="emerald">Connected</Tag>}>Google Calendar · Tuesday</CardTitle>
        {day.map(({ time, kind, label }) => (
          <span key={time} className="flex items-stretch gap-3">
            <span className="w-11 shrink-0 pt-2 font-mono text-[11px] text-ink-muted">{time}</span>
            <span
              className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-2 text-[12px] ${
                kind === "busy"
                  ? "bg-slate-100 text-ink-muted"
                  : kind === "new"
                    ? "border border-brand/40 bg-brand-soft/60 font-semibold text-ink shadow-card"
                    : "border border-dashed border-line text-ink-muted"
              }`}
            >
              {kind === "new" && <Check aria-hidden className="h-3.5 w-3.5 shrink-0 text-brand-strong" strokeWidth={2.5} />}
              <span className="truncate">{label}</span>
            </span>
          </span>
        ))}
        <span className="text-[11px] text-ink-muted">Booked during the call, into a free slot.</span>
      </Panel>
    </span>
  );
}

/* ---------------------------------------------------------------------- delivery */

/**
 * Your own tools — "Integrations" (`app/c/[slug]/integrations`: "Your endpoints", "Your
 * signing secret", the `X-Calevate-Signature` header, "Send events to a Google Sheet",
 * "Google connection ready", and the "Delivery log" columns Event / Result / Tries / When
 * with its `delivered` / `failed` badges). Event names are the API's own
 * (`apps/api/integrations`). The endpoint uses the reserved `.example` domain.
 */
export function DeliveryMock() {
  const log = [
    { event: "lead.created", result: "delivered", tries: "1", when: "10:44 AM" },
    { event: "call.completed", result: "delivered", tries: "1", when: "10:44 AM" },
    { event: "lead.updated", result: "failed", tries: "3", when: "9:12 AM" },
    { event: "lead.created", result: "delivered", tries: "2", when: "8:57 AM" },
  ] as const;
  return (
    <span className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] lg:items-start">
      <span className="flex flex-col gap-4">
        <Panel elevation="raised" className="mk-rise mk-s1 flex flex-col gap-3 p-4">
          <CardTitle>Your endpoints</CardTitle>
          <span className="flex flex-col gap-2 rounded-lg border border-line px-3 py-2.5">
            <span className="truncate font-mono text-[12px] text-ink">https://your-crm.example/leads</span>
            <span className="flex flex-wrap gap-1.5">
              <Chip>lead.created</Chip>
              <Chip>call.completed</Chip>
            </span>
          </span>
          <span className="flex flex-col gap-1 rounded-lg bg-app px-3 py-2">
            <span className="text-[11px] font-semibold text-ink-muted">Your signing secret</span>
            <span className="font-mono text-[12px] text-ink">••••••••••••3f9a</span>
            <span className="text-[11px] text-ink-muted">
              Sent as <span className="font-mono text-ink">X-Calevate-Signature</span>
            </span>
          </span>
        </Panel>
        <Panel elevation="raised" className="mk-rise mk-s2 flex items-center gap-3 p-4">
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-[13px] font-semibold text-ink">Send events to a Google Sheet</span>
            <span className="truncate text-[11px] text-ink-muted">Leads tab · Sunrise Dental enquiries</span>
          </span>
          <Tag tone="emerald">Google connection ready</Tag>
        </Panel>
      </span>

      <Window title="Delivery log" actions={<Chip>Export this view as CSV</Chip>}>
        <span className="flex items-center gap-3 border-b border-line bg-app/60 px-4 py-2 text-[11px] font-semibold text-ink-muted">
          <span className="min-w-0 flex-1">Event</span>
          <span className="w-20 shrink-0">Result</span>
          <span className="hidden w-10 shrink-0 min-[420px]:block">Tries</span>
          <span className="w-16 shrink-0 text-right">When</span>
        </span>
        {log.map(({ event, result, tries, when }, i) => (
          <span
            key={`${event}-${when}-${tries}`}
            className={`mk-rise mk-s${i + 1} flex items-center gap-3 border-b border-line px-4 py-2.5 text-[12px] last:border-b-0`}
          >
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-ink">{event}</span>
            <span className="w-20 shrink-0">
              <Tag tone={result === "delivered" ? "emerald" : "amber"}>{result}</Tag>
            </span>
            <span className="hidden w-10 shrink-0 text-ink-muted tabular-nums min-[420px]:block">{tries}</span>
            <span className="w-16 shrink-0 text-right text-[11px] text-ink-muted">{when}</span>
          </span>
        ))}
      </Window>
    </span>
  );
}

/* ----------------------------------------------------------------------- answers */

/**
 * Your answers — "Knowledge base" (`app/c/[slug]/knowledge`: the "Add knowledge" form's
 * "What this knowledge is about" / "What the agent should say" / "Add to agent", facts
 * "Live", and "Files and web pages" with an upload at "Being read" — `knowledge/uploadCopy.ts`).
 */
export function AnswersMock() {
  const facts = [
    { topic: "Sunday timings", says: "Sundays 10 AM to 1 PM, by appointment only.", state: "Live", tone: "emerald" },
    { topic: "Braces for adults", says: "Yes — a consultation first, with Dr Rao.", state: "Live", tone: "emerald" },
    { topic: "Parking", says: "Free parking behind the building.", state: "Live", tone: "emerald" },
  ] as const;
  return (
    <span className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] lg:items-start">
      <Panel elevation="raised" className="mk-rise mk-s1 flex flex-col gap-3 p-4">
        <CardTitle>Add knowledge</CardTitle>
        <span className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold text-ink-muted">What this knowledge is about</span>
          <span className="rounded-lg border border-line px-3 py-2 text-[12px] text-ink">Root canal</span>
        </span>
        <span className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold text-ink-muted">What the agent should say</span>
          <span className="rounded-lg border border-brand/50 px-3 py-2 text-[12px] leading-snug text-ink">
            The cost depends on the tooth. Offer a check-up with Dr Rao first, and book it.
          </span>
        </span>
        <span className="flex justify-end">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-strong px-4 py-1.5 text-[12px] font-semibold text-white">
            Add to agent
            <ArrowRight aria-hidden className="h-3 w-3" />
          </span>
        </span>
      </Panel>

      <Window title="Knowledge base">
        {facts.map(({ topic, says, state, tone }, i) => (
          <span
            key={topic}
            className={`mk-rise mk-s${i + 1} flex items-start gap-3 border-b border-line px-4 py-3 text-[12px]`}
          >
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="font-semibold text-ink">{topic}</span>
              <span className="text-ink-muted">{says}</span>
            </span>
            <Tag tone={tone}>{state}</Tag>
          </span>
        ))}
        <span className="flex flex-col gap-2 bg-app/50 px-4 py-3">
          <span className="text-[11px] font-semibold text-ink-muted">Files and web pages</span>
          <span className="mk-rise mk-s4 flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2">
            <FileText aria-hidden className="h-4 w-4 shrink-0 text-ink-muted" />
            <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ink">Price list.pdf</span>
            <Tag tone="sky">Being read</Tag>
          </span>
        </span>
      </Window>
    </span>
  );
}
