import { Play, Plus } from "lucide-react";

import { CallCard } from "./callCards";
import { Chip, Panel, StatusPill, Tag, Waveform } from "./kit";

/**
 * One screen per step of "how it works": the list you write, the call it takes, the lead
 * you get. Each is decorative — the step's own heading and sentence carry the meaning — so
 * `howItWorks.tsx` hides them from assistive technology.
 */

/**
 * Step 01: the agent's capture list, as the console's editor draws it ("What it writes
 * down", the type names from `agents/panels/extractionDraft.ts`, "Add variable"), filled
 * with the clinic template from `scripts/seed.py`.
 */
export function FieldListMock() {
  const fields = [
    { label: "Symptom / reason", type: "Text", required: true },
    { label: "Preferred doctor", type: "Text", required: false },
    { label: "Urgency", type: "One of a set list", required: true },
    { label: "Preferred slot", type: "Text", required: true },
    { label: "Insurance", type: "Text", required: false },
  ] as const;
  return (
    <Panel elevation="raised" className="p-4">
      <span className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-ink">What it writes down</span>
        <Chip>Clinic</Chip>
      </span>
      <span className="mt-3 flex flex-col gap-1.5">
        {fields.map(({ label, type, required }, i) => (
          <span
            key={label}
            className={`mk-rise mk-s${i + 1} flex items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-2 shadow-card`}
          >
            <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ink">
              {label}
              {required && <span className="ml-1 text-brand-strong dark:text-brand-bright">*</span>}
            </span>
            <span className="shrink-0 text-[11px] text-ink-muted">{type}</span>
          </span>
        ))}
        <span className="flex items-center gap-2 rounded-lg border border-dashed border-ink/15 px-2.5 py-2 text-[12px] font-medium text-brand-strong dark:text-brand-bright">
          <Plus className="h-3.5 w-3.5" />
          Add variable
        </span>
      </span>
    </Panel>
  );
}

/** Step 02: the call itself — the same card the hero uses, so the two read as one product. */
export function CallMock() {
  return <CallCard className="mk-rise mk-s1" />;
}

/**
 * Step 03: the lead with its call attached — summary, the console's "Key points in this
 * call" (field-captured moments and one AI-suggested highlight, as `apps/workers/
 * moments.py` labels them) and the recording.
 */
export function LeadRecordMock() {
  const moments = [
    { at: "0:21", label: "Symptom / reason captured", ai: false },
    { at: "0:48", label: "Asked what a root canal costs", ai: true },
    { at: "1:36", label: "Preferred slot captured", ai: false },
  ] as const;
  return (
    <Panel elevation="raised" className="mk-rise mk-s1 p-4">
      <span className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-[13px] font-semibold text-ink">Priya Reddy</span>
          <span className="text-[11px] text-ink-muted">inbound call · 2:14 · positive</span>
        </span>
        <StatusPill status="new" />
      </span>
      <span className="mt-3 flex flex-col gap-0.5 rounded-lg bg-app px-3 py-2 text-[12px] leading-snug">
        <span className="text-[11px] font-semibold text-ink-muted">Summary</span>
        <span className="text-ink">Asked about root canal cost; check-up booked for Tuesday, 6 PM.</span>
      </span>
      <span className="mt-3 block text-[11px] font-semibold text-ink-muted">Key points in this call</span>
      <span className="mt-1.5 flex flex-col gap-1">
        {moments.map(({ at, label, ai }, i) => (
          <span key={at} className={`mk-rise mk-s${i + 2} flex items-center gap-2 text-[12px]`}>
            <span className="w-8 shrink-0 font-mono text-[11px] text-brand-strong dark:text-brand-bright">{at}</span>
            <span className="min-w-0 flex-1 truncate text-ink">{label}</span>
            {ai && <Tag tone="violet">AI</Tag>}
          </span>
        ))}
      </span>
      <span className="mt-3 flex items-center gap-3 rounded-lg bg-app px-3 py-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-white">
          <Play className="h-2.5 w-2.5 translate-x-px fill-current" />
        </span>
        <span className="relative min-w-0 flex-1 overflow-hidden">
          <Waveform size="sm" tone="muted" />
          <span className="absolute top-0 left-[16%] h-full w-0.5 rounded-full bg-brand-strong" />
          <span className="absolute top-0 left-[36%] h-full w-0.5 rounded-full bg-brand-strong" />
          <span className="absolute top-0 left-[72%] h-full w-0.5 rounded-full bg-brand-strong" />
        </span>
      </span>
    </Panel>
  );
}
