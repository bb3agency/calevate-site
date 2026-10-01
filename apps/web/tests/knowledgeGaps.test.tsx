import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeGaps } from "@/app/c/[slug]/KnowledgeGaps";
import type { Me } from "@/lib/api/client";
import type { KnowledgeGap, KnowledgeGapList } from "@/lib/api/knowledgeGaps";

import { problem, renderClientPage } from "./harness";

/**
 * The URGENT "where the agents struggled" card — the dashboard-home insights surface.
 *
 * What a wrong render costs, ranked:
 *
 * 1. **A raw phone number in a quote.** The card shows the agent's deflection, which is
 *    server-redacted; the screen must render exactly what the API sent and add nothing.
 * 2. **"Nothing unanswered" while gaps exist.** The empty state is a claim about the
 *    business and must only appear when the server returned no open gaps.
 * 3. **A Dismiss/Teach button that does not call the API.** The two actions are the whole
 *    point of the card; each must POST to its endpoint.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "kb:write"],
  impersonating: false,
  withheld_acts: [],
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

const GAP: KnowledgeGap = {
  id: "0192f0aa-1111-7000-8000-000000000001",
  agent_id: "0192f0aa-2222-7000-8000-000000000002",
  agent_name: "Reception",
  topic_key: "pricing",
  topic_label: "Pricing",
  status: "open",
  signal: "dont_know",
  occurrence_count: 3,
  call_count: 2,
  example_question: "How much is the consultation?",
  example_answer: "I don't know the price, I'll WhatsApp you.",
  first_seen_at: "2026-08-20T04:30:00Z",
  last_seen_at: "2026-08-23T04:30:00Z",
};

function list(over: Partial<KnowledgeGapList> = {}): KnowledgeGapList {
  return { items: [GAP], open_count: 1, total: 1, ...over };
}

const GAPS_ROUTE = "/v1/knowledge-gaps?status=open&limit=20";

/**
 * Hold every POST until the screen has painted what the optimistic update did. The stub
 * otherwise rejects inside the same macrotask, the rollback lands before React renders
 * the removal, and the row is never unmounted — which is not what a real network does.
 */
function writesTakeARealRoundTrip(): void {
  const answer = globalThis.fetch;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") await new Promise((resolve) => setTimeout(resolve, 50));
    return answer(input, init);
  });
}
const page = <KnowledgeGaps />;

function routes(over: Record<string, unknown> = {}) {
  return { "/v1/me": ME, [GAPS_ROUTE]: list(), ...over };
}

describe("the knowledge-gaps card", () => {
  it("shows the topic, the badge, the redacted quote and the N× on M calls", async () => {
    await renderClientPage(page, routes());

    expect(await screen.findByText("Pricing")).toBeTruthy();
    // Sentence case: the console no longer sets labels in tracked capitals.
    expect(screen.getByText("Didn't know this")).toBeTruthy();
    expect(
      screen.getByText("I don't know the price, I'll WhatsApp you."),
    ).toBeTruthy();
    expect(screen.getByText("3× on 2 calls")).toBeTruthy();
    // The agent name is shown on the org-wide card so gaps from several agents are
    // distinguishable.
    expect(screen.getByText("Reception")).toBeTruthy();
  });

  it("says nothing is unanswered only when the server returned no open gaps", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [GAPS_ROUTE]: list({ items: [], open_count: 0, total: 0 }) }),
    );
    expect(await screen.findByText("Nothing unanswered")).toBeTruthy();
    expect(container.textContent).not.toContain("Didn't know this");
  });

  it("does not report calm when the request failed", async () => {
    const { container } = await renderClientPage(page, {
      "/v1/me": ME,
      [GAPS_ROUTE]: problem(503, { title: "Service unavailable" }),
    });
    // A 503 surfaces as an alert, never as the empty state.
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("Nothing unanswered");
  });

  it("Dismiss posts to the dismiss endpoint", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ [`POST /v1/knowledge-gaps/${GAP.id}/dismiss`]: GAP }),
    );
    fireEvent.click(await screen.findByText("Dismiss"));
    // The POST is the whole action; the optimistic removal + invalidation follow it.
    await screen.findByText("Nothing unanswered").catch(() => undefined);
    expect(
      calls.some((c) => c.path.endsWith(`/dismiss`) && c.method === "POST"),
    ).toBe(true);
  });

  it("Teach opens a form and posts the answer", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        [`POST /v1/knowledge-gaps/${GAP.id}/teach`]: {
          ...GAP,
          status: "taught",
        },
      }),
    );
    fireEvent.click(await screen.findByText("Teach this"));
    const box = await screen.findByLabelText(
      "What should the agent say next time?",
    );
    fireEvent.change(box, { target: { value: "It is 500 rupees." } });
    fireEvent.click(screen.getByText("Save answer"));
    await screen.findByText("Nothing unanswered").catch(() => undefined);
    const teach = calls.find(
      (c) => c.path.endsWith(`/teach`) && c.method === "POST",
    );
    expect(teach).toBeTruthy();
    expect(teach?.body).toContain("It is 500 rupees.");
  });

  /**
   * The optimistic removal UNMOUNTS the row, and the row owned the mutation — so when the
   * write failed and the list was put back, a fresh row mounted with a fresh mutation and
   * no error. The card reappeared as if nothing had been tried: a dismiss that did not
   * happen, told to nobody, and a typed answer thrown away.
   */
  it("says a Dismiss failed when the card comes back, rather than reappearing silently", async () => {
    await renderClientPage(
      page,
      routes({
        [`POST /v1/knowledge-gaps/${GAP.id}/dismiss`]: problem(409, {
          title: "Already changed",
          detail: "Somebody else already taught this one.",
        }),
      }),
    );
    writesTakeARealRoundTrip();
    fireEvent.click(await screen.findByText("Dismiss"));
    await screen.findByText("Nothing unanswered");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Somebody else already taught this one.");
    // The card is back, with its actions, so the person can act on what they just read.
    expect(screen.getByText("Pricing")).toBeTruthy();
    expect(screen.getByText("Dismiss")).toBeTruthy();
  });

  it("keeps the typed answer and says why when a Teach fails", async () => {
    await renderClientPage(
      page,
      routes({
        [`POST /v1/knowledge-gaps/${GAP.id}/teach`]: problem(503, {
          title: "Service unavailable",
          detail: "We could not save that answer.",
        }),
      }),
    );
    fireEvent.click(await screen.findByText("Teach this"));
    fireEvent.change(
      await screen.findByLabelText("What should the agent say next time?"),
      { target: { value: "It is 500 rupees." } },
    );
    writesTakeARealRoundTrip();
    fireEvent.click(screen.getByText("Save answer"));
    await screen.findByText("Nothing unanswered");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("We could not save that answer.");
    const box = screen.getByLabelText<HTMLTextAreaElement>(
      "What should the agent say next time?",
    );
    expect(box.value).toBe("It is 500 rupees.");
  });

  it("does not offer Teach or Dismiss to a staff member without kb:write", async () => {
    // `/v1/knowledge-gaps` is `calls:read`, so staff see the card; the two actions are
    // `kb:write`, which staff hold only when their owner switched curation on.
    const staff: Me = { ...ME, role: "staff", permissions: ["calls:read"] };
    const { calls } = await renderClientPage(page, routes({ "/v1/me": staff }));

    expect(await screen.findByText("Pricing")).toBeTruthy();
    expect(
      await screen.findByText("Only an account owner can teach or dismiss these."),
    ).toBeTruthy();
    expect(screen.queryByText("Teach this")).toBeNull();
    expect(screen.queryByText("Dismiss")).toBeNull();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});
