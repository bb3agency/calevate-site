import type { ReactNode } from "react";

import { Eye, PhoneOff, ShieldCheck } from "lucide-react";

import { Bar, MaskedPhone, Panel, Tag } from "@/components/marketing/home/mockups/kit";
import { NOTICE_TONES } from "@/components/ui";

/**
 * The controls `/security` talks about, drawn as the console draws them. Labels are the
 * console's own and each mockup names its source screen; people and times are made up, and
 * numbers carry the `+91 98XXX XX123` mask (see `home/mockups/kit.tsx` for the rules).
 *
 * Every sentence a mockup prints is either a console label or a line the page already
 * states. A mockup is not allowed to say something about a control the page does not.
 */

/** One transcript turn without a translation line: the redaction is the subject here. */
function Line({ who, children }: { who: "Agent" | "Caller"; children: ReactNode }) {
  const agent = who === "Agent";
  return (
    <span className={`flex ${agent ? "justify-start" : "justify-end"}`}>
      <span
        className={`flex max-w-[88%] flex-col gap-0.5 rounded-xl px-3 py-2 ${
          agent ? "rounded-bl-sm bg-brand-soft" : "rounded-br-sm bg-slate-100"
        }`}
      >
        <span className={`text-[11px] font-semibold ${agent ? "text-brand-strong" : "text-slate-600"}`}>
          {who}
        </span>
        <span className="text-[13px] leading-snug text-ink">{children}</span>
      </span>
    </span>
  );
}

/** A redaction mark as `apps/workers/redaction.py` writes it (`PHONE_MASK`, `MASK`). */
function Masked({ children }: { children: ReactNode }) {
  return (
    <span className="rounded bg-ink/[0.07] px-1 font-mono text-[12px] whitespace-nowrap text-ink-muted">
      {children}
    </span>
  );
}

/**
 * The "Transcript" card of an opened call (`calls/[callId]/TranscriptCard.tsx`) as a staff
 * member sees it: the "Show full transcript" control refused, the reason under it
 * (`transcriptAccess.tsx`), the redaction notice, and turns with the redaction marks in.
 */
export function RedactedTranscriptMock() {
  return (
    <Panel elevation="raised" className="flex flex-col gap-3 p-4 sm:p-5">
      <span className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[14px] font-semibold text-ink">Transcript</span>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-ink-muted opacity-50">
          <Eye className="h-3.5 w-3.5" />
          Show full transcript
        </span>
      </span>
      <span className="mk-rise mk-s1 rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-muted">
        Only an account owner can open the full transcript.
      </span>
      <span
        className={`mk-rise mk-s2 flex items-start gap-2 rounded-lg border px-3 py-2 text-[12px] leading-snug ${NOTICE_TONES.neutral}`}
      >
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Personal details — phone numbers, account numbers, dates of birth — are hidden in this
        view.
      </span>
      <span className="mk-rise mk-s3 flex flex-col gap-2">
        <Line who="Agent">Which number should we send the site-visit details to?</Line>
        <Line who="Caller">
          This one is fine — <Masked>[phone ••23]</Masked>.
        </Line>
        <Line who="Agent">Thank you. And your date of birth, for the loan pre-check?</Line>
        <Line who="Caller">
          It is <Masked>[redacted]</Masked>.
        </Line>
      </span>
    </Panel>
  );
}

/**
 * Audit entries for the reads that write one: the full transcript, a recording and the
 * contact-list download (`apps/api/crm/routes.py` audits all three). Plain words rather than
 * the stored action names, which are identifiers rather than copy.
 */
export function AuditLogMock() {
  const rows = [
    { when: "Today, 10:47 AM", who: "Lakshmi Reddy", role: "Owner", what: "Opened the full transcript" },
    { when: "Today, 9:12 AM", who: "Lakshmi Reddy", role: "Owner", what: "Downloaded the contact list" },
    { when: "Yesterday, 6:30 PM", who: "Lakshmi Reddy", role: "Owner", what: "Played a call recording" },
  ] as const;
  return (
    <Panel elevation="raised" className="flex flex-col overflow-hidden">
      <span className="flex items-center justify-between gap-2 border-b border-line bg-app/70 px-4 py-2.5">
        <span className="text-[13px] font-semibold text-ink">Audit log</span>
      </span>
      {rows.map(({ when, who, role, what }, i) => (
        <span
          key={when}
          className={`mk-rise mk-s${i + 1} flex flex-col gap-1 border-b border-line px-4 py-3 last:border-b-0`}
        >
          <span className="text-[12px] font-semibold text-ink">{what}</span>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-muted">
            <span className="font-medium text-ink">{who}</span>
            <Tag tone="brand">{role}</Tag>
            <span className="font-mono">{when}</span>
          </span>
        </span>
      ))}
    </Panel>
  );
}

