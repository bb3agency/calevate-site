import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ContactResults } from "@/app/c/[slug]/campaigns/ContactResults";
import { FoldGroup, FoldSection } from "@/app/c/[slug]/campaigns/FoldSection";

import { FIXTURE_CAMPAIGN_ID, contactsFixture } from "./campaignFixtures";
import { renderClientPage } from "./harness";
import { OWNER_ME } from "./fixtures/sharedReads";

/**
 * The campaign screens on a phone: every control a thumb presses is 44 px on a touch screen
 * (`touch:` is `pointer: coarse`), and the people table keeps the name wide by putting each
 * person's status under them below `sm`. jsdom draws no CSS, so these read the classes that do.
 */

const PERSON = {
  id: "0192f0aa-7777-7000-8000-000000000001",
  name: "Sujatha Reddy",
  phone_e164: "+919876543201",
  outcome: "no_answer" as const,
  attempts: 1,
  last_attempt_at: "2026-11-16T05:00:00Z",
  next_attempt_at: null,
  will_retry: false,
  call_id: "0192f0aa-8888-7000-8000-000000000001",
  goal_reached: null,
  goal_reason: null,
  business_outcome_label: null,
  included: true,
};

describe("the campaign screens on a phone", () => {
  it("gives each include box a thumb-sized label and puts the status under the person", async () => {
    await renderClientPage(
      <ContactResults slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} maxAttempts={3} live={false} canWrite refusal={undefined} />,
      {
        "/v1/me": OWNER_ME,
        [`/v1/campaigns/${FIXTURE_CAMPAIGN_ID}/contacts?limit=10&offset=0`]: contactsFixture({
          items: [PERSON],
          total: 1,
          everyone: 1,
          included: 1,
          counts: { ...contactsFixture().counts, no_answer: 1 },
        }),
      },
    );
    const box = await screen.findByRole("checkbox", { name: "Include Sujatha Reddy in this campaign" });
    expect(box.closest("label")?.className).toContain("touch:min-h-11");
    const all = screen.getByRole("checkbox", { name: "Leave everyone out of this campaign" });
    expect(all.closest("label")?.className).toContain("touch:min-w-11");
    // The Status column is for wider screens; on a phone the person's cell carries it.
    expect(screen.getByRole("columnheader", { name: "Status" }).className).toMatch(/\bhidden\b.*\bsm:table-cell\b/);
    const [underPerson] = screen.getAllByText("No answer");
    expect(underPerson.closest("div.sm\\:hidden")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the call with Sujatha Reddy" }).className).toContain("touch:min-w-11");
  });

  it("makes a fold's coloured pill and Collapse all thumb-sized", async () => {
    await renderClientPage(
      <FoldGroup>
        <FoldSection title="What this campaign is for" tone="task">
          <p>Body</p>
        </FoldSection>
      </FoldGroup>,
      { "/v1/me": OWNER_ME },
    );
    expect((await screen.findByRole("button", { name: "What this campaign is for" })).className).toContain("touch:min-h-11");
    expect(screen.getByRole("button", { name: "Collapse all" }).className).toContain("touch:min-h-11");
  });
});
