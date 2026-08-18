import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import IntegrationsPage from "@/app/c/[slug]/integrations/page";
import type { Delivery, Endpoint } from "@/lib/api/integrations";

import { problem, renderClientPage } from "./harness";

/**
 * "What did you send?" on the integrations screen (D-23).
 *
 * The delivery log answers "did it arrive?"; the retained body answers "and what was in
 * it?". The second question is the one that ends a dispute, and it is also unredacted
 * personal data, so four things about this control are worth a test:
 *
 * 1. **It is not offered to a reader who cannot use it.** `calls:read_raw` is owner-only
 *    and an impersonating operator does not hold it either (core/rbac.py). A button that
 *    can only 403 is worse than no button.
 * 2. **It is not offered where there is nothing to show.** A copy is kept only while the
 *    tenant's lead-retention policy allows, an erasure destroys it, and events naming no
 *    customer never had one — so `payload_stored: false` renders as a stated absence, not
 *    a link into a refusal.
 * 3. **It is fetched on the press and at no other moment.** The GET writes an audit row
 *    (integrations/routes.py), so an automatic refetch would forge audit entries naming a
 *    person who did not ask.
 * 4. **§52: loading is a skeleton and failure is a refusal.** "We no longer keep a copy"
 *    is a real answer that must be shown as one, never as an empty panel.
 */

const PERMISSIONS = [
  "agents:read",
  "calls:read",
  "leads:read",
  "leads:write",
  "org:read",
  "org:manage",
];

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: [...PERMISSIONS, "calls:read_raw"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

/** Same screen, a reader without the raw-data permission. */
const STAFF = { ...OWNER, role: "staff", permissions: PERMISSIONS };

const ENDPOINTS: Endpoint[] = [
  {
    id: "e1",
    kind: "webhook",
    url: "https://crm.example/hook",
    events: ["lead.created"],
    active: true,
    secret_fingerprint: "abc12345",
    created_at: "2026-08-01T10:00:00Z",
  },
];

function delivery(over: Partial<Delivery> = {}): Delivery {
  return {
    id: "d1",
    event_type: "lead.created",
    status: "delivered",
    attempts: 1,
    first_at: "2026-08-13T10:00:00Z",
    last_at: "2026-08-13T10:00:00Z",
    payload_stored: true,
    ...over,
  };
}

const BODY = '{"id":"d1","data":{"name":"Priya","phone":"+91XXXXXX0001"}}';

const PAYLOAD = {
  delivery_id: "d1",
  event_type: "lead.created",
  body: BODY,
  truncated: false,
  original_bytes: BODY.length,
  stored_at: "2026-08-13T10:00:01Z",
};

const page = <IntegrationsPage />;

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/integrations/endpoints": ENDPOINTS,
    // The create forms are built from the server's own options read, so the screen asks
    // for it. `sheets_delivery_available` decides whether the Sheets form is offered at
    // all; this file is about the delivery log, and true keeps the screen at full size.
    "/v1/integrations/events": {
      events: ["lead.created", "lead.updated", "call.completed", "campaign.completed"],
      sheets_delivery_available: true,
    },
    "/v1/integrations/deliveries": [delivery()],
    ...over,
  };
}

