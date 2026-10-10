import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NewAgentPage from "@/app/c/[slug]/agents/new/page";

import { OWNER_ME } from "./fixtures/sharedReads";
import { problem, renderClientPage } from "./harness";

/**
 * NEW AGENT: PICK A JOB, GET A READY AGENT (founder, REDESIGN-2).
 *
 * The page opens on two jobs; choosing one reads back what the server would make
 * (`GET /v1/agents/starters?job=…`); "Create agent" sends `starter` with the name the owner
 * kept or typed, and lands on the new agent's Script section to review it.
 */

const nav = vi.hoisted(() => ({ pushed: [] as string[] }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/c/acme/agents/new",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: (path: string) => nav.pushed.push(path),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const page = <NewAgentPage params={Promise.resolve({ slug: "acme" })} />;

const ANSWER = {
  job: "answer_calls",
  direction: "inbound",
  name_suggestion: "Front desk",
  opening_line: "Hello, you have reached Lakeview Properties. How can I help you today?",
  step_titles: [
    "Greet the caller",
    "Find out what they need",
    "Answer from what you know",
    "Take their name",
    "Confirm their number",
    "Close the call",
  ],
  captured_details: ["Their name", "What they want", "Best time to call back"],
};

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER_ME,
    "/v1/agents/starters?job=answer_calls": { vertical: "real_estate", starters: [ANSWER] },
    ...over,
  };
}

describe("new agent from a job", () => {
  it("offers the two jobs first, and nothing is read until one is chosen", async () => {
    const { calls } = await renderClientPage(page, routes());
    expect(await screen.findByRole("heading", { name: "What should your new agent do?" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Answer my calls/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Call my leads/ })).toBeTruthy();
    expect(calls.some((c) => c.path.includes("/starters"))).toBe(false);
  });

  it("previews the server's ready agent: its opening line, its steps in order and what it writes down", async () => {
    await renderClientPage(page, routes());
    fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));

    expect(await screen.findByText(ANSWER.opening_line)).toBeTruthy();
    const steps = screen.getByRole("heading", { name: "What it does on a call" }).nextElementSibling!;
    expect(Array.from(steps.querySelectorAll("li")).map((li) => li.textContent)).toEqual(ANSWER.step_titles);
    for (const detail of ANSWER.captured_details) expect(screen.getByText(detail)).toBeTruthy();
    expect((screen.getByLabelText(/^Name/) as HTMLInputElement).value).toBe("Front desk");
  });

  it("creates it from the job with the owner's name, then opens its script for review", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ "POST /v1/agents": { id: "agent-9", name: "Reception" } }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));
    const name = (await screen.findByLabelText(/^Name/)) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "Reception" } });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(nav.pushed).toContain("/c/acme/agents/agent-9?section=script&from=starter"));
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(post?.body ?? "{}")).toMatchObject({
      name: "Reception",
      starter: "answer_calls",
      direction: "inbound",
      language_primary: "te-IN",
    });
  });

  it("refuses an empty name in place and sends nothing", async () => {
    const { calls } = await renderClientPage(page, routes());
    fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));
    fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Give this agent a name of at least two characters.")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the server's refusal inline and keeps what was typed", async () => {
    await renderClientPage(
      page,
      routes({
        "POST /v1/agents": problem(422, { code: "starter_direction_mismatch", title: "This job sets which way its calls go.", detail: "This job sets which way its calls go.", fields: [{ name: "direction" }] }),
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));
    await screen.findByLabelText(/^Name/);
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    expect(await screen.findByText(/This job sets which way its calls go/)).toBeTruthy();
    expect((screen.getByLabelText(/^Name/) as HTMLInputElement).value).toBe("Front desk");
  });

  it("keeps the blank flow one link away", async () => {
    await renderClientPage(page, routes({ "/v1/agents/lanes": { precedence_rule: "", lanes: [] } }));
    fireEvent.click(await screen.findByRole("button", { name: "Start from a blank agent instead" }));
    expect(await screen.findByText("What should it do?")).toBeTruthy();
  });
});
