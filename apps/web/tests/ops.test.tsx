import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import OpsPage from "@/app/admin/ops/page";
import {
  platformConfirmation,
  type AuditChainVerdict,
  type OutboxReplayResult,
  type PlatformState,
} from "@/lib/api/admin";

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
 *
 * ## The three controls this screen grew, and what each is tested for
 *
 * `load_shed_mode`, `POST /v1/ops/outbox/replay` and `GET /v1/ops/audit/verify` had no
 * path here, so the runbooks sent an operator to a hand-written curl. Each arrives with
 * its own failure to be pinned, and they are not the same failure:
 *
 * - the LOAD-SHED control shares the halt's whole argument (unknown state ⇒ no control;
 *   typed confirmation; blast radius first) and adds one of its own: it must refuse to
 *   submit the mode the platform is already in, because the server would accept that and
 *   write an audit row for a change nobody made;
 * - the REPLAY is the only control here that redelivers other people's clients' messages,
 *   so it must not fire on one click — and its result is a COUNT the screen has to render
 *   rather than announce, including a failed replay rendered as the failure it is;
 * - the AUDIT VERIFICATION is the one whose bad answer arrives as a 200. `ok: false` is a
 *   successful request carrying evidence of a tampered ledger, and a screen that filed
 *   that under "try again" — or under a toast — would be the worst defect on this page.
 */