describe("the retained delivery body", () => {
  it("is fetched only when the owner asks, and shown byte for byte", async () => {
    const { calls } = await renderClientPage(page, {
      ...routes(),
      "/v1/integrations/deliveries/d1/payload": PAYLOAD,
    });

    const payloadPath = "/v1/integrations/deliveries/d1/payload";
    // NO payload request of any shape, not merely none for THIS delivery: a hook that
    // fetched eagerly with a null id would ask for `.../null/payload` and slip past an
    // assertion keyed on the real path, while still writing an audit row per render in
    // production.
    expect(calls.filter((c) => c.path.endsWith("/payload"))).toEqual([]);
    expect(screen.queryByText(BODY)).toBeNull();

    fireEvent.click(await screen.findByRole("button", { name: "View" }));

    expect(await screen.findByText(BODY)).toBeTruthy();
    expect(calls.filter((c) => c.path === payloadPath)).toHaveLength(1);
  });

  /**
   * Hard rule 5, on the SECOND press — the same claim `callDetail.test.tsx` makes about
   * the raw transcript, because this is the same kind of route and it was left behind
   * when that one was fixed.
   *
   * `GET /v1/integrations/deliveries/{id}/payload` writes an `audit_log` row in the same
   * transaction as the read (integrations/routes.py), because the body is unredacted
   * customer data. The trail therefore has to count OPENINGS: served from a cache, a
   * second look leaves no second row and the log understates what was seen.
   */
  it("asks again on a second open, so every look is audited", async () => {
    const { calls } = await renderClientPage(page, {
      ...routes(),
      "/v1/integrations/deliveries/d1/payload": PAYLOAD,
    });
    const payloadPath = "/v1/integrations/deliveries/d1/payload";

    fireEvent.click(await screen.findByRole("button", { name: "View" }));
    expect(await screen.findByText(BODY)).toBeTruthy();
    expect(calls.filter((c) => c.path === payloadPath)).toHaveLength(1);

    fireEvent.click(await screen.findByRole("button", { name: "Hide" }));
    await waitFor(() => expect(screen.queryByText(BODY)).toBeNull());

    fireEvent.click(await screen.findByRole("button", { name: "View" }));
    expect(await screen.findByText(BODY)).toBeTruthy();
    expect(calls.filter((c) => c.path === payloadPath)).toHaveLength(2);
  });

  it("does not replay the last body while the new read is still in flight", async () => {
    // The other half of asking again. A panel that reopens on the PREVIOUS payload prints
    // a customer's details on the strength of a request that has not answered — and on a
    // switch between rows it would print the wrong customer's, under the new row's
    // heading.
    const { container } = await renderClientPage(page, {
      ...routes(),
      "/v1/integrations/deliveries/d1/payload": PAYLOAD,
    });

    fireEvent.click(await screen.findByRole("button", { name: "View" }));
    expect(await screen.findByText(BODY)).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Hide" }));

    await waitFor(() => expect(container.textContent).not.toContain(BODY));
  });

  it("is not offered at all to a reader without calls:read_raw", async () => {
    await renderClientPage(page, { ...routes({ "/v1/me": STAFF }) });

    // The delivery itself is still there — "did it arrive?" is staff's question too.
    expect(await screen.findByText("delivered")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "View" })).toBeNull();
  });

  it("states the absence rather than offering a link into a refusal", async () => {
    await renderClientPage(page, {
      ...routes({ "/v1/integrations/deliveries": [delivery({ payload_stored: false })] }),
    });

    expect(await screen.findByTitle(/No copy is kept for this delivery/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "View" })).toBeNull();
  });

  it("shows a refusal, not an empty panel, when the copy is gone", async () => {
    await renderClientPage(page, {
      ...routes(),
      // The refusal the API actually sends (integrations/routes.py). `ProblemNotice`
      // renders `detail`, which is the sentence written for the client.
      "/v1/integrations/deliveries/d1/payload": problem(404, {
        type: "https://calevate.tech/problems/delivery_body_not_retained",
        title: "No copy of this delivery is kept",
        detail: "We no longer hold a copy of what was sent for this delivery.",
        status: 404,
        kind: "not_found",
        retryable: false,
      }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "View" }));

    const refusal = await screen.findByRole("alert");
    expect(refusal.textContent).toContain("We no longer hold a copy of what was sent");
    // A refusal, not an empty panel and not a stale body.
    expect(screen.queryByText(BODY)).toBeNull();
  });

  it("says when the copy it is showing is only part of what was sent", async () => {
    await renderClientPage(page, {
      ...routes(),
      "/v1/integrations/deliveries/d1/payload": {
        ...PAYLOAD,
        truncated: true,
        original_bytes: 4_000_000,
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "View" }));

    // The number is the SERVER's, and the sentence says our copy stops — a partial body
    // shown as if it were whole is a forensic record that lies.
    expect(await screen.findByText(/Only the first part of this body is kept/)).toBeTruthy();
    expect(screen.getByText(/40,00,000 bytes/)).toBeTruthy();
  });
});

/**
 * The last live entry on the §52 guard's EXEMPT list, closed.
 *
 * The offer was gated on `me.data?.permissions?.includes("calls:read_raw") ?? false`, and
 * `me.data` is undefined while `/v1/me` is in flight AND after it fails. So an owner whose
 * `/v1/me` 503'd lost the "Sent" column and the View buttons with no explanation — the
 * screen implying a refusal it never received, which is the same defect the Leads export
 * carried and closed the same way: `useWriteAccess`, which answers "We could not check
 * whether you can …" for exactly this case.
 */
describe("the payload offer when we could not check the permission", () => {
  it("says we could not check, rather than silently withdrawing the column", async () => {
    const { container } = await renderClientPage(page, {
      ...routes({ "/v1/me": problem(503, { title: "Service unavailable", retryable: true }) }),
    });

    // The delivery log itself is unaffected — that read succeeded.
    expect(await screen.findByText("delivered")).toBeTruthy();
    // The sentence is PRESENT. "No View button" is also true of a staff user, of an
    // empty log, and of a card that failed to render at all.
    expect(container.textContent).toContain(
      "We could not check whether you can open a delivered payload",
    );
    expect(screen.queryByRole("button", { name: "View" })).toBeNull();
  });

  it("stays quiet for a reader who genuinely lacks the permission", async () => {
    // The distinction the fix turns on. A KNOWN refusal needs no sentence here — the
    // column is deliberately absent, "a permanently empty column is a promise the screen
    // cannot keep" — and printing one for every staff reader is the noise that stops the
    // real refusal above from being read.
    const { container } = await renderClientPage(page, { ...routes({ "/v1/me": STAFF }) });

    expect(await screen.findByText("delivered")).toBeTruthy();
    expect(container.textContent).not.toContain("open a delivered payload");
    expect(screen.queryByRole("button", { name: "View" })).toBeNull();
  });

  it("says nothing at all to a reader who has it", async () => {
    // A restriction note that renders for everybody is noise, and noise is how a real
    // refusal stops being read.
    const { container } = await renderClientPage(page, { ...routes() });

    expect(await screen.findByRole("button", { name: "View" })).toBeTruthy();
    expect(container.textContent).not.toContain("open a delivered payload");
  });
});
