"use client";

import { useState } from "react";
import {
  CheckCircle2,
  CircleAlert,
  CircleHelp,
  KeyRound,
  Lock,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import {
  Card,
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  useKekState,
  useRewrapKeks,
  useSecrets,
  useSetSecret,
  useTestSecret,
  type KekState,
  type PlatformSecret,
  type ProbeOutcome,
  type SecretsList,
} from "@/lib/api/opsSecrets";

/**
 * Credentials (§8 panel 3) and key management (§8 panel 4).
 *
 * ## What this screen can and cannot do, and why the asymmetry is the security model
 *
 * It can INSTALL a credential and it can TEST one. It can never READ one. §7: "There is
 * no read-back route and there will not be one" — a console that can display a
 * credential leaks every credential through one screenshot or one compromised session.
 * So every row here shows a key name, four characters, a version and a date, and the
 * form is write-only. That is not a UI limitation to work around; it is the property
 * that makes §10's accepted trade acceptable.
 *
 * §10 states the trade plainly and this screen is where it lands: today, stealing every
 * vendor credential requires VPS access; after this, one compromised admin session is
 * enough to REPLACE them. It cannot exfiltrate them, every write is audited into the
 * hash-chained ledger, and every write fires an alert.
 *
 * ## Test before set, and the three ways a test can fail to be a yes
 *
 * `POST /test` sends the candidate to the vendor and stores nothing, so a wrong key is
 * refused at the screen rather than at the next call. The outcomes are deliberately not
 * collapsed: `rejected` is the vendor saying no, `unreachable` is the vendor having a
 * bad day, and `no_probe` is this build having no way to ask. Only the first is a
 * reason to go and find a different key, and rendering the other two as failures would
 * send an operator to rotate a credential that was fine.
 *
 * A green result also states its own limits: it proves the credential authenticates for
 * one read, not that it has every scope this platform uses.
 *
 * ## §52, on a screen where an invented value is worse than usual
 *
 * Loading is a skeleton, failure is a refusal. A credential list rendered from a failed
 * read would show every key as "not installed", which reads as "this platform has no
 * Sarvam key" — an operator would then install one over a working credential.
 */

type SecretsState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; list: SecretsList };

export function secretsState(query: {
  data: SecretsList | undefined;
  error: unknown;
  isLoading: boolean;
}): SecretsState {
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  return { status: "read", list: query.data };
}

