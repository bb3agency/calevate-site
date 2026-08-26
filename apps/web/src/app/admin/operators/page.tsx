"use client";

import { useState, type ReactNode } from "react";
import {
  CircleHelp,
  KeyRound,
  Lock,
  MailCheck,
  ShieldCheck,
  TriangleAlert,
  UserCog,
  UserMinus,
  UserPlus,
} from "lucide-react";

import {
  adminAccess,
  identityAnswerPending,
  useAdminMe,
} from "@/app/admin/access";
import {
  WithheldPanel,
  forbiddenReason,
  isForbidden,
} from "@/app/admin/withheld";
import { WriteFailure } from "@/app/admin/writeFailure";
import {
  Card,
  DANGER_BUTTON,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  TypedConfirmation,
  confirmationMatches,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  ADMIN_ROLES,
  ROLE_COPY,
  operatorConfirmPhrase,
  operatorLabel,
  selfAdministrationBlock,
  tierChangeTarget,
  useAddOperator,
  useOperators,
  useResendOperatorSetupLink,
  useRevokeOperator,
  useSetOperatorRole,
  type AdminRole,
  type Operator,
} from "@/lib/api/adminOperators";
import { lookup } from "@/lib/lookup";

/**
 * Admin accounts — who may sign in to this console, and in which tier.
 *
 * Until this screen existed the answer was `scripts/bootstrap_admin.py` and nothing else:
 * `authn/bootstrap.py` refuses to run once anybody has a password, and its refusal ends
 * "add further operators from the admin console, where an existing operator vouches for
 * the new one and the change is audited" — a console that did not have the screen. This
 * is that screen.
 *
 * ## The one property that makes the two tiers real
 *
 * Every route behind it is `admin:operators`, which ONLY `superadmin` holds
 * (`core/rbac.py`). A normal admin cannot reach the table that decides who is a normal
 * admin, so there is no request they can send that widens their own authority — and the
 * READ carries the same permission as the writes, which is why a refused session is
 * shown a withheld panel here rather than a list with dead buttons. A disabled control
 * over a list nobody may read is a panel whose every request is a 403 (see
 * `admin/withheld.tsx`, and the identical pass on the ops config and credential panels).
 *
 * ## What is consequential here, and what stands in front of it
 *
 * Four acts, all four audited into the hash-chained ledger and all four step-up confirmed
 * by the API. This screen adds the two halves a curl cannot have: a sentence saying what
 * the act does before it is clicked, and a typed confirmation that is the API's OWN
 * header string, shown in a `<code>` beside the field. That is the console's existing
 * idiom for its most consequential writes (`admin/tenants/[id]/lifecycle` types
 * `erase_tenant_data:<id>`; the credits screen types the amount twice), and the binding
 * is what stops muscle memory: the string names the ROLE when an account is created and
 * the SUBJECT when one is promoted, demoted, revoked or re-invited, so a phrase typed for
 * Asha cannot lift Ravi and a phrase typed to add a colleague cannot add a second holder
 * of every platform secret. `useSetOperatorRole` and friends carry the same strings; a
 * disagreement is a `step_up_required` refusal, which `WriteFailure` renders as the
 * version skew it is.
 *
 * ## The lockout the founder asked about
 *
 * A super admin cannot demote or revoke THEMSELVES, and the API refuses it
 * (`operator_self_administration`) rather than trusting the screen. That refusal is what
 * holds the "there is always at least one live super admin" invariant up — see
 * `selfAdministrationBlock`, which is where the reasoning lives and why this screen does
 * not re-derive a count of its own. The row for the signed-in account therefore carries
 * the sentence where its controls would be, so the person who owns the platform meets an
 * explanation rather than a 403 on the one request that would have ended their own
 * access.
 *
 * ## §52, on a list whose empty state is a security claim
 *
 * "Nobody else has an admin account" printed over a failed read is the same defect class
 * as the team screen's, one realm up: it invites a founder to add an administrator they
 * already have, and it answers "who can reach every client's data" with a reassurance
 * nobody checked. Loading is a skeleton, a failure is the refusal and nothing else, and
 * the empty state is reachable only through a list the server actually sent.
 */
