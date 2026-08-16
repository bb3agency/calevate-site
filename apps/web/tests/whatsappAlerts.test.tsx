import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TenantDetailPage from "@/app/admin/tenants/[tenantId]/page";
import AlertsPage from "@/app/c/[slug]/settings/alerts/page";
import { WHATSAPP_ALERTS_PATH, type AlertOptIn } from "@/lib/api/whatsappAlerts";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, renderClientPage, stillLoading, type Routes } from "./harness";

/**
 * WhatsApp hot-lead alerts — the client's own opt-in, and the operator's record of one.
 *
 * FLOWS §6's WhatsApp half has never delivered, because `resolve_destination` refuses
 * without an opt-in and nothing anywhere could record one. Both surfaces now exist, and
 * the four properties below are what make them worth having rather than dangerous:
 *
 * 1. **The wording is the SERVER'S, and the version sent back is the version shown.**
 *    A `notice_version` column is only evidence if the text it names can be reproduced,
 *    so a screen that shipped its own sentence — or posted a constant version while
 *    rendering something else — would turn every stored row into evidence of nothing.
 * 2. **Consent is not offered for a channel that cannot deliver, and withdrawal is
 *    always offered.** Recording an agreement to receive messages we cannot send is the
 *    "looks finished" failure; making it harder to stop than to start is worse.
 * 3. **The operator can SEE a withdrawal before recording over it.** The ledger is
 *    append-only, so an operator who records a month-old onboarding form over last
 *    week's withdrawal cannot edit it back — the correction is another row and the
 *    alerts went out in between.
 * 4. **A failed read is never "alerts are off".** On the client screen that sentence
 *    makes an owner turn on something already on; on the operator panel it is the
 *    sentence answered by recording a grant nobody asked for.
 *
 * Hard rule 6 is a property of the payload and nothing here widens it: there is no phone
 * field on any of these routes, in either direction.
 */

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "managed" },
};

/** A member who may read the account's settings and not change them. */
const STAFF = { ...ME, role: "staff", permissions: ["org:read"] };

const NOTICE = "I agree that Calevate may send WhatsApp messages to this number…";

function optIn(over: Partial<AlertOptIn> = {}): AlertOptIn {
  return {
    status: "none",
    channel: null,
    captured_at: null,
    notice_version: null,
    messageable: false,
    current_notice_version: "whatsapp-alerts-v1",
    current_notice_text: NOTICE,
    delivery_available: true,
    delivery_unavailable_reason: null,
    ...over,
  };
}

function clientRoutes(state: AlertOptIn, me: unknown = ME, over: Routes = {}): Routes {
  return { "/v1/me": me, [WHATSAPP_ALERTS_PATH]: state, ...over };
}

