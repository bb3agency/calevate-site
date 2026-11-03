"use client";

import { CheckCircle2, Lock, TriangleAlert } from "lucide-react";

import { MonoValue } from "@/app/admin/ops/opsLanguage";
import { NoticeBox, formatIST } from "@/components/ui";
import type { ConfigList } from "@/lib/api/opsConfig";

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
      <p className="text-meta text-ink-muted">
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
        title="This process has never read the configuration store"
      >
        <p className="mt-1">
          It runs on environment variables and code defaults; console changes are not in
          force here. Check the database is reachable.
        </p>
      </NoticeBox>
    );
  }
  if (config.stale) {
    return (
      <NoticeBox
        tone="warn"
        title="The last refresh of the configuration failed"
      >
        <p className="mt-1">
          Showing the last ones read successfully. A recent change may not be in force yet.
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
      title="We could not read the platform configuration"
    >
      <p className="mt-1">
        Nothing is shown rather than a guess. The settings in force are unaffected.
      </p>
    </NoticeBox>
  );
}

/**
 * The keys this console can NEVER change, with the reason (`GET /v1/ops/config`'s
 * `bootstrap` list). An operator looking for `APP_ENV` and finding nothing would read that
 * as "this build has no such setting".
 * No values, ever.
 */
export function EnvOnlyKeys({ keys }: { keys: ConfigList["bootstrap"] }) {
  if (keys.length === 0) return null;
  return (
    <section className="space-y-2">
      <div>
        <h3 className="text-body font-semibold text-ink">Set outside this console</h3>
        <p className="text-meta text-ink-muted">
          Real settings this deployment uses that can never be stored here. Each row says
          why, and where the value goes instead. Values are never shown.
        </p>
      </div>
      <ul className="divide-y divide-line border-y border-line">
        {keys.map((entry) => (
          <li key={entry.key} className="px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <Lock aria-hidden className="h-4 w-4 text-ink-muted" />
              <span className="text-body font-medium text-ink">{entry.label}</span>
              <MonoValue>{entry.env_var}</MonoValue>
              {entry.configured ? (
                <span className="inline-flex items-center gap-1 text-meta text-ink-muted">
                  <CheckCircle2 aria-hidden className="h-3.5 w-3.5" />
                  Set in this deployment&apos;s environment
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-meta text-warn">
                  <TriangleAlert aria-hidden className="h-3.5 w-3.5" />
                  Not set in this deployment&apos;s environment
                </span>
              )}
            </div>
            <p className="mt-1 text-meta text-ink-muted">Cannot be set here because {entry.reason}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

