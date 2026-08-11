"use client";

import { useState } from "react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  useIngestActivity,
  useTestWebhook,
  type TestWebhookResult,
} from "@/lib/api/leadSources";

/**
 * Lead sources (SURFACES §2b): inbound webhook ingest made visible.
 *
 * Two things this screen must do that a settings page would not:
 *
 * 1. **Let the client rehearse a lead without spending a call.** The test posts a
 *    sample payload through the REAL decision path (mapping → phone → consent →
 *    compliance gate) but nothing is written and nothing is dialled — the API
 *    reports each verdict as a step. The button copy says so explicitly, because
 *    an SMB owner will not press a button that might ring a customer.
 * 2. **Account for every delivery, including the retries.** Form vendors retry;
 *    the "retries absorbed" column shows the dedupe doing its job, which is the
 *    answer to the classic support thread "your system got fifteen requests, why
 *    did my customer only get one call?" (that's the point).
 */

// Outcome chips: accepted = the lead landed, rejected = it did not and the error
// column says why, processing = still in flight (deliberately muted — it resolves).
const OUTCOME_TONE: Record<string, string> = {
  accepted: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  rejected: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  processing: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

// Pre-filled so the first test works without reading docs: a bare 10-digit Indian
// mobile plus a name is exactly what most form vendors send.
const SAMPLE_PAYLOAD = JSON.stringify(
  { phone_number: "9876543210", full_name: "Priya" },
  null,
  2,
);

export default function LeadSourcesPage() {
  const session = useClientSession();

  const activity = useIngestActivity(session);
  const test = useTestWebhook(session);

  /**
   * D-22 read-only, and the least obvious case on the sweep: the dry-run writes
   * nothing — no lead row, no inbox row, no dial — yet `POST /v1/lead-sources/{id}/test`
   * requires `org:manage`, which is mutating, so an impersonating operator is refused
   * it. That is the server's deliberate call (ingest/routes.py): a dry-run is an action
   * taken ON the client's behalf, not a view of their data, and the activity table
   * below is on `org:read` precisely so support keeps the view without the action.
   *
   * So the button is gated on what the endpoint actually checks, not on what the
   * operation morally is.
   */
  const write = useWriteAccess(session, "org:manage", "run a test through this account");

  // There is no list-lead-sources endpoint yet, so the webhook ID is a raw UUID
  // input. A proper picker lands when the lead-source config CRUD ships.
  const [webhookId, setWebhookId] = useState("");
  const [payloadText, setPayloadText] = useState(SAMPLE_PAYLOAD);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [result, setResult] = useState<TestWebhookResult | null>(null);

  const runTest = () => {
    setJsonError(null);
    setResult(null);

    // Parse client-side first: a typo in the JSON is the user's most likely
    // failure, and it deserves a friendly message, not a 422 round-trip.
    let payload: unknown;
    try {
      payload = JSON.parse(payloadText);
    } catch {
      setJsonError(
        "That doesn't look like valid JSON — check for a missing quote, comma or brace.",
      );
      return;
    }
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
      setJsonError("The sample must be a JSON object like the pre-filled example.");
      return;
    }

    test.mutate(
      { webhookId: webhookId.trim(), payload },
      { onSuccess: (data) => setResult(data) },
    );
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Lead sources</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Incoming leads from your website forms and ads, with every delivery accounted for.
        </p>
      </div>

      <RestrictionNote reason={write.reason} />

      <Card title="Try a sample lead">
        <p className="text-sm text-slate-700 dark:text-slate-300">
          Send a sample through the same checks a real submission goes through, and see
          exactly what would happen. Nothing is saved and nobody&apos;s phone rings.
        </p>
        <form
          className="mt-3 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            runTest();
          }}
        >
          <input
            required
            value={webhookId}
            onChange={(e) => setWebhookId(e.target.value)}
            placeholder="Webhook ID (from your setup email, e.g. 018f3c…)"
            className="w-full rounded-md border border-slate-200 px-3 py-1.5 font-mono text-sm dark:border-slate-700 dark:bg-slate-950"
          />
          <textarea
            value={payloadText}
            onChange={(e) => setPayloadText(e.target.value)}
            rows={5}
            spellCheck={false}
            className="w-full rounded-md border border-slate-200 px-3 py-1.5 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
            aria-label="Sample lead payload (JSON)"
          />
          {jsonError && (
            <p className="text-sm text-amber-700 dark:text-amber-400">{jsonError}</p>
          )}
          <button
            type="submit"
            disabled={!write.allowed || test.isPending || !webhookId.trim()}
            className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            {test.isPending ? "Checking…" : "Run test — no call is placed"}
          </button>
        </form>

        {test.error != null && <div className="mt-3"><ProblemNotice error={test.error} /></div>}

        {result && (
          <div className="mt-4 space-y-3">
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {result.steps.map((step) => (
                <li key={step.step} className="flex items-start gap-3 py-2">
                  <span
                    aria-label={step.ok ? "passed" : "failed"}
                    className={
                      step.ok
                        ? "font-semibold text-emerald-600 dark:text-emerald-400"
                        : "font-semibold text-rose-600 dark:text-rose-400"
                    }
                  >
                    {step.ok ? "✓" : "✗"}
                  </span>
                  <div className="text-sm">
                    <p className="text-slate-700 dark:text-slate-300">{step.detail}</p>
                    {/* Which rule spoke (e.g. dnc, quiet_hours) matters when the
                        gate says no — it tells the client what to fix. */}
                    {step.rule && <p className="text-xs text-slate-500">rule: {step.rule}</p>}
                    {step.mapped_fields && step.mapped_fields.length > 0 && (
                      <p className="text-xs text-slate-500">
                        matched: {step.mapped_fields.join(", ")}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            <div
              className={
                result.would_call
                  ? "rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm font-medium text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
                  : "rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm font-medium text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
              }
            >
              {result.would_call
                ? "A real submission like this WOULD get a call."
                : "A real submission like this would NOT get a call."}
            </div>
          </div>
        )}
      </Card>

      <Card title="Recent deliveries">
        {activity.error != null && (
          <div className="mb-3">
            <ProblemNotice error={activity.error} onRetry={() => activity.refetch()} />
          </div>
        )}
        {activity.isLoading ? (
          <Skeleton rows={3} />
        ) : activity.data?.items.length ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="pb-2 font-medium">Source</th>
                <th className="pb-2 font-medium">Outcome</th>
                <th className="pb-2 font-medium">Retries absorbed</th>
                <th className="pb-2 text-right font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {activity.data.items.map((item, i) => (
                // No stable ID in the payload, and `event` is nullable — a vendor can
                // post without naming an event and we still record the delivery — so
                // it cannot carry the key. Source + first delivery narrows it; the
                // index is what actually guarantees uniqueness for a read-only list.
                <tr key={`${item.source}-${item.first_at}-${i}`}>
                  <td className="py-2 text-slate-700 dark:text-slate-300">{item.source}</td>
                  <td className="py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        OUTCOME_TONE[item.outcome] ?? OUTCOME_TONE.processing
                      }`}
                    >
                      {item.outcome}
                    </span>
                    {item.error && (
                      <p className="mt-1 text-xs text-rose-700 dark:text-rose-400">{item.error}</p>
                    )}
                  </td>
                  <td className="py-2 tabular-nums text-slate-600 dark:text-slate-400">
                    {/* 0 renders as "—": "zero retries" reads like a problem,
                        a dash reads like nothing needed absorbing. */}
                    {item.deduplicated > 0 ? item.deduplicated : "—"}
                  </td>
                  <td className="py-2 text-right text-xs text-slate-500">
                    {formatIST(item.last_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : activity.error != null ? null : (
          <EmptyState
            title="No deliveries yet"
            hint="When your website form or ad account sends a lead, it appears here — accepted or not."
          />
        )}
      </Card>
    </div>
  );
}
