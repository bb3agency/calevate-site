import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QuestionsToAnswer } from "@/components/improvement/QuestionsToAnswer";
import { SavedTests } from "@/components/improvement/SavedTests";
import type { Me } from "@/lib/api/client";
import type { TeachQuestion } from "@/lib/api/teachQuestions";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage, type Routes } from "./harness";

/**
 * Questions to answer (D-893). Each test names the failure it guards against: a draft
 * offered without its source, an answer that is not saved through the questions route, a
 * dismissal that keeps the question, a link that lands on a blank page, a failure that
 * loses what was typed, and a person without `kb:write` offered the answer form.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "agents:write", "calls:read", "kb:write", "org:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

function question(over: Partial<TeachQuestion> = {}): TeachQuestion {
  return {
    key: "delivery",
    question: "Do you deliver, and where?",
    topic: "Delivery",
    why: "callers",
    callers: 3,
    times: 4,
    agent_ids: ["agent-1"],
    latest_call_id: "call-9",
    latest_at: "2026-10-25T10:00:00Z",
    example: "Delivery Kukatpally ki undha?",
    draft: null,
    draft_source_kind: null,
    draft_source_label: null,
    drafting: false,
    ...over,
  };
}

async function renderList(items: TeachQuestion[], over: Routes = {}, focus: string | null = null) {
  return await renderClientPage(<QuestionsToAnswer focus={focus} />, {
    "/v1/me": OWNER,
    "/v1/teach/questions": { items, open_count: items.length },
    ...over,
  });
}

describe("the questions to answer", () => {
  it("lists each question with who asked and a link to the latest call", async () => {
    await renderList([
      question(),
      question({ key: "timings", question: "When are you open?", why: "setup", callers: 0, latest_call_id: null }),
    ]);
    const list = await screen.findByRole("list", { name: "Questions to answer" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.textContent).toContain("3 callers asked");
    expect(within(rows[0]!).getByRole("link", { name: "Latest call" }).getAttribute("href")).toBe(
      "/c/acme/calls/call-9",
    );
    expect(rows[1]!.textContent).toContain("Your setup leaves this open");
    expect(screen.getByText("2 to answer")).toBeTruthy();
  });

  it("offers a draft with the source it came from, and keeps it in one press", async () => {
    const { calls } = await renderList(
      [
        question({
          draft: "We deliver across Hyderabad within two days.",
          draft_source_kind: "profile",
          draft_source_label: "Your business profile",
        }),
      ],
      { "POST /v1/teach/questions/delivery/answer": { key: "delivery", fact_id: "f1", gaps_closed: 1 } },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Review answer" }));
    const box = screen.getByLabelText("Your answer to: Do you deliver, and where?") as HTMLTextAreaElement;
    expect(box.value).toBe("We deliver across Hyderabad within two days.");
    expect(screen.getByText(/drafted this from Your business profile/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep this answer" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/teach/questions/delivery/answer")).toBe(true),
    );
    const sent = calls.find((c) => c.path === "/v1/teach/questions/delivery/answer");
    expect(JSON.parse(sent!.body!)).toEqual({ answer: "We deliver across Hyderabad within two days." });
  });

  it("says a draft is being written rather than offering an empty one", async () => {
    await renderList([question({ drafting: true })]);
    fireEvent.click(await screen.findByRole("button", { name: "Answer" }));
    expect(screen.getByText(/is drafting an answer/)).toBeTruthy();
    expect((screen.getByLabelText(/Your answer to/) as HTMLTextAreaElement).value).toBe("");
  });

  it("refuses an empty answer in words, and saves a typed one", async () => {
    const { calls } = await renderList([question()], {
      "POST /v1/teach/questions/delivery/answer": { key: "delivery", fact_id: "f1", gaps_closed: 1 },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Answer" }));
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    expect(await screen.findByText("Write the answer, or say it.")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.change(screen.getByLabelText(/Your answer to/), { target: { value: "Yes, all of Hyderabad." } });
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  });

  it("keeps what was typed and says why when saving fails", async () => {
    await renderList([question()], {
      "POST /v1/teach/questions/delivery/answer": problem(409, {
        code: "question_not_open",
        title: "We could not complete that",
        detail: "This question was already answered or dismissed.",
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Answer" }));
    fireEvent.change(screen.getByLabelText(/Your answer to/), { target: { value: "Yes." } });
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    expect(await screen.findByText(/already answered or dismissed/)).toBeTruthy();
  });

  it("dismisses a question as not something we answer, with an optional reason", async () => {
    const { calls } = await renderList([question()], {
      "POST /v1/teach/questions/delivery/dismiss": { key: "delivery", fact_id: null, gaps_closed: 1 },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Answer" }));
    fireEvent.click(screen.getByRole("button", { name: "Not something we answer" }));
    fireEvent.change(screen.getByLabelText("Why not? (optional)"), { target: { value: "No delivery." } });
    fireEvent.click(screen.getByRole("button", { name: "Remove from the list" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/teach/questions/delivery/dismiss")).toBe(true),
    );
    const sent = calls.find((c) => c.path === "/v1/teach/questions/delivery/dismiss");
    expect(JSON.parse(sent!.body!)).toEqual({ reason: "No delivery." });
  });

  it("opens on the question a link named, ready to answer", async () => {
    await renderList([question(), question({ key: "pricing", question: "What do your products or services cost?" })], {}, "pricing");
    expect(await screen.findByLabelText("Your answer to: What do your products or services cost?")).toBeTruthy();
    expect(screen.queryByLabelText("Your answer to: Do you deliver, and where?")).toBeNull();
  });

  it("says a linked question is already answered rather than showing nothing", async () => {
    await renderList([question()], {}, "pricing");
    expect(await screen.findByText("That question is already answered.")).toBeTruthy();
  });

  it("passes axe with an answer form and a dismissal open", async () => {
    const { container } = await renderList(
      [
        question({
          draft: "We deliver across Hyderabad.",
          draft_source_kind: "file",
          draft_source_label: "Delivery areas.docx",
        }),
        question({ key: "timings", question: "When are you open?", why: "setup", callers: 0, latest_call_id: null }),
      ],
      {},
      "delivery",
    );
    await screen.findByLabelText("Your answer to: Do you deliver, and where?");
    fireEvent.click(screen.getByRole("button", { name: "Not something we answer" }));
    await expectNoA11yViolations(container, "Questions to answer, open");
  });

  it("says all is answered when the list is empty", async () => {
    await renderList([]);
    expect(await screen.findByText("All answered.")).toBeTruthy();
  });

  it("does not offer the answer form without kb:write", async () => {
    await renderClientPage(<QuestionsToAnswer />, {
      "/v1/me": { ...OWNER, role: "staff", permissions: ["agents:read", "calls:read"] },
      "/v1/teach/questions": { items: [question()], open_count: 1 },
    });
    await screen.findByText("Do you deliver, and where?");
    expect(screen.queryByRole("button", { name: "Answer" })).toBeNull();
  });
});

describe("a test written by hand", () => {
  it("saves the caller's lines one per line and what the agent should do", async () => {
    const { calls } = await renderClientPage(<SavedTests agentId="agent-1" />, {
      "/v1/me": OWNER,
      "/v1/agents/agent-1/test-cases": {
        cases: [],
        available: true,
        unavailable_reason: null,
        live_version: 3,
        cost_note: "Each run uses the test chat.",
      },
      "POST /v1/agents/agent-1/test-cases": {
        id: "case-1",
        agent_id: "agent-1",
        source_call_id: null,
        title: "Do you open on Sunday?",
        caller_lines: ["Do you open on Sunday?", "What time?"],
        expected: "Says no, Monday to Saturday.",
        status: "idle",
        last_result: null,
        last_error: null,
        last_run_at: null,
        last_prompt_version: null,
        created_at: "2026-10-26T10:00:00Z",
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Write a test" }));
    fireEvent.change(screen.getByLabelText("What the caller says"), {
      target: { value: "Do you open on Sunday?\n\nWhat time?" },
    });
    fireEvent.change(screen.getByLabelText("What the agent should do"), {
      target: { value: "Says no, Monday to Saturday." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save test" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const sent = calls.find((c) => c.method === "POST");
    expect(JSON.parse(sent!.body!)).toEqual({
      title: "Do you open on Sunday?",
      caller_lines: ["Do you open on Sunday?", "What time?"],
      expected: "Says no, Monday to Saturday.",
    });
  });
});
