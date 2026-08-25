import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import IntegrationsPage from "@/app/c/[slug]/integrations/page";
import type { Endpoint } from "@/lib/api/integrations";

import { problem, renderClientPage } from "./harness";

/**
 * INT-1 — stopping an outbound endpoint, which is the most expensive mis-click in this
 * console.
 *
 * The control used to be labelled "Turn off" and fired `DELETE
 * /v1/integrations/endpoints/{id}` on one press. Three things compounded:
 *
 * 1. **The label promised a switch the product does not have.** The API has no
 *    re-activate route; the row then rendered an `off` badge with no control on it at
 *    all, so the only way back is registering the address again — which mints a NEW
 *    signing secret, so the client must reconfigure their CRM too.
 * 2. **Nothing on screen said what stops.** The client's live lead feed into their own
 *    CRM, immediately, silently.
 * 3. **Five endpoints gave a screen reader five buttons announced identically** — the
 *    per-row accessible name `do-not-call` and `settings/team` already fixed on their own
 *    lists.
 *
 * The tests below are about ORDER and TARGET: nothing may leave the browser on the first
 * press, and the dialog must name the endpoint it is about to stop. A dialog that says
 * "are you sure?" confirms intent; only one that prints the URL confirms target.
 */

const PERMISSIONS = ["agents:read", "calls:read", "leads:read", "org:read", "org:manage"];

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: PERMISSIONS,
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const URL_A = "https://crm.example/hook";
const URL_B = "https://backup.example/hook";

function endpoint(over: Partial<Endpoint> = {}): Endpoint {
  return {
    id: "e1",
    kind: "webhook",
    url: URL_A,
    events: ["lead.created"],
    active: true,
    secret_fingerprint: "abc12345",
    include_recording_url: false,
    include_transcript: false,
    include_raw_transcript: false,
    created_at: "2026-08-01T10:00:00Z",
    ...over,
  };
}

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/integrations/endpoints": [endpoint()],
    "/v1/integrations/events": {
      events: ["lead.created", "call.completed"],
      sheets_delivery_available: false,
    },
    "/v1/integrations/deliveries": [],
    ...over,
  };
}

const stopButtons = (): HTMLElement[] =>
  screen.queryAllByRole("button", { name: /^Stop sending events to / });

