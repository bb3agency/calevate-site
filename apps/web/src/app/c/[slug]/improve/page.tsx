"use client";

import { use } from "react";

import { CompareCard } from "@/components/improve/account/CompareCard";
import { ContactHealthCard } from "@/components/improve/account/ContactHealthCard";
import { CostPerResultCard } from "@/components/improve/account/CostPerResultCard";
import { FollowUpsCard } from "@/components/improve/account/FollowUpsCard";
import { KnowledgeGapsCard } from "@/components/improve/account/KnowledgeGapsCard";
import { MistakePatternsCard } from "@/components/improve/account/MistakePatternsCard";
import { NumberHealthCard } from "@/components/improve/account/NumberHealthCard";
import { PipFixesCard } from "@/components/improve/account/PipFixesCard";
import { WeeklySummaryCard } from "@/components/improve/account/WeeklySummaryCard";
import { PageHeader } from "@/components/console/pageHeader";
import { RestrictionNote } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

/**
 * `/c/{slug}/improve` (founder, 24 Nov 2026): what would make results better across every
 * campaign and line, or belongs to the account. Needs attention is the other half: what is
 * broken or blocked. Each card shows a pattern and links down to the campaign or line whose
 * own Improve holds the control; nothing here copies one.
 *
 * Order: the week in a paragraph first, then the comparison that names what works, then the
 * patterns that span holders, then counts that open other pages, then the feed of changes.
 */
export default function ImprovePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const { session } = useClientRealm();
  const me = useMe(session);
  if (me.data !== undefined && !me.data.permissions.includes("leads:read")) {
    return <RestrictionNote reason="Your role cannot see how your campaigns are doing." />;
  }
  return (
    <div className="max-w-5xl space-y-5 pb-12">
      <PageHeader description="What would make your results better, across all your campaigns and lines." />
      <WeeklySummaryCard />
      <CompareCard slug={slug} />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <NumberHealthCard slug={slug} />
        <MistakePatternsCard slug={slug} />
        <KnowledgeGapsCard slug={slug} />
        <CostPerResultCard />
        <FollowUpsCard slug={slug} />
        <ContactHealthCard slug={slug} />
      </div>
      <PipFixesCard slug={slug} />
    </div>
  );
}
