"use client";

import { useId, useState, type ReactNode } from "react";
import { CheckCircle2, PhoneOff, ShieldAlert } from "lucide-react";

import {
  FIELD,
  FIELD_INLINE,
  NOTICE_BAR,
  NOTICE_BASE,
  ProblemNotice,
  formatCount,
  type NoticeTone,
} from "@/components/ui";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import {
  MAX_NUMBERS_PER_ADD,
  useAddDncNumbers,
  useCheckDncNumber,
  type DncSource,
} from "@/lib/api/dnc";
import { type Session } from "@/lib/api/client";

import { SOURCE_OPTIONS } from "./sources";

/**
 * Check a number, or add numbers: one field, because both start from "here is a number".
 *
 * One number offers Check first (the question most people arrive with) and Add beside it.
 * Several numbers offer Add, because the check endpoint answers for one number at a time
 * and checking a pasted list one request per row is not a check anyone asked for.
 *
 * Enter checks a single number; Shift+Enter or a paste starts a list.
 *
 * The verdicts and the reason notes are compliance sentences (TCCCPR) and keep their
 * words: "no agent will call it" is what a client repeats to a caller, "other checks still
 * apply" stops a clear check reading as clearance, and each reason note says whether the
 * choice can be taken back.
 */
export function NumberField({
  session,
  value,
  onChange,
  parsed,
  source,
  onSourceChange,
  canAdd,
}: {
  session: Session;
  value: string;
  onChange: (next: string) => void;
  parsed: string[];
  source: DncSource;
  onSourceChange: (next: DncSource) => void;
  canAdd: boolean;
}) {
  const check = useCheckDncNumber(session);
  const add = useAddDncNumbers(session);
  // Both answers are drawn under the field (the verdict, the counts, a failure), so the
  // buttons carry the state and nothing is toasted.
  const checkFeedback = useActionFeedback(check, { errorDisplay: "inline" });
  const addFeedback = useActionFeedback(add, { errorDisplay: "inline" });
  const fieldId = useId();
  const [empty, setEmpty] = useState(false);
  const many = parsed.length > 1;
  const tooMany = parsed.length > MAX_NUMBERS_PER_ADD;

  const runCheck = () => {
    if (parsed.length !== 1) {
      setEmpty(parsed.length === 0);
      return;
    }
    add.reset();
    checkFeedback.run(parsed[0]);
  };
  const runAdd = () => {
    check.reset();
    add.mutate({ numbers: parsed, source }, { onSuccess: () => onChange("") });
  };

  return (
    <section aria-label="Check or add numbers" className="max-w-xl space-y-3">
      <div>
        <div className="flex items-center gap-1.5">
          <label htmlFor={fieldId} className="text-meta font-medium text-ink">
            Phone numbers
          </label>
          <InfoTip label="About checking a number">
            This asks the same question the system asks itself before it dials, so the
            answer cannot disagree with what actually happens. Anyone with access to this
            account can check.
          </InfoTip>
        </div>
        <textarea
          id={fieldId}
          value={value}
          rows={1}
          spellCheck={false}
          autoComplete="off"
          inputMode="tel"
          placeholder="9876543210 or +919876543210"
          aria-describedby={`${fieldId}-hint`}
          onChange={(event) => {
            onChange(event.target.value);
            setEmpty(false);
            check.reset();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !value.includes("\n")) {
              event.preventDefault();
              runCheck();
            }
          }}
          className={`${FIELD} max-h-60 resize-none font-mono field-sizing-content`}
        />
        <p id={`${fieldId}-hint`} className="mt-1 text-meta text-ink-faint">
          {many
            ? `${formatCount(parsed.length)} numbers. Check works one number at a time.`
            : "Paste one or many: one per line, or separated by commas."}
        </p>
        {empty && (
          <p role="alert" className="mt-1 text-meta font-medium text-danger">
            Enter the number to check.
          </p>
        )}
      </div>

      {canAdd && parsed.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="dnc-source" className="text-meta text-ink-muted">
            Reason
          </label>
          <select
            id="dnc-source"
            value={source}
            onChange={(event) => onSourceChange(event.target.value as DncSource)}
            aria-describedby="dnc-source-note"
            className={FIELD_INLINE}
          >
            {SOURCE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <span id="dnc-source-note" className="text-meta text-ink-faint">
            {SOURCE_OPTIONS.find((option) => option.value === source)?.note}
          </span>
        </div>
      )}

      {tooMany && (
        <p className="text-meta text-warn">
          That is {formatCount(parsed.length)} numbers. Add up to {formatCount(MAX_NUMBERS_PER_ADD)} at a
          time.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {!many && (
          <ActionButton onClick={runCheck} status={checkFeedback.status} successLabel="Checked">
            Check
          </ActionButton>
        )}
        {canAdd && parsed.length > 0 && (
          <ActionButton
            onClick={runAdd}
            status={addFeedback.status}
            disabled={tooMany}
            variant={many ? "primary" : "secondary"}
            successLabel="Added"
          >
            {parsed.length === 1 ? "Add 1 number" : `Add ${formatCount(parsed.length)} numbers`}
          </ActionButton>
        )}
      </div>

      {check.error != null && <ProblemNotice error={check.error} />}
      {add.error != null && <ProblemNotice error={add.error} />}
      {/* A failed check renders the notice above and NOTHING else: "not on the do-not-call
          list" is the most dangerous sentence this screen can print about a request that
          never landed. */}
      {check.data && <CheckVerdict result={check.data} />}
      {add.data && <AddResult result={add.data} />}
    </section>
  );
}

function CheckVerdict({ result }: { result: { valid: boolean; suppressed: boolean; scope?: string | null } }) {
  if (!result.valid) {
    return (
      <Verdict tone="warn" icon={<ShieldAlert className="h-4 w-4" />}>
        That does not look like a phone number we can dial. Indian mobiles work as ten
        digits, or write the full number starting with +.
      </Verdict>
    );
  }
  if (result.suppressed) {
    return (
      <Verdict tone="stop" icon={<PhoneOff className="h-4 w-4" />}>
        This number is suppressed, so no agent will call it.
        {result.scope === "global"
          ? " Calevate has suppressed it across the whole platform, so it cannot be removed from this account."
          : " It was added to your account's list."}
      </Verdict>
    );
  }
  return (
    <Verdict tone="ok" icon={<CheckCircle2 className="h-4 w-4" />}>
      This number is not on the do-not-call list. Other checks, such as calling hours and
      consent, still apply to any actual call.
    </Verdict>
  );
}

function Verdict({ tone, icon, children }: { tone: NoticeTone; icon: ReactNode; children: ReactNode }) {
  return (
    <p
      aria-live="polite"
      className={`settings-enter flex items-start gap-2 ${NOTICE_BASE} ${NOTICE_BAR[tone]}`}
    >
      <span className="mt-0.5 shrink-0 text-ink-faint" aria-hidden>
        {icon}
      </span>
      <span>{children}</span>
    </p>
  );
}

/** Counts only: the API never says which number went where, and this must not imply it could. */
function AddResult({ result }: { result: { added: number; already_suppressed: number; malformed: number } }) {
  const counts = [
    { label: "Added", value: result.added, hint: "Suppressed from now on." },
    { label: "Already on the list", value: result.already_suppressed, hint: "Nothing to do — they were suppressed already." },
    { label: "Not a usable number", value: result.malformed, hint: "Skipped rather than guessed at." },
  ];
  return (
    <div className="settings-enter space-y-2">
      <dl className="flex flex-wrap gap-x-6 gap-y-2">
        {counts.map((count) => (
          <div key={count.label} title={count.hint}>
            <dt className="text-meta text-ink-muted">{count.label}</dt>
            <dd className="text-[18px] font-semibold tabular-nums text-ink">{formatCount(count.value)}</dd>
          </div>
        ))}
      </dl>
      <p className="text-meta text-ink-faint">
        We report totals, not which number went where: a list of who asked us to stop calling
        them is itself personal data. Check one number above if you need to confirm it.
      </p>
    </div>
  );
}
