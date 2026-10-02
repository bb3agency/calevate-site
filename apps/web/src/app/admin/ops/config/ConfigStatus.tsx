"use client";

import { CheckCircle2, CircleHelp, Lock, ShieldCheck, TriangleAlert } from "lucide-react";

import { MonoValue, TestOutcome } from "@/app/admin/ops/opsLanguage";
import { NoticeBox, ProblemNotice, SECONDARY_BUTTON_SM, formatIST } from "@/components/ui";
import type { ConfigList } from "@/lib/api/opsConfig";
import { useProbeCarrier } from "@/lib/api/opsSecrets";

import { settingLabel } from "./configField";

/** The env-only row the carrier check sits beside: the second half of the Vobiz pair, so
 *  the button appears once, under both halves, rather than once per half. */
const CARRIER_PROBE_ROW = "vobiz_auth_token";

/**
 * The facts that qualify EVERY section of the configuration screen, so they sit above the
 * section menu rather than inside one section: whether this process can still reach the
 * store, and which configuration version it is serving.
 */
export function ConfigStatus({ config }: { config: ConfigList }) {
  return (
    <div className="space-y-3">
      <StoreHealth config={config} />
      {/* Read from the sentinel, not from any row's `updated_at`: a revert deletes the row
          and takes that timestamp with it. */}
      <p className="text-xs text-ink-faint">
        Configuration version <MonoValue>{config.config_version}</MonoValue>
        {config.config_changed_at
          ? `, last changed ${formatIST(config.config_changed_at)}.`
          : ", never changed on this deployment."}
      </p>
    </div>
  );
}

/**
 * Whether the process that answered can still reach the store. Rendered only when the
 * answer is NOT "yes" — a green box on every load trains people to stop reading it.
 */
function StoreHealth({ config }: { config: ConfigList }) {
  if (config.never_loaded) {
    return (
      <NoticeBox
        tone="stop"
        icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
        title="This process has never read the configuration store"
      >
        <p className="mt-1">
          It is running on environment variables and code defaults. Values below are what
          it is using, but nothing set from this console is in force here, and a change
          you make now may not appear. Check that the database is reachable before
          treating this screen as the platform&apos;s configuration.
        </p>
      </NoticeBox>
    );
  }
  if (config.stale) {
    return (
      <NoticeBox
        tone="warn"
        icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
        title="The last refresh of the configuration failed"
      >
        <p className="mt-1">
          The values below are the last ones read successfully, so they are real rather
          than invented — but a change made recently may not have reached this process. It
          keeps serving them deliberately: a configuration lookup must never be able to
          take the phone system down.
        </p>
      </NoticeBox>
    );
  }
  return null;
}

/** The refusal for a read that failed: no field list, because a list of defaults is a lie. */
export function ConfigUnreadable() {
  return (
    <NoticeBox
      tone="warn"
      icon={<CircleHelp aria-hidden className="h-5 w-5" />}
      title="We could not read the platform configuration"
    >
      <p className="mt-1">
        This screen will not show you values it did not receive. The error above says what
        stopped the read — nothing here has changed, and the settings currently in force are
        unaffected by this screen failing to load.
      </p>
    </NoticeBox>
  );
}

/**
 * The keys this console can NEVER change, with the reason (`GET /v1/ops/config`'s
 * `bootstrap` list). An operator looking for `APP_ENV` and finding nothing would read that
 * as "this build has no such setting".
 *
 * A key with `held_by` renders WHERE the value lives and no verdict: `PLIVO_AUTH_ID` belongs
 * in the voice worker's secret set, and a red "not set here" badge would be "fixed" by
 * putting a live carrier credential on a host with no reader for it. No values, ever.
 */
export function EnvOnlyKeys({ keys }: { keys: ConfigList["bootstrap"] }) {
  if (keys.length === 0) return null;
  return (
    <section className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold text-ink">Set outside this console</h3>
        <p className="text-xs text-ink-faint">
          Real settings this deployment uses that can never be stored here. Each row says
          why, and where the value goes instead. Values are never shown.
        </p>
      </div>
      <ul className="divide-y divide-line rounded-card border border-line">
        {keys.map((entry) => (
          <li key={entry.key} className="px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <Lock aria-hidden className="h-4 w-4 text-ink-faint" />
              <span className="text-sm font-medium text-ink">{settingLabel(entry.key)}</span>
              <MonoValue>{entry.env_var}</MonoValue>
              {entry.held_by ? (
                <span className="text-xs text-ink-muted">
                  Held by {entry.held_by} — not by this deployment.
                </span>
              ) : entry.configured ? (
                <span className="inline-flex items-center gap-1 text-xs text-ink-muted">
                  <CheckCircle2 aria-hidden className="h-3.5 w-3.5" />
                  Set in this deployment&apos;s environment
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-xs text-warn">
                  <TriangleAlert aria-hidden className="h-3.5 w-3.5" />
                  Not set in this deployment&apos;s environment
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-ink-muted">Cannot be set here because {entry.reason}</p>
            {entry.key === CARRIER_PROBE_ROW && <CarrierProbe />}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Asks the carrier whether the pair this deployment's processes hold authenticates.
 * `POST /v1/ops/carrier/probe` takes no value — the pair is env-only, so there is nothing
 * to paste — and stores nothing, so it needs no typed confirmation. The server's own
 * sentence is shown beside the verdict because "not checked" has two causes (no pair set,
 * or the carrier unreachable) and only the detail says which.
 */
function CarrierProbe() {
  const probe = useProbeCarrier();
  return (
    <div className="mt-2 space-y-2">
      {probe.error && <ProblemNotice error={probe.error} />}
      {probe.data && (
        <div className="space-y-1">
          <TestOutcome outcome={probe.data.outcome} verified={probe.data.verified} />
          <p className="text-xs text-ink-muted">
            Asked <MonoValue>{probe.data.carrier}</MonoValue>: {probe.data.detail}
          </p>
        </div>
      )}
      <button
        type="button"
        disabled={probe.isPending}
        onClick={() => probe.mutate()}
        className={SECONDARY_BUTTON_SM}
      >
        <ShieldCheck aria-hidden className="h-3.5 w-3.5" />
        {probe.isPending ? "Testing…" : "Test the carrier credentials"}
      </button>
    </div>
  );
}
