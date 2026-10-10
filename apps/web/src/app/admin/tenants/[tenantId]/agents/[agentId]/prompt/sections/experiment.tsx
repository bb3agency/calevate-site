"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { useFormValidation } from "@/components/formValidation";
import { StatusPill } from "@/components/admin/kit";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_INLINE,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  Skeleton,
  formatIST,
} from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import type { PromptVersion } from "@/lib/api/prompts";
import {
  useConcludeExperiment,
  useStartExperiment,
  useTenantExperiment,
  type Experiment,
} from "@/lib/api/publishing";

import { concludeMessage, pointsReading, rateReading } from "../experimentCopy";

/**
 * A/B script testing with conversion attribution (ROADMAP M3).
 *
 * THE ONE THING THIS PANEL MUST NOT DO is print a number that reads as a verdict. The
 * server answers three different things and they are rendered three different ways:
 *
 * - `basis: "insufficient_data"` — the counts are shown and NO comparison is drawn.
 *   No difference interval, no winner badge, and the arm that is ahead is labelled
 *   "ahead so far", which is an ordering, not a claim. §52's rule applied to a
 *   statistic: a comparison the server refused to make must not be inferable from two
 *   percentages sitting next to each other, so the reason is printed in the same block.
 * - `verdict: "inconclusive"` — enough calls, and the plausible range for the gap still
 *   contains zero. This is the commonest correct answer and it is stated plainly.
 * - `verdict: "winner"` — the only state that gets a winner badge.
 *
 * `headline` and `caveat` are the SERVER's sentences, printed verbatim. A UI that
 * paraphrased them would be a second statistical opinion, and the second one is where
 * the drift starts (`publishing.ts`'s lane table makes the same argument).
 *
 * §52 for the failure paths: loading is a skeleton, a failed read is a refusal, and
 * neither is an empty state. An experiment whose results endpoint 503s must NOT render
 * as "no conversions yet" or as "no test running" — both are claims about the world,
 * and a dead endpoint is a fact about our ignorance. The Start form is withheld under a
 * failure for the same reason it is withheld under a load: it needs `rules` from the
 * same read, and a form defaulted from nothing would submit a split nobody chose.
 */
export function ExperimentPanel({
  tenantId,
  agentId,
  slug,
  write,
  versions,
}: {
  tenantId: string;
  agentId: string;
  slug: string;
  write: ReturnType<typeof useAdminAccess>;
  versions: PromptVersion[] | undefined;
}) {
  const target = { tenantId, agentId, slug };
  const state = useTenantExperiment(slug, agentId);
  const start = useStartExperiment(target);
  const conclude = useConcludeExperiment(target);

  const experiment = state.data?.experiment ?? null;
  const running = experiment?.status === "running";

  return (
    <Section
      title="Script test"
      headingLevel={3}
      info="Two published scripts against comparable outbound traffic. Which arm a call ran is recorded on the call, so the attribution never changes when the split does."
    >
      <div className="space-y-4">
        <RestrictionNote reason={write.reason} />
        {state.error != null && (
          <ProblemNotice error={state.error} onRetry={() => state.refetch()} />
        )}
        {start.error && <ProblemNotice error={start.error} />}
        {conclude.error && <ProblemNotice error={conclude.error} />}

        {state.isLoading && !state.data ? (
          <Skeleton rows={3} />
        ) : !state.data ? (
          /* No results and no problem to show: say we cannot tell, and offer nothing
             else. A Start form here would be a control built on rules we never read. */
          state.error == null && (
            <p className="text-meta text-ink-muted">
              Script-test state is unavailable for this agent.
            </p>
          )
        ) : (
          <>
            {experiment && <ExperimentResults experiment={experiment} />}
            {running ? (
              <div className="flex flex-wrap items-center gap-2">
                {/* Every ending names the test ON SCREEN, never "whatever is running".
                    This panel's read is cached and refetched on focus, so the id under
                    the button can be a test a colleague has already ended — and if they
                    started the next one, an unnamed conclude would promote an arm of a
                    test this operator has not read a single number of. */}
                {experiment.variants.map((variant) => (
                  <button
                    key={variant.label}
                    type="button"
                    disabled={conclude.isPending || !write.allowed}
                    onClick={() =>
                      conclude.mutate({
                        experiment_id: experiment.experiment_id,
                        promote: variant.label,
                      })
                    }
                    className={SECONDARY_BUTTON_SM}
                  >
                    Promote {variant.label} (v{variant.prompt_version})
                  </button>
                ))}
                <button
                  type="button"
                  disabled={conclude.isPending || !write.allowed}
                  onClick={() =>
                    conclude.mutate({ experiment_id: experiment.experiment_id, promote: null })
                  }
                  className={SECONDARY_BUTTON_SM}
                >
                  Stop, keep the control
                </button>
                <span className="text-meta text-ink-muted">
                  Promoting saves the winning script as a new version and applies it — the
                  same Apply to live calls as the Live section.
                </span>
              </div>
            ) : (
              <StartExperimentForm
                rules={state.data.rules}
                versions={versions}
                write={write}
                pending={start.isPending}
                onStart={(payload) => start.mutate(payload)}
              />
            )}
            {conclude.data && (
              <p className="text-meta text-ink-muted">{concludeMessage(conclude.data)}</p>
            )}
          </>
        )}
      </div>
    </Section>
  );
}

