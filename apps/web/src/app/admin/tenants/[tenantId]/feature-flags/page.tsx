"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Info, Wrench } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  TermGloss,
  formatIST,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { useTenant } from "@/lib/api/admin";
import {
  REASON_MAX,
  flagBlockReason,
  projectedState,
  useFeatureFlags,
  useSetFeatureFlag,
  type FeatureFlag,
  type FeatureFlagIn,
} from "@/lib/api/featureFlags";

import { useAdminAccess } from "@/app/admin/access";

/**
 * Per-tenant feature flags (SURFACES §1) — read them, and flip one.
 *
 * **What a flag is here, said on the screen rather than only in the code.** These are OUR
 * switches on OUR product behaviour for ONE client: a beta, a debug view. They are not
 * the platform switches (`/admin/ops`), not the client's plan, and — the one an operator
 * must never assume — they cannot turn a compliance control off. The panel at the top
 * says so, because the person most likely to look for such a switch is the person on a
 * support call being asked for one.
 *
 * **Resolution is stated, not implied.** Every row shows three separate facts: what the
 * platform does by default, what this client's stored override says (or that they have
 * none), and the resolved answer. A client pinned to the value the default happens to
 * have today is NOT the same as a client with no row — the next change to the default
 * reaches one and not the other — so the screen shows both rather than collapsing them
 * into one green tick.
 *
 * **`consumed_by` is on screen.** A flag can be declared before the code that reads it
 * exists; that is how a flag lands ahead of its feature. But an operator flipping a
 * switch that nothing reads, believing they enabled something for a client on the phone,
 * is the failure this field prevents — so a flag with no consumer says "nothing reads
 * this yet" beside its own control, in the amber tone the console uses for "true but
 * not what you were hoping".
 *
 * **§52.** Loading is a skeleton. A failed read is a REFUSAL and the forms are withheld
 * with it — not disabled, not empty: this write replaces whatever is on file, and
 * deciding while the current state is unreadable can silently reverse a colleague's
 * change. There is no default state anywhere on this screen, and no `?? false`.
 *
 * **The permission is answered before the click.** `admin:tenants` is what the route
 * requires; `useAdminAccess` reads the admin realm's own identity, so a session that may
 * not write sees a disabled control with its reason rather than a 403 that reads like a
 * fault. The READ is `org:read`, which both admin roles hold — see `apps/api/flags/
 * routes.py` on why a GET must not carry a mutating permission (D-22).
 */
