"use client";

import { useState } from "react";
import {
  Globe2,
  ListPlus,
  Lock,
  PhoneOff,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  Undo2,
} from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import {
  CopyButton,
  DANGER_BUTTON,
  dncSourceCopy,
  MonoValue,
  TermGloss,
  TypeToConfirm,
  confirmMatches,
} from "@/app/admin/ops/opsLanguage";
import { WriteFailure } from "@/app/admin/writeFailure";
import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  StatTile,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { DNC_LIST_LIMIT, MAX_NUMBERS_PER_ADD, parsePastedNumbers } from "@/lib/api/dnc";
import {
  useGlobalDncList,
  useReleaseGlobally,
  useSuppressGlobally,
  type GlobalDncEntry,
  type GlobalDncSource,
} from "@/lib/api/opsDnc";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

/**
 * The PLATFORM-WIDE do-not-call screen — `/v1/ops/dnc/global` given the screen it never had.
 *
 * ## Why this screen exists
 *
 * The three routes behind it shipped complete, audited and step-up confirmed, and were
 * reachable only by curl: nothing in `apps/web/src` referenced them except the generated
 * types. `runbooks/dnc-complaint.md` §6 therefore told an operator to hand-assemble a POST
 * with an `X-Confirm-Action` header, against production, while answering a regulator — the
 * document people follow when they are least careful. That is the same defect the ops
 * console already closed for the load-shed mode, the dead-letter replay and the audit-chain
 * verification, and it is closed here the same way: every one of them is a control on a
 * screen, and the runbook keeps the curl as the fallback for a console that cannot load.
 *
 * ## The plain-language pass (see `../opsLanguage.tsx`)
 *
 * This screen is used by ONE non-engineer, so no code symbol, path, status, internal event
 * name or decision-record code reaches the visible copy — those stay in comments like this
 * one. The one unavoidable legal term (the national Do Not Disturb register) is kept and
 * glossed in place with `TermGloss`, and the two suppression sources speak with the ONE
 * voice `dncSourceCopy` owns so the select, the row and the release block cannot drift.
 *
 * ## What makes this the most dangerous list in the product
 *
 * A row here is `dnc_list.scope='global'` (D-107): an ABSOLUTE suppression, true for every
 * tenant at once, ranked above a tenant entry by the compliance gate and removable by no
 * client. So the two directions are not symmetrical and this screen does not pretend they
 * are. **Suppressing** costs calls that would have been placed. **Releasing re-permits
 * dialling somebody who asked not to be dialled**, for every client on the platform, at the
 * next dispatch tick — which is a TRAI complaint with our own audit log as the evidence.
 *
 * Four properties follow, and none of them is styling:
 *
 * 1. **There is no default state.** The list is `GlobalDncEntry[] | undefined` and stays
 *    that way: a read that failed renders the refusal above and no rows, never "nobody is
 *    suppressed platform-wide", which is a compliance claim made on no evidence (§52).
 * 2. **Both writes carry their own typed word and their own header**, and the two headers
 *    are different strings the API binds separately. The typed word says WHICH act was
 *    meant on this click; admin-realm MFA already says who holds the session.
 * 3. **The destructive direction is confirmed PER ROW.** Releasing opens a block naming
 *    the number it would un-suppress, states what happens next, and takes RELEASE
 *    typed into it — the discipline the tenant erasure and the credit adjustment already
 *    use for acts bound to one object. A list of forty rows with forty live Release
 *    buttons is a mis-click away from calling a complainant.
 * 4. **Counts, never numbers, out of a BULK ADD.** The API answers an add with three
 *    integers rather than echoing the pasted list back — an operator who pasted the
 *    wrong column needs a count that disagrees with theirs, not their own text repeated.
 *    The LIST is a different question and answers it in full (D-436): releasing a
 *    platform-wide suppression means reading the number back to whoever asked for it.
 *
 * NOT HERE, and argued rather than forgotten: `POST /v1/admin/tenants/{tenant_id}/
 * campaigns/{campaign_id}/preference-scrub`. It is the national customer preference
 * register, which is a DIFFERENT fact — a per-campaign scrub run on an access provider's
 * DLT platform, recorded against the campaign it covers and expiring at 23:59:59 IST that
 * day. It names a tenant and a campaign, so it belongs beside them and not on a
 * platform-wide screen; and performing one at all needs the Registered Telemarketer
 * relationship (R-01) this company does not yet hold, which is an external blocker rather
 * than a missing screen. `runbooks/dnc-complaint.md` §8 carries the procedure meanwhile.
 *
 * NO `<h1>`: the admin shell (layout.tsx) derives the page title from the same nav list it
 * renders, so a heading here would print the screen's name twice.
 */

