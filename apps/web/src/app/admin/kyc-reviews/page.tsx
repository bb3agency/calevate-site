"use client";

import Link from "next/link";

import { Card, ProblemNotice, Skeleton } from "@/components/ui";
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
    <Card title="Waiting for review">
      {items.length === 0 ? (
        <p className="text-sm text-ink-muted">Nothing is waiting for review.</p>
      ) : (
        <ul className="divide-y divide-line text-sm">
          {items.map((item) => (
            <li key={item.tenant_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <Link href={`/admin/tenants/${item.tenant_id}/kyc`} className="font-semibold underline">
                {item.name}
              </Link>
              <span className="text-ink-muted">
                {item.kyc_path === "digilocker" ? "DigiLocker" : "Document review"}
                {item.owner_id_type ? ` · ${lookup(ID_TYPE_LABEL, item.owner_id_type) ?? item.owner_id_type}` : ""}
                {item.digilocker_required ? " · DigiLocker required" : ""}
                {item.submitted_at ? ` · sent ${new Date(item.submitted_at).toLocaleDateString("en-IN")}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
