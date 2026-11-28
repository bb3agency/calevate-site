"use client";

/**
 * `/c/{slug}/inbound/{id}/callers`: THE PEOPLE A LINE STILL OWES A CALL (W4.1, W4.2). Everyone
 * who rang it in the last week and was missed, hung up quickly, or asked for someone to call,
 * unless a later call reached them or the call was marked handled (`apps/api/inbound/today`).
 *
 * One button per person, "Call back", which opens Make a call on their last call: the
 * call-back door every call page uses (founder, 5 Nov 2026), so the dial gate's answer (Do
 * not call, calling hours, the per-person limits) is said there, never bypassed here. A
 * person already being rung, or with a call-back booked, shows that instead of the button.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { PhoneForwarded } from "lucide-react";

import { ChipGroup } from "@/components/arc/chip-group";
import { TEXT_ACTION } from "@/components/console/section";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { SECONDARY_BUTTON_SM, Skeleton, formatIST, formatPhone } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useInboundLine } from "@/lib/api/inboundLines";
import { useLineCallers, type OwedCaller } from "@/lib/api/inboundToday";
import { makeCallHref } from "@/lib/api/oneCall";
import { useClientRealm } from "@/lib/api/session";

type Show = "missed" | "asked" | "message";

const SHOW_CHIPS: { value: Show; label: string }[] = [
  { value: "missed", label: "Missed" },
  { value: "asked", label: "Asked for a call back" },
  { value: "message", label: "Left a message" },
];

const REASON_WORDS: Record<OwedCaller["reason"], string> = {
  not_answered: "Not answered",
  hung_up_early: "Hung up quickly",
  asked: "Asked for a call back",
  message: "Left you a message",
};

function kindOf(caller: OwedCaller): Show {
  return caller.reason === "asked" || caller.reason === "message" ? caller.reason : "missed";
}

function initialShow(param: string | null): Show | null {
  return param === "missed" || param === "asked" || param === "message" ? param : null;
}

export function LineCallersScreen({ slug, lineId }: { slug: string; lineId: string }) {
  const { session, href } = useClientRealm();
  const line = useInboundLine(session, lineId);
  const callers = useLineCallers(session, lineId);
  const dial = useWriteAccess(session, "leads:dispatch", "place calls");
  const params = useSearchParams();
  const [show, setShow] = useState<Show | null>(() => initialShow(params.get("show")));
  const back = { href: href(`/c/${slug}/inbound/${encodeURIComponent(lineId)}`), label: line.data?.name ?? "The line" };

  const all = callers.data?.callers ?? [];
  const shown = show ? all.filter((c) => kindOf(c) === show) : all;

  return (
    <div className="max-w-3xl space-y-5 pb-12">
      <PageHeader
        back={back}
        title="Call them back"
        description={
          <span className="inline-flex items-center gap-1">
            Callers from the last 7 days who are still waiting.
            <InfoTip label="who is listed">
              <p>Anyone reached since, or marked handled, drops off.</p>
              <p>A caller who hangs up before it answers may be missing.</p>
            </InfoTip>
          </span>
        }
      />
      {callers.isLoading ? (
        <Skeleton rows={3} label="Loading who is waiting" />
      ) : !callers.data ? (
        <EmptyState
          variant="error"
          message="Who is waiting did not load."
          error={callers.error}
          onRetry={() => void callers.refetch()}
        />
      ) : all.length === 0 ? (
        <EmptyState message="Nobody is waiting for a call back." />
      ) : (
        <>
          <ChipGroup
            mode="single"
            label="Show callers by why they are waiting"
            allLabel="Everyone"
            chips={SHOW_CHIPS}
            value={show}
            onChange={(next) => setShow(initialShow(next))}
          />
          {shown.length === 0 ? (
            <p className="text-body text-ink-muted">Nobody here right now.</p>
          ) : (
            <ul aria-label="Callers to call back" className="divide-y divide-line border-y border-line">
              {shown.map((caller) => (
                <CallerRow key={caller.call_id} slug={slug} caller={caller} dial={dial} />
              ))}
            </ul>
          )}
        </>
      )}
      <p>
        <Link href={href(`/c/${slug}/calls?inbound_line_id=${encodeURIComponent(lineId)}`)} className={TEXT_ACTION}>
          All its calls
        </Link>
      </p>
    </div>
  );
}

function CallerRow({
  slug,
  caller,
  dial,
}: {
  slug: string;
  caller: OwedCaller;
  dial: ReturnType<typeof useWriteAccess>;
}) {
  const { session, href } = useClientRealm();
  const number = formatPhone(caller.phone_e164);
  const who = caller.name ?? number;
  const tries = caller.tries > 1 ? ` · rang ${caller.tries} times` : "";
  return (
    <li className="grid grid-cols-1 gap-x-6 gap-y-2 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0 space-y-0.5">
        <Link
          href={href(`/c/${slug}/calls/${caller.call_id}`)}
          className="block rounded-sm text-[15px] font-semibold leading-snug text-ink [overflow-wrap:anywhere] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          {who}
        </Link>
        {caller.name && <p className="text-meta tabular-nums text-ink-muted">{number}</p>}
        <p className="text-meta text-ink-muted">
          {REASON_WORDS[caller.reason]} · <span className="tabular-nums">{formatIST(caller.at)}</span>
          {tries}
        </p>
      </div>
      <div className="flex sm:justify-end">
        {caller.calling ? (
          <p className="text-meta font-medium text-ink">Calling now</p>
        ) : caller.call_back_at ? (
          <p className="text-meta text-ink">
            Call-back booked <span className="tabular-nums">{formatIST(caller.call_back_at)}</span>
          </p>
        ) : dial.allowed ? (
          <Link
            href={href(makeCallHref(session.orgSlug, { call: caller.call_id }))}
            className={SECONDARY_BUTTON_SM}
            aria-label={`Call back ${who}`}
          >
            <PhoneForwarded aria-hidden className="h-4 w-4" />
            Call back
          </Link>
        ) : (
          <button type="button" disabled title={dial.reason ?? undefined} className={SECONDARY_BUTTON_SM}>
            <PhoneForwarded aria-hidden className="h-4 w-4" />
            Call back
          </button>
        )}
      </div>
    </li>
  );
}
