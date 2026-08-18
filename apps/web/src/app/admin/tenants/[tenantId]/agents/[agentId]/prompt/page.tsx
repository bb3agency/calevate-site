"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft } from "lucide-react";

import {
  Card,
  EmptyState,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useTenant } from "@/lib/api/admin";
import {
  usePromptHistory,
  useRollbackPrompt,
  useWritePrompt,
  type PromptVersion,
} from "@/lib/api/prompts";
import {
  useApplyChanges,
  useConcludeExperiment,
  usePublishAgent,
  usePublishingRefresh,
  useSetCallCap,
  useStartExperiment,
  useTenantExperiment,
  useTenantEngineState,
  useTenantLanes,
  useTenantPending,
  useUndoChanges,
  type ConcludeExperimentOut,
  type Experiment,
  type ExperimentVariant,
  type PendingState,
} from "@/lib/api/publishing";
import type {
  AgentVoice,
  AgentVoiceState,
  EngineVerification,
} from "@/lib/api/publishing";
import { useSetAgentVoice, useTenantVoiceCatalogue, type Voice } from "@/lib/api/voices";

import { useAdminAccess } from "@/app/admin/access";

/**
 * One agent's script: its version history, the staged-change controls, and the call
 * cap (admin surface — D-22 makes impersonation read-only, so every mutation on this
 * page can only exist here).
 *
 * Two-speed publishing (SURFACES §2b) is what makes this a page and not just a list.
 * Saving a version STAGES it: `agents.system_prompt_id` is the draft pointer and
 * `live_prompt_id` is what callers hear, and they are allowed to differ. So the
 * screen has to answer three questions that used to have one answer between them —
 * what is written, what is staged, and what is live — and offer the two buttons §2b
 * names: **Apply to live calls** and **Undo**.
 *
 * The client sees the same staged state on their own agents screen and cannot act on
 * it. That asymmetry is the point: they can tell an edit has not landed without
 * calling us, and only we can land it.
 *
 * The tenant SLUG is read from `useTenant` because the two publishing GETs are
 * client-realm endpoints, reached from here through impersonation (`viewAsSession`) —
 * the D-22 split `admin.ts` already uses for the KB queue: read as the tenant, write
 * as ourselves.
 */
