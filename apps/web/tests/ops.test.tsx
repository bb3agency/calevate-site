import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import OpsPage from "@/app/admin/ops/page";
import {
  OUTBOX_REPLAY_CONFIRMATION,
  platformConfirmation,
  type AuditChainVerdict,
  type ChainBreak,
  type EngineDrift,
  type KbDrift,
  type OutboxReplayResult,
  type PlatformState,
} from "@/lib/api/admin";

import {
  OPS_SECRETS_PATH,
  secretConfirmation,
  type KekState,
  type SecretsList,
} from "@/lib/api/opsSecrets";
import {
  OPS_CONFIG_PATH,
  configConfirmation,
  revertConfirmation,
  type ConfigField,
  type ConfigList,
} from "@/lib/api/opsConfig";

import { formatISTInput, istInputToInstant } from "@/components/ui";

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
  };
}

const SUPERADMIN = me([
  "org:read",
  "admin:tenants",
  "ops:manage",
  "platform:config",
  "platform:secrets",
]);
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
  // The config panel rides this screen, so its read is part of every case's premise —
  // the harness THROWS on an unrouted request rather than 404ing, which is right: an
  // unstubbed endpoint is a hole in the premise. Overridable through `extra`, which the
  // config cases use to make the read fail or to change one field.
  return {
    [PLATFORM]: platformAnswer,
    [ADMIN_ME_PATH]: identity,
    [OPS_CONFIG_PATH]: configList(),
    [OPS_SECRETS_PATH]: secretsList(),
    [`${OPS_SECRETS_PATH}/kek`]: kekState(),
    ...extra,
  };
}

/** Two credentials on purpose: one INSTALLED and one that is not, plus one shadowed by
 *  the environment — three different pieces of markup that a single-row fixture would
 *  leave unscanned. */
function secretsList(over: Partial<SecretsList> = {}): SecretsList {
  return { ...SECRETS_FIXTURE, ...over };
}

const SECRETS_FIXTURE: SecretsList = {
  secrets: [
    {
      key: "bolna_api_key",
      env_var: "BOLNA_API_KEY",
      installed: true,
      version: 2,
      versions: 2,
      last_four: "9f3c",
      kek_id: 1633907231,
      created_at: "2026-08-10T06:30:00Z",
      created_by: "Ops",
      shadowed_by_env: false,
      testable: true,
      applies: "on_restart",
      caveat: "the engine adapter captures this key at construction (D-101)",
    },
    {
      key: "sarvam_api_key",
      env_var: "SARVAM_API_KEY",
      installed: false,
      version: 0,
      versions: 0,
      last_four: "",
      kek_id: 0,
      created_at: null,
      created_by: null,
      shadowed_by_env: true,
      testable: true,
      applies: "live",
      caveat: null,
    },
  ],
};

function kekState(over: Partial<KekState> = {}): KekState {
  return { ...KEK_FIXTURE, ...over };
}

const KEK_FIXTURE: KekState = {
  active_kek_id: 1633907231,
  has_retired_kek: false,
  versions: 2,
  current: 2,
  pending: 0,
};

/** One managed setting, as `GET /v1/ops/config` returns it. */
function configField(over: Partial<ConfigField> = {}): ConfigField {
  return {
    key: "self_serve_inr_per_min",
    env_var: "SELF_SERVE_INR_PER_MIN",
    value: "6.00",
    source: "default",
    default: "6.00",
    has_default: true,
    kind: "decimal",
    options: [],
    editable: true,
    applies: "live",
    caveat: null,
    // The key's concurrency token, sent back as `If-Match` on every write. A field
    // WITHOUT one makes the console refuse to offer a form at all — the API answers 428
    // to an unconditional write (`ops/config_routes.require_if_match`), so a Change
    // button for a key with no token is a control whose only outcome is a refusal.
    // `opsHardening.test.tsx` owns that property; this fixture simply has one.
    etag: '"7"',
    updated_by: null,
    updated_at: null,
    note: null,
    ...over,
  };
}

function configList(over: Partial<ConfigList> = {}): ConfigList {
  return {
    // Required since D-101: the six keys that can only change with an SSH session and a
    // restart. Their ABSENCE used to read identically to "this build has no such
    // setting", which is why the server states them rather than the console inferring.
    bootstrap: [],
    fields: [
      configField(),
      configField({
        key: "object_store_bucket",
        env_var: "OBJECT_STORE_BUCKET",
        value: "calevate-prod",
        source: "env",
        editable: false,
        kind: "string",
        default: null,
        has_default: false,
      }),
    ],
    config_version: 42,
    stale: false,
    never_loaded: false,
    config_changed_at: "2026-08-12T09:00:00Z",
    ...over,
  };
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
    // Added by the slice that regenerated the client after `deferred` landed on
    // `DeadLetterQueueOut`; the field is required on the wire, so a fixture without it
    // is a shape the server never sends.
    deferred: 0,
    oldest_at: "2026-08-04T04:15:00Z",
    by_job: [
      { job: "deliver_outbound_webhook", depth: 6, oldest_at: "2026-08-04T04:15:00Z" },
      { job: "send_hot_lead_email", depth: 3, oldest_at: "2026-08-11T09:00:00Z" },
    ],
    ...over,
  };
}

/**
 * The drift summary, defaulting to a SWEPT and CLEAN platform (D-123).
 *
 * Clean rather than empty on purpose: a default of all-zeroes with a null
 * `oldest_checked_at` is the "no agent has been checked yet" state, and every unrelated
 * ops test would then render a warning banner it was not written to expect.
 */
