import { describe, expect, it } from "vitest";

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
