"use client";

import { useState, type ReactNode } from "react";
import {
  CheckCircle2,
  Copy,
  Eye,
  EyeOff,
  FlaskConical,
  Inbox,
  KeyRound,
  Plus,
  Power,
  ShieldAlert,
  Webhook,
  XCircle,
} from "lucide-react";

import {
  Card,
  EmptyState,
  NOTICE_TONES,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatIST,
  PRIMARY_BUTTON_SM,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import { API_BASE } from "@/lib/api/client";
import { useAgents } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  useCreateLeadSource,
  useIngestActivity,
  useLeadSources,
  useMetaSetup,
  useRotateLeadSourceSecret,
  useSetLeadSourceActive,
  useTestWebhook,
  type LeadSource,
  type LeadSourceDryRun,
  type MetaSetup,
  type NewLeadSource,
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
 *
 * ## Nothing here says a source is connected, because nothing here can know
 *
 * The Meta card hands over a callback URL and a verify token. That is SETUP MATERIAL,
 * not a connection: until someone pastes both into the Meta App Dashboard and Meta
 * completes the handshake, no delivery has happened and this deployment cannot tell the
 * difference between "not wired up yet" and "wired up wrong". The only evidence a source
 * is live is a row in the deliveries table below, so the card points at it rather than
 * implying success — the same argument `lead_retrieval_available` makes one level down,
 * where a verified delivery still cannot become a lead we can call.
 *
 * ## What the design pass changed
 *
 * Tokens from `globals.css` replace the slate literals, and three honesty problems went
 * with them:
 *
 * - **It printed its own `<h1>`**, which the app shell already renders from the nav list.
 * - **The read-only explanation named one control and gated two.** Both buttons require
 *   `org:manage`, but the reason beside them said only "run a test through this account",
 *   so a `staff` user staring at a disabled "Show setup details" was given an explanation
 *   for a different button.
 * - **The same identifier was called two different things** — "Webhook ID" in one card
 *   and "Lead source ID" in the other — for one value the client is told to paste into
 *   both. It is a lead source everywhere now, which is what the API calls the resource.
 *
 * ## What the provisioning pass changed
 *
 * The two cards below used to take a raw UUID in a text box, under a line reading
 * "Don't have an ID? Ask us — lead sources are provisioned by Calevate", because nothing
 * in the product could create one: every `inbound_webhooks` row was an operator running
 * SQL. `GET/POST /v1/lead-sources` ended that, so the ID boxes are pickers over the
 * client's own sources and the sentence they stood under is gone.
 *
 * Three rules the new card obeys, each of which is a way this screen could lie:
 *
 * - **The secret is on screen exactly once.** The create and rotate responses are the
 *   only place the plaintext exists outside the database; the list carries a
 *   fingerprint, and nothing here re-fetches a value.
 * - **Rotation states its deadline.** "Rotated" without a deadline reads as "the old one
 *   is dead", and it is not — the old secret keeps working for the grace window, which
 *   is the whole reason a client can rotate without dropping leads. The banner says when
 *   it stops, and the row keeps saying so until it does.
 * - **§52 holds for the list too.** A failed read renders a refusal and NO list — never
 *   "no lead sources yet", which on this screen would invite a client to create a second
 *   source for a form that is already wired up.
 */

/**
 * Outcome chips: accepted = the lead landed, rejected = it did not and the error column
 * says why, processing = still in flight (deliberately muted — it resolves).
 *
 * The two coloured tones follow `StatusBadge`'s palette rather than the design tokens
 * because there is no token for a success tint; the neutral one uses tokens, which is
 * why it needs no `dark:` pair.
 */
const OUTCOME_TONE: Record<string, string> = {
  accepted: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  rejected: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  processing: "border border-line bg-app text-ink-muted",
};

// Pre-filled so the first test works without reading docs: a bare 10-digit Indian
// mobile plus a name is exactly what most form vendors send.
const SAMPLE_PAYLOAD = JSON.stringify(
  { phone_number: "9876543210", full_name: "Priya" },
  null,
  2,
);

/* Split so the JSON box can be smaller without `${FIELD} text-xs` — two font-size
   utilities on one element, where Tailwind's emission order decides the winner and
   `text-sm` happens to be the one that does. */
const FIELD_BASE =
  "rounded-md border border-line bg-surface px-3 py-1.5 text-ink placeholder:text-ink-faint";
const FIELD = `${FIELD_BASE} text-sm`;
const QUIET_BUTTON =
  "flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5";
const CODE = "break-all rounded bg-app px-2 py-1 font-mono text-xs text-ink";

/** What a client calls each `inbound_webhooks.source`. The API's enum is the contract;
 *  this is the only place it is turned into English. */
const SOURCE_LABELS: Record<string, string> = {
  website_form: "Website form",
  meta_lead_ads: "Meta Lead Ads (Facebook / Instagram)",
  zoho: "Zoho",
  sheets: "Google Sheets",
  custom: "Something else (custom POST)",
};

/** The order the picker offers them in: the two most clients use, then the rest. */
const CREATABLE_SOURCES = ["website_form", "meta_lead_ads", "zoho", "sheets", "custom"] as const;

const sourceLabel = (source: string) => lookup(SOURCE_LABELS, source) ?? source;

export default function LeadSourcesPage() {
  const session = useClientSession();

  const sources = useLeadSources(session);
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
   * operation morally is — and BOTH buttons are, because `POST .../meta/setup` is on
   * the same permission for its own reason (its response carries a credential).
   */
  const write = useWriteAccess(session, "org:manage", "test or set up a lead source");

  // Pickers over the client's own sources now that `GET /v1/lead-sources` exists. The
  // state is still an id string, so a request built from it is unchanged — what went
  // away is a client having to know a UUID by heart.
  const [testSourceId, setTestSourceId] = useState("");
  // Separate from the test above on purpose: the two cards are independent tasks and
  // a client wiring up Meta is usually not the same person rehearsing a form post.
  const [metaSourceId, setMetaSourceId] = useState("");
  const [payloadText, setPayloadText] = useState(SAMPLE_PAYLOAD);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [result, setResult] = useState<LeadSourceDryRun | null>(null);

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

    // The sample goes in the BODY. It carries a phone number — the client's own test
    // number or, sooner or later, a real lead's — and a number in a query string lands
    // in access logs, proxies and browser history (hard rule 6). Only the lead source's
    // UUID is ever in the path.
    test.mutate({ webhookId: testSourceId.trim(), payload }, { onSuccess: setResult });
  };

  /* `activity.data`, never `?? []`: "the server said nothing arrived" and "we could not
     ask" are different facts, and only the first one may print an empty state. */
  const deliveries = activity.data?.items;

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Incoming leads from your website forms and ads, with every delivery accounted for.
      </p>

      <RestrictionNote reason={write.reason} />

      <LeadSourcesCard session={session} canWrite={write.allowed} />

      <Card title="Try a sample lead">
        <p className="text-sm text-ink-muted">
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
          <SourcePicker
            label="Lead source to test"
            value={testSourceId}
            onChange={setTestSourceId}
            query={sources}
          />
          <textarea
            value={payloadText}
            onChange={(e) => setPayloadText(e.target.value)}
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
            disabled={!write.allowed || test.isPending || !testSourceId.trim()}
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

      {/* Meta Lead Ads (SURFACES §2b). Placed above the delivery log on purpose: the
          capability statement in the response is the thing someone needs BEFORE they
          wire an ad account up, not something to infer from a column of rejections. */}
      <Card title="Meta Lead Ads">
        <p className="text-sm text-ink-muted">
          Point a Facebook or Instagram lead form straight at Calevate — no Zapier in
          between. Add a Meta Lead Ads source above, then pick it here to see what to
          paste into the Meta App Dashboard.
        </p>

        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            metaSetup.mutate(metaSourceId.trim());
          }}
        >
          <SourcePicker
            label="Meta lead source"
            value={metaSourceId}
            onChange={(id) => {
              setMetaSourceId(id);
              // The response carries a credential for ONE source; leaving it on screen
              // beside a different ID is how the wrong token gets pasted into Meta.
              metaSetup.reset();
            }}
            query={sources}
            // Only Meta sources: the other kinds have no Meta endpoint at all, and
            // `POST .../meta/setup` answers 404 for them. A picker that offers a choice
            // whose only outcome is a refusal is a worse ID box than the one it replaced.
            only="meta_lead_ads"
            emptyHint="Add a Meta Lead Ads source above first."
          />
          <button
            type="submit"
            disabled={!write.allowed || metaSetup.isPending || !metaSourceId.trim()}
            className={PRIMARY_BUTTON_SM}
          >
            <Webhook className="h-4 w-4" />
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

      <Card
        title="Recent deliveries"
        action={
          deliveries ? (
            <span className="text-xs text-ink-faint">
              {formatCount(deliveries.length)}{" "}
              {deliveries.length === 1 ? "source" : "sources"} with activity
            </span>
          ) : undefined
        }
        bodyClassName="p-2"
      >
        {activity.error != null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={activity.error} onRetry={() => activity.refetch()} />
          </div>
        )}
        {/* Loading is a skeleton and failure is the notice above — never "No deliveries
            yet", which on a screen someone opened to find out whether their form is
            reaching us at all is the one sentence that sends them to change a working
            integration. */}
        {activity.isLoading ? (
          <div className="p-4">
            <Skeleton rows={3} />
          </div>
        ) : !deliveries ? null : deliveries.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[700px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-3 py-2.5 font-semibold">Source</th>
                  <th className="px-3 py-2.5 font-semibold">Outcome</th>
                  <th className="px-3 py-2.5 font-semibold">Retries absorbed</th>
                  <th className="px-3 py-2.5 text-right font-semibold">Last seen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {deliveries.map((item, i) => (
                  // No stable ID in the payload, and `event` is nullable — a vendor can
                  // post without naming an event and we still record the delivery — so
                  // it cannot carry the key. Source + first delivery narrows it; the
                  // index is what actually guarantees uniqueness for a read-only list.
                  <tr key={`${item.source}-${item.first_at}-${i}`}>
                    <td className="px-3 py-2.5 text-ink">{item.source}</td>
                    <td className="px-3 py-2.5">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          // `lookup`, not `OUTCOME_TONE[item.outcome]`: a bare index
                          // reaches Object.prototype (src/lib/lookup.ts).
                          lookup(OUTCOME_TONE, item.outcome) ?? OUTCOME_TONE.processing
                        }`}
                      >
                        {item.outcome}
                      </span>
                      {item.error && (
                        <p className="mt-1 text-xs text-rose-700 dark:text-rose-400">
                          {item.error}
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums text-ink-muted">
                      {/* 0 renders as "—": "zero retries" reads like a problem,
                          a dash reads like nothing needed absorbing. */}
                      {item.deduplicated > 0 ? formatCount(item.deduplicated) : "—"}
                    </td>
                    <td className="px-3 py-2.5 text-right text-xs text-ink-faint">
                      {formatIST(item.last_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No deliveries yet"
            hint="When your website form or ad account sends a lead, it appears here — accepted or not."
          />
        )}
      </Card>
    </div>
  );
}

type SourcesQuery = ReturnType<typeof useLeadSources>;

/**
 * Pick one of the client's own lead sources.
 *
 * §52 applies to a form control as much as to a panel: while the list is loading this
 * is a skeleton, when the read FAILED it is a disabled control saying so, and only a
 * successful empty list may say there is nothing to pick. The three used to be one
 * text box that accepted anything, which is how "I pasted the ID from the email and it
 * says not found" became a support thread.
 */
function SourcePicker({
  label,
  value,
  onChange,
  query,
  only,
  emptyHint = "Add a lead source above first.",
}: {
  label: string;
  value: string;
  onChange: (id: string) => void;
  query: SourcesQuery;
  only?: string;
  emptyHint?: string;
}) {
  if (query.isLoading) {
    return (
      <div className="w-full max-w-md">
        <Skeleton rows={1} />
      </div>
    );
  }
  const items = query.data?.items;
  if (!items) {
    // The read failed. The card's own ProblemNotice carries the reason and the retry;
    // what this must not do is render an empty picker, which reads as "you have none".
    return (
      <select
        disabled
        aria-label={label}
        className={`${FIELD} w-full max-w-md`}
        value=""
        onChange={() => undefined}
      >
        <option value="">We could not load your lead sources</option>
      </select>
    );
  }
  const choices = only ? items.filter((item) => item.source === only) : items;
  return (
    <select
      required
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={choices.length === 0}
      className={`${FIELD} w-full max-w-md`}
    >
      <option value="">{choices.length === 0 ? emptyHint : "Choose a lead source…"}</option>
      {choices.map((item) => (
        <option key={item.id} value={item.id}>
          {sourceLabel(item.source)} · {item.id.slice(0, 8)}
          {item.active ? "" : " (off)"}
        </option>
      ))}
    </select>
  );
}

/**
 * The card that ended out-of-band provisioning: create a source, see the ones you have,
 * rotate a secret, turn one off and back on.
 *
 * The secret banner is the delicate part. It is rendered from the create/rotate
 * RESPONSE and from nothing else — there is no route that returns it again, and there
 * must never be a code path here that re-reads one — and it carries the whole
 * instruction (which header, which URL) because a client who dismisses it and comes
 * back cannot recover the value.
 */
function LeadSourcesCard({
  session,
  canWrite,
}: {
  session: ReturnType<typeof useClientSession>;
  canWrite: boolean;
}) {
  const sources = useLeadSources(session);
  const agents = useAgents(session);
  const create = useCreateLeadSource(session);
  const rotate = useRotateLeadSourceSecret(session);
  const setActive = useSetLeadSourceActive(session);

  const [source, setSource] = useState<string>("website_form");
  const [agentId, setAgentId] = useState("");
  const [phoneField, setPhoneField] = useState("phone");
  const [nameField, setNameField] = useState("name");
  const [consentField, setConsentField] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [issued, setIssued] = useState<IssuedSecret | null>(null);

  const items = sources.data?.items;
  const isMeta = source === "meta_lead_ads";

  const submit = () => {
    // Only the rules the client filled in. A blank field is not a mapping to an empty
    // field name — the server refuses those — it is "we do not map this one".
    const mapping: Record<string, string> = {};
    if (phoneField.trim()) mapping.phone = phoneField.trim();
    if (nameField.trim()) mapping.name = nameField.trim();
    if (consentField.trim()) mapping.consent_field = consentField.trim();

    create.mutate(
      {
        source,
        agent_id: agentId || null,
        mapping,
        ...(isMeta && appSecret.trim() ? { app_secret: appSecret.trim() } : {}),
      },
      {
        onSuccess: (made: NewLeadSource) => {
          setIssued({
            secret: made.secret,
            header: made.secret_header,
            path: made.ingest_path,
            expiresAt: null,
          });
          setAppSecret("");
        },
      },
    );
  };

  return (
    <Card title="Your lead sources">
      <p className="text-sm text-ink-muted">
        Each lead source is one place leads come from — a website form, an ad account, a
        CRM. It has its own address and its own secret, so you can turn one off without
        touching the others.
      </p>

      {issued && <IssuedSecretNotice issued={issued} onDismiss={() => setIssued(null)} />}

      {sources.error != null && (
        <div className="mt-3">
          <ProblemNotice error={sources.error} onRetry={() => sources.refetch()} />
        </div>
      )}
      {create.error != null && (
        <div className="mt-3">
          <ProblemNotice error={create.error} />
        </div>
      )}
      {rotate.error != null && (
        <div className="mt-3">
          <ProblemNotice error={rotate.error} />
        </div>
      )}
      {setActive.error != null && (
        <div className="mt-3">
          <ProblemNotice error={setActive.error} />
        </div>
      )}

      {/* Loading is a skeleton, a failed read is the notice above and NO list. "No lead
          sources yet" under a failed request would have a client create a second source
          for a form that is already wired up — two secrets, one form, and leads landing
          on whichever they pasted last. */}
      {sources.isLoading ? (
        <div className="mt-3">
          <Skeleton rows={2} />
        </div>
      ) : !items ? null : items.length ? (
        <ul className="mt-3 divide-y divide-line">
          {items.map((item) => (
            <LeadSourceRow
              key={item.id}
              item={item}
              canWrite={canWrite}
              busy={rotate.isPending || setActive.isPending}
              onRotate={(graceMinutes, secret) =>
                rotate.mutate(
                  { webhookId: item.id, graceMinutes, appSecret: secret },
                  {
                    onSuccess: (result) =>
                      setIssued({
                        secret: result.secret,
                        header: result.secret_header,
                        path: null,
                        expiresAt: result.previous_secret_expires_at,
                      }),
                  },
                )
              }
              onToggle={() => setActive.mutate({ webhookId: item.id, active: !item.active })}
            />
          ))}
        </ul>
      ) : (
        <div className="mt-3">
          <EmptyState
            title="No lead sources yet"
            hint="Add one below and point your website form at the address we give you."
          />
        </div>
      )}

      <form
        className="mt-4 space-y-3 border-t border-line pt-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <p className="text-sm font-medium text-ink">Add a lead source</p>
        <div className="flex flex-wrap gap-3">
          <label className="text-xs text-ink-muted">
            Where leads come from
            <select
              aria-label="Lead source kind"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className={`${FIELD} mt-1 block w-full min-w-[16rem]`}
            >
              {CREATABLE_SOURCES.map((kind) => (
                <option key={kind} value={kind}>
                  {sourceLabel(kind)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ink-muted">
            Which agent answers them
            <select
              aria-label="Agent to answer these leads"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              className={`${FIELD} mt-1 block w-full min-w-[16rem]`}
            >
              {/* Honest, not blank: a source with no agent SAVES leads and never dials
                  them, which is a legitimate state and a surprising one. Say it. */}
              <option value="">Not yet — save leads, don&apos;t call</option>
              {(agents.data ?? []).map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <fieldset className="flex flex-wrap gap-3">
          <legend className="text-xs text-ink-muted">
            What your form calls each field (leave blank to send ours)
          </legend>
          <input
            value={phoneField}
            onChange={(e) => setPhoneField(e.target.value)}
            aria-label="Your form's phone field name"
            placeholder="phone_number"
            className={`${FIELD} font-mono`}
          />
          <input
            value={nameField}
            onChange={(e) => setNameField(e.target.value)}
            aria-label="Your form's name field name"
            placeholder="full_name"
            className={`${FIELD} font-mono`}
          />
          <input
            value={consentField}
            onChange={(e) => setConsentField(e.target.value)}
            aria-label="Your form's consent field name"
            placeholder="consent_to_call (optional)"
            className={`${FIELD} font-mono`}
          />
        </fieldset>
        {/* Consent is not a formality on this path: a lead that does not affirm it is
            saved and never dialled (FLOWS §4). Say what naming the field does. */}
        <p className="text-xs text-ink-faint">
          If your form asks permission to call, name that field — a lead that does not
          confirm it is saved and never dialled.
        </p>

        {isMeta && (
          <label className="block text-xs text-ink-muted">
            Your Meta app&apos;s App Secret
            <input
              required
              type="password"
              value={appSecret}
              onChange={(e) => setAppSecret(e.target.value)}
              aria-label="Meta App Secret"
              className={`${FIELD} mt-1 block w-full max-w-md font-mono`}
            />
            <span className="mt-1 block text-ink-faint">
              Meta signs every notification with this, so we cannot generate it. Find it
              under App settings → Basic in the Meta App Dashboard.
            </span>
          </label>
        )}

        <button
          type="submit"
          disabled={!canWrite || create.isPending || (isMeta && !appSecret.trim())}
          className={PRIMARY_BUTTON_SM}
        >
          <Plus className="h-4 w-4" />
          {create.isPending ? "Adding…" : "Add lead source"}
        </button>
      </form>
    </Card>
  );
}

interface IssuedSecret {
  /** Null when the client supplied it themselves (Meta) — there is nothing to show. */
  secret: string | null;
  header: string;
  /** Only on creation: where to send leads. Null after a rotation, which changes
   *  nothing about the address. */
  path: string | null;
  /** Only after a rotation with a grace window: when the OLD secret stops working. */
  expiresAt: string | null;
}

/**
 * The one moment the plaintext is on screen.
 *
 * It says "copy it now" because that is literally true — no route returns it again —
 * and, after a rotation, it says when the old one stops working. A rotation banner
 * without that deadline is the dangerous version: a client who reads "rotated" as "the
 * old key is dead" will scramble, and one who reads it as "nothing changed" will never
 * update their form. The date is the only sentence that produces the right behaviour.
 */
function IssuedSecretNotice({
  issued,
  onDismiss,
}: {
  issued: IssuedSecret;
  onDismiss: () => void;
}) {
  return (
    <div className={`mt-3 rounded-lg border p-3 text-sm ${NOTICE_TONES.warn}`}>
      {issued.secret ? (
        <>
          <p className="font-medium">Copy this secret now — we will not show it again.</p>
          <code className={`${CODE} mt-2 block`}>{issued.secret}</code>
          <p className="mt-2 text-xs">
            Send it in the <code className="font-mono">{issued.header}</code> header on
            every submission.
          </p>
        </>
      ) : (
        <p className="font-medium">
          Saved. We store your app secret and verify every notification against it —
          there is nothing new for you to copy.
        </p>
      )}
      {issued.path && (
        <p className="mt-2 text-xs">
          Send leads to <code className="font-mono">{`${API_BASE}${issued.path}`}</code>
        </p>
      )}
      {issued.expiresAt && (
        <p className="mt-2 text-xs">
          Your previous secret keeps working until {formatIST(issued.expiresAt)} — update
          your form before then and no lead is lost.
        </p>
      )}
      {issued.expiresAt === null && issued.path === null && (
        <p className="mt-2 text-xs">The previous secret stopped working immediately.</p>
      )}
      <button type="button" onClick={onDismiss} className={`${QUIET_BUTTON} mt-3`}>
        I&apos;ve saved it
      </button>
    </div>
  );
}

/** One source: what it is, which secret we hold, and the two things you can do to it. */
function LeadSourceRow({
  item,
  canWrite,
  busy,
  onRotate,
  onToggle,
}: {
  item: LeadSource;
  canWrite: boolean;
  busy: boolean;
  onRotate: (graceMinutes: number, appSecret?: string) => void;
  onToggle: () => void;
}) {
  const [rotating, setRotating] = useState(false);
  const [grace, setGrace] = useState("60");
  const [appSecret, setAppSecret] = useState("");
  const isMeta = item.source === "meta_lead_ads";

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-ink">{sourceLabel(item.source)}</span>
        {!item.active && (
          <span className="rounded-full border border-line bg-app px-2 py-0.5 text-xs text-ink-muted">
            off
          </span>
        )}
        <code className="text-xs text-ink-faint">{item.id}</code>
        {/* The fingerprint, never the secret: enough to tell the client which key we
            hold when they are staring at two of them in a form vendor's settings. */}
        <span className="ml-auto text-xs text-ink-faint">key ···{item.secret_fingerprint}</span>
        <button
          type="button"
          disabled={!canWrite || busy}
          onClick={() => setRotating((open) => !open)}
          className={SECONDARY_BUTTON_SM}
        >
          <KeyRound className="h-3.5 w-3.5" />
          {rotating ? "Cancel" : "New secret"}
        </button>
        <button
          type="button"
          disabled={!canWrite || busy}
          onClick={onToggle}
          className={SECONDARY_BUTTON_SM}
        >
          <Power className="h-3.5 w-3.5" />
          {item.active ? "Turn off" : "Turn on"}
        </button>
      </div>

      {item.previous_secret_expires_at && (
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
          Your previous secret still works until {formatIST(item.previous_secret_expires_at)}.
        </p>
      )}

      {rotating && (
        <form
          className="mt-2 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            onRotate(Number(grace), isMeta ? appSecret.trim() || undefined : undefined);
            setRotating(false);
            setAppSecret("");
          }}
        >
          {isMeta && (
            <label className="text-xs text-ink-muted">
              Your new Meta App Secret
              <input
                required
                type="password"
                value={appSecret}
                onChange={(e) => setAppSecret(e.target.value)}
                aria-label="New Meta App Secret"
                className={`${FIELD} mt-1 block w-56 font-mono`}
              />
            </label>
          )}
          <label className="text-xs text-ink-muted">
            Keep the old secret working for
            <select
              aria-label="How long the old secret keeps working"
              value={grace}
              onChange={(e) => setGrace(e.target.value)}
              className={`${FIELD} mt-1 block`}
            >
              <option value="60">1 hour (recommended)</option>
              <option value="1440">24 hours</option>
              {/* The revocation, named for what it costs rather than for what it is:
                  a client choosing this because it sounds tidiest would drop the leads
                  submitted in the minutes it takes them to update their form. */}
              <option value="0">Stop it immediately — my secret leaked</option>
            </select>
          </label>
          <button type="submit" disabled={busy} className={PRIMARY_BUTTON_SM}>
            Issue new secret
          </button>
        </form>
      )}
    </li>
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
  // server's own path so the two cannot disagree. It carries no credential — the token
  // goes in Meta's own field, and putting it here instead would publish it in every
  // access log between Meta and us.
  const callbackUrl = `${API_BASE}${setup.callback_path}`;

  return (
    <div className="mt-4 space-y-4">
      {setup.lead_retrieval_available ? (
        <div className={`rounded-lg border p-3 text-sm ${NOTICE_TONES.ok}`}>
          <p className="font-medium">Lead answers will be collected.</p>
          <p className="mt-1">
            Once Meta accepts the details below, each verified delivery becomes a lead
            with the fields the person filled in.
          </p>
        </div>
      ) : (
        <div className={`rounded-lg border p-3 text-sm ${NOTICE_TONES.warn}`}>
          <p className="flex items-center gap-1.5 font-medium">
            <ShieldAlert className="h-4 w-4 shrink-0" aria-hidden />
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
            <code className={CODE}>{revealed ? setup.verify_token : "•".repeat(24)}</code>
            <button
              type="button"
              onClick={() => setRevealed((value) => !value)}
              className={QUIET_BUTTON}
            >
              {revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              {revealed ? "Hide" : "Reveal"}
            </button>
            <CopyButton value={setup.verify_token} label="Copy token" />
          </div>
        </SetupRow>

        <SetupRow
          label="Subscribe your Page to"
          hint="The webhook field to tick on the Page subscription."
        >
          <code className={CODE}>{setup.subscribe_field}</code>
        </SetupRow>

        <SetupRow
          label="Signature header"
          hint="Every delivery is checked against this before we read a single field of it."
        >
          <code className={CODE}>{setup.signature_header}</code>
        </SetupRow>
      </dl>

      {/* These details are what you PASTE somewhere else. Nothing in this response has
          seen Meta, so none of it is evidence that the connection works — and a client
          who reads a filled-in setup card as "connected" will point ad spend at a
          handshake that never completed. The inbox is the only witness. */}
      <p className="flex items-start gap-2 text-xs text-ink-muted">
        <Inbox className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        Showing these details does not connect anything, and we cannot see your Meta
        setup from here. The first row in “Recent deliveries” below is what tells you it
        worked.
      </p>
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
  children: ReactNode;
}) {
  return (
    <div>
      <dt className="text-sm font-medium text-ink">{label}</dt>
      <dd className="mt-1">{children}</dd>
      <p className="mt-1 text-xs text-ink-faint">{hint}</p>
    </div>
  );
}

function CopyableValue({ value }: { value: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <code className={CODE}>{value}</code>
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
      className={QUIET_BUTTON}
    >
      <Copy className="h-3.5 w-3.5" />
      {copied ? "Copied" : label}
    </button>
  );
}
