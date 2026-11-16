import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NewAgentPage from "@/app/c/[slug]/agents/new/page";
import { ENGINE_CATALOGUE_PATH } from "@/lib/api/engineCatalogue";
import type { PendingState } from "@/lib/api/publishing";

import { operatorEngineCatalogue } from "./fixtures/engineCatalogue";
import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { problem, renderClientPage, type Routes } from "./harness";

/**
 * NEW AGENT: NAME, VOICE, DONE (founder, 16 Nov 2026). An agent is staff with no script of its
 * own, so step 1 creates it from a name and a language alone (able to do both jobs), the voice
 * step uses the agent's own picker and save, and the finish gives it a job: a new Inbound
 * line in its voice, or a new campaign with it as the agent.
 */

const push = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/c/acme/agents/new",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push,
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const page = <NewAgentPage params={Promise.resolve({ slug: "acme" })} />;

const AGENT = "agent-9";
const BASE = `/v1/agents/${AGENT}`;

const PENDING: PendingState = {
  agent_id: AGENT,
  agent_status: "draft",
  published: false,
  has_pending: false,
  pending: [],
  effective_call_cap_s: 600,
  call_cap_is_platform_default: true,
  worst_case_call_cost_inr: "65.00",
  precedence_rule: "Script decides content, rules decide conduct, voice only changes delivery.",
  voice_tier_rates: [
    { voice_tier: "clear", label: "Clear", inr_per_min: "4.5000", further_open_lots: 0 },
    { voice_tier: "studio", label: "Studio", inr_per_min: "6.0000", further_open_lots: 0 },
  ],
  voice: { configured: null, live: null, republish_required: false, unnamed_note: null, headline: "No voice has been set on this agent." },
  engine_verification: {
    state: "unverified",
    confirmed: false,
    publishable: true,
    verified_at: null,
    headline: "Not on the voice platform yet.",
  },
};

const created = agentRow({
  id: AGENT,
  name: "Reception",
  direction: "both",
  status: "draft",
  published: false,
  inbound_number_count: 0,
  engine_voice_id: null,
});

function routes(over: Routes = {}): Routes {
  return {
    "/v1/me": OWNER_ME,
    "POST /v1/agents": { id: AGENT, name: "Reception" },
    [BASE]: created,
    [`${BASE}/pending`]: PENDING,
    [ENGINE_CATALOGUE_PATH]: operatorEngineCatalogue({ models: [] }),
    ...over,
  };
}

async function createAgent() {
  const create = (await screen.findByRole("button", { name: "Create agent" })) as HTMLButtonElement;
  await waitFor(() => expect(create.disabled).toBe(false));
  fireEvent.click(create);
  await screen.findByRole("heading", { name: "Pick a voice" });
}

async function toFinish() {
  await createAgent();
  fireEvent.click(screen.getByRole("button", { name: "Skip" }));
  return within(
    (await screen.findByRole("heading", { name: "Reception is set up" })).closest("section") as HTMLElement,
  );
}

describe("new agent: step 1, its name", () => {
  it("asks only a name and a language, with two steps on the rail", async () => {
    await renderClientPage(page, routes());
    expect(await screen.findByRole("heading", { name: "Your new agent" })).toBeTruthy();
    expect((screen.getByLabelText(/^Name/) as HTMLInputElement).value).toBe("Front desk");
    expect(screen.getByLabelText("Language")).toBeTruthy();
    expect(screen.queryByText(/How it opens a call/)).toBeNull();
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Name");
    expect(screen.queryByText("Script")).toBeNull();
  });

  it("says what every agent is born saying, before it exists", async () => {
    await renderClientPage(page, routes());
    expect(await screen.findByText("Always answers honestly if asked: AI? Recorded?")).toBeTruthy();
  });

  it("creates it able to do both jobs, with no job and no script, then moves on to its voice", async () => {
    const { calls } = await renderClientPage(page, routes());
    fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: "Reception" } });
    await createAgent();
    const body = JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}");
    expect(body).toEqual({ name: "Reception", direction: "both", language_primary: "te-IN" });
  });

  it("refuses an empty name in place and sends nothing", async () => {
    const { calls } = await renderClientPage(page, routes());
    fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));
    expect(await screen.findByText("Give this agent a name of at least two characters.")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the server's refusal inline and keeps what was typed", async () => {
    await renderClientPage(
      page,
      routes({ "POST /v1/agents": problem(409, { code: "account_closed", title: "This account is closed.", detail: "This account is closed." }) }),
    );
    const create = (await screen.findByRole("button", { name: "Create agent" })) as HTMLButtonElement;
    await waitFor(() => expect(create.disabled).toBe(false));
    fireEvent.click(create);
    expect(await screen.findByText(/This account is closed/)).toBeTruthy();
    expect((screen.getByLabelText(/^Name/) as HTMLInputElement).value).toBe("Front desk");
  });

  it("keeps which way it calls and the call limit one link away", async () => {
    await renderClientPage(page, routes({ "/v1/agents/lanes": { precedence_rule: "", lanes: [] } }));
    fireEvent.click(await screen.findByRole("button", { name: "Set which way it calls and its longest call" }));
    expect(await screen.findByText("What should it do?")).toBeTruthy();
  });
});

describe("new agent: step 2, the voice", () => {
  it("offers the enabled voices by rung with this account's rate for each", async () => {
    await renderClientPage(page, routes());
    await createAgent();
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Voice");
    expect(await screen.findByRole("group", { name: "Clear voices" })).toBeTruthy();
    expect(await screen.findByText("Clear — ₹4.5 / min")).toBeTruthy();
  });

  it("saves the picked voice with the agent's own write and finishes", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ [`PATCH ${BASE}`]: { ...created, engine_voice_id: "engine:anjali" } }),
    );
    await createAgent();
    fireEvent.click(await screen.findByRole("radio", { name: /Anjali/ }));
    fireEvent.click(screen.getByRole("button", { name: "Use this voice" }));
    expect(await screen.findByRole("heading", { name: "Reception is set up" })).toBeTruthy();
    expect(screen.getByText(/Voice chosen\./)).toBeTruthy();
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({ engine_voice_id: "engine:anjali" });
  });
});

describe("new agent: the finish gives it a job", () => {
  it("offers a new Inbound line or a new campaign in its voice, and no script", async () => {
    await renderClientPage(page, routes());
    const finish = await toFinish();
    expect(finish.getByText(/Voice not chosen yet\. Now give it a job\./)).toBeTruthy();
    expect(finish.getByRole("button", { name: /New Inbound line/ })).toBeTruthy();
    expect(finish.getByRole("link", { name: /New campaign/ }).getAttribute("href")).toBe(
      `/c/acme/campaigns/new?agent=${AGENT}`,
    );
    expect(finish.getByRole("link", { name: "Try it on your business" }).getAttribute("href")).toBe(
      `/c/acme/agents/${AGENT}?section=training`,
    );
    expect(finish.getByRole("link", { name: "Choose a voice" }).getAttribute("href")).toBe(
      `/c/acme/agents/${AGENT}?section=settings`,
    );
    expect(finish.queryByText(/script/i)).toBeNull();
  });

  it("makes the Inbound line in its voice and opens it", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ "POST /v1/inbound-lines": { id: "line-1", name: "Reception's line", agent_id: AGENT } }),
    );
    const finish = await toFinish();
    fireEvent.click(finish.getByRole("button", { name: /New Inbound line/ }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/c/acme/inbound/line-1"));
    expect(JSON.parse(calls.find((c) => c.path === "/v1/inbound-lines")?.body ?? "{}")).toEqual({ agent_id: AGENT });
  });
});