export function SecretsPanel({
  access,
}: {
  access: { allowed: boolean; reason: string | null };
}) {
  const query = useSecrets();
  const state = secretsState(query);

  return (
    <Card title="Vendor credentials">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Installed keys, by their last four characters. This console can install and test
          a credential; it can never show you one. If you need the value, you already have
          it — you are the person who set it.
        </p>

        {query.error && <ProblemNotice error={query.error} onRetry={() => query.refetch()} />}
        {state.status === "loading" && <Skeleton rows={3} />}

        {state.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We could not read which credentials are installed"
          >
            <p className="mt-1">
              This panel will not tell you a key is missing when it could not find out —
              installing one over a working credential is the mistake that would cause.
              The error above says what stopped the read.
            </p>
          </NoticeBox>
        )}

        {state.status === "read" && (
          <ul className="space-y-2">
            {state.list.secrets.map((secret) => (
              <li key={secret.key}>
                <SecretRow secret={secret} access={access} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

const OUTCOME_TONE: Record<ProbeOutcome, "ok" | "warn" | "stop" | "neutral"> = {
  accepted: "ok",
  rejected: "stop",
  unreachable: "warn",
  no_probe: "neutral",
};

const OUTCOME_TITLE: Record<ProbeOutcome, string> = {
  accepted: "The vendor accepted this credential",
  rejected: "The vendor REFUSED this credential",
  unreachable: "We could not reach the vendor",
  no_probe: "This build cannot test this credential",
};

function SecretRow({
  secret,
  access,
}: {
  secret: PlatformSecret;
  access: { allowed: boolean; reason: string | null };
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const test = useTestSecret();
  const save = useSetSecret();

  const word = secret.key.toUpperCase();
  const ready = value.length > 0 && reason.trim().length >= 3 && confirm === word;

  return (
    <div className="rounded-card border border-line bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-sm text-ink">{secret.key}</p>
          {secret.installed ? (
            <p className="mt-0.5 text-sm text-ink">
              <span className="font-mono font-semibold">…{secret.last_four}</span>{" "}
              <span className="text-ink-faint">
                v{secret.version}
                {secret.versions > 1 && ` of ${formatCount(secret.versions)}`} ·{" "}
                {secret.created_by ?? "unknown"} · {formatIST(secret.created_at)}
              </span>
            </p>
          ) : (
            // NOT an empty row: "nothing is installed" is a fact an operator acts on.
            <p className="mt-0.5 text-sm text-ink-muted">
              Not installed — this deployment has never stored one here.
            </p>
          )}
          {secret.shadowed_by_env && (
            // The §4 escape hatch, and the one thing that would otherwise make a
            // rotation on this screen silently do nothing.
            <p className="mt-1 flex items-start gap-1.5 text-xs text-amber-700">
              <TriangleAlert aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
              <span>
                <span className="font-mono">{secret.env_var}</span> is also set in this
                deployment&apos;s environment, and the environment always wins — so
                anything stored here is INERT until that variable is removed. Rotating it
                on this screen would change nothing.
              </span>
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setOpen((was) => !was)}
          disabled={!access.allowed}
          title={access.reason ?? undefined}
          className={SECONDARY_BUTTON_SM}
        >
          <KeyRound aria-hidden className="h-3.5 w-3.5" />
          {open ? "Cancel" : secret.installed ? "Rotate" : "Install"}
        </button>
      </div>

      {open && (
        <form
          className="mt-3 space-y-3 border-t border-line pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(
              { key: secret.key, value, reason: reason.trim() },
              {
                onSuccess: () => {
                  setValue("");
                  setReason("");
                  setConfirm("");
                  setOpen(false);
                },
              },
            );
          }}
        >
          {save.error && <ProblemNotice error={save.error} />}
          {test.error && <ProblemNotice error={test.error} />}

          {/* THE VERDICT, before the value is stored. Rendered as itself rather than as
              a pass/fail: only `rejected` means "find a different key". */}
          {test.data && (
            <NoticeBox
              tone={OUTCOME_TONE[test.data.outcome]}
              icon={
                test.data.outcome === "accepted" ? (
                  <ShieldCheck aria-hidden className="h-5 w-5" />
                ) : test.data.outcome === "rejected" ? (
                  <ShieldAlert aria-hidden className="h-5 w-5" />
                ) : (
                  <CircleAlert aria-hidden className="h-5 w-5" />
                )
              }
              title={OUTCOME_TITLE[test.data.outcome]}
            >
              <p className="mt-1">{test.data.detail}</p>
              <p className="mt-2 text-xs">
                Tested <span className="font-mono">…{test.data.candidate_last_four}</span>
                {test.data.status !== null && ` · vendor answered ${test.data.status}`}
              </p>
              {/* OPERATIONS §2: an unverified vendor behaviour is a MARKED assumption,
                  never a silent premise. The operator sees which this is. */}
              {!test.data.verified && test.data.outcome !== "no_probe" && (
                <p className="mt-2 text-xs">
                  This check has not been confirmed against the live vendor from this
                  build, so treat it as indicative rather than authoritative.
                </p>
              )}
            </NoticeBox>
          )}

          <label className="block">
            <span className={FIELD_LABEL}>
              {secret.installed ? "New value" : "Value"}
            </span>
            <input
              type="password"
              autoComplete="off"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className={`${FIELD} font-mono`}
            />
            <span className={FIELD_HINT}>
              Stored encrypted. It is never shown again — only its last four characters.
            </span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Reason</span>
            <input
              required
              minLength={3}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. 'rotating after the vendor's breach notice'"
              className={FIELD}
            />
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>
              Type <span className="font-mono">{word}</span> to confirm
            </span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder={word}
              className={`${FIELD} font-mono`}
            />
          </label>

          <div className="flex flex-wrap gap-2">
            {/* TEST FIRST, and it needs no typed confirmation: it stores nothing, and a
                confirmation on a check only teaches operators to type past them. */}
            <button
              type="button"
              disabled={value.length === 0 || test.isPending}
              onClick={() => test.mutate({ key: secret.key, value })}
              title={
                secret.testable
                  ? undefined
                  : "This build has no probe for this vendor — the test will say so"
              }
              className={SECONDARY_BUTTON_SM}
            >
              <ShieldCheck aria-hidden className="h-3.5 w-3.5" />
              {test.isPending ? "Testing…" : "Test with the vendor"}
            </button>
            <button type="submit" disabled={!ready || save.isPending} className={PRIMARY_BUTTON_SM}>
              <KeyRound aria-hidden className="h-3.5 w-3.5" />
              {save.isPending ? "Storing…" : secret.installed ? "Rotate" : "Install"}
            </button>
          </div>

          <p className="text-xs text-ink-faint">
            Recorded in the audit log against your admin account, and an alert is sent —
            an installed credential is what an attacker with an admin session would
            replace, so every one of these is watched.
          </p>
        </form>
      )}
    </div>
  );
}

/**
 * Key management (§8 panel 4): which KEK is live, how many DEKs are wrapped under it,
 * and the rewrap action.
 *
 * THE NUMBER THAT MATTERS IS `pending`. While it is above zero, some stored credential
 * is still wrapped under a key other than the current one, and removing
 * `PLATFORM_KEK_RETIRED` from the environment would make those rows permanently
 * unreadable. So the panel says that in those words rather than showing a progress bar:
 * the operator's next action (clean up the environment, or run the rewrap again) depends
 * entirely on this one count.
 */
export function KeyManagementPanel({
  access,
}: {
  access: { allowed: boolean; reason: string | null };
}) {
  const query = useKekState();
  const rewrap = useRewrapKeks();
  const [confirm, setConfirm] = useState("");
  const kek: KekState | null = query.error ? null : (query.data ?? null);

  return (
    <Card title="Key management">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Every stored credential is encrypted with its own key, and those keys are
          wrapped with this deployment&apos;s <span className="font-mono">PLATFORM_KEK</span>
          , which lives in the environment and never in the database. Rotating it re-wraps
          the keys — the credentials themselves are never decrypted.
        </p>

        {query.error && <ProblemNotice error={query.error} onRetry={() => query.refetch()} />}
        {query.isLoading && <Skeleton rows={2} />}

        {kek && (
          <>
            <dl className="grid gap-3 sm:grid-cols-3">
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-faint">Active key</dt>
                <dd className="mt-0.5 font-mono text-sm text-ink">#{kek.active_kek_id}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-faint">
                  Wrapped under it
                </dt>
                <dd className="mt-0.5 text-sm text-ink">
                  {formatCount(kek.current)} of {formatCount(kek.versions)}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-faint">
                  Retired key configured
                </dt>
                <dd className="mt-0.5 text-sm text-ink">
                  {kek.has_retired_kek ? "yes" : "no"}
                </dd>
              </div>
            </dl>

            {kek.pending > 0 ? (
              <NoticeBox
                tone="warn"
                icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
                title={`${formatCount(kek.pending)} stored versions are still wrapped under another key`}
              >
                <p className="mt-1">
                  <span className="font-semibold">
                    Do not remove PLATFORM_KEK_RETIRED from the environment yet.
                  </span>{" "}
                  Those versions can only be opened with it, so removing it would make
                  them permanently unreadable. Run the rewrap below, then check this
                  number again.
                </p>
              </NoticeBox>
            ) : (
              <NoticeBox
                tone="ok"
                icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
                title="Every stored key is wrapped under the current KEK"
              >
                <p className="mt-1">
                  A rotation is complete, so{" "}
                  <span className="font-mono">PLATFORM_KEK_RETIRED</span> can be removed
                  from the environment at the next deploy.
                </p>
              </NoticeBox>
            )}
          </>
        )}

        {rewrap.error && <ProblemNotice error={rewrap.error} />}
        {rewrap.data && (
          <NoticeBox
            tone={rewrap.data.unreadable.length > 0 ? "stop" : "ok"}
            icon={<RefreshCw aria-hidden className="h-5 w-5" />}
            title={`${formatCount(rewrap.data.rewrapped)} of ${formatCount(rewrap.data.examined)} versions re-wrapped`}
          >
            {rewrap.data.unreadable.length > 0 ? (
              <>
                <p className="mt-1 font-semibold">
                  {formatCount(rewrap.data.unreadable.length)} could NOT be opened by any
                  configured key.
                </p>
                <p className="mt-1">
                  These will be lost if the retired key is removed. They were written
                  under a key this deployment no longer has — find it and set it as{" "}
                  <span className="font-mono">PLATFORM_KEK_RETIRED</span> before doing
                  anything else.
                </p>
                <ul className="mt-2 space-y-0.5 font-mono text-xs">
                  {rewrap.data.unreadable.map((entry) => (
                    <li key={entry}>{entry}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="mt-1">
                Every version this deployment can open is now wrapped under key #
                {rewrap.data.active_kek_id}. No credential was decrypted to do it.
              </p>
            )}
          </NoticeBox>
        )}

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            rewrap.mutate(undefined, { onSuccess: () => setConfirm("") });
          }}
        >
          <label className="block">
            <span className={FIELD_LABEL}>
              Type <span className="font-mono">REWRAP</span> to confirm
            </span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed}
              placeholder="REWRAP"
              className={`${FIELD} font-mono`}
            />
            <span className={FIELD_HINT}>
              Re-wraps every stored version, including historical ones. It reads no
              credential and changes no value — only which key protects them.
            </span>
          </label>
          <button
            type="submit"
            title={access.reason ?? undefined}
            disabled={!access.allowed || confirm !== "REWRAP" || rewrap.isPending}
            className={DANGER_BUTTON}
          >
            <RefreshCw aria-hidden className="h-4 w-4" />
            {rewrap.isPending ? "Re-wrapping…" : "Re-wrap every key"}
          </button>
          {!access.allowed && access.reason && (
            <p className="flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {access.reason}
            </p>
          )}
        </form>
      </div>
    </Card>
  );
}
