"use client";

import { useRef, useState } from "react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { lookup } from "@/lib/lookup";
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
  type NoticeTone,
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
  type SecretTest,
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
 *
 * ## What the hardening pass changed
 *
 * 1. **A verdict belongs to ONE candidate, and dies with it.** The test mutation used to
 *    live on the ROW, so its green box outlived the value it was about: type key A, test
 *    it, accept, then edit the box to key B — the tick stayed on screen, above a
 *    different credential, and Install stored B. Worse, closing the form and reopening it
 *    left the same tick over an EMPTY box. The mutations now live in the form, which
 *    unmounts, and any edit to the candidate clears the verdict outright.
 * 2. **An unverified probe is not a tick.** Every probe in this build reports
 *    `verified=false` (apps/api/ops/secret_probes.PROBES), so the green `ShieldCheck` an
 *    operator saw was rendering an UNCONFIRMED result as a confirmed one, with the
 *    caveat in 11px at the bottom of the box. Only a verified acceptance gets the green
 *    tick now; the rest say what they are in the title.
 * 3. **The install says what the SERVER stored**, from the returned `SecretOut` — the
 *    last four characters and the version it landed at. Before, a successful install
 *    closed the form and produced nothing at all, so an operator's only evidence was a
 *    list refetch that looks identical whether their key or the previous one is in it.
 * 4. **The rewrap cannot double-fire**, and the plaintext does not outlive the form —
 *    see `CREDENTIAL_MUTATION_GC_MS` in `lib/api/opsSecrets.ts`.
 */

type SecretsState =
  | { status: "loading" }
  | { status: "unreadable" }
  /** The server ANSWERED, and the answer was "not you". See `withheld.tsx`. */
  | { status: "forbidden"; said: string | null }
  | { status: "read"; list: SecretsList };

