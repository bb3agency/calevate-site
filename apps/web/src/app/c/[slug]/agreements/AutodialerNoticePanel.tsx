"use client";

/**
 * Where a sender records the autodialler notice their outbound depends on.
 *
 * WHY IT IS ON THIS SCREEN AND NOT A PAGE OF ITS OWN. The readiness list two cards below
 * names this as a blocker and tells the client to record it; for one release there was
 * nowhere to do that, and a blocker whose remedy is on another screen is only marginally
 * better. The refusal and the fix read as one thing here.
 *
 * WHY THE FORM IS NOT PREFILLED FROM THE LAST NOTICE. The facts describe a letter the
 * client sent — a provider, a purpose, the numbers it names and the date on it.
 * Prefilling invites somebody to re-submit last year's date without reading it, which is
 * the one thing this record must not contain. A withdrawal is the exception and is
 * deliberate: it carries the same facts because the row has to say which notice was
 * retracted. The one thing offered is the numbers the calls come from — those on the
 * notice on file and the agent numbers it misses — as a button the client presses, because
 * those come from this account and not from a letter.
 *
 * `effective` COMES FROM THE SERVER, never from comparing the date here. A notice dated
 * in the future is recorded, `notified`, and not yet carrying outbound — the same
 * predicate the dial gate uses decides that, in IST, and a browser comparing calendar
 * days would disagree with the gate for five and a half hours of every day.
 */

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Section, TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import {
  FIELD,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
} from "@/components/ui";
import {
  parseDeclaredNumbers,
  useAutodialerNotice,
  useRecordAutodialerNotice,
  type AutodialerNotice,
} from "@/lib/api/autodialerNotice";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import type { LegalReadiness } from "@/lib/api/agreements";

import { useAutodialerNoticeCopilot, type NoticeDraft } from "./copilot";

function stateLine(notice: AutodialerNotice): {
  tone: "ok" | "warn";
  text: string;
} {
  if (!notice.recorded) {
    return {
      tone: "warn",
      text: "Not recorded yet, so no outgoing call will go out.",
    };
  }
  if (notice.state === "withdrawn") {
    return {
      tone: "warn",
      text: "You withdrew this notice, so outgoing calls have stopped. Give the notice again and record it to start them.",
    };
  }
  if (!notice.effective) {
    return {
      tone: "warn",
      text: "The date on your notice has not arrived yet. Outgoing calls start on that date.",
    };
  }
  if (notice.undeclared_clis.length > 0) {
    return {
      tone: "warn",
      text: "Your notice does not name every number your agents call from, so calls from the missing numbers will not go out. Add them to your letter, send it to your operator, and record it here again.",
    };
  }
  return {
    tone: "ok",
    text: "Your notice is on file and your outgoing calls are not held up by it.",
  };
}

/**
 * What "Add my agents' numbers" puts in the box: what is typed, then every number the
 * notice on file names, then the agent numbers it misses.
 *
 * The notice on file as well as the missing ones, because the LATEST notice is the whole
 * declaration — the dial gate and readiness read nothing older. Adding only
 * `undeclared_clis` meant recording the result declared the new number and dropped the
 * ones already declared, so their calls were refused next.
 *
 * Compared by digits so "+91 98480 22338" typed and "+919848022338" from the server are
 * one entry; what is typed keeps its spelling, since the server normalises it anyway.
 */
function withEveryCallingNumber(typed: string[], notice: AutodialerNotice): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const number of [...typed, ...notice.declared_clis, ...notice.undeclared_clis]) {
    const key = number.replace(/[^\d]/g, "");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(number);
  }
  return out;
}

