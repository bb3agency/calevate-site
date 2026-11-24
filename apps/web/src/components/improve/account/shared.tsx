"use client";

/**
 * What the account Improve page's cards share: the one `GET /v1/improve` read, drawn by each
 * card as loading, failed, then its own body (`WithAccountImprove`), and the card props.
 * The read is one query, so the cards on a page make one request between them.
 */

import type { ReactNode } from "react";

import { ProblemNotice, Skeleton } from "@/components/ui";
import { useAccountImprove, type AccountImprove } from "@/lib/api/accountImprove";
import { useClientRealm } from "@/lib/api/session";

export type AccountCardProps = {
  slug: string;
};

export function WithAccountImprove({
  label,
  children,
}: {
  /** What is being read, for the skeleton's accessible name. */
  label: string;
  children: (data: AccountImprove) => ReactNode;
}) {
  const { session } = useClientRealm();
  const read = useAccountImprove(session);
  if (read.isLoading) return <Skeleton rows={3} label={label} />;
  if (!read.data) return <ProblemNotice error={read.error} onRetry={() => void read.refetch()} />;
  return <>{children(read.data)}</>;
}

/** "1 campaign" / "3 campaigns and lines", for a count of holders. */
export function holdersWord(n: number): string {
  return n === 1 ? "1 campaign or line" : `${n} campaigns and lines`;
}

/** The muted one-liner every empty and too-few state uses. */
export function Quiet({ children }: { children: ReactNode }) {
  return <p className="text-meta text-ink-muted">{children}</p>;
}
