import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MaintenancePage from "@/app/admin/ops/maintenance/page";
import { MaintenanceBanner, MaintenanceGate } from "@/components/maintenance";
import {
  maintenanceConfirmation,
  maintenanceFromProblem,
  MAINTENANCE_PROBLEM_CODE,
} from "@/lib/api/maintenance";
import { ApiProblem } from "@/lib/api/client";

import { problem, renderAdminPage, renderClientPage } from "./harness";

/**
 * Planned maintenance, on the two screens a person actually meets it on.
 *
 * The backend suites (`tests/maintenance_drain_test.py`,
 * `tests/maintenance_surface_test.py`) own the state machine and the refusal. What is
 * asserted HERE is what those cannot see: that the operator is shown the numbers before
 * the buttons, that the announced-start rule is explained rather than sprung, and that a
 * locked-out client meets ONE page saying what is happening — not twenty red boxes.
 */

const DRAINING = {
  id: "0199a0b0-0000-7000-8000-0000000000ff",
  reason: "Upgrading the telephony stack. Nothing is deleted.",
  starts_at: "2026-09-06T20:30:00Z",
  ends_at: "2026-09-06T21:30:00Z",
  state: "draining" as const,
  max_drain_minutes: 15,
  drain_deadline_at: "2026-09-06T20:45:00Z",
  activated_at: null,
  forced: false,
  stragglers: null,
  in_flight: {
    calls: 2,
    jobs: 3,
    tenants_unreached: 0,
    complete: true,
    measured_at: "2026-09-06T20:31:00Z",
  },
  ended_at: null,
  cancelled_at: null,
  announced: true,
};

describe("the maintenance confirmations", () => {
  it("name the action and its target, and no two verbs share a string", () => {
    // Pinned as literals because `runbooks/maintenance-window.md` prints them and the API
    // refuses anything else. A reformat here has to fail a test rather than quietly leave
    // the console sending a header the server rejects.
    expect(maintenanceConfirmation("schedule_maintenance")).toBe("schedule_maintenance");
    expect(maintenanceConfirmation("end_maintenance", DRAINING.id)).toBe(
      `end_maintenance:${DRAINING.id}`,
    );
    const verbs = ["amend_maintenance", "cancel_maintenance", "end_maintenance"];
    const strings = new Set(verbs.map((verb) => maintenanceConfirmation(verb, DRAINING.id)));
    expect(strings.size).toBe(3);
  });
});

