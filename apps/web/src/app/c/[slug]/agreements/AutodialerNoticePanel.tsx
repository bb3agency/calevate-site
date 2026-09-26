"use client";

/**
 * Where a sender records the autodialler notice their outbound depends on.
 *
 * WHY IT IS ON THIS SCREEN AND NOT A PAGE OF ITS OWN. The readiness list two cards below
 * names this as a blocker and tells the client to record it; for one release there was
 * nowhere to do that, and a blocker whose remedy is on another screen is only marginally
 * better. The refusal and the fix read as one thing here.
 *
 * WHY THE FORM IS NOT PREFILLED FROM THE LAST NOTICE. The three facts describe a letter
 * the client sent — a provider, a purpose and the date on it. Prefilling invites somebody
 * to re-submit last year's date without reading it, which is the one thing this record
 * must not contain. A withdrawal is the exception and is deliberate: it carries the same
 * three facts because the row has to say which notice was retracted.
 *
 * `effective` COMES FROM THE SERVER, never from comparing the date here. A notice dated
 * in the future is recorded, `notified`, and not yet carrying outbound — the same
 * predicate the dial gate uses decides that, in IST, and a browser comparing calendar
 * days would disagree with the gate for five and a half hours of every day.
 */

import { useState } from "react";

import {
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
} from "@/components/ui";
import {
  useAutodialerNotice,
  useRecordAutodialerNotice,
  type AutodialerNotice,
} from "@/lib/api/autodialerNotice";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

const FIELD =
  "mt-1 w-full touch:min-h-11 rounded-input border border-line bg-surface px-3 py-2 " +
  "text-sm text-ink focus:border-accent focus:outline-none";

function stateLine(notice: AutodialerNotice): {
  tone: "ok" | "warn";
  text: string;
} {
  if (!notice.recorded) {
    return {
      tone: "warn",
      text: "You have not recorded this notice yet, so no outgoing call will go out. Answering incoming calls is not affected.",
    };
  }
  if (notice.state === "withdrawn") {
    return {
      tone: "warn",
      text: "You withdrew this notice, so outgoing calls have stopped. Give the notice again and record it here to start them.",
    };
  }
  if (!notice.effective) {
    return {
      tone: "warn",
      text: "The date on your notice has not arrived yet. Nothing is wrong with your paperwork — outgoing calls start on that date.",
    };
  }
  return {
    tone: "ok",
    text: "Your notice is on file and your outgoing calls are not held up by it.",
  };
}

export function AutodialerNoticePanel() {
  const session = useClientSession();
  const notice = useAutodialerNotice(session);
  const record = useRecordAutodialerNotice(session);
  // Reading the notice is `org:read`; recording or withdrawing it is `org:manage`, which
  // staff do not hold. Before the hooks' early returns below.
  const write = useWriteAccess(session, "org:manage", "record or withdraw this notice");

  const [accessProvider, setAccessProvider] = useState("");
  const [objective, setObjective] = useState("");
  const [notifiedOn, setNotifiedOn] = useState("");

  if (notice.isPending)
    return <Skeleton rows={4} label="Loading your notice" />;
  if (notice.error) return <ProblemNotice error={notice.error} />;
  if (!notice.data) return null;

  const current = notice.data;
  const line = stateLine(current);
  const canSubmit =
    accessProvider.trim().length > 0 &&
    objective.trim().length > 0 &&
    notifiedOn.length > 0;

  return (
    <section className="rounded-card border border-line p-5">
      <h2 className="text-sm font-semibold text-ink">
        Your notice to your telecom access provider
      </h2>
      <p className="mt-1 text-sm text-ink-muted">
        Every outgoing call we place for you is dialled automatically. The rules
        put one duty on the business whose calls they are: tell your own telecom
        operator, in writing and before the calls start, that you use an
        automated dialler and what the calls are for. That letter is yours to
        send — we cannot send it for you, because the operator holds your
        business to it, not us. Send it, then record it here.
      </p>

      <NoticeBox tone={line.tone} className="mt-4">
        {line.text}
      </NoticeBox>

      {current.recorded && (
        <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-ink-muted">Operator you told</dt>
            <dd className="text-ink">{current.access_provider}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">What the calls are for</dt>
            <dd className="text-ink">{current.objective}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Date on the letter</dt>
            <dd className="text-ink">{current.notified_on}</dd>
          </div>
        </dl>
      )}

      {write.reason && (
        <div className="mt-4">
          <RestrictionNote reason={write.reason} />
        </div>
      )}

      <form
        noValidate
        className="mt-5"
        onSubmit={(event) => {
          event.preventDefault();
          record.mutate({ accessProvider, objective, notifiedOn });
        }}
      >
        {/* A disabled <fieldset> closes every field and both buttons at once. */}
        <fieldset disabled={!write.allowed} className="min-w-0 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="text-ink">Which operator did you tell?</span>
              <input
                className={FIELD}
                value={accessProvider}
                onChange={(event) => setAccessProvider(event.target.value)}
                placeholder="The operator that supplies your outgoing line"
              />
            </label>
            <label className="block text-sm">
              <span className="text-ink">What is the date on your letter?</span>
              <input
                className={FIELD}
                type="date"
                value={notifiedOn}
                onChange={(event) => setNotifiedOn(event.target.value)}
              />
            </label>
          </div>
          <label className="block text-sm">
            <span className="text-ink">
              What did you tell them the calls are for?
            </span>
            <input
              className={FIELD}
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              placeholder="In your own words, as your letter puts it"
            />
          </label>

          {record.error && <ProblemNotice error={record.error} />}

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              className={PRIMARY_BUTTON_SM}
              disabled={!canSubmit || record.isPending}
            >
              {record.isPending ? "Recording…" : "Record this notice"}
            </button>
            {current.recorded && current.state === "notified" && (
              <button
                type="button"
                className="text-sm text-ink-muted underline"
                disabled={record.isPending}
                onClick={() =>
                  record.mutate({
                    // A withdrawal names the notice it retracts, so it carries that notice's
                    // own three facts rather than whatever is typed in the form above.
                    accessProvider: current.access_provider ?? "",
                    objective: current.objective ?? "",
                    notifiedOn: current.notified_on ?? "",
                    withdraw: true,
                  })
                }
              >
                I have withdrawn this notice
              </button>
            )}
          </div>
        </fieldset>
      </form>
    </section>
  );
}