export function AutodialerNoticePanel({
  readiness,
  openRequest = 0,
}: {
  readiness?: LegalReadiness;
  /** Bumped by the readiness list's "Record it": open the form and move to it. */
  openRequest?: number;
}) {
  const session = useClientSession();
  const notice = useAutodialerNotice(session);
  const record = useRecordAutodialerNotice(session);
  // Reading the notice is `org:read`; recording or withdrawing it is `org:manage`, which
  // staff do not hold. Before the hooks' early returns below.
  const write = useWriteAccess(session, "org:manage", "record or withdraw this notice");

  const [accessProvider, setAccessProvider] = useState("");
  const [objective, setObjective] = useState("");
  const [notifiedOn, setNotifiedOn] = useState("");
  const [numbers, setNumbers] = useState("");
  // Closed until asked for: the panel's job on arrival is to say where the notice stands.
  const [formOpen, setFormOpen] = useState(false);
  // A new "Record it" press opens the form, adjusted while rendering rather than in an
  // effect so the form is never painted closed for a frame after the press.
  const [seenRequest, setSeenRequest] = useState(0);
  if (openRequest !== seenRequest) {
    setSeenRequest(openRequest);
    setFormOpen(true);
  }

  if (notice.isPending)
    return <Skeleton rows={4} label="Loading your notice" />;
  if (notice.error) return <ProblemNotice error={notice.error} />;
  if (!notice.data) return null;

  return (
    <NoticeForm
      readiness={readiness}
      current={notice.data}
      canWrite={write.allowed}
      writeReason={write.reason}
      record={record}
      draft={{ accessProvider, objective, notifiedOn, numbers }}
      formOpen={formOpen}
      setFormOpen={setFormOpen}
      focusRequest={seenRequest}
      setDraft={(patch) => {
        // The assistant fills a closed form too, so whatever it wrote is on screen.
        setFormOpen(true);
        if (patch.accessProvider !== undefined) setAccessProvider(patch.accessProvider);
        if (patch.objective !== undefined) setObjective(patch.objective);
        if (patch.notifiedOn !== undefined) setNotifiedOn(patch.notifiedOn);
        if (patch.numbers !== undefined) setNumbers(patch.numbers);
      }}
    />
  );
}

/**
 * The panel over a notice that has loaded. Split from the reader so the assistant's
 * declaration (a hook) is made only once there is a notice to describe.
 */
