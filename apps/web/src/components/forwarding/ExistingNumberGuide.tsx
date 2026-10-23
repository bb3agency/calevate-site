"use client";

import { useState } from "react";

import { SegmentedControl } from "@/components/interior/segmented-control";
import { Section } from "@/components/console/section";
import { StepFlow } from "@/components/console/stepFlow";
import { FIELD, FIELD_HINT, FIELD_LABEL, ProblemNotice, formatPhone } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import {
  DEFAULT_RING_SECONDS,
  useAddLine,
  type Carrier,
  type ForwardedLine,
  type ForwardingMode,
  type LineKind,
} from "@/lib/api/forwarding";

import { CARRIER_LABEL, LINE_KIND_CHOICE, modeSummary } from "./copy";
import { ForwardingCodes } from "./ForwardingCodes";
import { ModeChoice } from "./ModeChoice";
import { TestPanel } from "./TestPanel";

/** Typed digits, the shape the server accepts: 10 digits, or 0/91 in front. */
export function looksLikeIndianNumber(raw: string): boolean {
  const digits = raw.replace(/\D/g, "");
  return digits.length === 10 || (digits.length === 11 && digits.startsWith("0")) || (digits.length === 12 && digits.startsWith("91"));
}

/**
 * "USE YOUR EXISTING NUMBER": the guided flow (D-746). One question at a time: which number
 * callers know, how calls should reach the agent, then a check with the confirmation that
 * the number is the business's own. After saving, the codes for the client's own phone and
 * the test call. Skippable: `onSkip` leaves without saving.
 */
