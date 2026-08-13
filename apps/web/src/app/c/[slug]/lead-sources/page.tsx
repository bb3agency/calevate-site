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
import { API_BASE } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  useIngestActivity,
  useMetaSetup,
  useTestWebhook,
  type MetaSetup,
  type TestWebhookResult,
} from "@/lib/api/leadSources";
import { lookup } from "@/lib/lookup";

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
  const metaSetup = useMetaSetup(session);

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
  // Separate from the test above on purpose: the two cards are independent tasks and
  // a client wiring up Meta is usually not the same person rehearsing a form post.
  const [metaWebhookId, setMetaWebhookId] = useState("");
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

      {/* Meta Lead Ads (SURFACES §2b). Placed above the delivery log on purpose: the
          capability statement in the response is the thing someone needs BEFORE they
          wire an ad account up, not something to infer from a column of rejections. */}
      <Card title="Meta Lead Ads">
        <p className="text-sm text-slate-700 dark:text-slate-300">
          Point a Facebook or Instagram lead form straight at Calevate — no Zapier in
          between. Your lead source is created for you during setup; enter its ID here
          to see what to paste into the Meta App Dashboard.
        </p>
        {/* Nothing in the product creates one of these yet, and pretending otherwise
            with a "Create source" button would be a form that 404s. Say where it
            comes from instead. */}
        <p className="mt-1 text-xs text-slate-500">
          Don&apos;t have an ID? Ask us — lead sources are provisioned by Calevate.
        </p>

        <form
          className="mt-3 flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            metaSetup.mutate(metaWebhookId.trim());
          }}
        >
          <input
            required
            value={metaWebhookId}
            onChange={(e) => {
              setMetaWebhookId(e.target.value);
              // The response carries a credential for ONE source; leaving it on screen
              // beside a different ID is how the wrong token gets pasted into Meta.
              metaSetup.reset();
            }}
            placeholder="Lead source ID (e.g. 018f3c…)"
            aria-label="Meta lead source ID"
            className="w-full max-w-md rounded-md border border-slate-200 px-3 py-1.5 font-mono text-sm dark:border-slate-700 dark:bg-slate-950"
          />
          <button
            type="submit"
            disabled={!write.allowed || metaSetup.isPending || !metaWebhookId.trim()}
            className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            {metaSetup.isPending ? "Loading…" : "Show setup details"}
          </button>
        </form>

        {metaSetup.error != null && (
          <div className="mt-3">
            <ProblemNotice error={metaSetup.error} />
          </div>
        )}
        {metaSetup.data && <MetaSetupDetails setup={metaSetup.data} />}
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
          <div className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0">
            <table className="w-full min-w-[700px] text-sm">
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
                        lookup(OUTCOME_TONE, item.outcome) ?? OUTCOME_TONE.processing
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
          </div>
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

/**
 * The setup card's result — capability first, credential last and hidden.
 *
 * Order is the argument. `lead_retrieval_available` is `false` in this deployment: the
 * receiver verifies Meta's signature and records the delivery, but reading the answers
 * the person typed into the form needs a Graph token we do not hold, so each verified
 * delivery lands as a RECORDED refusal. Someone about to spend twenty minutes in the
 * Meta App Dashboard should read that before they start, not discover it in the
 * rejections column afterwards — which is why the notice sits above the credentials
 * rather than in a footnote (the same argument `payment_capability` makes about
 * rendering a pay button for a deployment that cannot take payments).
 *
 * The verify token is treated as the credential the endpoint's own docstring says it
 * is: not fetched until asked for, never interpolated into a URL, and masked until
 * someone explicitly reveals it. It goes in Meta's "Verify token" FIELD — the callback
 * URL below carries no secret at all, which is what makes it safe to display.
 */
function MetaSetupDetails({ setup }: { setup: MetaSetup }) {
  const [revealed, setRevealed] = useState(false);
  // Absolute, because Meta needs a URL it can reach; built from the API base and the
  // server's own path so the two cannot disagree.
  const callbackUrl = `${API_BASE}${setup.callback_path}`;

  return (
    <div className="mt-4 space-y-4">
      {!setup.lead_retrieval_available && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <p className="font-medium">
            Read this first: lead answers are not collected yet.
          </p>
          <p className="mt-1">
            We verify each notification Meta sends and record it, so the connection
            itself will work and you will see every delivery below. But fetching what
            the person actually typed into your form needs a Meta access token this
            deployment does not hold — so each lead is recorded as{" "}
            <span className="font-mono text-xs">
              {setup.lead_retrieval_reason ?? "unavailable"}
            </span>{" "}
            instead of becoming a lead you can call. Nothing is lost: every delivery is
            kept against its Meta lead ID and can be claimed once that is in place.
            Talk to us before pointing live ad spend at this.
          </p>
        </div>
      )}

      <dl className="space-y-3">
        <SetupRow label="Callback URL" hint="Paste into “Callback URL” in the Meta App Dashboard.">
          <CopyableValue value={callbackUrl} />
        </SetupRow>

        <SetupRow
          label="Verify token"
          hint="Paste into “Verify token”. It belongs in that field only — never in the URL."
        >
          <div className="flex flex-wrap items-center gap-2">
            <code className="break-all rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-800 dark:bg-slate-800 dark:text-slate-200">
              {revealed ? setup.verify_token : "•".repeat(24)}
            </code>
            <button
              type="button"
              onClick={() => setRevealed((value) => !value)}
              className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {revealed ? "Hide" : "Reveal"}
            </button>
            <CopyButton value={setup.verify_token} label="Copy token" />
          </div>
        </SetupRow>

        <SetupRow label="Subscribe your Page to" hint="The webhook field to tick on the Page subscription.">
          <code className="rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-800 dark:bg-slate-800 dark:text-slate-200">
            {setup.subscribe_field}
          </code>
        </SetupRow>

        <SetupRow
          label="Signature header"
          hint="Every delivery is checked against this before we read a single field of it."
        >
          <code className="rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-800 dark:bg-slate-800 dark:text-slate-200">
            {setup.signature_header}
          </code>
        </SetupRow>
      </dl>
    </div>
  );
}

function SetupRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-sm font-medium text-slate-700 dark:text-slate-300">{label}</dt>
      <dd className="mt-1">{children}</dd>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  );
}

function CopyableValue({ value }: { value: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <code className="break-all rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-800 dark:bg-slate-800 dark:text-slate-200">
        {value}
      </code>
      <CopyButton value={value} label="Copy" />
    </div>
  );
}

/**
 * Copy to clipboard, or nothing at all.
 *
 * `navigator.clipboard` is undefined outside a secure context — it is not merely
 * blocked, the property is absent on plain http, which is exactly how local and
 * on-prem deployments run
 * (developer.mozilla.org/en-US/docs/Web/API/Clipboard/writeText). A button that throws
 * `Cannot read properties of undefined` is worse than no button, and the
 * `document.execCommand("copy")` fallback is deprecated and needs a selected DOM node,
 * so this renders nothing there: the value is on screen and selectable either way.
 */
function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const available = typeof navigator !== "undefined" && Boolean(navigator.clipboard);
  if (!available) return null;
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard.writeText(value).then(
          () => {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          },
          // A denied clipboard permission must not look like a successful copy.
          () => setCopied(false),
        );
      }}
      className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
    >
      {copied ? "Copied" : label}
    </button>
  );
}