function NoticeForm({
  readiness,
  current,
  canWrite,
  writeReason,
  record,
  draft,
  setDraft,
  formOpen,
  setFormOpen,
  focusRequest,
}: {
  formOpen: boolean;
  setFormOpen: (open: boolean) => void;
  /** Changes on each "Record it": move to the form's first field. */
  focusRequest: number;
  readiness?: LegalReadiness;
  current: AutodialerNotice;
  canWrite: boolean;
  writeReason: string | null;
  record: ReturnType<typeof useRecordAutodialerNotice>;
  draft: NoticeDraft;
  setDraft: (patch: Partial<NoticeDraft>) => void;
}) {
  const { accessProvider, objective, notifiedOn, numbers } = draft;
  const setAccessProvider = (v: string) => setDraft({ accessProvider: v });
  const setObjective = (v: string) => setDraft({ objective: v });
  const setNotifiedOn = (v: string) => setDraft({ notifiedOn: v });
  const setNumbers = (v: string) => setDraft({ numbers: v });
  useAutodialerNoticeCopilot({ readiness, notice: current, draft, apply: setDraft, canWrite });

  const firstField = useRef<HTMLInputElement>(null);
  // After the opened form has rendered: bring it into view and put the caret in it.
  useEffect(() => {
    if (focusRequest === 0) return;
    const field = firstField.current;
    if (!field) return;
    field.scrollIntoView?.({ block: "center", behavior: "smooth" });
    field.focus({ preventScroll: true });
  }, [focusRequest]);

  const line = stateLine(current);
  const declared = parseDeclaredNumbers(numbers);
  const canSubmit =
    accessProvider.trim().length > 0 &&
    objective.trim().length > 0 &&
    notifiedOn.length > 0 &&
    declared.length > 0;

  return (
    <div id="autodialer-notice" className="scroll-mt-4">
      <Section
        title="Your notice to your telecom access provider"
        description="Your written notice that your calls are automated, what they are for, and the numbers they come from."
        info={
          <>
            <p>
              Every outgoing call we place for you is dialled automatically. TRAI&apos;s
              rules put one duty on the business whose calls they are: tell your telecom
              operator, in writing and before the calls start, that you use an automated
              dialler and what the calls are for.
            </p>
            <p>
              The notice must also name every number the calls come from. It is yours to
              send. We cannot send it for you, because the operator holds your business to
              it, not us.
            </p>
          </>
        }
      >

        <NoticeBox tone={line.tone} className="mt-4">
          {line.text}
        </NoticeBox>

        {current.recorded && (
          <SettingRows className="mt-4 border-y border-line">
            <SettingRow label="Operator you told" value={current.access_provider} />
            <SettingRow label="What the calls are for" value={current.objective} />
            <SettingRow label="Date on the letter" value={current.notified_on} />
            <SettingRow
              label="Numbers it names"
              value={current.declared_clis.length > 0 ? current.declared_clis.join(", ") : "None"}
            />
          </SettingRows>
        )}

        {current.undeclared_clis.length > 0 && (
          <div className="mt-4 text-body">
            <p className="text-ink">
              Your agents call from these numbers, which your notice does not name:
            </p>
            <ul className="mt-1 list-disc pl-5 text-ink">
              {current.undeclared_clis.map((number) => (
                <li key={number}>{number}</li>
              ))}
            </ul>
          </div>
        )}

        {writeReason && (
          <div className="mt-4">
            <RestrictionNote reason={writeReason} />
          </div>
        )}

        <button
          type="button"
          className={`${TEXT_ACTION} mt-4`}
          aria-expanded={formOpen}
          aria-controls="autodialer-notice-form"
          onClick={() => setFormOpen(!formOpen)}
        >
          {current.recorded ? "Record a new notice" : "Record your notice"}
          <ChevronDown
            aria-hidden
            className={`h-4 w-4 transition-transform duration-(--duration-fast) motion-reduce:transition-none ${formOpen ? "rotate-180" : ""}`}
          />
        </button>

        <form
          id="autodialer-notice-form"
          hidden={!formOpen}
          aria-label={current.recorded ? "Record a new notice" : "Record your notice"}
          noValidate
          className="mt-4"
          onSubmit={(event) => {
            event.preventDefault();
            record.mutate({
              accessProvider,
              objective,
              notifiedOn,
              declaredClis: declared,
            });
          }}
        >
          {/* A disabled <fieldset> closes every field and both buttons at once. */}
          <fieldset disabled={!canWrite} className="min-w-0 space-y-4">
            <label className="block max-w-md">
              <span className={FIELD_LABEL}>Which operator did you tell?</span>
              <input
                ref={firstField}
                className={FIELD}
                value={accessProvider}
                onChange={(event) => setAccessProvider(event.target.value)}
                placeholder="The operator that supplies your outgoing line"
              />
            </label>
            <label className="block max-w-[12rem]">
              <span className={FIELD_LABEL}>What is the date on your letter?</span>
              <input
                className={FIELD}
                type="date"
                value={notifiedOn}
                onChange={(event) => setNotifiedOn(event.target.value)}
              />
            </label>
            <label className="block">
              <span className={FIELD_LABEL}>What did you tell them the calls are for?</span>
              <input
                className={FIELD}
                value={objective}
                onChange={(event) => setObjective(event.target.value)}
                placeholder="In your own words, as your letter puts it"
              />
            </label>
            <div>
              <label className="block">
                <span className={FIELD_LABEL}>
                  Which numbers did your letter say the calls come from?
                </span>
                <textarea
                  className={FIELD}
                  rows={3}
                  value={numbers}
                  onChange={(event) => setNumbers(event.target.value)}
                  placeholder="One per line, for example +91 98480 22338 or a 140 or 160 number"
                />
              </label>
              {current.undeclared_clis.length > 0 && (
                <button
                  type="button"
                  className={`${TEXT_ACTION} mt-1`}
                  onClick={() => setNumbers(withEveryCallingNumber(declared, current).join("\n"))}
                >
                  {"Add my agents' numbers"}
                </button>
              )}
            </div>

            {record.error && <ProblemNotice error={record.error} />}

            <div className="flex flex-wrap items-center justify-end gap-x-5 gap-y-3 pt-2">
              {current.recorded && current.state === "notified" && (
                <button
                  type="button"
                  className={`${TEXT_ACTION_DANGER} mr-auto`}
                  disabled={record.isPending}
                  onClick={() =>
                    record.mutate({
                      // A withdrawal names the notice it retracts, so it carries that notice's
                      // own three facts rather than whatever is typed in the form above.
                      accessProvider: current.access_provider ?? "",
                      objective: current.objective ?? "",
                      notifiedOn: current.notified_on ?? "",
                      declaredClis: current.declared_clis,
                      withdraw: true,
                    })
                  }
                >
                  I have withdrawn this notice
                </button>
              )}
              <button
                type="submit"
                className={PRIMARY_BUTTON}
                disabled={!canSubmit || record.isPending}
              >
                {record.isPending ? "Recording…" : "Record this notice"}
              </button>
            </div>
          </fieldset>
        </form>
      </Section>
    </div>
  );
}