function engineDrift(over: Partial<EngineDrift> = {}): EngineDrift {
  return {
    live_agents: 4,
    never_checked: 0,
    out_of_sync: 0,
    in_sync: 4,
    undetermined: 0,
    oldest_drift_at: null,
    oldest_checked_at: "2026-08-15T04:07:00Z",
    ...over,
  };
}

/**
 * The knowledge sweep's summary, clean by default for `engineDrift`'s reason: an
 * all-zeroes default with a null `oldest_checked_at` is the "nothing has been checked yet"
 * state, and every unrelated ops test would then render a warning banner it was not
 * written to expect.
 */
function kbDrift(over: Partial<KbDrift> = {}): KbDrift {
  return {
    live_agents: 4,
    never_checked: 0,
    out_of_sync: 0,
    in_sync: 4,
    undetermined: 0,
    oldest_drift_at: null,
    oldest_checked_at: "2026-08-15T00:23:00Z",
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
    engine_drift: engineDrift(),
    kb_drift: kbDrift(),
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
        platform({ outbox_dead_letters: { depth: 0, deferred: 0, oldest_at: null, by_job: [] } }),
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

  it("does NOT say all-clear while messages are deferred behind a backoff", async () => {
    // THE MID-INCIDENT LIE this panel used to tell, and the reason `deferred` exists.
    //
    // During a queue outage `defer_outbox_claim` holds the batch as `pending` with a
    // lease into the future, so the DLQ really is empty and "Nothing is dead-lettered"
    // was a TRUE sentence producing a false screen — a green box for the whole five
    // minutes of tolerated downtime that the backoff buys, which is exactly the window
    // an operator is looking at it in. The all-clear now follows the queue's health
    // rather than the one state this panel happens to act on.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(
        platform({
          outbox_dead_letters: { depth: 0, deferred: 214, oldest_at: null, by_job: [] },
        }),
        SUPERADMIN,
      ),
    );

    await screen.findByText("214 messages are waiting on a retry backoff");
    expect(container.textContent).not.toContain("Nothing is dead-lettered");
    // And it must not read as something the button fixes: replay acts on `failed` rows
    // and would move none of these. An operator told "there is a backlog" beside a live
    // replay button will press it, and then believe they have done something.
    expect(container.textContent).toContain("Replaying does nothing for them");
    const button = (await screen.findByRole("button", {
      name: /Replay dead letters/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("shows dead letters and deferred messages side by side when both are real", async () => {
    // The state after the backoff ran out mid-outage: some messages burned through the
    // budget and some are still waiting. Both numbers have to be on screen — a panel
    // that showed only the DLQ would tell the operator the incident is over.
    renderAdminPage(
      <OpsPage />,
      routes(platform({ outbox_dead_letters: deadLetters({ deferred: 31 }) }), SUPERADMIN),
    );

    await screen.findByText("9 messages are parked in the dead-letter queue");
    await screen.findByText("31 messages are waiting on a retry backoff");
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

describe("what the voice platform is running", () => {
  it("names the drifted agents as an alarm, and the unreadable ones as NOT one", async () => {
    // The distinction the whole panel turns on. `agents/verification.py` keeps "provably
    // running something else" apart from "we could not read the answer" at the source, and
    // a console that added them would report a slow vendor as a fleet of agents speaking
    // unapproved scripts — a number an operator learns to ignore inside a week.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(
        platform({
          engine_drift: engineDrift({
            live_agents: 10,
            in_sync: 6,
            out_of_sync: 2,
            undetermined: 2,
            oldest_drift_at: "2026-08-01T04:07:00Z",
          }),
        }),
        SUPERADMIN,
      ),
    );

    await screen.findByText("2 of 10 live agents are running something else");
    expect(container.textContent).toContain("Oldest divergence");
    expect(container.textContent).not.toContain("4 of 10");
    // NO LEVER. Re-publishing over a drift overwrites whatever the vendor's console was
    // used to change, so the console must not offer that as one click from a summary.
    expect(screen.queryByRole("button", { name: /publish/i })).toBeNull();
  });

  it("says nobody is watching when the sweep has never run, instead of all-clear", async () => {
    // The panel's own version of the DLQ's "0 is not the same as unread". If the cron
    // dies, every count freezes and `out_of_sync: 0` reads as all-clear forever;
    // `oldest_checked_at` is the only field that can say otherwise.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(
        platform({
          engine_drift: engineDrift({
            live_agents: 3,
            in_sync: 0,
            never_checked: 3,
            oldest_checked_at: null,
          }),
        }),
        SUPERADMIN,
      ),
    );

    await screen.findByText("No agent has been checked yet");
    expect(container.textContent).not.toContain("Every checked agent is running what we published");
    expect(container.textContent).toContain("never");
  });

  it("REFUSES to state a drift count it could not read, rather than showing zero", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(problem(503, { title: "Service unavailable" }), SUPERADMIN),
    );

    await screen.findByText("We do not know what the voice platform is running");
    expect(container.textContent).not.toContain("Every checked agent is running what we published");
    expect(container.textContent).not.toContain("live agents are running something else");
  });

  it("treats a payload with no drift field as unreadable, not as an all-clear", async () => {
    // Against a CURRENT server this cannot happen — `engine_drift` is required on the
    // wire. Against an older one it can, and mid-deploy is exactly when someone is on
    // this screen. The narrowing has to hold at runtime because `read !== null` is true
    // for `undefined`: before it did, this rendered a blank ops console, taking the big
    // red switch down with it. Found by axe's screen scan, which renders with a bare
    // payload; pinned here because a11y would not say WHY it broke.
    const withoutDrift: Record<string, unknown> = { ...platform() };
    delete withoutDrift.engine_drift;
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(withoutDrift, SUPERADMIN),
    );

    await screen.findByText("We do not know what the voice platform is running");
    // And the rest of the screen survived — this panel must never be able to blank the
    // incident levers beside it.
    expect(container.textContent).toContain("Load-shed mode");
  });

  it("reports an all-clear only when the sweep has actually run", async () => {
    const { container } = renderAdminPage(<OpsPage />, routes(platform(), SUPERADMIN));

    await screen.findByText("Every checked agent is running what we published");
    expect(container.textContent).toContain("What the voice platform is running");
    expect(container.textContent).not.toContain("No agent has been checked yet");
  });
});

