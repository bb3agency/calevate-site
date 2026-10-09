"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { ActionButton } from "@/components/actionButton";
import { SuccessRipple } from "@/components/successRipple";
import {
  Card,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  useApplyChanges,
  usePublishAgent,
  useTenantEngineState,
  useUndoChanges,
  type EngineVerification,
  type PendingState,
} from "@/lib/api/publishing";

/*
 * THE LIVE SECTION — what callers hear, the two levers that change it, and the read-back
 * that proves it. It opens first because the read-back carries the truthful-answer and
 * disclosure verdicts (hard rule 5), and a compliance verdict is never behind a section
 * switch (UX-DOCTRINE §8.7).
 */

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
export function GoLivePanel({
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
   * in the Script section — and a second `ProblemNotice` quoting the same sentence
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
            This agent is on the voice platform. Script changes reach it through Apply to
            live calls.
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
              {/* The one first-publish CTA, now the shared ActionButton: it carries the
                  spinner while the mutation is in flight (`loading`) so this panel no longer
                  spells "Publishing…" itself, and it disables during the request the same way
                  the old button did (`disabled || loading`). The accessible name is the
                  children and does NOT change with `loading`, which is what keeps
                  `agentGoLive.test.tsx`'s `findByRole(button, /Publish to the voice
                  platform/)` — and a screen reader — pointing at the same control mid-press. */}
              <ActionButton
                type="button"
                loading={publish.isPending}
                disabled={!write.allowed || hasAScript === false}
                onClick={() => publish.mutate()}
              >
                Publish to the voice platform
              </ActionButton>
              <span className="text-xs text-ink-muted">
                {hasAScript === false
                  ? "This agent has no script yet — the client's business profile, or a version saved in Script, gives it one."
                  : "A test call and a re-check of the standard scripts are meant to happen before this. Neither is automated here yet, so this button only publishes the agent — it does not sign anything off."}
              </span>
            </div>
          </>
        )}

        {publish.data && (
          <div className="flex items-center gap-3">
            {/* Decorative — the sentence beside it is the announced confirmation, so the mark
                is `aria-hidden` to avoid saying "success" twice. Sized down from the
                component default for an inline panel confirmation. */}
            <SuccessRipple
              aria-hidden
              sizeClassName="h-10 w-10 shrink-0 sm:h-12 sm:w-12"
            />
            <p className="text-xs text-ink-muted">
              Published — the platform holds this agent as{" "}
              <span className="font-mono">{publish.data.engine_agent_ref}</span>.
            </p>
          </div>
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
export function PublishingPanel({
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
          <p className="text-[12px] font-medium text-ink-muted">
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
          Publishing is not available on this voice platform, so there is nothing to
          confirm.
        </p>
      )}

      {verification.publishable && !verification.confirmed && published && (
        /* Amber and unmissable, because the failure this covers looks like success from
           every other angle: the agent says `live`, the version list says the right
           number, and nobody has established that a caller hears any of it. */
        <p className="mt-2 text-xs text-warn">
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
                    : "text-xs font-medium text-warn"
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
        ? "text-warn"
        : "text-ink-muted";
  return (
    <div>
      <dt className="text-[12px] font-medium text-ink-muted">{label}</dt>
      <dd className={`text-sm font-medium ${tone}`}>{reading}</dd>
    </div>
  );
}
