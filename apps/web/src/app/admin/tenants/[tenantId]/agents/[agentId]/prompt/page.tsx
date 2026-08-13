"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft } from "lucide-react";

import {
  Card,
  EmptyState,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
  PRIMARY_BUTTON_SM,
  SECONDARY_BUTTON_SM,
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
  usePublishingRefresh,
  useSetCallCap,
  useTenantLanes,
  useTenantPending,
  useUndoChanges,
  type PendingState,
} from "@/lib/api/publishing";

import { useAdminAccess } from "../../../../access";

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
  // different moment as `/v1/me` resolved.
  const write = useAdminAccess(slug, "agents:write", "change this agent's script");

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
  "w-full rounded-md border border-line bg-surface px-2 py-1.5 text-xs text-ink placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-50";



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
      </div>
    </Card>
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
            {lanes.data
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

/** Seconds in the units an operator argues about caps in. Presentation only — the
 *  number sent to the API is always the seconds the field holds. */
function minutesReading(seconds: number): string {
  if (!Number.isFinite(seconds)) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes === 0) return `${rest}s`;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest}s`;
}
