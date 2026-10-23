"use client";

import { useState } from "react";

import { Accordion } from "@/components/arc/accordion";
import { ChangelogFeed } from "@/components/arc/changelog-feed";
import { ExpandableText } from "@/components/arc/expandable-text";
import type { FeedbackStatus } from "@/components/arc/feedback";
import { JsonViewer } from "@/components/arc/json-viewer";
import { ScriptEditor, scriptOverBudget, unknownVariables, type ScriptEditorSection } from "@/components/arc/script-editor";
import { TextShimmer } from "@/components/arc/text-shimmer";
import { TierComparison } from "@/components/arc/tier-comparison";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { CopyButton } from "@/components/interior/copy-button";
import { ApiProblem } from "@/lib/api/client";
import { PRIMARY_BUTTON } from "@/components/ui";

import { KitDemo, KitGrid, KitSection } from "../kitLayout";

const VARIABLES = [
  { key: "caller_name", label: "Caller's name", sample: "Priya" },
  { key: "business_name", label: "Business name", sample: "Sri Lakshmi Sweets" },
  { key: "last_order", label: "Last order", sample: "two kilos of kaju katli" },
];

const SCRIPT: ScriptEditorSection[] = [
  {
    id: "opening",
    title: "Opening line",
    hint: "The first thing the caller hears. Keep it to one breath.",
    value: "Namaste {{caller_name}}, this is {{business_name}}. Is this a good time?",
    maxChars: 160,
    rows: 2,
  },
  {
    id: "purpose",
    title: "Why you are calling",
    hint: "One or two sentences the agent works from, not a speech.",
    value: "Confirm the delivery of {{last_order}} for Saturday and ask for a convenient time.",
    maxChars: 300,
  },
  {
    id: "questions",
    title: "Questions to ask",
    value: "Which time on Saturday suits you? Should we leave it with the security desk if nobody is home? Ask about {{order_total}}.",
    maxChars: 120,
  },
  {
    id: "closing",
    title: "Closing",
    value: "",
    maxChars: 200,
    placeholder: "Thank them and say when they will hear from you next.",
  },
];

const CHECKLIST: ChecklistItem[] = [
  { id: "agent", label: "Create your agent", state: "done" },
  { id: "voice", label: "Choose a voice", state: "done" },
  {
    id: "knowledge",
    label: "Add what your agent should know",
    state: "todo",
    detail: "Your price list or a page from your website.",
    link: { href: "#content", label: "Add knowledge" },
  },
  { id: "number", label: "Get a phone number", state: "waiting", detail: "Waiting for your business to be verified." },
  { id: "live", label: "Put the agent live", state: "todo", disabledReason: "Add knowledge first." },
];

const DELIVERY = {
  delivery_id: "dlv_01JBK7",
  status: 502,
  attempt: 3,
  request: { event: "lead.captured", lead: { id: "lead_9f2", fields: { interest: "Bulk order", city: "Vijayawada" } } },
  response: { error: "Bad gateway", retry_after: null, headers: { "content-type": "text/html" } },
  tags: Array.from({ length: 60 }, (_, i) => `tag-${i + 1}`),
};

const LONG_NOTE =
  "The caller wanted to know whether the shop delivers to Benz Circle on Sundays, asked twice about the price of a one kilo box of kaju katli, and said she would place an order for her daughter's engagement next month if the sweets can be packed in steel boxes rather than cardboard. She asked for someone to call her back after six in the evening, because she is at work during the day and cannot take calls at the counter.";

