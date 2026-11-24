"use client";

/**
 * The Diagnose cards (founder, 24 Nov 2026), in the order an owner acts on them, for a
 * campaign's Improve tab or an Inbound line's Improve section: each is its own holder-agnostic
 * card, placed here once so both pages show the same set. They sit in the page's own grid.
 */

import type { Holder } from "@/lib/api/improve";

import { DropOffCard } from "./DropOffCard";
import { MistakesCard } from "./MistakesCard";
import { OpeningLossCard } from "./OpeningLossCard";
import { RefusalReasonsCard } from "./RefusalReasonsCard";
import { TestCallReviewCard } from "./TestCallReviewCard";

export function DiagnoseCards({
  slug,
  holder,
  canWrite,
  refusal,
}: {
  slug: string;
  holder: Holder;
  canWrite: boolean;
  refusal?: string;
}) {
  const props = { slug, holder, canWrite, refusal };
  return (
    <>
      <DropOffCard {...props} />
      <OpeningLossCard {...props} />
      <RefusalReasonsCard slug={slug} holder={holder} />
      <MistakesCard slug={slug} holder={holder} />
      <TestCallReviewCard slug={slug} holder={holder} />
    </>
  );
}
