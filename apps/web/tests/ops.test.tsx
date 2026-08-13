import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import OpsPage from "@/app/admin/ops/page";
import {
  OUTBOX_REPLAY_CONFIRMATION,
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

/**
 * A dead-letter queue with something in it, which is the DEFAULT for this suite.
 *
 * Deliberate: the replay control is disabled on a queue of depth 0 (there is nothing to
 * replay, and running it anyway records an `ops.outbox_replay` entry for a redelivery
 * nobody performed), so every case below that is about the confirmation, the header or
 * the result needs a non-empty queue to be about anything at all. The empty case has its
 * own test rather than being everyone's premise.
 */
function deadLetters(over: Partial<PlatformState["outbox_dead_letters"]> = {}) {
  return {
    depth: 9,
    oldest_at: "2026-08-04T04:15:00Z",
    by_job: [
      { job: "deliver_outbound_webhook", depth: 6, oldest_at: "2026-08-04T04:15:00Z" },
      { job: "send_hot_lead_email", depth: 3, oldest_at: "2026-08-11T09:00:00Z" },
    ],
    ...over,
  };
}

/** What the server answers a replay with: the count it moved, and the scope it used. */
function replayed(count: number, job: string | null = null): OutboxReplayResult {
  return { replayed: count, job };
}

function platform(over: Partial<PlatformState> = {}): PlatformState {
  return {
    load_shed_mode: "normal",
    outbound_halted: false,
    halt_reason: null,
    outbox_dead_letters: deadLetters(),
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

/**
 * The shell owns the page title. Two headings saying "Operations" is the visible half of
 * a drift: rename the nav entry and the screen goes on arguing with it. Asserted as the
 * ABSENCE of an h1 rather than by naming today's string, because the next screen to grow
 * one would not be caught by a test that only knows this word.
 */
describe("the ops screen leaves its title to the shell", () => {
  it("renders no heading of its own", async () => {
    // `routes(platform())` rather than `routes()`: the first argument is REQUIRED, and
    // omitting it type-errored (TS2554) while vitest passed, because JS handed the stub
    // `undefined` and the screen fell through to its unreadable-state panel — which also
    // contains the string this test waits for. So the green came from the failure path.
    // A rendered SUCCESS is what this assertion is about anyway: a stray `<h1>` would
    // live in one of the panels that only exist once the platform read succeeds.
    const { container } = renderAdminPage(<OpsPage />, routes(platform()));
    // The exact readout, not `/outbound calling/i`: a rendered success says that phrase in
    // a heading, a button and two paragraphs, and `findByText` throws on more than one
    // match — which reads as a broken selector rather than as the premise it is.
    await screen.findByText("Outbound calling is running");
    expect(container.querySelector("h1")).toBeNull();
  });
});

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
  it("names the replay action, with no target to bind because there is only one queue", () => {
    // `runbooks/webhook-delivery-failures.md` prints this for the curl fallback and
    // `ops/routes.py::OUTBOX_REPLAY_CONFIRMATION` is the server's copy. Pinned here so a
    // reformat has to fail a test rather than leave the console sending a refused header.
    expect(OUTBOX_REPLAY_CONFIRMATION).toBe("replay_dead_letters");
    // And it is not equal to any other header this console sends — the property that
    // stops a confirmation captured for the smallest action authorising the largest.
    expect(
      [
        platformConfirmation({ outboundHalted: true }),
        platformConfirmation({ outboundHalted: false }),
        platformConfirmation({ loadShedMode: "maintenance" }),
      ].includes(OUTBOX_REPLAY_CONFIRMATION),
    ).toBe(false);
  });

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
async function armReplay(scope = "*"): Promise<HTMLButtonElement> {
  const button = (await screen.findByRole("button", {
    name: /Replay dead letters/,
  })) as HTMLButtonElement;
  // Identity settled, permission held — and still dead, because nothing is typed yet.
  await waitFor(() => expect(button.disabled).toBe(true));
  // The scope has NO default: the form opens on "— choose —" so that clicking the obvious
  // button can never be a cross-tenant redelivery of everything, chosen by nobody. `"*"`
  // is the every-job option; a job name scopes the run to that job.
  //
  // Wait for the DEPTH, not just for the button: the panel paints its button on the first
  // frame and its scope select only once `outbox_dead_letters` has arrived, so querying
  // synchronously here would read the millisecond before the answer landed.
  await waitFor(() =>
    expect(
      screen.queryByLabelText(/What to replay/) !== null ||
        screen.queryByText("We do not know how many messages are parked") !== null,
    ).toBe(true),
  );
  // `query` rather than `get`: the select is offered only when the breakdown could be
  // READ. On an unreadable queue there is nothing to enumerate, so the run is unscoped
  // and the panel says so — asserted directly in its own case below. The pattern is a
  // regex because the label carries its hint text as well as its name.
  const select = screen.queryByLabelText(/What to replay/);
  if (select) fireEvent.change(select, { target: { value: scope } });
  fireEvent.change(screen.getByPlaceholderText("REPLAY"), { target: { value: "REPLAY" } });
  await waitFor(() => expect(button.disabled).toBe(false));
  return button;
}

describe("the outbox dead-letter replay", () => {
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
    // `find`, not `get`: the panel renders its button immediately and its scope select
    // only once the depth has arrived, so a synchronous query here would be asserting on
    // the millisecond before the read landed.
    fireEvent.change(await screen.findByLabelText(/What to replay/), { target: { value: "*" } });
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

  it("sends the step-up header the typed word was always standing in for", async () => {
    // The half that used to be missing on BOTH sides. The console collected the word and
    // sent no header, because the route accepted none — so nothing but this screen stood
    // between a stolen `ops:manage` session and a cross-tenant redelivery.
    const { calls } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [REPLAY]: replayed(2) }),
    );

    fireEvent.click(await armReplay());

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === REPLAY)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === REPLAY);
    expect(post?.headers["X-Confirm-Action"]).toBe(OUTBOX_REPLAY_CONFIRMATION);
  });

  it("renders a refused confirmation as a refusal to act on, not a red box to retry", async () => {
    // `step_up_required` is the one 4xx here that a retry cannot fix: the console DOES
    // send a header, so a refusal means this build and the API disagree about the string.
    // Rendered generically it reads as "try again", which sends the identical header.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [REPLAY]: problem(403, {
          kind: "permission",
          type: "urn:calevate:error/step_up_required",
          title: "Confirmation required",
          detail: "This action needs an explicit confirmation.",
          remediation: "Repeat the request with the header X-Confirm-Action: replay_dead_letters",
        }),
      }),
    );

    fireEvent.click(await armReplay());

    await screen.findByText(
      "Refused: this console's confirmation is not the one the API expects",
    );
    // The two things a generic error cannot say: nothing happened, and what to do next.
    expect(container.textContent).toContain("Nothing was changed");
    expect(container.textContent).toContain("Reload this page first");
    // The API's own remediation, verbatim — the operator needs the exact header for the
    // runbook's curl, not this screen's paraphrase of it.
    expect(container.textContent).toContain("X-Confirm-Action: replay_dead_letters");
    // And still no count: a refusal is not a result.
    expect(screen.queryByText(/moved back to pending/)).toBeNull();
    expect(container.textContent).not.toContain("Nothing was dead-lettered");
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

