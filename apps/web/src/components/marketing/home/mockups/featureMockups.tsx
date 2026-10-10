import { ArrowRight, Check, Pause, Play } from "lucide-react";

import { Turn, type CallTurn } from "./callCards";
import { Avatar, Bar, Chip, MaskedPhone, Panel, StatusPill, Tag, Waveform, Window } from "./kit";

/**
 * The remaining product screens, each drawn for the one section that talks about it, from
 * the console screen named above it. Sample people and counts are illustrative (see
 * `kit.tsx` for the rules they follow).
 */

/* ---------------------------------------------------------------- call detail */

/**
 * One call, opened — `app/c/[slug]/calls/[callId]`: the header (number, status, outcome,
 * the "date · duration · agent · direction · sentiment" line), the "Transcript" card with
 * "Agent"/"Caller" turns, and the right-hand cards "Summary", "Captured details", "Key
 * points in this call" and "Recording".
 *
 * An illustrative dental clinic in Hyderabad, so this section shows a different trade from
 * the hero's coaching centre; the captured fields are the clinic template's
 * (`scripts/seed.py`).
 */
const CLINIC_TURNS: readonly CallTurn[] = [
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

export function CallDetailMock() {
  const captured = [
    ["Symptom / reason", "Root canal"],
    ["Preferred doctor", "Dr. Rao"],
    ["Urgency", "this week"],
    ["Preferred slot", "Tuesday, 6:00 PM"],
  ] as const;
  const moments = [
    { at: "0:21", label: "Symptom / reason captured", ai: false },
    { at: "0:48", label: "Asked what a root canal costs", ai: true },
    { at: "1:36", label: "Preferred slot captured", ai: false },
  ] as const;
  return (
    <Window
      title="Call logs"
      actions={
        <Chip tone="brand">Telugu</Chip>
      }
    >
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line px-4 py-3 sm:px-5">
        <MaskedPhone className="text-[13px] font-semibold text-ink" />
        <Tag tone="emerald">completed</Tag>
        <Tag tone="brand">Resolved</Tag>
        <span className="w-full text-[11px] text-ink-muted sm:ml-auto sm:w-auto">
          Today, 10:42 AM · 2:14 · Front desk · inbound · positive
        </span>
      </span>
      <span className="flex flex-col md:flex-row">
        <span className="flex flex-1 flex-col gap-2 p-4 sm:p-5">
          <span className="text-[12px] font-semibold text-ink">Transcript</span>
          {CLINIC_TURNS.map((turn, i) => (
            <Turn key={turn.en} {...turn} className={`mk-rise mk-s${Math.min(i + 1, 6)}`} />
          ))}
        </span>
        <span className="flex flex-col gap-3 border-t border-line bg-app/50 p-4 sm:p-5 md:w-80 md:border-t-0 md:border-l">
          <span className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface p-3">
            <span className="text-[11px] font-semibold text-ink-muted">Summary</span>
            <span className="text-[12px] leading-snug text-ink">
              Priya asked whether the clinic does root canals and what it costs. The agent
              explained it depends on the tooth and booked a check-up for Tuesday evening.
            </span>
            <span className="flex items-center gap-1 text-[11px] font-semibold text-brand-strong dark:text-brand-bright">
              View the lead this call created
              <ArrowRight className="h-3 w-3" />
            </span>
          </span>
          <span className="flex flex-col rounded-lg border border-line bg-surface">
            <span className="border-b border-line px-3 py-2 text-[11px] font-semibold text-ink-muted">
              Captured details
            </span>
            {captured.map(([label, value]) => (
              <span key={label} className="flex items-center justify-between gap-3 px-3 py-1.5 text-[12px]">
                <span className="text-ink-muted">{label}</span>
                <span className="truncate font-semibold text-ink">{value}</span>
              </span>
            ))}
          </span>
          <span className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface p-3">
            <span className="text-[11px] font-semibold text-ink-muted">Key points in this call</span>
            {moments.map(({ at, label, ai }) => (
              <span key={at} className="flex items-center gap-2 text-[12px]">
                <span className="w-8 shrink-0 font-mono text-[11px] text-brand-strong dark:text-brand-bright">{at}</span>
                <span className="min-w-0 flex-1 truncate text-ink">{label}</span>
                {ai && <Tag tone="violet">AI</Tag>}
              </span>
            ))}
          </span>
          <span className="flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-white">
              <Play className="h-2.5 w-2.5 translate-x-px fill-current" />
            </span>
            <span className="text-[12px] font-semibold text-ink">Listen to this call</span>
            <Waveform size="sm" tone="muted" bars={12} className="ml-auto" />
          </span>
        </span>
      </span>
    </Window>
  );
}

/* ------------------------------------------------------------- outcome minis */

/**
 * Answered at any hour — one day of calls on a 24-hour ribbon, with the hours the business
 * is shut shaded, and the dashboard's own "Captured after hours" tile under it. The ticks
 * are the picture: calls land at every hour, including the shaded ones.
 */
const TICKS = [
  "left-[4%]", "left-[27%]", "left-[31%]", "left-[38%]", "left-[42%]", "left-[47%]",
  "left-[52%]", "left-[58%]", "left-[63%]", "left-[69%]", "left-[74%]", "left-[83%]",
  "left-[88%]", "left-[93%]",
] as const;
/** Ticks inside the shaded hours (before 9 AM, after 9 PM). */
const AFTER_HOURS = new Set(["left-[4%]", "left-[27%]", "left-[31%]", "left-[88%]", "left-[93%]"]);

export function AnsweredMini() {
  return (
    <span className="flex flex-col gap-3">
      <span className="flex items-center justify-between text-[12px]">
        <span className="font-semibold text-ink">Calls each day</span>
        <span className="text-ink-muted">Today</span>
      </span>
      <span className="mk-rise mk-s1 relative block h-12 overflow-hidden rounded-lg border border-line bg-surface">
        {/* Closed hours: midnight to 9 AM, and 9 PM to midnight. */}
        <span className="absolute inset-y-0 left-0 w-[37.5%] bg-slate-100 dark:bg-white/[0.06]" />
        <span className="absolute inset-y-0 right-0 w-[12.5%] bg-slate-100 dark:bg-white/[0.06]" />
        {TICKS.map((left) => (
          <span
            key={left}
            className={`absolute top-1/2 h-6 w-1 -translate-y-1/2 rounded-full ${left} ${
              AFTER_HOURS.has(left) ? "bg-brand-strong" : "bg-brand/50"
            }`}
          />
        ))}
      </span>
      <span className="flex justify-between font-mono text-[10px] text-ink-muted">
        <span>12 AM</span>
        <span>6 AM</span>
        <span>12 PM</span>
        <span>6 PM</span>
        <span>12 AM</span>
      </span>
      <span className="mk-rise mk-s2 grid grid-cols-1 gap-2 min-[400px]:grid-cols-2">
        <span className="flex flex-col rounded-lg border border-line bg-surface px-3 py-2">
          <span className="text-[11px] text-ink-muted">Calls today</span>
          <span className="text-lg leading-tight font-semibold text-ink tabular-nums">14</span>
        </span>
        <span className="flex flex-col rounded-lg border border-line bg-surface px-3 py-2">
          <span className="text-[11px] text-ink-muted">Captured after hours</span>
          <span className="text-lg leading-tight font-semibold text-ink tabular-nums">5</span>
        </span>
      </span>
    </span>
  );
}

/**
 * Follow-up: a web enquiry and the first call it became, with the gap between them
 * TIMED — the shipped fact (`record_speed_to_lead`). No times are printed, because a pair
 * of times would be a speed claim.
 */
export function FollowUpMini() {
  return (
    <span className="flex flex-col items-stretch gap-2 min-[420px]:flex-row min-[420px]:items-center">
      <span className="mk-rise mk-s1 flex min-w-0 flex-1 flex-col gap-1 rounded-lg border border-line bg-surface p-3 shadow-card">
        <span className="text-[11px] font-semibold text-ink-muted">Website form</span>
        <span className="text-[13px] font-semibold text-ink">Sneha Rao</span>
        <span className="truncate text-[12px] text-ink-muted">Class 6 admission for her son</span>
      </span>
      <span className="mk-rise mk-s2 flex shrink-0 items-center justify-center gap-2 min-[420px]:flex-col min-[420px]:gap-1">
        <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] leading-5 font-semibold text-ink-muted ring-1 ring-line">
          gap timed
        </span>
        <span className="hidden h-px w-10 border-t border-dashed border-brand/60 min-[420px]:block" />
      </span>
      <span className="mk-rise mk-s3 flex min-w-0 flex-1 flex-col gap-1 rounded-lg border border-brand/30 bg-brand-soft/60 dark:bg-brand-strong/20 p-3 shadow-card">
        <span className="text-[11px] font-semibold text-brand-strong dark:text-brand-bright">First call · outbound</span>
        <span className="text-[13px] font-semibold text-ink">Call placed</span>
        <span className="flex items-center gap-1.5">
          <StatusPill status="interested" />
        </span>
      </span>
    </span>
  );
}

