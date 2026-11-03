import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { partTone } from "@/app/c/[slug]/agents/AgentReadiness";
import { NeedsYouTally } from "@/app/c/[slug]/knowledge/WhatItKnows";
import { noteTone } from "@/app/c/[slug]/knowledge/NotesList";
import { businessOutcomeKind, callOutcome } from "@/lib/callReview";

/**
 * Colour on the agent and knowledge screens follows the console's four tones and always sits
 * beside words: these pin which tone each fact gets, and that the words are there.
 */

describe("a readiness part's tone", () => {
  it("is done when full, a gap when empty, and partial in between", () => {
    expect(partTone(20, 20)).toBe("ok");
    expect(partTone(0, 20)).toBe("stop");
    expect(partTone(7, 20)).toBe("warn");
  });

  it("does not call a part with nothing to earn a gap", () => {
    expect(partTone(0, 0)).toBe("ok");
  });
});

describe("the knowledge tally", () => {
  it("counts waiting and broken rows in words", () => {
    render(<NeedsYouTally tones={["ok", "warn", "warn", "stop", "neutral"]} />);
    expect(screen.getByText("1 not working")).toBeTruthy();
    expect(screen.getByText("2 waiting")).toBeTruthy();
  });

  it("says nothing when every row is in use or on its way", () => {
    const { container } = render(<NeedsYouTally tones={["ok", "neutral"]} />);
    expect(container.textContent).toBe("");
  });

  it("reads a note's tone from the badge's own table", () => {
    expect(noteTone("needs_attention")).toBe("stop");
    expect(noteTone("in_review")).toBe("warn");
    expect(noteTone("toString")).toBe("neutral");
  });
});

describe("an outcome's colour in the editor and the log", () => {
  it("files an outcome by how far it moves the lead, and the refusal as said no", () => {
    expect(businessOutcomeKind("site_visit", "hot")).toBe("hot");
    expect(businessOutcomeKind("asked_price", "interested")).toBe("interested");
    expect(businessOutcomeKind("asked_hours", "contacted")).toBe("neutral");
    expect(businessOutcomeKind("not_interested", "contacted")).toBe("said_no");
  });

  it("is the same kind the call log gives a call filed under it", () => {
    const call = {
      status: "completed",
      outcome_tag: null,
      business_outcome: "site_visit",
      business_outcome_label: "Site visit",
      business_outcome_lead_status: "hot" as const,
    };
    expect(callOutcome(call).kind).toBe(businessOutcomeKind("site_visit", "hot"));
  });
});
