"use client";

import { useState, type ReactNode } from "react";
import {
  CheckCircle2,
  Globe2,
  ListPlus,
  Lock,
  PhoneOff,
  Search,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from "lucide-react";

import {
  Card,
  EmptyState,
  MonoValue,
  NOTICE_TONES,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  StatTile,
  formatCount,
  formatIST,
  type NoticeTone,
  PRIMARY_BUTTON_SM,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import {
  DNC_LIST_LIMIT,
  MAX_NUMBERS_PER_ADD,
  parsePastedNumbers,
  useAddDncNumbers,
  useCheckDncNumber,
  useDncList,
  useRemoveDncEntry,
  type DncEntry,
  type DncSource,
} from "@/lib/api/dnc";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/**
 * Do not call (SEC-COMP §3, hard rule 5) — the suppression list made visible.
 *
 * `/v1/dnc` shipped without a screen, which meant the live list the compliance gate
 * reads on every dispatch could only be written by us. This is the client's own way in,
 * and it is shaped by three API decisions it must not paper over:
 *
 * 1. **Adding answers with counts, never numbers.** There is no per-number result to
 *    render, by design. The screen says so rather than leaving the client hunting for
 *    a list that will never come.
 * 2. **Each row says whether it may be undone.** A `global`
 *    entry belongs to the national list; an entry that records a consumer's opt-out is
 *    permanent. Both are SHOWN — a number you cannot un-suppress is still a number you
 *    should know is suppressed — and neither gets a Remove button, because the API
 *    refuses those (`dnc_global_entry`, `dnc_consumer_optout`) and a button that 400s
 *    teaches a client that our compliance rules are a bug.
 * 3. **Checking a number is a POST.** The number is the personal data; a GET would put
 *    it in browser history, access logs and the referrer of the next page. It never
 *    goes in the URL, and the answer is held in component state, not a query cache.
 *
 * ## What the design pass changed
 *
 * Styling moved to the tokens in `globals.css` (`bg-surface`, `border-line`, `text-ink*`,
 * `rounded-card`) and the shared primitives, so this screen inherits a rebrand instead of
 * arguing with one. Four things that were WRONG under the old styling, and are fixed here
 * rather than restyled:
 *
 * - **It printed its own `<h1>Do not call</h1>`**, which the app shell already renders
 *   from the nav list (layout.tsx). Two headings saying the same words is the visible
 *   half of a drift: rename the nav entry and the screen keeps arguing with it.
 * - **A failed `/v1/me` silently deleted the Add form and said nothing.** The permission
 *   test was hand-rolled (`me.data && permissions.includes(...)`), so "we could not find
 *   out" and "you may not" rendered identically — as an empty space. It now goes through
 *   `useWriteAccess`, the one place in this app that answers "may this session write",
 *   which has a sentence for the error case and is the same mechanism the messaging
 *   consent and lead-source screens already use.
 * - **The count of the list was nowhere**, so "your suppression list is empty" and "the
 *   list did not load" looked alike. It is now stated — and stated as a TRUNCATION when
 *   the response is `DNC_LIST_LIMIT` long, because the endpoint clamps and has no offset,
 *   so the row count stops being the account's total at exactly that point.
 * - **Every Remove button had the same accessible name.** A screen reader on a list of
 *   forty suppressions heard "Remove, button" forty times with nothing to tell them
 *   apart; each now names the number it would un-suppress.
 *
 * WHERE A NUMBER MAY GO, which D-436 changed in one direction only. The list renders
 * numbers IN FULL — a client checking "did we suppress the person shouting at me?"
 * cannot do it against dots. What has NOT changed is the URL rule (hard rule 6): the
 * check sends its number in a POST BODY, never a path or a query string, so nothing
 * here reaches browser history, an access log or the next request's referrer.
 */

/** Why a number is on the list, in the client's words. The values are the API's. */
const SOURCE_COPY: Record<string, { label: string; hint: string }> = {
  manual: { label: "Added by your team", hint: "Someone here typed or pasted it in." },
  customer_request: {
    label: "They asked us to stop",
    hint: "A request from the person themselves.",
  },
  call_optout: {
    label: "Opted out on a call",
    hint: "They told the agent not to call again.",
  },
  regulator: { label: "Regulator list", hint: "Suppressed by a regulator's list." },
};

/**
 * The four reasons, ordered by how often they are used. Only `manual` is reversible —
 * that is `REMOVABLE_SOURCES` on the server, and the form says it out loud, because
 * picking the wrong reason here is a decision that cannot be taken back from this screen.
 */
const SOURCE_OPTIONS: { value: DncSource; label: string; note: string }[] = [
  {
    value: "manual",
    label: "Added by your team",
    note: "You can remove these again from the list below.",
  },
  {
    value: "customer_request",
    label: "They asked us to stop",
    note: "Permanent — a person's request cannot be undone from here.",
  },
  {
    value: "call_optout",
    label: "They opted out on a call",
    note: "Permanent — a person's request cannot be undone from here.",
  },
  {
    value: "regulator",
    label: "From a regulator's list",
    note: "Permanent — remove it through support if it is wrong.",
  },
];

/**
 * Form controls, once — a screen whose inputs disagree about padding reads as two.
 *
 * Split rather than overridden at the call site: `${FIELD} pl-8` is two utilities for
 * one property, and which one wins is decided by Tailwind's own emission order rather
 * than by the order they are written in. That is a coin toss dressed as a style.
 */
/* `min-w-0 max-w-full`: an <input> with no width utility sizes to its `size`
   attribute (~20 characters), which at the 16px this repo now gives touch devices
   is ~256px — 2px wider than the 254px card it sits in at 320px, so it painted
   across the border. A CAP rather than `w-full`: these sit in flex rows where a
   forced full width would restyle the desktop console, and on desktop there is
   room so the cap never binds. `min-w-0` because a flex item will not otherwise
   shrink below its own min-content. */
const FIELD_BASE =
  "rounded-md border border-line bg-surface py-1.5 text-sm text-ink placeholder:text-ink-faint min-w-0 max-w-full touch:min-h-11";
const FIELD = `${FIELD_BASE} px-3`;
/** The same field with room for a leading icon. */
const FIELD_ICON = `${FIELD_BASE} pl-8 pr-3`;

export default function DoNotCallPage() {
  const session = useClientSession();
  const entries = useDncList(session);
  const add = useAddDncNumbers(session);
  const remove = useRemoveDncEntry(session);

  /**
   * The entry a client has asked to un-suppress, held until they confirm it. 🔒
   *
   * "Remove" used to call `remove.mutate(entry.id)` on one click, and the consequence is
   * that agents will dial that person again — this screen's own header says the list is
   * checked live before every single call, so a removal takes effect just as immediately
   * as an addition does. Under TCCCPR a wrongly-removed suppression is a call that should
   * not have happened.
   *
   * The friction on this lane was inverted before this: `/data-rights` makes a client type
   * the word ERASE, so destroying a person's data was harder than putting a person back in
   * the dial pool. This does not equalise them — a typed keyword is still the heavier
   * ceremony, and erasure deserves it — but it stops the consequential action being the
   * cheaper one.
   *
   * A modal rather than an inline two-step row swap, which was the other candidate: this
   * console has exactly one dialog idiom (`components/confirmDialog.tsx`, focus-trapped
   * per the WAI-ARIA APG), and a bespoke per-row interaction would be a second answer to
   * "how does this product ask are-you-sure" — the drift CLAUDE.md's one-way-per-problem
   * rule is about. The dialog names the number, so it confirms target as well as intent.
   */
  const [unsuppressing, setUnsuppressing] = useState<DncEntry | null>(null);
  const check = useCheckDncNumber(session);

  /**
   * Adding and removing both need `leads:dispatch` — the same authority that lets
   * someone cause a call, because suppressing a number is that decision in the other
   * direction. `staff` does not hold it, and an impersonating operator is refused every
   * mutating permission (D-22). Checking a number is `leads:read`, so it is deliberately
   * NOT gated: it is the question people arrive with, and it stays answerable inside a
   * read-only support session, which is exactly when someone is asking it.
   */
  const write = useWriteAccess(session, "leads:dispatch", "add or remove numbers on this list");

  const [paste, setPaste] = useState("");
  const [source, setSource] = useState<DncSource>("manual");
  const [phone, setPhone] = useState("");

  const parsed = parsePastedNumbers(paste);
  const tooMany = parsed.length > MAX_NUMBERS_PER_ADD;

  /* `entries.data`, not `entries.data ?? []`: the difference between "the server said
     none" and "the server did not answer" is the whole of this screen's honesty, and an
     empty array erases it. Everything counted or emptied below hangs off this. */
  const rows = entries.data;
  /* At the endpoint's ceiling the row count stops being a total (no offset, clamped
     limit), so the header says which of the two it is showing. */
  const truncated = rows !== undefined && rows.length >= DNC_LIST_LIMIT;

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Numbers your agents will never dial. The list is checked live before every single
        call, so anything added here takes effect straight away — including for a campaign
        that is already running.
      </p>

      <RestrictionNote reason={write.reason} />

      {/* Checking comes first: it is the question someone actually arrives with
          ("did we stop calling this person?"), and it is the one thing everyone with
          access to the account may do. */}
      <Card title="Check a number">
        <p className="text-sm text-ink-muted">
          Ask whether one number is suppressed. This asks the same question the system
          asks itself before it dials, so the answer cannot disagree with what actually
          happens. Anyone with access to this account can check.
        </p>
        <form
          className="mt-3 flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            // POST with the number in the BODY. Never a query string, never the URL —
            // the number is the personal data (see the API's dnc_routes docstring).
            check.mutate(phone.trim());
          }}
        >
          {/* `min-w-0`: this wrapper is a flex item, and a flex item defaults to
              `min-width: auto` — so it took the search input's intrinsic ~256px width
              and would not shrink into the 254px row at 320px. The input's own
              `max-w-full` can only cap it once the wrapper is allowed to give. */}
          <div className="relative min-w-0">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
            <input
              required
              value={phone}
              onChange={(e) => {
                setPhone(e.target.value);
                // A stale verdict beside a changed number is worse than no verdict.
                check.reset();
              }}
              minLength={8}
              maxLength={20}
              inputMode="tel"
              autoComplete="off"
              placeholder="9876543210 or +919876543210"
              aria-label="Phone number to check"
              className={`${FIELD_ICON} w-64 font-mono`}
            />
          </div>
          <button
            type="submit"
            disabled={check.isPending || phone.trim().length < 8}
            className={PRIMARY_BUTTON_SM}
          >
            {check.isPending ? "Checking…" : "Check"}
          </button>
        </form>

        {check.error != null && (
          <div className="mt-3">
            <ProblemNotice error={check.error} />
          </div>
        )}

        {/* A failed check renders the notice above and NOTHING else: "not on the
            do-not-call list" is the single most dangerous sentence this screen can print
            about a request that never landed. */}
        {check.data && (
          <div className="mt-3">
            {!check.data.valid ? (
              <Verdict tone="warn" icon={<ShieldAlert className="h-4 w-4" />}>
                That does not look like a phone number we can dial. Indian mobiles work
                as ten digits, or write the full number starting with +.
              </Verdict>
            ) : check.data.suppressed ? (
              <Verdict tone="stop" icon={<PhoneOff className="h-4 w-4" />}>
                This number is suppressed — no agent will call it.
                {check.data.scope === "global"
                  ? " It is on the national list, so it cannot be removed from this account."
                  : " It was added to your account's list."}
              </Verdict>
            ) : (
              <Verdict tone="ok" icon={<CheckCircle2 className="h-4 w-4" />}>
                This number is not on the do-not-call list. Other checks — calling hours,
                consent — still apply to any actual call.
              </Verdict>
            )}
          </div>
        )}
      </Card>

      {write.allowed && (
        <Card title="Add numbers">
          <p className="text-sm text-ink-muted">
            Paste as many as you like — one per line, or separated by commas. Numbers
            can be ten digits or the full +91 form; we work out the rest.
          </p>
          <form
            className="mt-3 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate({ numbers: parsed, source }, { onSuccess: () => setPaste("") });
            }}
          >
            <textarea
              value={paste}
              onChange={(e) => setPaste(e.target.value)}
              rows={6}
              spellCheck={false}
              aria-label="Numbers to suppress"
              placeholder={"9876543210\n+919876543211\n9876543212"}
              className={`${FIELD} w-full font-mono`}
            />

            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="dnc-source" className="text-sm text-ink-muted">
                Reason
              </label>
              <select
                id="dnc-source"
                value={source}
                onChange={(e) => setSource(e.target.value as DncSource)}
                className={FIELD}
              >
                {SOURCE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <span className="text-xs text-ink-faint">
                {SOURCE_OPTIONS.find((o) => o.value === source)?.note}
              </span>
            </div>

            {/* Stopped here rather than at the API's 422: 2000 is the server's cap and
                a client who pasted 5,000 rows deserves to be told before they wait. */}
            {tooMany && (
              <p className="text-sm text-amber-700 dark:text-amber-400">
                That is {formatCount(parsed.length)} numbers. Add up to{" "}
                {formatCount(MAX_NUMBERS_PER_ADD)} at a time.
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={add.isPending || parsed.length === 0 || tooMany}
                className={PRIMARY_BUTTON_SM}
              >
                <ListPlus className="h-4 w-4" />
                {add.isPending
                  ? "Adding…"
                  : parsed.length === 1
                    ? "Add 1 number"
                    : `Add ${formatCount(parsed.length)} numbers`}
              </button>
              {parsed.length > 0 && !tooMany && (
                <span className="text-xs text-ink-faint">
                  {formatCount(parsed.length)} distinct{" "}
                  {parsed.length === 1 ? "entry" : "entries"} found in what you pasted.
                </span>
              )}
            </div>
          </form>

          {add.error != null && (
            <div className="mt-3">
              <ProblemNotice error={add.error} />
            </div>
          )}

          {/* Counts, and only counts — the API never echoes the numbers back and this
              screen must not imply that it could. */}
          {add.data && (
            <div className="mt-4 space-y-3">
              <div className="grid gap-3 sm:grid-cols-3">
                <StatTile
                  label="Added"
                  value={formatCount(add.data.added)}
                  icon={<PhoneOff className="h-5 w-5" />}
                  tone="strong"
                  hint="Suppressed from now on."
                />
                <StatTile
                  label="Already on the list"
                  value={formatCount(add.data.already_suppressed)}
                  icon={<ShieldCheck className="h-5 w-5" />}
                  hint="Nothing to do — they were suppressed already."
                />
                <StatTile
                  label="Not a usable number"
                  value={formatCount(add.data.malformed)}
                  icon={<ShieldAlert className="h-5 w-5" />}
                  hint="Skipped rather than guessed at."
                />
              </div>
              <p className="text-xs text-ink-faint">
                We report totals, not which number went where: a list of who asked us to
                stop calling them is itself personal data. Use the check above if you
                need to confirm one number.
              </p>
            </div>
          )}
        </Card>
      )}

      <Card
        title="Suppressed numbers"
        action={
          /* No count until the server has sent one. "0 entries" while the first request
             is in flight is a statement about the client's compliance posture, and it is
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
        {/* While the dialog is open the refusal belongs INSIDE it, where the decision is
            being made — rendering it here as well would say the same failure twice. */}
        {remove.error != null && unsuppressing == null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={remove.error} />
          </div>
        )}
        {entries.error != null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={entries.error} onRetry={() => entries.refetch()} />
          </div>
        )}

        {/* Loading is a skeleton, failure is the notice above and NOTHING ELSE, and the
            empty state is reached only through a `rows` the server actually sent. "Nobody
            is suppressed yet" under a failed request is the worst sentence on this
            screen: it reads as "nobody is suppressed", which is a compliance claim we
            would be making on no evidence. */}
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
                canSuppress={write.allowed}
                removing={remove.isPending && remove.variables === entry.id}
                onRemove={() => setUnsuppressing(entry)}
              />
            ))}
          </ul>
        ) : (
          <EmptyState
            title="Nobody is suppressed yet"
            hint="Anyone who tells an agent to stop calling is added here automatically. You can also add numbers yourself."
          />
        )}
      </Card>

      {/* The consequence, not a restatement of the command (NN/g, *Preventing User
          Errors*, read 25 Aug 2026). Closes only on success: a failed removal leaves the
          number suppressed, and closing would imply it no longer was. */}
      {unsuppressing && (
        <ConfirmDialog
          title="Let agents call this number again?"
          confirmLabel="Un-suppress this number"
          pendingLabel="Removing…"
          cancelLabel="Keep it suppressed"
          pending={remove.isPending}
          error={remove.error}
          onCancel={() => {
            remove.reset();
            setUnsuppressing(null);
          }}
          onConfirm={() =>
            remove.mutate(unsuppressing.id, { onSuccess: () => setUnsuppressing(null) })
          }
        >
          <p>
            <MonoValue className="tabular-nums text-ink">
              {unsuppressing.phone_e164}
            </MonoValue>{" "}
            comes off your do-not-call list.
          </p>
          <p>
            This list is checked live before every single call, so the change takes effect
            straight away:{" "}
            <strong className="font-semibold text-ink">
              your agents will be able to ring this person again
            </strong>
            . Only do this if you know they are happy to be called.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

/**
 * A compliance verdict, in the four tones `NOTICE_TONES` already defines.
 *
 * Local rather than shared for the reason ui.tsx gives at `NOTICE_TONES`: only the
 * palette is common between screens, the shape is not. (This one carries an icon and one
 * paragraph; the consent screen's carries two.)
 */
function Verdict({
  tone,
  icon,
  children,
}: {
  tone: NoticeTone;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <p className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES[tone]}`}>
      <span className="mt-0.5 shrink-0" aria-hidden>
        {icon}
      </span>
      <span>{children}</span>
    </p>
  );
}

function EntryRow({
  entry,
  canSuppress,
  removing,
  onRemove,
}: {
  entry: DncEntry;
  canSuppress: boolean;
  removing: boolean;
  onRemove: () => void;
}) {
  // `DncEntryOut.source` is `string | null`; `lookup` absorbs the null too.
  const source = lookup(SOURCE_COPY, entry.source);
  const global = entry.scope === "global";

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          global ? "bg-black/5 text-ink-muted dark:bg-white/10" : "bg-brand-soft text-brand-strong"
        }`}
        aria-hidden
      >
        {global ? <Globe2 className="h-4 w-4" /> : <PhoneOff className="h-4 w-4" />}
      </span>
      {/* IN FULL (D-436) — a suppression list a client cannot read back is one they
          cannot check against the caller complaining that we rang them again. */}
      <MonoValue className="tabular-nums text-ink">{entry.phone_e164}</MonoValue>
      {global && (
        // Shown, never removable: it is not this account's entry, and hiding it would
        // leave a client wondering why a number they can't find is never dialled.
        <span className="rounded-full border border-line bg-app px-2 py-0.5 text-xs font-medium text-ink-muted">
          national list
        </span>
      )}
      {/* Fails VISIBLE: a source this build cannot name still gets its row and its raw
          value, because a suppression the client cannot see is one they will ask us to
          explain. */}
      <span className="text-xs text-ink-muted">
        {source?.label ?? entry.source ?? "unknown reason"}
      </span>
      <span className="ml-auto whitespace-nowrap text-xs text-ink-faint">
        {formatIST(entry.added_at)}
      </span>
      {/* `removable` is the server's own `is_removable()` verdict, RENDERED rather than
          re-derived from `scope`/`source` here. Two rules that agree today drift apart
          the day one of them changes, and the direction this one drifts in is a Remove
          button on a consumer opt-out. */}
      {entry.removable ? (
        canSuppress ? (
          <button
            type="button"
            disabled={removing}
            onClick={onRemove}
            // Named for the row: forty buttons called "Remove" are forty identical
            // announcements to a screen reader, and "remove which one?" is exactly the
            // question a mis-click answers wrongly.
            aria-label={`Remove ${entry.phone_e164} from the do-not-call list`}
            className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-ink-muted hover:bg-black/5 disabled:opacity-50 dark:hover:bg-white/5"
          >
            <Trash2 className="h-3.5 w-3.5" />
            {removing ? "Removing…" : "Remove"}
          </button>
        ) : null
      ) : (
        <span className="flex items-center gap-1.5 text-xs text-ink-faint">
          <Lock className="h-3.5 w-3.5" aria-hidden />
          {global ? "removed by operations only" : "opt-out — cannot be undone"}
        </span>
      )}
    </li>
  );
}