/**
 * The calling window on a new campaign (`campaigns/NewCampaignForm.tsx`): the platform's
 * 9am–9pm bound drawn on a day, and the optional narrower window inside it, with the form's
 * own "Only call during specific hours" and its caption.
 */
export function CallingWindowMock() {
  return (
    <span className="flex flex-col gap-3">
      <span className="mk-rise mk-s1 relative block h-10 overflow-hidden rounded-lg border border-line bg-slate-100">
        {/* 9am to 9pm on a midnight-to-midnight ribbon, and the narrowed 10am to 7pm window inside it. */}
        <span className="absolute inset-y-0 left-[37.5%] w-1/2 bg-brand-soft" />
        <span className="absolute inset-y-2 left-[41.7%] w-[37.5%] rounded bg-brand/45" />
      </span>
      <span className="flex justify-between font-mono text-[10px] text-ink-muted">
        <span>12 AM</span>
        <span>9 AM</span>
        <span>9 PM</span>
        <span>12 AM</span>
      </span>
      <span className="mk-rise mk-s2 flex flex-col gap-1.5 rounded-lg border border-line bg-surface p-3">
        <span className="flex items-center gap-2 text-[12px] font-medium text-ink">
          <span className="flex h-3.5 w-3.5 items-center justify-center rounded-sm bg-brand-strong text-[9px] text-white">
            ✓
          </span>
          Only call during specific hours
        </span>
        <span className="flex gap-2">
          {[
            ["From", "10:00"],
            ["To", "19:00"],
          ].map(([label, value]) => (
            <span key={label} className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="text-[11px] text-ink-muted">{label}</span>
              <span className="rounded-md border border-line px-2 py-1 font-mono text-[12px] text-ink">
                {value}
              </span>
            </span>
          ))}
        </span>
        <span className="text-[11px] leading-snug text-ink-muted">
          Calls never go out before 9am or after 9pm — this narrows that further.
        </span>
      </span>
    </span>
  );
}

/**
 * The do-not-call screen (`app/c/[slug]/do-not-call`): "Check a number" with its
 * suppressed verdict, and two rows of "Suppressed numbers" with their source labels
 * (`do-not-call/sources.ts`) — a caller's own opt-out carries no Remove control.
 */
export function DoNotCallMock() {
  const rows = [
    { tail: "123", source: "Opted out on a call", removable: false },
    { tail: "908", source: "Added by your team", removable: true },
  ] as const;
  return (
    <span className="flex flex-col gap-2">
      <span className="mk-rise mk-s1 flex flex-col gap-2 rounded-lg border border-line bg-surface p-3 shadow-card">
        <span className="text-[12px] font-semibold text-ink">Check a number</span>
        <span className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate rounded-md border border-line px-2 py-1">
            <MaskedPhone />
          </span>
          <span className="rounded-full bg-brand-strong px-3 py-1 text-[11px] font-semibold text-white">
            Check
          </span>
        </span>
        <span
          className={`flex items-start gap-2 rounded-md border px-2.5 py-2 text-[11px] leading-snug ${NOTICE_TONES.stop}`}
        >
          <PhoneOff className="mt-0.5 h-3 w-3 shrink-0" />
          This number is suppressed — no agent will call it. It was added to your account&apos;s list.
        </span>
      </span>
      <span className="mk-rise mk-s2 flex flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-card">
        <span className="border-b border-line bg-app/70 px-3 py-2 text-[11px] font-semibold text-ink-muted">
          Suppressed numbers
        </span>
        {rows.map(({ tail, source, removable }) => (
          <span
            key={tail}
            className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-line px-3 py-2 last:border-b-0"
          >
            <MaskedPhone tail={tail} />
            <span className="text-[11px] text-ink-muted">{source}</span>
            <span className="ml-auto text-[11px] font-medium text-ink-muted">
              {removable ? (
                <span className="rounded-md px-2 py-0.5 ring-1 ring-line">Remove</span>
              ) : (
                "Permanent"
              )}
            </span>
          </span>
        ))}
      </span>
    </span>
  );
}

/**
 * "What it says at the start of every call" (`agents/panels/openingNotices.tsx`): the two
 * per-agent switches with the agent's own sentence quoted, under the guarantee that heads
 * the panel. Only the guarantee's first sentence is printed — it is the half the page's own
 * card already states.
 */