const PLATFORM = "/v1/ops/platform";
const REPLAY = "/v1/ops/outbox/replay";
const VERIFY = "/v1/ops/audit/verify";

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
function routes(
  platformAnswer: unknown,
  identity: unknown = SUPERADMIN,
  extra: Routes = {},
): Routes {
  return { [PLATFORM]: platformAnswer, [ADMIN_ME_PATH]: identity, ...extra };
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

describe("the load-shed mode", () => {
  it("offers no control at all when the mode could not be read", async () => {
    // The mode lives on the row that failed, so it is exactly as unknown as the halt.
    // A select seeded from nothing would let an operator "restore normal" on a platform
    // that was never shedding, or re-impose a shed somebody had just lifted.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(problem(503, { title: "Service unavailable", retryable: true })),
    );

    await screen.findByText("We do not know whether outbound calling is halted");
    expect(container.textContent).toContain("The load-shed mode is on that same row");
    expect(screen.queryByRole("button", { name: /Switch to/ })).toBeNull();
    expect(screen.queryByPlaceholderText("MAINTENANCE")).toBeNull();
  });

  it("will not submit the mode the platform is already in", async () => {
    // The form opens on the CURRENT mode, so the button is dead before anything is typed.
    // The server would accept this body and audit it — a recorded platform change nobody
    // made — which is the same objection `platform_confirmation` makes to an empty one.
    const { container } = renderAdminPage(<OpsPage />, routes(platform()));

    const button = await screen.findByRole("button", { name: /Switch to normal/ });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(container.textContent).toContain("The platform is already in normal mode");
    // And the confirmation box is dead too, so there is nothing to type past.
    expect((screen.getByPlaceholderText("NORMAL") as HTMLInputElement).disabled).toBe(true);
  });

  it("needs the target typed back and a reason the server would not strip away", async () => {
    renderAdminPage(<OpsPage />, routes(platform()));

    await screen.findByRole("button", { name: /Switch to normal/ });
    fireEvent.change(screen.getByLabelText("Change the mode to"), {
      target: { value: "maintenance" },
    });

    const button = screen.getByRole("button", { name: /Switch to maintenance/ });
    expect((button as HTMLButtonElement).disabled).toBe(true);

    // Whitespace is not a reason: the server strips it and refuses under three chars, so
    // a button that lights up on "   " teaches the operator that the API is flaky.
    fireEvent.change(screen.getByPlaceholderText(/database CPU/), { target: { value: "   " } });
    fireEvent.change(screen.getByPlaceholderText("MAINTENANCE"), {
      target: { value: "MAINTENANCE" },
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);

    // The wrong mode's word is not enough either — this is the guard that keeps consent
    // to `reduced` from authorising `maintenance`.
    fireEvent.change(screen.getByPlaceholderText(/database CPU/), {
      target: { value: "index build" },
    });
    fireEvent.change(screen.getByPlaceholderText("MAINTENANCE"), { target: { value: "REDUCED" } });
    expect((button as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("MAINTENANCE"), {
      target: { value: "MAINTENANCE" },
    });
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("forgets a confirmation typed for a different target", async () => {
    // Type MAINTENANCE, change your mind, pick `reduced` — the old word must not carry
    // over and satisfy a control it was never meant for.
    renderAdminPage(<OpsPage />, routes(platform()));

    await screen.findByRole("button", { name: /Switch to normal/ });
    fireEvent.change(screen.getByLabelText("Change the mode to"), {
      target: { value: "maintenance" },
    });
    fireEvent.change(screen.getByPlaceholderText(/database CPU/), {
      target: { value: "index build" },
    });
    fireEvent.change(screen.getByPlaceholderText("MAINTENANCE"), {
      target: { value: "MAINTENANCE" },
    });
    fireEvent.change(screen.getByLabelText("Change the mode to"), { target: { value: "reduced" } });

    expect((screen.getByPlaceholderText("REDUCED") as HTMLInputElement).value).toBe("");
    expect(
      (screen.getByRole("button", { name: /Switch to reduced/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("says what the target mode sheds, and sends the header bound to that mode", async () => {
    const { calls, container } = renderAdminPage(<OpsPage />, routes(platform()));

    await screen.findByRole("button", { name: /Switch to normal/ });
    fireEvent.change(screen.getByLabelText("Change the mode to"), {
      target: { value: "maintenance" },
    });

    // Blast radius BEFORE the click, and the half that reassures: this console keeps
    // working, so an operator cannot shed themselves out of the switch that undoes it.
    expect(container.textContent).toContain("Client screens go dark");
    expect(container.textContent).toContain("you can always take the platform back out");

    fireEvent.change(screen.getByPlaceholderText(/database CPU/), {
      target: { value: "  planned migration window  " },
    });
    fireEvent.change(screen.getByPlaceholderText("MAINTENANCE"), {
      target: { value: "MAINTENANCE" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Switch to maintenance/ }));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === PLATFORM)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === PLATFORM);
    expect(post?.headers["X-Confirm-Action"]).toBe("set_load_shed:maintenance");
    // NO `outbound_halted`: an absent field means "leave it alone", and sending one would
    // make this request confirmable only with a joined header the console did not send.
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      load_shed_mode: "maintenance",
      reason: "planned migration window",
    });
  });

  it("names the reduced/emergency equivalence rather than implying an escalation", async () => {
    // `is_shed` puts both in `_SHED_WRITES` and neither in `_SHED_READS`, so they shed the
    // same set. An operator who picks `emergency` believing reads stop has spent the
    // escalation and bought nothing — the screen has to say so where they are choosing.
    const { container } = renderAdminPage(<OpsPage />, routes(platform()));

    await screen.findByRole("button", { name: /Switch to normal/ });
    fireEvent.change(screen.getByLabelText("Change the mode to"), {
      target: { value: "emergency" },
    });
    expect(container.textContent).toContain("Sheds exactly what reduced sheds");
  });
});

/** The console's mirror of `ops/routes.py::platform_confirmation`, pinned as the ops
 * PROCEDURE it is — two runbooks print these literals for the curl fallback. */
describe("the step-up strings", () => {
  it("names the transition, and joins both halves halt-first", () => {
    expect(platformConfirmation({ outboundHalted: true })).toBe("halt_outbound");
    expect(platformConfirmation({ outboundHalted: false })).toBe("release_outbound");
    expect(platformConfirmation({ loadShedMode: "maintenance" })).toBe(
      "set_load_shed:maintenance",
    );
    expect(platformConfirmation({ outboundHalted: false, loadShedMode: "normal" })).toBe(
      "release_outbound+set_load_shed:normal",
    );
  });
});

/**
 * Both recovery panels render their button IMMEDIATELY — before `GET /v1/admin/me` has
 * answered — disabled and with no sentence beside it, because a control must never flash
 * an explanation it is about to withdraw (`adminAccess`). So every case below waits for
 * the verdict it is about rather than reading the button in the instant after render,
 * which is a state the operator sees for a few milliseconds and no test should assert on.
 */
async function armReplay(): Promise<HTMLButtonElement> {
  const button = (await screen.findByRole("button", {
    name: /Replay dead letters/,
  })) as HTMLButtonElement;
  // Identity settled, permission held — and still dead, because nothing is typed yet.
  await waitFor(() => expect(button.disabled).toBe(true));
  fireEvent.change(screen.getByPlaceholderText("REPLAY"), { target: { value: "REPLAY" } });
  await waitFor(() => expect(button.disabled).toBe(false));
  return button;
}

describe("the outbox dead-letter replay", () => {
  const replayed = (count: number): OutboxReplayResult => ({ replayed: count });

  it("is dead WITH the reason for a session that lacks ops:manage", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(problem(403, { title: "Forbidden" }), OPERATOR, { [REPLAY]: replayed(3) }),
    );

    const button = await screen.findByRole("button", { name: /Replay dead letters/ });
    // The refusal names the permission AND what it is for, before any click: "change
    // platform-wide switches" would be the wrong description of a dead-letter replay.
    await waitFor(() => {
      expect(container.textContent).toContain("run the platform recovery tools");
    });
    expect(container.textContent).toContain("Ask a superadmin");
    // Typing the word must not revive it — the gate is the permission, not the form.
    fireEvent.change(screen.getByPlaceholderText("REPLAY"), { target: { value: "REPLAY" } });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("stays offered when the PLATFORM row could not be read", async () => {
    // The deliberate asymmetry: this control neither reads nor moves `platform_state`, so
    // coupling it to that read would remove a recovery lever exactly when the platform is
    // behaving strangely. The halt switch is gone, this one is not.
    const { calls } = renderAdminPage(
      <OpsPage />,
      routes(problem(503, { title: "Service unavailable", retryable: true }), SUPERADMIN, {
        [REPLAY]: replayed(4),
      }),
    );

    await screen.findByText("We do not know whether outbound calling is halted");
    fireEvent.click(await armReplay());
    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === REPLAY)).toBe(true);
    });
  });

  it("does not fire on one click, and says whose messages it moves first", async () => {
    const { calls, container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [REPLAY]: replayed(7) }),
    );

    const button = (await screen.findByRole("button", {
      name: /Replay dead letters/,
    })) as HTMLButtonElement;
    expect(container.textContent).toContain(
      "This replays dead letters for EVERY client, not one",
    );
    expect(container.textContent).toContain("delivered a second time");

    // A near-miss must not do it, even once the session is known to be allowed.
    fireEvent.change(screen.getByPlaceholderText("REPLAY"), { target: { value: "replay" } });
    await waitFor(() => expect(container.textContent).toContain("Recorded in the audit log"));
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((c) => c.method === "POST" && c.path === REPLAY)).toBe(false);

    fireEvent.change(screen.getByPlaceholderText("REPLAY"), { target: { value: "REPLAY" } });
    await waitFor(() => expect(button.disabled).toBe(false));
  });

  it("renders the server's count, and flags a full batch as 'there may be more'", async () => {
    // 100 is `replay_dead_letters`'s per-run limit, so it is the one count that does NOT
    // mean the queue is empty — an operator who walks away on it leaves messages parked.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [REPLAY]: replayed(100) }),
    );

    fireEvent.click(await armReplay());

    await screen.findByText("100 messages moved back to pending");
    expect(container.textContent).toContain("That is the per-run limit");
  });

  it("does not claim anything moved when the replay FAILED", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [REPLAY]: problem(500, {
          title: "Server error",
          detail: "The outbox could not be claimed.",
        }),
      }),
    );

    fireEvent.click(await armReplay());

    await screen.findByText("The outbox could not be claimed.");
    expect(screen.queryByText(/moved back to pending/)).toBeNull();
    expect(container.textContent).not.toContain("Nothing was dead-lettered");
  });
});