export function secretsState(query: {
  data: SecretsList | undefined;
  error: unknown;
  isLoading: boolean;
}): SecretsState {
  // BEFORE `unreadable`, because a 403 is not a failure to read — it is a read that
  // succeeded in refusing. The two need opposite sentences: "we could not find out"
  // invites a retry (and `ProblemNotice` offers one), while this refusal is settled and
  // pressing the button again can only produce it a second time. The window where an
  // operator meets this at all is narrow — `/admin/ops` withholds the panel outright once
  // `/v1/admin/me` has answered — and it is exactly the window where the identity read is
  // slow or dead, i.e. when the console is least able to explain itself.
  if (isForbidden(query.error)) {
    return { status: "forbidden", said: forbiddenReason(query.error) };
  }
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

  if (state.status === "forbidden") {
    return (
      <WithheldPanel
        title="Vendor credentials"
        reason={state.said ?? "The API refused this read: your admin account may not see installed credentials."}
        subject="This panel would list the key names this deployment holds and the last four characters of each."
      />
    );
  }

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

const OUTCOME_TONE: Record<ProbeOutcome, NoticeTone> = {
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

/**
 * What the caveat is called when it reaches the title, rather than the footnote.
 *
 * OPERATIONS §2 and PLATFORM-CONFIG's own probe module: `verified` is false for every
 * probe this build has, because the STATUS a given vendor returns for a bad credential
 * has not been observed against the live vendor from this build. That does not weaken
 * the probe — accepted and rejected are still different answers — but it does change
 * what the screen may claim, and a green tick claims confirmation.
 */
const UNCONFIRMED_SUFFIX = " — indicative, not confirmed";

/**
 * `no_probe` is excluded on purpose: its title already says the check did not happen, and
 * appending "not confirmed" to "this build cannot test this credential" would be the
 * caveat arguing with itself.
 */
export function verdictTitle(test: SecretTest): string {
  const base =
    lookup(OUTCOME_TITLE, test.outcome) ??
    "The check returned an outcome this build has no words for";
  return test.verified || test.outcome === "no_probe" ? base : base + UNCONFIRMED_SUFFIX;
}

/** Green is reserved for a confirmed acceptance. An unconfirmed one is not a failure
 *  either, so it renders neutral rather than borrowing the refusal's red. */
export function verdictTone(test: SecretTest): NoticeTone {
  const base = lookup(OUTCOME_TONE, test.outcome) ?? "neutral";
  return base === "ok" && !test.verified ? "neutral" : base;
}

function SecretRow({
  secret,
  access,
}: {
  secret: PlatformSecret;
  access: { allowed: boolean; reason: string | null };
}) {
  const [open, setOpen] = useState(false);
  // The SERVER's row for what was just stored. Held here rather than in the form, which
  // unmounts — deliberately, because unmounting is what drops the plaintext.
  const [stored, setStored] = useState<PlatformSecret | null>(null);

  return (
    <div className="rounded-card border border-line bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          {/* `break-all`, like the value line below: these keys are unbroken snake_case
              identifiers (`self_serve_inr_per_min`, `object_store_bucket`) with no space
              for a browser to wrap at, so at 320px they painted 15px outside the card. */}
          <p className="break-all font-mono text-sm text-ink">{secret.key}</p>
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
          onClick={() => {
            // A receipt for the previous install must not sit above the next one.
            setStored(null);
            setOpen((was) => !was);
          }}
          disabled={!access.allowed}
          title={access.reason ?? undefined}
          className={SECONDARY_BUTTON_SM}
        >
          <KeyRound aria-hidden className="h-3.5 w-3.5" />
          {open ? "Cancel" : secret.installed ? "Rotate" : "Install"}
        </button>
      </div>

      {open && (
        <SecretForm
          secret={secret}
          onStored={(row) => {
            setStored(row);
            setOpen(false);
          }}
        />
      )}

      {!open && stored && <StoredReceipt stored={stored} />}
    </div>
  );
}

/**
 * What the SERVER stored, after it stored it.
 *
 * The four characters here come from the response, not from the candidate in the box —
 * which is the point: they are the server's proof it holds the value the operator meant,
 * and the only fragment anyone may ever see again. Before this existed, a successful
 * install closed the form and said nothing, so "did that work?" was answered by a list
 * that looks the same whether the new key or the old one is in it.
 */
function StoredReceipt({ stored }: { stored: PlatformSecret }) {
  return (
    <div className="mt-3 border-t border-line pt-3">
      <p role="status" className="flex items-start gap-2 text-sm text-ink">
        <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
        <span>
          Stored. <span className="font-mono">{stored.key}</span> now ends{" "}
          <span className="font-mono font-semibold">…{stored.last_four}</span> at version{" "}
          <span className="font-mono">{stored.version}</span>
          {stored.versions > 1 && <> of {formatCount(stored.versions)} kept</>}.
          {stored.shadowed_by_env && (
            <>
              {" "}
              <span className="font-semibold">
                It is not in force: {stored.env_var} is set in this deployment&apos;s
                environment and the environment wins.
              </span>
            </>
          )}
        </span>
      </p>
    </div>
  );
}

/**
 * The write-only credential form.
 *
 * ITS OWN COMPONENT, and that is a property rather than tidiness: the test and set
 * mutations live here, so closing the form unmounts them — which is what drops both the
 * verdict (it belonged to a candidate that no longer exists) and TanStack's reference to
 * the plaintext in `variables` (see `CREDENTIAL_MUTATION_GC_MS`). Held on the row, as
 * they were, a green "the vendor accepted this credential" survived Cancel and reappeared
 * above an empty box the next time the form was opened.
 */
function SecretForm({
  secret,
  onStored,
}: {
  secret: PlatformSecret;
  onStored: (row: PlatformSecret) => void;
}) {
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const test = useTestSecret();
  const save = useSetSecret();

  const word = secret.key.toUpperCase();
  const ready = value.length > 0 && reason.trim().length >= 3 && confirm === word;

  return (
    <form
      className="mt-3 space-y-3 border-t border-line pt-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready || save.isPending) return;
        save.mutate(
          { key: secret.key, value, reason: reason.trim() },
          {
            onSuccess: (row) => {
              // Cleared before the unmount rather than relying on it: this is the one
              // string on the screen worth being explicit about.
              setValue("");
              setReason("");
              setConfirm("");
              onStored(row);
            },
          },
        );
      }}
    >
      {save.error && <WriteFailure error={save.error} />}
      {test.error && <ProblemNotice error={test.error} />}

      {/* THE VERDICT, before the value is stored. Rendered as itself rather than as
          a pass/fail: only `rejected` means "find a different key". */}
      {test.data && (
        <NoticeBox
          tone={verdictTone(test.data)}
          icon={
            // The tick is spent only on a CONFIRMED acceptance. Every probe in this build
            // reports `verified: false`, so this branch is the live one today — and a
            // green shield over an unconfirmed result is the screen claiming more than
            // the server said.
            test.data.outcome === "accepted" && test.data.verified ? (
              <ShieldCheck aria-hidden className="h-5 w-5" />
            ) : test.data.outcome === "rejected" ? (
              <ShieldAlert aria-hidden className="h-5 w-5" />
            ) : (
              <CircleAlert aria-hidden className="h-5 w-5" />
            )
          }
          title={verdictTitle(test.data)}
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
              This check has not been confirmed against the live vendor from this build, so
              treat it as indicative rather than authoritative.
            </p>
          )}
        </NoticeBox>
      )}

      <label className="block">
        <span className={FIELD_LABEL}>{secret.installed ? "New value" : "Value"}</span>
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            // THE VERDICT DIES WITH ITS CANDIDATE. A result is about the exact string that
            // was sent; one keystroke later it is about a string nobody checked, and a
            // stale green box beside a changed value is this panel's version of the lie
            // §52 is named for.
            test.reset();
          }}
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

      {/* THE CONTROL THAT PREVENTS THE OUTAGE, said where the decision is made. §7 calls
          `/test` "the feature that makes this safe to use": a wrong key stored here is
          silent until a call drops. It does NOT block the install — `no_probe` and
          `unreachable` are real answers an operator must be able to store past — so the
          pressure is a sentence rather than a disabled button. */}
      {value.length > 0 && !test.data && !test.isPending && (
        <p className="flex items-start gap-1.5 text-xs text-amber-700">
          <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          This value has not been checked with the vendor. Test it first — a wrong
          credential stored here is not refused, it is discovered when a call drops.
        </p>
      )}
      {!secret.testable && (
        // Was a `title` on the button: invisible to a keyboard and to a screen reader,
        // which is where this panel's operators most need it.
        <p className="text-xs text-ink-muted">
          This build has no probe for this vendor, so the test will answer
          &ldquo;not checked&rdquo; rather than a verdict. Storing it is still safe — it
          simply will not be verified until the first real use.
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {/* TEST FIRST, and it needs no typed confirmation: it stores nothing, and a
            confirmation on a check only teaches operators to type past them. */}
        <button
          type="button"
          disabled={value.length === 0 || test.isPending}
          onClick={() => test.mutate({ key: secret.key, value })}
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
        Recorded in the audit log against your admin account, and an alert is sent — an
        installed credential is what an attacker with an admin session would replace, so
        every one of these is watched.
      </p>
    </form>
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
/**
 * The word an operator types to arm the rewrap.
 *
 * A constant rather than two string literals, because it was two: the input's placeholder
 * and the button's `disabled` compared against separate copies of `"REWRAP"`, and the
 * form's submit handler compared against neither. One name, one place to change.
 *
 * It is NOT `REWRAP_CONFIRMATION` — that is the `X-Confirm-Action` string the API checks
 * (`rewrap_platform_keks`), and conflating the word a person types with the header a
 * request carries is how a UI change quietly becomes an API change.
 */
const REWRAP_WORD = "REWRAP";

export function KeyManagementPanel({
  access,
}: {
  access: { allowed: boolean; reason: string | null };
}) {
  const query = useKekState();
  const rewrap = useRewrapKeks();
  const [confirm, setConfirm] = useState("");
  /** One rewrap in flight at a time — see the submit handler for why state cannot do it. */
  const firing = useRef(false);
  const kek: KekState | null = query.error ? null : (query.data ?? null);

  // `/v1/ops/secrets/kek` carries `platform:secrets` like every other route on that
  // router, so the refusal reaches this panel through the same door as the credential
  // list — and here the generic notice would be actively wrong, because it says the
  // rewrap "is still offered ... it is the recovery action". Offering a recovery action
  // to a session the API will refuse is precisely the 403-shaped control this pass
  // removes.
  if (isForbidden(query.error)) {
    return (
      <WithheldPanel
        title="Key management"
        reason={
          forbiddenReason(query.error) ??
          "The API refused this read: your admin account may not see key-management state."
        }
        subject="This panel would show which key-encryption key is active and how many stored versions are still wrapped under an older one."
      />
    );
  }

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

        {/* THE REFUSAL. Without it a failed read left the two verdict boxes absent and the
            rewrap form sitting there alone, which reads as "nothing to report" — and the
            fact that went missing is `pending`, the one number that decides whether
            removing PLATFORM_KEK_RETIRED destroys data. */}
        {query.error !== null && !query.isLoading && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We could not read the key-management state"
          >
            <p className="mt-1">
              This panel will not tell you a rotation is complete when it could not find
              out. In particular it does NOT know how many stored versions are still
              wrapped under an older key, so do not remove{" "}
              <span className="font-mono">PLATFORM_KEK_RETIRED</span> from the environment
              on the strength of this screen. The rewrap below is still offered — it is the
              recovery action, and it reports its own counts.
            </p>
          </NoticeBox>
        )}

        {kek && (
          <>
            <dl className="grid gap-3 sm:grid-cols-3">
              <div>
                {/* A FINGERPRINT, not a counter (D-96). Rendered as one, because
                    "#1633907231" invites an operator to read it as a generation number
                    and conclude a rotation went badly wrong. */}
                <dt className="text-xs uppercase tracking-wide text-ink-faint">
                  Active key fingerprint
                </dt>
                <dd className="mt-0.5 font-mono text-sm text-ink">{kek.active_kek_id}</dd>
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

        {rewrap.error && <WriteFailure error={rewrap.error} />}
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
                Every version this deployment can open is now wrapped under the key with
                fingerprint{" "}
                <span className="font-mono">{rewrap.data.active_kek_id}</span>. No
                credential was decrypted to do it.
              </p>
            )}
          </NoticeBox>
        )}

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            // THE DOUBLE-FIRE GUARD, and it is a REF rather than either the button's
            // `disabled` or the typed word. Enter inside the text input submits the form,
            // and neither of those closes the window between two fast submits: `isPending`
            // flips a microtask after `mutate`, and `setConfirm("")` does not change the
            // `confirm` this closure already captured — both handlers run against the
            // render that armed the first one. The first draft of this guard did exactly
            // that and fired twice; a ref is the only value that mutates in time.
            if (firing.current || !access.allowed || confirm !== REWRAP_WORD || rewrap.isPending)
              return;
            firing.current = true;
            setConfirm("");
            rewrap.mutate(undefined, {
              // Released on success AND on failure: a rewrap that 500s must be runnable
              // again, and a latch that only opened on success would need a page reload.
              onSettled: () => {
                firing.current = false;
              },
            });
          }}
        >
          <label className="block">
            <span className={FIELD_LABEL}>
              Type <span className="font-mono">{REWRAP_WORD}</span> to confirm
            </span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed || rewrap.isPending}
              placeholder={REWRAP_WORD}
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
            disabled={!access.allowed || confirm !== REWRAP_WORD || rewrap.isPending}
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
