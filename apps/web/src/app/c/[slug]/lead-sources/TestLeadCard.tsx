"use client";

import { FlaskConical, CheckCircle2, XCircle } from "lucide-react";

import {
  Card,
  NOTICE_TONES,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
} from "@/components/ui";
import type { LeadSourceDryRun } from "@/lib/api/leadSources";
import { useTestWebhook } from "@/lib/api/leadSources";

import { SourcePicker, type SourcesQuery } from "./SourcePicker";
import { FIELD_BASE } from "./styles";

// Pre-filled so the first test works without reading docs: a bare 10-digit Indian
// mobile plus a name is exactly what most form vendors send.
export const SAMPLE_PAYLOAD = JSON.stringify(
  { phone_number: "9876543210", full_name: "Priya" },
  null,
  2,
);

/**
 * REHEARSE A LEAD WITHOUT SPENDING A CALL.
 *
 * The test posts a sample payload through the REAL decision path (mapping → phone →
 * consent → compliance gate) but nothing is written and nothing is dialled — the API
 * reports each verdict as a step. The button copy says so explicitly, because an SMB
 * owner will not press a button that might ring a customer.
 */
export function TestLeadCard({
  sources,
  test,
  sourceId,
  onSourceId,
  payloadText,
  onPayloadText,
  jsonError,
  result,
  onRun,
  canWrite,
}: {
  sources: SourcesQuery;
  test: ReturnType<typeof useTestWebhook>;
  sourceId: string;
  onSourceId: (id: string) => void;
  payloadText: string;
  onPayloadText: (text: string) => void;
  jsonError: string | null;
  result: LeadSourceDryRun | null;
  onRun: () => void;
  canWrite: boolean;
}) {
  return (
    <Card title="Try a sample lead">
      <p className="text-sm text-ink-muted">
        Send a sample through the same checks a real submission goes through. Nothing
        is saved and nobody&apos;s phone rings.
      </p>
      <form
        className="mt-3 space-y-3"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          onRun();
        }}
      >
        <SourcePicker
          label="Lead source to test"
          value={sourceId}
          onChange={onSourceId}
          query={sources}
        />
        <textarea
          value={payloadText}
          onChange={(e) => onPayloadText(e.target.value)}
          rows={5}
          spellCheck={false}
          className={`${FIELD_BASE} w-full font-mono text-xs`}
          aria-label="Sample lead payload (JSON)"
        />
        {jsonError && (
          <p className="text-sm text-amber-700 dark:text-amber-400">{jsonError}</p>
        )}
        <button
          type="submit"
          disabled={!canWrite || test.isPending || !sourceId.trim()}
          className={PRIMARY_BUTTON_SM}
        >
          <FlaskConical className="h-4 w-4" />
          {test.isPending ? "Checking…" : "Run test — no call is placed"}
        </button>
      </form>

      {test.error != null && (
        <div className="mt-3">
          <ProblemNotice error={test.error} />
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-3">
          <ul className="divide-y divide-line">
            {result.steps.map((step) => (
              <li key={step.step} className="flex items-start gap-3 py-2">
                <span
                  aria-label={step.ok ? "passed" : "failed"}
                  className={
                    step.ok
                      ? "mt-0.5 shrink-0 text-brand"
                      : "mt-0.5 shrink-0 text-rose-600 dark:text-rose-400"
                  }
                >
                  {step.ok ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <XCircle className="h-4 w-4" />
                  )}
                </span>
                <div className="text-sm">
                  <p className="text-ink">{step.detail}</p>
                  {/* Which rule spoke (e.g. dnc, quiet_hours) matters when the
                      gate says no — it tells the client what to fix. */}
                  {step.rule && <p className="text-xs text-ink-muted">rule: {step.rule}</p>}
                  {step.mapped_fields && step.mapped_fields.length > 0 && (
                    <p className="text-xs text-ink-muted">
                      matched: {step.mapped_fields.join(", ")}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {/* Present tense, and said as one: the gate reads the do-not-call list live,
              so this is what would happen NOW — not a property of the source. */}
          <div
            className={`rounded-lg border p-3 text-sm ${
              result.would_call ? NOTICE_TONES.ok : NOTICE_TONES.warn
            }`}
          >
            <p className="font-medium">
              {result.would_call
                ? "A real submission like this WOULD get a call."
                : "A real submission like this would NOT get a call."}
            </p>
            <p className="mt-1">
              That is the answer right now. The do-not-call list and calling hours are
              read at the moment of the dial, so a real submission is checked again
              when it arrives.
            </p>
          </div>
        </div>
      )}
    </Card>
  );
}