describe("what the voice platform is answering from", () => {
  it("names knowledge we did not publish as an alarm, and undecided reads as NOT one", async () => {
    // Same split as the agent panel and it matters more here: an empty knowledge listing
    // is ambiguous between "the documents are gone" and "the vendor does not attribute its
    // listing by agent" (pilot gate 8, open), so folding `undetermined` into the alarm
    // would report an unanswered vendor question as a fleet of clients whose knowledge
    // vanished.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(
        platform({
          kb_drift: kbDrift({
            live_agents: 10,
            in_sync: 6,
            out_of_sync: 2,
            undetermined: 2,
            oldest_drift_at: "2026-08-01T00:23:00Z",
          }),
        }),
        SUPERADMIN,
      ),
    );

    await screen.findByText("2 of 10 live agents hold knowledge we did not publish");
    expect(container.textContent).toContain("Oldest divergence");
    // NO LEVER, and here the reason is stronger than on the panel above: the repair a
    // knowledge drift invites is an irreversible DELETE at the vendor of a document our
    // tables cannot describe.
    expect(screen.queryByRole("button", { name: /remove|detach|delete/i })).toBeNull();
  });

  it("says nobody is watching when the knowledge sweep has never run", async () => {
    // The two sweeps have two pulses on purpose: a healthy agent sweep must not be able to
    // vouch for a knowledge sweep that died, so this panel reads its OWN timestamp. The
    // fixture leaves `engine_drift` healthy, which is exactly the state that would hide
    // this if the two shared a field.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(
        platform({
          kb_drift: kbDrift({
            live_agents: 3,
            in_sync: 0,
            never_checked: 3,
            oldest_checked_at: null,
          }),
        }),
        SUPERADMIN,
      ),
    );

    await screen.findByText("No agent's knowledge has been checked yet");
    expect(container.textContent).toContain("Every checked agent is running what we published");
  });

  it("REFUSES to state a knowledge count it could not read, rather than showing zero", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(problem(503, { title: "Service unavailable" }), SUPERADMIN),
    );

    await screen.findByText("We do not know what knowledge the voice platform is holding");
    expect(container.textContent).not.toContain(
      "Every checked agent is answering from what we published",
    );
  });

  it("treats a payload with no kb_drift field as unreadable, not as an all-clear", async () => {
    // Against a CURRENT server this cannot happen — `kb_drift` is required on the wire.
    // Against an older one it can, and mid-deploy is exactly when someone is on this
    // screen; `read !== null` is true for `undefined`, which is not a type error and is a
    // blank ops console.
    const withoutKbDrift: Record<string, unknown> = { ...platform() };
    delete withoutKbDrift.kb_drift;
    const { container } = renderAdminPage(<OpsPage />, routes(withoutKbDrift, SUPERADMIN));

    await screen.findByText("We do not know what knowledge the voice platform is holding");
    // The rest of the screen survived, including the OTHER drift panel — one missing
    // field must not take the incident levers down with it.
    expect(container.textContent).toContain("Load-shed mode");
    expect(container.textContent).toContain("Every checked agent is running what we published");
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
    // The SCOPE travels with the verdict now. A fixture that omitted it would let the
    // panel render "whole log checked" off a default, which is the shape this test exists
    // to catch — `complete` is the server's claim, never the client's assumption.
    entries_checked: 4210,
    complete: true,
    oldest_checked_at: "2026-08-11T04:30:00Z",
    newest_checked_at: "2026-08-13T09:15:00Z",
    breaks: [],
    breaks_found: 0,
    // Zero is the honest default for a deployment that has always been configured, and
    // it is the value that must render NOTHING — an "0 entries under a retired key"
    // line would be a caveat about a problem this log does not have.
    entries_under_retired_key: 0,
    ...over,
  });

  /** A break, spelled the way the server spells one. */
  const chainBreak = (over: Partial<ChainBreak> = {}): ChainBreak => ({
    entry_id: "0192f0aa-7777-7000-8000-00000000dead",
    at: "2026-08-13T09:15:00Z",
    kind: "link",
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
        [VERIFY]: verdict({
          ok: false,
          first_bad_entry_id: "0192f0aa-7777-7000-8000-00000000dead",
          breaks: [chainBreak()],
          breaks_found: 1,
        }),
      }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("AUDIT CHAIN VERIFICATION FAILED");
    expect(container.textContent).toContain("0192f0aa-7777-7000-8000-00000000dead");
    expect(container.textContent).toContain("Treat this as an incident");
    // The reassuring sentence must be nowhere on the page.
    expect(screen.queryByText("Chain intact for the entries checked")).toBeNull();
  });

  it("names EVERY break, not just the first, and dates them", async () => {
    /* The reason the verdict grew a list. `audit_log` is append-only, so a break can
       never be repaired — which means a real historical one is permanent, and a panel
       that showed only the earliest would show that same scar every quarter while a
       fresh break behind it stayed invisible. Worse as an attack: damage something from
       six months ago and verification of last night switches itself off. The dates are
       what let an operator say "two of these are the known March incident and this one
       is from Tuesday". */
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [VERIFY]: verdict({
          ok: false,
          first_bad_entry_id: "0192f0aa-1111-7000-8000-000000000001",
          breaks: [
            chainBreak({ entry_id: "0192f0aa-1111-7000-8000-000000000001", kind: "link" }),
            chainBreak({
              entry_id: "0192f0aa-2222-7000-8000-000000000002",
              kind: "content",
              at: "2026-08-13T11:45:00Z",
            }),
          ],
          breaks_found: 2,
        }),
      }),
    );

    fireEvent.click(await armVerify());
    await screen.findByText("AUDIT CHAIN VERIFICATION FAILED");

    // BOTH ids, because the second one is the whole point of the change.
    expect(container.textContent).toContain("0192f0aa-1111-7000-8000-000000000001");
    expect(container.textContent).toContain("0192f0aa-2222-7000-8000-000000000002");
    // And the two KINDS are distinguished — "edited" and "reordered" are different
    // incidents with different next moves.
    expect(container.textContent).toContain("no longer hash");
    expect(container.textContent).toContain("wrong predecessor");
    // The scope still travels with the verdict on the failure path, which is where it
    // was previously dropped: a break used to truncate the walk, so a red box said
    // nothing about how much of the log had been looked at.
    expect(container.textContent).toContain("Whole log checked");
  });

  it("says how many breaks it did NOT list once the cap bites", async () => {
    // A capped list rendered as a complete one is the same defect as a bounded walk
    // rendered as a full audit, one level down: the operator counts the rows on screen
    // and reports that number.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [VERIFY]: verdict({
          ok: false,
          first_bad_entry_id: "0192f0aa-1111-7000-8000-000000000001",
          breaks: [chainBreak({ entry_id: "0192f0aa-1111-7000-8000-000000000001" })],
          breaks_found: 47,
        }),
      }),
    );

    fireEvent.click(await armVerify());
    await screen.findByText("AUDIT CHAIN VERIFICATION FAILED");

    expect(container.textContent).toContain("47 places");
    expect(container.textContent).toContain("46 more");
  });

  it("says a failure it could not localise rather than printing nothing", async () => {
    // `first_bad_entry_id` is nullable on the wire. A template that interpolated it raw
    // would render "The recomputed hash does not match at ." — a sentence that reads like
    // a rendering bug at the moment an operator most needs to trust the screen.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [VERIFY]: verdict({ ok: false, first_bad_entry_id: null, breaks: [], breaks_found: 1 }),
      }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("AUDIT CHAIN VERIFICATION FAILED");
    expect(container.textContent).toContain("an entry it did not name");
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
    // The scope belongs to the SERVER now: `verify_chain` reports how many links it
    // recomputed and whether it reached the end, and this panel renders those two facts
    // rather than a sentence about a limit. A green box that silently covered only part
    // of the log is how a tampered recent entry goes unlooked-at.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [VERIFY]: verdict() }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("Chain intact for the entries checked");
    // The SERVER's scope, not a sentence about a limit the route no longer has.
    expect(container.textContent).toContain("Whole log checked");
  });

  it("never lets a PARTIAL walk read like a full audit", async () => {
    /* The dangerous shape, and the reason the console renders the server's numbers
       rather than a sentence about them. `ok: true` with `complete: false` means every
       link the walk reached recomputed cleanly AND the walk did not reach the end — a
       green box on its own would invite exactly the reading the scope exists to refuse.
       This panel's copy was hard-coded to "the oldest 1,000 entries" for precisely this
       reason, and that string outlived the limit it described. */
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [VERIFY]: verdict({ ok: true, complete: false, entries_checked: 1000 }),
      }),
    );
    fireEvent.click(await armVerify());
    await screen.findByText(/1,000 entries only/);

    expect(container.textContent).not.toContain("Whole log checked");
    expect(container.textContent).toContain("says nothing about the rest of the log");
  });

  it("names the weakly-attested era on an INTACT log, because ok is not the whole answer", async () => {
    /* `entries_under_retired_key` is not a break and does not move `ok` — those rows
       hash correctly. What they lack is attestation STRENGTH: they were signed before
       this deployment had its own AUDIT_CHAIN_SECRET, when the key was a constant in
       the source, so anyone who could read the repository could have produced one that
       verifies. A green box that says only "intact" is what puts that era into an
       evidence export unremarked. */
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [VERIFY]: verdict({ ok: true, entries_under_retired_key: 812 }),
      }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("Chain intact for the entries checked");
    expect(container.textContent).toContain("812 entries verified under a retired signing key");
    // Still intact — the caveat must not be written as a failure.
    expect(container.textContent).toContain("they are not a break");
  });

  it("says nothing about retired keys when there are none", async () => {
    // Zero is the answer on a deployment that has always been configured, and a caveat
    // about a problem the log does not have is how operators learn to skim caveats.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, { [VERIFY]: verdict() }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("Chain intact for the entries checked");
    expect(container.textContent).not.toContain("retired signing key");
  });

  it("carries the retired-key caveat onto a FAILED verdict too", async () => {
    // The two facts are independent: a log can be broken AND partly weakly attested,
    // and the era question applies either side of the break.
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [VERIFY]: verdict({
          ok: false,
          first_bad_entry_id: chainBreak().entry_id,
          breaks: [chainBreak()],
          breaks_found: 1,
          entries_under_retired_key: 3,
        }),
      }),
    );

    fireEvent.click(await armVerify());

    await screen.findByText("AUDIT CHAIN VERIFICATION FAILED");
    expect(container.textContent).toContain("3 entries verified under a retired signing key");
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

  /**
   * THE REGISTRATION TIMESTAMP, IN A BROWSER THAT IS NOT IN INDIA.
   *
   * The field held "the IST moment on the registrar's letter" — its own comment said so —
   * and read `at.getHours()`, the BROWSER's wall clock, in both directions. Correct on a
   * machine set to India and silently wrong everywhere else, which for an admin console is
   * not a hypothetical: D-22 "view as client" and a colleague on a laptop still set to a US
   * zone are ordinary sessions.
   *
   * The value is IST BY ITS NATURE — it is a timestamp on an Indian DLT registrar's letter,
   * not a local reading of when the operator happened to be sitting down — so both
   * directions are pinned to `Asia/Kolkata` and the input says IST on screen.
   *
   * The zone is moved FOR REAL rather than mocked, the way `quality.test.tsx` does it: Node
   * re-reads `process.env.TZ` on assignment, so this is the same code path a browser in New
   * York takes. `06:30Z` is chosen because it is the value that separates the two
   * implementations — 12:00 IST the same day, and 01:30 the same day in New York, so a
   * fixture that merely differed by hours could still pass on the date alone.
   */
  it("reads and writes the registration date in IST, from a browser outside India", async () => {
    const original = process.env.TZ;
    process.env.TZ = "America/New_York";
    try {
      const { calls } = renderAdminPage(
        <OpsPage />,
        routes(platform(), SUPERADMIN, {
          "POST /v1/ops/platform/tm-registration": {
            status: "active",
            tm_id: "TM-110022",
            registered_at: "2026-01-04T06:30:00Z",
            verified_at: "2026-08-01T06:30:00Z",
            is_live: true,
          },
        }),
      );

      // READ. 2026-01-04T06:30:00Z is 12:00 IST — what the letter says — and 01:30 in the
      // browser's own zone, which is what the field used to show.
      const field = (await screen.findByDisplayValue("2026-01-04T12:00")) as HTMLInputElement;
      expect(field.type).toBe("datetime-local");

      // THE LABEL IS PART OF THE FIX. A `datetime-local` carries no zone, so an unlabelled
      // one means "this machine's clock" to every reader; a field that quietly means
      // something else is worse than the bug, because nobody can tell which they typed.
      expect(screen.getByText("Registered on (IST)")).toBeTruthy();

      // WRITE. The operator retypes what the letter says — 14:45 IST on the 9th — and the
      // instant that leaves must be 09:15Z, never the 19:45Z a New York reading produces.
      fireEvent.change(field, { target: { value: "2026-01-09T14:45" } });
      fireEvent.change(screen.getByPlaceholderText(/registrar grant letter/), {
        target: { value: "registrar grant letter 2026-01-09" },
      });
      fireEvent.change(screen.getByPlaceholderText("RECORD"), { target: { value: "RECORD" } });
      fireEvent.click(screen.getByRole("button", { name: /Record registration as active/ }));

      await waitFor(() => {
        expect(calls.some((c) => c.path === "/v1/ops/platform/tm-registration")).toBe(true);
      });
      const sent = calls.find((c) => c.path === "/v1/ops/platform/tm-registration");
      expect(JSON.parse(sent?.body ?? "{}").registered_at).toBe("2026-01-09T09:15:00.000Z");
    } finally {
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    }
  });

  /**
   * The codec's two edges, asserted directly because neither is reachable from the form.
   *
   * MIDNIGHT is the one an `Intl` mistake produces silently: `hour12: false` resolves to
   * `h24` under some locale data and renders 00:00 as "24:00", which no `datetime-local`
   * accepts — the field would simply go blank, on the one value nobody thinks to try.
   * `hourCycle: "h23"` in `components/ui.tsx` is what prevents it, and a future
   * simplification back to `hour12` would pass every other test in this file.
   */
  it("round-trips IST midnight, which is where an hourCycle mistake would hide", () => {
    const original = process.env.TZ;
    process.env.TZ = "America/New_York";
    try {
      // 2026-01-08T18:30:00Z is exactly 00:00 IST on the 9th — a different DAY in New York.
      expect(formatISTInput("2026-01-08T18:30:00Z")).toBe("2026-01-09T00:00");
      expect(istInputToInstant("2026-01-09T00:00")).toBe("2026-01-08T18:30:00.000Z");
      // Absent stays absent, in both directions: a field nobody filled in is not midnight.
      expect(formatISTInput(null)).toBe("");
      expect(istInputToInstant("")).toBeNull();
      expect(istInputToInstant("not a date")).toBeNull();
    } finally {
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    }
  });
});

