"use client";

import { PageHeader } from "@/components/console/pageHeader";

import { ChartsSection } from "./sections/charts";
import { ContentSection } from "./sections/content";
import { FeedbackSection } from "./sections/feedback";
import { InputsSection } from "./sections/inputs";
import { OverlaysSection } from "./sections/overlays";
import { StructureSection } from "./sections/structure";

const CONTENTS = [
  { id: "feedback", label: "Feedback" },
  { id: "overlays", label: "Overlays" },
  { id: "inputs", label: "Inputs" },
  { id: "charts", label: "Charts" },
  { id: "structure", label: "Structure" },
  { id: "content", label: "Content" },
] as const;

/**
 * The living kit (docs/design/KIT.md): every shared component in every state it has, with
 * real props. Admin realm only — it is the reference the screen lanes build from and the
 * page the browser checks run against, never something a client reaches.
 */
export function KitScreen() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Interface kit"
        description="Every shared component in every state. Screens are built from these and nothing else."
      />
      <nav aria-label="Kit sections" className="flex flex-wrap gap-2">
        {CONTENTS.map((section) => (
          <a
            key={section.id}
            href={`#${section.id}`}
            className="inline-flex min-h-9 items-center rounded-md border border-line bg-surface px-3 text-meta font-medium text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
          >
            {section.label}
          </a>
        ))}
      </nav>
      <FeedbackSection />
      <OverlaysSection />
      <InputsSection />
      <ChartsSection />
      <StructureSection />
      <ContentSection />
    </div>
  );
}
