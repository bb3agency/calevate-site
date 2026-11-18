import { render, screen, within } from "@testing-library/react";
import type { UseMutationResult } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { blockerNote } from "@/app/c/[slug]/campaigns/blockerCopy";
import { TestCallForm } from "@/app/c/[slug]/campaigns/CampaignBoosters";
import { ApiProblem } from "@/lib/api/client";

vi.mock("@/lib/api/session", () => ({
  useClientRealm: () => ({
    href: (path: string) => path,
    session: { orgSlug: "rytu-khata" },
  }),
}));
/** What `GET /v1/trial/rings-from` answered; undefined while it has not. */
const ringsFrom = vi.hoisted(() => ({
  ownNumber: undefined as string | null | undefined,
  rest: {} as { setups_busy?: boolean; unavailable?: string | null },
}));
vi.mock("@/lib/api/trialCalls", async (original) => ({
  ...(await original<typeof import("@/lib/api/trialCalls")>()),
  useTestRingsFrom: () => ({
    data:
      ringsFrom.ownNumber === undefined
        ? undefined
        : { own_number: ringsFrom.ownNumber, ...ringsFrom.rest },
  }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/c/rytu-khata/campaigns/c1",
  useSearchParams: () => new URLSearchParams(),
}));

/**
 * NO FREE CALLING SETUP (D-1018). The founder read "can run 2 calling agents at once ... then
 * press Start again" under a TEST CALL: the limit is how many setups may exist, not calls at
 * once, and a test call has no Start. The refusal names what holds each setup, as a link to
 * where it is freed, and "ask us to raise your limit" is a real button.
 */

const HOLDERS = [
  { kind: "agent", id: "a-varsha", name: "Varsha", removing: false },
  { kind: "inbound_line", id: "l-front", name: "Front desk", removing: false },
  {
    kind: "campaign",
    id: "c-diwali",
    name: "Diwali reminders",
    removing: false,
  },
  { kind: "campaign", id: "c-old", name: "Old list", removing: true },
  { kind: "test_call", id: "a-anjali", name: "Anjali", removing: false },
] as const;

function refused(context: "test_call" | "start"): ApiProblem {
  return new ApiProblem(422, {
    type: "https://calevate.tech/problems/engine_agent_allowance_full",
    title: "We cannot do that",
    detail:
      "Test calls need a free calling setup. Your account can have 2, and both are in use: 1 agent.",
    kind: "business_rule",
    retryable: false,
    remediation:
      "Archive an inbound line you no longer use, or stop a campaign, to free one.",
    context,
    limit: 2,
    holders: HOLDERS,
  });
}

function formWith(
  error: unknown,
  {
    ownNumber,
    data,
    rest = {},
  }: {
    ownNumber?: string | null;
    data?: { status: "queued"; call_id: string; shared_fallback: boolean };
    rest?: { setups_busy?: boolean; unavailable?: string | null };
  } = {},
) {
  ringsFrom.ownNumber = ownNumber;
  ringsFrom.rest = rest;
  const call = {
    error,
    data,
    isPending: false,
    mutate: vi.fn(),
  } as unknown as UseMutationResult<
    { status: "queued" | "blocked" },
    Error,
    { number: string; numberIsMine: boolean }
  >;
  return render(
    <TestCallForm
      slug="rytu-khata"
      call={call}
      saved={{ data: { numbers: [] }, error: null, refetch: vi.fn() } as never}
      canWrite
      ringsFrom={{ agentId: "a-varsha", campaignId: "c1" }}
    />,
  );
}

describe("a test call with no free calling setup", () => {
  it("says a test call needs one, without Start or 'at once'", () => {
    formWith(refused("test_call"));
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(
      "Test calls need a free calling setup. Your account can have 2, and both are in use:",
    );
    expect(alert.textContent).not.toMatch(/Start|at once/);
  });

  it("lists each holder as a link with what frees it", () => {
    formWith(refused("test_call"));
    const list = screen.getByRole("list", { name: "Calling setups in use" });
    const links = within(list).getAllByRole("link");
    const hrefs = links.map((link) => link.getAttribute("href"));
    expect(hrefs).toEqual(
      expect.arrayContaining([
        "/c/rytu-khata/agents/a-varsha",
        "/c/rytu-khata/inbound",
        "/c/rytu-khata/inbound/l-front",
        "/c/rytu-khata/campaigns/c-diwali",
        "/c/rytu-khata/campaigns/c-old",
      ]),
    );
    expect(list.textContent).toContain(
      "It answers your calls until its Inbound line is live.",
    );
    expect(list.textContent).toContain("Archive the line to free it.");
    expect(list.textContent).toContain("Stop the campaign to free it.");
    expect(list.textContent).toContain("Being removed.");
    // A test call's own setup in the workspace (D-1020) goes back by itself.
    expect(hrefs).toContain("/c/rytu-khata/agents/a-anjali");
    expect(list.textContent).toContain(
      "Freed an hour after the last test call.",
    );
  });

  it("offers a real button to ask for a higher limit, naming the account", () => {
    formWith(refused("test_call"));
    const ask = screen.getByRole("link", {
      name: "Ask us to raise your limit",
    });
    const href = ask.getAttribute("href") ?? "";
    expect(href).toMatch(/^mailto:/);
    expect(decodeURIComponent(href)).toContain(
      "subject=Raise our calling setup limit (rytu-khata)",
    );
  });

  it("says so when the test rings from our test number", () => {
    formWith(null, { ownNumber: null });
    expect(screen.getByText("It rings from our test number.")).toBeTruthy();
  });
});

describe("where a test call rings from (D-1020)", () => {
  it("names the account's own number before the call", () => {
    formWith(null, { ownNumber: "+919876543210" });
    const note = screen.getByText(/It rings from your number/);
    expect(note.textContent).toBe("It rings from your number +91 98765 43210.");
    expect(screen.queryByText("It rings from our test number.")).toBeNull();
  });

  it("says before the call that both setups are in use, not that its own number rings", () => {
    formWith(null, { ownNumber: null, rest: { setups_busy: true } });
    expect(
      screen.getByText(
        "It rings from our test number: both your calling setups are in use.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/It rings from your number/)).toBeNull();
  });

  it("says why a test cannot ring at all when no setup is free and nothing to fall back to", () => {
    const why =
      "Test calls need a free calling setup. Your account can have 2, and both are in use: 2 agents.";
    formWith(null, { ownNumber: null, rest: { unavailable: why } });
    expect(screen.getByRole("status").textContent).toBe(why);
    expect(screen.queryByText(/It rings from/)).toBeNull();
  });

  it("says nothing about the number until the server has said", () => {
    formWith(null);
    expect(screen.queryByText(/It rings from/)).toBeNull();
  });

  it("says why a call rang from our test number when the slots were busy", () => {
    formWith(null, {
      ownNumber: "+919876543210",
      data: { status: "queued", call_id: "k1", shared_fallback: true },
    });
    expect(
      screen.getByText(
        "Rang from our test number: both your calling slots were busy.",
      ),
    ).toBeTruthy();
  });

  it("says nothing of a fallback when there was none", () => {
    formWith(null, {
      ownNumber: "+919876543210",
      data: { status: "queued", call_id: "k1", shared_fallback: false },
    });
    expect(screen.queryByText(/both your calling slots were busy/)).toBeNull();
  });
});

describe("the launch checklist's line for a full workspace", () => {
  it("speaks of starting and of setups, not of calls at once", () => {
    const note = blockerNote("engine_agent_allowance_full", {
      promotionalOpen: null,
    });
    expect(note?.text).toBe(
      "Starting needs a free calling setup. All are in use.",
    );
    expect(`${note?.text} ${note?.why ?? ""}`).not.toMatch(
      /at once|calling agents/,
    );
  });
});
