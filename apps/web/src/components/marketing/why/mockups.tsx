import { ArrowRight, Check, PhoneOff, Play, Voicemail } from "lucide-react";

import { CALL_TURNS, LeadCapturedCard, Turn } from "@/components/marketing/home/mockups/callCards";
import {
  Chip,
  MaskedPhone,
  Panel,
  StatusPill,
  Tag,
  Waveform,
} from "@/components/marketing/home/mockups/kit";

/**
 * The `/why-calevate` screens. Same kit and same honesty rules as the homepage mockups
 * (`home/mockups/kit.tsx`): console labels, made-up people, masked numbers, no figure that
 * could read as a result.
 */

/**
 * The hero: one call, opened. The agent's first line is the AI disclosure line every agent
 * has on file (hard rule 5); the lead beside it is what the call left behind. The launch
 * check joins them from `lg`, where there is room for three panels without overlap.
 */
export function WhyHeroMock() {
  return (
    <span className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
      <Panel elevation="raised" className="mk-rise mk-s1 flex min-w-0 flex-col gap-2 p-4">
        <span className="flex items-center justify-between gap-3">
          <span className="text-[12px] font-semibold text-ink">Transcript</span>
          <Chip tone="brand">Telugu</Chip>
        </span>
        <span className="relative flex flex-col gap-1.5 rounded-xl ring-2 ring-brand/40 ring-offset-2 ring-offset-surface">
          <Turn {...CALL_TURNS[0]} />
        </span>
        <span className="flex items-center gap-1.5 text-[11px] font-semibold text-brand-strong">
          <Check className="h-3 w-3" strokeWidth={3} />
          AI disclosure line
        </span>
        {CALL_TURNS.slice(1, 4).map((turn) => (
          <Turn key={turn.en} {...turn} />
        ))}
      </Panel>
      <LeadCapturedCard className="mk-rise mk-s2 min-w-0" />
      <span className="mk-rise mk-s3 hidden min-w-0 lg:block">
        <DialRulesMock />
      </span>
    </span>
  );
}

/**
 * A busy hour — several calls live at once, each answered rather than queued. Rows are
 * the hero `CallCard`'s header line ("Live call", direction, language, timer).
 */
export function BusyHourMock() {
  const calls = [
    { tail: "123", lang: "Telugu", at: "02:41" },
    { tail: "457", lang: "Telugu", at: "01:18" },
    { tail: "802", lang: "Hindi", at: "00:52" },
    { tail: "316", lang: "English", at: "00:09" },
  ] as const;
  return (
    <span className="flex flex-col gap-1.5">
      <span className="flex items-center justify-between text-[12px]">
        <span className="font-semibold text-ink">Live calls</span>
        <span className="font-mono text-[11px] text-ink-muted">11:04 AM</span>
      </span>
      {calls.map(({ tail, lang, at }, i) => (
        <span
          key={tail}
          className={`mk-rise mk-s${i + 1} flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2 shadow-card`}
        >
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="mk-ping absolute inline-flex h-full w-full rounded-full bg-brand-bright" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-bright" />
          </span>
          <MaskedPhone tail={tail} className="min-w-0 truncate" />
          <Waveform live size="sm" bars={10} className="hidden min-[420px]:flex" />
          <Chip className="ml-auto">{lang}</Chip>
          <span className="w-10 shrink-0 text-right font-mono text-[11px] text-ink-muted">{at}</span>
        </span>
      ))}
    </span>
  );
}

/**
 * The rules on the dispatch path, as a running campaign shows them: contact states from
 * the campaign progress legend ("connected", "dnc blocked", "pending") and the two lines of
 * `campaigns/LaunchConfirm.tsx` about calling hours and the do-not-call list.
 */
export function DialRulesMock() {
  const contacts = [
    { who: "Sneha Rao", state: "connected", tone: "emerald" },
    { who: null, state: "dnc blocked", tone: "slate" },
    { who: "Karthik Varma", state: "pending", tone: "sky" },
  ] as const;
  return (
    <Panel elevation="raised" className="p-4">
      <span className="flex items-center justify-between gap-3">
        <span className="text-[12px] font-semibold text-ink">Progress</span>
        <Tag tone="emerald">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
          Running
        </Tag>
      </span>
      <span className="mt-3 flex flex-col gap-1.5">
        {contacts.map(({ who, state, tone }, i) => (
          <span
            key={state}
            className={`mk-rise mk-s${i + 1} flex items-center gap-2.5 rounded-lg border border-line bg-surface px-3 py-2 text-[12px]`}
          >
            {who ? (
              <span className="min-w-0 flex-1 truncate font-semibold text-ink">{who}</span>
            ) : (
              <span className="flex min-w-0 flex-1 items-center gap-1.5">
                <PhoneOff className="h-3 w-3 shrink-0 text-ink-muted" />
                <MaskedPhone tail="640" className="truncate" />
              </span>
            )}
            <Tag tone={tone}>{state}</Tag>
          </span>
        ))}
      </span>
      <span className="mt-3 flex flex-col gap-1 rounded-lg bg-app px-3 py-2.5 text-[11px] leading-snug text-ink-muted">
        <span>Calls go out between 9am and 9pm IST only.</span>
        <span>Anyone already on your do-not-call list is dropped as it starts.</span>
      </span>
    </Panel>
  );
}

/**
 * "They come back sorted, not just recorded": a voicemail — a recording somebody still has
 * to play — above the row the same enquiry becomes in Calevate. The lead uses the
 * real-estate template's own columns (`scripts/seed.py`: "Budget (lakhs)", "Location",
 * "BHK") for an illustrative Vijayawada property office.
 */
export function RecordedVsSortedMock() {
  const fields = [
    ["Budget (lakhs)", "60"],
    ["Location", "Benz Circle"],
    ["BHK", "2BHK"],
  ] as const;
  return (
    <span className="flex flex-col gap-2">
      <span className="mk-rise mk-s1 flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2.5 shadow-card">
        <Voicemail className="h-4 w-4 shrink-0 text-ink-muted" />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-[12px] font-semibold text-ink">Voicemail</span>
          <MaskedPhone tail="519" />
        </span>
        <Waveform size="sm" tone="muted" bars={8} className="hidden min-[400px]:flex" />
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface text-ink-muted ring-1 ring-line">
          <Play className="h-2.5 w-2.5 translate-x-px fill-current" />
        </span>
      </span>
      <span className="mk-rise mk-s2 flex items-center justify-center text-ink-faint">
        <ArrowRight className="h-3.5 w-3.5 rotate-90" />
      </span>
      <span className="mk-rise mk-s3 flex flex-col rounded-lg border border-brand/30 bg-surface shadow-raised">
        <span className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
          <span className="truncate text-[12px] font-semibold text-ink">Srinivas Rao</span>
          <StatusPill status="interested" />
        </span>
        {fields.map(([label, value]) => (
          <span key={label} className="flex items-center justify-between gap-3 px-3 py-1.5 text-[12px]">
            <span className="text-ink-muted">{label}</span>
            <span className="truncate font-semibold text-ink">{value}</span>
          </span>
        ))}
      </span>
    </span>
  );
}
