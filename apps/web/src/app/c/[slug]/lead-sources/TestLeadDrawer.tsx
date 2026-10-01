"use client";

import { CheckCircle2, XCircle } from "lucide-react";

import { Drawer } from "@/components/console/drawer";
import {
  Disclosure,
  FIELD,
  NOTICE_TONES,
  PRIMARY_BUTTON,
  ProblemNotice,
  Skeleton,
} from "@/components/ui";
import type { LeadSource, LeadSourceDryRun, useTestWebhook } from "@/lib/api/leadSources";

import { rowName } from "./SourcesList";

/**
 * THE DRY RUN for one source: a sample through the same checks a real submission meets.
 * Nothing is saved and nobody's phone rings.
 *
 * It runs as the drawer opens, on a sample shaped for this source (`testSample.ts`), so a
 * test is one press. Editing the sample is there for the rarer question "what if the form
 * sends this instead", and an edit retracts the verdict: a verdict about a sample nobody
 * is looking at any more is a stale claim.
 */
export function TestLeadDrawer({
  source,
  onClose,
  test,
  payloadText,
  onPayloadText,
  jsonError,
  result,
  onRun,
}: {
  source: LeadSource | null;
  onClose: () => void;
  test: ReturnType<typeof useTestWebhook>;
  payloadText: string;
  onPayloadText: (text: string) => void;
  jsonError: string | null;
  result: LeadSourceDryRun | null;
  onRun: () => void;
}) {
  return (
    <Drawer
      open={source !== null}
      onClose={onClose}
      title="Test lead"
      description={source ? `${rowName(source)} · nothing is saved and no call is placed` : undefined}
      initialFocus="container"
      footer={
        <button type="button" onClick={onRun} disabled={test.isPending} className={PRIMARY_BUTTON}>
          {test.isPending ? "Checking…" : "Run again"}
        </button>
      }
    >
      <div className="space-y-4">
        {test.isPending && <Skeleton rows={3} />}
        {test.error != null && <ProblemNotice error={test.error} />}
        {jsonError && <p className="text-sm text-warn">{jsonError}</p>}
        {result && (
          <>
            {/* Present tense: the gate reads the do-not-call list live, so this is what
                would happen NOW — not a property of the source. */}
            <div
              className={`rounded-lg border p-3 text-sm ${result.would_call ? NOTICE_TONES.ok : NOTICE_TONES.warn}`}
            >
              <p className="font-medium">
                {result.would_call
                  ? "A real submission like this WOULD get a call."
                  : "A real submission like this would NOT get a call."}
              </p>
              <p className="mt-1">
                That is the answer right now. The do-not-call list and calling hours are read at
                the moment of the dial, so a real submission is checked again when it arrives.
              </p>
            </div>
            <ul className="divide-y divide-line">
              {result.steps.map((step) => (
                <li key={step.step} className="flex items-start gap-3 py-2">
                  <span
                    aria-label={step.ok ? "passed" : "failed"}
                    className={step.ok ? "mt-0.5 shrink-0 text-brand-strong" : "mt-0.5 shrink-0 text-danger"}
                  >
                    {step.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                  </span>
                  <div className="text-sm">
                    <p className="text-ink">{step.detail}</p>
                    {/* Which rule spoke tells the client what to fix. */}
                    {step.rule && <p className="text-xs text-ink-muted">rule: {step.rule}</p>}
                    {step.mapped_fields && step.mapped_fields.length > 0 && (
                      <p className="text-xs text-ink-muted">matched: {step.mapped_fields.join(", ")}</p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
        <Disclosure
          variant="inline"
          headingLevel={3}
          title="The sample"
          subtitle="Built from this source's field names. Edit it to try what your form really sends."
        >
          <textarea
            value={payloadText}
            onChange={(e) => onPayloadText(e.target.value)}
            rows={6}
            spellCheck={false}
            className={`${FIELD} w-full font-mono text-xs`}
            aria-label="Sample lead payload (JSON)"
          />
        </Disclosure>
      </div>
    </Drawer>
  );
}