/** Qualified first: the list arrives sorted, with the hot lead on top and its reason. */
export function QualifiedMini() {
  const rows = [
    { status: "hot", name: "Ravi Kumar", reason: "Severe tooth pain, wants today" },
    { status: "interested", name: "Sneha Rao", reason: "Braces consult, Saturday" },
    { status: "contacted", name: "Karthik Varma", reason: "Cleaning, sometime next week" },
  ] as const;
  return (
    <span className="flex flex-col gap-2">
      {rows.map(({ status, name, reason }, i) => (
        <span
          key={status}
          className={`mk-rise mk-s${i + 1} flex items-center gap-3 rounded-lg border px-3 py-2.5 ${
            i === 0 ? "border-amber-200 bg-surface shadow-raised" : "border-line bg-surface/80 shadow-card"
          }`}
        >
          <Avatar name={name} className="h-7 w-7" tone={i === 0 ? "brand" : "base"} />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-[12px] font-semibold text-ink">{name}</span>
            <span className="truncate text-[11px] text-ink-muted">{reason}</span>
          </span>
          <StatusPill status={status} />
        </span>
      ))}
    </span>
  );
}

/**
 * Information you can act on: calls as rows and columns, and the CSV export. An
 * illustrative appliance shop, so its columns are the starting fields every business
 * outside the named trades gets (`scripts/seed.py` CUSTOM_EXTRACTION_FIELDS).
 */