describe("the operator's screen", () => {
  it("leads with what the drain is waiting for, how old it is, and the deadline", async () => {
    // THE FOUNDER'S FAILURE MODE, ASSERTED: "an operator staring at a spinner with no
    // numbers will force it and break a live call." Both counts and the deadline have to
    // be on the screen before any button is.
    const view = renderAdminPage(<MaintenancePage />, {
      "/v1/ops/maintenance": { current: DRAINING, history: [DRAINING], notice_lead_hours: 24 },
    });
    expect(await view.findByText("What the drain is waiting for")).toBeTruthy();
    expect(screen.getByText("Calls still up")).toBeTruthy();
    expect(screen.getByText("Jobs still queued")).toBeTruthy();
    expect(view.container.textContent).toContain("Drain deadline");
    // And the state is explained in the operator's terms, not as a status word alone.
    expect(view.container.textContent).toContain("Client portals are still OPEN");
  });

  it("says a partial check is a floor rather than reporting a clean drain", async () => {
    const truncated = {
      ...DRAINING,
      in_flight: { calls: 0, jobs: 0, tenants_unreached: 4, complete: false, measured_at: null },
    };
    const view = renderAdminPage(<MaintenancePage />, {
      "/v1/ops/maintenance": { current: truncated, history: [], notice_lead_hours: 24 },
    });
    // Two zeros on the screen must NOT read as "drained": the caveat is what stops an
    // operator concluding the platform is idle from a walk that gave up early.
    expect(await view.findByText("These numbers are a floor, not a total")).toBeTruthy();
    expect(view.container.textContent).toContain("4 clients");
  });

  it("keeps the straggler report of a forced activation on the screen", async () => {
    const forced = {
      ...DRAINING,
      state: "active" as const,
      activated_at: "2026-09-06T20:45:00Z",
      forced: true,
      in_flight: null,
      stragglers: {
        calls: 1,
        jobs: 9,
        tenants_unreached: 0,
        complete: true,
        measured_at: "2026-09-06T20:45:00Z",
      },
    };
    const view = renderAdminPage(<MaintenancePage />, {
      "/v1/ops/maintenance": { current: forced, history: [forced], notice_lead_hours: 24 },
    });
    expect(await view.findByText("What was still running when it activated")).toBeTruthy();
    expect(view.container.textContent).toContain(
      "Activated on the deadline, not on a clean drain",
    );
  });

  it("offers END on an active window and does not offer CANCEL", async () => {
    // The server refuses `cancel` on an ACTIVE window — it has already closed the portals
    // and owes restoration work. A button rendered to fail teaches an operator to treat
    // this surface's refusals as noise, so it is not rendered.
    const active = { ...DRAINING, state: "active" as const, in_flight: null };
    const view = renderAdminPage(<MaintenancePage />, {
      "/v1/ops/maintenance": { current: active, history: [], notice_lead_hours: 24 },
    });
    expect(await view.findByText("End now and reopen the portals")).toBeTruthy();
    expect(screen.queryByText("Call it off")).toBeNull();
  });

  it("does not invite a second window when the board could not be read", async () => {
    // A FAILED READ IS NOT "NO WINDOW". The platform has one maintenance slot; inviting a
    // schedule off a dead read is how an operator books over a window they cannot see.
    const view = renderAdminPage(<MaintenancePage />, {
      "/v1/ops/maintenance": problem(503, { title: "Unavailable" }),
    });
    expect(await view.findByText("The maintenance board could not be read")).toBeTruthy();
    expect(screen.queryByText("Schedule it")).toBeNull();
  });

  it("sends the amendment as only the fields that moved, with the bound confirmation", async () => {
    const view = renderAdminPage(<MaintenancePage />, {
      "/v1/ops/maintenance": { current: DRAINING, history: [], notice_lead_hours: 24 },
      [`/v1/ops/maintenance/${DRAINING.id}`]: { ...DRAINING, max_drain_minutes: 40 },
    });
    await view.findByText("Change it");
    fireEvent.change(screen.getByDisplayValue("15"), { target: { value: "40" } });
    fireEvent.click(screen.getByText("Save changes"));
    await waitFor(() => {
      const patch = view.calls.find((call) => call.method === "PATCH");
      expect(patch).toBeTruthy();
      // Only the drain bound moved, so only the drain bound is sent — an amendment that
      // resent the unchanged reason would re-notify every client for nothing.
      expect(JSON.parse(patch?.body ?? "{}")).toEqual({ max_drain_minutes: 40 });
      expect(patch?.headers["X-Confirm-Action"]).toBe(
        `amend_maintenance:${DRAINING.id}`,
      );
    });
  });
});

describe("moving an announced window", () => {
  it("offers the start on a scheduled window and warns that clients hear about it", async () => {
    // THE FOUNDER'S REVERSAL, ON THE SCREEN. The first version froze the start of an
    // announced window and told the operator to cancel and re-schedule. Now it moves, and
    // the console says what that costs — a second email to everybody — rather than either
    // hiding the input or letting the operator find out afterwards.
    const scheduled = {
      ...DRAINING,
      state: "scheduled" as const,
      in_flight: null,
      drain_deadline_at: null,
      announced: true,
    };
    const view = renderAdminPage(<MaintenancePage />, {
      "/v1/ops/maintenance": { current: scheduled, history: [], notice_lead_hours: 24 },
    });
    expect(await view.findByText("Clients have already been told about this window")).toBeTruthy();
    expect(screen.getByText("Opens at")).toBeTruthy();
  });

  it("does not offer the start on a window that has begun", async () => {
    // A draining window's start is history and the API refuses it by name. An input
    // rendered to fail teaches an operator to read this surface's refusals as noise.
    const view = renderAdminPage(<MaintenancePage />, {
      "/v1/ops/maintenance": { current: DRAINING, history: [], notice_lead_hours: 24 },
    });
    await view.findByText("Change it");
    expect(screen.queryByText("Opens at")).toBeNull();
    expect(screen.getByText("Ends at")).toBeTruthy();
  });

  it("states the CONFIGURED notice period, not a number baked into the copy", async () => {
    // The hint said "Clients are emailed 24 hours ahead" and the lead is now a dial. A
    // screen stating a rule the platform does not follow is the stale-constant defect one
    // surface closer to the person acting on it.
    const view = renderAdminPage(<MaintenancePage />, {
      "/v1/ops/maintenance": { current: null, history: [], notice_lead_hours: 6 },
    });
    expect(await view.findByText("Schedule it")).toBeTruthy();
    expect(view.container.textContent).toContain("Clients are emailed 6 hours ahead");
    expect(view.container.textContent).not.toContain("24 hours ahead");
  });
});