export function ExistingNumberGuide({
  session,
  calevateNumber,
  calevateNumberId,
  allowed,
  testingAvailable,
  onSkip,
  onDone,
}: {
  session: Session;
  calevateNumber: string;
  calevateNumberId: string;
  allowed: boolean;
  testingAvailable: boolean;
  onSkip?: () => void;
  onDone?: () => void;
}) {
  const add = useAddLine(session);
  const [number, setNumber] = useState("");
  const [kind, setKind] = useState<LineKind>("mobile");
  const [carrier, setCarrier] = useState<Carrier>("airtel");
  const [mode, setMode] = useState<ForwardingMode | null>(null);
  const [seconds, setSeconds] = useState<number>(DEFAULT_RING_SECONDS);
  const [attest, setAttest] = useState(false);
  const [saved, setSaved] = useState<ForwardedLine | null>(null);
  const numberInvalid = number.trim() !== "" && !looksLikeIndianNumber(number);

  if (saved) {
    return (
      <div className="space-y-10">
        <Section
          title="Set it on your phone"
          description={`Forwarding ${formatPhone(saved.e164)} to ${formatPhone(calevateNumber)}. ${modeSummary(saved.mode, saved.ring_seconds)}.`}
        >
          <ForwardingCodes
            session={session}
            carrier={saved.carrier}
            lineKind={saved.line_kind}
            mode={saved.mode}
            seconds={saved.ring_seconds}
            calevateNumber={calevateNumber}
          />
        </Section>
        <Section title="Test it">
          <TestPanel session={session} line={saved} allowed={allowed} available={testingAvailable} primary />
        </Section>
        {onDone && (
          <button type="button" className="text-body font-medium text-brand-strong underline-offset-2 hover:underline touch:min-h-11" onClick={onDone}>
            Done
          </button>
        )}
      </div>
    );
  }

  return (
    <StepFlow
      label="Use your existing number"
      onCancel={onSkip}
      cancelLabel="Skip for now"
      submitLabel="Save and show my codes"
      pending={add.isPending}
      error={add.error ? <ProblemNotice error={add.error} /> : null}
      onSubmit={() => {
        if (!mode || !attest) return;
        add.mutate(
          {
            number,
            line_kind: kind,
            carrier,
            mode,
            ring_seconds: mode === "all_calls" ? 0 : seconds,
            calevate_number_id: calevateNumberId,
            attest,
          },
          { onSuccess: (line) => setSaved(line) },
        );
      }}
      steps={[
        {
          id: "number",
          title: "Which number do your callers know?",
          hint: "Your callers keep dialling it. Calls reach your agent through your phone's call forwarding.",
          validate: () =>
            !looksLikeIndianNumber(number) ? "Enter your Indian business number, like 98765 43210." : null,
          content: (
            <div className="space-y-4">
              <div>
                <label htmlFor="existing-number" className={FIELD_LABEL}>
                  Your business number
                </label>
                <input
                  id="existing-number"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  className={FIELD}
                  value={number}
                  placeholder="98765 43210"
                  aria-invalid={numberInvalid}
                  aria-describedby="existing-number-hint"
                  onChange={(event) => setNumber(event.target.value)}
                />
                <span id="existing-number-hint" className={FIELD_HINT}>
                  {numberInvalid ? "Enter 10 digits, or 0 and the area code for a landline." : "The number on your board, card or website."}
                </span>
              </div>
              <div>
                <p className={FIELD_LABEL} aria-hidden>
                  What kind of line is it?
                </p>
                <SegmentedControl
                  label="What kind of line is it?"
                  className="mt-1.5"
                  value={kind}
                  options={(Object.keys(LINE_KIND_CHOICE) as LineKind[]).map((option) => ({
                    value: option,
                    label: LINE_KIND_CHOICE[option].label,
                  }))}
                  onValueChange={(next) => setKind(next as LineKind)}
                />
                <p className={FIELD_HINT}>{LINE_KIND_CHOICE[kind].hint}</p>
              </div>
              {kind === "mobile" && (
                <div>
                  <label htmlFor="existing-carrier" className={FIELD_LABEL}>
                    Mobile network
                  </label>
                  <select
                    id="existing-carrier"
                    className={FIELD}
                    value={carrier}
                    onChange={(event) => setCarrier(event.target.value as Carrier)}
                  >
                    {(Object.keys(CARRIER_LABEL) as Carrier[]).map((option) => (
                      <option key={option} value={option}>
                        {CARRIER_LABEL[option]}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          ),
        },
        {
          id: "mode",
          title: "How should calls reach your agent?",
          hint: "You set it once on your phone. You can change it any time.",
          validate: () => (mode ? null : "Choose one of the two."),
          content: (
            <ModeChoice
              mode={mode}
              seconds={seconds}
              onChange={(nextMode, nextSeconds) => {
                setMode(nextMode);
                if (nextSeconds > 0) setSeconds(nextSeconds);
              }}
            />
          ),
        },
      ]}
      review={{
        title: "Check and confirm",
        content: (
          <div className="space-y-3">
            <dl className="divide-y divide-line border-y border-line text-body">
              <div className="flex flex-wrap justify-between gap-2 py-2.5">
                <dt className="text-ink-muted">Your number</dt>
                <dd className="font-mono tabular-nums text-ink">{number}</dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2 py-2.5">
                <dt className="text-ink-muted">Forwards to</dt>
                <dd className="font-mono tabular-nums text-ink">{formatPhone(calevateNumber)}</dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2 py-2.5">
                <dt className="text-ink-muted">Calls</dt>
                <dd className="text-ink">{mode ? modeSummary(mode, seconds) : "Not chosen"}</dd>
              </div>
            </dl>
            <label className="flex items-start gap-3 text-body text-ink touch:min-h-11">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 shrink-0 accent-[var(--brand)]"
                checked={attest}
                disabled={!allowed}
                onChange={(event) => setAttest(event.target.checked)}
              />
              <span>This number belongs to my business. Calevate may ring it to test the forward.</span>
            </label>
            {!attest && <p className="text-meta text-ink-muted">Tick the box to save.</p>}
          </div>
        ),
      }}
    />
  );
}