describe("the client's own WhatsApp alert opt-in", () => {
  it("renders the server's wording and records the version it showed", async () => {
    const { calls, container } = await renderClientPage(
      <AlertsPage />,
      clientRoutes(optIn(), ME, {
        [`POST ${WHATSAPP_ALERTS_PATH}`]: optIn({ status: "granted", messageable: true }),
      }),
    );

    // The exact sentence from `whatsapp_optin.ALERT_NOTICE_TEXT`, not a copy in the
    // bundle: the stored `notice_version` has to resolve back to something.
    await waitFor(() => expect(container.textContent).toContain(NOTICE));

    fireEvent.click(await screen.findByRole("button", { name: /I agree/ }));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST")).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      status: "granted",
      // THE VERSION THAT WAS ON SCREEN. A constant here would let a stale build record
      // this quarter's version against last quarter's wording, which the API refuses
      // (`alert_optin_notice_out_of_date`) precisely because the console could get it
      // wrong — and a console that always sent the current one would never be refused.
      notice_version: "whatsapp-alerts-v1",
    });
  });

  it("sends back a version the server has superseded rather than papering over it", async () => {
    // A build rendering older wording must send THAT version and be refused, which is
    // what makes the refusal reachable at all. The screen renders the refusal it gets.
    const { calls, container } = await renderClientPage(
      <AlertsPage />,
      clientRoutes(optIn({ current_notice_version: "whatsapp-alerts-v0" }), ME, {
        [`POST ${WHATSAPP_ALERTS_PATH}`]: problem(422, {
          kind: "validation",
          type: "urn:calevate:error/alert_optin_notice_out_of_date",
          title: "The wording on your screen is out of date",
          detail: "The wording on your screen is out of date.",
          remediation: "Reload the page and confirm again.",
        }),
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /I agree/ }));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST")).toBe(true);
    });
    expect(JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}")).toEqual({
      status: "granted",
      notice_version: "whatsapp-alerts-v0",
    });
    await waitFor(() => {
      expect(container.textContent).toContain("Reload the page and confirm again");
    });
  });

  it("withholds the agreement while nothing can deliver it, and says whose problem that is", async () => {
    const { container } = await renderClientPage(
      <AlertsPage />,
      clientRoutes(optIn({ delivery_available: false, delivery_unavailable_reason: "no_credential" })),
    );

    await waitFor(() => {
      expect(container.textContent).toContain("We cannot send WhatsApp messages yet");
    });
    // Present and DEAD, with the reason — not absent, which would read as a broken page.
    const agree = await screen.findByRole("button", { name: /I agree/ });
    expect((agree as HTMLButtonElement).disabled).toBe(true);
    expect(container.textContent).toContain("This is on our side, not yours");
  });

  it("lets an opted-in owner withdraw even when the channel is down", async () => {
    // Consent that is harder to take back than to give is not consent, and our vendor
    // situation is not a reason to keep messaging somebody who asked us to stop.
    const { calls } = await renderClientPage(
      <AlertsPage />,
      clientRoutes(
        optIn({
          status: "granted",
          messageable: true,
          captured_at: "2026-08-12T09:00:00Z",
          delivery_available: false,
          delivery_unavailable_reason: "no_credential",
        }),
        ME,
        { [`POST ${WHATSAPP_ALERTS_PATH}`]: optIn({ status: "withdrawn" }) },
      ),
    );

    const stop = await screen.findByRole("button", { name: /Stop sending me/ });
    expect((stop as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(stop);

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}").status).toBe(
      "withdrawn",
    );
  });

  it("refuses rather than reporting alerts off when the read fails", async () => {
    const { container } = await renderClientPage(
      <AlertsPage />,
      clientRoutes(optIn(), ME, {
        [WHATSAPP_ALERTS_PATH]: problem(503, { title: "Service unavailable" }),
      }),
    );

    // The refusal is PRESENT — asserting only that the state sentence is absent would
    // pass on an empty card too.
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toBeTruthy();
    });
    expect(container.textContent).not.toContain("Hot-lead alerts are not going to your WhatsApp");
    expect(container.textContent).not.toContain("Hot-lead alerts are on");
    expect(screen.queryByRole("button", { name: /I agree/ })).toBeNull();
  });

  it("renders a skeleton while the read is in flight, and claims nothing", async () => {
    const { container } = await renderClientPage(
      <AlertsPage />,
      clientRoutes(optIn(), ME, { [WHATSAPP_ALERTS_PATH]: stillLoading() }),
    );

    await waitFor(() => {
      expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    });
    expect(container.textContent).not.toContain("Hot-lead alerts are not going to your WhatsApp");
  });

  it("does not let a staff member give the owner's consent", async () => {
    // `org:manage` is the owner's alone (ROLE_PERMISSIONS): the subject of an opt-in is
    // the only person who can give it, so the control is dead with its reason rather
    // than posting a request the API would refuse.
    const { container } = await renderClientPage(<AlertsPage />, clientRoutes(optIn(), STAFF));

    const agree = await screen.findByRole("button", { name: /I agree/ });
    expect((agree as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => {
      // `useWriteAccess`'s own sentence — the one place in this app that answers "may
      // this session write", so the wording is its and not this screen's.
      expect(container.textContent).toContain(
        "Only an account owner can turn WhatsApp alerts on or off",
      );
    });
  });
});

const ADMIN_ME = {
  user_id: "admin-1",
  realm: "admin",
  role: "superadmin",
  permissions: ["admin:tenants", "org:read"],
};

const TENANT_ALERTS = "/v1/admin/tenants/t1/whatsapp-alerts";