describe("what a client sees", () => {
  it("warns before the window and says the phones keep ringing", async () => {
    const view = await renderClientPage(<MaintenanceBanner />, {
      "/v1/maintenance": {
        state: "scheduled",
        starts_at: "2026-09-06T20:30:00Z",
        ends_at: "2026-09-06T21:30:00Z",
        reason: "Upgrading the telephony stack.",
      },
    });
    expect(await view.findByText(/Planned maintenance/)).toBeTruthy();
    // The one sentence a shop owner most needs and an outage notice usually omits.
    expect(view.container.textContent).toContain("Your phone numbers keep ringing");
  });

  it("renders nothing at all on an ordinary day", async () => {
    const view = await renderClientPage(<MaintenanceBanner />, {
      "/v1/maintenance": { state: "none" },
    });
    await waitFor(() => expect(view.container.textContent).toBe(""));
  });

  it("replaces the screen with ONE page when the platform has shut", async () => {
    // The 503 IS the answer — the banner's own request is refused like everything else,
    // and the door is rendered from that refusal rather than from a second request that
    // would fail identically.
    const view = await renderClientPage(
      <MaintenanceGate>
        <p>the dashboard</p>
      </MaintenanceGate>,
      {
        "/v1/maintenance": problem(503, {
          type: `https://calevate.tech/problems/${MAINTENANCE_PROBLEM_CODE}`,
          title: "Down for planned maintenance",
          detail: "Upgrading the telephony stack. Nothing is deleted.",
          kind: "transient",
        }),
      },
    );
    expect(await view.findByText("Calevate is down for planned maintenance")).toBeTruthy();
    // The operator's own sentence, verbatim — not a re-worded version of it.
    expect(view.container.textContent).toContain(
      "Upgrading the telephony stack. Nothing is deleted.",
    );
    expect(view.container.textContent).toContain("resume by itself");
    // And the app behind it is GONE rather than overlaid, so nothing keeps polling into
    // a closed door.
    expect(screen.queryByText("the dashboard")).toBeNull();
  });

  it("shows the dashboard when the failure is anything else", async () => {
    // The control. A 500, a timeout, an expired session: none of those is a maintenance
    // window, and a door rendered for them would tell a client the platform is down when
    // it is one screen that failed.
    const view = await renderClientPage(
      <MaintenanceGate>
        <p>the dashboard</p>
      </MaintenanceGate>,
      { "/v1/maintenance": problem(500, { title: "Internal" }) },
    );
    expect(await view.findByText("the dashboard")).toBeTruthy();
  });
});

describe("reading a maintenance refusal", () => {
  it("takes the reason and the server's own countdown, and nothing else", () => {
    const shut = maintenanceFromProblem(
      new ApiProblem(
        503,
        {
          type: `https://calevate.tech/problems/${MAINTENANCE_PROBLEM_CODE}`,
          detail: "Upgrading the telephony stack.",
        },
        900,
      ),
    );
    expect(shut).toEqual({
      detail: "Upgrading the telephony stack.",
      retryAfterSeconds: 900,
    });
    // A LOAD SHED IS NOT A WINDOW. Both are 503 and they mean opposite things; the code is
    // what separates them, and reading a shed as a window would tell a client an unplanned
    // spike was scheduled downtime.
    expect(
      maintenanceFromProblem(
        new ApiProblem(503, {
          type: "https://calevate.tech/problems/service_load_shed",
          detail: "Managing a spike in load.",
        }),
      ),
    ).toBeNull();
    expect(maintenanceFromProblem(new Error("network"))).toBeNull();
  });
});