export default function AgentPromptPage({
  params,
}: {
  params: Promise<{ tenantId: string; agentId: string }>;
}) {
  const { tenantId, agentId } = use(params);
  const tenant = useTenant(tenantId);
  const slug = tenant.data?.slug ?? "";

  const history = usePromptHistory(tenantId, agentId);
  const pending = useTenantPending(slug, agentId);
  const newVersion = useWritePrompt(tenantId, agentId);
  const rollback = useRollbackPrompt(tenantId, agentId);
  // Writing or rolling back a version moves the staged state this page renders, and
  // neither prompt hook can invalidate it alone (it is keyed by slug, which they do
  // not have). The screen that knows both composes them.
  const refreshPublishing = usePublishingRefresh({ tenantId, agentId, slug });

  // Every write on this screen — save, roll back, apply, undo, call cap — is
  // `agents:write` (agents/prompt_routes.py, agents/publishing_routes.py). One gate, read
  // once, passed down: five controls that each asked separately would each answer at a
  // different moment as `/v1/admin/me` resolved.
  const write = useAdminAccess("agents:write", "change this agent's script");

  const [body, setBody] = useState("");
  const [notes, setNotes] = useState("");

  return (
    <div className="space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Client
        </Link>
        {/* Kept: `admin/layout.tsx` prints no page title, so this is the screen's only
            name. Delete it if one lands in the shell. */}
        <h1 className="mt-1 text-xl font-semibold text-ink">Agent prompt</h1>
        <p className="text-sm text-ink-muted">
          Every save is a new immutable version, staged rather than published; the live
          one is a separate pointer that only Apply moves.
        </p>
      </div>

      {tenant.error && <ProblemNotice error={tenant.error} onRetry={() => tenant.refetch()} />}

      <GoLivePanel
        tenantId={tenantId}
        agentId={agentId}
        slug={slug}
        write={write}
        pending={pending.data}
        hasAScript={history.data === undefined ? undefined : history.data.length > 0}
        isLoading={tenant.isLoading || pending.isLoading || history.isLoading}
        readFailed={pending.error != null || history.error != null}
      />

      <PublishingPanel
        tenantId={tenantId}
        agentId={agentId}
        slug={slug}
        write={write}
        pending={pending.data}
        isLoading={tenant.isLoading || pending.isLoading}
        error={pending.error}
        onRetry={() => pending.refetch()}
      />

      <CallCapPanel
        tenantId={tenantId}
        agentId={agentId}
        slug={slug}
        pending={pending.data}
        write={write}
      />

      <VoicePanel
        tenantId={tenantId}
        agentId={agentId}
        slug={slug}
        pending={pending.data}
        tenantLoading={tenant.isLoading || pending.isLoading}
        write={write}
      />

      <ExperimentPanel
        tenantId={tenantId}
        agentId={agentId}
        slug={slug}
        write={write}
        versions={history.data}
      />

      {history.error && (
        <ProblemNotice error={history.error} onRetry={() => history.refetch()} />
      )}
      {rollback.error && <ProblemNotice error={rollback.error} />}

      <Card title="Version history">
        <p className="-mt-2 text-xs text-ink-muted">
          Rolling back creates a NEW version with that content — history is never rewritten
          — and it applies IMMEDIATELY: FLOWS §7 defines rollback as republishing an earlier
          version, which is the recovery path, so it does not wait behind Apply.
        </p>
        <div className="mt-3">
          <RestrictionNote reason={write.reason} />
          {history.isLoading ? (
            <Skeleton rows={4} />
          ) : history.data?.length ? (
            <ul className="space-y-2">
              {history.data.map((entry) => (
                <li
                  key={entry.id}
                  className="flex flex-wrap items-center gap-2 rounded-card border border-line p-3"
                >
                  <span className="font-mono text-sm font-semibold text-ink">
                    v{entry.version}
                  </span>
                  <VersionBadges entry={entry} pending={pending.data} />
                  <span className="text-xs text-ink-muted">{formatIST(entry.created_at)}</span>
                  {entry.notes && <span className="text-xs text-ink-muted">{entry.notes}</span>}
                  {!entry.active && (
                    <button
                      type="button"
                      disabled={rollback.isPending || !write.allowed}
                      onClick={() =>
                        rollback.mutate(
                          { version: entry.version },
                          { onSuccess: () => void refreshPublishing() },
                        )
                      }
                      className="ml-auto rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-ink hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/5"
                    >
                      Roll back to this
                    </button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No prompt versions yet"
              hint="Write the first version below."
            />
          )}
        </div>
      </Card>

      <Card title="New version">
        <div>
          <RestrictionNote reason={write.reason} />
          {newVersion.error && <ProblemNotice error={newVersion.error} />}
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              newVersion.mutate(
                { body, ...(notes.trim() ? { notes: notes.trim() } : {}) },
                {
                  onSuccess: () => {
                    setBody("");
                    setNotes("");
                    void refreshPublishing();
                  },
                },
              );
            }}
          >
            <textarea
              required
              minLength={20}
              rows={8}
              value={body}
              disabled={!write.allowed}
              onChange={(ev) => setBody(ev.target.value)}
              placeholder="The full system prompt for this agent (min 20 characters)."
              className={FIELD}
            />
            <input
              value={notes}
              disabled={!write.allowed}
              onChange={(ev) => setNotes(ev.target.value)}
              maxLength={200}
              placeholder="Notes (optional) — what changed and why"
              className={FIELD}
            />
            <button
              type="submit"
              disabled={newVersion.isPending || body.length < 20 || !write.allowed}
              className={PRIMARY_BUTTON_SM}
            >
              Save as new version
            </button>
          </form>
          {/* This sentence used to say the opposite — "if the agent is live, this goes
              to the voice platform immediately" — which was true until two-speed
              publishing landed and is now the single most expensive thing this page
              could get wrong. */}
          <p className="mt-2 text-xs text-ink-muted">
            Saving stages the version. Callers keep hearing the live one until you press
            Apply above.
          </p>
        </div>
      </Card>
    </div>
  );
}

/** The form language of this screen, in one place rather than per control. */
const FIELD =
  "w-full rounded-md border border-line bg-surface px-2 py-1.5 text-xs text-ink placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11";



/**
 * Which version is staged and which one callers hear.
 *
 * `active` on a history row is the DRAFT pointer (`prompts.py::list_prompt_versions`
 * derives it from `system_prompt_id`), so labelling it "live" — as this page did
 * before two-speed publishing — now says the opposite of the truth. The live version
 * NUMBER comes from the pending read, which is the server's answer; the only
 * inference made here is that with nothing pending the two pointers are equal, which
 * is the definition of `has_pending` and not a second rule.
 *
 * While the pending read is unavailable the badge says "draft" and claims nothing
 * about live: a wrong green badge is worse than a missing one.
 */
function VersionBadges({
  entry,
  pending,
}: {
  entry: PromptVersion;
  pending: PendingState | undefined;
}) {
  // The live version NUMBER as the server reports it: while a script change is staged
  // the pending row carries it. With nothing staged the two pointers are equal — that
  // is the definition of `has_pending`, not a second rule — so the draft row is live.
  const liveVersion = pending?.pending.find((c) => c.field === "script")?.live_version ?? null;
  const isStaged = pending?.has_pending === true && entry.active;
  const isLive =
    pending !== undefined &&
    (pending.has_pending ? entry.version === liveVersion : entry.active);

  return (
    <>
      {isLive && (
        <span className="rounded bg-brand-strong px-1.5 py-0.5 text-xs font-medium text-white">
          live
        </span>
      )}
      {isStaged && (
        <span className="rounded bg-amber-200 px-1.5 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-900 dark:text-amber-100">
          staged
        </span>
      )}
      {entry.active && !isLive && !isStaged && (
        <span className="rounded bg-brand-soft px-1.5 py-0.5 text-xs font-medium text-brand-strong">
          draft
        </span>
      )}
    </>
  );
}

/**
 * The FIRST publish — FLOWS §1 step 7, and the seam that had no control anywhere.
 *
 * Every other publish in this product is a RE-publish, guarded on the agent already
 * being live: Apply pushes only `if row.is_live`, the call cap and the T0 recompile only
 * when `status == 'live' AND engine_agent_ref`. An agent minted by the wizard is
 * `draft`/`NULL`, so none of them fired and no screen offered the one endpoint that
 * would — `POST …/agents/{id}/publish` was mounted, tested, and called by nobody. A
 * founder could finish the wizard, invite the owner and hand over an account whose agent
 * had never reached the voice platform.
 *
 * ## What this panel refuses to guess
 *
 * `published` is the SERVER's answer (`engine_agent_ref IS NOT NULL`), never inferred
 * from `status`, and while the read has not landed the panel is a skeleton — not a
 * button that might be about to publish an agent that is already live, and not an
 * "unpublished" state built from an absent read (§52).
 *
 * The script precondition is stated rather than discovered: `publish_agent` refuses an
 * agent with no prompt version by name (`agent_has_no_script`) instead of shipping a
 * hardcoded English placeholder, so the button is disabled with that sentence when the
 * history is empty. It is a HINT, not the enforcement — the server refuses either way,
 * and if the two ever disagree the refusal is what the operator sees, through
 * `ProblemNotice`, in the server's own words.
 *
 * ## What it does NOT claim
 *
 * Publishing is not sign-off. FLOWS §1 step 7 puts a test call and a regression
 * mini-suite in front of it, both pilot-gated and neither of them ours to run yet, so
 * this panel says so instead of implying that pressing the button completed a gate.
 */
function GoLivePanel({
  tenantId,
  agentId,
  slug,
  pending,
  hasAScript,
  isLoading,
  readFailed,
  write,
}: {
  tenantId: string;
  agentId: string;
  slug: string;
  pending: PendingState | undefined;
  /** `undefined` while the version history has not answered — never assumed false. */
  hasAScript: boolean | undefined;
  isLoading: boolean;
  /**
   * Whether either read this panel depends on came back refused.
   *
   * A BOOLEAN, not the error: both of them are already rendered as refusals with their
   * own retry — the pending read by `PublishingPanel` directly below, the history read
   * beside the version list — and a second `ProblemNotice` quoting the same sentence
   * makes the page look like two things failed. What this panel needs from a failure is
   * only that it must claim NOTHING, which is what the flag buys.
   */
  readFailed: boolean;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const publish = usePublishAgent({ tenantId, agentId, slug });

  return (
    <Card title="Voice platform">
      <div className="mt-1 space-y-3">
        <RestrictionNote reason={write.reason} />
        {publish.error && <ProblemNotice error={publish.error} />}

        {isLoading && !pending ? (
          <Skeleton rows={2} />
        ) : !pending ? (
          !readFailed && (
            <p className="text-xs text-ink-muted">
              We could not read whether this agent is on the voice platform, so there is
              nothing to act on here yet.
            </p>
          )
        ) : !pending.engine_verification.publishable ? (
          /*
           * THE BUTTON IS NOT OFFERED, because pressing it can only ever fail (D-281).
           * This deployment's voice platform does not host agents built here — its agents
           * are deployed to it separately, so there is no create endpoint and no prompt
           * read-back — and `publish_agent` refuses every attempt by name. A screen that
           * rendered Publish anyway would be offering a control the route cannot honour,
           * which is exactly the divergence the capability descriptor exists to remove.
           * The sentence is the server's own (`engine_verification.headline`), never a
           * second wording that could drift from the refusal.
           */
          <NoticeBox
            tone="warn"
            icon={<AlertTriangle className="h-5 w-5" />}
            title="This agent cannot be published from here"
          >
            <p className="mt-0.5 text-xs">{pending.engine_verification.headline}</p>
          </NoticeBox>
        ) : pending.published ? (
          <p className="text-sm text-ink-muted">
            This agent is on the voice platform. Script changes reach it through Apply
            above; the voice and the call cap have their own panels below.
          </p>
        ) : (
          <>
            <NoticeBox
              tone="warn"
              icon={<AlertTriangle className="h-5 w-5" />}
              title="This agent has never reached the voice platform"
            >
              <p className="mt-0.5 text-xs">
                Nothing dials it and nothing answers on it. Publishing creates the agent
                on the platform and records the routing that lets an inbound call find
                this client.
              </p>
            </NoticeBox>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={publish.isPending || !write.allowed || hasAScript === false}
                onClick={() => publish.mutate()}
                className={PRIMARY_BUTTON_SM}
              >
                {publish.isPending ? "Publishing…" : "Publish to the voice platform"}
              </button>
              <span className="text-xs text-ink-muted">
                {hasAScript === false
                  ? "This agent has no script yet — complete the client's intake, or save a version below, first."
                  : "FLOWS §1 step 7 asks for a test call and a regression run before this. Both are pilot-gated and neither is automated here, so this button publishes — it does not sign anything off."}
              </span>
            </div>
          </>
        )}

        {publish.data && (
          <p className="text-xs text-ink-muted">
            Published — the platform holds this agent as{" "}
            <span className="font-mono">{publish.data.engine_agent_ref}</span>.
          </p>
        )}
      </div>
    </Card>
  );
}

/**
 * "Apply to live calls" / "Undo" — the two buttons §2b names, and nothing else.
 *
 * Apply sends `expected_version` (the CAS token of BACKEND-PATTERNS §5): the staged
 * version this operator is looking at. Without it, two operators on the same agent
 * make the second one publish a draft they never read — `apply_to_live` refuses that
 * with `stale_pending_change`, which arrives as problem+json and is rendered by
 * `ProblemNotice` rather than second-guessed here.
 *
 * `applied: false` is a 200, not an error: a double-clicked button is the same intent
 * already satisfied. The result line says what actually happened either way, including
 * `engine_synced` — an agent that is not live keeps its pointer moved but reaches no
 * vendor, and pretending otherwise would be a lie about where the script is running.
 */
function PublishingPanel({
  tenantId,
  agentId,
  slug,
  pending,
  isLoading,
  error,
  onRetry,
  write,
}: {
  tenantId: string;
  agentId: string;
  slug: string;
  pending: PendingState | undefined;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const target = { tenantId, agentId, slug };
  const apply = useApplyChanges(target);
  const undo = useUndoChanges(target);

  const staged = pending?.pending.find((change) => change.field === "script");
  const busy = apply.isPending || undo.isPending;

  return (
    <Card title="Publishing">
      {/* The precedence rule §2b asks to be stated in the UI, in the server's own
          words — the same sentence the client sees on their agents screen. */}
      {pending && <p className="-mt-2 text-xs text-ink-muted">{pending.precedence_rule}</p>}
      <div className="mt-3 space-y-3">
        <RestrictionNote reason={write.reason} />
        {error != null && <ProblemNotice error={error} onRetry={onRetry} />}
        {apply.error && <ProblemNotice error={apply.error} />}
        {undo.error && <ProblemNotice error={undo.error} />}

        {isLoading && !pending ? (
          <Skeleton rows={2} />
        ) : !pending ? (
          error == null && (
            <p className="text-xs text-ink-muted">
              Publishing state is unavailable for this agent.
            </p>
          )
        ) : pending.has_pending && staged ? (
          <>
            <NoticeBox
              tone="warn"
              icon={<AlertTriangle className="h-5 w-5" />}
              title={staged.headline}
            >
              <p className="mt-0.5 text-xs">{staged.why}</p>
              <p className="mt-0.5 text-xs opacity-80">Staged {formatIST(staged.staged_at)}</p>
            </NoticeBox>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={busy || !write.allowed}
                onClick={() => apply.mutate({ expected_version: staged.staged_version })}
                className={PRIMARY_BUTTON_SM}
              >
                {apply.isPending ? "Applying…" : "Apply to live calls"}
              </button>
              <button
                type="button"
                disabled={busy || !write.allowed}
                onClick={() => undo.mutate()}
                className={SECONDARY_BUTTON_SM}
              >
                {undo.isPending ? "Undoing…" : "Undo"}
              </button>
              <span className="text-xs text-ink-muted">
                {pending.published
                  ? "Apply pushes this script to the voice platform now."
                  : "This agent is not on the voice platform yet, so Apply moves our pointer only."}
              </span>
            </div>
          </>
        ) : (
          <p className="text-sm text-ink-muted">
            Nothing staged. The live script is what the client&apos;s dashboard describes.
          </p>
        )}

        {apply.data && (
          <p className="text-xs text-ink-muted">
            {apply.data.applied
              ? `Applied — callers now hear v${apply.data.live_version}.`
              : `Nothing to apply — v${apply.data.live_version} was already live.`}
            {apply.data.applied &&
              (apply.data.engine_synced
                ? " The voice platform has it."
                : " The agent is not live, so nothing was sent to the voice platform.")}
          </p>
        )}
        {undo.data && (
          <p className="text-xs text-ink-muted">
            {undo.data.undone
              ? `Discarded v${undo.data.discarded_version}. The draft is back to v${undo.data.live_version ?? "—"}; the discarded version stays in the history.`
              : "Nothing was staged, so nothing was discarded."}
          </p>
        )}

        {pending && (
          <LiveConfirmation
            slug={slug}
            agentId={agentId}
            verification={pending.engine_verification}
            published={pending.published}
          />
        )}
      </div>
    </Card>
  );
}

/**
 * What "live" is actually claiming, and the button that goes and checks.
 *
 * THE DEFECT THIS RENDERS. Every other publishing field on this page — the applied
 * version, `voice.live` — records what we SENT the voice platform on the strength of a
 * 2xx. A 2xx says the vendor took the bytes; whether the agent is RUNNING them is a
 * different claim and the one a client's compliance disclosure depends on. The server
 * now reads the agent back on every publish and stores the verdict, and this is where an
 * operator sees which of the four answers they have.
 *
 * `confirmed` is rendered, never `state !== "unverified"`. The four states are four
 * different answers and only one of them is evidence: `unreadable` means the voice
 * platform's reply did not contain the field, `unreachable` means it did not reply.
 * Collapsing either into "fine" is exactly the rounding-up the read-back exists to stop.
 *
 * The RE-CHECK is a button, not a query that runs on mount, because it costs a request
 * to the vendor per press — a screen that dialled them on every page view would be a
 * rate-limit incident wearing a reassurance. §52 governs its three states: the pending
 * fetch is a SKELETON, a failure is a REFUSAL through `ProblemNotice` (never a blank
 * panel and never a stale green), and the answer is the server's own sentence.
 */
function LiveConfirmation({
  slug,
  agentId,
  verification,
  published,
}: {
  slug: string;
  agentId: string;
  verification: EngineVerification;
  published: boolean;
}) {
  const [checking, setChecking] = useState(false);
  const engineState = useTenantEngineState(slug, agentId, checking);

  return (
    <div className="rounded-card border border-line p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            What the voice platform was confirmed to be running
          </p>
          <p className="mt-1 text-xs text-ink">{verification.headline}</p>
          {verification.confirmed && verification.verified_at && (
            <p className="mt-0.5 text-xs text-ink-muted">
              Confirmed {formatIST(verification.verified_at)}.
            </p>
          )}
        </div>
        {published && (
          <button
            type="button"
            disabled={engineState.isFetching}
            onClick={() => {
              setChecking(true);
              void engineState.refetch();
            }}
            className={SECONDARY_BUTTON_SM}
          >
            {engineState.isFetching ? "Checking…" : "Check the voice platform now"}
          </button>
        )}
      </div>

      {!verification.publishable && (
        /* The reason this agent has nothing to confirm, said once here as well as on the
           publish panel: an operator who scrolls straight to this card must not read
           "nothing confirmed" as a publish that went wrong. */
        <p className="mt-2 text-xs text-ink-muted">
          Publishing is unavailable on this deployment&rsquo;s voice platform, so there is
          nothing for a read-back to confirm.
        </p>
      )}

      {verification.publishable && !verification.confirmed && published && (
        /* Amber and unmissable, because the failure this covers looks like success from
           every other angle: the agent says `live`, the version list says the right
           number, and nobody has established that a caller hears any of it. */
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
          Nothing here is wrong yet — it is unconfirmed. Publish again, or check now, to
          find out which.
        </p>
      )}

      {checking && (
        <div className="mt-3 border-t border-line pt-3">
          {engineState.error != null ? (
            <ProblemNotice error={engineState.error} onRetry={() => void engineState.refetch()} />
          ) : engineState.isPending ? (
            <Skeleton rows={2} />
          ) : engineState.data ? (
            <>
              <p
                className={
                  engineState.data.in_sync
                    ? "text-xs text-ink"
                    : "text-xs font-medium text-amber-700 dark:text-amber-400"
                }
              >
                {engineState.data.detail}
              </p>
              <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
                <PropertyVerdict label="Script" verdict={engineState.data.prompt_applied} />
                {/*
                 * TWO DISCLOSURE VERDICTS, and the labels have to say which is which.
                 * "Disclosure (spoken first)" is the engine's GREETING field — the
                 * deterministic first utterance, the one hard rule 5 and SEC-COMP §1 are
                 * about, and the only one a publish is refused over. "Disclosure (in
                 * script)" is the second copy both adapters also send; a mismatch there
                 * is a rendering difference worth seeing, not a compliance failure. One
                 * label reading "Disclosure line" for whichever we happened to check is
                 * how P3.3 stayed invisible on this very screen.
                 */}
                <PropertyVerdict
                  label="Disclosure (spoken first)"
                  verdict={engineState.data.disclosure_applied}
                />
                <PropertyVerdict
                  label="Disclosure (in script)"
                  verdict={engineState.data.prompt_disclosure_applied}
                />
                {/* D-163. The one verdict on this panel that no client setting can
                    explain away: the platform rules that make the agent admit it is an
                    AI and admit the call is recorded when a caller ASKS. Rendered here
                    rather than folded into "Script" because it sits at the TAIL of the
                    prompt, which is where a vendor length ceiling truncates — so an
                    engine can hold every word of the script and none of the rules under
                    it, and a single verdict would report that agent green. A `false`
                    here is `runbooks/agent-engine-drift.md`'s gravest case. */}
                <PropertyVerdict
                  label="Truthful-answer rule"
                  verdict={engineState.data.truthful_answer_applied}
                />
                <PropertyVerdict label="Voice" verdict={engineState.data.voice_applied} />
              </dl>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

/**
 * One read-back property, as a TRI-STATE.
 *
 * `null` is "the voice platform's answer did not contain this", which is neither a match
 * nor a mismatch — the `AgentSnapshot.*_readable` doctrine, carried all the way to the
 * screen. Rendering it as a cross would send an operator to fix a working agent;
 * rendering it as a tick would be the lie the whole read-back exists to prevent.
 */
function PropertyVerdict({ label, verdict }: { label: string; verdict: boolean | null }) {
  const reading =
    verdict === true ? "Matches" : verdict === false ? "Does not match" : "Could not read";
  const tone =
    verdict === true
      ? "text-ink"
      : verdict === false
        ? "text-amber-700 dark:text-amber-400"
        : "text-ink-muted";
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className={`text-sm font-medium ${tone}`}>{reading}</dd>
    </div>
  );
}

/**
 * The cost-runaway guard (§2b:107): the longest one call may run, and what that costs.
 *
 * It applies IMMEDIATELY — `set_call_cap` re-publishes a live agent in the same
 * transaction, so a cap that only landed in our table can never be shown as if the
 * engine were holding it — which is why this panel has no Apply step and says so.
 *
 * Seconds, not minutes, in the input: the column is seconds, the bounds published by
 * `/v1/agents/lanes` are seconds, and converting through minutes would silently
 * round a 330s cap set by anyone else. The minute reading is shown beside it, which
 * is the half an operator actually thinks in.
 *
 * No client-side range check beyond the input's own min/max: `call_cap_out_of_range`
 * is the server's refusal, with its own message, and a second copy of the rule here
 * is a rule that drifts.
 */
function CallCapPanel({
  tenantId,
  agentId,
  slug,
  pending,
  write,
}: {
  tenantId: string;
  agentId: string;
  slug: string;
  pending: PendingState | undefined;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const lanes = useTenantLanes(slug);
  const save = useSetCallCap({ tenantId, agentId, slug });
  // `null` means "not edited yet" — the field shows the server's effective cap. An
  // empty string is a real instruction (clear the override, fall back to the platform
  // default) and must not be confused with "unchanged".
  const [seconds, setSeconds] = useState<string | null>(null);

  const field =
    seconds ??
    (pending && !pending.call_cap_is_platform_default
      ? String(pending.effective_call_cap_s)
      : "");
  const parsed = field.trim() === "" ? null : Number(field);
  const worstCase = save.data?.worst_case_call_cost_inr ?? pending?.worst_case_call_cost_inr;
  const hasWorstCase = worstCase !== undefined && worstCase !== null;

  return (
    <Card title="Maximum call length">
      <p className="-mt-2 text-xs text-ink-muted">
        Applies immediately — a live agent is re-published with it, so there is nothing to
        apply. Clearing the box restores the platform default; it never means unlimited.
      </p>
      <div className="mt-3 space-y-3">
        <RestrictionNote reason={write.reason} />
        {save.error && <ProblemNotice error={save.error} />}

        {pending ? (
          <dl className="grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-muted">In force</dt>
              <dd className="text-sm font-medium tabular-nums text-ink">
                {pending.effective_call_cap_s}s
                <span className="ml-1 text-xs font-normal text-ink-muted">
                  ({minutesReading(pending.effective_call_cap_s)}
                  {pending.call_cap_is_platform_default ? ", platform default" : ", set here"})
                </span>
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-muted">
                Worst case, one call
              </dt>
              {/* Null is "no rate on the plan", not free. Rendering ₹0 would be a lie
                  the client would then see on their own screen. The value is an exact
                  NUMERIC string and is never parsed (hard rule 7). */}
              <dd className="text-sm font-medium tabular-nums text-ink">
                {hasWorstCase ? `₹${worstCase}` : "no rate on this plan"}
              </dd>
            </div>
          </dl>
        ) : (
          <Skeleton rows={1} />
        )}

        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ max_call_duration_s: parsed });
          }}
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="call-cap" className="text-xs text-ink-muted">
              Seconds
            </label>
            <input
              id="call-cap"
              type="number"
              inputMode="numeric"
              value={field}
              min={lanes.data?.call_cap_min_s}
              max={lanes.data?.call_cap_max_s}
              disabled={!write.allowed}
              onChange={(ev) => setSeconds(ev.target.value)}
              placeholder={
                lanes.data ? String(lanes.data.call_cap_default_s) : "platform default"
              }
              className={`w-32 tabular-nums ${FIELD}`}
            />
          </div>
          <button
            type="submit"
            disabled={save.isPending || !write.allowed}
            className={PRIMARY_BUTTON_SM}
          >
            {save.isPending ? "Saving…" : "Set cap"}
          </button>
          <span className="text-xs text-ink-muted">
            {parsed === null
              ? "Empty — restores the platform default."
              : `${minutesReading(parsed)} per call.`}
            {/* Three states, not two. `lanes` supplies this input's `min`/`max`, so a
                FAILED read silently removes the bounds from a control that is still
                pressable — the operator types a value, the server refuses it, and nothing
                on the screen ever said the range was unknown. §52: failure is a refusal,
                and the refusal here is a sentence rather than a withdrawn control,
                because the server is the enforcement and blocking the field would stop
                work the operator can still legitimately do. */}
            {lanes.isError
              ? " The allowed range could not be read, so this box is unbounded here; the" +
                " server still enforces it."
              : lanes.data
                ? ` Allowed ${lanes.data.call_cap_min_s}–${lanes.data.call_cap_max_s}s; default ${lanes.data.call_cap_default_s}s.`
                : ""}
          </span>
        </form>

        {save.data && (
          <p className="text-xs text-ink-muted">
            Saved — {save.data.effective_call_cap_s}s per call
            {save.data.is_platform_default ? " (platform default)" : ""}.
            {save.data.engine_synced
              ? " The voice platform has it."
              : " The agent is not live, so nothing was sent to the voice platform."}
          </p>
        )}
      </div>
    </Card>
  );
}

/**
 * Which voice this agent speaks in — D-36's premium/value ladder, selectable and, now,
 * READABLE.
 *
 * **Why this screen.** Voice is agent CONFIGURATION and the write is admin-realm
 * `agents:write` (`agents/voice_routes.py`, D-21: which voice speaks Telugu well is an ear
 * test, so it routes through us). This is the only per-agent operator screen in the
 * console and it already holds every other `agents:write` control — script, apply/undo,
 * call cap, A/B — behind one `useAdminAccess` gate. A second per-agent screen for one
 * dropdown would be a second place to look for the same class of setting.
 *
 * **CONFIGURED IS NOT LIVE, and this panel is built around that rather than around the
 * dropdown.** The write touches our row only; `publish_agent` re-reads the column, so a
 * live agent keeps its old voice until the next publish. `GET /v1/agents/{id}/pending`
 * therefore answers with TWO voices — `voice.configured` and `voice.live` — and both are
 * rendered as labelled data, side by side, exactly as `PendingRow` renders the two script
 * pointers on the client screen. The reasoning is the same and it has been earned twice:
 * a sentence can be read the wrong way round, two `dt`/`dd` pairs under "Callers hear
 * now" and "Configured" cannot. The panel used to say it could not report the voice in
 * force at all; the fix was not to start guessing but to make the server answer.
 *
 * **The select pre-selects `voice.configured`** and nothing else. Not `voice.live` (the
 * operator edits the configuration, not the past), not the catalogue's `is_default` (that
 * is D-36's written default, not this agent's state), and not a blank when the server
 * answered — a picker that reopens on "choose a voice" over a configured agent invites
 * the operator to re-pick a value that is already set.
 *
 * `verified: false` is rendered, not hidden: the catalogue entries carry it until the
 * Bolna pilot confirms each string is selectable on the engine (OPERATIONS §2 gate 3), and
 * an operator picking an unverified voice should know that is what they are doing.
 */
function VoicePanel({
  tenantId,
  agentId,
  slug,
  pending,
  tenantLoading,
  write,
}: {
  tenantId: string;
  agentId: string;
  slug: string;
  pending: PendingState | undefined;
  tenantLoading: boolean;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const catalogue = useTenantVoiceCatalogue(slug);
  const save = useSetAgentVoice({ tenantId, agentId, slug });
  // `null` means "not edited on this visit" — the select then shows the server's
  // configured voice. Same shape, and the same reason, as the call-cap field above: an
  // explicit "" is a real (invalid) choice and must not be confused with "unchanged".
  const [choice, setChoice] = useState<string | null>(null);
  const state = pending?.voice;
  const selected = choice ?? state?.configured?.voice_id ?? "";

  return (
    <Card title="Voice">
      <p className="-mt-2 text-xs text-ink-muted">
        Setting a voice writes it to the agent and stops there — a live agent keeps
        speaking in its old voice until the next publish, which is deliberate: re-voicing a
        running client&apos;s phone line is not something to do silently.
      </p>
      <div className="mt-3 space-y-3">
        <RestrictionNote reason={write.reason} />
        {save.error && <ProblemNotice error={save.error} />}

        {/* §52: the catalogue is a read like any other. A skeleton while it is in flight,
            a refusal when it failed — never an empty `<select>`, which reads as "this
            agent has no voices available" and is a claim about the product. The tenant
            and pending reads gate it too: the catalogue request goes through that
            tenant's impersonation session, and pre-selecting before the pending read
            lands would flash "choose a voice" over a configured agent. */}
        {tenantLoading || catalogue.isLoading ? (
          <Skeleton rows={2} />
        ) : catalogue.error || !catalogue.data ? (
          <ProblemNotice
            error={
              catalogue.error ??
              new Error("The voice catalogue did not load, so there is nothing to choose from.")
            }
            onRetry={() => void catalogue.refetch()}
          />
        ) : !catalogue.data.selectable ? (
          /* THE ENGINE SUPPLIES ITS OWN VOICES (D-93), which is a product fact and not a
             fault — so it is stated, in the server's own words, and NOT rendered through
             `ProblemNotice`. An error card here would send an operator to a runbook for
             a deployment that is working exactly as intended.

             The picker is not rendered at all rather than rendered-and-disabled: a
             disabled dropdown full of Bulbul entries still tells the reader those are the
             voices this agent might speak, and they are not. `voices` is empty from the
             server for the same reason. What IS still shown is `VoiceInForce`, because
             "what do callers hear right now" remains a fair question — the answer is just
             not ours to change here. */
          <>
            <VoiceInForce state={state} published={pending?.published} />
            <p className="text-xs text-ink-muted">{catalogue.data.note}</p>
          </>
        ) : (
          <>
            <VoiceInForce state={state} published={pending?.published} />

            <form
              className="flex flex-wrap items-end gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                save.mutate(selected);
              }}
            >
              <label className="flex flex-col gap-1">
                <span className="text-xs text-ink-muted">Voice</span>
                <select
                  value={selected}
                  disabled={!write.allowed}
                  onChange={(event) => setChoice(event.target.value)}
                  className={FIELD}
                >
                  <option value="">Choose a voice</option>
                  {catalogue.data.voices.map((voice) => (
                    <option key={voice.id} value={voice.id}>
                      {voiceReading(voice)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="submit"
                disabled={save.isPending || selected === "" || !write.allowed}
                className={PRIMARY_BUTTON_SM}
              >
                {save.isPending ? "Saving…" : "Set voice"}
              </button>
            </form>

            <VoiceDetail voice={catalogue.data.voices.find((entry) => entry.id === selected)} />
          </>
        )}

        {save.data && (
          <p className="text-xs text-ink-muted">
            Saved — {save.data.voice.label} ({save.data.voice.tier} tier,{" "}
            {save.data.voice.tts_model}). {save.data.next_step}
          </p>
        )}
      </div>
    </Card>
  );
}

/**
 * The two voices, named, with the gap between them stated where there is one.
 *
 * Modelled on `PendingRow` on the client agents screen, deliberately: that component
 * exists because showing the STAGED script as the one callers hear was shipped once and
 * `agents/publishing.py` opens by recording it. A voice has the same two-pointer shape
 * for the same reason — our row moves, the engine does not until a publish — so it gets
 * the same treatment: the server's headline, and both values as labelled data underneath
 * so no one has to parse a sentence correctly to know which is which.
 *
 * `published` decides how a null `live` reads, and it is genuinely two different facts:
 * an unpublished agent has nothing live, while a published one with nothing recorded is
 * an agent whose voice we cannot name. The second is not "no voice" and must not be
 * rendered as one — the server says `republish_required` for it either way.
 *
 * Nothing at all is rendered while the pending read is unavailable: the panel below still
 * SETS a voice, and a missing "in force" block is a smaller lie than an invented one.
 */
function VoiceInForce({
  state,
  published,
}: {
  state: AgentVoiceState | undefined;
  published: boolean | undefined;
}) {
  if (!state) return null;
  return (
    <div className="rounded-card border border-line p-3">
      <p className="text-xs text-ink">{state.headline}</p>
      <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            Callers hear now
          </dt>
          <dd className="text-sm font-medium text-ink">
            {state.live
              ? voiceName(state.live)
              : published
                ? "Not recorded — publish to be sure"
                : "Nothing — not on the voice platform yet"}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            Configured
          </dt>
          <dd className="text-sm font-medium text-ink">
            {state.configured ? voiceName(state.configured) : "None set"}
          </dd>
        </div>
      </dl>
      {state.republish_required && (
        /* Amber, and only when the server says so. The two values above are already
           different at this point, but "different" is not the operator's question —
           "does a caller hear the wrong thing until I act" is, and only the server can
           answer it (an unpublished agent has two different values and no problem). */
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
          Publishing this agent is what moves the voice callers hear. Nothing else on this
          screen does it.
        </p>
      )}
    </div>
  );
}

/** A stored voice in the words an operator recognises, degrading to the raw id.
 *
 *  `catalog` is null for a voice the API no longer offers, and the id is then all we
 *  have. Printing it beats printing "unknown": an operator can search for an id. */
function voiceName(voice: AgentVoice): string {
  return voice.catalog ? `${voice.catalog.label} (${voice.catalog.tts_model})` : voice.voice_id;
}

/**
 * What the operator is about to choose, before they choose it.
 *
 * The `<option>` text carries the tier and the model because that is what an operator
 * compares on; the rest — languages, the catalogue's own note, and whether the string has
 * been confirmed on the engine — needs more room than an option can hold. Nothing is
 * rendered when the select sits on "choose a voice", which now only happens on an agent
 * with no voice configured: the block above has already said so, and repeating it here
 * would be two answers to one question.
 */
function VoiceDetail({ voice }: { voice: Voice | undefined }) {
  if (!voice) return null;
  return (
    <div className="rounded-card border border-line p-3 text-xs text-ink-muted">
      <p>
        <span className="font-semibold text-ink">{voice.label}</span> · {voice.provider}{" "}
        {voice.tts_model} · {voice.tier} tier
        {voice.gender ? ` · ${voice.gender}` : ""} · {voice.languages.join(", ")}
      </p>
      <p className="mt-1">{voice.note}</p>
      {!voice.verified && (
        // Stated, not hidden: the catalogue marks an entry verified only once the pilot
        // has confirmed the engine accepts the string (OPERATIONS §2 gate 3). Setting an
        // unverified one is allowed and is a decision the operator should make knowingly.
        <p className="mt-1 text-amber-700 dark:text-amber-400">
          Not yet confirmed against the voice platform — we have not heard this one on a
          live call. Expect to verify it before a client hears it.
        </p>
      )}
    </div>
  );
}

/** One catalogue entry, in the words an operator picks on. */
function voiceReading(voice: Voice): string {
  const badge = voice.verified ? "" : " · unverified";
  return `${voice.label} — ${voice.tier} (${voice.tts_model})${badge}`;
}

/**
 * What the Conclude button reports, including the ending it did not perform.
 *
 * Concluding is idempotent on the server: a second operator on the same screen, or a
 * retry of a request whose response was lost, gets 200 and a test that ended exactly
 * once — nothing is promoted or published a second time. That call's response carries
 * the arm the test ENDED on and a null `new_version`, because no version was minted by
 * it, and printing "as vnull" at an operator is how a correct server answer becomes a
 * broken screen.
 *
 * The server states it outright as `changed`, and that is now what this reads. It used
 * to derive the same fact from `promoted_label != null && new_version == null` because
 * the generated client predated the field; the two agree by construction, but the
 * derivation was a second way of knowing one thing and this is the first.
 *
 * "This test" is exact rather than loose: the request names an `experiment_id`, so the
 * response is about the test that was on screen — never about whichever one happens to
 * be running now. That is what makes "reload" honest advice; before the id, the reply
 * could be describing a test the operator had not looked at.
 */
function concludeMessage(data: ConcludeExperimentOut): string {
  if (!data.promoted_label) {
    // True of an ending with no promotion whether or not this call made it: either way
    // the control is what callers keep hearing.
    return "Stopped. Callers keep hearing the control script.";
  }
  if (!data.changed) {
    return (
      `This test had already ended, promoting variant ${data.promoted_label}. ` +
      "Nothing was published again — reload to see the version it produced."
    );
  }
  return (
    `Promoted variant ${data.promoted_label} as v${data.new_version}.` +
    (data.applied
      ? data.engine_synced
        ? " The voice platform has it."
        : " The agent is not live, so nothing was sent to the voice platform."
      : " It is STAGED — press Apply above to put it on live calls.")
  );
}

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
function ExperimentPanel({
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
    <Card title="Script test (A/B)">
      <p className="-mt-2 text-xs text-ink-muted">
        Two published scripts against comparable outbound traffic. Which arm a call ran is
        recorded on the call, so the attribution never changes when the split does.
      </p>
      <div className="mt-3 space-y-3">
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
            <p className="text-xs text-ink-muted">
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
                <span className="text-xs text-ink-muted">
                  Promoting saves the winning script as a new version and applies it — the
                  same Apply the panel above uses.
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
              <p className="text-xs text-ink-muted">{concludeMessage(conclude.data)}</p>
            )}
          </>
        )}
      </div>
    </Card>
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
        <span className="text-sm font-medium text-ink">{experiment.name}</span>
        <span className="text-xs text-ink-muted">
          {experiment.status === "running" ? "running" : "concluded"} · scoring{" "}
          {experiment.conversion_metric_label} · started {formatIST(experiment.started_at)}
        </span>
        {experiment.winner_label && (
          <span className="rounded bg-brand-strong px-1.5 py-0.5 text-xs font-medium text-white">
            winner: {experiment.winner_label}
          </span>
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
        <p className="mt-0.5 text-xs">{experiment.caveat}</p>
        {experiment.coverage_note && (
          <p className="mt-0.5 text-xs opacity-80">{experiment.coverage_note}</p>
        )}
      </NoticeBox>

      <ScrollRegion label="Prompt experiment arms">
        <table className="w-full text-left text-xs">
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
                    <span className="ml-1.5 font-sans text-[11px] font-normal text-ink-muted">
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
        <p className="text-xs text-ink-muted">
          Gap between the arms: {pointsReading(experiment.difference_low)} to{" "}
          {pointsReading(experiment.difference_high)} (A minus B, 95% confidence).
        </p>
      ) : (
        /* Deliberately not a dash, not a zero and not an empty cell: the reason the
           comparison is absent is more useful than the space it would occupy. */
        <p className="text-xs text-ink-muted">
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
  const [control, setControl] = useState<string>("");
  const [challenger, setChallenger] = useState<string>("");
  const [metric, setMetric] = useState(rules.default_metric);

  // Two versions are the minimum a test can exist between, and saying so is more use
  // than a disabled control with no explanation.
  if (!versions || versions.length < 2) {
    return (
      <p className="text-xs text-ink-muted">
        A test needs two prompt versions. Write a challenger below, then start one.
      </p>
    );
  }

  const parsed = { control: Number(control), challenger: Number(challenger) };
  const ready =
    name.trim().length >= 3 &&
    Number.isFinite(parsed.control) &&
    Number.isFinite(parsed.challenger) &&
    parsed.control !== parsed.challenger &&
    control !== "" &&
    challenger !== "";

  return (
    <form
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
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
      }}
    >
      <input
        value={name}
        disabled={!write.allowed}
        onChange={(event) => setName(event.target.value)}
        maxLength={120}
        placeholder="What is being tested (e.g. 'direct booking greeting')"
        className={FIELD}
      />
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
          <span className="text-xs text-ink-muted">Counts as a conversion</span>
          <select
            value={metric}
            disabled={!write.allowed}
            onChange={(event) => setMetric(event.target.value)}
            className={FIELD}
          >
            {rules.metrics.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <button type="submit" disabled={pending || !ready || !write.allowed} className={PRIMARY_BUTTON_SM}>
        {pending ? "Starting…" : "Start test (50/50)"}
      </button>
      <p className="text-xs text-ink-muted">
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
      <span className="text-xs text-ink-muted">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={FIELD}
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

/** A rate with its plausible range, or the reason there is no rate. Never "0%" for an
 *  arm with no completed calls — that is a claim, and the server sent null.
 *
 *  The mixed-population qualifier is built INTO this string rather than rendered beside
 *  it, and that is the point: the rate's denominator is `completed`, which can hold
 *  inbound calls the engine credited to this arm (D-60) and which nothing ever SPLIT
 *  between the arms. A caller who renders the number therefore cannot omit the fact that
 *  part of it was not randomised — the alternative, a separate element somebody may
 *  forget or a layout may drop, is how the "dialled" defect this replaced got shipped.
 */
function rateReading(variant: ExperimentVariant): string {
  if (variant.rate === null || variant.rate_low === null || variant.rate_high === null) {
    return "no completed calls yet";
  }
  const pct = (value: number) => `${(value * 100).toFixed(1)}%`;
  const reading = `${pct(variant.rate)} (${pct(variant.rate_low)}–${pct(variant.rate_high)})`;
  if (variant.inbound_completed === 0) return reading;
  return (
    `${reading} · includes ${variant.inbound_completed} inbound call` +
    `${variant.inbound_completed === 1 ? "" : "s"} this arm's line answered, which were ` +
    `not split between the arms`
  );
}

/** Percentage POINTS, signed, because the gap can legitimately run either way. */
function pointsReading(value: number): string {
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)} pts`;
}

/** Seconds in the units an operator argues about caps in. Presentation only — the
 *  number sent to the API is always the seconds the field holds. */
function minutesReading(seconds: number): string {
  if (!Number.isFinite(seconds)) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes === 0) return `${rest}s`;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest}s`;
}
