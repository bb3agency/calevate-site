"use client";

import { Section } from "@/components/console/section";
import { formatDecimal } from "@/components/ui";
import type { CallDetail } from "@/lib/api/client";

/**
 * "How the call went": the voice platform's own figures for the call (how long the caller
 * waited for each reply, silences, interruptions, replies a backup had to give) and anything
 * it reported going wrong while the call was live. Shown on the admin view of a call; the
 * words name no provider, so the card is safe on any screen.
 *
 * Every figure can be missing on a given call, and a missing one is left out rather than
 * shown as zero: "not measured" and "none" send a reader in different directions.
 */

type Quality = NonNullable<CallDetail["quality"]>;
type Signal = CallDetail["signals"][number];

const SIGNAL_WORDS: Record<Signal["kind"], string> = {
  slow_reply: "A reply took more than five seconds to start",
  no_answer_from_model: "The agent could not get an answer and apologised to the caller",
  own_key_failed: "The agent's own model key failed and it apologised to the caller",
  voice_failed: "The voice connection failed: the caller may have heard silence or been cut off",
  lead_captured: "The agent took down the caller's details",
  conversation_escalated: "The agent handed the conversation to a person",
};

const PROBLEMS: ReadonlySet<Signal["kind"]> = new Set([
  "slow_reply",
  "no_answer_from_model",
  "own_key_failed",
  "voice_failed",
]);

function seconds(ms: number | null | undefined): string | null {
  if (ms === null || ms === undefined) return null;
  return `${formatDecimal(ms / 1000)} s`;
}

function figures(q: Quality): { label: string; value: string }[] {
  const rows: { label: string; value: string | null }[] = [
    { label: "Replies", value: q.turns === null || q.turns === undefined ? null : String(q.turns) },
    {
      label: "Wait for a reply (typical / slow / slowest)",
      value:
        q.reply_ms_median === null || q.reply_ms_median === undefined
          ? null
          : [seconds(q.reply_ms_median), seconds(q.reply_ms_p90), seconds(q.reply_ms_max)]
              .map((v) => v ?? "–")
              .join(" / "),
    },
    {
      label: "Of which thinking (typical)",
      value: seconds(q.first_token_ms_median),
    },
    {
      label: "Long silences",
      value:
        q.long_silences === null || q.long_silences === undefined
          ? null
          : `${q.long_silences}${
              q.longest_silence_s !== null && q.longest_silence_s !== undefined
                ? ` (longest ${formatDecimal(q.longest_silence_s)} s)`
                : ""
            }`,
    },
    {
      label: "Caller talked over the agent",
      value:
        q.interruptions === null || q.interruptions === undefined ? null : String(q.interruptions),
    },
    {
      label: "Replies a backup had to give",
      value:
        q.backup_answers === null || q.backup_answers === undefined ? null : String(q.backup_answers),
    },
    {
      label: "Replies that failed",
      value: q.model_errors === null || q.model_errors === undefined ? null : String(q.model_errors),
    },
  ];
  return rows.filter((r): r is { label: string; value: string } => r.value !== null);
}

export function CallQualityCard({
  detail,
}: {
  detail: Pick<CallDetail, "quality" | "signals">;
}) {
  const quality = detail.quality ? figures(detail.quality) : [];
  const problems = detail.signals.filter((s) => PROBLEMS.has(s.kind));
  const notes = detail.signals.filter((s) => !PROBLEMS.has(s.kind));
  if (quality.length === 0 && detail.signals.length === 0) return null;
  return (
    <Section title="How the call went">
      {problems.length > 0 && (
        <ul aria-label="Problems on this call" className="mb-3 space-y-1 text-body text-ink">
          {problems.map((p) => (
            <li key={p.kind}>{SIGNAL_WORDS[p.kind]}.</li>
          ))}
        </ul>
      )}
      {quality.length > 0 && (
        <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-meta">
          {quality.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-ink-muted">{row.label}</dt>
              <dd className="text-right tabular-nums text-ink">{row.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {notes.length > 0 && (
        <ul aria-label="Noted on this call" className="mt-3 space-y-1 text-meta text-ink-muted">
          {notes.map((n) => (
            <li key={n.kind}>{SIGNAL_WORDS[n.kind]}.</li>
          ))}
        </ul>
      )}
    </Section>
  );
}
