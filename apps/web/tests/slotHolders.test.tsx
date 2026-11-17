import { render, screen, within } from "@testing-library/react";
import type { UseMutationResult } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { blockerNote } from "@/app/c/[slug]/campaigns/blockerCopy";
import { TestCallForm } from "@/app/c/[slug]/campaigns/CampaignBoosters";
import { ApiProblem } from "@/lib/api/client";

vi.mock("@/lib/api/session", () => ({
  useClientRealm: () => ({ href: (path: string) => path, session: { orgSlug: "rytu-khata" } }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
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
  { kind: "campaign", id: "c-diwali", name: "Diwali reminders", removing: false },
  { kind: "campaign", id: "c-old", name: "Old list", removing: true },
] as const;

function refused(context: "test_call" | "start"): ApiProblem {
  return new ApiProblem(422, {
    type: "https://calevate.tech/problems/engine_agent_allowance_full",
    title: "We cannot do that",
    detail: "Test calls need a free calling setup. Your account can have 2, and both are in use: 1 agent.",
    kind: "business_rule",
    retryable: false,
    remediation: "Archive an inbound line you no longer use, or stop a campaign, to free one.",
    context,
    limit: 2,
    holders: HOLDERS,
  });
}

function formWith(error: unknown, fromTestLine = false) {
  const call = {
    error,
    data: undefined,
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
      fromTestLine={fromTestLine}
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
    expect(list.textContent).toContain("It answers your calls until its Inbound line is live.");
    expect(list.textContent).toContain("Archive the line to free it.");
    expect(list.textContent).toContain("Stop the campaign to free it.");
    expect(list.textContent).toContain("Being removed.");
  });

  it("offers a real button to ask for a higher limit, naming the account", () => {
    formWith(refused("test_call"));
    const ask = screen.getByRole("link", { name: "Ask us to raise your limit" });
    const href = ask.getAttribute("href") ?? "";
    expect(href).toMatch(/^mailto:/);
    expect(decodeURIComponent(href)).toContain("subject=Raise our calling setup limit (rytu-khata)");
  });

  it("says so when the test rings from our test number", () => {
    formWith(null, true);
    expect(screen.getByText("It rings from our test number.")).toBeTruthy();
  });
});

describe("the launch checklist's line for a full workspace", () => {
  it("speaks of starting and of setups, not of calls at once", () => {
    const note = blockerNote("engine_agent_allowance_full", { promotionalOpen: null });
    expect(note?.text).toBe("Starting needs a free calling setup. All are in use.");
    expect(`${note?.text} ${note?.why ?? ""}`).not.toMatch(/at once|calling agents/);
  });
});
