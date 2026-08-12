"use client";

import { useState } from "react";

import { Card, EmptyState, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import {
  MAX_NUMBERS_PER_ADD,
  parsePastedNumbers,
  useAddDncNumbers,
  useCheckDncNumber,
  useDncList,
  useRemoveDncEntry,
  type DncEntry,
  type DncSource,
} from "@/lib/api/dnc";
import { useMe } from "@/lib/api/hooks";
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
 * 2. **The list is masked, and each row says whether it may be undone.** A `global`
 *    entry belongs to the national list; an entry that records a consumer's opt-out is
 *    permanent. Both are SHOWN — a number you cannot un-suppress is still a number you
 *    should know is suppressed — and neither gets a Remove button, because the API
 *    refuses those (`dnc_global_entry`, `dnc_consumer_optout`) and a button that 400s
 *    teaches a client that our compliance rules are a bug.
 * 3. **Checking a number is a POST.** The number is the personal data; a GET would put
 *    it in browser history, access logs and the referrer of the next page. It never
 *    goes in the URL, and the answer is held in component state, not a query cache.
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

export default function DoNotCallPage() {
  const session = useClientSession();
  const me = useMe(session);
  const entries = useDncList(session);
  const add = useAddDncNumbers(session);
  const remove = useRemoveDncEntry(session);
  const check = useCheckDncNumber(session);

  const [paste, setPaste] = useState("");
  const [source, setSource] = useState<DncSource>("manual");
  const [phone, setPhone] = useState("");

  const parsed = parsePastedNumbers(paste);
  const tooMany = parsed.length > MAX_NUMBERS_PER_ADD;

  /**
   * Adding and removing both need `leads:dispatch` — the same authority that lets
   * someone cause a call, because suppressing a number is that decision in the other
   * direction. `staff` does not hold it, and an impersonating operator is refused every
   * mutating permission (D-22). Checking a number is `leads:read`, so it stays open to
   * both. Rendering the forms regardless would be rendering a 403.
   */
  const canSuppress = Boolean(
    me.data && me.data.permissions.includes("leads:dispatch") && !me.data.impersonating,
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Do not call</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Numbers your agents will never dial. The list is checked live before every
          single call, so anything added here takes effect straight away — including
          for a campaign that is already running.
        </p>
      </div>

      {me.data && !canSuppress && (
        <p className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
          {me.data.impersonating
            ? "You are viewing this account read-only, so the list can be read and checked here but not changed."
            : "You can see and check this list. Adding or removing numbers is done by an account owner."}
        </p>
      )}

      {/* Checking comes first: it is the question someone actually arrives with
          ("did we stop calling this person?"), and it is the one thing everyone with
          access to the account may do. */}
      <Card title="Check a number">
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Ask whether one number is suppressed. This asks the same question the system
          asks itself before it dials, so the answer cannot disagree with what actually
          happens.
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
            className="w-64 rounded-md border border-slate-200 px-3 py-1.5 font-mono text-sm dark:border-slate-700 dark:bg-slate-950"
          />
          <button
            type="submit"
            disabled={check.isPending || phone.trim().length < 8}
            className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            {check.isPending ? "Checking…" : "Check"}
          </button>
        </form>

        {check.error != null && (
          <div className="mt-3">
            <ProblemNotice error={check.error} />
          </div>
        )}

        {check.data && (
          <div className="mt-3">
            {!check.data.valid ? (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
                That does not look like a phone number we can dial. Indian mobiles work
                as ten digits, or write the full number starting with +.
              </p>
            ) : check.data.suppressed ? (
              <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">
                This number is suppressed — no agent will call it.
                {check.data.scope === "global"
                  ? " It is on the national list, so it cannot be removed from this account."
                  : " It was added to your account's list."}
              </p>
            ) : (
              <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
                This number is not on the do-not-call list. Other checks — calling hours,
                consent — still apply to any actual call.
              </p>
            )}
          </div>
        )}
      </Card>

      {canSuppress && (
        <Card title="Add numbers">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Paste as many as you like — one per line, or separated by commas. Numbers
            can be ten digits or the full +91 form; we work out the rest.
          </p>
          <form
            className="mt-3 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate(
                { numbers: parsed, source },
                { onSuccess: () => setPaste("") },
              );
            }}
          >
            <textarea
              value={paste}
              onChange={(e) => setPaste(e.target.value)}
              rows={6}
              spellCheck={false}
              aria-label="Numbers to suppress"
              placeholder={"9876543210\n+919876543211\n9876543212"}
              className="w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-sm dark:border-slate-700 dark:bg-slate-950"
            />

            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="dnc-source" className="text-sm text-slate-600 dark:text-slate-400">
                Reason
              </label>
              <select
                id="dnc-source"
                value={source}
                onChange={(e) => setSource(e.target.value as DncSource)}
                className="rounded-md border border-slate-200 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
              >
                {SOURCE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <span className="text-xs text-slate-500">
                {SOURCE_OPTIONS.find((o) => o.value === source)?.note}
              </span>
            </div>

            {/* Stopped here rather than at the API's 422: 2000 is the server's cap and
                a client who pasted 5,000 rows deserves to be told before they wait. */}
            {tooMany && (
              <p className="text-sm text-amber-700 dark:text-amber-400">
                That is {parsed.length.toLocaleString("en-IN")} numbers. Add up to{" "}
                {MAX_NUMBERS_PER_ADD.toLocaleString("en-IN")} at a time.
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={add.isPending || parsed.length === 0 || tooMany}
                className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
              >
                {add.isPending
                  ? "Adding…"
                  : parsed.length === 1
                    ? "Add 1 number"
                    : `Add ${parsed.length.toLocaleString("en-IN")} numbers`}
              </button>
              {parsed.length > 0 && !tooMany && (
                <span className="text-xs text-slate-500">
                  {parsed.length.toLocaleString("en-IN")} distinct{" "}
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
            <div className="mt-4 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <div className="grid gap-3 sm:grid-cols-3">
                <AddCount
                  value={add.data.added}
                  label="added"
                  hint="Suppressed from now on."
                />
                <AddCount
                  value={add.data.already_suppressed}
                  label="already on the list"
                  hint="Nothing to do — they were suppressed already."
                />
                <AddCount
                  value={add.data.malformed}
                  label="not a usable number"
                  hint="Skipped rather than guessed at."
                />
              </div>
              <p className="mt-3 text-xs text-slate-500">
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
          <span className="text-xs text-slate-500">
            Numbers are shown with the last two digits only.
          </span>
        }
      >
        {remove.error != null && (
          <div className="mb-3">
            <ProblemNotice error={remove.error} />
          </div>
        )}
        {entries.error != null && (
          <div className="mb-3">
            <ProblemNotice error={entries.error} onRetry={() => entries.refetch()} />
          </div>
        )}

        {entries.isLoading ? (
          <Skeleton rows={5} />
        ) : entries.data?.length ? (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {entries.data.map((entry) => (
              <EntryRow
                key={entry.id}
                entry={entry}
                canSuppress={canSuppress}
                removing={remove.isPending && remove.variables === entry.id}
                onRemove={() => remove.mutate(entry.id)}
              />
            ))}
          </ul>
        ) : entries.error != null ? null : (
          <EmptyState
            title="Nobody is suppressed yet"
            hint="Anyone who tells an agent to stop calling is added here automatically. You can also add numbers yourself."
          />
        )}
      </Card>
    </div>
  );
}

function AddCount({ value, label, hint }: { value: number; label: string; hint: string }) {
  return (
    <div>
      <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-50">
        {value.toLocaleString("en-IN")}
      </div>
      <div className="text-xs font-medium text-slate-700 dark:text-slate-300">{label}</div>
      <div className="mt-0.5 text-xs text-slate-500">{hint}</div>
    </div>
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
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm">
      <span className="font-mono tabular-nums text-slate-800 dark:text-slate-200">
        {entry.phone_masked}
      </span>
      {global && (
        // Shown, never removable: it is not this account's entry, and hiding it would
        // leave a client wondering why a number they can't find is never dialled.
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
          national list
        </span>
      )}
      <span className="text-xs text-slate-500">
        {source?.label ?? entry.source ?? "unknown reason"}
      </span>
      <span className="ml-auto text-xs text-slate-500">{formatIST(entry.added_at)}</span>
      {/* `removable` is the server's own `is_removable()` verdict, rendered rather than
          re-derived. No button appears where the API would answer dnc_global_entry or
          dnc_consumer_optout — the reason takes its place instead. */}
      {entry.removable ? (
        canSuppress ? (
          <button
            type="button"
            disabled={removing}
            onClick={onRemove}
            className="rounded-md border border-slate-200 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            {removing ? "Removing…" : "Remove"}
          </button>
        ) : null
      ) : (
        <span className="text-xs text-slate-400">
          {global ? "removed by operations only" : "opt-out — cannot be undone"}
        </span>
      )}
    </li>
  );
}