export function RowsMini() {
  const rows = [
    ["Suresh Babu", "1.5-ton split AC, fitted", "Sat morning"],
    ["Ramya Devi", "Washing machine repair", "Today, 5:30 PM"],
    ["Naveen Kumar", "Double-door fridge", "This week"],
    ["Fatima Begum", "TV wall mounting", "Tomorrow, 11 AM"],
  ] as const;
  return (
    <span className="flex flex-col gap-2">
      <span className="flex flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-card">
        <span className="flex items-center gap-3 border-b border-line bg-app/70 px-3 py-2 text-[11px] font-semibold text-ink-muted">
          <span className="w-24 shrink-0">Name</span>
          <span className="min-w-0 flex-1">What they need</span>
          <span className="hidden w-24 shrink-0 min-[420px]:block">Preferred time</span>
        </span>
        {rows.map(([name, reason, slot], i) => (
          <span
            key={name}
            className={`mk-rise mk-s${i + 1} flex items-center gap-3 border-b border-line px-3 py-2 text-[12px] last:border-b-0`}
          >
            <span className="w-24 shrink-0 truncate font-semibold text-ink">{name}</span>
            <span className="min-w-0 flex-1 truncate text-ink">{reason}</span>
            <span className="hidden w-24 shrink-0 truncate text-ink-muted min-[420px]:block">{slot}</span>
          </span>
        ))}
      </span>
      <span className="flex justify-end">
        <Chip>Export this view as CSV</Chip>
      </span>
    </span>
  );
}