/**
 * The platform-configuration panel (PLATFORM-CONFIG §8 panel 2).
 *
 * Ranked by what each failure costs, worst first — the same ordering the rest of this
 * file uses, because it is the same screen and the same operator:
 *
 * 1. **A read we could not make must never render as a table of values.** Every other
 *    panel here can lie about one fact; this one would lie about thirty-six at once, each
 *    of them a plausible-looking default an operator would then act on. §52's rule, at
 *    its highest stake on this screen.
 * 2. **A key the ENVIRONMENT pins is read-only WITH the reason.** The store cannot win
 *    against `os.environ` (§4), so an editable box for such a key would be a control
 *    whose only outcome is a refusal — "a field that silently does nothing is worse than
 *    no field" (§8). The screen must show the value, refuse the edit, and name the
 *    variable to change instead.
 * 3. **A write is not one click, and its confirmation is bound to the KEY.** The header
 *    on the wire is what the API checks, so a test that only asserted the button worked
 *    would pass with the binding removed — and a confirmation captured while raising a
 *    pool size would switch the voice engine.
 * 4. **Staleness is stated.** A process that has never read the store is running on its
 *    environment and its defaults, and a change made on this screen may not be reflected
 *    by it. That is a sentence, not a silence.
 */
describe("the platform configuration panel", () => {
  it("refuses to show values it did not receive", async () => {
    renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [OPS_CONFIG_PATH]: problem(503, {
          title: "Service unavailable",
          detail: "The database is not reachable.",
        }),
      }),
    );

    await screen.findByText("We could not read the platform configuration");
    // Not a table of defaults, and not an empty state that reads as "nothing is managed".
    expect(screen.queryByText("self_serve_inr_per_min")).toBeNull();
  });

  it("renders an env-pinned key read-only, with the variable that pins it", async () => {
    const { container } = renderAdminPage(<OpsPage />, routes(platform()));

    await screen.findByText("object_store_bucket");
    // The value is SHOWN — hiding it would leave an operator hunting for a setting they
    // can see in .env.
    expect(screen.getByText("calevate-prod")).toBeTruthy();
    // …and the refusal names the variable, so they know where to go instead.
    expect(container.textContent).toContain("OBJECT_STORE_BUCKET");
    expect(container.textContent).toContain("The environment always wins over the console");
  });

  it("sends the confirmation bound to the key it is changing", async () => {
    const { calls } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: {
          key: "self_serve_inr_per_min",
          previous: null,
          field: configField({ value: "7.25", source: "db" }),
          config_version: 43,
          recorded: true,
          etag: '"8"',
        },
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);

    const [valueInput] = screen.getAllByDisplayValue("6.00");
    fireEvent.change(valueInput, { target: { value: "7.25" } });
    fireEvent.change(screen.getByPlaceholderText(/Q3 price change/), {
      target: { value: "Q3 self-serve price change" },
    });

    const save = screen.getByRole("button", { name: /^Save$/ });
    // Dead until the key itself has been typed — the same shape as the switches above.
    expect((save as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("SELF_SERVE_INR_PER_MIN"), {
      target: { value: "SELF_SERVE_INR_PER_MIN" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "PUT")).toBe(true);
    });
    const write = calls.find((c) => c.method === "PUT");
    expect(write?.path).toBe(`${OPS_CONFIG_PATH}/self_serve_inr_per_min`);
    // THE BINDING, on the wire. The API refuses a header that names another key.
    // The literal, for the reason the credential test above records: an assertion
    // against the function under test cannot see the two sides move together.
    expect(write?.headers["X-Confirm-Action"]).toBe("set_config:self_serve_inr_per_min");
    expect(configConfirmation("self_serve_inr_per_min")).toBe(
      "set_config:self_serve_inr_per_min",
    );
    // Money leaves as a STRING. A `number` input would have handed us a float, and
    // `usd_inr_rate` is stamped into usage_events.meta (hard rule 7).
    expect(JSON.parse(write?.body ?? "{}")).toEqual({
      value: "7.25",
      reason: "Q3 self-serve price change",
    });
  });

  it("uses a DIFFERENT confirmation string to revert", async () => {
    const { calls } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [OPS_CONFIG_PATH]: configList({
          fields: [configField({ value: "7.25", source: "db", updated_by: "Ops" })],
        }),
        [`DELETE ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: {
          key: "self_serve_inr_per_min",
          previous: "7.25",
          field: configField(),
          config_version: 44,
          recorded: true,
          etag: '"0"',
        },
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getByRole("button", { name: /Change/ }));
    fireEvent.change(screen.getByPlaceholderText("SELF_SERVE_INR_PER_MIN"), {
      target: { value: "SELF_SERVE_INR_PER_MIN" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Revert to default/ }));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "DELETE")).toBe(true);
    });
    const revert = calls.find((c) => c.method === "DELETE");
    expect(revert?.headers["X-Confirm-Action"]).toBe("revert_config:self_serve_inr_per_min");
    expect(revertConfirmation("self_serve_inr_per_min")).toBe(
      "revert_config:self_serve_inr_per_min",
    );
    // Not the same string as a set: reverting puts a value nobody has looked at in
    // months back into force, and a header captured for either must not authorise the
    // other.
    expect(revert?.headers["X-Confirm-Action"]).not.toBe(
      configConfirmation("self_serve_inr_per_min"),
    );
  });

  it("says so when the serving process has never read the store", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [OPS_CONFIG_PATH]: configList({ never_loaded: true, config_version: 0 }),
      }),
    );

    await screen.findByText("This process has never read the configuration store");
    expect(container.textContent).toContain(
      "nothing set from this console is in force here",
    );
  });

  it("distinguishes a stale refresh from a process that never loaded", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [OPS_CONFIG_PATH]: configList({ stale: true }),
      }),
    );

    await screen.findByText("The last refresh of the configuration failed");
    // The values are REAL, just possibly behind — the opposite reading from `never_loaded`,
    // and the operator's next move differs.
    expect(container.textContent).toContain("last ones read successfully");
    expect(screen.queryByText("This process has never read the configuration store")).toBeNull();
  });

  it("warns on a setting that will not take effect until a restart", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [OPS_CONFIG_PATH]: configList({
          fields: [
            configField({
              key: "db_pool_size",
              env_var: "DB_POOL_SIZE",
              value: 16,
              default: 16,
              kind: "integer",
              applies: "on_restart",
              caveat: "the SQLAlchemy engine is built once per process",
            }),
          ],
        }),
      }),
    );

    await screen.findByText("db_pool_size");
    // A field that quietly does nothing for six hours is §8's defect wearing a delay.
    expect(container.textContent).toContain("Needs a restart to take effect");
  });

  it("keeps the controls dead for a session without platform:config", async () => {
    renderAdminPage(<OpsPage />, routes(platform(), OPERATOR));

    await screen.findByText("self_serve_inr_per_min");
    const change = screen.getAllByRole("button", { name: /Change/ })[0] as HTMLButtonElement;
    // The permission is NOT ops:manage — an operator who may run the recovery tools
    // still has no business switching the platform's voice engine (§7).
    expect(change.disabled).toBe(true);
  });

  /**
   * THE TWO SETTINGS WHOSE BLAST RADIUS IS WIDEST WERE FILED UNDER "no group for yet".
   *
   * "Other" is a safety net — a key this console has never heard of stays editable — and
   * it is the wrong home for a key whose change is a commercial or security event.
   * `azure_openai_model` is a LIVE switch between two models 2.7x apart on price, so it
   * moves every in-call token bill AND every "about N assists" a client reads
   * (`billing/ai_quota.assist_nominal_inr` derives that estimate per model);
   * `first_party_auth_enabled` is the kill switch over the only authentication this
   * product has. Both arrived after the group list was written — the Azure keys with
   * D-410, the auth switch with D-177 — and prefix matching cannot notice that on its
   * own, which is the whole reason this test exists rather than a comment.
   */
  it("files the language model and the sign-in switch under their own headings", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [OPS_CONFIG_PATH]: configList({
          fields: [
            configField({
              key: "azure_openai_model",
              env_var: "AZURE_OPENAI_MODEL",
              value: "gpt-4o-mini",
              default: "gpt-4o-mini",
              kind: "string",
            }),
            configField({
              key: "first_party_auth_enabled",
              env_var: "FIRST_PARTY_AUTH_ENABLED",
              value: true,
              default: true,
              kind: "boolean",
            }),
          ],
        }),
      }),
    );

    await screen.findByText("azure_openai_model");
    expect(screen.getByText("Language model")).toBeTruthy();
    expect(screen.getByText("Sign-in")).toBeTruthy();
    // The bucket that says this console has no opinion about a setting — neither of
    // these may land in it.
    expect(container.textContent).not.toContain("Settings this console has no group for yet");
  });
});

/**
 * Credentials and key management (PLATFORM-CONFIG §8 panels 3-4).
 *
 * Ranked by cost, worst first:
 *
 * 1. **No plaintext, on any screen, ever.** §7's rule is a property of the API, and this
 *    asserts the console never grows a field for one — including through the `/test`
 *    flow, which is the one place a credential is in the browser's memory.
 * 2. **A read we could not make must not render as "not installed".** That reads as "this
 *    platform has no Sarvam key", and an operator would install one over a working
 *    credential. §52 at its highest stake on this screen.
 * 3. **A credential the environment shadows says so.** Otherwise an operator rotates a
 *    key here and the platform goes on using the one in `.env` — §4's precedence turning
 *    into a silent no-op.
 * 4. **`pending > 0` blocks the environment cleanup, in those words.** The whole point of
 *    the key-management panel is that removing `PLATFORM_KEK_RETIRED` too early makes
 *    rows permanently unreadable.
 */
/** The credential box. `type="password"` has no accessible role, so it is addressed the
 *  way a browser would find it rather than through a label this panel deliberately keeps
 *  short — and it throws rather than returning null, so a form that failed to open reads
 *  as the premise failure it is instead of an unhelpful "cannot fire change". */
function secretInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>('input[type="password"]');
  if (!input) throw new Error("the credential form is not open — did the button render disabled?");
  return input;
}

describe("the credentials panel", () => {
  it("never puts a credential on screen, including after a test", async () => {
    const { container, calls } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [`POST ${OPS_SECRETS_PATH}/bolna_api_key/test`]: {
          key: "bolna_api_key",
          outcome: "accepted",
          status: 200,
          detail: "The vendor accepted this credential for one authenticated read.",
          verified: false,
          candidate_last_four: "cdef",
        },
      }),
    );

    await screen.findByText("bolna_api_key");
    fireEvent.click(screen.getAllByRole("button", { name: /Rotate|Install/ })[0]);
    const secret = "bn-live-secret-abcdef";
    fireEvent.change(secretInput(), { target: { value: secret } });
    fireEvent.click(screen.getByRole("button", { name: /Test with the vendor/ }));

    // The TITLE carries the epistemic status: this fixture is `verified: false`, which
    // every probe in this build is, so the box may not read as a plain acceptance.
    // `opsHardening.test.tsx` owns that property; here it is only the anchor.
    await screen.findByText("The vendor accepted this credential — indicative, not confirmed");
    // The value went to the API and came back nowhere. The response carries four
    // characters and the screen shows those four and nothing more.
    expect(container.textContent).not.toContain(secret);
    expect(container.textContent).toContain("…cdef");
    // And the test STORED nothing: no PUT was made.
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("marks an unverified probe as indicative rather than authoritative", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [`POST ${OPS_SECRETS_PATH}/bolna_api_key/test`]: {
          key: "bolna_api_key",
          outcome: "rejected",
          status: 401,
          detail: "The vendor refused this credential.",
          verified: false,
          candidate_last_four: "wxyz",
        },
      }),
    );
    await screen.findByText("bolna_api_key");
    fireEvent.click(screen.getAllByRole("button", { name: /Rotate|Install/ })[0]);
    fireEvent.change(secretInput(), { target: { value: "a-wrong-key-wxyz" } });
    fireEvent.click(screen.getByRole("button", { name: /Test with the vendor/ }));

    await screen.findByText("The vendor REFUSED this credential — indicative, not confirmed");
    // OPERATIONS §2: an unverified vendor behaviour is a MARKED assumption.
    expect(container.textContent).toContain("not been confirmed against the live vendor");
  });

  it("refuses to report 'not installed' from a read that failed", async () => {
    renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [OPS_SECRETS_PATH]: problem(503, { title: "Service unavailable" }),
      }),
    );
    await screen.findByText("We could not read which credentials are installed");
    expect(screen.queryByText("bolna_api_key")).toBeNull();
  });

  it("says when a stored credential is inert because the environment sets it", async () => {
    const { container } = renderAdminPage(<OpsPage />, routes(platform()));
    await screen.findByText("sarvam_api_key");
    expect(container.textContent).toContain("SARVAM_API_KEY");
    expect(container.textContent).toContain("the environment always wins");
  });

  it("sends the key-bound confirmation when installing", async () => {
    const { calls } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [`PUT ${OPS_SECRETS_PATH}/bolna_api_key`]: {
          ...SECRETS_FIXTURE.secrets[0],
          version: 3,
          versions: 3,
        },
      }),
    );
    await screen.findByText("bolna_api_key");
    fireEvent.click(screen.getAllByRole("button", { name: /Rotate|Install/ })[0]);
    fireEvent.change(secretInput(), { target: { value: "bn-live-new-key-0001" } });
    fireEvent.change(screen.getByPlaceholderText(/rotating after/), {
      target: { value: "vendor breach notice" },
    });
    fireEvent.change(screen.getByPlaceholderText("BOLNA_API_KEY"), {
      target: { value: "BOLNA_API_KEY" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Rotate$/ }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const write = calls.find((c) => c.method === "PUT");
    // THE LITERAL, not `secretConfirmation("bolna_api_key")`. Comparing the header
    // against the same function that produced it asserts nothing — a sabotage that
    // unbound the string left this green, because both sides moved together. The API
    // owns this vocabulary (`ops/secret_routes.secret_confirmation`) and a runbook
    // prints it, so the console's copy is pinned to the literal it must match.
    expect(write?.headers["X-Confirm-Action"]).toBe("set_secret:bolna_api_key");
    expect(secretConfirmation("bolna_api_key")).toBe("set_secret:bolna_api_key");
  });
});

describe("the key-management panel", () => {
  it("tells the operator NOT to remove the retired key while any DEK is pending", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [`${OPS_SECRETS_PATH}/kek`]: kekState({
          has_retired_kek: true,
          versions: 5,
          current: 2,
          pending: 3,
        }),
      }),
    );
    await screen.findByText("3 stored versions are still wrapped under another key");
    // The sentence that prevents permanent data loss, in the imperative.
    expect(container.textContent).toContain(
      "Do not remove PLATFORM_KEK_RETIRED from the environment yet",
    );
  });

  it("names the versions a rewrap could not open rather than counting them away", async () => {
    const { container } = renderAdminPage(
      <OpsPage />,
      routes(platform(), SUPERADMIN, {
        [`POST ${OPS_SECRETS_PATH}/kek/rewrap`]: {
          examined: 4,
          rewrapped: 3,
          unreadable: ["sarvam_api_key#1"],
          active_kek_id: 1633907231,
        },
      }),
    );
    await screen.findByText("Every stored key is wrapped under the current KEK");
    fireEvent.change(screen.getByPlaceholderText("REWRAP"), { target: { value: "REWRAP" } });
    fireEvent.click(screen.getByRole("button", { name: /Re-wrap every key/ }));

    await screen.findByText("3 of 4 versions re-wrapped");
    // A row nobody can open is the one that will be LOST, so it is named.
    expect(container.textContent).toContain("sarvam_api_key#1");
    expect(container.textContent).toContain("will be lost if the retired key is removed");
  });

  it("keeps the rewrap dead for a session without platform:secrets", async () => {
    renderAdminPage(<OpsPage />, routes(platform(), OPERATOR));
    await screen.findByText("Key management");
    const button = screen.getByRole("button", { name: /Re-wrap every key/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});