export default function OperatorsPage() {
  /**
   * ONE identity read for the whole screen, resolved here and passed down.
   *
   * Not a second `useAdminMe()` inside the body, and the reason is measured rather than
   * stylistic: mounting a second observer on a query in the ERROR state triggers
   * `retryOnMount`, and `identityAnswerPending` is exactly the predicate that decides
   * whether the body is mounted — so the two together used to be an unbounded loop of
   * `/v1/admin/me` requests (~45 in 300ms) on the one screen an operator opens when
   * authentication is already misbehaving. The predicate is sticky now, which closes it;
   * one observer keeps it closed for the next reader too.
   */
  const me = useAdminMe();
  const access = adminAccess(
    me,
    "admin:operators",
    "manage who may use this console",
  );

  // The gate `admin/ops/page.tsx` puts in front of its permission-gated panels, for the
  // same two reasons: mounting the list for an unknown session fires a `GET` that can
  // only 403 for a normal admin, and the operator would watch the screen render,
  // populate, and then be replaced by a refusal. See `identityAnswerPending`.
  if (identityAnswerPending(me)) {
    return (
      <div className="max-w-3xl space-y-5">
        <Card title="Admin accounts">
          <Skeleton
            rows={4}
            label="Checking whether you may manage admin accounts…"
          />
        </Card>
      </div>
    );
  }

  if (access.refused) {
    return (
      <div className="max-w-3xl space-y-5">
        <WithheldPanel
          title="Admin accounts"
          reason={
            access.reason ??
            "Your admin account cannot manage who may use this console."
          }
          subject="This screen would list who may sign in to this console and in which tier."
        />
      </div>
    );
  }

  return (
    <OperatorsScreen
      viewerId={me.data?.user_id ?? null}
      /**
       * A CONTROL FAILS CLOSED, so anything short of `allowed` closes the form — and the
       * `??` is not decoration. `AdminAccess` has a fourth state with no sentence in it:
       * no data, no error, and not loading either, which is what a query query-core has
       * PAUSED looks like (the console open across a dropped connection). Passing
       * `access.reason` alone would hand that state a `null` restriction, which this
       * screen reads as "you may" — offering every consequential control on the strength
       * of an answer nobody received.
       */
      restriction={
        access.allowed
          ? null
          : (access.reason ??
            "The console has not been able to establish what you may do here — you may be offline. The controls stay closed until it can.")
      }
    />
  );
}

/**
 * The screen proper, mounted only once the identity read has settled on something other
 * than a refusal.
 *
 * `restriction` is non-null in the two cases where we do not KNOW: the identity read
 * failed, or it could not be started at all (an offline browser pauses the query). Either
 * way the controls stay closed with that sentence beside them — a control fails closed
 * (`access.ts`) — while the list read is still attempted, because the API is the
 * enforcement and a console that hid the allowlist because an unrelated read was slow
 * would be worse than one that meets the server's own answer.
 */
