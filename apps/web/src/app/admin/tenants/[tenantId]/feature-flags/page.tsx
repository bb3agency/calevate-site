"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
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
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { useAdminAccess } from "@/app/admin/access";
import { Term } from "@/lib/glossary";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { StatePill } from "../statePill";

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

  /*
   * THE FLAG TABLE, DECLARED TO THE SCREEN ASSISTANT.
   *
   * One tenant, named by the route, so the same scoping argument the client-detail screen
   * makes applies unchanged. Nothing here is personal: a flag is a machine name, a boolean
   * and a provenance.
   *
   * THE RESOLVED ANSWER IS SENT WITH ITS PROVENANCE, never on its own. The screen's whole
   * reason for existing (see the nav comment on `/admin/tenants/{id}`) is that a row
   * showing only "on" reads as a switch nobody set, and an assistant told "on" would
   * repeat the same half-fact back. So each flag goes as
   * `<resolved> (platform default <x>, override <y>)`.
   *
   * NO FIELDS. Every write here is a switch plus a REASON that goes into the audit log
   * under the operator's name, and the screen deliberately shows the projected state
   * before the click; a fill would be the assistant flipping a client's behaviour with a
   * justification it wrote for itself. The `reason` box is left out for the same reason
   * the DNC one is — free text, and free text about a client is where a name lands.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/feature-flags",
    title: "Feature flags",
    realm: "admin",
    fields: [],
    facts: [
      { key: "tenant_id", label: "Tenant id", value: tenantId },
      { key: "client", label: "Client", value: tenant?.name ?? "not read yet" },
      {
        key: "may_write",
        label: "May this operator change a flag",
        value: write.allowed ? "yes" : "no",
      },
      ...(flags.data
        ? flags.data.items.map((item) => ({
            key: `flag_${item.flag}`,
            label: `Flag ${item.flag}${item.declared ? "" : " (not declared in code)"}`,
            value: `${item.enabled ? "on" : "off"} — platform default ${
              item.platform_default === null ? "unset" : item.platform_default ? "on" : "off"
            }, this client's override ${
              item.override === null ? "none" : item.override ? "on" : "off"
            }`,
          }))
        : [
            {
              key: "flags",
              label: "The flag table",
              value: flags.error ? "could not be read" : "still loading",
            },
          ]),
    ],
    apply: noFill,
  });

  // The layout resolves the tenant before this page mounts; a render without it (a test
  // that mounts the page alone) paints nothing rather than a guess.
  if (!tenant) return null;

  return (
    <div className="max-w-3xl space-y-5">
      <PageHeader
        title="Feature flags"
        description="Betas and debug views, for this client only. A change applies on their next request."
      />

      {/* VISIBLE AND VERBATIM: the person most likely to look for such a switch is the
          person on a support call being asked for one. The two other "what these are not"
          notes are explanation, so they sit behind the ⓘ. */}
      <NoticeBox tone="neutral" icon={<Info className="h-5 w-5" />}>
        <div className="flex items-start gap-1 text-xs">
          <p>
            <span className="font-medium">Never a compliance control.</span> Nothing here
            can switch off the{" "}
            <Term id="dnc" audience="operator" />, calling hours, the
            disclosure line, the campaign review or{" "}
            <Term id="kyc" audience="operator" />{" "}
            for a client. If someone asks for that, the answer is no and the reason is that
            those checks are the law, not a preference.
          </p>
          <InfoTip label="What these flags are not">
            <p>
              Not the platform switches. Halting outbound calling, the load-shed mode and our
              own <Term id="tm" term="telemarketer" audience="operator" /> registration are
              global and live on{" "}
              <Link href="/admin/ops" className="font-medium underline">
                the operations screen
              </Link>
              .
            </p>
            <p>
              Not what this client pays for. Plan, included minutes and spend ceilings are a
              dated commercial agreement, on Commercials.
            </p>
          </InfoTip>
        </div>
      </NoticeBox>

      {flags.error && <ProblemNotice error={flags.error} onRetry={() => flags.refetch()} />}

      {flags.isLoading ? (
        <Skeleton rows={4} />
      ) : !flags.data ? (
        /* The controls are WITHHELD rather than merely disabled: a write here replaces
           whatever is on file, so acting while the current state is unreadable can
           silently reverse a colleague's change — and nothing downstream would refuse it. */
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
        <EmptyState message="This build has no feature flags, so there is nothing to configure here." />
      ) : (
        <ul className="divide-y divide-line rounded-card border border-line bg-surface">
          {flags.data.items.map((flag) => (
            <FlagRow
              // Remounted only when the STORED position changes — an equal refetch keeps
              // the key, so a poll or a sibling write cannot wipe a reason an operator is
              // halfway through typing (react.dev/learn/you-might-not-need-an-effect).
              key={`${flag.flag}|${flag.override}|${flag.reason}`}
              flag={flag}
              tenantName={tenant.name}
              set={set}
              write={write}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * One flag: what it does, the three facts behind its answer, and the control that moves
 * it. The reason and Save sit on the row because every write here — in either direction —
 * is audited with the operator's reason; the projection is one line and the audit detail
 * is behind an ⓘ.
 */
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
  const dirty = position !== flag.override || reason !== "";
  useUnsavedGuard(dirty);
  const reasonId = `${flag.flag}-reason`;

  return (
    <li className="space-y-3 px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-64">
          <h3 className="flex flex-wrap items-center gap-2">
            <MonoValue className="text-[14px] font-semibold text-ink">{flag.flag}</MonoValue>
            {!flag.declared && <StatePill>Left over from an older release</StatePill>}
            {flag.declared && flag.consumed_by === null && (
              <StatePill tone="warn">Nothing reads this flag yet</StatePill>
            )}
          </h3>
          <p className="mt-1 text-sm text-ink-muted">
            {flag.description ??
              "This build no longer declares this flag, so nothing describes it and nothing reads it."}
          </p>
          {!flag.declared && (
            <p className="mt-1 text-xs text-ink-muted">
              This row is stored but no code reads it, so it changes nothing. Clearing it is
              safe and is how these are tidied up.
            </p>
          )}
          {flag.declared && flag.consumed_by === null && (
            <p className="mt-1 text-xs text-warn">
              The switch is real and the setting is stored, but no code consults it in this
              build — so turning it on changes nothing a client would notice.
            </p>
          )}
        </div>
      </div>

      <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
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
          <div className="sm:col-span-3">
            <dt className="text-ink-faint">Why</dt>
            <dd className="mt-0.5 whitespace-pre-wrap text-ink">
              {flag.reason ?? "—"}
              {flag.set_at && (
                <span className="ml-1 text-ink-muted">· set {formatIST(flag.set_at)} IST</span>
              )}
            </dd>
          </div>
        )}
      </dl>

      <form
        className="space-y-3"
        // No rule the browser can refuse here (only `maxLength`), and every refusal is
        // already written in our words beside the control.
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (blocked === null) set.mutate({ flag: flag.flag, ...draft });
        }}
      >
        <RestrictionNote reason={write.reason} />

        <fieldset>
          <legend className="sr-only">This client&apos;s position</legend>
          <div className="grid gap-1 rounded-lg border border-line bg-app p-1 sm:inline-grid sm:grid-cols-3">
            {POSITIONS.map((option) => {
              const on = position === option.value;
              return (
                <label
                  key={String(option.value)}
                  title={option.effect}
                  className={`press flex cursor-pointer items-center justify-center gap-2 rounded-md px-3 py-1.5 text-[13px] font-medium touch:min-h-11 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand ${
                    on ? "bg-surface text-ink shadow-card" : "text-ink-muted hover:text-ink"
                  } ${!write.allowed ? "cursor-not-allowed opacity-60" : ""}`}
                >
                  <input
                    type="radio"
                    name={`${flag.flag}-position`}
                    checked={on}
                    disabled={!write.allowed}
                    onChange={() => {
                      setPosition(option.value);
                      set.reset();
                    }}
                    className="sr-only"
                  />
                  {option.label}
                </label>
              );
            })}
          </div>
          <p className="mt-1.5 text-xs text-ink-muted">
            {POSITIONS.find((option) => option.value === position)?.effect}
          </p>
        </fieldset>

        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1 basis-64">
            <label htmlFor={reasonId} className={FIELD_LABEL}>
              Why (recorded)
            </label>
            <input
              id={reasonId}
              maxLength={REASON_MAX}
              value={reason}
              disabled={!write.allowed}
              onChange={(event) => {
                setReason(event.target.value);
                set.reset();
              }}
              placeholder="e.g. Beta trial, ticket 4471"
              className={FIELD}
            />
          </div>
          {/* Shared primary CTA: the "Save this flag" name stays mounted (no flicker to
              "Saving…"), and the spinner rides `loading`. */}
          <ActionButton
            type="submit"
            loading={set.isPending}
            disabled={blocked !== null || !write.allowed}
          >
            Save this flag
          </ActionButton>
        </div>
        <div className={`${FIELD_HINT} flex items-start gap-1`}>
          <span>
            Required in both directions. No phone numbers and no transcript text.
            {dirty && projected.enabled !== null && (
              <>
                {" "}
                Afterwards: <span className="font-medium text-ink">{projected.enabled ? "on" : "off"}</span>,{" "}
                {projected.source === "tenant_override"
                  ? "from this client's own override."
                  : "from the platform default."}
              </>
            )}
          </span>
          <InfoTip label="What saving records">
            <p>Recorded against {tenantName}, from your session rather than this form.</p>
            <p>It applies on this client&apos;s next request; there is no cache to wait out.</p>
            <p>
              One audit entry, and only if something actually changes. Restating what is
              already on file writes nothing.
            </p>
          </InfoTip>
        </div>
        {blocked && <p className="text-xs text-warn">{blocked}</p>}
      </form>

      {set.error != null && result === null && set.variables?.flag === flag.flag && (
        <ProblemNotice error={set.error} />
      )}
      {result && (
        <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
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
    </li>
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
