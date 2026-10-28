"use client";

import { Section } from "@/components/console/section";
import { ScrollRegion, formatDecimal } from "@/components/ui";
import type { CallDetail } from "@/lib/api/client";

/**
 * "How the call went": the voice platform's own figures for the call.
 *
 * An operator viewing the call as the client (`operator`) sees all of it: the wait for the
 * first word of the answer, the first sound beside it (a filler line ends that one, D-902),
 * silences, interruptions, knowledge lookups, the problems reported while the call was live,
 * and each turn's wait step by step. A client sees only the typical wait for an answer and
 * how often the agent looked something up. The words name no provider either way (D-679).
 *
 * Every figure can be missing on a given call, and a missing one is left out rather than
 * shown as zero: "not measured" and "none" send a reader in different directions.
 */

type Quality = NonNullable<CallDetail["quality"]>;
type Signal = CallDetail["signals"][number];
type Turn = NonNullable<CallDetail["timeline"]>[number];

const SIGNAL_WORDS: Record<Signal["kind"], string> = {
  slow_reply: "A reply took over 5 seconds",
  no_answer_from_model: "Agent had no answer and said sorry",
  own_key_failed: "Agent's AI key failed; it said sorry",
  voice_failed: "Voice dropped; caller may have heard silence",
  lead_captured: "Agent took the caller's details",
  conversation_escalated: "Agent handed over to a person",
};

const PROBLEMS: ReadonlySet<Signal["kind"]> = new Set([
  "slow_reply",
  "no_answer_from_model",
  "own_key_failed",
  "voice_failed",
]);

/** The turn table's steps, in the order they happen. */
const STEPS: readonly { key: keyof Turn; label: string }[] = [
  { key: "wait_before_decision_ms", label: "Wait before decision" },
  { key: "recogniser_ms", label: "Recogniser" },
  { key: "ear_check_ms", label: "Ear check" },
  { key: "model_asked_ms", label: "Model asked" },
  { key: "model_first_sentence_ms", label: "Model's first sentence" },
  { key: "voice_ms", label: "Voice" },
];

function seconds(ms: number | null | undefined): string | null {
  if (ms === null || ms === undefined) return null;
  return `${formatDecimal(ms / 1000)} s`;
}

function count(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : String(value);
}

function spread(median?: number | null, p90?: number | null, max?: number | null): string | null {
  if (median === null || median === undefined) return null;
  return [seconds(median), seconds(p90), seconds(max)].map((v) => v ?? "–").join(" / ");
}

type Row = { label: string; value: string | null };

function operatorFigures(q: Quality): Row[] {
  return [
    { label: "Replies", value: count(q.turns) },
    {
      label: "Wait for an answer (typical / slow / longest)",
      value: spread(q.answer_ms_median, q.answer_ms_p90, q.answer_ms_max),
    },
    {
      label: "First sound, a filler included (typical / slow / longest)",
      value: spread(q.reply_ms_median, q.reply_ms_p90, q.reply_ms_max),
    },
    { label: "Of which thinking (typical)", value: seconds(q.first_token_ms_median) },
    { label: "Replies that looked up knowledge", value: count(q.knowledge_turns) },
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
    { label: "Caller talked over the agent", value: count(q.interruptions) },
    { label: "Replies a backup had to give", value: count(q.backup_answers) },
    { label: "Replies that failed", value: count(q.model_errors) },
  ];
}

function clientFigures(q: Quality): Row[] {
  const lookups = q.knowledge_turns;
  return [
    { label: "Typical wait for an answer", value: seconds(q.answer_ms_median) },
    {
      label: "Replies that looked up your information",
      value:
        lookups === null || lookups === undefined
          ? null
          : q.turns !== null && q.turns !== undefined
            ? `${lookups} of ${q.turns}`
            : String(lookups),
    },
  ];
}

function Figures({ rows }: { rows: { label: string; value: string }[] }) {
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-meta">
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className="text-ink-muted">{row.label}</dt>
          <dd className="text-right tabular-nums text-ink">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ms(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : value.toLocaleString("en-IN");
}

/** Each turn's wait, step by step, in milliseconds from the caller stopping. */
function TurnTable({ turns }: { turns: Turn[] }) {
  return (
    <ScrollRegion label="Each turn's wait" className="mt-4">
      <table className="w-full text-meta tabular-nums">
        <caption className="mb-1 text-left text-ink-muted">
          Each turn, ms after the caller stops. “Est.” is estimated.
        </caption>
        <thead>
          <tr className="text-left text-ink-muted">
            <th scope="col" className="pr-3 font-normal">Turn</th>
            <th scope="col" className="pr-3 font-normal">Answer</th>
            <th scope="col" className="pr-3 font-normal">First sound</th>
            {STEPS.map((step) => (
              <th key={step.key} scope="col" className="pr-3 font-normal">
                {step.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {turns.map((turn) => (
            <tr key={turn.turn} className="text-ink">
              <th scope="row" className="pr-3 text-left font-normal">{turn.turn}</th>
              <td className="pr-3">
                {ms(turn.answer_ms)}
                {turn.answer_estimated && <span className="text-ink-muted"> est.</span>}
              </td>
              <td className="pr-3">
                {ms(turn.first_sound_ms)}
                {turn.first_sound_kind === "filler" && <span className="text-ink-muted"> filler</span>}
              </td>
              {STEPS.map((step) => (
                <td key={step.key} className="pr-3">
                  {ms(turn[step.key] as number | null | undefined)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

export function CallQualityCard({
  detail,
  operator = false,
}: {
  detail: Pick<CallDetail, "quality" | "signals"> & Partial<Pick<CallDetail, "timeline">>;
  operator?: boolean;
}) {
  const rows = detail.quality
    ? (operator ? operatorFigures : clientFigures)(detail.quality).filter(
        (r): r is { label: string; value: string } => r.value !== null,
      )
    : [];
  const signals = operator ? detail.signals : [];
  const problems = signals.filter((s) => PROBLEMS.has(s.kind));
  const notes = signals.filter((s) => !PROBLEMS.has(s.kind));
  const turns = operator ? (detail.timeline ?? []) : [];
  if (rows.length === 0 && signals.length === 0 && turns.length === 0) return null;
  return (
    <Section title="How the call went">
      {problems.length > 0 && (
        <ul aria-label="Problems on this call" className="mb-3 space-y-1 text-body text-ink">
          {problems.map((p) => (
            <li key={p.kind}>{SIGNAL_WORDS[p.kind]}.</li>
          ))}
        </ul>
      )}
      {rows.length > 0 && <Figures rows={rows} />}
      {turns.length > 0 && <TurnTable turns={turns} />}
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
