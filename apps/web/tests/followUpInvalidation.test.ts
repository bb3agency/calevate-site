import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { refreshAfterConfirm } from "@/lib/api/copilot";
import { followUpKeys } from "@/lib/api/followUps";

/**
 * What Pip does to a Follow-up refreshes the Follow-ups screens (their `followUpKeys.all`
 * prefix) and Leads & hours, which says whether "Call new leads" is on; a start plan also
 * refreshes the leads it put on one. A tool missing from the map would refetch everything,
 * so each is asserted by name.
 */

function invalidated(tool: string): unknown[][] {
  const client = new QueryClient();
  const keys: unknown[][] = [];
  vi.spyOn(client, "invalidateQueries").mockImplementation((filters) => {
    keys.push([...((filters?.queryKey as unknown[] | undefined) ?? [])]);
    return Promise.resolve();
  });
  refreshAfterConfirm(client, "acme", tool);
  return keys;
}

describe("Pip's Follow-up actions refresh the screens they change", () => {
  it.each([
    "follow_up_draft",
    "follow_up_publish",
    "follow_up_pause",
    "follow_up_resume",
    "follow_up_turn_off",
  ])("%s", (tool) => {
    expect(invalidated(tool)).toEqual([[...followUpKeys.all("acme")], ["lead-calling", "acme"]]);
  });

  it("follow_up_start refreshes the Follow-ups and the leads", () => {
    expect(invalidated("follow_up_start")).toEqual([
      [...followUpKeys.all("acme")],
      ["leads", "acme"],
      ["lead", "acme"],
    ]);
  });
});
