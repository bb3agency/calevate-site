import { Avatar, Chip, MaskedPhone, Panel, StatusPill, Tag, Waveform, type LeadStatus } from "./kit";

/**
 * The call and the lead it leaves, for one illustrative caller: Priya, ringing a dental
 * clinic in Hyderabad about a root canal.
 *
 * Telugu because an agent starts as a Telugu agent (`language_primary` defaults to
 * `te-IN`). The agent's first line carries both opening sentences every agent has on file
 * — the AI disclosure and the recording notice — as an agent whose owner switched both on
 * (D-163; a new agent volunteers neither, D-669).
 * The Telugu runs carry `lang="te"` so a screen reader switches voice; each has its English
 * underneath so a reader who does not speak Telugu can follow.
 *
 * Field names are the clinic template's own (`scripts/seed.py` VERTICAL_TEMPLATES):
 * "Symptom / reason", "Preferred doctor", "Urgency", "Preferred slot". Speakers are labelled "Agent" and
 * "Caller", as the console's transcript labels them.
 */

export const CLINIC = "Sunrise Dental";

export const CALL_TURNS: readonly { who: "Agent" | "Caller"; te: string; en: string }[] = [
  {
    who: "Agent",
    te: "నమస్కారం, Sunrise Dental. నేను AI అసిస్టెంట్‌ని, ఈ కాల్ రికార్డ్ చేయబడుతోంది. మీకు ఎలా సహాయం చేయగలను?",
    en: "Namaskaram, Sunrise Dental. I am an AI assistant, and this call is recorded. How can I help?",
  },
  {
    who: "Caller",
    te: "రూట్ కెనాల్ చేస్తారా? ఖర్చు ఎంత అవుతుంది?",
    en: "Do you do root canal? What does it cost?",
  },
  {
    who: "Agent",
    te: "చేస్తాము. ఖర్చు పంటిని బట్టి ఉంటుంది — ముందుగా చెకప్ బుక్ చేయనా?",
    en: "We do. It depends on the tooth — shall I book a check-up first?",
  },
  {
    who: "Caller",
    te: "అవును. మంగళవారం సాయంత్రం. నా పేరు ప్రియ.",
    en: "Yes. Tuesday evening. My name is Priya.",
  },
  {
    who: "Agent",
    te: "మంగళవారం సాయంత్రం 6 గంటలకు బుక్ చేశాను.",
    en: "Booked for Tuesday at 6 PM.",
  },
];

/** One turn of a conversation, as a bubble. Agent on the left, caller on the right. */
export function Turn({
  who,
  te,
  en,
  className = "",
}: {
  who: "Agent" | "Caller";
  te: string;
  en: string;
  className?: string;
}) {
  const agent = who === "Agent";
  return (
    <span className={`flex ${agent ? "justify-start" : "justify-end"} ${className}`}>
      <span
        className={`flex max-w-[88%] flex-col gap-0.5 rounded-xl px-3 py-2 ${
          agent ? "rounded-bl-sm bg-brand-soft dark:bg-brand-strong/20" : "rounded-br-sm bg-slate-100 dark:bg-white/[0.06]"
        }`}
      >
        <span className={`text-[11px] font-semibold ${agent ? "text-brand-strong dark:text-brand-bright" : "text-slate-600 dark:text-slate-300"}`}>
          {who}
        </span>
        <span lang="te" className="text-[13px] leading-snug text-ink">
          {te}
        </span>
        <span className="text-[11px] leading-snug text-ink-muted">{en}</span>
      </span>
    </span>
  );
}

/** The call as it happens: who is ringing, in what language, and the first exchange. */
export function CallCard({ className = "", turns = 2 }: { className?: string; turns?: number }) {
  return (
    <Panel elevation="overlay" className={`p-4 ${className}`}>
      <span className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="mk-ping absolute inline-flex h-full w-full rounded-full bg-brand-bright" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-bright" />
          </span>
          <span className="text-[12px] font-semibold text-ink">Live call</span>
          <span className="text-[11px] text-ink-muted">inbound</span>
        </span>
        <Chip tone="brand">Telugu</Chip>
      </span>

      <span className="mt-3 flex items-center gap-3">
        <span className="flex min-w-0 flex-1 flex-col">
          <MaskedPhone />
          <span className="truncate text-[12px] font-medium text-ink">{CLINIC} · Front desk</span>
        </span>
        <span className="font-mono text-[12px] font-semibold text-ink-muted">01:12</span>
      </span>

      <span className="mt-3 flex justify-center rounded-lg bg-app px-3 py-1.5">
        <Waveform live />
      </span>

      <span className="mt-3 flex flex-col gap-2">
        {CALL_TURNS.slice(0, turns).map((turn) => (
          <Turn key={turn.en} {...turn} />
        ))}
      </span>
    </Panel>
  );
}