/**
 * The depth — the half that makes the confirmation an informed one.
 *
 * The step-up landed on this endpoint and left a different defect: the operator was asked
 * to confirm a redelivery of unknown SIZE, unknown mix and unknown AGE, and the panel said
 * so in its own words because no endpoint published a count. Every other confirmation on
 * this router binds to something the operator can SEE — a tenant id, a target mode, a
 * direction — and a confirmation you cannot size is a habit rather than a control.
 *
 * Ranked by what each failure costs, worst first:
 *
 * 1. **A depth we could not read must never render as "nothing to replay."** It is
 *    `halted ?? false` in a different costume — the same defect BUILD-LOG §52 removed from
 *    this exact screen — and here it would talk an operator out of a recovery they came to
 *    perform. Loading is a skeleton, failure is a refusal, and neither is a number.
 * 2. **The depth is on screen BEFORE the confirmation, not after it.** A count that only
 *    exists in the response is a measurement taken after the irreversible act.
 * 3. **The control's state matches what the depth says**: dead on an empty queue with the
 *    reason beside it, alive on an unreadable one because a recovery lever must not vanish
 *    when the platform is behaving strangely.
 * 4. **The scope is chosen, never defaulted**, and the header carries whichever was
 *    chosen — a header saying "everything" on a request that replays one job describes an
 *    action other than the one being performed.
 */