describe("stopping an endpoint is confirmed, named and explained", () => {
  it("says what it does, per row, rather than promising a switch", async () => {
    await renderClientPage(<IntegrationsPage />, {
      ...routes({
        "/v1/integrations/endpoints": [endpoint(), endpoint({ id: "e2", url: URL_B })],
      }),
    });

    await screen.findByText(URL_A);
    // The visible label states the operation. "Turn off" described a toggle for what is
    // a delete — a match-between-system-and-real-world failure independent of the
    // missing confirmation.
    expect(screen.getAllByText("Stop sending events")).toHaveLength(2);
    // …and each button's accessible name carries its own row, so two endpoints are two
    // distinct announcements.
    expect(stopButtons().map((b) => b.getAttribute("aria-label"))).toEqual([
      `Stop sending events to ${URL_A}`,
      `Stop sending events to ${URL_B}`,
    ]);
  });

  it("sends nothing on the first press and names the endpoint and the cost", async () => {
    const { calls } = await renderClientPage(<IntegrationsPage />, routes());

    await screen.findByText(URL_A);
    fireEvent.click(stopButtons()[0]);

    const dialog = await screen.findByRole("dialog");
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([]);
    // Target: WHICH endpoint stops receiving leads.
    expect(within(dialog).getByText(URL_A)).toBeTruthy();
    // Consequence, both halves — the feed stops, and coming back costs a new secret.
    expect(dialog.textContent).toContain("stop receiving leads");
    expect(dialog.textContent).toContain("NEW signing secret");
    expect(dialog.textContent).toContain("cannot be undone here");
  });

  it("deletes the endpoint by id once the client confirms", async () => {
    const { calls } = await renderClientPage(<IntegrationsPage />, {
      ...routes(),
      "/v1/integrations/endpoints/e1": {},
    });

    await screen.findByText(URL_A);
    fireEvent.click(stopButtons()[0]);
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Stop sending events",
      }),
    );

    await waitFor(() => {
      const deletes = calls.filter((c) => c.method === "DELETE");
      expect(deletes).toHaveLength(1);
      expect(deletes[0].path).toBe("/v1/integrations/endpoints/e1");
    });
    // The dialog closes on SUCCESS, which is the only state in which it may.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the feed running when the client backs out", async () => {
    const { calls } = await renderClientPage(<IntegrationsPage />, routes());

    await screen.findByText(URL_A);
    fireEvent.click(stopButtons()[0]);
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Keep sending" }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([]);
    expect(stopButtons()).toHaveLength(1);
  });

  it("stays open with the server's refusal when the delete fails", async () => {
    // A dialog that closed on a failure would tell a client their CRM feed had stopped
    // when it had not — and they would go and reconfigure a working integration.
    const { calls } = await renderClientPage(<IntegrationsPage />, {
      ...routes(),
      "/v1/integrations/endpoints/e1": problem(503, {
        title: "Service unavailable",
        detail: "We could not stop this endpoint just now.",
      }),
    });

    await screen.findByText(URL_A);
    fireEvent.click(stopButtons()[0]);
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Stop sending events",
      }),
    );

    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() =>
      expect(dialog.textContent).toContain("could not stop this endpoint"),
    );
  });

  it("is a real modal: labelled, described, and focus is inside it", async () => {
    await renderClientPage(<IntegrationsPage />, routes());

    await screen.findByText(URL_A);
    fireEvent.click(stopButtons()[0]);

    const dialog = await screen.findByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
    expect(dialog.getAttribute("aria-describedby")).toBeTruthy();
    // `aria-modal` without a focus trap is the half of the contract that leaves a
    // keyboard user typing into the page behind the dialog.
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("explains a stopped row instead of leaving it with no control", async () => {
    // An `off` row used to carry nothing at all, which reads as a button that failed to
    // render rather than as a state with no way out.
    const { container } = await renderClientPage(<IntegrationsPage />, {
      ...routes({ "/v1/integrations/endpoints": [endpoint({ active: false })] }),
    });

    await screen.findByText(URL_A);
    expect(container.textContent).toContain("stopped — add a new endpoint to resume");
    expect(stopButtons()).toHaveLength(0);
  });

  it("offers nothing to a reader who may not change the integration", async () => {
    // The refusal is pre-empted, not discovered on click — `useWriteAccess`, the way the
    // rest of this console does it.
    await renderClientPage(<IntegrationsPage />, {
      ...routes({ "/v1/me": { ...OWNER, role: "staff", permissions: ["org:read"] } }),
    });

    await screen.findByText(URL_A);
    expect((stopButtons()[0] as HTMLButtonElement).disabled).toBe(true);
  });
});

/**
 * INT-2 — the token migration, asserted at the source rather than at the render.
 *
 * This file was the only route under `src/app/c/` writing its ink in raw Tailwind
 * literals, and the repo-wide rule now lives in `tests/contrast.test.ts`. This is the
 * narrower claim that belongs with this screen: that THIS file stayed migrated. It is
 * kept separate from the repo-wide guard because the failure it protects against is
 * different — the guard catches a new file drifting in, this catches this file drifting
 * back after a merge.
 */
describe("the integrations screen writes its ink in tokens", () => {
  it("carries no raw grey ink literal", () => {
    const file = resolve(
      dirname(fileURLToPath(import.meta.url)),
      "../src/app/c/[slug]/integrations/page.tsx",
    );
    const source = readFileSync(file, "utf8");
    const offenders = source
      .split("\n")
      .map((line, index) => ({ line, index }))
      .filter(
        ({ line }) =>
          /(?<![-\w:])(?:dark:)?text-(?:slate|gray|zinc|neutral|stone)-\d{2,3}\b/.test(line) &&
          !/(?<![-\w:])(?:dark:)?bg-(?:slate|gray|zinc|neutral|stone)-\d{2,3}\b/.test(line),
      )
      .map(({ index }) => index + 1);
    expect(
      offenders,
      "these lines put ink on a token surface without using an ink token — the exact " +
        "defect that rendered this screen's hints at 2.56:1 in light and 3.75:1 in dark " +
        "(globals.css:39,88) while both the palette check and the jsdom axe sweep passed",
    ).toEqual([]);
  });
});
