import { Avatar, Chip, MaskedPhone, Panel, StatusPill, Tag, Waveform, type LeadStatus } from "./kit";

/**
 * The call and the lead it leaves, for one illustrative caller: Kavya, ringing a coaching
 * centre in Guntur about a long-term entrance-exam batch.
 *
 * The other mockups depict other trades (a dental clinic, a property office, a school, a
 * shop), so the site does not read as built for one line of work; this one leads because
 * it is the hero's, and `why-calevate`, the auth showcase and `/roi` reuse it.
 *
 * Telugu because an agent starts as a Telugu agent (`language_primary` defaults to
 * `te-IN`). The agent's first line carries both opening sentences every agent has on file
 * — the AI disclosure and the recording notice — as an agent whose owner switched both on
 * (D-163; a new agent volunteers neither, D-669).
 * The Telugu runs carry `lang="te"` so a screen reader switches voice; each has its English
 * underneath so a reader who does not speak Telugu can follow.
 *
 * Field names are the education template's own (`scripts/seed.py` VERTICAL_TEMPLATES):
 * "Course", "Class / year", "Fee concern", "Demo booked". Speakers are labelled "Agent" and
 * "Caller", as the console's transcript labels them.
 */

export const SAMPLE_BUSINESS = "Akshara Coaching";

export type CallTurn = { who: "Agent" | "Caller"; te: string; en: string };

export const CALL_TURNS: readonly CallTurn[] = [
  {
    who: "Agent",
    te: "నమస్కారం, Akshara Coaching. నేను AI అసిస్టెంట్‌ని, ఈ కాల్ రికార్డ్ చేయబడుతోంది. మీకు ఎలా సహాయం చేయగలను?",
    en: "Namaskaram, Akshara Coaching. I am an AI assistant, and this call is recorded. How can I help?",
  },
  {
    who: "Caller",
    te: "EAMCET లాంగ్ టర్మ్ బ్యాచ్ ఉందా? ఫీజు ఎంత?",
    en: "Do you have an EAMCET long-term batch? What are the fees?",
  },
  {
    who: "Agent",
    te: "ఉంది. ఫీజు వివరాలు కౌన్సెలర్ చెబుతారు — ముందుగా డెమో క్లాస్ బుక్ చేయనా?",
    en: "We do. The counsellor will go through the fees — shall I book a demo class first?",
  },
  {
    who: "Caller",
    te: "అవును. శనివారం ఉదయం. నా పేరు కావ్య.",
    en: "Yes. Saturday morning. My name is Kavya.",
  },
  {
    who: "Agent",
    te: "శనివారం ఉదయం 10 గంటలకు డెమో క్లాస్ బుక్ చేశాను.",
    en: "Booked the demo class for Saturday at 10 AM.",
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
          <span className="truncate text-[12px] font-medium text-ink">{SAMPLE_BUSINESS} · Front desk</span>
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

/** The record the call leaves: the coaching centre's own columns, filled in. */
export function LeadCapturedCard({ className = "" }: { className?: string }) {
  const fields = [
    ["Name", "Kavya Reddy"],
    ["Course", "EAMCET long-term"],
    ["Class / year", "Inter 2nd year"],
    ["Fee concern", "Yes"],
    ["Demo booked", "Yes"],
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
        <Tag tone="emerald">Demo class booked</Tag>
        <Tag>inbound call · 2:14</Tag>
      </span>
    </Panel>
  );
}

/**
 * A leads-table row for the coaching centre: Name (with source and age under it), Status,
 * the template's "Course" and "Class / year". Four columns rather than the console's full
 * set, so nothing is cut mid-word at the width the hero gives the table.
 */
export type SampleLead = {
  name: string;
  status: LeadStatus;
  course: string;
  year: string;
  source: string;
  when: string;
};

export const SAMPLE_LEADS: readonly SampleLead[] = [
  { name: "Kavya Reddy", status: "new", course: "EAMCET long-term", year: "Inter 2nd year", source: "inbound call", when: "just now" },
  { name: "Sai Charan", status: "hot", course: "NEET repeater", year: "Class 12", source: "inbound call", when: "12 min ago" },
  { name: "Harshitha K", status: "interested", course: "Class 10 foundation", year: "Class 9", source: "campaign", when: "1 hr ago" },
  { name: "Manoj Kumar", status: "contacted", course: "Weekend maths batch", year: "Class 8", source: "inbound call", when: "3 hr ago" },
  { name: "Anitha Naidu", status: "won", course: "EAMCET crash course", year: "Inter 2nd year", source: "campaign", when: "Yesterday" },
  { name: "Imran Shaik", status: "lost", course: "Bank exams", year: "—", source: "inbound call", when: "Yesterday" },
];

export function SampleLeadRow({
  lead,
  highlight = false,
  className = "",
}: {
  lead: SampleLead;
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
      <span className="min-w-0 flex-1 truncate text-ink">{lead.course}</span>
      <span className="hidden w-28 shrink-0 truncate text-ink-muted md:block">{lead.year}</span>
    </span>
  );
}

/** The header row matching `SampleLeadRow`'s columns. */
export function SampleLeadHeader() {
  return (
    <span className="flex items-center gap-3 border-b border-line bg-app/60 px-4 py-2 text-[11px] font-semibold text-ink-muted">
      <span className="w-36 shrink-0">Name</span>
      <span className="w-20 shrink-0">Status</span>
      <span className="min-w-0 flex-1">Course</span>
      <span className="hidden w-28 shrink-0 md:block">Class / year</span>
    </span>
  );
}