/* ------------------------------------------------------------ campaign board */

/**
 * An outbound list being worked — `app/c/[slug]/campaigns`: the status pill, the detail
 * tiles ("Contacts", "Connected" / calls answered, "Not called" / on the do-not-call list),
 * and the "Progress" card with the contact states and the Pause control. Every count is
 * sample data, chosen to add up, for an illustrative school's admissions list.
 */
export function CampaignBoardMock() {
  const progress = [
    { label: "connected", n: "152", w: "w-[63%]", tone: "bg-brand" },
    { label: "no answer", n: "41", w: "w-[17%]", tone: "bg-amber-300" },
    { label: "pending", n: "37", w: "w-[15%]", tone: "bg-slate-200" },
    { label: "dnc blocked", n: "6", w: "w-[3%]", tone: "bg-rose-300" },
    { label: "failed", n: "4", w: "w-[2%]", tone: "bg-slate-400" },
  ] as const;
  const tiles = [
    { label: "Contacts", value: "240", hint: "on this list" },
    { label: "Connected", value: "152", hint: "calls answered" },
    { label: "Not called", value: "6", hint: "on the do-not-call list" },
  ] as const;
  return (
    <Window
      title="Campaigns"
      actions={
        <span className="inline-flex items-center gap-1 rounded-md bg-surface px-2 py-0.5 text-[11px] leading-5 font-semibold text-ink ring-1 ring-line">
          <Pause className="h-3 w-3" />
          Pause
        </span>
      }
    >
      <span className="flex flex-col gap-4 p-4 sm:p-5">
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-[15px] font-semibold text-ink">Admissions — open day invitations</span>
          <Tag tone="emerald">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
            Running
          </Tag>
        </span>
        <span className="grid grid-cols-1 gap-2 min-[400px]:grid-cols-3">
          {tiles.map(({ label, value, hint }, i) => (
            <span
              key={label}
              className={`mk-rise mk-s${i + 1} flex flex-col gap-0.5 rounded-lg border border-line bg-surface p-3`}
            >
              <span className="text-[11px] text-ink-muted">{label}</span>
              <span className="text-xl leading-tight font-semibold text-ink tabular-nums">{value}</span>
              <span className="truncate text-[11px] text-ink-muted">{hint}</span>
            </span>
          ))}
        </span>
        <span className="flex flex-col gap-2.5 rounded-lg border border-line p-3">
          <span className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-semibold text-ink">Progress</span>
            <span className="text-[11px] text-ink-muted">Launched 14 Sep · up to 5 calls at a time</span>
          </span>
          <span className="mk-rise mk-s4 flex h-2.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/[0.06]">
            {progress.map(({ label, w, tone }) => (
              <span key={label} className={`block h-full ${w} ${tone}`} />
            ))}
          </span>
          <span className="flex flex-wrap gap-x-4 gap-y-1">
            {progress.map(({ label, n, tone }) => (
              <span key={label} className="flex items-center gap-1.5 text-[11px] text-ink-muted">
                <span className={`h-2 w-2 rounded-full ${tone}`} />
                {label}
                <span className="font-semibold text-ink tabular-nums">{n}</span>
              </span>
            ))}
          </span>
        </span>
      </span>
    </Window>
  );
}

/* ------------------------------------------------------------- launch check */

/**
 * The check a campaign passes before it can dial — `campaigns/LaunchGate.tsx` ("Before
 * you launch", "Everything checks out.", "Review this launch") with the gate's own items
 * satisfied (published agent, AI disclosure line, DLT voice template, calling number,
 * contact list, where the list came from), and two lines of the confirm panel's own copy
 * from `LaunchConfirm.tsx` about calling hours and the do-not-call list.
 */