/**
 * The counts, the intervals, and exactly as much of a conclusion as the server allowed.
 *
 * Every percentage is accompanied by its plausible range, because a bare "17%" over 46
 * calls is the number this whole feature exists to stop somebody quoting.
 */
function ExperimentResults({ experiment }: { experiment: Experiment }) {
  const measured = experiment.basis === "measured";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-body font-medium text-ink">{experiment.name}</span>
        <span className="text-meta text-ink-muted">
          {experiment.status === "running" ? "running" : "concluded"} · scoring{" "}
          {experiment.conversion_metric_label} · started {formatIST(experiment.started_at)}
        </span>
        {experiment.winner_label && (
          <StatusPill tone="ok">winner: {experiment.winner_label}</StatusPill>
        )}
      </div>

      <NoticeBox
        // `ok` ONLY for a winner. An inconclusive or under-powered result gets the
        // neutral tone rather than a green one — a colour is read before a sentence is,
        // and a green box over "not enough data" would say the opposite of the words in
        // it.
        tone={experiment.verdict === "winner" ? "ok" : "neutral"}
        icon={<AlertTriangle className="h-5 w-5" />}
        title={experiment.headline}
      >
        {/* The server's own caveat, verbatim. It is about repeated reading, which is
            exactly what a screen invites. */}
        <p className="mt-0.5">{experiment.caveat}</p>
        {experiment.coverage_note && (
          <p className="mt-0.5">{experiment.coverage_note}</p>
        )}
      </NoticeBox>

      <ScrollRegion label="Prompt experiment arms">
        <table className="w-full text-left text-meta">
          <thead className="text-ink-muted">
            <tr>
              <th className="py-1 pr-3 font-medium">Arm</th>
              <th className="py-1 pr-3 font-medium">Share</th>
              {/* "Dialled (outbound)" rather than "Dialled": an arm can also be credited
                  with an inbound call its own line answered (D-60), and that call was
                  never placed by us. Completed can therefore exceed it, which the rate
                  cell explains on the same row. */}
              <th className="py-1 pr-3 font-medium">Dialled (outbound)</th>
              <th className="py-1 pr-3 font-medium">Completed</th>
              <th className="py-1 pr-3 font-medium">Converted</th>
              <th className="py-1 font-medium">Rate (95% range)</th>
            </tr>
          </thead>
          <tbody>
            {experiment.variants.map((variant) => (
              <tr key={variant.label} className="border-t border-line">
                <td className="py-1.5 pr-3 font-mono font-semibold text-ink">
                  {variant.label} · v{variant.prompt_version}
                  {experiment.leader_label === variant.label && (
                    // AHEAD, not better. The word is the whole point: on an unearned
                    // basis this is the only comparative statement allowed on screen.
                    <span className="ml-1.5 font-sans text-meta font-normal text-ink-muted">
                      ahead so far
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-3 tabular-nums">{variant.weight_bp / 100}%</td>
                <td className="py-1.5 pr-3 tabular-nums">{variant.outbound_dialled}</td>
                <td className="py-1.5 pr-3 tabular-nums">{variant.completed}</td>
                <td className="py-1.5 pr-3 tabular-nums">{variant.conversions}</td>
                <td className="py-1.5 tabular-nums">{rateReading(variant)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>

      {measured && experiment.difference_low !== null && experiment.difference_high !== null ? (
        <p className="text-meta text-ink-muted">
          Gap between the arms: {pointsReading(experiment.difference_low)} to{" "}
          {pointsReading(experiment.difference_high)} (A minus B, 95% confidence).
        </p>
      ) : (
        /* Deliberately not a dash, not a zero and not an empty cell: the reason the
           comparison is absent is more useful than the space it would occupy. */
        <p className="text-meta text-ink-muted">
          No gap is published below {experiment.minimum_calls_per_variant} completed calls
          per arm — the comparison is not valid at smaller samples.
        </p>
      )}
    </div>
  );
}

/**
 * Start a test between two versions this agent already has.
 *
 * No prompt is authored here: the challenger is written through the New version form
 * below, which is the one place a `prompt_versions` row is born. That keeps this a
 * choice between existing, auditable scripts rather than a second editor.
 */
function StartExperimentForm({
  rules,
  versions,
  write,
  pending,
  onStart,
}: {
  rules: NonNullable<ReturnType<typeof useTenantExperiment>["data"]>["rules"];
  versions: PromptVersion[] | undefined;
  write: ReturnType<typeof useAdminAccess>;
  pending: boolean;
  onStart: (payload: {
    name: string;
    control_version: number;
    challenger_version: number;
    split_bp: number;
    conversion_metric: string;
  }) => void;
}) {
  const [name, setName] = useState("");
  const expValid = useFormValidation();
  const [control, setControl] = useState<string>("");
  const [challenger, setChallenger] = useState<string>("");
  const [metric, setMetric] = useState(rules.default_metric);

  // Two versions are the minimum a test can exist between, and saying so is more use
  // than a disabled control with no explanation.
  if (!versions || versions.length < 2) {
    return (
      <p className="text-meta text-ink-muted">
        A test needs two prompt versions. Write a challenger in Script, then start one.
      </p>
    );
  }

  const parsed = { control: Number(control), challenger: Number(challenger) };
  const ready =
    Number.isFinite(parsed.control) &&
    Number.isFinite(parsed.challenger) &&
    parsed.control !== parsed.challenger &&
    control !== "" &&
    challenger !== "";

  return (
    <form
      className="max-w-xl space-y-4"
      noValidate
      onSubmit={expValid.onSubmit(() => {
        onStart({
          name: name.trim(),
          control_version: parsed.control,
          challenger_version: parsed.challenger,
          // 50/50 is the only split this screen offers: a ramp is a real feature of the
          // API, and an unexplained slider is how somebody ships a 95/5 test that can
          // never reach the minimum on the small arm.
          split_bp: rules.split_total_bp / 2,
          conversion_metric: metric,
        });
      })}
    >
      <input
        {...expValid.field("name", "Say what is being tested.")}
        required
        minLength={3}
        value={name}
        disabled={!write.allowed}
        onChange={(event) => setName(event.target.value)}
        maxLength={120}
        placeholder="What is being tested (e.g. 'direct booking greeting')"
        className={FIELD}
      />
      {expValid.error("name")}
      <div className="flex flex-wrap gap-2">
        <VersionSelect
          label="Control (A)"
          value={control}
          onChange={setControl}
          versions={versions}
          disabled={!write.allowed}
        />
        <VersionSelect
          label="Challenger (B)"
          value={challenger}
          onChange={setChallenger}
          versions={versions}
          disabled={!write.allowed}
        />
        <label className="flex flex-col gap-1">
          <span className="text-meta text-ink-muted">Counts as a conversion</span>
          <select
            value={metric}
            disabled={!write.allowed}
            onChange={(event) => setMetric(event.target.value)}
            className={FIELD_INLINE}
          >
            {rules.metrics.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <button type="submit" disabled={pending || !ready || !write.allowed} className={PRIMARY_BUTTON}>
        {pending ? "Starting…" : "Start test (50/50)"}
      </button>
      <p className="text-meta text-ink-muted">
        Each arm is published to the voice platform with its own disclosure line. Outbound
        calls only. No comparison is reported until each arm has{" "}
        {rules.minimum_calls_per_variant} completed calls.
      </p>
    </form>
  );
}

function VersionSelect({
  label,
  value,
  onChange,
  versions,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  versions: PromptVersion[];
  disabled: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-meta text-ink-muted">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={FIELD_INLINE}
        aria-label={label}
      >
        <option value="">Choose a version</option>
        {versions.map((version) => (
          <option key={version.id} value={version.version}>
            v{version.version}
            {version.notes ? ` — ${version.notes}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
