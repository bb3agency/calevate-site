import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import { reachesAgents, uploadState, uploadSteps } from "@/app/c/[slug]/knowledge/uploadCopy";
import type { Me } from "@/lib/api/client";
import type { KbUpload } from "@/lib/api/kb";

import { businessProfileFixture } from "./businessProfileFixture";
import { renderClientPage, type Routes } from "./harness";

/**
 * WHAT A STATUS MAY CLAIM (D-874, D-868). A PDF reaches the agents once its words are read,
 * a link as its address — the server's `reaches_agents` — and a page the agents could not
 * read comes back as an `error` with the reason. Until the server says it reaches them, a
 * published PDF must never be called "In use".
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
  // What the server says unless a test says otherwise (`upload_reaches_agents`).
  const reaches = base.source_kind !== "pdf" || base.read_state === "ready";
  return { ...base, reaches_agents: over.reaches_agents ?? reaches };
}

describe("which kinds reach the agents", () => {
  it("is the server's answer, never a list of kinds kept here", () => {
    expect(reachesAgents(upload({ source_kind: "docx" }))).toBe(true);
    expect(reachesAgents(upload())).toBe(true);
    expect(reachesAgents(upload({ reaches_agents: false }))).toBe(false);
  });

  it("calls a read PDF and a live link in use, and says how much of the PDF was read", () => {
    expect(uploadState(upload()).label).toBe("In use");
    const partial = uploadState(upload({ read_detail: "We read 18 of 20 pages." }));
    expect(partial.label).toBe("In use");
    expect(partial.meaning).toBe("We read 18 of 20 pages.");
    const link = uploadState(upload({ source_kind: "url", name: "Prices page", source_url: "https://example.in" }));
    expect(link.label).toBe("In use");
    expect(link.meaning).toContain("this page");
  });

  it("never calls a live PDF in use before its words are read", () => {
    const unread = uploadState(upload({ read_state: null }));
    expect(unread.label).toBe("Not read yet");
    expect(unread.meaning).toContain("Read it again");
  });

  it("says why the agents could not read a page, in the platform's reason", () => {
    const refused = uploadState(
      upload({
        source_kind: "url",
        ingest_status: "error",
        ingest_detail: "Your agents could not read that page. The page may require a login.",
      }),
    );
    expect(refused.label).toBe("Agents couldn't read it");
    expect(refused.meaning).toContain("may require a login");
    expect(refused.tone).toBe("stop");
  });

  it("says while the words are being read, and when they could not be", () => {
    const reading = upload({ read_state: "reading", is_live: false, ingest_status: "processing" });
    expect(uploadState(reading).label).toBe("Being read");
    expect(uploadSteps(reading)).toBeNull();
    const failed = upload({ read_state: "failed", read_detail: "This PDF is locked with a password." });
    expect(uploadState(failed).label).toBe("Couldn't read");
    expect(uploadState(failed).meaning).toBe("This PDF is locked with a password.");
  });

  it("walks a read PDF that is still on its way through the steps to 'In use'", () => {
    const moving = upload({ is_live: false, ingest_status: "processing" });
    expect(uploadState(moving).label).toBe("Going to your agents");
    expect(uploadSteps(moving)?.current).toBe(2);
  });

  it("still puts a refusal first, whatever the kind", () => {
    expect(uploadState(upload({ is_live: false, ingest_status: "error" })).label).toBe("Could not be added");
    expect(uploadState(upload({ is_live: false, review_state: "rejected" })).label).toBe("Not accepted");
  });

  it("calls a published Word file in use", () => {
    const docx = uploadState(upload({ source_kind: "docx", name: "Price list.docx" }));
    expect(docx.label).toBe("In use");
    expect(docx.meaning).toContain("Your agents use this on calls");
  });
});

async function renderKnowledge(over: Routes = {}) {
  return await renderClientPage(<KnowledgePage />, {
    "/v1/me": ME,
    "/v1/kb/notes": { notes: [] },
    "/v1/kb/uploads": [],
    "/v1/teach/questions": { items: [], open_count: 0 },
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
    "/v1/kb/teach/open": { teaching: null },
    // Nothing offered and no common questions, so an empty account reads as empty.
    "/v1/business-profile": businessProfileFixture({ services: [], faqs: [] }),
    ...over,
  });
}

describe("the one teach card (D-874)", () => {
  it("offers every way in one row and opens on typing or saying it", async () => {
    await renderKnowledge();
    const ways = await screen.findByRole("radiogroup", { name: "What do you want to add?" });
    // The owner still says what it is (D-968): an offer and a question go into the profile.
    expect(within(ways).getAllByRole("radio").map((r) => r.closest("label")?.textContent)).toEqual([
      "Type or say it",
      "Service and price",
      "Question and answer",
      "Photo or file",
      "Website link",
    ]);
    expect((within(ways).getByRole("radio", { name: "Type or say it" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("button", { name: "Teach this" })).toBeTruthy();
    fireEvent.click(within(ways).getByRole("radio", { name: "Question and answer" }));
    expect(screen.getByLabelText("What callers ask")).toBeTruthy();
  });

  it("says before a PDF or a link is sent what we do with it, and promises nothing the row may deny", async () => {
    await renderKnowledge();
    fireEvent.click(await screen.findByRole("radio", { name: "Photo or file" }));
    // One short line each by default; the full sentence sits behind the ⓘ beside it.
    expect(screen.getByText("Scanned PDF pages are read too.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "About what you can send" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Website link" }));
    expect(screen.getByText("Your agents read that one page.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "About links" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /save link/i })).toBeTruthy();
  });

  it("keeps half-typed words when the owner looks at another way and comes back", async () => {
    await renderKnowledge();
    const box = (await screen.findByLabelText("What should your agents know?")) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "Open 9 to 9." } });
    fireEvent.click(screen.getByRole("radio", { name: "Website link" }));
    fireEvent.click(screen.getByRole("radio", { name: "Type or say it" }));
    expect((screen.getByLabelText("What should your agents know?") as HTMLTextAreaElement).value).toBe(
      "Open 9 to 9.",
    );
  });

  it("sends an empty knowledge list to the questions to answer, open on prices", async () => {
    await renderKnowledge({
      "/v1/teach/questions": {
        items: [
          {
            key: "pricing",
            question: "What do your products or services cost?",
            topic: "Pricing",
            why: "practice",
            callers: 0,
            times: 0,
            agent_ids: [],
            latest_call_id: null,
            latest_at: null,
            example: null,
            draft: null,
            draft_source_kind: null,
            draft_source_label: null,
            drafting: false,
          },
        ],
        open_count: 1,
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Answer the first questions" }));
    expect(
      (await screen.findByRole("tab", { name: "Questions to answer · 1" })).getAttribute("aria-selected"),
    ).toBe("true");
    expect(
      await screen.findByLabelText("Your answer to: What do your products or services cost?"),
    ).toBeTruthy();
  });
});

describe("what the agents know, grouped", () => {
  it("puts files and links in their own groups, each with a status that does not overclaim", async () => {
    await renderKnowledge({
      "/v1/kb/uploads": [
        upload({ id: "a", name: "Menu.docx", source_kind: "docx", filename: "Menu.docx" }),
        upload({ id: "b", name: "Brochure.pdf", read_state: "failed", read_detail: "This PDF is locked with a password." }),
        upload({
          id: "c",
          name: "Prices page",
          source_kind: "url",
          source_url: "https://example.in/p",
          filename: null,
          ingest_status: "error",
          ingest_detail: "Your agents could not read that page.",
        }),
        // History, not a row: the version that replaced it is the row.
        upload({ id: "d", name: "Old menu.docx", source_kind: "docx", review_state: "archived", is_live: false }),
      ],
    });
    const files = (await screen.findByRole("heading", { name: /^Files/ })).closest("section") as HTMLElement;
    const links = screen.getByRole("heading", { name: /^Links/ }).closest("section") as HTMLElement;

    const menu = within(files).getByText("Menu.docx").closest("li") as HTMLElement;
    expect(menu.textContent).toContain("In use");
    const brochure = within(files).getByText("Brochure.pdf").closest("li") as HTMLElement;
    expect(brochure.textContent).toContain("Couldn't read");
    expect(brochure.textContent).not.toContain("In use");
    const page = within(links).getByText("Prices page").closest("li") as HTMLElement;
    expect(page.textContent).toContain("Agents couldn't read it");
    expect(page.textContent).not.toContain("In use");
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
    expect(await screen.findByText("Nothing added to Knowledge yet")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /^Links/ })).toBeNull();
  });
});
