import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import type { BusinessProfile } from "@/lib/api/businessProfile";
import type { Me } from "@/lib/api/client";

import { NEUTRAL_WORDING, businessProfileFixture } from "./businessProfileFixture";
import { renderClientPage, type Routes } from "./harness";

/**
 * What the business offers and its common questions on "What your agents know" (D-968).
 * They have one home, the business profile: each test names the failure it guards, a second
 * copy written beside the profile, a row written from a stale copy of the list, or a label
 * that is not the business's own.
 */

function me(permissions: string[]): Me {
  return {
    impersonating: false,
    withheld_acts: [],
    permissions,
    realm: "client",
    role: "owner",
    user_id: "user_1",
    organization: null,
  };
}

const OWNER = me(["agents:read", "calls:read", "kb:write", "org:read", "org:manage"]);

const PLANS: BusinessProfile = businessProfileFixture({
  wording: { ...NEUTRAL_WORDING, offer_label: "Plan", price_label: "Monthly fee", drafted: true },
  services: [{ name: "Gold plan", price_inr: "999", notes: "Two visits" }],
  faqs: [{ question: "Do you take UPI?", answer: "Yes." }],
});

async function renderKnowledge(profile: BusinessProfile, over: Routes = {}, who: Me = OWNER) {
  return await renderClientPage(<KnowledgePage />, {
    "/v1/me": who,
    "/v1/agents": [],
    "/v1/kb/notes": { notes: [] },
    "/v1/kb/uploads": [],
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
    "/v1/teach/questions": { items: [], open_count: 0 },
    "/v1/kb/teach/open": { teaching: null },
    "/v1/business-profile": profile,
    ...over,
  });
}

function patched(calls: { method: string; path: string; body?: string | null }[]) {
  const patch = calls.find((c) => c.method === "PATCH" && c.path === "/v1/business-profile");
  return patch ? JSON.parse(patch.body ?? "{}") : null;
}

describe("the business profile on What your agents know", () => {
  it("shows what it offers and its questions in the business's own words", async () => {
    await renderKnowledge(PLANS);
    const offers = await screen.findByRole("list", { name: "What you offer" });
    expect(within(offers).getByText("Gold plan")).toBeTruthy();
    expect(within(offers).getByText("₹999")).toBeTruthy();
    const questions = screen.getByRole("list", { name: "Common questions" });
    expect(within(questions).getByText("Do you take UPI?")).toBeTruthy();
    // The add choice is named by the business's labels, never "Service" or "Price".
    expect(screen.getByRole("radio", { name: "Plan and monthly fee" })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /Service/ })).toBeNull();
  });

  it("adds a plan to the profile as it is now, and writes no fact beside it", async () => {
    // The screen loaded one plan; another tab added a second since. The add must keep both.
    let reads = 0;
    const newer = { ...PLANS, services: [...PLANS.services, { name: "Silver plan", price_inr: "499", notes: null }] };
    const { calls } = await renderKnowledge(PLANS, {
      "/v1/business-profile": () => (reads++ === 0 ? PLANS : newer),
      "PATCH /v1/business-profile": newer,
    });
    fireEvent.click(await screen.findByRole("radio", { name: "Plan and monthly fee" }));
    fireEvent.change(await screen.findByLabelText("Plan"), { target: { value: "Family plan" } });
    fireEvent.change(screen.getByLabelText("Monthly fee (₹)"), { target: { value: "1499" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(patched(calls)).not.toBeNull());
    expect(patched(calls)).toEqual({
      services: [
        { name: "Gold plan", price_inr: "999", notes: "Two visits" },
        { name: "Silver plan", price_inr: "499", notes: null },
        { name: "Family plan", price_inr: "1499", notes: null },
      ],
    });
    expect(calls.some((c) => c.path.startsWith("/v1/kb/facts"))).toBe(false);
  });

  it("asks a business that quotes no price for no price", async () => {
    const free = businessProfileFixture({
      wording: { ...NEUTRAL_WORDING, offer_label: "Course", price_label: null, drafted: true },
      services: [],
    });
    await renderKnowledge(free);
    expect(await screen.findByRole("radio", { name: "Course" })).toBeTruthy();
    expect(await screen.findByLabelText("Course")).toBeTruthy();
    expect(screen.queryByLabelText(/₹/)).toBeNull();
  });

  it("adds a question and its answer to the profile's common questions", async () => {
    const { calls } = await renderKnowledge(PLANS, { "PATCH /v1/business-profile": PLANS });
    fireEvent.click(await screen.findByRole("radio", { name: "Question and answer" }));
    fireEvent.change(await screen.findByLabelText("What callers ask"), { target: { value: "Is there parking?" } });
    fireEvent.change(screen.getByLabelText("The answer"), { target: { value: "Yes, behind the shop." } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(patched(calls)).not.toBeNull());
    expect(patched(calls)).toEqual({
      faqs: [
        { question: "Do you take UPI?", answer: "Yes." },
        { question: "Is there parking?", answer: "Yes, behind the shop." },
      ],
    });
  });

  it("edits and removes a row through the profile", async () => {
    const { calls } = await renderKnowledge(PLANS, { "PATCH /v1/business-profile": PLANS });
    const questions = await screen.findByRole("list", { name: "Common questions" });
    fireEvent.click(within(questions).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(questions).getByLabelText("The answer"), { target: { value: "Yes, and cards." } });
    fireEvent.click(within(questions).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patched(calls)).toEqual({ faqs: [{ question: "Do you take UPI?", answer: "Yes, and cards." }] }));

    const offers = screen.getByRole("list", { name: "What you offer" });
    fireEvent.click(within(offers).getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PATCH" && JSON.parse(c.body ?? "{}").services?.length === 0)).toBe(true),
    );
  });

  it("shows the rows but no way to change them without the right to change business details", async () => {
    await renderKnowledge(PLANS, {}, me(["agents:read", "calls:read", "kb:write", "org:read"]));
    const offers = await screen.findByRole("list", { name: "What you offer" });
    expect(within(offers).queryByRole("button", { name: "Edit" })).toBeNull();
    expect((await screen.findByLabelText("Plan")).closest("fieldset")?.disabled).toBe(true);
  });
});
