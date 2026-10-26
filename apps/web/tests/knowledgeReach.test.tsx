import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import { reachesAgents, uploadState, uploadSteps } from "@/app/c/[slug]/knowledge/uploadCopy";
import type { Me } from "@/lib/api/client";
import type { KbUpload } from "@/lib/api/kb";

import { renderClientPage, type Routes } from "./harness";

/**
 * WHAT A STATUS MAY CLAIM (D-874, D-893 L8). A PDF's and a link's words are read into a copy
 * the owner and Pip can open, and reach the agents only while our console sends them — the
 * server's `reaches_agents`. Until it does, a published PDF must never be called "In use".
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "kb:write"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

function upload(over: Partial<KbUpload> = {}): KbUpload {
  const base: KbUpload = {
    id: "u1",
    source_id: "s1",
    name: "Price list.pdf",
    source_kind: "pdf",
    ingest_status: "processed",
    ingest_detail: null,
    review_state: "approved",
    is_live: true,
    version: 1,
    filename: "Price list.pdf",
    byte_size: 1024,
    source_url: null,
    text_provenance: null,
    change_detected_at: null,
    read_state: "ready",
    read_detail: null,
    page_count: 1,
    reaches_agents: false,
    ...over,
  };
  // What the server says unless a test says otherwise: a converted kind always reaches.
  return { ...base, reaches_agents: over.reaches_agents ?? !["pdf", "url"].includes(base.source_kind) };
}

describe("which kinds reach the agents", () => {
  it("is the server's answer, never a list of kinds kept here", () => {
    expect(reachesAgents(upload({ source_kind: "docx" }))).toBe(true);
    expect(reachesAgents(upload())).toBe(false);
    expect(reachesAgents(upload({ reaches_agents: true }))).toBe(true);
  });

  it("never calls a published PDF or link in use while the agents do not get it", () => {
    const pdf = uploadState(upload());
    expect(pdf.label).toBe("Saved, not used yet");
    expect(pdf.meaning).toContain("Saved — your agents don't use this yet");
    expect(pdf.meaning).toContain("You and Pip can open it");
    expect(pdf.tone).toBe("neutral");

    const link = uploadState(upload({ source_kind: "url", name: "Prices page", source_url: "https://example.in" }));
    expect(link.label).toBe("Saved, not used yet");
    expect(link.meaning).toContain("open the page");
  });

  it("calls a PDF in use once the server says its words reach the agents", () => {
    expect(uploadState(upload({ reaches_agents: true })).label).toBe("In use");
  });

  it("says while the words are being read, and when they could not be", () => {
    const reading = upload({ read_state: "reading", is_live: false, ingest_status: "processing" });
    expect(uploadState(reading).label).toBe("Being read");
    expect(uploadSteps(reading)).toBeNull();
    const failed = upload({ read_state: "failed", read_detail: "This PDF is locked with a password." });
    expect(uploadState(failed).label).toBe("Couldn't read");
    expect(uploadState(failed).meaning).toBe("This PDF is locked with a password.");
  });

  it("says the same of a PDF that is still moving, and draws no steps towards 'In use'", () => {
    const moving = upload({ is_live: false, ingest_status: "processing" });
    expect(uploadState(moving).label).toBe("Saved, not used yet");
    expect(uploadSteps(moving)).toBeNull();
  });

  it("still puts a refusal first, whatever the kind", () => {
    expect(uploadState(upload({ is_live: false, ingest_status: "error" })).label).toBe("Could not be added");
    expect(uploadState(upload({ is_live: false, review_state: "rejected" })).label).toBe("Not accepted");
  });

  it("calls a published Word file in use", () => {
    const docx = uploadState(upload({ source_kind: "docx", name: "Price list.docx" }));
    expect(docx.label).toBe("In use");
    expect(docx.meaning).toContain("Your agents are using this now");
  });
});

async function renderKnowledge(over: Routes = {}) {
  return await renderClientPage(<KnowledgePage />, {
    "/v1/me": ME,
    "/v1/kb/sources": [],
    "/v1/kb/uploads": [],
    "/v1/kb/struggles": [],
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
    "/v1/kb/teach/open": { teaching: null },
    ...over,
  });
}

describe("the one Add area (D-874)", () => {
  it("opens on writing, and offers a file and a link beside it", async () => {
    await renderKnowledge();
    const add = await screen.findByRole("radiogroup", { name: "What are you adding?" });
    const modes = within(add).getAllByRole("radio").map((r) => r.textContent);
    expect(modes).toEqual(["Write it", "File", "Link"]);
    expect(within(add).getByRole("radio", { name: "Write it" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("button", { name: "Let Pip teach it" })).toBeTruthy();
  });

  it("says before a PDF or a link is sent what we do with it, and promises nothing the row may deny", async () => {
    await renderKnowledge();
    fireEvent.click(await screen.findByRole("radio", { name: "File" }));
    expect(screen.getByText(/We read its words so you and Pip can open and search it/)).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Link" }));
    expect(screen.getByText(/We read that one page so you and Pip can open and search it/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /save link/i })).toBeTruthy();
  });

  it("keeps half-typed words when the owner looks at another way and comes back", async () => {
    await renderKnowledge();
    const box = (await screen.findByLabelText("What should your agents know?")) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "Open 9 to 9." } });
    fireEvent.click(screen.getByRole("radio", { name: "Link" }));
    fireEvent.click(screen.getByRole("radio", { name: "Write it" }));
    expect((screen.getByLabelText("What should your agents know?") as HTMLTextAreaElement).value).toBe(
      "Open 9 to 9.",
    );
  });

  it("goes back to writing when the owner answers a question the agents could not", async () => {
    await renderKnowledge({
      "/v1/kb/struggles": [
        {
          id: "g1",
          kind: "didnt_know",
          gap_id: "g1",
          agent_id: "agent-1",
          agent_name: "Front desk",
          topic: "Parking",
          question: "Is there parking?",
          answer: null,
          times: 1,
          calls: 1,
          last_call_id: null,
          last_seen_at: "2026-10-10T10:00:00Z",
        },
      ],
    });
    fireEvent.click(await screen.findByRole("radio", { name: "Link" }));
    fireEvent.click(await screen.findByRole("tab", { name: "Couldn’t answer · 1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Add the answer" }));
    expect(screen.getByRole("radio", { name: "Write it" }).getAttribute("aria-checked")).toBe("true");
    expect(await screen.findByText(/Answering a caller who asked/)).toBeTruthy();
  });
});

describe("what the agents know, grouped", () => {
  it("puts files and links in their own groups, each with a status that does not overclaim", async () => {
    await renderKnowledge({
      "/v1/kb/uploads": [
        upload({ id: "a", name: "Menu.docx", source_kind: "docx", filename: "Menu.docx" }),
        upload({ id: "b", name: "Brochure.pdf" }),
        upload({ id: "c", name: "Prices page", source_kind: "url", source_url: "https://example.in/p", filename: null }),
        // History, not a row: the version that replaced it is the row.
        upload({ id: "d", name: "Old menu.docx", source_kind: "docx", review_state: "archived", is_live: false }),
      ],
    });
    const files = (await screen.findByRole("heading", { name: /^Files/ })).closest("section") as HTMLElement;
    const links = screen.getByRole("heading", { name: /^Links/ }).closest("section") as HTMLElement;

    const menu = within(files).getByText("Menu.docx").closest("li") as HTMLElement;
    expect(menu.textContent).toContain("In use");
    const brochure = within(files).getByText("Brochure.pdf").closest("li") as HTMLElement;
    expect(brochure.textContent).toContain("Saved, not used yet");
    expect(brochure.textContent).not.toContain("In use");
    const page = within(links).getByText("Prices page").closest("li") as HTMLElement;
    expect(page.textContent).toContain("Saved, not used yet");
    expect(screen.queryByText("Old menu.docx")).toBeNull();
  });

  it("finds a row by search across the groups, and says so when nothing matches", async () => {
    await renderKnowledge({
      "/v1/kb/knows": {
        facts: [
          { id: "f1", text: "We deliver in Kukatpally.", question: null, pinned: false, origin: "taught", created_at: "2026-10-10T10:00:00Z" },
        ],
        facts_state: "live",
        items: [],
        pinned_not_yet_on: [],
      },
      "/v1/kb/uploads": [upload({ id: "a", name: "Menu.docx", source_kind: "docx" })],
    });
    const search = await screen.findByRole("searchbox", { name: "Search what your agents know" });
    fireEvent.change(search, { target: { value: "menu" } });
    expect(screen.getByText("Menu.docx")).toBeTruthy();
    expect(screen.queryByText("We deliver in Kukatpally.")).toBeNull();
    fireEvent.change(search, { target: { value: "zzz" } });
    expect(await screen.findByText("Nothing matches your search.")).toBeTruthy();
  });

  it("invites the first fact when there is nothing at all", async () => {
    await renderKnowledge();
    expect(await screen.findByText("Your agents don’t know anything yet")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /^Links/ })).toBeNull();
  });
});
