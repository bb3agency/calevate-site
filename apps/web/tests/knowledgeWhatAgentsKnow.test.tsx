import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import { knowledgeTally } from "@/app/c/[slug]/knowledge/WhatItKnows";
import type { Me } from "@/lib/api/client";
import type { KbChunk, KbUpload } from "@/lib/api/kb";

import { businessProfileFixture } from "./businessProfileFixture";
import { renderClientPage, type Routes } from "./harness";

/**
 * THE PAGE SHOWS WHAT THE AGENTS KNOW, NOT ONLY WHAT WAS SENT (founder, 6 Nov 2026). A guide
 * that taught the agents a dozen things used to read as one row with a size; the hours,
 * addresses and team every agent is told were not on the page at all; and each agent's own
 * script had no pointer from it.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "kb:write", "org:manage"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const GUIDE: KbUpload = {
  id: "u1",
  source_id: "s1",
  facts_count: 2,
  name: "Voice agent guide.md",
  source_kind: "txt",
  ingest_status: "processed",
  ingest_detail: null,
  review_state: "approved",
  is_live: true,
  version: 1,
  filename: "guide.md",
  byte_size: 21_000,
  source_url: null,
  text_provenance: "parsed",
  change_detected_at: null,
  read_state: null,
  read_detail: null,
  page_count: null,
  reaches_agents: true,
  call_instructions: [
    { section: "How the agent should speak", text: "Say who you are." },
    { section: null, text: "Ask whether now is a good time." },
  ],
};

const CHUNKS: KbChunk[] = [
  {
    idx: 0,
    content: "Installing on Android:\nOpen the Play Store and search for the app.",
    chars: 60,
    section: "Installing on Android",
    body: "Open the Play Store and search for the app.",
    gloss: null,
    gloss_model: null,
  },
  {
    idx: 1,
    content: "Opening hours:\nWe help farmers from 9 to 6.",
    chars: 40,
    section: "Opening hours",
    body: "We help farmers from 9 to 6.",
    gloss: null,
    gloss_model: null,
  },
];

async function renderKnowledge(over: Routes = {}) {
  return await renderClientPage(<KnowledgePage />, {
    "/v1/me": ME,
    "/v1/kb/notes": { notes: [] },
    "/v1/kb/uploads": [GUIDE],
    "/v1/kb/uploads/u1": GUIDE,
    "/v1/kb/sources/s1/preview": CHUNKS,
    "/v1/teach/questions": { items: [], open_count: 0 },
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
    "/v1/kb/teach/open": { teaching: null },
    "/v1/business-profile": businessProfileFixture({
      services: [],
      faqs: [],
      staff: [{ name: "Ravi", role: "Support", pronunciation: null }],
    }),
    "/v1/agents": [],
    ...over,
  });
}

describe("what a file taught the agents", () => {
  it("counts what was read out of it, and opens it under its own headings", async () => {
    await renderKnowledge();
    expect(await screen.findByText("2 things learned · 2 call instructions")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Show what it learned" }));
    const learned = await screen.findByRole("list", { name: "What it learned" });
    expect(within(learned).getByText("Installing on Android")).toBeTruthy();
    expect(within(learned).getByText("Open the Play Store and search for the app.")).toBeTruthy();
    // The heading is printed once, as a heading, not again at the top of the text.
    expect(within(learned).getAllByText(/Installing on Android/)).toHaveLength(1);
  });

  it("shows the call instructions in place, and says they are not said on calls yet", async () => {
    await renderKnowledge();
    fireEvent.click(await screen.findByRole("button", { name: "Show call instructions" }));
    const list = screen.getByRole("list", { name: "Call instructions in Voice agent guide.md" });
    expect(within(list).getByText("Say who you are.")).toBeTruthy();
    expect(screen.getByText("Not said on calls until they are in a script.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Use in call scripts" })).toBeTruthy();
  });
});

describe("the count at the top", () => {
  it("adds up every source the agents use, and jumps to each", async () => {
    await renderKnowledge();
    // Hours (one line), one address, one team member, and two things from the file.
    expect(await screen.findByText("5 things your agents know")).toBeTruthy();
    const where = screen.getByRole("list", { name: "Where it came from" });
    expect(within(where).getByRole("link", { name: "3 from business details" }).getAttribute("href")).toBe(
      "#knows-business",
    );
    expect(within(where).getByRole("link", { name: "2 from 1 file" })).toBeTruthy();
  });

  it("counts nothing from a file the agents do not use yet", () => {
    const waiting = { ...GUIDE, is_live: false, review_state: "pending_approval" };
    const tally = knowledgeTally({ pinned: 0, facts: 0, profile: undefined, files: [waiting], links: [], notes: 0 });
    expect(tally.total).toBe(0);
    expect(tally.files).toBe(0);
  });
});

describe("what the business details tell every agent", () => {
  it("lists hours, addresses and the team, not only offers and questions", async () => {
    await renderKnowledge();
    expect(await screen.findByText("Hours, places and team")).toBeTruthy();
    expect(screen.getByText("Monday 09:00–18:00")).toBeTruthy();
    expect(screen.getByText("1 Test Road, Hyderabad")).toBeTruthy();
    expect(screen.getByText("Ravi")).toBeTruthy();
  });
});

describe("what one agent knows alone", () => {
  it("names each agent once, with a way to its own script", async () => {
    await renderKnowledge({
      "/v1/agents": [{ id: "a1", name: "Front desk", status: "live", caller_memory_enabled: true, caller_memory_paused: false }],
    });
    const agents = await screen.findByRole("list", { name: "Agents" });
    expect(within(agents).getByText("Front desk")).toBeTruthy();
    expect(within(agents).getByText("Its script. Also remembers each caller.")).toBeTruthy();
    expect(within(agents).getByRole("link", { name: "Open its script" }).getAttribute("href")).toContain(
      "/agents/a1?section=script",
    );
  });
});
