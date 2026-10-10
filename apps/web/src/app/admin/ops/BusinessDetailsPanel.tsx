"use client";

import { Section } from "@/components/console/section";
import { NoticeBox, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { useEngineBusinessDetails, type EngineBusinessDetails } from "@/lib/api/numbers";
import { lookup } from "@/lib/lookup";

/** Each status in the operator's words (`phone-numbers/get-business-details.md:425-436`). */
const STATUS_COPY: Record<string, string> = {
  none: "Nothing sent yet",
  draft: "Started, never sent",
  submitted: "Being checked",
  accepted: "Approved",
  rejected: "Rejected — correct it and send again",
  suspended: "Approval withdrawn",
  expired: "Lapsed — send again",
  unknown: "A status we do not recognise",
};

/**
 * The voice platform's business-details application (D-691). India issues a number only to
 * a business it has approved, so a lapsed application means no new number can be rented.
 * Read live on every visit and read-only: the details are sent in the platform's console.
 * The daily number check alarms `engine_business_details_lapsed` on a rejected, suspended
 * or expired application. Renders nothing on a deployment whose numbers are not the
 * platform's.
 */
export function BusinessDetailsPanel() {
  const details = useEngineBusinessDetails();

  if (details.isLoading) {
    return (
      <Section title="Platform account: business details">
        <Skeleton rows={2} />
      </Section>
    );
  }
  if (details.error) {
    return (
      <Section title="Platform account: business details">
        <ProblemNotice error={details.error} onRetry={() => void details.refetch()} />
      </Section>
    );
  }
  const data = details.data;
  if (!data || !data.available) return null;
  return <BusinessDetailsCard data={data} />;
}

function BusinessDetailsCard({ data }: { data: EngineBusinessDetails }) {
  const status = data.status ?? "unknown";
  return (
    <Section
      title={`Platform account: ${data.platform ?? "voice platform"} business details`}
      info={
        <p>
          The platform (developer) account&apos;s own application, which India requires before a
          number is rented there. Each client&apos;s own workspace has its own, on that client&apos;s
          Numbers page. Send or correct this one in the voice platform&apos;s own console, on its
          Phone Numbers page; this panel only reads it.
        </p>
      }
    >
      <dl className="grid gap-x-6 gap-y-2 text-body sm:grid-cols-[max-content_1fr]">
        <dt className="text-ink-muted">Status</dt>
        <dd className="font-medium text-ink">{lookup(STATUS_COPY, status) ?? STATUS_COPY.unknown}</dd>
        <dt className="text-ink-muted">Can rent a number</dt>
        <dd className="text-ink">{data.can_rent ? "Yes" : "No"}</dd>
        {data.business_name && (
          <>
            <dt className="text-ink-muted">Sent as</dt>
            <dd className="text-ink">{data.business_name}</dd>
          </>
        )}
        {data.submitted_at && (
          <>
            <dt className="text-ink-muted">Last sent</dt>
            <dd className="text-ink">{formatIST(data.submitted_at)}</dd>
          </>
        )}
      </dl>
      {data.lapsed && (
        <div className="mt-3">
          <NoticeBox tone="warn">
            No new number can be rented until this is approved again.
            {data.review_note ? ` The review says: ${data.review_note}` : ""}
          </NoticeBox>
        </div>
      )}
    </Section>
  );
}
