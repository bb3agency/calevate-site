import { describe, expect, it } from "vitest";

import {
  UNKNOWN_CAPABILITIES,
  accountCapabilities,
  allSupportAgents,
  leadNouns,
  leadWords,
} from "@/lib/businessCapabilities";
import { clientNavigation, inAccountWords } from "@/lib/clientNav";
import { clientPageTitle } from "@/lib/clientPageTitle";

/** E2E audit OB-9: the Go live guide was headed "Dashboard". */
describe("the client shell's page title", () => {
  it("names a screen the sidebar does not list", () => {
    expect(clientPageTitle("acme", "/c/acme/go-live")).toBe("Go live");
  });

  it("keeps the sidebar's label for a listed screen and Dashboard for home", () => {
    expect(clientPageTitle("acme", "/c/acme/billing")).toBe("Credits & billing");
    expect(clientPageTitle("acme", "/c/acme")).toBe("Dashboard");
  });

  it("does not take a listed screen's sub-path for an unlisted one", () => {
    expect(clientPageTitle("acme", "/c/acme/agents/go-live")).toBe("Agents");
  });
});

describe("an account whose agents all help customers", () => {
  const roster = (...purposes: ("sales" | "support")[]) => purposes.map((purpose) => ({ purpose }));

  it("reads Callers only when every working agent is a support agent", () => {
    expect(allSupportAgents(roster("support", "support"))).toBe(true);
    expect(allSupportAgents(roster("support", "sales"))).toBe(false);
    expect(allSupportAgents([])).toBe(false);
    expect(allSupportAgents(undefined)).toBe(false);
  });

  it("names the leads screens in the account's words and keeps their paths", () => {
    const callers = leadNouns(true);
    expect(clientPageTitle("acme", "/c/acme/leads", callers)).toBe("Callers");
    expect(clientPageTitle("acme", "/c/acme/leads/lead-1", callers)).toBe("Callers");
    expect(clientPageTitle("acme", "/c/acme/settings/lead-details", callers)).toBe("Caller details");
    expect(clientPageTitle("acme", "/c/acme/leads", leadNouns(false))).toBe("Leads");
    const items = inAccountWords(clientNavigation("acme"), "acme", callers).flatMap((group) => group.items);
    expect(items.find((item) => item.href === "/c/acme/leads")?.label).toBe("Callers");
    expect(items.find((item) => item.href === "/c/acme/lead-sources")?.label).toBe("Leads & hours");
  });

  it("drops the sales words even for a business judged to sell", () => {
    const sells = { ...UNKNOWN_CAPABILITIES, sells: true };
    expect(leadWords(accountCapabilities(sells, true)).leads).toBe("interested callers");
    expect(leadWords(accountCapabilities(sells, false)).leads).toBe("leads");
  });
});
