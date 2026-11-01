import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, screen, waitFor } from "@testing-library/react";
import { cloneElement } from "react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import type { Me } from "@/lib/api/client";
import { ClientRealmProvider } from "@/lib/api/session";

import { renderClientPage } from "./harness";

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "kb:write", "org:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const ROUTES = {
  "/v1/me": ME,
  "/v1/agents": [],
  "/v1/kb/notes": { notes: [] },
  "/v1/kb/uploads": [],
  "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
  "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
  "/v1/teach/questions": { items: [], open_count: 0 },
  "/v1/kb/teach/open": { teaching: null },
};

describe("a link to the questions followed while the knowledge page is open", () => {
  it("opens the questions tab rather than keeping the tab the page opened on", async () => {
    window.history.replaceState(null, "", "/c/acme/knowledge");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const page = <KnowledgePage />;
    try {
      const { rerender } = await renderClientPage(page, ROUTES, "acme", client);
      await waitFor(() =>
        expect(screen.getByRole("tab", { name: "What they know" }).getAttribute("aria-selected")).toBe(
          "true",
        ),
      );
      await act(async () => {
        window.history.replaceState(null, "", "/c/acme/knowledge?tab=questions");
        rerender(
          <QueryClientProvider client={client}>
            {/* A new element, so React renders the route again rather than reusing the old tree. */}
            <ClientRealmProvider slug="acme">{cloneElement(page)}</ClientRealmProvider>
          </QueryClientProvider>,
        );
      });
      await waitFor(() =>
        expect(
          screen.getByRole("tab", { name: /Questions to answer/ }).getAttribute("aria-selected"),
        ).toBe("true"),
      );
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });
});