/** The record the call leaves: the clinic's own columns, filled in. */
export function LeadCapturedCard({ className = "" }: { className?: string }) {
  const fields = [
    ["Name", "Priya Reddy"],
    ["Symptom / reason", "Root canal"],
    ["Preferred doctor", "Dr. Rao"],
    ["Urgency", "this week"],
    ["Preferred slot", "Tue, 6:00 PM"],
  ] as const;
  return (
    <Panel elevation="overlay" className={`p-4 ${className}`}>
      <span className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-[13px] font-semibold text-ink">
          <span className="h-2 w-2 rounded-full bg-brand" />
          Lead captured
        </span>
        <StatusPill status="new" />
      </span>
      <span className="mt-3 flex flex-col divide-y divide-line rounded-lg border border-line">
        {fields.map(([label, value]) => (
          <span key={label} className="flex items-center justify-between gap-4 px-3 py-1.5">
            <span className="text-[11px] text-ink-muted">{label}</span>
            <span className="truncate text-[12px] font-semibold text-ink">{value}</span>
          </span>
        ))}
      </span>
      <span className="mt-3 flex flex-wrap items-center gap-2">
        <Tag tone="emerald">Check-up booked</Tag>
        <Tag>inbound call · 2:14</Tag>
      </span>
    </Panel>
  );
}

/**
 * A leads-table row for the clinic: Name (with source and age under it), Status, the
 * template's "Symptom / reason" and "Preferred slot". Four columns rather than the
 * console's full set, so nothing is cut mid-word at the width the hero gives the table.
 */
export type ClinicLead = {
  name: string;
  status: LeadStatus;
  reason: string;
  slot: string;
  source: string;
  when: string;
};

export const CLINIC_LEADS: readonly ClinicLead[] = [
  { name: "Priya Reddy", status: "new", reason: "Root canal", slot: "Tue, 6:00 PM", source: "inbound call", when: "just now" },
  { name: "Ravi Kumar", status: "hot", reason: "Severe tooth pain", slot: "Today, 5:30 PM", source: "inbound call", when: "12 min ago" },
  { name: "Sneha Rao", status: "interested", reason: "Braces for daughter", slot: "Sat morning", source: "campaign", when: "1 hr ago" },
  { name: "Karthik Varma", status: "contacted", reason: "Teeth cleaning", slot: "Next week", source: "inbound call", when: "3 hr ago" },
  { name: "Anitha Naidu", status: "won", reason: "Implant consult", slot: "Thu, 11:00 AM", source: "campaign", when: "Yesterday" },
  { name: "Imran Shaik", status: "lost", reason: "Asked about fees only", slot: "—", source: "inbound call", when: "Yesterday" },
];

export function ClinicLeadRow({
  lead,
  highlight = false,
  className = "",
}: {
  lead: ClinicLead;
  highlight?: boolean;
  className?: string;
}) {
  return (
    <span
      className={`flex items-center gap-3 px-4 py-2.5 text-[12px] ${highlight ? "bg-brand-soft/60 dark:bg-brand-strong/20" : ""} ${className}`}
    >
      <span className="flex w-36 shrink-0 items-center gap-2">
        <Avatar name={lead.name} tone={highlight ? "brand" : "base"} className="h-6 w-6" />
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-semibold text-ink">{lead.name}</span>
          <span className="truncate text-[11px] text-ink-muted">
            {lead.source} · {lead.when}
          </span>
        </span>
      </span>
      <span className="w-20 shrink-0">
        <StatusPill status={lead.status} />
      </span>
      <span className="min-w-0 flex-1 truncate text-ink">{lead.reason}</span>
      <span className="hidden w-28 shrink-0 truncate text-ink-muted md:block">{lead.slot}</span>
    </span>
  );
}

/** The header row matching `ClinicLeadRow`'s columns. */
export function ClinicLeadHeader() {
  return (
    <span className="flex items-center gap-3 border-b border-line bg-app/60 px-4 py-2 text-[11px] font-semibold text-ink-muted">
      <span className="w-36 shrink-0">Name</span>
      <span className="w-20 shrink-0">Status</span>
      <span className="min-w-0 flex-1">Symptom / reason</span>
      <span className="hidden w-28 shrink-0 md:block">Preferred slot</span>
    </span>
  );
}