/** The content components of the kit: what a screen shows, edits and explains. */
export function ContentSection() {
  const [sections, setSections] = useState(SCRIPT);
  const [saveStatus, setSaveStatus] = useState<FeedbackStatus>("idle");
  const [choosing, setChoosing] = useState<FeedbackStatus>("idle");
  const over = scriptOverBudget(sections, 700);
  const unknown = unknownVariables(sections, VARIABLES);

  const simulate = (set: (s: FeedbackStatus) => void, outcome: FeedbackStatus) => {
    set("pending");
    window.setTimeout(() => {
      set(outcome);
      if (outcome === "success") window.setTimeout(() => set("idle"), 2000);
    }, 900);
  };

  return (
    <KitSection
      id="content"
      title="Content"
      lead="What a screen shows and edits: the script editor, tier comparison, checklists, empty states, long text, JSON and release notes."
    >
      <KitDemo
        wide
        label="ScriptEditor · budgets, an unknown field, an over-budget section, live preview"
        note="Type an asterisk, a list marker or an emoji: it is removed at once and the note says so. The value is always plain text."
      >
        <ScriptEditor
          sections={sections}
          variables={VARIABLES}
          totalMaxChars={700}
          onChange={(id, value) => setSections((all) => all.map((s) => (s.id === id ? { ...s, value } : s)))}
          onSave={() => simulate(setSaveStatus, "success")}
          status={saveStatus}
          saveBlockedReason={
            unknown.length > 0
              ? "Replace the unknown caller detail before saving."
              : over
                ? "Shorten the sections that are over before saving."
                : null
          }
          previewAction={
            <button type="button" className="text-meta font-medium text-brand-strong hover:underline">
              Listen
            </button>
          }
        />
      </KitDemo>

      <KitDemo
        wide
        label="TierComparison · Clear vs Studio, current tier, choosing"
        note="Sample rates and copy. A screen passes the server's rate strings and its own words."
      >
        <TierComparison
          currentId="clear"
          choosingId="studio"
          chooseStatus={choosing}
          onChoose={() => simulate(setChoosing, "success")}
          tiers={[
            {
              id: "clear",
              name: "Clear",
              ratePerMinute: "4.50",
              summary: "A clear, natural voice in your callers' language.",
              includes: ["Answers and places calls", "Understands mixed-language callers", "Call recordings and summaries"],
              bestFor: "Most businesses: bookings, enquiries, order follow-ups.",
            },
            {
              id: "studio",
              name: "Studio",
              ratePerMinute: "6.00",
              summary: "A richer, more expressive voice for calls where tone sells.",
              includes: ["Everything in Clear", "The most lifelike voices", "Better for long, warm conversations"],
              bestFor: "Premium brands and sales calls where the voice is the first impression.",
              cta: "Switch to Studio",
            },
          ]}
          guidance={
            <>
              <p>Start on Clear: it suits most everyday calls.</p>
              <p>Move to Studio when your calls are long or the voice is part of your brand.</p>
            </>
          }
        />
      </KitDemo>

      <KitGrid>
        <KitDemo label="Checklist · next step emphasised, done folded">
          <Checklist label="Before your first call" items={CHECKLIST} emphasizeNext foldDone />
        </KitDemo>
        <KitDemo label="Checklist · all done, collapsible">
          <Checklist
            label="Before your first call"
            collapsible
            items={CHECKLIST.map((item) => ({ ...item, state: "done", disabledReason: undefined }))}
          />
        </KitDemo>

        <KitDemo label="EmptyState · first use">
          <EmptyState
            message="No calls yet."
            hint="Calls appear here as soon as your agent answers one."
            illustration={<EmptySketch kind="calls" />}
            action={
              <a href="#content" className={PRIMARY_BUTTON}>
                Make a test call
              </a>
            }
          />
        </KitDemo>
        <KitDemo label="EmptyState · filtered">
          <EmptyState variant="filtered" message="No leads match these filters." onClear={() => undefined} />
        </KitDemo>
        <KitDemo label="EmptyState · restricted">
          <EmptyState
            variant="restricted"
            message="Only the account owner can see billing."
            hint="Ask the owner to give you access."
          />
        </KitDemo>
        <KitDemo label="EmptyState · error">
          <EmptyState
            variant="error"
            message="Calls did not load."
            error={new ApiProblem(503, { title: "We could not load your calls", detail: "Calevate is not answering right now.", retryable: true })}
            onRetry={() => undefined}
          />
        </KitDemo>

        <KitDemo label="ExpandableText · long note, clamped to 3 lines">
          <ExpandableText lines={3} textClassName="text-body text-ink">
            {LONG_NOTE}
          </ExpandableText>
        </KitDemo>
        <KitDemo label="ExpandableText · short text, no toggle">
          <ExpandableText textClassName="text-body text-ink">Wants a call back after 6 pm.</ExpandableText>
        </KitDemo>

        <KitDemo label="Accordion · exclusive, inline">
          <Accordion
            defaultOpenId="minutes"
            items={[
              { id: "minutes", title: "How minutes are counted", content: "Every started minute of a connected call is counted." },
              { id: "recordings", title: "How long recordings are kept", content: "Recordings follow the retention you set in Settings." },
              { id: "numbers", title: "Using your own number", content: "Forward your existing number to the one we give you." },
            ]}
          />
        </KitDemo>
        <KitDemo label="TextShimmer · working line, and CopyButton">
          <div className="space-y-3">
            <TextShimmer>Reading your price list…</TextShimmer>
            <div className="flex items-center gap-2 text-body text-ink">
              <span className="font-mono">+91 98765 43210</span>
              <CopyButton value="+919876543210" label="Copy phone number" />
              <CopyButton value="+919876543210" label="Copy phone number" variant="text" />
            </div>
          </div>
        </KitDemo>
      </KitGrid>

      <KitDemo wide label="JsonViewer · delivery log, collapsed past depth 2, paged array">
        <JsonViewer label="Delivery response" value={DELIVERY} pageSize={20} />
      </KitDemo>

      <KitDemo wide label="ChangelogFeed · What's new">
        <ChangelogFeed
          entries={[
            {
              id: "c3",
              date: "2026-10-22T05:30:00Z",
              title: "Call back later from the calls list",
              tags: ["Calls"],
              body: "Swipe a call on your phone to schedule a call back between 9 am and 9 pm.",
              href: "#content",
              hrefLabel: "Open calls",
            },
            {
              id: "c2",
              date: "2026-10-15T05:30:00Z",
              title: "Readiness score on every agent",
              tags: ["Agents"],
              body: "See what to fix before your agent goes live.",
            },
          ]}
        />
      </KitDemo>
      <KitDemo label="ChangelogFeed · empty">
        <ChangelogFeed entries={[]} />
      </KitDemo>
    </KitSection>
  );
}
