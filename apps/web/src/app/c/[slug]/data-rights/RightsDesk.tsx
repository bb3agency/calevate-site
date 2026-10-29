"use client";

import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { Drawer } from "@/components/console/drawer";
import { StatusPill } from "@/components/console/statusPill";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatISTDate,
  istDateToInstant,
  type NoticeTone,
} from "@/components/ui";
import {
  useCloseRightsRequest,
  useLogRightsRequest,
  useRightsDesk,
  type RightsRequest,
  type RightsRequestCloseIn,
  type RightsRequestIn,
} from "@/lib/api/compliancePack";
import { type Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

import { WhyTip } from "../agreements/_ui/WhyTip";
import { DESK_COPY as COPY, daysLeftLine } from "./deskCopy";

type Kind = RightsRequest["kind"];
type Channel = RightsRequest["channel"];
type Outcome = RightsRequestCloseIn["outcome"];

const KINDS: Record<Kind, string> = {
  access: "See their data",
  correction: "Correct their data",
  erasure: "Erase their data",
  nomination: "Name someone for them",
  grievance: "A complaint",
};

const CHANNELS: Record<Channel, string> = {
  phone: "Phone",
  email: "Email",
  whatsapp: "WhatsApp",
  letter: "Letter",
  in_person: "In person",
  other: "Other",
};

/** What "answered" means for each kind: the first is the usual answer. */
const ANSWERS: Record<Kind, { outcome: Outcome; label: string }[]> = {
  access: [
    { outcome: "exported", label: "Sent them their data" },
    { outcome: "not_held", label: "We hold nothing for them" },
  ],
  correction: [
    { outcome: "corrected", label: "Corrected it" },
    { outcome: "not_held", label: "We hold nothing for them" },
  ],
  erasure: [{ outcome: "not_held", label: "We hold nothing for them" }],
  nomination: [{ outcome: "nominated", label: "Recorded who acts for them" }],
  grievance: [{ outcome: "explained", label: "Replied to them" }],
};

/**
 * The rights desk (D-943): requests a client's customers make about their own data, each
 * with the 90-day clock the DPDP Rules 2025 set. Primary job: see which request is due
 * next and answer it. Export and erasure are the page's own drawers; this list only says
 * which to open, and an erasure filed from a row answers that row.
 *
 * §52: loading, failed and empty are three branches; "no requests" is shown only when the
 * server said so.
 */
export function RightsDesk({
  session,
  canWrite,
  writeReason,
  onExport,
  onErase,
}: {
  session: Session;
  canWrite: boolean;
  writeReason: string | null;
  onExport: () => void;
  /** Opens the erasure drawer; the filed erasure answers `requestId`. */
  onErase: (requestId: string) => void;
}) {
  const desk = useRightsDesk(session);
  const [logging, setLogging] = useState(false);

  return (
    <section aria-labelledby="rights-desk-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="rights-desk-heading" className="text-section font-semibold text-ink">
          {COPY.heading}{" "}
          <WhyTip about="the 90-day clock" label="Why?">
            <p>{COPY.why}</p>
          </WhyTip>
        </h2>
        <button
          type="button"
          className={PRIMARY_BUTTON}
          onClick={() => setLogging(true)}
          disabled={!canWrite}
          title={writeReason ?? undefined}
        >
          {COPY.log}
        </button>
      </div>

      {desk.error ? (
        <ProblemNotice error={desk.error} />
      ) : !desk.data ? (
        <Skeleton rows={3} label={COPY.loading} />
      ) : desk.data.items.length === 0 ? (
        <p className="text-body text-ink-muted">{COPY.empty}</p>
      ) : (
        <>
          <p className="text-meta text-ink-muted">
            {COPY.counts(desk.data.open, desk.data.due_soon, desk.data.overdue)}
          </p>
          <ul className="divide-y divide-line rounded-card border border-line bg-surface">
            {desk.data.items.map((request) => (
              <DeskRow
                key={request.id}
                session={session}
                request={request}
                canWrite={canWrite}
                writeReason={writeReason}
                onExport={onExport}
                onErase={() => onErase(request.id)}
              />
            ))}
          </ul>
        </>
      )}

      <Drawer open={logging} onClose={() => setLogging(false)} title={COPY.log} width="md">
        <LogForm session={session} onDone={() => setLogging(false)} />
      </Drawer>
    </section>
  );
}

function clockTone(request: RightsRequest): NoticeTone {
  if (request.status !== "open") return "ok";
  if (request.overdue) return "stop";
  return request.due_soon ? "warn" : "neutral";
}

function DeskRow({
  session,
  request,
  canWrite,
  writeReason,
  onExport,
  onErase,
}: {
  session: Session;
  request: RightsRequest;
  canWrite: boolean;
  writeReason: string | null;
  onExport: () => void;
  onErase: () => void;
}) {
  const close = useCloseRightsRequest(session);
  useActionFeedback(close, { errorDisplay: "inline", successToast: "Saved" });
  const answers = lookup(ANSWERS, request.kind) ?? [];
  const isOpen = request.status === "open";
  const finish = (body: RightsRequestCloseIn) => close.mutate({ id: request.id, body });

  return (
    <li className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium text-ink">{lookup(KINDS, request.kind) ?? request.kind}</span>
        <span className="text-meta text-ink-muted">
          {COPY.asked(lookup(CHANNELS, request.channel) ?? request.channel, formatISTDate(request.received_at) ?? "—")}
        </span>
        <StatusPill tone={clockTone(request)}>
          {isOpen ? daysLeftLine(request.days_left ?? 0) : COPY.closed(request.status)}
        </StatusPill>
        <span className="text-meta text-ink-faint" title={COPY.codeWhy}>
          {COPY.code(request.subject_ref.slice(0, 8))}
        </span>
      </div>
      {isOpen && (
        <div className="flex flex-wrap gap-2">
          {request.kind === "access" && (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={onExport} disabled={!canWrite} title={writeReason ?? undefined}>
              {COPY.export}
            </button>
          )}
          {request.kind === "erasure" && (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={onErase} disabled={!canWrite} title={writeReason ?? undefined}>
              {COPY.erase}
            </button>
          )}
          {answers.map((answer) => (
            <button
              key={answer.outcome}
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!canWrite || close.isPending}
              title={writeReason ?? undefined}
              onClick={() => finish({ status: "answered", outcome: answer.outcome })}
            >
              {answer.label}
            </button>
          ))}
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!canWrite || close.isPending}
            title={writeReason ?? undefined}
            onClick={() => finish({ status: "refused", outcome: "identity_not_confirmed" })}
          >
            {COPY.refuseIdentity}
          </button>
        </div>
      )}
      {close.error && <ProblemNotice error={close.error} />}
    </li>
  );
}

