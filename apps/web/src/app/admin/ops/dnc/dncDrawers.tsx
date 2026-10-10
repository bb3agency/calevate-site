"use client";

import { useState } from "react";
import { ListPlus, Lock, TriangleAlert, Undo2 } from "lucide-react";

import type { useAdminAccess } from "@/app/admin/access";
import {
  DANGER_BUTTON,
  MonoValue,
  dncSourceCopy,
} from "@/app/admin/ops/opsLanguage";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useFormValidation } from "@/components/formValidation";
import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
  formatCount,
  formatPhone,
} from "@/components/ui";
import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import { MAX_NUMBERS_PER_ADD, parsePastedNumbers } from "@/lib/api/dnc";
import type {
  GlobalDncEntry,
  GlobalDncSource,
  useReleaseGlobally,
  useSuppressGlobally,
} from "@/lib/api/opsDnc";
import { Term } from "@/lib/glossary";

type Access = ReturnType<typeof useAdminAccess>;

/** The order the two sources are offered in; their words live in `dncSourceCopy`. */
const SOURCE_VALUES: GlobalDncSource[] = ["regulator", "platform_block"];

/** The submit row, pinned to the bottom of the drawer's scrolling body. */
const PINNED_ACTIONS =
  "sticky bottom-0 -mx-4 -mb-4 mt-4 flex flex-wrap items-center gap-2 border-t border-line bg-surface px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] sm:-mx-5 sm:px-5";

/**
 * Suppress numbers for every client — the additive direction.
 *
 * A typed word plus a reason, mirroring the `X-Confirm-Action` header the API demands
 * (BACKEND-PATTERNS §7). The reason is trimmed before it is sent because the server strips
 * it and refuses anything under three characters. The API answers with three counts and
 * never echoes the numbers: an operator who pasted the wrong column needs a figure that
 * disagrees with theirs, not their own text handed back.
 */
