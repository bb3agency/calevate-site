"use client";

import Link from "next/link";
import type { ComponentType } from "react";
import { use, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Eye,
  Info,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import {
  Card,
  EmptyState,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import {
  useFirstCampaignDecision,
  useTenant,
  useTenantCampaigns,
  useTenantFirstCampaignHold,
} from "@/lib/api/admin";
import {
  DECISION_COPY,
  DECISION_NOTE_MAX,
  decisionBlockReason,
  firstCampaignState,
  type FirstCampaignDecision,
  type FirstCampaignDecisionIn,
  type FirstCampaignHold,
  type FirstCampaignState,
} from "@/lib/api/firstCampaign";
import { VIEW_AS_ADMIN, VIEW_AS_PARAM } from "@/lib/api/session";

import { useAdminAccess } from "@/app/admin/access";

/**
 * Releasing (or refusing) an account's campaign calling — R-11's last hold.
 *
 * `POST /v1/admin/tenants/{tenant_id}/first-campaign-review` shipped with no caller
 * anywhere in the console, so the only way to release a held account was a curl. Every
 * self-serve signup starts in the held state by construction (absence of a row IS the
 * hold, `compliance/first_campaign.py`), which means the product's own front door led to
 * a gate whose key existed only in an operator's shell history.
 *
 * **What is being decided, said before it is decided.** This is an audited compliance
 * decision, not a toggle: it records a status, a note, the deciding operator and
 * optionally the campaign that was read, and it writes an `audit_log` entry per call. So
 * the screen shows the record it is about to write, in the shape it will be written —
 * including the two fields the operator cannot supply, because those are the two an
 * auditor most wants and the reason there is no "decided on" date picker here.
 *
 * **A rejection is not a deletion.** The note goes to the client VERBATIM on
 * `/c/[slug]/campaign-review`; the account stays held, they fix what was named, and a
 * reviewer looks again. That makes the note client-facing prose rather than an internal
 * jotting, and the form says so at the box where it is typed rather than in a comment
 * nobody reading the screen can see.
 *
 * **The decision is about the ACCOUNT.** `approved` releases it for good — this rule
 * never holds another of their campaigns — and while it stands every campaign is refused,
 * not only the first. `reviewed_campaign_id` is evidence of what a human read, not the
 * mechanism, which is why it is optional here and `ON DELETE SET NULL` there.
 *
 * **Two sessions, deliberately.** The state is READ through impersonation (`org:read`,
 * non-mutating, the only read of a tenant's review that exists) and the decision is
 * WRITTEN through the admin surface with the tenant in the path (`admin:tenants`, which
 * an impersonating principal is refused). That is D-22 working; `admin.ts` builds both.
 * The Record button is gated on that same `admin:tenants` and disabled with its reason,
 * so the refusal arrives before the click rather than as a 403 that reads like a fault.
 *
 * Every rule this form enforces is enforced again by the route (problem+json naming the
 * field) and again by `decision_says_what_was_reviewed` underneath it. The form is the
 * preview of the refusal, never the enforcement.
 *
 * The verdict boxes are the shared `NoticeBox` rather than the hand-built panel this
 * screen carried: it had independently chosen `rounded-xl` where the client's screens use
 * `rounded-card`, which is exactly the drift the primitive exists to stop. The two realms
 * now render the same four tones AND the same four icons for the same five states, so an
 * operator and the client they are on the phone with are looking at the same verdict.
 */
export default function FirstCampaignReviewPage({
  params,
}: {
  // Next 15: `params` is a Promise in every page, unwrapped with React's `use()` in a
  // client component — nextjs.org/docs/app/api-reference/file-conventions/dynamic-routes.
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const slug = tenant?.slug ?? "";
  // The mutation lives HERE rather than inside the form, for the reason the KYC screen
  // states: a successful write invalidates the hold, the form is remounted by its key to
  // pick up the new state, and a mutation held inside it would be remounted with it —
  // taking the confirmation of the write down at the moment the write landed.
  const decide = useFirstCampaignDecision(tenantId);
  const hold = useTenantFirstCampaignHold(slug);
  const write = useAdminAccess("admin:tenants", "record a review decision");

  if (tenantQuery.isLoading) return <Skeleton rows={6} />;
  if (tenantQuery.error)
    return <ProblemNotice error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />;
  if (!tenant) return <EmptyState title="Client not found" />;

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {tenant.name}
        </Link>
        {/* `admin/layout.tsx` prints no page title (unlike the client shell), so this
            heading is the only name this screen has. Delete it if a title lands there. */}
        <h1 className="mt-1 text-xl font-semibold text-ink">First campaign review</h1>
        <p className="text-sm text-ink-muted">
          Calevate reads the first campaign of every self-serve account before it dials —
          the contact list and where it came from, the script, and the disclosure line.
          Releasing the account clears this rule for good. Inbound answering is never held
          by it.
        </p>
      </div>

      {hold.error && <ProblemNotice error={hold.error} onRetry={() => hold.refetch()} />}

      {hold.isLoading ? (
        <Skeleton rows={4} />
      ) : !hold.data ? (
        /* The form is withheld rather than merely unpopulated, and the reason belongs on
           screen. This write replaces the CURRENT decision outright — deciding while the
           current one is unreadable can silently reverse a colleague's refusal, or
           re-release an account that was withdrawn an hour ago because complaints
           arrived. Making an operator retry a read is the cheaper failure. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot decide while the current state is unreadable"
        >
          <p className="mt-1 text-xs opacity-90">
            We could not read where this account stands. A decision replaces whatever is on
            file, so recording one now could reverse a colleague&apos;s without anyone
            seeing it happen. Retry the read above; the form comes back with it.
          </p>
        </NoticeBox>
      ) : (
        <>
          <WhereItStands hold={hold.data} tenantName={tenant.name} slug={slug} />
          {/* Remounted only when the STORED decision changes — an equal refetch keeps the
              key, so a poll cannot wipe a note an operator is halfway through writing.
              Resetting state via `key` rather than an effect is React's own answer
              (react.dev/learn/you-might-not-need-an-effect). */}
          <DecisionForm
            key={holdStamp(hold.data)}
            decide={decide}
            tenantName={tenant.name}
            slug={slug}
            write={write}
          />
          {decide.error != null && <ProblemNotice error={decide.error} />}
          {decide.data && (
            <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
              <p className="text-xs">
                Recorded as <span className="font-medium">{decide.data.status}</span> at{" "}
                {formatIST(decide.data.decided_at)} IST. The panel above has re-read the
                gate&apos;s own answer, and the client&apos;s campaign screen reflects it
                from their next request.
              </p>
            </NoticeBox>
          )}
        </>
      )}
    </div>
  );
}

/** Content, not identity: an equal refetch must not wipe a half-written note. */
function holdStamp(hold: FirstCampaignHold): string {
  return [hold.held, hold.rule, hold.status, hold.decision_note, hold.reviewed_campaign_id].join(
    "|",
  );
}

/**
 * The five states, in the operator's words — beside the client's words for the same five.
 *
 * Tone and icon match `/c/[slug]/campaign-review` state for state, deliberately: the two
 * screens are read side by side on a support call, and a client seeing a red box while
 * the operator sees amber is the two realms contradicting each other about a compliance
 * gate. Keyed on the STATE rather than the tone for the reason the client screen gives —
 * `warn` covers both "queued" and "held on a rule we cannot name".
 */
const OPERATOR_VERDICTS: Record<
  FirstCampaignState,
  { headline: string; tone: NoticeTone; icon: ComponentType<{ className?: string }> }
> = {
  pending: {
    headline: "Held — nobody has reviewed this account yet.",
    tone: "warn",
    icon: Clock,
  },
  rejected: {
    headline: "Held — a reviewer refused this account.",
    tone: "stop",
    icon: XCircle,
  },
  held_unknown: {
    headline: "Held on a rule this console does not recognise.",
    tone: "warn",
    icon: ShieldAlert,
  },
  released: {
    headline: "Released — cleared for campaign calling.",
    tone: "ok",
    icon: ShieldCheck,
  },
  never_applied: {
    headline: "This rule does not apply to this account.",
    tone: "neutral",
    icon: Info,
  },
};

/**
 * Where the account stands right now — the GATE's answer, not a re-derived one.
 *
 * `held` comes from `first_campaign_hold_blocker`, the same predicate that refuses the
 * launch and the dispatch tick, so this panel cannot tell an operator an account is clear
 * while the client is being refused. `firstCampaignState` is the one place that reads it,
 * shared with the client's own screen so the two realms cannot disagree — including about
 * `never_applied`, which is a managed account the rule exempts and NOT a released one.
 */
function WhereItStands({
  hold,
  tenantName,
  slug,
}: {
  hold: FirstCampaignHold;
  tenantName: string;
  slug: string;
}) {
  const state = firstCampaignState(hold);
  const verdict = OPERATOR_VERDICTS[state];
  const Icon = verdict.icon;

  return (
    <NoticeBox tone={verdict.tone} icon={<Icon className="h-5 w-5" />} title={verdict.headline}>
      {state === "never_applied" && (
        <p className="mt-1 text-xs opacity-90">
          The hold is scoped to the self-serve and trial motions. {tenantName} was onboarded
          by a person, so no campaign of theirs is held by this rule — recording a decision
          here is possible and changes nothing about their calling.
        </p>
      )}
      {state === "held_unknown" && hold.reason && (
        <p className="mt-1 text-xs opacity-90">{hold.reason}</p>
      )}

      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <div>
          <dt className="opacity-70">Decision on file</dt>
          <dd className="mt-0.5 font-medium">{hold.status ?? "none — nobody has looked"}</dd>
        </div>
        <div>
          <dt className="opacity-70">Decided</dt>
          <dd className="mt-0.5 font-medium">
            {hold.decided_at ? `${formatIST(hold.decided_at)} IST` : "—"}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="opacity-70">
            Note on file
            {hold.status === "rejected" && " — this is what the client is reading now"}
          </dt>
          <dd className="mt-0.5 whitespace-pre-wrap font-medium">{hold.decision_note ?? "—"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="opacity-70">Campaign read</dt>
          {/* The id and not a name: resolving it would be a second request for a fact
              that is evidence, not mechanism — and the campaign may since have been
              deleted, which the API made survivable on purpose (ON DELETE SET NULL). */}
          <dd className="mt-0.5 break-all font-mono">{hold.reviewed_campaign_id ?? "—"}</dd>
        </div>
      </dl>

      {/* The view-as marker, not a bare client-realm link: without it the client shell
          would build a client session this operator does not have (lib/api/session.tsx).
          It selects a credential and grants nothing — the view is read-only and every
          page view of it is audited (D-22), which the label says rather than leaving to
          a tooltip. */}
      <p className="mt-3 text-xs opacity-80">
        <Link
          href={`/c/${slug}/campaign-review?${VIEW_AS_PARAM}=${VIEW_AS_ADMIN}`}
          className="inline-flex items-center gap-1 font-medium underline"
          title="Read-only. Every page view is recorded in the audit log."
        >
          <Eye className="h-3.5 w-3.5" />
          What the client sees (read-only)
        </Link>{" "}
        — their own screen renders the note above verbatim.
      </p>
    </NoticeBox>
  );
}

const DECISIONS = Object.keys(DECISION_COPY) as FirstCampaignDecision[];

const FIELD =
  "w-full rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11";

/**
 * The decision itself.
 *
 * Starts EMPTY rather than prefilled from the record, which is the opposite of the KYC
 * form and deliberate. That one edits a document whose fields are COALESCEd, so a blank
 * means "leave as filed"; this one records a fresh judgement, `decision_note` is assigned
 * outright, and defaulting the note to the last reviewer's words invites re-recording
 * somebody else's sentence under your own name. There is no default decision either — a
 * pre-selected "release" is a release one stray Enter away.
 */
function DecisionForm({
  decide,
  tenantName,
  slug,
  write,
}: {
  decide: ReturnType<typeof useFirstCampaignDecision>;
  tenantName: string;
  slug: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [decision, setDecision] = useState<FirstCampaignDecision | null>(null);
  const [note, setNote] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const campaigns = useTenantCampaigns(slug);

  const draft: FirstCampaignDecisionIn | null =
    decision === null
      ? null
      : { decision, note, reviewed_campaign_id: campaignId === "" ? null : campaignId };
  const blocked = draft === null ? "Choose what you are recording." : decisionBlockReason(draft);
  const copy = decision === null ? null : DECISION_COPY[decision];

  return (
    <Card title="Record a decision">
      <p className="-mt-2 text-xs text-ink-muted">
        This keeps one decision per account — a release can be withdrawn when complaints
        arrive and granted again afterwards. Each decision writes its own audit entry, so
        the history is the audit log rather than this row.
      </p>

      <form
        className="mt-4 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (draft !== null) decide.mutate(draft);
        }}
      >
        {/* The permission this route requires, answered before the click (D-22 note in
            ../../access.ts: the WRITE is admin-realm, so `impersonating` is not the
            question here — the role's `admin:tenants` is). */}
        <RestrictionNote reason={write.reason} />

        <fieldset>
          <legend className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Decision
          </legend>
          <div className="mt-2 space-y-2">
            {DECISIONS.map((value) => (
              <label
                key={value}
                className="flex cursor-pointer gap-2 rounded-card border border-line p-3 text-xs hover:bg-black/5 dark:hover:bg-white/5"
              >
                <input
                  type="radio"
                  name="decision"
                  value={value}
                  checked={decision === value}
                  disabled={!write.allowed}
                  onChange={() => {
                    setDecision(value);
                    decide.reset();
                  }}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium text-ink">{DECISION_COPY[value].label}</span>
                  <span className="mt-0.5 block text-ink-muted">{DECISION_COPY[value].effect}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {/* The note's meaning changes with the decision — audit evidence versus a
            message the client reads — so the label and the hint change with it rather
            than describing both jobs at once and being wrong about one. */}
        <div>
          <label
            htmlFor="fcr-note"
            className="text-xs font-semibold uppercase tracking-wide text-ink-muted"
          >
            {copy?.noteLabel ?? "Note"}
          </label>
          <textarea
            id="fcr-note"
            rows={4}
            maxLength={DECISION_NOTE_MAX}
            value={note}
            disabled={!write.allowed}
            onChange={(e) => {
              setNote(e.target.value);
              decide.reset();
            }}
            placeholder={
              decision === "rejected"
                ? "e.g. The contact list is a purchased list and the campaign declares it as opt-in. Re-upload a list you collected yourself, or declare the true source, and we will look again."
                : "e.g. Read campaign “Diwali offers”: 320 contacts from their own enquiry form, script matches the DLT template, disclosure line present and in Telugu."
            }
            className={`mt-1 ${FIELD}`}
          />
          <p className="mt-1 max-w-xl text-xs text-ink-muted">
            {copy?.noteHint ??
              "What was reviewed, or what was wrong with it. Choose a decision above and this says which."}
          </p>
          <p className="mt-1 text-xs text-ink-faint">
            {note.trim().length}/{DECISION_NOTE_MAX} characters. This is a note about a
            campaign — no phone numbers, no transcript text.
          </p>
        </div>

        <div>
          <label
            htmlFor="fcr-campaign"
            className="text-xs font-semibold uppercase tracking-wide text-ink-muted"
          >
            Campaign read (optional)
          </label>
          <select
            id="fcr-campaign"
            value={campaignId}
            disabled={!write.allowed}
            onChange={(e) => {
              setCampaignId(e.target.value);
              decide.reset();
            }}
            className={`mt-1 max-w-md ${FIELD}`}
          >
            <option value="">— not recorded —</option>
            {(campaigns.data ?? []).map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name} · {campaign.status} · {campaign.contacts} contacts
              </option>
            ))}
          </select>
          <p className="mt-1 max-w-xl text-xs text-ink-muted">
            Evidence, not mechanism: the hold is on the account, so deleting this campaign
            later cannot change whether they are released. Leaving it blank keeps whatever
            was recorded before — a reversal that names no campaign does not erase what the
            first reviewer read.
          </p>
          {/* Error first: with a failed list `campaigns.data` is undefined, and saying
              "this account has no campaigns yet" about a read that never landed would
              invite a release recorded on a premise nobody checked. */}
          {/* `|| !campaigns.data` covers the non-answer that carries no error: a query
              TanStack has PAUSED because the browser is offline has `error === null` and
              no data, so neither arm was taken and the picker sat empty and unexplained —
              which is the premise this branch exists to stop a reviewer acting on. */}
          {campaigns.error != null || !campaigns.data ? (
            <p className="mt-1 text-xs text-ink-muted">
              Their campaigns could not be listed, so this field is empty. It is optional —
              the decision can still be recorded without naming one.
            </p>
          ) : campaigns.data.length === 0 ? (
            <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
              This account has no campaigns yet. Releasing it now clears the rule before
              anything exists to read — which is a decision, not an accident, so record why
              in the note.
            </p>
          ) : null}
        </div>

        <WillRecord draft={draft} tenantName={tenantName} />

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={decide.isPending || blocked !== null || !write.allowed}
            className="rounded-md bg-brand-strong px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
          >
            {decide.isPending ? "Recording…" : "Record decision"}
          </button>
          {/* The refusal given before the click rather than as a 422 from the route or a
              500 out of the CHECK constraint underneath it. */}
          {blocked && <span className="text-xs text-amber-700 dark:text-amber-400">{blocked}</span>}
        </div>
      </form>
    </Card>
  );
}

/**
 * What this write will actually put in the record, said before it is made.
 *
 * The two facts an auditor most needs are the two the operator cannot supply: the
 * deciding admin comes from the session that sends the request, and `decided_at` is
 * stamped by the database in the same statement. Saying that here is the point — it is
 * why this form has no "decided on" date picker and why nobody should go looking for one.
 */
function WillRecord({
  draft,
  tenantName,
}: {
  draft: FirstCampaignDecisionIn | null;
  tenantName: string;
}) {
  const note = draft?.note.trim() ?? "";
  return (
    <div className="rounded-card border border-line bg-app p-3 text-xs text-ink-muted">
      <p className="font-medium text-ink">This will record, against {tenantName}:</p>
      <ul className="mt-1.5 space-y-1">
        <li>
          <span className="text-ink-faint">Outcome</span> —{" "}
          {draft === null
            ? "nothing yet; choose a decision above."
            : draft.decision === "approved"
              ? "approved. Campaign calling opens and this rule never holds another of their campaigns."
              : "rejected. Every campaign stays blocked, and the client is shown the note."}
        </li>
        <li>
          <span className="text-ink-faint">Note</span> —{" "}
          {note === "" ? (
            "empty; the database refuses a decision that does not say what was reviewed."
          ) : (
            <span className="text-ink">
              “{note}”
              {draft?.decision === "rejected" && " — shown to the client word for word."}
            </span>
          )}
        </li>
        <li>
          <span className="text-ink-faint">Campaign read</span> —{" "}
          {draft?.reviewed_campaign_id
            ? "the one selected above, checked against this tenant before it is stored."
            : "none named; whatever was recorded before is kept."}
        </li>
        <li>
          <span className="text-ink-faint">Decided by</span> — the admin account sending
          this request. Taken from your session, not from this form.
        </li>
        <li>
          <span className="text-ink-faint">Decided at</span> — stamped by the database as
          the row is written.
        </li>
        <li>
          <span className="text-ink-faint">Audit</span> — one audit-log entry carrying the
          decision and the note, so a later reversal adds a row rather than editing this
          one.
        </li>
      </ul>
    </div>
  );
}
