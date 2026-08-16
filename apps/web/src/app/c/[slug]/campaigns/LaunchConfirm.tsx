"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Rocket } from "lucide-react";

import {
  DANGER_BUTTON,
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
  formatCount,
} from "@/components/ui";

/**
 * The gate in front of the one client action that dials real phone numbers.
 *
 * ## Why this exists
 *
 * Launching was a bare `<button onClick={() => launch.mutate()}>` sitting under the
 * sentence "Everything checks out." One press, no restatement, no second step — on the
 * client action with the largest irreversible blast radius in the product. A placed call
 * cannot be recalled, it is made under TRAI to an Indian subscriber, and the campaign it
 * belongs to may hold thousands of them.
 *
 * It was also out of step with every comparable control this repo already ships: bulk
 * lead edit is two-step plus type-the-count (`leads/BulkActionBar.tsx`), DPDP erasure
 * types `ERASE`, the big red switch has a consequences panel plus a typed reason plus a
 * typed word, and global DNC release types `RELEASE`. Launching was the only one with no
 * gate at all.
 *
 * And the server had already assumed otherwise. `campaigns/service.py::launch_campaign`
 * says the scrub runs at launch *"so the 'N contacts will be dialled' number **the client
 * confirms** is true"* — a sentence about a confirmation that did not exist.
 *
 * ## The shape, and why it is `BulkActionBar`'s and not a new one
 *
 * Consequences ABOVE the control, decision made before the click — the ops
 * big-red-switch idiom, which the bulk bar already borrowed. Two ways of confirming one
 * class of thing is a defect even when both work (CLAUDE.md), so this is the same three
 * beats: a review button, a panel that restates what will happen, and a danger button
 * that is dead until the count has been typed.
 *
 * **The count is what must be typed, not a fixed word**, and the bulk bar's reasoning
 * carries over exactly: a fixed word proves the person meant to press the button, and the
 * risk here is not the button, it is the number beside it. Typing "1240" cannot be done
 * without reading it.
 *
 * It differs from `BulkActionBar` in one place: there is **no size threshold**. The bulk
 * bar types the count only above 25 rows, on the argument that a ceremony everybody
 * performs on three rows is a ceremony nobody reads on twelve hundred — and that argument
 * is about an action performed many times a day on a table. A campaign is launched once,
 * ever, and every launch is irreversible whatever the count. So the ceremony is never
 * worn out by repetition and it is always proportionate.
 *
 * ## What this panel may and may not state
 *
 * `contacts` is `ProgressOut.total` — the server's count of rows on this campaign — and
 * when it is `undefined` **there is no review to offer**. §52 applies to a confirmation
 * more than anywhere else: a manufactured `0` under "this will call N people" is the one
 * number nobody would question.
 *
 * That branch is a CONTRACT, not a reachable state from today's only call site: the
 * "Before you launch" card is itself gated on `status`, which is derived from the same
 * `progress` read, so a campaigns page that cannot read the progress renders no launch
 * card at all (`campaignLaunch.test.tsx` pins that). It is written here rather than
 * pushed onto the caller as a required prop because the rule belongs to the control —
 * "a launch must be able to say how many people it will call" is true of every caller,
 * and a required `number` would invite the next one to supply a `0`.
 *
 * Two things this panel has to restate were WRITE-ONLY until `ProgressOut` gained them:
 * **the campaign's own calling window** and **the number it dials from**. Both were set
 * in the create form, held as local state, and returned by no endpoint — so the panel
 * asking a client to authorise thousands of calls could not say when they would go out or
 * what would appear on the handset. Both are now read back, and both are stated exactly
 * as the server reports them:
 *
 * - `callingHours` is the campaign's OWN NARROWING, `null` when it chose none. The
 *   platform's 9am–9pm IST bound is stated unconditionally either way, because it is true
 *   of every campaign; a narrowed window is stated IN ADDITION, never instead.
 * - `numberE164` is `null` when the campaign has no number of its own, and that is said
 *   in words rather than left blank — "the platform picks one" and "we could not read it"
 *   are different facts to somebody deciding whether to authorise the calls.
 */
export function LaunchConfirm({
  contacts,
  concurrency,
  callingHours,
  numberE164,
  canWrite,
  writeReason,
  pending,
  onLaunch,
}: {
  /** `ProgressOut.total` — `undefined` while it is unknown, and then there is no review. */
  contacts: number | undefined;
  /** `ProgressOut.concurrency`, when the progress read has answered. */
  concurrency: number | undefined;
  /** `ProgressOut.calling_hours` — the campaign's own narrowing, null when it has none. */
  callingHours: { start: string; end: string } | null | undefined;
  /** `ProgressOut.number_e164` — null when this campaign dials from no number of its own. */
  numberE164: string | null | undefined;
  canWrite: boolean;
  /** `undefined` when nothing refuses — the page's own `refusal`, unchanged. */
  writeReason: string | undefined;
  pending: boolean;
  onLaunch: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");

  // A changed count retracts a confirmation in progress — the bulk bar's rule, and it
  // matters more here because this screen POLLS: contacts can be added in another tab
  // while the panel is open, and a person must not spend a confirmation of 40 on 4,000.
  useEffect(() => {
    setConfirming(false);
    setTyped("");
  }, [contacts]);

  if (contacts === undefined) {
    return (
      <p className="text-sm text-ink-muted">
        We could not read how many contacts this campaign has, so it cannot be
        launched from here yet — a launch has to be able to say how many people
        it will call.
      </p>
    );
  }

  const people = contacts === 1 ? "person" : "people";
  const armed = canWrite && typed.trim() === String(contacts);

  if (!confirming) {
    return (
      <div className="space-y-3">
        <button
          type="button"
          title={writeReason}
          disabled={!canWrite || pending}
          onClick={() => setConfirming(true)}
          className={PRIMARY_BUTTON}
        >
          <Rocket aria-hidden className="h-4 w-4" />
          Review this launch
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
        <p className="flex items-start gap-2 font-semibold">
          <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            This starts calling {formatCount(contacts)} {people}.
          </span>
        </p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>
            Calls go out between 9am and 9pm IST only
            {callingHours ? (
              <>
                , and this campaign narrows that further to{" "}
                <strong>
                  {callingHours.start}&ndash;{callingHours.end} IST
                </strong>
              </>
            ) : null}
            . Each one opens with your agent&rsquo;s recording-and-AI notice.
          </li>
          <li>
            {numberE164 ? (
              <>
                They will show <strong>{numberE164}</strong> on the handset.
              </>
            ) : (
              "This campaign has no number of its own, so calls go out on whichever of your numbers is available."
            )}
          </li>
          {concurrency !== undefined && (
            <li>
              Up to {formatCount(concurrency)} calls run at the same time.
            </li>
          )}
          <li>
            Anyone already on your do-not-call list is dropped as it starts, and
            we tell you how many.
          </li>
          <li>
            <strong>A call that has been placed cannot be recalled.</strong> You
            can pause the campaign, which stops the calls that have not been
            made yet.
          </li>
        </ul>
        <label className="mt-3 block">
          <span className={FIELD_LABEL}>Type {contacts} to confirm</span>
          <input
            aria-label={`Type ${contacts} to confirm`}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            inputMode="numeric"
            className={FIELD}
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          title={writeReason}
          disabled={!armed || pending}
          onClick={onLaunch}
          className={DANGER_BUTTON}
        >
          <Rocket aria-hidden className="h-4 w-4" />
          {pending ? "Launching…" : `Call ${formatCount(contacts)} ${people}`}
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className={SECONDARY_BUTTON}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