export function OpeningNoticesMock() {
  const toggles = [
    { label: "Say it is an AI assistant", on: true, quote: "I am an AI assistant." },
    { label: "Say the call is being recorded", on: true, quote: "This call is recorded." },
  ] as const;
  return (
    <span className="flex flex-col gap-2">
      <span className="text-[12px] font-semibold text-ink">What it says at the start of every call</span>
      <span
        className={`mk-rise mk-s1 flex items-start gap-2 rounded-lg border px-3 py-2 text-[11px] leading-snug ${NOTICE_TONES.neutral}`}
      >
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Whatever these settings say, the agent always answers honestly when a caller asks.
      </span>
      {toggles.map(({ label, on, quote }, i) => (
        <span
          key={label}
          className={`mk-rise mk-s${i + 2} flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2 shadow-card`}
        >
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-[12px] font-medium text-ink">{label}</span>
            <span className="truncate text-[11px] text-ink-muted italic">“{quote}”</span>
          </span>
          <span
            className={`flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 ${
              on ? "justify-end bg-brand-strong" : "justify-start bg-ink/15"
            }`}
          >
            <span className="h-4 w-4 rounded-full bg-white shadow-card" />
          </span>
        </span>
      ))}
    </span>
  );
}

/**
 * "How long you keep it" on the caller notice (`caller-notice/page.tsx`), with the
 * category labels `apps/api/compliance/caller_notice.py` prints, and
 * the database-enforced floor on the recording row. The other periods are drawn as bars on
 * purpose: `/security` leaves them to the privacy policy rather than stating them.
 */
export function RetentionMock() {
  const rows = [
    { what: "The recording of your call", days: "90 days", floor: true },
    { what: "The transcript of what was said", days: null, floor: false },
    { what: "The details noted from your call (your enquiry record)", days: null, floor: false },
  ] as const;
  return (
    <span className="flex flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-card">
      <span className="border-b border-line bg-app/70 px-3 py-2 text-[12px] font-semibold text-ink">
        How long you keep it
      </span>
      {rows.map(({ what, days, floor }, i) => (
        <span
          key={what}
          className={`mk-rise mk-s${i + 1} flex items-center gap-3 border-b border-line px-3 py-2 last:border-b-0`}
        >
          <span className="min-w-0 flex-1 text-[12px] leading-snug text-ink">{what}</span>
          <span className="flex shrink-0 flex-col items-end gap-0.5">
            {days ? (
              <span className="font-mono text-[12px] text-ink-muted tabular-nums">{days}</span>
            ) : (
              <Bar w="w-12" />
            )}
            {floor && <Tag tone="amber">floor</Tag>}
          </span>
        </span>
      ))}
    </span>
  );
}

/**
 * The team screen (`settings/team`): "People", each with a role, and the two roles in the
 * console's own words (`lib/api/members.ts` `ROLE_COPY`).
 */
export function RolesMock() {
  const people = [
    { name: "Lakshmi Reddy", role: "Owner", you: true },
    { name: "Ravi Teja", role: "Staff", you: false },
    { name: "Divya Naidu", role: "Staff", you: false },
  ] as const;
  const roles = [
    {
      label: "Owner",
      can: "Everything, including billing, full phone numbers in exports, launching campaigns, and managing this team.",
    },
    {
      label: "Staff",
      can: "Day-to-day work: leads, calls and agents. No billing, no team changes, and phone numbers stay masked.",
    },
  ] as const;
  return (
    <Panel elevation="raised" className="flex flex-col overflow-hidden">
      <span className="border-b border-line bg-app/70 px-4 py-2.5 text-[13px] font-semibold text-ink">
        People
      </span>
      {people.map(({ name, role, you }, i) => (
        <span
          key={name}
          className={`mk-rise mk-s${i + 1} flex items-center gap-2.5 border-b border-line px-4 py-2.5 text-[12px]`}
        >
          <span className="min-w-0 truncate font-medium text-ink">{name}</span>
          {you && <span className="text-[11px] text-ink-muted">(you)</span>}
          <span className="ml-auto">
            <Tag tone={role === "Owner" ? "brand" : "slate"}>{role}</Tag>
          </span>
        </span>
      ))}
      <span className="flex flex-col gap-2 bg-app/50 px-4 py-3">
        {roles.map(({ label, can }) => (
          <span key={label} className="flex flex-col gap-0.5 text-[11px] leading-snug">
            <span className="font-semibold text-ink">{label}</span>
            <span className="text-ink-muted">{can}</span>
          </span>
        ))}
      </span>
    </Panel>
  );
}