export function SuppressForm({
  access,
  mutation,
}: {
  access: Access;
  mutation: ReturnType<typeof useSuppressGlobally>;
}) {
  const [paste, setPaste] = useState("");
  const [source, setSource] = useState<GlobalDncSource>("regulator");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  // One parser and one ceiling with the client realm, so a paste from a regulator's email
  // behaves identically on both surfaces.
  const parsed = parsePastedNumbers(paste);
  const tooMany = parsed.length > MAX_NUMBERS_PER_ADD;
  const valid = useFormValidation();
  // The reason's rule lives on the control, so an empty reason SAYS so on submit. These are
  // the gates that are not answers on a control.
  const ready = parsed.length > 0 && !tooMany && confirmationMatches(confirm, "SUPPRESS", "exact");

  return (
    <div className="space-y-4">
      <form
        className="space-y-4"
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
        {/* What the button does, above the button: blast radius first, then what is NOT
            affected, then that it is recorded — an operator who reads only the first line
            has read the part that matters. */}
        <div className="flex gap-3 border-l-2 border-danger py-1 pl-4 text-body">
          <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
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
              <Term id="dnd" />)
              — that is a separate per-campaign scrub, recorded against the campaign it
              covers.
            </p>
            <p className="mt-1 text-meta text-ink-muted">
              Recorded in the audit log under your admin account, together with the reason
              you type below — as counts, never as the numbers themselves.
            </p>
          </div>
        </div>

        {mutation.error != null && <WriteFailure error={mutation.error} actionLabel="Suppress" />}

        <div>
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
          </label>
          <p className={`${FIELD_HINT} flex items-center gap-1`}>
            One per line or comma-separated: ten digits, or the full +91 form.
            <InfoTip label="Numbers we cannot read">
              Anything we can&apos;t read is counted as not a usable number, rather than
              suppressed on a guess.
            </InfoTip>
          </p>
        </div>

        {/* Stopped here rather than at the API's 422: the ceiling is the server's, and an
            operator who pasted a whole register should be told before they wait. */}
        {tooMany && (
          <p className="text-body text-warn">
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

        <div>
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
          </label>
          {valid.error("reason")}
          <p className={`${FIELD_HINT} flex items-center gap-1`}>
            Goes into the audit log.
            <InfoTip label="The reason">
              It is the record of who refused these numbers for the whole platform, and on
              whose instruction — the answer someone will need a year from now.
            </InfoTip>
          </p>
        </div>

        <TypedConfirmation
          match="exact"
          id="global-dnc-suppress-confirm"
          phrase="SUPPRESS"
          value={confirm}
          onChange={setConfirm}
          hint="This confirms you mean the platform-wide list, not one client's."
        />

        {/* A dead control with no explanation cannot be told apart from a broken page. */}
        {!access.allowed && access.reason && (
          <p className="flex items-start gap-2 text-meta text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {access.reason}
          </p>
        )}

        <div className={PINNED_ACTIONS}>
          <button
            type="submit"
            title={access.reason ?? undefined}
            disabled={!access.allowed || !ready || mutation.isPending}
            className={`${PRIMARY_BUTTON} max-sm:w-full max-sm:justify-center`}
          >
            <ListPlus aria-hidden className="h-4 w-4" />
            {mutation.isPending
              ? "Sending…"
              : parsed.length === 1
                ? "Suppress 1 number platform-wide"
                : `Suppress ${formatCount(parsed.length)} numbers platform-wide`}
          </button>
        </div>
      </form>

      {/* Counts, and only counts — the API never echoes the numbers back. */}
      {mutation.data && (
        <section aria-label="Result" className="space-y-3 border-t border-line pt-4">
          <div className="grid grid-cols-3 gap-3">
            <Metric label="Suppressed" value={formatCount(mutation.data.added)} />
            <Metric label="Already suppressed" value={formatCount(mutation.data.already_suppressed)} />
            <Metric label="Not a usable number" value={formatCount(mutation.data.malformed)} />
          </div>
          <p className="text-meta text-ink-muted">
            Totals, not which number went where: a list of who must not be called is itself
            personal data.
          </p>
        </section>
      )}
    </div>
  );
}

/**
 * The confirmation that stands between one suppression and its release.
 *
 * Mounted per entry (the caller keys it by id), so the typed word belongs to one number
 * and cannot be carried to another: a list of forty rows with forty live Release buttons
 * is a mis-click away from calling a complainant. Releasing re-permits dialling somebody
 * who asked not to be dialled, for every client, at the next dispatch tick.
 */
export function ReleaseConfirm({
  entry,
  mutation,
  onDone,
}: {
  entry: GlobalDncEntry;
  mutation: ReturnType<typeof useReleaseGlobally>;
  onDone: () => void;
}) {
  const [confirm, setConfirm] = useState("");
  const releasing = mutation.isPending && mutation.variables === entry.id;
  const number = formatPhone(entry.phone_e164);

  return (
    <div className="space-y-4">
      {mutation.error != null && <WriteFailure error={mutation.error} actionLabel="Release" />}

      <div className="flex gap-3 border-l-2 border-danger py-1 pl-4 text-body">
        <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
        <div className="min-w-0">
          <p className="font-semibold text-ink">
            Releasing <MonoValue>{number}</MonoValue> lets every client dial it again
          </p>
          <p className="mt-1 text-ink-muted">
            From the next dispatch decision, any campaign holding this number may call it
            again. Lift it only if the instruction to refuse it has been withdrawn — a
            client&apos;s own do-not-call entry for the same number, if they have one, still
            applies.
          </p>
          <p className="mt-1 text-ink-muted">
            Reason on file:{" "}
            {entry.source ? dncSourceCopy(entry.source).label : "no source was recorded"}.
          </p>
          <p className="mt-1 text-meta text-ink-muted">
            Recorded in the audit log under your admin account. The only way back is to add the
            number again.
          </p>
        </div>
      </div>

      <TypedConfirmation
        match="exact"
        id={`global-dnc-release-confirm-${entry.id}`}
        phrase="RELEASE"
        value={confirm}
        onChange={setConfirm}
        hint={
          <>
            This lifts the suppression on <MonoValue>{number}</MonoValue>.
          </>
        }
      />

      <div className={PINNED_ACTIONS}>
        <button type="button" disabled={releasing} onClick={onDone} className={SECONDARY_BUTTON}>
          Cancel
        </button>
        <button
          type="button"
          disabled={!confirmationMatches(confirm, "RELEASE", "exact") || releasing}
          onClick={() =>
            mutation.mutate(entry.id, {
              onSuccess: () => onDone(),
            })
          }
          className={`${DANGER_BUTTON} max-sm:flex-1 max-sm:justify-center`}
        >
          <Undo2 aria-hidden className="h-4 w-4" />
          {releasing ? (
            "Releasing…"
          ) : (
            <>
              Release <MonoValue>{number}</MonoValue>
            </>
          )}
        </button>
      </div>
    </div>
  );
}