describe("the dead-letter depth, before the click", () => {
  it("shows the size, the mix and the age above the confirmation", async () => {
    const { container } = renderAdminPage(<OpsPage />, routes(platform(), SUPERADMIN));

    await screen.findByText("9 messages are parked in the dead-letter queue");
    // The mix, because 9 CRM webhooks and 9 hot-lead emails are different things to
    // re-send — this is the sentence a bare total cannot say.
    expect(container.textContent).toContain("deliver_outbound_webhook");
    expect(container.textContent).toContain("send_hot_lead_email");

    // ORDER is the property, not mere presence: a count rendered under the button is a
    // measurement taken after the irreversible act.
    const body = container.textContent ?? "";
    expect(body.indexOf("9 messages are parked")).toBeLessThan(body.indexOf("Type REPLAY"));

    // And the chosen scope is sized in its own sentence, immediately above the
    // confirmation, so the operator confirms a number rather than a verb.
    fireEvent.change(await screen.findByLabelText(/What to replay/), {
      target: { value: "deliver_outbound_webhook" },
    });
    await screen.findByText(/About to re-send up to 6 of the 6 parked/);
    fireEvent.change(screen.getByLabelText(/What to replay/), { target: { value: "*" } });
    // No stray word where the job name would have been on an unscoped run.
    await screen.findByText("About to re-send up to 9 of the 9 parked messages, oldest first.");
  });

  it("REFUSES to state a depth it could not read, rather than showing zero", async () => {
    // The screen's one unrecoverable lie, in this panel's dialect. "Nothing is
    // dead-lettered" over a failed read sends an operator away from the recovery they came
    // for — and the button must survive, because this control does not move a state we
    // failed to read.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(problem(503, { title: "Service unavailable" }), SUPERADMIN, {
        [REPLAY]: replayed(4),
      }),
    );

    await screen.findByText("We do not know how many messages are parked");
    expect(container.textContent).not.toContain("Nothing is dead-lettered");
    expect(container.textContent).not.toContain("messages are parked in the dead-letter queue");
    // Nothing to enumerate, so nothing to choose from: the run is unscoped and says so.
    expect(screen.queryByLabelText(/What to replay/)).toBeNull();

    const button = (await screen.findByRole("button", {
      name: /Replay dead letters/,
    })) as HTMLButtonElement;
    fireEvent.change(screen.getByPlaceholderText("REPLAY"), { target: { value: "REPLAY" } });
    await waitFor(() => expect(button.disabled).toBe(false));
  });

  it("kills the button on an EMPTY queue, with the reason where the button is", async () => {
    // 0 and "we could not read it" are opposite facts, and this is the one that is a fact.
    // The server would accept an empty replay and write an ops.outbox_replay row for a
    // redelivery nobody performed — the load-shed panel's objection to re-asserting the
    // current mode, one step earlier where the operator can still see it.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(
        platform({ outbox_dead_letters: { depth: 0, oldest_at: null, by_job: [] } }),
        SUPERADMIN,
      ),
    );

    await screen.findByText("Nothing is dead-lettered");
    const button = (await screen.findByRole("button", {
      name: /Replay dead letters/,
    })) as HTMLButtonElement;
    fireEvent.change(screen.getByPlaceholderText("REPLAY"), { target: { value: "REPLAY" } });
    await waitFor(() => {
      expect(container.textContent).toContain("so there is nothing to replay");
    });
    expect(button.disabled).toBe(true);
    // The panel is still HERE. runbooks/webhook-delivery-failures.md sends operators to it
    // by name, and one that vanished would make "the runbook is wrong" indistinguishable
    // from "there is nothing parked".
    expect(container.textContent).toContain("Dead-lettered outbox messages");
  });

  it("will not replay until a scope is chosen, and there is no default", async () => {
    const { calls, container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [REPLAY]: replayed(9) }),
    );

    const button = (await screen.findByRole("button", {
      name: /Replay dead letters/,
    })) as HTMLButtonElement;
    fireEvent.change(screen.getByPlaceholderText("REPLAY"), { target: { value: "REPLAY" } });
    await waitFor(() => expect(container.textContent).toContain("Choose what to replay first"));
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("scopes the request AND the confirmation to the job that was chosen", async () => {
    const { calls, container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        "/v1/ops/outbox/replay?job=deliver_outbound_webhook": replayed(
          6,
          "deliver_outbound_webhook",
        ),
      }),
    );

    fireEvent.click(await armReplay("deliver_outbound_webhook"));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    // The scope travels in the query string — it is part of this request's identity, not
    // its content, so it belongs somewhere an access log records.
    expect(post?.path).toBe("/v1/ops/outbox/replay?job=deliver_outbound_webhook");
    // And the header names the SAME scope. A header saying "replay everything" on a
    // request that replays one job describes an action other than the one performed.
    expect(post?.headers["X-Confirm-Action"]).toBe(
      "replay_dead_letters:deliver_outbound_webhook",
    );
    expect(post?.headers["X-Confirm-Action"]).not.toBe(OUTBOX_REPLAY_CONFIRMATION);
    // The SERVER's scope in the result, not this form's memory of it: a `replayed: 0`
    // under a mistyped job is an operator's typo, and reading it back is what shows that.
    await waitFor(() => expect(container.textContent).toContain("6 messages moved back"));
  });

  it("forgets a confirmation typed for a different scope", async () => {
    // The load-shed panel's rule on a bigger blast radius: the header is bound to the
    // scope, so a word typed for "just the webhooks" must not survive a change to "every
    // job" and authorise the larger act.
    renderAdminPage(<OpsPage />, routes(platform(), SUPERADMIN, { [REPLAY]: replayed(9) }));

    const button = (await screen.findByRole("button", {
      name: /Replay dead letters/,
    })) as HTMLButtonElement;
    fireEvent.change(await screen.findByLabelText(/What to replay/), {
      target: { value: "deliver_outbound_webhook" },
    });
    fireEvent.change(screen.getByPlaceholderText("REPLAY"), { target: { value: "REPLAY" } });
    await waitFor(() => expect(button.disabled).toBe(false));

    fireEvent.change(screen.getByLabelText(/What to replay/), { target: { value: "*" } });

    expect((screen.getByPlaceholderText("REPLAY") as HTMLInputElement).value).toBe("");
    expect(button.disabled).toBe(true);
  });

  it("re-reads the depth after a replay instead of leaving a stale one beside it", async () => {
    // Two numbers about one queue from two instants is the defect `GET /v1/ops/platform`
    // exists to prevent; a panel that printed "6 moved" beside a depth measured before
    // they moved would have reintroduced it inside a single card.
    const { calls } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [REPLAY]: replayed(9) }),
    );

    fireEvent.click(await armReplay());

    await waitFor(() => {
      expect(calls.filter((c) => c.method === "GET" && c.path === PLATFORM).length).toBeGreaterThan(
        1,
      );
    });
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
