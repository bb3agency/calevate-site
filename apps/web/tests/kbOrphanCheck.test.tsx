import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KnowledgeDriftPanel } from "@/app/admin/ops/KnowledgeDriftPanel";
import type { KbDrift } from "@/lib/api/admin";
import { OPS_KB_ORPHANS_PATH, type KbOrphanReport } from "@/lib/api/opsKbOrphans";

import { stubApi, type Routes } from "./harness";

const DRIFT: KbDrift = {
  engine_supports_knowledge_base: true,
  in_sync: 3,
  live_agents: 3,
  never_checked: 0,
  oldest_checked_at: "2026-10-10T05:00:00Z",
  oldest_drift_at: null,
  out_of_sync: 0,
  undetermined: 0,
};

function report(over: Partial<KbOrphanReport> = {}): KbOrphanReport {
  return {
    engine: "thinnest",
    supported: true,
    accounted: 4,
    unrecorded: 1,
    unclaimed: 0,
    stranded: 0,
    findings: 1,
    truncated: false,
    listing_complete: true,
    listing_incomplete_reason: null,
    rows: [
      {
        verdict: "unrecorded",
        handle: "kb_calevate_123",
        source_id: null,
        tenant_id: "0192f0aa-7777-7000-8000-0000000000aa",
        created_at: "2026-10-09T06:00:00Z",
      },
    ],
    ...over,
  };
}

function renderPanel(table: Routes) {
  const calls = stubApi(table);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <KnowledgeDriftPanel drift={{ status: "read", drift: DRIFT }} />
    </QueryClientProvider>,
  );
  return calls;
}

describe("the account-level knowledge check", () => {
  it("never walks the platform account until an operator asks", () => {
    const calls = renderPanel({});
    expect(calls.length).toBe(0);
    expect(screen.getByRole("button", { name: "Check the account" })).toBeTruthy();
  });

  it("prints the exact counts and each finding with its meaning", async () => {
    renderPanel({ [OPS_KB_ORPHANS_PATH]: report() });
    fireEvent.click(screen.getByRole("button", { name: "Check the account" }));

    await screen.findByText("kb_calevate_123");
    expect(screen.getByText(/a publish that rolled back/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Check again" })).toBeTruthy();
  });

  it("says the walk was cut short rather than reporting a clean account", async () => {
    renderPanel({
      [OPS_KB_ORPHANS_PATH]: report({
        listing_complete: false,
        listing_incomplete_reason: "page_cap_reached",
        rows: [],
        findings: 0,
        unrecorded: 0,
      }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Check the account" }));

    await screen.findByText("The platform's listing could not be read to the end");
    expect(screen.getByText(/page_cap_reached/)).toBeTruthy();
  });

  it("names an engine with nothing to walk instead of printing zeros", async () => {
    renderPanel({ [OPS_KB_ORPHANS_PATH]: report({ supported: false, rows: [] }) });
    fireEvent.click(screen.getByRole("button", { name: "Check the account" }));

    await screen.findByText(/keeps no account-level knowledge store/);
    expect(screen.queryByText("Accounted for")).toBeNull();
  });
});