export function LaunchCheckMock() {
  const checks = [
    "Agent published",
    "AI disclosure line on file",
    "DLT voice template attached",
    "Calling number chosen",
    "Contact list uploaded",
    "List source: People who contacted us",
  ] as const;
  return (
    <Panel elevation="raised" className="p-4 sm:p-5">
      <span className="flex items-center justify-between gap-3">
        <span className="text-[14px] font-semibold text-ink">Before you launch</span>
        <Tag tone="emerald">Everything checks out.</Tag>
      </span>
      <span className="mt-4 flex flex-col gap-1.5">
        {checks.map((label, i) => (
          <span
            key={label}
            className={`mk-rise mk-s${Math.min(i + 1, 6)} flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2`}
          >
            <Check className="h-3.5 w-3.5 shrink-0 text-brand-strong dark:text-brand-bright" strokeWidth={2.5} />
            <span className="min-w-0 flex-1 text-[12px] font-medium text-ink">{label}</span>
          </span>
        ))}
      </span>
      <span className="mt-4 flex flex-col gap-1.5 rounded-lg bg-app px-3 py-2.5 text-[12px] leading-snug text-ink-muted">
        <span>Calls go out between 9am and 9pm IST only.</span>
        <span>Anyone already on your do-not-call list is dropped as it starts.</span>
      </span>
      <span className="mt-4 flex justify-end">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-strong px-4 py-1.5 text-[12px] font-semibold text-white shadow-card">
          Review this launch
          <ArrowRight className="h-3 w-3" />
        </span>
      </span>
    </Panel>
  );
}

/* ------------------------------------------------------------- voice picker */

/**
 * Choosing how the agent sounds — `components/voicePicker.tsx`'s two groups, "Studio voice"
 * and "Clear voice". On the live engine (`ENGINE=thinnest`, D-687) Clear is the hosted
 * platform's studio band, and Anjali and Rakesh Khanna are two of its studio-tab voices
 * (`thinnest-findings/mirror/snapshots/2026-10-07b/pages/channels/voice-clone.md:86-88`);
 * which voices a client sees is the admin's curated list, so this is illustration only.
 * Studio names come from our Cartesia key at runtime, so that row's name is a bar rather
 * than an invented one. No rate and no
 * availability is shown: the console's own rate line is served, and the cost section's
 * rate card is the only place this page prices anything.
 */
export function VoicePickerMock() {
  const groups = [
    { tier: "Studio voice", voices: [{ name: null, selected: true }] },
    {
      tier: "Clear voice",
      voices: [
        { name: "Anjali", selected: false },
        { name: "Rakesh Khanna", selected: false },
      ],
    },
  ] as const;
  return (
    <Panel elevation="raised" className="p-4 sm:p-5">
      <span className="flex items-center justify-between gap-3">
        <span className="text-[13px] font-semibold text-ink">Voice</span>
        <Chip tone="brand">Telugu</Chip>
      </span>
      {groups.map(({ tier, voices }) => (
        <span key={tier} className="mt-3 flex flex-col gap-1.5">
          <span className="text-[12px] font-semibold text-ink-muted">{tier}</span>
          {voices.map(({ name, selected }, i) => (
            <span
              key={name ?? i}
              className={`flex items-center gap-3 rounded-lg border px-3 py-2 ${
                selected ? "border-brand/40 bg-brand-soft/50 dark:bg-brand-strong/20" : "border-line bg-surface"
              }`}
            >
              <span
                className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                  selected ? "border-brand-strong" : "border-ink/25"
                }`}
              >
                {selected && <span className="h-2 w-2 rounded-full bg-brand-strong" />}
              </span>
              {name ? (
                <span className="w-16 shrink-0 text-[13px] font-semibold text-ink">{name}</span>
              ) : (
                <Bar w="w-16" tone="strong" className="shrink-0" />
              )}
              <span className="font-mono text-[11px] text-ink-muted">te-IN</span>
              <Waveform size="sm" bars={12} tone={selected ? "brand" : "muted"} className="ml-auto hidden min-[400px]:flex" />
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface text-ink-muted ring-1 ring-line max-[399px]:ml-auto">
                <Play className="h-2.5 w-2.5 translate-x-px fill-current" />
              </span>
            </span>
          ))}
        </span>
      ))}
    </Panel>
  );
}