/** Everything the tenant screen reads, so only the alerts panel is under test. */
function tenantRoutes(state: unknown, over: Routes = {}): Routes {
  return {
    "/v1/admin/me": ADMIN_ME,
    "/v1/admin/tenants/t1": {
      id: "t1",
      name: "Sri Traders",
      slug: "sri-traders",
      status: "active",
      vertical_template: "clinic",
      live_agents: 1,
      calls_7d: 12,
      leads: 4,
      last_call_at: null,
      holds: [],
      capped: false,
    },
    "/v1/admin/tenants/t1/margin": problem(404, { title: "no margin" }),
    "/v1/compliance/kyc": problem(404, { title: "none" }),
    "/v1/kb/sources?status=pending_approval": [],
    "/v1/kb/sources?status=approved": [],
    "/v1/agents": [],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    "/v1/billing/caps": problem(404, { title: "none" }),
    [TENANT_ALERTS]: state,
    ...over,
  };
}

describe("the operator's record of a client's opt-in", () => {
  it("shows a WITHDRAWAL before an operator can record an older agreement over it", async () => {
    const { container } = await renderAdminRoute(
      <TenantDetailPage params={routeParams({ tenantId: "t1" })} />,
      tenantRoutes(
        optIn({
          status: "withdrawn",
          channel: "self_serve_console",
          captured_at: "2026-08-13T09:00:00Z",
          delivery_available: false,
          delivery_unavailable_reason: "no_credential",
        }),
      ),
    );

    // The append-only ledger makes this the one order that cannot be undone, so the
    // withdrawal is stated in the panel's loudest line rather than in a timestamp.
    await waitFor(() => {
      expect(container.textContent).toContain("The owner has WITHDRAWN");
    });
    // …and the channel's own state, which is a different fact from consent.
    expect(container.textContent).toContain("This deployment cannot deliver WhatsApp yet");
  });

  it("will not record a grant without the document it rests on", async () => {
    const { calls, container } = await renderAdminRoute(
      <TenantDetailPage params={routeParams({ tenantId: "t1" })} />,
      tenantRoutes(optIn()),
    );

    const record = await screen.findByRole("button", { name: /Record that the owner agreed/ });
    // Dead until a reference is typed: the service AND a CHECK refuse an unevidenced
    // grant, so a live button here would send a request that cannot succeed.
    await waitFor(() => expect((record as HTMLButtonElement).disabled).toBe(true));
    expect(container.textContent).toContain("A reference, never the document itself");

    fireEvent.change(screen.getByPlaceholderText(/ONB-2026/), {
      target: { value: " ONB-2026-0042 " },
    });
    await waitFor(() => expect((record as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(record);

    // Filtered by PATH: the tenant screen mints a view-as grant on load, which is also a
    // POST, so `find(method === "POST")` would assert against the wrong request.
    await waitFor(() => expect(calls.some((c) => c.path === TENANT_ALERTS && c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.path === TENANT_ALERTS && c.method === "POST");
    expect(post?.path).toBe(TENANT_ALERTS);
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      status: "granted",
      evidence: { reference: "ONB-2026-0042" },
    });
  });

  it("records a withdrawal with no document at all", async () => {
    // Nobody has to prove that somebody asked to stop, and demanding evidence for it
    // would be a reason to delay stopping.
    const { calls } = await renderAdminRoute(
      <TenantDetailPage params={routeParams({ tenantId: "t1" })} />,
      tenantRoutes(optIn({ status: "granted", messageable: true })),
    );

    fireEvent.click(await screen.findByRole("button", { name: /Record a withdrawal/ }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === TENANT_ALERTS && c.method === "POST")).toBe(true),
    );
    const post = calls.find((c) => c.path === TENANT_ALERTS && c.method === "POST");
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      status: "withdrawn",
      evidence: null,
    });
  });

  it("refuses rather than reporting that nobody has agreed, when the read fails", async () => {
    const { container } = await renderAdminRoute(
      <TenantDetailPage params={routeParams({ tenantId: "t1" })} />,
      tenantRoutes(
        problem(422, {
          kind: "validation",
          type: "urn:calevate:error/alert_optin_no_owner_with_a_number",
          title: "This account has no active owner with a mobile number",
          detail: "This account has no active owner with a mobile number.",
          remediation: "Add a mobile number to the owner's profile, then record the opt-in.",
        }),
      ),
    );

    await waitFor(() => {
      expect(container.textContent).toContain("no active owner with a mobile number");
    });
    // The refusal names what to fix, and the write is not offered over a state nobody read.
    expect(container.textContent).toContain("Add a mobile number to the owner's profile");
    expect(screen.queryByRole("button", { name: /Record that the owner agreed/ })).toBeNull();
  });
});