/**
 * The two sources a suppression can carry. The wording lives in `dncSourceCopy` (one voice
 * for the select, the row and the release block); this only fixes the order they appear in.
 */
const SOURCE_VALUES: GlobalDncSource[] = ["regulator", "platform_block"];

export default function GlobalDncPage() {
  const entries = useGlobalDncList();
  const suppress = useSuppressGlobally();
  const release = useReleaseGlobally();
  /**
   * Every route on `/v1/ops` is `ops:manage`, which only `superadmin` holds
   * (`core/rbac.py`). Asked of the admin realm's own identity read rather than derived
   * from a 403, so the controls disable themselves with the reason instead of offering a
   * button whose only outcome is a refusal that reads like a fault.
   *
   * Gated on the PERMISSION alone and not on the list read, unlike the platform switches:
   * those move a state that must be read before it can be moved, and these do not.
   * Suppressing a number the list could not be shown for is still the right act when a
   * regulator is on the phone, and withdrawing it would remove the control exactly when
   * the platform is behaving strangely.
   */
  const write = useAdminAccess("ops:manage", "change the platform-wide do-not-call list");

  /* `entries.data`, not `entries.data ?? []`: "the server said none" and "the server did
     not answer" are opposite facts about our compliance posture, and an empty array erases
     the difference. Everything counted or emptied below hangs off this. */
  const rows = entries.data;
  /* At the endpoint's ceiling the row count stops being a total (it clamps and has no
     offset), so the header says which of the two it is showing. */
  const truncated = rows !== undefined && rows.length >= DNC_LIST_LIMIT;

  /*
   * THE PLATFORM-WIDE DNC LIST, DECLARED TO THE SCREEN ASSISTANT.
   *
   * EVERY ROW ON THIS SCREEN IS A PHONE NUMBER, so this declaration carries none of them
   * and declares no field either — which is a stronger statement than marking them
   * `personal: "phone"` would be, and it is deliberate.
   *
   * Redaction would have WORKED: `redactForWire` would swap each value for «PHONE_n» and
   * `assert_redacted` would confirm it. The reason not to is that the two controls it
   * would cover are the paste box and the suppression reason, and neither should be
   * reachable from a sentence. The paste box is a bulk WRITE against every client's dialler
   * at once; a fill into it is the assistant nominating who this platform will never call
   * again, behind a typed confirmation whose whole purpose is that a human read the
   * numbers. The reason box is free text an operator writes about a complainant, which is
   * where a name lands — and a name in the payload refuses the question outright
   * (`copilot/sanitize.py`), on a screen somebody has open because a regulator is on the
   * phone.
   *
   * The counts are the useful half and identify nobody: how many numbers this platform
   * refuses to dial, which provenances they carry, and whether the list is complete.
   */
  useCopilotSurface({
    route: "/admin/ops/dnc",
    title: "Do-not-call, platform-wide",
    realm: "admin",
    fields: [],
    facts: rows
      ? [
          {
            key: "entries",
            label: truncated
              ? `Entries listed (clamped at the endpoint's ceiling of ${DNC_LIST_LIMIT}, so this is not the total)`
              : "Numbers suppressed for every client",
            value: String(rows.length),
          },
          {
            key: "sources",
            label: "Where the listed entries came from",
            value:
              [...new Set(rows.map((entry) => entry.source ?? "unrecorded"))].sort().join(", ") ||
              "none",
          },
          {
            key: "removable",
            label: "Listed entries an operator may release",
            value: String(rows.filter((entry) => entry.removable).length),
          },
          {
            key: "may_write",
            label: "May this operator suppress or release a number",
            value: write.allowed ? "yes" : "no",
          },
          {
            key: "numbers_withheld",
            label: "The numbers themselves",
            value: "not sent to the assistant — see the comment above this declaration",
          },
        ]
      : [
          {
            key: "list",
            label: "The platform-wide list",
            // "Nothing is suppressed platform-wide" is the most dangerous sentence this
            // page can say, and a failed read is not evidence for it.
            value: entries.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  return (
    <div className="max-w-2xl space-y-5">
      <p className="mt-0.5 text-sm text-ink-muted">
        These are the numbers Calevate will not dial for anyone. A number here overrides
        every client&apos;s own do-not-call list, is checked before every single call, and no
        client can add or remove it. Every change you make is recorded in the audit log
        under your admin account.
      </p>

      <SuppressPanel access={write} mutation={suppress} />

      <Card
        title="Suppressed for every client"
        action={
          /* No count until the server has sent one: "0 entries" while the first request is
             in flight is a statement about what this platform refuses to dial, and it is
             the wrong one. */
          rows ? (
            <span className="text-xs text-ink-faint">
              {truncated
                ? `Showing the ${formatCount(DNC_LIST_LIMIT)} most recently added`
                : `${formatCount(rows.length)} ${rows.length === 1 ? "entry" : "entries"}`}
            </span>
          ) : undefined
        }
        bodyClassName="p-2"
      >
        {release.error != null && (
          <div className="mb-3 px-4 pt-2">
            <WriteFailure error={release.error} actionLabel="Release" />
          </div>
        )}
        {entries.error != null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={entries.error} onRetry={() => entries.refetch()} />
            {/* The refusal in this screen's own words, beside the generic one. "Nothing is
                suppressed platform-wide" is the most dangerous sentence this page can
                print, and an operator who cannot see the list is the one most likely to
                assume it. */}
            <p className="mt-2 text-sm text-ink-muted">
              This screen will not tell you what is suppressed, and it will not tell you
              nothing is. The suppressions are unaffected — the check runs against them
              directly before every call, not from this screen.
            </p>
          </div>
        )}

        {/* Loading is a skeleton, failure is the refusal above and NOTHING ELSE, and the
            empty state is reached only through a `rows` the server actually sent. */}
        {entries.isLoading ? (
          <div className="p-4">
            <Skeleton rows={5} />
          </div>
        ) : !rows ? null : rows.length ? (
          <ul className="divide-y divide-line">
            {rows.map((entry) => (
              <EntryRow
                key={entry.id}
                entry={entry}
                access={write}
                releasing={release.isPending && release.variables === entry.id}
                onRelease={() => release.mutate(entry.id)}
              />
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No number is suppressed platform-wide"
            hint="Clients' own do-not-call lists are separate and are not shown here. Add a number above when a regulator names one, or when this platform must never call it again."
          />
        )}
      </Card>
    </div>
  );
}

/**
 * Suppress numbers for every client — the additive direction.
 *
 * The confirmation is this console's settled pattern kept intact: a typed word plus a
 * reason, mirroring the `X-Confirm-Action` header the API demands (BACKEND-PATTERNS §7).
 * The reason is trimmed before it is measured, because the server strips it and refuses
 * anything under three characters — a form that enables its button on `"   "` teaches the
 * operator that the API is flaky.
 */
function SuppressPanel({
  access,
  mutation,
}: {
  access: ReturnType<typeof useAdminAccess>;
  mutation: ReturnType<typeof useSuppressGlobally>;
}) {
  const [paste, setPaste] = useState("");
  const [source, setSource] = useState<GlobalDncSource>("regulator");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  // `parsePastedNumbers` and the ceiling come from the client-realm module: one server
  // constant, one parser, and a paste from a regulator's email behaves identically on
  // both surfaces.
  const parsed = parsePastedNumbers(paste);
  const tooMany = parsed.length > MAX_NUMBERS_PER_ADD;
  const valid = useFormValidation();
  // The reason's rule left `ready` and went to the control, so pressing Suppress with an
  // empty reason now SAYS so instead of doing nothing. What stays are the two gates that
  // are not answers on a control: whether the paste parsed into numbers at all, and the
  // typed confirmation.
  const ready = parsed.length > 0 && !tooMany && confirmMatches(confirm, "SUPPRESS");

  return (
    <Card title="Suppress a number for every client">
      <form
        className="space-y-3"
        noValidate
        onSubmit={valid.onSubmit(() => {
          mutation.mutate(
            { numbers: parsed, source, reason: reason.trim() },
            {
              onSuccess: () => {
                setPaste("");
                setReason("");
                setConfirm("");
              },
            },
          );
        })}
      >
        {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON. Blast radius first, then what is NOT
            affected, then the fact that it is recorded — in that order, because an
            operator who reads only the first line has read the part that matters. */}
        <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
          <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
          <div className="min-w-0">
            <p className="font-semibold text-ink">
              Every client stops dialling these numbers, from the next dispatch decision
            </p>
            <p className="mt-1 text-ink-muted">
              This is not one client&apos;s list. A number here overrides every client&apos;s
              own do-not-call list, shows on each of their lists as one they cannot lift, and
              no client can remove it. Inbound calls are unaffected — the do-not-call list
              only governs outbound dialling. It is{" "}
              <span className="font-semibold">not</span> the national customer preference
              register (
              <TermGloss term="DND">India&apos;s national Do Not Disturb registry</TermGloss>)
              — that is a separate per-campaign scrub, recorded against the campaign it
              covers.
            </p>
            <p className="mt-1 text-xs text-ink-faint">
              Recorded in the audit log under your admin account, together with the reason
              you type below — as counts, never as the numbers themselves.
            </p>
          </div>
        </div>

        {mutation.error != null && <WriteFailure error={mutation.error} actionLabel="Suppress" />}

        <label className="block">
          <span className={FIELD_LABEL}>Numbers</span>
          <textarea
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            rows={4}
            spellCheck={false}
            disabled={!access.allowed}
            placeholder={"9876543210\n+919876543211"}
            className={`${FIELD} w-full font-mono`}
          />
          <span className={FIELD_HINT}>
            One number per line, or separated by commas. Ten digits, or the full +91 form.
            Anything we can&apos;t read is counted as not a usable number, rather than
            suppressed on a guess.
          </span>
        </label>

        {/* Stopped here rather than at the API's 422: the ceiling is the server's and an
            operator who pasted a whole register deserves to be told before they wait. */}
        {tooMany && (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            That is {formatCount(parsed.length)} numbers. Add up to{" "}
            {formatCount(MAX_NUMBERS_PER_ADD)} at a time.
          </p>
        )}

        <label className="block">
          <span className={FIELD_LABEL}>Why this platform refuses these numbers</span>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value as GlobalDncSource)}
            disabled={!access.allowed}
            className={FIELD}
          >
            {SOURCE_VALUES.map((value) => (
              <option key={value} value={value}>
                {dncSourceCopy(value).label}
              </option>
            ))}
          </select>
          <span className={FIELD_HINT}>{dncSourceCopy(source).help}</span>
        </label>

        <label className="block">
          <span className={FIELD_LABEL}>Reason</span>
          <input
            {...valid.field("reason", "Say why the platform refuses these numbers.")}
            required
            minLength={3}
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={!access.allowed}
            placeholder="e.g. 'TRAI escalation TR-4471 named this number'"
            className={FIELD}
          />
          {valid.error("reason")}
          <span className={FIELD_HINT}>
            What you write here goes into the audit log. It is the record of who refused
            these numbers for the whole platform, and on whose instruction — the answer
            someone will need a year from now.
          </span>
        </label>

        <TypeToConfirm
          id="global-dnc-suppress-confirm"
          word="SUPPRESS"
          value={confirm}
          onChange={setConfirm}
          hint="This confirms you mean the platform-wide list, not one client's."
        />

        <button
          type="submit"
          title={access.reason ?? undefined}
          disabled={!access.allowed || !ready || mutation.isPending}
          className={PRIMARY_BUTTON}
        >
          <ListPlus aria-hidden className="h-4 w-4" />
          {mutation.isPending
            ? "Sending…"
            : parsed.length === 1
              ? "Suppress 1 number platform-wide"
              : `Suppress ${formatCount(parsed.length)} numbers platform-wide`}
        </button>

        {/* A dead control with no explanation is worse than a refusal after the click:
            the operator cannot tell it apart from a broken page. */}
        {!access.allowed && access.reason && (
          <p className="flex items-start gap-2 text-xs text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {access.reason}
          </p>
        )}
      </form>

      {/* Counts, and only counts — the API never echoes the numbers back and this screen
          must not imply that it could. */}
      {mutation.data && (
        <div className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <StatTile
              label="Suppressed"
              value={formatCount(mutation.data.added)}
              icon={<PhoneOff className="h-5 w-5" />}
              tone="strong"
              hint="No client will dial these from the next dispatch decision."
            />
            <StatTile
              label="Already suppressed"
              value={formatCount(mutation.data.already_suppressed)}
              icon={<ShieldCheck className="h-5 w-5" />}
              hint="Nothing to do — the platform-wide list already covered them."
            />
            <StatTile
              label="Not a usable number"
              value={formatCount(mutation.data.malformed)}
              icon={<ShieldAlert className="h-5 w-5" />}
              hint="Skipped rather than guessed at."
            />
          </div>
          <p className="text-xs text-ink-faint">
            Totals, not which number went where: a list of who must not be called is itself
            personal data.
          </p>
        </div>
      )}
    </Card>
  );
}

/**
 * One suppression, and the confirmation that stands between it and being lifted.
 *
 * `entry.removable` is deliberately NOT what gates the control here, and that is the one
 * subtlety on this screen. `is_removable()` answers "may a CLIENT undo this", so it is
 * false on every row this endpoint returns — reading it as "nobody may" would leave the
 * ops surface unable to perform the act it exists for. The API's own docstring draws the
 * line: global suppressions are removed by operations, through this router.
 */
function EntryRow({
  entry,
  access,
  releasing,
  onRelease,
}: {
  entry: GlobalDncEntry;
  access: ReturnType<typeof useAdminAccess>;
  releasing: boolean;
  onRelease: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [confirm, setConfirm] = useState("");

  return (
    <li className="px-4 py-2.5 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-black/5 text-ink-muted dark:bg-white/10"
          aria-hidden
        >
          <Globe2 className="h-4 w-4" />
        </span>
        {/* IN FULL (D-436), and copyable. An operator releasing a platform-wide suppression
            has to read the number back to the telecom operator or regulator who asked for
            it — and the confirmation below asks them to match it, which dots made
            impossible. The copy control is for that quote, never a secret (see
            `CopyButton`); the number is already on screen, so this adds no disclosure. */}
        <span className="inline-flex items-center gap-1.5">
          <MonoValue className="tabular-nums text-ink">{entry.phone_e164}</MonoValue>
          <CopyButton value={entry.phone_e164} label={entry.phone_e164} />
        </span>
        {/* Fails VISIBLE: a source this build cannot name still gets its row and, through
            `dncSourceCopy`, its raw value read back — a suppression an operator cannot
            explain is one they will be asked to. */}
        <span className="text-xs text-ink-muted">
          {entry.source ? dncSourceCopy(entry.source).label : "No source recorded"}
        </span>
        <span className="ml-auto whitespace-nowrap text-xs text-ink-faint">
          {formatIST(entry.added_at)}
        </span>
        {access.allowed && !confirming && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            // Named for the row: forty buttons called "Release" are forty identical
            // announcements to a screen reader, and "release which one?" is exactly the
            // question a mis-click answers wrongly.
            aria-label={`Release the platform-wide suppression on ${entry.phone_e164}`}
            className={SECONDARY_BUTTON}
          >
            <Undo2 aria-hidden className="h-3.5 w-3.5" />
            Release
          </button>
        )}
      </div>

      {/* The destructive direction, confirmed against THIS row. Opened by the button
          above rather than rendered inline for every entry, so the typed word belongs to
          one number and cannot be carried from the row above it. */}
      {confirming && (
        <div className="mt-3 space-y-3 rounded-card border border-line bg-surface p-4">
          <div className="flex gap-3">
            <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
            <div className="min-w-0">
              <p className="font-semibold text-ink">
                Releasing <MonoValue>{entry.phone_e164}</MonoValue> lets every client dial it
                again
              </p>
              <p className="mt-1 text-ink-muted">
                From the next dispatch decision, any campaign holding this number may call it
                again. Lift it only if the instruction to refuse it has been withdrawn — a
                client&apos;s own do-not-call entry for the same number, if they have one,
                still applies.
              </p>
              <p className="mt-1 text-ink-muted">
                Reason on file:{" "}
                {entry.source ? dncSourceCopy(entry.source).label : "no source was recorded"}.
              </p>
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the audit log under your admin account. The only way back is to
                add the number again.
              </p>
            </div>
          </div>

          <TypeToConfirm
            id={`global-dnc-release-confirm-${entry.id}`}
            word="RELEASE"
            value={confirm}
            onChange={setConfirm}
            hint={
              <>
                This lifts the suppression on{" "}
                <MonoValue>{entry.phone_e164}</MonoValue>.
              </>
            }
          />

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={!confirmMatches(confirm, "RELEASE") || releasing}
              onClick={onRelease}
              className={DANGER_BUTTON}
            >
              <Undo2 aria-hidden className="h-4 w-4" />
              {releasing ? (
                "Releasing…"
              ) : (
                <>
                  Release <MonoValue>{entry.phone_e164}</MonoValue>
                </>
              )}
            </button>
            <button
              type="button"
              disabled={releasing}
              onClick={() => {
                setConfirming(false);
                setConfirm("");
              }}
              className={SECONDARY_BUTTON}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
