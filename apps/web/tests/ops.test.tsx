import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import OpsPage from "@/app/admin/ops/page";
import type { PlatformState } from "@/lib/api/admin";

import { problem, renderAdminPage, type Routes } from "./harness";

/**
 * The operations screen — the highest-consequence surface in either realm, because its
 * controls act on EVERY tenant at once and its readouts are what an operator trusts
 * mid-incident (runbooks/calls-stopped.md §1).
 *
 * Ranked by what each failure costs, worst first:
 *
 * 1. **A read we could not make must never render as "outbound is running."** This is
 *    the screen's one unrecoverable lie: an operator diagnosing stopped calls crosses the
 *    switch off the list, and an operator who has just ordered a halt believes it did not
 *    take. `?? false` was the shape that produced it.
 * 2. **A control this session may not use is dead WITH its reason.** Every route on
 *    `/v1/ops` is `ops:manage` (superadmin only), so an `operator` who reaches this page
 *    is refused by the API on everything here. The answer comes from the admin realm's
 *    own identity read (`GET /v1/admin/me`) rather than from a 403 on this screen's own
 *    read, so it can be given before any request has failed — and the nav no longer
 *    offers the entry to a session that would meet nothing but that 403.
 * 3. **The switch is not one accidental click.** A typed confirmation plus a reason, both
 *    required, and the reason measured after trimming — the API strips it and refuses
 *    anything under three characters, so a button that lights up on `"   "` teaches an
 *    operator that the API is flaky.
 * 4. **`is_live` is the server's answer, never recomputed** — a console that decided for
 *    itself whether `submitted` counts could show a green platform while every tenant's
 *    launch was refused.
 *
 * Hard rule 6 is a property of this payload and nothing here widens it: no phone number,
 * no transcript, no extraction field exists anywhere on `/v1/ops/platform`.
 */

const PLATFORM = "/v1/ops/platform";

/** Who the console is. `ops:manage` is superadmin-only (core/rbac.py). */
function me(permissions: string[]): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-7777-7000-8000-0000000000c1",
    role: permissions.includes("ops:manage") ? "superadmin" : "operator",
    permissions,
  } as AdminMe;
}

const SUPERADMIN = me(["org:read", "admin:tenants", "ops:manage"]);
const OPERATOR = me(["org:read", "admin:tenants"]);

/**
 * This screen's routes: the platform state, plus the identity its gate is read from.
 *
 * A helper rather than a spread in every case, because the identity is now a PREMISE of
 * the screen — a test that omitted it would assert the behaviour of a console that does
 * not know who it is, which is a state the shell never renders.
 */
function routes(platformAnswer: unknown, identity: unknown = SUPERADMIN): Routes {
  return { [PLATFORM]: platformAnswer, [ADMIN_ME_PATH]: identity };
}

function platform(over: Partial<PlatformState> = {}): PlatformState {
  return {
    load_shed_mode: "normal",
    outbound_halted: false,
    halt_reason: null,
    tm_registration: {
      status: "active",
      tm_id: "TM-110022",
      registered_at: "2026-01-04T06:30:00Z",
      verified_at: "2026-08-01T06:30:00Z",
      is_live: true,
    },
    ...over,
  };
}

describe("the ops screen when the platform state cannot be read", () => {
  it("does NOT report that outbound calling is running", async () => {
    renderAdminPage(
      <OpsPage />,
      routes(
        problem(503, {
          title: "Service unavailable",
          detail: "The database is not reachable.",
          retryable: true,
        }),
      ),
    );

    // The honest statement, and it is the headline rather than a footnote.
    await screen.findByText("We do not know whether outbound calling is halted");
    // The two comfortable defaults, both absent.
    expect(screen.queryByText("Outbound calling is running")).toBeNull();
    expect(screen.queryByText(/Outbound calling is HALTED/)).toBeNull();
    // And no switch to press over a state nobody has read.
    expect(screen.queryByRole("button", { name: /Halt all outbound calling/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Resume outbound calling/ })).toBeNull();
  });

  it("says the read failed rather than blaming the operator's permissions", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(problem(503, { title: "Service unavailable", retryable: true })),
    );

    await screen.findByText("We do not know whether outbound calling is halted");
    expect(container.textContent).toContain("the current state could not be read");
    // A 503 is not an authorization answer, so the screen must not invent one.
    expect(container.textContent).not.toContain("ops:manage");
  });

  it("disables every control WITH the reason when the session lacks ops:manage", async () => {
    // An `operator`: the API refuses this screen's read AND its writes with the same
    // permission, and the console now knows which one is missing before either lands.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(
        problem(403, {
          title: "Forbidden",
          detail: "This action requires the ops:manage permission.",
        }),
        OPERATOR,
      ),
    );

    await screen.findByText("We do not know whether outbound calling is halted");
    // The permission the ROUTE requires, named — the operator learns what to ask for
    // rather than meeting a 403 that reads like a fault.
    expect(container.textContent).toContain("ops:manage");
    expect(container.textContent).toContain("Ask a superadmin");
    // Still no state claim, and still no control.
    expect(screen.queryByText("Outbound calling is running")).toBeNull();
    expect(screen.queryByRole("button", { name: /Halt all outbound calling/ })).toBeNull();
  });

  it("blames the read, not the operator, when a superadmin's own read fails", async () => {
    // The pair to the case above, and the distinction the old mechanism could not make:
    // a 503 and a 403 both stopped the read, and only one of them is about the session.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(problem(503, { title: "Service unavailable", retryable: true }), SUPERADMIN),
    );

    await screen.findByText("We do not know whether outbound calling is halted");
    expect(container.textContent).toContain("the current state could not be read");
    expect(container.textContent).not.toContain("ops:manage");
  });
});

