"use client";

import { useRef, useState } from "react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import {
  CheckCircle2,
  CircleHelp,
  KeyRound,
  Lock,
  RefreshCw,
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
  KeyField,
  MonoValue,
  TestOutcome,
  TypeToConfirm,
  confirmMatches,
} from "@/app/admin/ops/opsLanguage";
import {
  useKekState,
  useRewrapKeks,
  useSecrets,
  useSetSecret,
  useTestSecret,
  type KekState,
  type PlatformSecret,
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
          The vendor keys this platform holds, shown only by their last four characters. You
          can install a key here and test it with the vendor, but this screen can never show
          you a stored key. If you need the value itself, get it from your vendor&apos;s
          dashboard — it is never kept anywhere you can read it back.
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

/**
 * A plain name for a credential, shown above its machine key.
 *
 * The key IS fairly self-describing (`bolna_api_key`), but a person reads "Bolna API key"
 * faster than the snake_case, and the machine key is always printed beneath it so nothing
 * is hidden. This only reshapes the key's own words — it makes no claim about the vendor —
 * so a new credential the console has never seen still gets a readable title.
 */
function credentialLabel(key: string): string {
  return key
    .split("_")
    .map((word) => {
      if (word === "api") return "API";
      if (word === "url") return "URL";
      if (word === "id") return "ID";
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(" ");
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
          {/* The plain vendor name first, then the machine key. `break-all` on the key:
              these are unbroken snake_case identifiers with no space for a browser to wrap
              at, so at 320px they painted 15px outside the card. */}
          <p className="text-sm font-semibold text-ink">{credentialLabel(secret.key)}</p>
          <p className="mt-0.5 break-all text-xs text-ink-faint">
            <MonoValue>{secret.key}</MonoValue>
          </p>
          {secret.installed ? (
            <p className="mt-1 text-sm text-ink">
              Ends <MonoValue className="font-semibold">…{secret.last_four}</MonoValue>{" "}
              <span className="text-ink-faint">
                (version <MonoValue>{secret.version}</MonoValue>
                {secret.versions > 1 && <> of {formatCount(secret.versions)}</>}) ·{" "}
                set by {secret.created_by ?? "unknown"} · {formatIST(secret.created_at)}
              </span>
            </p>
          ) : (
            // NOT an empty row: "nothing is installed" is a fact an operator acts on.
            <p className="mt-1 text-sm text-ink-muted">
              Not installed — this deployment has never stored one here.
            </p>
          )}
          {secret.shadowed_by_env && (
            // The escape hatch that would otherwise make a rotation on this screen silently
            // do nothing: the same key is set on the server itself, and that always wins.
            <p className="mt-1 flex items-start gap-1.5 text-xs text-amber-700">
              <TriangleAlert aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
              <span>
                This key is also set on the server itself (as{" "}
                <MonoValue>{secret.env_var}</MonoValue>), and the server&apos;s own setting
                always wins — so anything you store here does nothing until it is removed
                there. Rotating it on this screen would change nothing.
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
          Stored. <MonoValue>{stored.key}</MonoValue> now ends{" "}
          <MonoValue className="font-semibold">…{stored.last_four}</MonoValue> at version{" "}
          <MonoValue>{stored.version}</MonoValue>
          {stored.versions > 1 && <> of {formatCount(stored.versions)} kept</>}.
          {stored.shadowed_by_env && (
            <>
              {" "}
              <span className="font-semibold">
                It is not in force: the same key is set on the server itself (as{" "}
                {stored.env_var}), and the server&apos;s own setting wins.
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
  const ready = value.length > 0 && reason.trim().length >= 3 && confirmMatches(confirm, word);

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
      {save.error && (
        <WriteFailure
          error={save.error}
          actionLabel={secret.installed ? "Rotate" : "Install"}
        />
      )}
      {test.error && <ProblemNotice error={test.error} />}

      {/* THE TEST RESULT, before the key is stored. `TestOutcome` renders the four honest
          outcomes and keeps the "unconfirmed acceptance is not a green tick" guarantee:
          every probe in this build reports `verified: false`, so an accepted result shows
          as "looks right" (neutral) rather than a confirmed pass. Only a rejection means
          "find a different key". */}
      {test.data && (
        <TestOutcome
          outcome={test.data.outcome}
          verified={test.data.verified}
          lastFour={test.data.candidate_last_four}
        />
      )}

      <KeyField
        id={`secret-value-${secret.key}`}
        label={secret.installed ? "New key" : "Key"}
        value={value}
        onChange={(next) => {
          setValue(next);
          // THE RESULT DIES WITH ITS CANDIDATE. A result is about the exact string that
          // was sent; one keystroke later it is about a string nobody checked, and a stale
          // result box beside a changed value is this panel's version of the lie §52 is
          // named for.
          test.reset();
        }}
        placeholder="Paste the key from your vendor's dashboard"
        hint="This is stored securely and never shown again — only its last four characters. If you need it later, get it from your vendor's dashboard."
      />

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

      <TypeToConfirm
        id={`secret-confirm-${secret.key}`}
        word={word}
        value={confirm}
        onChange={setConfirm}
      />

      {/* THE CONTROL THAT PREVENTS THE OUTAGE, said where the decision is made. A wrong key
          stored here is silent until a call drops, so the test is the thing that catches it
          at the screen. It does NOT block installing — "we couldn't reach the vendor" and
          "we can't test this one" are real answers you must be able to store past — so the
          nudge is a sentence, not a disabled button. */}
      {value.length > 0 && !test.data && !test.isPending && (
        <p className="flex items-start gap-1.5 text-xs text-amber-700">
          <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          This key has not been checked with the vendor. Test it first — a wrong key stored
          here is not refused; it is discovered when a call drops.
        </p>
      )}
      {!secret.testable && (
        // Was a `title` on the button: invisible to a keyboard and to a screen reader,
        // which is where this panel's operators most need it.
        <p className="text-xs text-ink-muted">
          There is no automatic check for this vendor, so the test will say it wasn&apos;t
          checked rather than pass or fail. It is still safe to store — it just won&apos;t be
          verified until the platform first uses it.
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
        subject="This panel would show which master key is active and how many stored keys are still locked with an older one."
      />
    );
  }

  return (
    <Card title="Key management">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Each stored key is encrypted with its own key, and those keys are locked by this
          platform&apos;s master key — the one key that locks all the others. The master key
          lives on the server (as <MonoValue>PLATFORM_KEK</MonoValue>), never in the
          database. Re-locking updates every stored key to the current master key; your
          vendor keys are never unlocked or read to do it.
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
              out. In particular it does NOT know how many stored keys are still locked with
              a previous master key, so do not remove the previous master key (
              <MonoValue>PLATFORM_KEK_RETIRED</MonoValue>) from the server on the strength of
              this screen. The re-lock below is still available — it is the recovery step,
              and it reports its own counts.
            </p>
          </NoticeBox>
        )}

        {kek && (
          <>
            <dl className="grid gap-3 sm:grid-cols-3">
              <div>
                {/* A key ID (a short code identifying the key without revealing it), NOT a
                    counter (D-96). Shown as an ID, because "#1633907231" invites an operator
                    to read it as a version number and conclude a rotation went badly wrong. */}
                <dt className="text-xs uppercase tracking-wide text-ink-faint">
                  Active master key ID
                </dt>
                <dd className="mt-0.5 text-sm text-ink">
                  <MonoValue>{kek.active_kek_id}</MonoValue>
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-faint">
                  Locked with it
                </dt>
                <dd className="mt-0.5 text-sm text-ink">
                  {formatCount(kek.current)} of {formatCount(kek.versions)}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-faint">
                  Previous master key set
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
                title={`${formatCount(kek.pending)} stored keys are still locked with a previous master key`}
              >
                <p className="mt-1">
                  <span className="font-semibold">
                    Do not remove the previous master key (
                    <MonoValue>PLATFORM_KEK_RETIRED</MonoValue>) from the server yet.
                  </span>{" "}
                  These keys can only be unlocked with it, so removing it would make them
                  permanently unreadable. Run the re-lock below, then check this number
                  again.
                </p>
              </NoticeBox>
            ) : (
              <NoticeBox
                tone="ok"
                icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
                title="Every stored key is locked with the current master key"
              >
                <p className="mt-1">
                  A rotation is complete, so the previous master key (
                  <MonoValue>PLATFORM_KEK_RETIRED</MonoValue>) can be removed from the server
                  at the next deploy.
                </p>
              </NoticeBox>
            )}
          </>
        )}

        {rewrap.error && <WriteFailure error={rewrap.error} actionLabel="Re-lock every key" />}
        {rewrap.data && (
          <NoticeBox
            tone={rewrap.data.unreadable.length > 0 ? "stop" : "ok"}
            icon={<RefreshCw aria-hidden className="h-5 w-5" />}
            title={`${formatCount(rewrap.data.rewrapped)} of ${formatCount(rewrap.data.examined)} stored keys re-locked`}
          >
            {rewrap.data.unreadable.length > 0 ? (
              <>
                <p className="mt-1 font-semibold">
                  {formatCount(rewrap.data.unreadable.length)} could NOT be unlocked by any
                  master key the server has.
                </p>
                <p className="mt-1">
                  These will be lost if the previous master key is removed. They were locked
                  with a master key this server no longer has — find it and set it as the
                  previous master key (<MonoValue>PLATFORM_KEK_RETIRED</MonoValue>) before
                  doing anything else.
                </p>
                <ul className="mt-2 space-y-0.5 text-xs">
                  {rewrap.data.unreadable.map((entry) => (
                    <li key={entry}>
                      <MonoValue>{entry}</MonoValue>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="mt-1">
                Every stored key the server can unlock is now locked with the master key
                whose ID is <MonoValue>{rewrap.data.active_kek_id}</MonoValue>. No vendor key
                was unlocked to do it.
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
          {/* A custom confirm field rather than the shared TypeToConfirm, because this one
              must DISABLE while a re-lock is running or the session cannot run it — a state
              the shared control does not expose. The typed word (REWRAP) is unchanged: it
              is a local gate, and NOT the API's confirmation string (`rewrap_platform_keks`,
              in opsSecrets.ts). */}
          <label className="block">
            <span className={FIELD_LABEL}>
              Type <MonoValue>{REWRAP_WORD}</MonoValue> to confirm
            </span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed || rewrap.isPending}
              placeholder={REWRAP_WORD}
              className={`${FIELD} font-mono`}
            />
            <span className={FIELD_HINT}>
              Re-locks every stored key, including old versions. It never unlocks or reads a
              vendor key — it only changes which master key protects them.
            </span>
          </label>
          <button
            type="submit"
            title={access.reason ?? undefined}
            disabled={!access.allowed || confirm !== REWRAP_WORD || rewrap.isPending}
            className={DANGER_BUTTON}
          >
            <RefreshCw aria-hidden className="h-4 w-4" />
            {rewrap.isPending ? "Re-locking…" : "Re-lock every key"}
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
