import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EMPTY_TRAINING, HowTheySpeak, TAB_LEAD, reasonWords } from "@/app/c/[slug]/knowledge/HowTheySpeak";
import { KnowledgeScreen } from "@/app/c/[slug]/knowledge/KnowledgeScreen";
import type { CompanyTraining } from "@/lib/api/companyTraining";

import { noReply, problem, renderClientPage } from "./harness";

/*
 * HOW THEY SPEAK (D-996): the one training every agent is given, a tab of What your agents
 * know. Pip writes it by itself in the background and saves it live (D-1034); the screen says
 * when and why, the owner can still edit it, and Rewrite now runs the same write.
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
    last_write: null,
    owner_edited: false,
    overview_max: 4000,
    training_max: 6000,
    ...over,
  };
}

const QUEUED: CompanyTraining["proposal"] = {
  id: "p-1",
  status: "queued",
  requested_at: "2026-11-16T05:00:00Z",
  due_at: "2026-11-16T05:01:00Z",
  reasons: ["knowledge_changed", "profile_changed"],
  note: null,
  reason: null,
};

describe("Company training", () => {
  it.each(["training", "speak"])("is the Company training tab, opened by ?tab=%s", async (tab) => {
    window.history.replaceState(null, "", `/c/acme/knowledge?tab=${tab}`);
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
      expect(await screen.findByRole("tab", { name: "Company training", selected: true })).toBeTruthy();
      expect(await screen.findByText(TAB_LEAD)).toBeTruthy();
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });

  it("says Pip writes the training by itself, with no Generate step", async () => {
    await renderClientPage(<HowTheySpeak />, { "/v1/me": OWNER, [PATH]: training() });
    expect(await screen.findByText(TAB_LEAD)).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "About the business" })).toBeTruthy();
    expect(screen.getByText(EMPTY_TRAINING)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Generate" })).toBeNull();
    expect(screen.getByRole("button", { name: "Write it myself" })).toBeTruthy();
  });

  it("shows Pip about to rewrite it, and why", async () => {
    await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({ training: "Address people as sir or madam.", version: 2, proposal: QUEUED }),
    });
    expect(await screen.findByText("Pip rewrites it shortly")).toBeTruthy();
    expect(screen.getByText(reasonWords(["knowledge_changed", "profile_changed"]))).toBeTruthy();
    expect(screen.getByText("Address people as sir or madam.")).toBeTruthy();
  });

  it("says when Pip last wrote it, what it kept, and what newer knowledge replaced", async () => {
    await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({
        training: "Address people as sir or madam.",
        version: 4,
        last_write: {
          at: "2026-11-16T05:00:00Z",
          reasons: ["knowledge_changed"],
          owner_edits_kept: 2,
          superseded: ["Delivery is 50 rupees."],
          shortened: false,
          disclosure: null,
        },
      }),
    });
    expect(await screen.findByText(/^Pip wrote it/)).toBeTruthy();
    expect(screen.getByText("Your edits kept: 2")).toBeTruthy();
    expect(screen.getByText("Newer knowledge replaced 1")).toBeTruthy();
    expect(screen.getByText("Delivery is 50 rupees.")).toBeTruthy();
    expect(screen.queryByText("Pip needs more about your business")).toBeNull();
  });

  it("asks for what the knowledge does not say about the business", async () => {
    await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({
        training: "Address people as sir or madam.",
        version: 4,
        last_write: {
          at: "2026-11-16T05:00:00Z",
          reasons: ["knowledge_changed"],
          owner_edits_kept: 0,
          superseded: [],
          shortened: false,
          disclosure: null,
          missing: ["business", "customers"],
        },
      }),
    });
    expect(await screen.findByText("Pip needs more about your business")).toBeTruthy();
    expect(
      screen.getByText("Your knowledge does not say what your business does and who your customers are."),
    ).toBeTruthy();
    const link = screen.getByRole("link", { name: "Write about the business" });
    expect(link.getAttribute("href")).toBe("#training-overview");
  });

  it("Rewrite now starts Pip's write", async () => {
    const page = await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({ training: "Address people as sir or madam.", version: 2 }),
      [`POST ${PATH}/proposal`]: { ...QUEUED, reasons: ["owner_asked"] },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Rewrite now" }));
    await waitFor(() => expect(page.calls.some((c) => c.method === "POST" && c.path === `${PATH}/proposal`)).toBe(true));
  });

  it("holds Rewrite now back while Pip is writing", async () => {
    await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({ training: "Address people as sir or madam.", proposal: { ...QUEUED, status: "drafting" } }),
    });
    expect(await screen.findByText("Pip is rewriting it")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Rewrite now" }) as HTMLButtonElement).disabled).toBe(true);
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

  it("saves the owner's edit of the training as their own words", async () => {
    const page = await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({ training: "Address people as sir or madam.", version: 1 }),
      [`PUT ${PATH}/training`]: training({ training: "Call people sir.", version: 2, owner_edited: true }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Edit training" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Training" }), { target: { value: "Call people sir." } });
    fireEvent.click(screen.getByRole("button", { name: "Save for every agent" }));
    await waitFor(() => expect(page.calls.some((c) => c.path === `${PATH}/training`)).toBe(true));
    const sent = page.calls.find((c) => c.path === `${PATH}/training`);
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ training: "Call people sir.", version: 1 });
    expect(await screen.findByText("Has your edits")).toBeTruthy();
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

  it("links straight to the campaign a too-long refusal names", async () => {
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
        campaign_id: "c-42",
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Edit training" }));
    fireEvent.click(screen.getByRole("button", { name: "Save for every agent" }));
    const link = await screen.findByRole("link", { name: "Open the campaign" });
    expect(link.getAttribute("href")).toBe("/c/acme/campaigns/c-42");
    expect(screen.queryByRole("link", { name: "Open Inbound lines" })).toBeNull();
  });

  it("links straight to the Inbound line a too-long refusal names", async () => {
    await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({ overview: "We build flats.", training: "Address people as sir or madam.", version: 3 }),
      [`PUT ${PATH}/training`]: problem(422, {
        type: "https://calevate.tech/problems/company_training_too_long",
        title: "That change is not allowed",
        status: 422,
        kind: "business_rule",
        detail: "With this training, the script of the Inbound line Front desk is 90 characters too long.",
        remediation: "Shorten the training or that Inbound line's script.",
        inbound_line_id: "l-7",
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Edit training" }));
    fireEvent.click(screen.getByRole("button", { name: "Save for every agent" }));
    const link = await screen.findByRole("link", { name: "Open the Inbound line" });
    expect(link.getAttribute("href")).toBe("/c/acme/inbound/l-7");
    expect(screen.queryByRole("link", { name: "Open Campaigns" })).toBeNull();
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

  it("says a script belongs to a line or campaign, never to an agent (D-1005)", async () => {
    await renderClientPage(<HowTheySpeak />, {
      "/v1/me": OWNER,
      [PATH]: training({ overview: "We build flats.", training: "Address people as sir or madam.", version: 3 }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "About training" }));
    const tip = await screen.findByText(/keeps its own script on top of this/);
    expect(tip.textContent).toMatch(/^Each Inbound line and campaign keeps/);
    expect(tip.textContent).not.toMatch(/agent/i);
  });
});