describe("the big red switch", () => {
  it("will not fire on one click, and needs the reason the audit log will hold", async () => {
    renderAdminPage(<OpsPage />, routes(platform()));

    const halt = await screen.findByRole("button", { name: /Halt all outbound calling/ });
    expect((halt as HTMLButtonElement).disabled).toBe(true);

    // A reason alone is not enough.
    fireEvent.change(screen.getByPlaceholderText(/DLT complaint spike/), {
      target: { value: "complaints spiking" },
    });
    expect((halt as HTMLButtonElement).disabled).toBe(true);

    // The wrong word is not enough either — this is the guard against a form submitted
    // by habit from the other direction.
    fireEvent.change(screen.getByPlaceholderText("HALT"), { target: { value: "RESUME" } });
    expect((halt as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("HALT"), { target: { value: "HALT" } });
    expect((halt as HTMLButtonElement).disabled).toBe(false);
  });

  it("refuses a whitespace reason the server would strip and reject", async () => {
    renderAdminPage(<OpsPage />, routes(platform()));

    const halt = await screen.findByRole("button", { name: /Halt all outbound calling/ });
    fireEvent.change(screen.getByPlaceholderText(/DLT complaint spike/), {
      target: { value: "   " },
    });
    fireEvent.change(screen.getByPlaceholderText("HALT"), { target: { value: "HALT" } });
    expect((halt as HTMLButtonElement).disabled).toBe(true);
  });

  it("says what the click will do BEFORE it is clicked, and sends the step-up header", async () => {
    const { calls, container } = renderAdminPage(<OpsPage />, routes(platform()));

    const halt = await screen.findByRole("button", { name: /Halt all outbound calling/ });
    expect(container.textContent).toContain(
      "Halting stops every client's outbound dialling immediately",
    );
    // The half that is NOT affected, said in the same breath — an operator who believes
    // inbound stops too will not use the switch when they should.
    expect(container.textContent).toContain("Inbound calls are unaffected");

    fireEvent.change(screen.getByPlaceholderText(/DLT complaint spike/), {
      target: { value: "  complaints spiking  " },
    });
    fireEvent.change(screen.getByPlaceholderText("HALT"), { target: { value: "HALT" } });
    fireEvent.click(halt);

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === PLATFORM)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === PLATFORM);
    // The confirmation names the TRANSITION (ops/routes.py `platform_confirmation`), not
    // the endpoint: a header captured for a load-shed tweak must not authorise this.
    expect(post?.headers["X-Confirm-Action"]).toBe("halt_outbound");
    // Trimmed, because the server stores what it strips.
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      outbound_halted: true,
      reason: "complaints spiking",
    });
  });

  it("shows the halt's own reason, so nobody has to grep for why calls stopped", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(
        platform({
          outbound_halted: true,
          halt_reason: "registrar suspension — do not lift without Sri",
        }),
      ),
    );

    await screen.findByText("Outbound calling is HALTED for every client");
    expect(container.textContent).toContain("registrar suspension — do not lift without Sri");
    // The direction flips with the state: the control offered is the one that changes it.
    expect(screen.getByRole("button", { name: /Resume outbound calling/ })).toBeDefined();
    expect(screen.queryByRole("button", { name: /Halt all outbound calling/ })).toBeNull();
  });

  it("says a halt carries no reason rather than implying it was routine", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform({ outbound_halted: true, halt_reason: null })),
    );

    await screen.findByText("Outbound calling is HALTED for every client");
    expect(container.textContent).toContain("none was recorded with this halt");
  });

  it("prints a load-shed mode this build cannot name instead of rendering a function", async () => {
    // `load_shed_mode` is a bare string on the wire, and `constructor` is the wire value
    // that turns `TABLE[mode]` into the `Object` FUNCTION — truthy, so `??` never fires
    // and the page renders `function Object() { [native code] }` under a heading an
    // operator reads mid-incident. `lookup()` returns undefined for it.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform({ load_shed_mode: "constructor" })),
    );

    await screen.findByText("Outbound calling is running");
    expect(container.textContent).toContain("constructor");
    expect(container.textContent).not.toContain("native code");
    expect(container.textContent).toContain("This console has no description for that mode");
  });
});

describe("our own telemarketer registration", () => {
  it("reports the server's is_live even when the status looks reassuring", async () => {
    // The exact disagreement the panel exists to prevent: a status a reader would call
    // good, and a gate that is refusing every tenant. The server owns `is_live`.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(
        platform({
          tm_registration: {
            status: "active",
            tm_id: "TM-110022",
            registered_at: "2026-01-04T06:30:00Z",
            verified_at: null,
            is_live: false,
          },
        }),
      ),
    );

    await screen.findByText("NOT LIVE — no tenant can launch");
    expect(container.textContent).toContain("NO tenant can launch an outbound campaign");
    expect(screen.queryByText("LIVE — we may lawfully dial")).toBeNull();
  });

  it("keeps the registration form dead while the session lacks the permission", async () => {
    renderAdminPage(<OpsPage />, routes(problem(403, { title: "Forbidden" }), OPERATOR));

    await screen.findByText("We do not know whether outbound calling is halted");
    // The panel needs the read to render at all, so the refused session gets no form —
    // which is the strongest form of "disabled with its reason" available here.
    expect(screen.queryByRole("button", { name: /Record registration/ })).toBeNull();
  });
});