export default function FeatureFlagsPage({
  params,
}: {
  // Next 15: `params` is a Promise in every page, unwrapped with React's `use()` in a
  // client component — nextjs.org/docs/app/api-reference/file-conventions/dynamic-routes.
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const flags = useFeatureFlags(tenantId);
  // The mutation lives HERE rather than inside each row, for the reason the KYC and
  // first-campaign screens state: a successful write invalidates the list, the row is
  // remounted by its key to pick up the new state, and a mutation held inside it would be
  // remounted with it — taking the confirmation down at the moment the write landed.
  const set = useSetFeatureFlag(tenantId);
  const write = useAdminAccess("admin:tenants", "change a client's feature flags");

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
        <h1 className="mt-1 text-xl font-semibold text-ink">Feature flags</h1>
        <p className="text-sm text-ink-muted">
          Beta features and debug views, switched on for this client alone. Each flag
          starts at a platform default set in code; an override here moves this client off
          it and takes effect on their next request.
        </p>
      </div>

      <NoticeBox tone="neutral" icon={<Info className="h-5 w-5" />} title="What these are not">
        <ul className="mt-1 space-y-1 text-xs opacity-90">
          <li>
            Not the platform switches. Halting outbound calling, the load-shed mode and our
            own telemarketer registration are global and live on{" "}
            <Link href="/admin/ops" className="font-medium underline">
              the operations screen
            </Link>
            .
          </li>
          <li>
            Not what this client pays for. Plan, included minutes and spend ceilings are a
            dated commercial agreement, on Commercials.
          </li>
          <li>
            <span className="font-medium">Never a compliance control.</span> Nothing here
            can switch off the{" "}
            <TermGloss term="DNC">do-not-call list</TermGloss>, calling hours, the
            disclosure line, the campaign review or{" "}
            <TermGloss term="KYC">Know Your Customer — the business identity check</TermGloss>{" "}
            for a client. If someone asks for that, the answer is no and the reason is that
            those checks are the law, not a preference.
          </li>
        </ul>
      </NoticeBox>

      {flags.error && <ProblemNotice error={flags.error} onRetry={() => flags.refetch()} />}

      {flags.isLoading ? (
        <Skeleton rows={4} />
      ) : !flags.data ? (
        /* The controls are WITHHELD rather than merely disabled, and the reason belongs
           on screen. A write here replaces whatever is on file, so acting while the
           current state is unreadable can silently reverse a colleague's change — and on
           a flag, unlike a compliance decision, nothing downstream would refuse it. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot change a flag while the current state is unreadable"
        >
          <p className="mt-1 text-xs opacity-90">
            We could not read where this client stands. A change replaces whatever is on
            file, so making one now could undo a colleague&apos;s without anyone seeing it
            happen. Retry the read above; the controls come back with it.
          </p>
        </NoticeBox>
      ) : flags.data.items.length === 0 ? (
        <EmptyState
          title="This build has no feature flags"
          hint="No feature flags are defined yet, so there is nothing to configure here."
        />
      ) : (
        <div className="space-y-4">
          {flags.data.items.map((flag) => (
            <FlagRow
              // Remounted only when the STORED position changes — an equal refetch keeps
              // the key, so a poll or a sibling write cannot wipe a reason an operator is
              // halfway through typing. Resetting state via `key` rather than an effect is
              // React's own answer (react.dev/learn/you-might-not-need-an-effect).
              key={`${flag.flag}|${flag.override}|${flag.reason}`}
              flag={flag}
              tenantName={tenant.name}
              set={set}
              write={write}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** The three facts behind one answer, plus the control that moves it. */
function FlagRow({
  flag,
  tenantName,
  set,
  write,
}: {
  flag: FeatureFlag;
  tenantName: string;
  set: ReturnType<typeof useSetFeatureFlag>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  // `null` here is the OVERRIDE's absence, not "unknown" — the three-way choice the API
  // takes. It starts at whatever is on file, so the form opens describing the truth.
  const [position, setPosition] = useState<boolean | null>(flag.override);
  const [reason, setReason] = useState("");

  const draft: FeatureFlagIn = { enabled: position, reason };
  const blocked = flagBlockReason(draft, flag);
  const projected = projectedState(draft, flag);
  const result = set.data?.flag === flag.flag ? set.data : null;

  return (
    <Card title={flag.flag}>
      <p className="-mt-2 text-sm text-ink-muted">
        {flag.description ??
          "This build no longer declares this flag, so nothing describes it and nothing reads it."}
      </p>

      {!flag.declared && (
        <NoticeBox
          tone="neutral"
          icon={<Wrench className="h-5 w-5" />}
          title="Left over from an older release"
          className="mt-3"
        >
          <p className="mt-1 text-xs opacity-90">
            This row is stored but no code reads it, so it changes nothing. Clearing it is
            safe and is how these are tidied up.
          </p>
        </NoticeBox>
      )}

      {flag.declared && flag.consumed_by === null && (
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Nothing reads this flag yet"
          className="mt-3"
        >
          <p className="mt-1 text-xs opacity-90">
            The switch is real and the setting is stored, but no code consults it in this
            build — so turning it on changes nothing a client would notice. It is declared
            ahead of the feature it will gate.
          </p>
        </NoticeBox>
      )}

      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-ink-faint">Platform default</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {flag.platform_default === null
              ? "— (not declared)"
              : flag.platform_default
                ? "On"
                : "Off"}
          </dd>
        </div>
        <div>
          <dt className="text-ink-faint">This client&apos;s override</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {flag.override === null ? "None — follows the default" : flag.override ? "On" : "Off"}
          </dd>
        </div>
        <div>
          <dt className="text-ink-faint">In effect</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {flag.enabled ? "On" : "Off"}
            <span className="ml-1 font-normal text-ink-muted">
              ({flag.source === "tenant_override" ? "from the override" : "from the default"})
            </span>
          </dd>
        </div>
        {flag.override !== null && (
          <>
            <div className="sm:col-span-2">
              <dt className="text-ink-faint">Why</dt>
              <dd className="mt-0.5 whitespace-pre-wrap font-medium text-ink">
                {flag.reason ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-ink-faint">Set</dt>
              <dd className="mt-0.5 font-medium text-ink">
                {flag.set_at ? `${formatIST(flag.set_at)} IST` : "—"}
              </dd>
            </div>
          </>
        )}
      </dl>

      <form
        className="mt-5 space-y-4 border-t border-line pt-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (blocked === null) set.mutate({ flag: flag.flag, ...draft });
        }}
      >
        {/* The permission the route requires, answered before the click. */}
        <RestrictionNote reason={write.reason} />

        <fieldset>
          <legend className={FIELD_LABEL}>This client&apos;s position</legend>
          <div className="mt-2 space-y-2">
            {POSITIONS.map((option) => (
              <label
                key={String(option.value)}
                className="flex cursor-pointer gap-2 rounded-card border border-line p-3 text-xs hover:bg-black/5 dark:hover:bg-white/5"
              >
                <input
                  type="radio"
                  name={`${flag.flag}-position`}
                  checked={position === option.value}
                  disabled={!write.allowed}
                  onChange={() => {
                    setPosition(option.value);
                    set.reset();
                  }}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium text-ink">{option.label}</span>
                  <span className="mt-0.5 block text-ink-muted">{option.effect}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div>
          {/* A persistent visible label, not a placeholder: the hint below explains the
              field, the label names it, and neither disappears when typing starts. */}
          <label htmlFor={`${flag.flag}-reason`} className={FIELD_LABEL}>
            Why (recorded)
          </label>
          <textarea
            id={`${flag.flag}-reason`}
            rows={2}
            maxLength={REASON_MAX}
            value={reason}
            disabled={!write.allowed}
            onChange={(event) => {
              setReason(event.target.value);
              set.reset();
            }}
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            Goes into the audit entry, and into the row for as long as the override stands.
            Required in both directions — &ldquo;why did we put them back on the
            default&rdquo; is asked just as often. Keep it to notes about the change only:
            no phone numbers and no transcript text.
          </span>
        </div>

        <div className="rounded-card border border-line bg-app p-3 text-xs text-ink-muted">
          <p className="font-medium text-ink">This will record, against {tenantName}:</p>
          <ul className="mt-1.5 space-y-1">
            <li>
              <span className="text-ink-faint">In effect afterwards</span> —{" "}
              {projected.enabled === null
                ? "nothing; this flag is not declared by this build."
                : `${projected.enabled ? "on" : "off"}, ${
                    projected.source === "tenant_override"
                      ? "from this client's own override."
                      : "from the platform default, because the override is being cleared."
                  }`}
            </li>
            <li>
              <span className="text-ink-faint">When</span> — on this client&apos;s next
              request. There is no cache to wait out.
            </li>
            <li>
              <span className="text-ink-faint">Audit</span> — one entry, and only if
              something actually changes. Restating what is already on file writes nothing.
            </li>
            <li>
              <span className="text-ink-faint">Set by</span> — the admin account sending
              this request. Taken from your session, not from this form.
            </li>
          </ul>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Shared primary CTA: the "Save this flag" label stays mounted (no name
              flicker to "Saving…"), the spinner rides `loading`, and the two non-pending
              disable reasons are unchanged — ActionButton folds `loading` in on top. */}
          <ActionButton
            type="submit"
            loading={set.isPending}
            disabled={blocked !== null || !write.allowed}
          >
            Save this flag
          </ActionButton>
          {blocked && <span className="text-xs text-amber-700 dark:text-amber-400">{blocked}</span>}
        </div>
      </form>

      {set.error != null && <ProblemNotice error={set.error} />}
      {result && (
        <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />} className="mt-4">
          <p className="text-xs">
            {result.changed ? (
              <>
                Changed from <span className="font-medium">{result.before.enabled ? "on" : "off"}</span>{" "}
                to <span className="font-medium">{result.after.enabled ? "on" : "off"}</span>, and
                audited. It applies from this client&apos;s next request.
              </>
            ) : (
              <>
                Nothing changed — that is already what was on file, so no row moved and no
                audit entry was written.
              </>
            )}
          </p>
        </NoticeBox>
      )}
    </Card>
  );
}

/**
 * The three positions, in the operator's words.
 *
 * "Follow the platform default" is a genuinely different choice from "off", not a tidier
 * spelling of it: it deletes the override, so the next change to the default reaches this
 * client. Presenting only on/off would make that choice unreachable from the console and
 * would leave a client silently pinned to a value nobody meant to pin them to.
 */
const POSITIONS: { value: boolean | null; label: string; effect: string }[] = [
  {
    value: true,
    label: "On for this client",
    effect: "An explicit override. Stays on even if the platform default changes.",
  },
  {
    value: false,
    label: "Off for this client",
    effect: "An explicit override. Stays off even if the platform default changes.",
  },
  {
    value: null,
    label: "Follow the platform default",
    effect: "Clears the override, so a future change to the default reaches this client.",
  },
];
