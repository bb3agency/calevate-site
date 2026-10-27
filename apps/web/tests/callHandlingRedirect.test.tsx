import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Agent } from "@/lib/api/agents";

const permanentRedirect = vi.fn((to: string) => {
  throw new Error(`NEXT_REDIRECT ${to}`);
});
const replace = vi.fn();
let search = new URLSearchParams("");

vi.mock("next/navigation", () => ({
  permanentRedirect: (to: string) => permanentRedirect(to),
  useSearchParams: () => search,
  useRouter: () => ({ replace }),
}));

const { default: CallHandlingRedirect } = await import("@/app/c/[slug]/settings/call-handling/page");
const { useOpenOnlyAgentSettings } = await import("@/app/c/[slug]/agents/openSettings");

/**
 * The account call-handling page is gone (founder, 27 Oct 2026): call handling is set on each
 * agent's Settings. Old links land on the agents list, which steps straight to the agent's
 * Settings when there is only one.
 */
async function landing(query: Record<string, string | string[] | undefined>): Promise<string> {
  permanentRedirect.mockClear();
  await expect(
    CallHandlingRedirect({ params: Promise.resolve({ slug: "acme" }), searchParams: Promise.resolve(query) }),
  ).rejects.toThrow("NEXT_REDIRECT");
  return permanentRedirect.mock.calls[0][0];
}

const agent = (id: string): Pick<Agent, "id"> => ({ id });
const plain = (path: string) => path;

describe("the retired call handling page", () => {
  it("lands, permanently, on the agents list asking for call handling", async () => {
    expect(await landing({})).toBe("/c/acme/agents?open=call-handling");
  });

  it("carries the view-as marker and every other parameter", async () => {
    expect(await landing({ view: "admin", tag: ["a", "b"] })).toBe(
      "/c/acme/agents?view=admin&tag=a&tag=b&open=call-handling",
    );
  });
});

describe("the agents list asked for call handling", () => {
  it("opens the only agent's Settings", () => {
    replace.mockClear();
    search = new URLSearchParams("open=call-handling");
    renderHook(() => useOpenOnlyAgentSettings([agent("agent-1")], "acme", plain));
    expect(replace).toHaveBeenCalledWith("/c/acme/agents/agent-1?section=settings");
  });

  it("keeps an operator's view-as session on the hop", () => {
    replace.mockClear();
    search = new URLSearchParams("open=call-handling&view=admin");
    renderHook(() =>
      useOpenOnlyAgentSettings([agent("agent-1")], "acme", (path) => `${path}&view=admin`),
    );
    expect(replace).toHaveBeenCalledWith("/c/acme/agents/agent-1?section=settings&view=admin");
  });

  it("stays on the list when there are several agents to choose from, or it was not asked", () => {
    replace.mockClear();
    search = new URLSearchParams("open=call-handling");
    renderHook(() => useOpenOnlyAgentSettings([agent("agent-1"), agent("agent-2")], "acme", plain));
    search = new URLSearchParams("");
    renderHook(() => useOpenOnlyAgentSettings([agent("agent-1")], "acme", plain));
    expect(replace).not.toHaveBeenCalled();
  });
});
