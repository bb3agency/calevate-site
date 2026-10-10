"use client";

import Link from "next/link";

import { ADMIN_PAGE_WIDE, HAIRLINE_LIST, ROW_HOVER } from "@/components/admin/kit";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import { useKycReviewQueue } from "@/lib/api/kycReview";

const ID_TYPE_LABEL: Record<string, string> = { aadhaar: "Aadhaar", pan: "PAN" };

/**
 * Clients whose identity verification waits for a reviewer (D-692), oldest submission
 * first. Each row opens the client's KYC page, where the files are reviewed and the
 * decision recorded. No `<h1>`: the shell takes the title from the nav list.
 */
export default function KycReviewsPage() {
  const queue = useKycReviewQueue();
  if (queue.isLoading) return <Skeleton rows={6} />;
  if (!queue.data) {
    return (
      <ProblemNotice
        error={queue.error ?? new Error("The review queue did not load.")}
        onRetry={() => void queue.refetch()}
      />
    );
  }
  const items = queue.data;
  return (
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader description="Identity checks waiting for a reviewer, oldest first. Open one to see the files and decide." />
      {items.length === 0 ? (
        <EmptyState message="Nothing is waiting for review." />
      ) : (
        <ul aria-label="Waiting for review" className={HAIRLINE_LIST}>
          {items.map((item) => (
            <li key={item.tenant_id}>
              <Link
                href={`/admin/tenants/${item.tenant_id}/kyc`}
                className={`flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand sm:px-2 touch:min-h-11 ${ROW_HOVER}`}
              >
                <span className="text-body font-medium text-ink">{item.name}</span>
                <span className="text-meta text-ink-muted">
                  {item.kyc_path === "digilocker" ? "DigiLocker" : "Document review"}
                  {item.owner_id_type ? ` · ${lookup(ID_TYPE_LABEL, item.owner_id_type) ?? item.owner_id_type}` : ""}
                  {item.digilocker_required ? " · DigiLocker required" : ""}
                  {item.submitted_at ? ` · sent ${formatIST(item.submitted_at)}` : ""}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