function OperatorsScreen({
  viewerId,
  restriction,
}: {
  /** `admin_users.id` of the signed-in operator, or null when we could not find out. */
  viewerId: string | null;
  restriction: string | null;
}) {
  const list = useOperators();

  if (isForbidden(list.error)) {
    return (
      <div className="max-w-3xl space-y-5">
        <WithheldPanel
          title="Admin accounts"
          reason={
            forbiddenReason(list.error) ??
            "The API refused this read: your admin account may not see who may use this console."
          }
          subject="This screen would list who may sign in to this console and in which tier."
        />
      </div>
    );
  }

  /**
   * `.data`, never `.data ?? []` — the difference between "the server said there is one
   * admin" and "the server did not answer" is this screen's whole honesty (§52).
   *
   * AND ERROR FIRST, which is the stricter of the two precedents this repo has and the
   * right one here. The client realm's team screen keeps its last good list under a
   * failure notice; `configState` on `/admin/ops` refuses to, on the grounds that "a
   * stale config table rendered as current is the same lie as an invented one". This list
   * is the answer to "who can reach every client's data", and a failed REFETCH leaves the
   * previous rows in place — so a colleague revoked thirty seconds ago by another super
   * admin would still be shown as having access, under a red box that reads as a network
   * blip. Withholding costs a reload; the other way costs a wrong belief about access.
   */
  const operators = list.error ? undefined : list.data?.operators;

  return (
    <div className="max-w-3xl space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Everyone who can sign in to this console, and what each of them may do.
        Adding, promoting, demoting and revoking are all recorded in the audit
        log against your own account, with the reason you type.
      </p>

      {restriction && (
        <NoticeBox
          tone="warn"
          icon={<CircleHelp aria-hidden className="h-5 w-5" />}
          title="We could not check what you may do here"
        >
          <p className="mt-1">{restriction}</p>
          <p className="mt-2">
            The controls below stay closed until we know. These actions are only
            ever allowed for a super admin, whatever this screen shows, so
            nothing is being withheld that you could otherwise have done.
          </p>
        </NoticeBox>
      )}

      <AddOperatorCard disabled={restriction !== null} />

      <Card
        title="Admin accounts"
        action={
          /* No count until the server has sent a list. "1 account" while the request is
             in flight is a statement about who can reach every client's data, made on no
             evidence. */
          operators ? (
            <span className="text-xs text-ink-faint">
              {formatCount(operators.length)}{" "}
              {operators.length === 1 ? "account" : "accounts"}
            </span>
          ) : undefined
        }
        bodyClassName="p-2"
      >
        {list.error != null && (
          <div className="mb-3 space-y-2 px-4 pt-2">
            <ProblemNotice
              error={list.error}
              onRetry={() => void list.refetch()}
            />
            {/* Said out loud, because an empty card under an error box is otherwise
                indistinguishable from "there is nobody" — and on this screen those are
                opposite facts. */}
            <p className="text-xs text-ink-muted">
              No accounts are listed while that read is failing, including any
              this screen had already shown: a list that is thirty seconds stale
              would tell you somebody still has access after another super admin
              has taken it away.
            </p>
          </div>
        )}

        {/* Loading is a skeleton; a failure is the notice above and NOTHING else. There is
            deliberately no "you are the only admin" fallback: that sentence, wrong, is an
            answer to "who else can reach every client's data" that nobody checked. */}
        {list.isLoading ? (
          <div className="p-4">
            <Skeleton rows={3} />
          </div>
        ) : !operators ? null : operators.length ? (
          <ul className="divide-y divide-line">
            {operators.map((operator) => (
              <li key={operator.id}>
                <OperatorRow
                  operator={operator}
                  viewerId={viewerId}
                  restriction={restriction}
                />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No admin accounts are listed"
            hint="That cannot be right — you are signed in to this console, so at least your own account exists. Reload the page, and treat it as an incident if it stays empty."
          />
        )}

        <p className="px-4 pb-3 pt-1 text-xs text-ink-faint">
          Revoked accounts are not listed: their rows survive as the record of
          what they approved, and &ldquo;who was removed and when&rdquo; is a
          question for the audit log, which keeps a record that cannot be
          quietly changed.
        </p>
      </Card>
    </div>
  );
}

/** A tier as a badge, from the wire string, never from a guess about seniority. */
function RoleBadge({ role }: { role: string }) {
  const copy = lookup(ROLE_COPY, role);
  const isSuper = role === "superadmin";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
        isSuper
          ? "bg-brand-soft text-brand-strong dark:bg-brand-strong/20 dark:text-brand-bright"
          : "bg-black/5 text-ink-muted dark:bg-white/10"
      }`}
    >
      {isSuper ? (
        <ShieldCheck aria-hidden className="h-3 w-3" />
      ) : (
        <UserCog aria-hidden className="h-3 w-3" />
      )}
      {/* Fails VISIBLE: a tier this build has no word for still gets its badge, with the
          wire string in it, because an account whose tier the console cannot name is
          exactly the one somebody needs to look at. */}
      {copy?.label ?? role}
    </span>
  );
}

/**
 * Add an account, and mail its setup link.
 *
 * No password is chosen, generated or shown: the API mints a single-use link and mails it
 * to the address typed here, and there is no field on any response it could be assigned
 * to. That is D-190's finding — a token the inviter can see is an account squat — applied
 * to the account type that can install vendor credentials.
 *
 * The typed confirmation is `add_operator:<role>`, which is the API's own header and is
 * bound to the ROLE. So promoting the picker from Admin to Super admin invalidates a
 * phrase already typed, and the field is cleared when the role changes — the same rule
 * the model picker follows, and for the identical reason: a phrase typed for one outcome
 * must not confirm another.
 */
function AddOperatorCard({ disabled }: { disabled: boolean }) {
  const add = useAddOperator();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<AdminRole>("operator");
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const [added, setAdded] = useState<Operator | null>(null);

  // NOTE: the header the API validates is still `add_operator:<role>` and is built by
  // `useAddOperator` (`lib/api/adminOperators`), which is where it always belonged — the
  // wire value is a property of the REQUEST, not of this form. This screen's job is the
  // human half.
  const copy = lookup(ROLE_COPY, role);
  /** What a PERSON types. The tier, in the words the picker shows. */
  const confirmPhrase = (copy?.label ?? role).toUpperCase();
  const ready =
    !disabled &&
    email.trim().length >= 3 &&
    reason.trim().length >= 3 &&
    confirmationMatches(typed, confirmPhrase);

  return (
    <Card title="Add an admin">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          add.mutate(
            {
              email: email.trim(),
              // An empty box is NOT an empty name: the column is nullable and the row
              // falls back to the address, which is more use than a blank cell.
              name: name.trim() === "" ? null : name.trim(),
              role,
              reason: reason.trim(),
            },
            {
              onSuccess: (created) => {
                setAdded(created);
                setEmail("");
                setName("");
                setReason("");
                setTyped("");
              },
            },
          );
        }}
      >
        {/* A GRID, NOT `flex flex-wrap` WITH HAND-PICKED WIDTHS. The three fields
            were `sm:w-72`, `sm:w-56` and full-width — three arbitrary numbers giving
            a ragged right edge and a wrap order nobody chose. One column on a phone,
            two on a tablet, three on a desktop; they line up because the grid
            decides, and no field carries a width of its own. */}
        <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="block">
            <span className={FIELD_LABEL}>Their email address</span>
            <input
              required
              type="email"
              value={email}
              disabled={disabled}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="off"
              placeholder="asha@calevate.tech"
              aria-label="Email address of the admin to add"
              // `w-full sm:w-72`, not a bare `w-72`. `FIELD` is `w-full`, and overriding
              // it at every width pins a 288px box inside a card that has ~256px of
              // content width on a 320px phone — the fixed-width overflow
              // `tests/responsive.test.ts` chases through `min-w-` utilities, arriving
              // through the one utility it does not scan. The breakpoint keeps the roomy
              // desktop field and lets the phone have the row.
              className={FIELD}
            />
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>Their name (optional)</span>
            <input
              value={name}
              disabled={disabled}
              onChange={(event) => setName(event.target.value)}
              autoComplete="off"
              placeholder="Asha Rao"
              aria-label="Name of the admin to add"
              className={FIELD}
            />
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>Tier</span>
            <select
              value={role}
              disabled={disabled}
              onChange={(event) => {
                setRole(event.target.value as AdminRole);
                // The confirmation names the ROLE, so a different tier is a different
                // string. Carrying the old one over would let a phrase typed to add an
                // admin confirm the creation of a second super admin.
                setTyped("");
                add.reset();
              }}
              aria-label="Tier for the new admin"
              className={FIELD}
            >
              {ADMIN_ROLES.map((value) => (
                <option key={value} value={value}>
                  {ROLE_COPY[value].label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {/* Under the ROW, not under the first column — where it wrapped into a narrow
            ribbon beside two empty fields. */}
        <p className={FIELD_HINT}>
          The setup link is mailed to that address and nowhere else — we cannot
          show it to you, and there is no password to pass on.
        </p>

        {/* WHAT THE TIER MEANS, ABOVE THE BUTTON — the sentence somebody is actually
            deciding on. A super admin can replace the Bolna key and add further admins;
            nothing else on this screen says so. */}
        <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
          {role === "superadmin" ? (
            <TriangleAlert
              aria-hidden
              className="mt-0.5 h-4 w-4 shrink-0 text-rose-600"
            />
          ) : (
            <ShieldCheck
              aria-hidden
              className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint"
            />
          )}
          <div className="min-w-0">
            <p className="font-semibold text-ink">
              {role === "superadmin"
                ? "A super admin can do everything you can, including this screen"
                : "An admin runs onboarding and support, and nothing platform-wide"}
            </p>
            {/* LABELLED HALVES. These were two consecutive paragraphs in one colour, so
                a reader had to parse each to learn which was the grant and which the
                limit — on the screen where that distinction IS the decision. Labelling
                them makes it scannable without shortening either. */}
            <p className="mt-2 text-ink-muted">
              <span className="font-medium text-ink">Can</span> {copy?.can}
            </p>
            {copy?.cannot && (
              <p className="mt-1.5 text-ink-muted">
                <span className="font-medium text-ink">Cannot</span>{" "}
                {copy.cannot}
              </p>
            )}
          </div>
        </div>

        <label className="block">
          <span className={FIELD_LABEL}>Why</span>
          <input
            required
            minLength={3}
            maxLength={500}
            value={reason}
            disabled={disabled}
            onChange={(event) => setReason(event.target.value)}
            aria-label="Why you are adding this admin"
            placeholder="e.g. 'joining as our second onboarding operator'"
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            Recorded in the audit log beside who asked for it. Whoever reads
            this row in a year has to be able to decide whether the reason still
            holds.
          </span>
        </label>

        {/* THE TIER, IN WORDS — not the API's `add_operator:<role>`. See
            `TypedConfirmation`: the phrase has to be specific enough that typing it is
            an act of attention, and readable enough that somebody types it rather than
            copying it. The tier is both, and it is what the server binds its own header
            to, so the two agree about what is being consented to. */}
        <TypedConfirmation
          phrase={confirmPhrase}
          binding="Naming the tier is the confirmation: change the tier and this phrase changes with it, so a phrase typed to add an admin cannot add a super admin."
          value={typed}
          disabled={disabled}
          onChange={(next) => {
            setTyped(next);
            add.reset();
          }}
        />

        <button
          type="submit"
          disabled={!ready || add.isPending}
          className={PRIMARY_BUTTON}
        >
          <UserPlus aria-hidden className="h-4 w-4" />
          {add.isPending
            ? "Adding…"
            : `Add ${copy?.label.toLowerCase() ?? role}`}
        </button>

        {disabled && (
          <p className="flex items-start gap-2 text-xs text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            This form is closed until the console knows what you may do.
          </p>
        )}
      </form>

      {add.error != null && (
        <div className="mt-3">
          <WriteFailure error={add.error} />
        </div>
      )}

      {added && (
        <div className="mt-4">
          <NoticeBox
            tone="ok"
            icon={<MailCheck aria-hidden className="h-5 w-5" />}
            title={`Setup link sent to ${added.email ?? operatorLabel(added)}`}
          >
            <p className="mt-1">
              The account exists and cannot sign in until they follow that link
              and choose their own password. It works once and expires within
              the hour.
            </p>
            <p className="mt-2 text-xs">
              We cannot show or forward the link — it is stored only as a
              fingerprint. If it does not arrive, use{" "}
              <span className="font-semibold">Resend setup link</span> on their
              row below, which invalidates the previous one.
            </p>
          </NoticeBox>
        </div>
      )}
    </Card>
  );
}

/** Which inline confirmation, if any, this row currently has open. */
type RowAction = "role" | "revoke" | "resend";

function OperatorRow({
  operator,
  viewerId,
  restriction,
}: {
  operator: Operator;
  viewerId: string | null;
  restriction: string | null;
}) {
  const [open, setOpen] = useState<RowAction | null>(null);
  const selfBlock = selfAdministrationBlock(operator, viewerId);
  const isMe = selfBlock !== null;
  const label = operatorLabel(operator);
  // `null` for a tier this build has no words for — see `tierChangeTarget`. Revocation is
  // still offered in that case, because it needs no opinion about which tier they are in.
  const target = tierChangeTarget(operator);

  return (
    <div className="px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-black/5 text-ink-muted dark:bg-white/10"
          aria-hidden
        >
          {operator.activated ? (
            <UserCog className="h-4 w-4" />
          ) : (
            <KeyRound className="h-4 w-4" />
          )}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-ink">
            {operator.name ?? "No name on file"}
          </span>
          {/* The whole address, like the client realm's pending-invite row (D-436): a
              super admin has to be able to tell two accounts at one domain apart before
              revoking one of them, and the confirmations below are typed against a row
              they must be sure of. */}
          <span className="block truncate font-mono text-xs text-ink-muted">
            {operator.email ?? "no address on file"}
          </span>
        </span>
        {isMe && <span className="text-xs text-ink-faint">(you)</span>}
        <RoleBadge role={operator.role} />
        {!operator.activated && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
            <KeyRound aria-hidden className="h-3 w-3" />
            Setup link outstanding
          </span>
        )}
        <span className="ml-auto whitespace-nowrap text-xs text-ink-faint">
          added {formatIST(operator.created_at)}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {isMe ? (
          /* THE LOCKOUT SENTENCE, where the controls would have been rather than as a
             disabled button — the API refuses both acts on your own account outright, so
             a greyed-out control would be one that is never available. */
          <p className="flex items-start gap-2 text-xs text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {selfBlock}
          </p>
        ) : restriction !== null ? (
          <p className="flex items-start gap-2 text-xs text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {restriction}
          </p>
        ) : (
          open === null && (
            <>
              {target === null ? (
                <span className="text-xs text-ink-muted">
                  This console does not recognise the tier{" "}
                  <span className="font-mono">{operator.role}</span>, so it will
                  not guess which way a change would move them. Revoking still
                  works.
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setOpen("role")}
                  // Named for the row: identical buttons are identical announcements to a
                  // screen reader, and "promote which one?" is the question a mis-click
                  // answers wrongly.
                  aria-label={`Change the tier of ${label}`}
                  className={SECONDARY_BUTTON_SM}
                >
                  <UserCog aria-hidden className="h-3.5 w-3.5" />
                  Change tier
                </button>
              )}
              {!operator.activated && (
                <button
                  type="button"
                  onClick={() => setOpen("resend")}
                  aria-label={`Resend the setup link for ${label}`}
                  className={SECONDARY_BUTTON_SM}
                >
                  <MailCheck aria-hidden className="h-3.5 w-3.5" />
                  Resend setup link
                </button>
              )}
              <button
                type="button"
                onClick={() => setOpen("revoke")}
                aria-label={`Revoke the admin access of ${label}`}
                className={SECONDARY_BUTTON_SM}
              >
                <UserMinus aria-hidden className="h-3.5 w-3.5" />
                Revoke access
              </button>
            </>
          )
        )}
      </div>

      {open === "role" && target !== null && (
        <RoleChangePanel
          operator={operator}
          target={target}
          onClose={() => setOpen(null)}
        />
      )}
      {open === "revoke" && (
        <RevokePanel operator={operator} onClose={() => setOpen(null)} />
      )}
      {open === "resend" && (
        <ResendPanel operator={operator} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}

/**
 * The confirmation block every consequential row action opens.
 *
 * ONE component rather than three near-copies, because the parts that differ are the
 * heading, the consequence and the confirmation STRING, and the parts that must not
 * differ are the reason field's bounds, the typed-confirmation rule, the disabled
 * predicate and where the failure is rendered. Three copies is how one of them ends up
 * enabling its button on whitespace, or sending a reason the API strips to nothing.
 */
function ConfirmBlock({
  heading,
  consequence,
  confirmPhrase,
  reasonLabel,
  actionLabel,
  pendingLabel,
  danger,
  icon,
  pending,
  error,
  onConfirm,
  onClose,
  children,
}: {
  heading: string;
  consequence: ReactNode;
  /**
   * What a PERSON types — the account's address, not the API's id-bound header string.
   * `TypedConfirmation` argues why the two are different requirements.
   */
  confirmPhrase: string;
  /**
   * The reason box's accessible name, naming the ACT and the account.
   *
   * Every row can open one of these and the visible label on all of them is the word
   * "Why", so without this a screen-reader user hears one identical prompt however many
   * accounts are on screen — the same defect the per-row buttons' `aria-label`s fix one
   * line up. It BEGINS with "Why" so the accessible name still contains the visible
   * label (axe's `label-content-name-mismatch`).
   */
  reasonLabel: string;
  actionLabel: string;
  pendingLabel: string;
  danger: boolean;
  icon: ReactNode;
  pending: boolean;
  error: unknown;
  onConfirm: (reason: string) => void;
  onClose: () => void;
  children?: ReactNode;
}) {
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  // Trimmed before it is measured, because the API strips it and refuses anything under
  // three characters — a form that lights up on "   " teaches an operator the API is
  // flaky (`admin/ops/page.tsx` records the same trap).
  const ready =
    reason.trim().length >= 3 &&
    confirmationMatches(typed, confirmPhrase) &&
    !pending;

  return (
    <div className="mt-3 space-y-3 rounded-card border border-line bg-surface p-4">
      <div className="flex gap-3">
        <span
          className={`mt-0.5 shrink-0 ${danger ? "text-rose-600" : "text-ink-faint"}`}
        >
          {icon}
        </span>
        <div className="min-w-0">
          <p className="font-semibold text-ink">{heading}</p>
          <div className="mt-1 text-ink-muted">{consequence}</div>
          <p className="mt-1 text-xs text-ink-faint">
            Recorded in the audit log against your admin account, with the
            reason you type below.
          </p>
        </div>
      </div>

      {children}

      <label className="block">
        <span className={FIELD_LABEL}>Why</span>
        <input
          required
          minLength={3}
          maxLength={500}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          aria-label={reasonLabel}
          placeholder="e.g. 'left the company on Friday'"
          className={FIELD}
        />
      </label>

      {/* WHO, not `revoke_operator:<uuid>`. The old phrase was a UUID, and nobody types
          a UUID — they copy it, which is a click with extra steps and confirms nothing.
          The address is the thing an operator would most regret getting wrong here, so
          it is the thing worth reading twice. It never leaves this page: the header the
          API validates is still the id-bound string (hard rule 6 keeps mailboxes out of
          headers). */}
      <TypedConfirmation
        phrase={confirmPhrase}
        binding="This names the account you are acting on, so a phrase typed for somebody else cannot be used here."
        value={typed}
        onChange={setTyped}
      />

      {error != null && <WriteFailure error={error} />}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!ready}
          onClick={() => onConfirm(reason.trim())}
          className={danger ? DANGER_BUTTON : PRIMARY_BUTTON_SM}
        >
          {pending ? pendingLabel : actionLabel}
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={onClose}
          className={SECONDARY_BUTTON}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function RoleChangePanel({
  operator,
  target,
  onClose,
}: {
  operator: Operator;
  /**
   * The tier this change moves them TO, decided by `tierChangeTarget` and passed in.
   *
   * A PROP rather than a local ternary, because the null case has to be handled by the
   * row (no control at all) rather than here (a panel that has already been opened), and
   * a component that recomputed it would be a second opinion about which direction an
   * unrecognised tier moves in.
   */
  target: AdminRole;
  onClose: () => void;
}) {
  const change = useSetOperatorRole();
  const targetCopy = lookup(ROLE_COPY, target);
  const label = operatorLabel(operator);
  const promoting = target === "superadmin";

  return (
    <ConfirmBlock
      heading={
        promoting
          ? `Promoting ${label} to super admin`
          : `Demoting ${label} to admin`
      }
      consequence={
        promoting ? (
          <p>
            They gain everything you can do: the vendor API keys, the platform
            configuration, the incident switches, and this screen — so they will
            be able to add and remove admins, including you. Their live sessions
            end, so the change is in force on their next request.
          </p>
        ) : (
          <p>
            They keep onboarding and support across every client and lose the
            four platform-wide authorities: the vendor API keys, the platform
            configuration, the incident switches and this screen. Their live
            sessions end, so the change is in force on their next request.
          </p>
        )
      }
      confirmPhrase={operatorConfirmPhrase(operator)}
      reasonLabel={`Why you are changing ${label}'s tier`}
      actionLabel={promoting ? "Promote to super admin" : "Demote to admin"}
      pendingLabel="Saving…"
      danger={promoting}
      icon={<UserCog aria-hidden className="h-4 w-4" />}
      pending={change.isPending}
      error={change.error}
      onConfirm={(reason) =>
        change.mutate(
          { operatorId: operator.id, role: target, reason },
          { onSuccess: () => onClose() },
        )
      }
      onClose={onClose}
    >
      <p className="text-xs text-ink-faint">{targetCopy?.can}</p>
    </ConfirmBlock>
  );
}

function RevokePanel({
  operator,
  onClose,
}: {
  operator: Operator;
  onClose: () => void;
}) {
  const revoke = useRevokeOperator();
  const label = operatorLabel(operator);

  return (
    <ConfirmBlock
      heading={`Revoking ${label}'s access to this console`}
      consequence={
        <>
          <p>
            Their password, their live sessions and any outstanding setup link
            are destroyed, and they cannot sign in from their next request
            onwards. There is no undo: adding them again creates a new account
            and a new setup link.
          </p>
          {/* The one thing an operator will otherwise ask support about, said here. */}
          <p className="mt-1">
            Their row is kept and their name stays on what they decided — the
            campaigns they approved, the identity checks they signed off, the
            credentials they installed. Nothing about this is a data erasure.
          </p>
        </>
      }
      confirmPhrase={operatorConfirmPhrase(operator)}
      reasonLabel={`Why you are revoking ${label}'s access`}
      actionLabel="Revoke access"
      pendingLabel="Revoking…"
      danger
      icon={<UserMinus aria-hidden className="h-4 w-4" />}
      pending={revoke.isPending}
      error={revoke.error}
      onConfirm={(reason) =>
        revoke.mutate(
          { operatorId: operator.id, reason },
          { onSuccess: () => onClose() },
        )
      }
      onClose={onClose}
    />
  );
}

function ResendPanel({
  operator,
  onClose,
}: {
  operator: Operator;
  onClose: () => void;
}) {
  const resend = useResendOperatorSetupLink();
  const label = operatorLabel(operator);

  return (
    <ConfirmBlock
      heading={`Sending ${label} a fresh setup link`}
      consequence={
        <>
          <p>
            A new single-use link is mailed to{" "}
            <span className="font-mono">
              {operator.email ?? "their address"}
            </span>{" "}
            and the previous one stops working. It is not shown here and cannot
            be forwarded.
          </p>
          {/* THIS IS NOT A PASSWORD RESET, and the API refuses to let it become one. Said
              here because the button is next to a name and the temptation is obvious. */}
          <p className="mt-1">
            This only works for an account that has never set a password.
            Somebody who has forgotten theirs uses the sign-in page&apos;s
            reset, which mails the link to them rather than to you.
          </p>
        </>
      }
      confirmPhrase={operatorConfirmPhrase(operator)}
      reasonLabel={`Why you are re-sending ${label}'s setup link`}
      actionLabel="Send a new setup link"
      pendingLabel="Sending…"
      danger={false}
      icon={<MailCheck aria-hidden className="h-4 w-4" />}
      pending={resend.isPending}
      error={resend.error}
      onConfirm={(reason) =>
        resend.mutate(
          { operatorId: operator.id, reason },
          { onSuccess: () => onClose() },
        )
      }
      onClose={onClose}
    />
  );
}
