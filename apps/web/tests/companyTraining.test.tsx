import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CompanyTrainingScreen, PAGE_DESCRIPTION } from "@/app/c/[slug]/company-training/CompanyTrainingScreen";
import type { CompanyTraining } from "@/lib/api/companyTraining";

import { renderClientPage } from "./harness";

/*
 * THE COMPANY TRAINING (founder, 16 Nov 2026): one training every agent is given. The owner
 * describes the business, Pip writes the training, and the owner keeps it, edits it first or
 * discards it. Keeping Pip's draft saves it together with the draft's id, so the draft is
 * settled in the same save.
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
    materials: [],
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

describe("the company training page", () => {
  it("asks for the business first, with Generate held back until it is saved", async () => {
    await renderClientPage(<CompanyTrainingScreen />, { "/v1/me": OWNER, [PATH]: training() });
    expect(await screen.findByText(PAGE_DESCRIPTION)).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "About the business" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Generate" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Save About the business first.")).toBeTruthy();
  });

  it("saves the owner's words about the business", async () => {
    const page = await renderClientPage(<CompanyTrainingScreen />, {
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
    const page = await renderClientPage(<CompanyTrainingScreen />, {
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
    await renderClientPage(<CompanyTrainingScreen />, {
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
});