/** Same reason as `armReplay`: wait for the identity verdict, not for the first paint. */
async function armVerify(): Promise<HTMLButtonElement> {
  const button = (await screen.findByRole("button", {
    name: /Verify the audit chain/,
  })) as HTMLButtonElement;
  // It needs no typed confirmation, so "allowed" and "enabled" are the same moment here.
  await waitFor(() => expect(button.disabled).toBe(false));
  return button;
}

describe("the audit chain verification", () => {
  const verdict = (over: Partial<AuditChainVerdict> = {}): AuditChainVerdict => ({
    ok: true,
    first_bad_entry_id: null,
    checked: "audit_log",
    ...over,
  });

  it("is dead WITH the reason for a session that lacks ops:manage", async () => {
    const { container, calls } = renderAdminPage(
      <OpsPage />,
      routes(problem(403, { title: "Forbidden" }), OPERATOR, { [VERIFY]: verdict() }),
    );

    const button = await screen.findByRole("button", { name: /Verify the audit chain/ });
    await waitFor(() => {
      expect(container.textContent).toContain("run the platform recovery tools");
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    // The refusal arrives BEFORE the click, so the endpoint is never reached — which is
    // the whole point of reading the permission rather than a 403.
    fireEvent.click(button);
    expect(calls.some((c) => c.path === VERIFY)).toBe(false);
  });

  it("renders a FAILED verification as the incident it is, naming the entry", async () => {
    // The dangerous shape: a 200 carrying `ok: false`. The request worked; the ledger did
    // not. Nothing on screen may read as success, and the entry id has to survive on the
    // page rather than in a toast, because it is the evidence.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [VERIFY]: verdict({ ok: false, first_bad_entry_id: "0192f0aa-7777-7000-8000-00000000dead" }),
      }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("AUDIT CHAIN VERIFICATION FAILED");
    expect(container.textContent).toContain("0192f0aa-7777-7000-8000-00000000dead");
    expect(container.textContent).toContain("Treat this as an incident");
    // The reassuring sentence must be nowhere on the page.
    expect(screen.queryByText("Chain intact for the entries checked")).toBeNull();
  });

  it("says a failure it could not localise rather than printing nothing", async () => {
    // `first_bad_entry_id` is nullable on the wire. A template that interpolated it raw
    // would render "The recomputed hash does not match at ." — a sentence that reads like
    // a rendering bug at the moment an operator most needs to trust the screen.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [VERIFY]: verdict({ ok: false, first_bad_entry_id: null }) }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("AUDIT CHAIN VERIFICATION FAILED");
    expect(container.textContent).toContain("an entry the server did not name");
  });

  it("does not report a verdict when the verification request itself failed", async () => {
    renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [VERIFY]: problem(503, { title: "Service unavailable", retryable: true }),
      }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("Service unavailable");
    expect(screen.queryByText("Chain intact for the entries checked")).toBeNull();
    expect(screen.queryByText("AUDIT CHAIN VERIFICATION FAILED")).toBeNull();
  });

  it("does not let an intact verdict read as 'the whole log is verified'", async () => {
    // `verify_chain` walks `ORDER BY at ASC LIMIT 1000` — the OLDEST thousand. On a longer
    // log a green box says nothing about last night, which is the half an operator would
    // otherwise assume, and assuming it is how a tampered recent entry goes unlooked-at.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [VERIFY]: verdict() }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("Chain intact for the entries checked");
    expect(container.textContent).toContain("OLDEST 1,000 entries only");
  });

  it("asks for no typed confirmation, because it writes nothing", async () => {
    // Stated as a property rather than left implicit: a confirmation on a read is friction
    // whose only lesson is that confirmations are things you type past, and the two
    // controls beside it that DO change something would inherit that habit.
    const { calls } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [VERIFY]: verdict() }),
    );

    fireEvent.click(await armVerify());

    await waitFor(() => {
      expect(calls.some((c) => c.path === VERIFY)).toBe(true);
    });
    const read = calls.find((c) => c.path === VERIFY);
    expect(read?.method).toBe("GET");
    expect(read?.headers["X-Confirm-Action"]).toBeUndefined();
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
