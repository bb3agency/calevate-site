import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HowTheySpeak, TAB_LEAD, TRAINING_INFO } from "@/app/c/[slug]/knowledge/HowTheySpeak";
import { KnowledgeScreen } from "@/app/c/[slug]/knowledge/KnowledgeScreen";
import type { CompanyTraining } from "@/lib/api/companyTraining";

import { noReply, problem, renderClientPage } from "./harness";

/*
 * HOW THEY SPEAK (D-996): the one training every agent is given, a tab of What your agents
 * know. The owner describes the business, Pip writes the training from it and the page's
 * sources, and the owner keeps it, edits it first or discards it. Keeping Pip's draft saves it
 * together with the draft's id, so the draft is settled in the same save.
 */

const PATH = "/v1/company-training";
const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "org:read", "org:manage", "kb:read", "kb:write"],
  impersonating: false,
};

function training(over: Partial<CompanyTraining> = {}): CompanyTraining {
  return {
    overview: "",
    training: "",
    version: 0,
    updated_at: null,
    proposal: null,
    overview_max: 4000,
    training_max: 6000,
    ...over,
  };
}

const READY: CompanyTraining["proposal"] = {
  id: "p-1",
  status: "ready",
  requested_at: "2026-11-16T05:00:00Z",
  base_training: null,
  training: "We are Sunrise Homes. We build flats in Kompally.",
  note: null,
  disclosure: null,
  reason: null,
};

describe("How they speak", () => {
  it("is a tab of What your agents know, opened by ?tab=speak", async () => {
    window.history.replaceState(null, "", "/c/acme/knowledge?tab=speak");
    try {
      await renderClientPage(<KnowledgeScreen />, {
        "/v1/me": OWNER,
        [PATH]: training(),
        "/v1/kb/notes": { notes: [] },
        "/v1/teach/questions": { items: [], open_count: 0 },
        "/v1/kb/teach/open": { teaching: null },
        "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
        "/v1/business-profile": noReply(),
      });
      expect(await screen.findByRole("tab", { name: "How they speak", selected: true })).toBeTruthy();
      expect(await screen.findByText(TAB_LEAD)).toBeTruthy();
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });

  it("asks for the business first, with Generate held back until it is saved", async () => {
    await renderClientPage(<HowTheySpeak />, { "/v1/me": OWNER, [PATH]: training() });
    expect(await screen.findByText(TAB_LEAD)).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "About the business" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Generate" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Save About the business first.")).toBeTruthy();
  });

  it("saves the owner's words about the business", async () => {
    const page = await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training(),
      [`PUT ${PATH}/overview`]: training({ overview: "We build flats in Kompally." }),
    });
    fireEvent.change(await screen.findByRole("textbox", { name: "About the business" }), {
      target: { value: "We build flats in Kompally." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(page.calls.some((c) => c.method === "PUT")).toBe(true));
    const sent = page.calls.find((c) => c.method === "PUT");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ overview: "We build flats in Kompally." });
  });

  it("keeps Pip's draft with its id, so the draft is settled by the same save", async () => {
    const page = await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({ overview: "We build flats.", proposal: READY }),
      [`PUT ${PATH}/training`]: training({ overview: "We build flats.", training: READY?.training ?? "", version: 1 }),
    });
    expect(await screen.findByText(/We build flats in Kompally/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    await waitFor(() => expect(page.calls.some((c) => c.path === `${PATH}/training`)).toBe(true));
    const sent = page.calls.find((c) => c.path === `${PATH}/training`);
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ training: READY?.training, proposal_id: "p-1" });
  });

  it("shows the saved training with its version and an Edit", async () => {
    await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({
        overview: "We build flats.",
        training: "Address people as sir or madam.",
        version: 3,
        updated_at: "2026-11-16T05:00:00Z",
      }),
    });
    expect(await screen.findByText("Address people as sir or madam.")).toBeTruthy();
    expect(screen.getByText("Version 3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Edit training" }));
    expect((screen.getByRole("textbox", { name: "Training" }) as HTMLTextAreaElement).value).toBe(
      "Address people as sir or madam.",
    );
    expect(screen.getByRole("button", { name: "Save for every agent" })).toBeTruthy();
  });

  it("offers the places a too-long script is shortened when a save is refused for one", async () => {
    await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({ overview: "We build flats.", training: "Address people as sir or madam.", version: 3 }),
      [`PUT ${PATH}/training`]: problem(422, {
        type: "https://calevate.tech/problems/company_training_too_long",
        title: "That change is not allowed",
        status: 422,
        kind: "business_rule",
        detail: "With this training, the script of the campaign Diwali visits is 1,240 characters too long.",
        remediation: "Shorten the training or that campaign's script.",
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Edit training" }));
    fireEvent.click(screen.getByRole("button", { name: "Save for every agent" }));
    expect(await screen.findByText(/campaign Diwali visits is 1,240 characters too long/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open Inbound lines" }).getAttribute("href")).toBe("/c/acme/inbound");
    expect(screen.getByRole("link", { name: "Open Campaigns" }).getAttribute("href")).toBe("/c/acme/campaigns");
  });

  it("offers no way out for a refusal that is not about a script's length", async () => {
    await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({ overview: "We build flats.", training: "Address people as sir or madam.", version: 3 }),
      [`PUT ${PATH}/training`]: problem(409, {
        type: "https://calevate.tech/problems/company_training_changed",
        title: "Changed elsewhere",
        status: 409,
        kind: "conflict",
        detail: "Someone else saved the training.",
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Edit training" }));
    fireEvent.click(screen.getByRole("button", { name: "Save for every agent" }));
    expect(await screen.findByText("Someone else saved the training.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open Campaigns" })).toBeNull();
  });

  it("says a script belongs to a line or campaign, never to an agent (D-1005)", () => {
    expect(TRAINING_INFO).toMatch(/Inbound line and campaign/);
    expect(TRAINING_INFO).not.toMatch(/agent/i);
  });
});