function LogForm({ session, onDone }: { session: Session; onDone: () => void }) {
  const log = useLogRightsRequest(session);
  useActionFeedback(log, { errorDisplay: "inline", successToast: "Logged" });
  const [kind, setKind] = useState<Kind>("access");
  const [channel, setChannel] = useState<Channel>("phone");
  const [phone, setPhone] = useState("");
  const [asked, setAsked] = useState("");

  const submit = () => {
    if (!phone.trim()) return;
    const body: RightsRequestIn = {
      kind,
      channel,
      phone: phone.trim(),
      received_at: asked ? istDateToInstant(asked) : null,
    };
    log.mutate(body, {
      onSuccess: () => {
        setPhone("");
        onDone();
      },
    });
  };

  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label className="block">
        <span className={FIELD_LABEL}>{COPY.kindField}</span>
        <select className={FIELD} value={kind} onChange={(event) => setKind(event.target.value as Kind)}>
          {(Object.keys(KINDS) as Kind[]).map((value) => (
            <option key={value} value={value}>
              {KINDS[value]}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={FIELD_LABEL}>{COPY.channelField}</span>
        <select className={FIELD} value={channel} onChange={(event) => setChannel(event.target.value as Channel)}>
          {(Object.keys(CHANNELS) as Channel[]).map((value) => (
            <option key={value} value={value}>
              {CHANNELS[value]}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={FIELD_LABEL}>{COPY.phoneField}</span>
        <input
          className={FIELD}
          inputMode="tel"
          autoComplete="off"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          aria-required="true"
        />
      </label>
      <label className="block">
        <span className={FIELD_LABEL}>{COPY.askedField}</span>
        <input className={FIELD} type="date" value={asked} onChange={(event) => setAsked(event.target.value)} />
        <span className="mt-1 block text-xs text-ink-faint">{COPY.askedHint}</span>
      </label>
      {log.error && <ProblemNotice error={log.error} />}
      <button type="submit" className={PRIMARY_BUTTON} disabled={!phone.trim() || log.isPending}>
        {log.isPending ? COPY.logging : COPY.logSubmit}
      </button>
    </form>
  );
}
