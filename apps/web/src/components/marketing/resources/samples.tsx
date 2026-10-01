import { StatusPill, type LeadStatus } from "@/components/marketing/home/mockups/kit";

/**
 * Two glossary entries are easier to recognise than to read: the lead stages and what a
 * redacted line looks like. Each sample is the console's own rendering (`StatusPill` in its
 * colours; the redaction marks `apps/workers/redaction.py` writes), shown under the
 * definition and hidden from assistive technology because the definition already says it.
 */

const STAGES: readonly LeadStatus[] = ["new", "contacted", "interested", "hot", "won", "lost"];

export function LeadStatusSample() {
  return (
    <span aria-hidden className="mt-3 flex flex-wrap gap-1.5">
      {STAGES.map((status) => (
        <StatusPill key={status} status={status} />
      ))}
    </span>
  );
}

export function RedactedSample() {
  return (
    <span
      aria-hidden
      className="mt-3 flex flex-col gap-0.5 rounded-xl rounded-br-sm bg-slate-100 px-3 py-2 text-[13px] leading-snug text-ink"
    >
      <span className="text-[11px] font-semibold text-slate-600">Caller</span>
      <span>
        Send it to{" "}
        <span className="rounded bg-ink/[0.07] px-1 font-mono text-[12px] text-ink-muted">
          [phone ••23]
        </span>
        , please.
      </span>
    </span>
  );
}
