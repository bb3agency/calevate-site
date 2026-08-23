import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import OpsConfigPage from "@/app/admin/ops/config/page";
import { appliesVerdict } from "@/app/admin/ops/ConfigPanel";
import { verdictTitle, verdictTone } from "@/app/admin/ops/SecretsPanel";
import { ApiProblem } from "@/lib/api/client";
import {
  OPS_CONFIG_PATH,
  OPS_CONFIG_QUERY_KEY,
  isLostUpdate,
  type ConfigField,
  type ConfigList,
  type ConfigWrite,
} from "@/lib/api/opsConfig";
import {
  OPS_SECRETS_PATH,
  type KekState,
  type PlatformSecret,
  type SecretTest,
  type SecretsList,
} from "@/lib/api/opsSecrets";
import { OPS_MODEL_PRICES_PATH, type ModelPrices } from "@/lib/api/opsModelPricing";

import { expectNoA11yViolations } from "./a11y";
import { expectTextCount, problem, stubApi, type Routes } from "./harness";

/**
 * The ops console, hardened for the operator who is tired, in a hurry, or NOT ALONE.
 *
 * `ops.test.tsx` pins what the screen says. This file pins what it must never let an
 * operator BELIEVE — every case below is one where the old screen produced a state an
 * operator would read as "that landed" when it had not, or "that is checked" when it was
 * not. Ranked by what each costs:
 *
 * 1. **A write refused for a lost update must not be retryable.** This console is the
 *    first thing in the estate where two operators can hold one key at once, and a
 *    "try again" that re-sends the same body is last-write-wins with a confirmation step
 *    in front of it. The screen must show the value NOW, who set it and when, and make a
 *    person choose — and whichever they choose, the next write is conditional again.
 * 2. **A save with no visible answer is a save an operator repeats.** The form used to
 *    close on success and render its confirmation from a branch that had already
 *    unmounted, so a successful write produced nothing at all. On a `stale` snapshot the
 *    list beside it still shows the old value, which reads as failure.
 * 3. **`applies` decides whether a change worked.** `on_restart` means the store moved
 *    and nothing else did; a live value with a caveat (`webhook_base_url`) means every
 *    agent already published keeps the old one until it is re-published. Both used to be
 *    a muted line in the row summary, and a word this build does not know rendered as
 *    silence — which reads as live.
 * 4. **A credential verdict belongs to one candidate.** A green box that outlives the
 *    value it was about is worse than no test at all: it is the control that prevents a
 *    bad key, reporting on a key nobody checked.
 * 5. **The plaintext must not outlive the form.** TanStack keeps a finished mutation's
 *    `variables` for five minutes by default, and `variables.value` here is a live vendor
 *    key.
 *
 * ## Why this file renders its own provider
 *
 * `renderAdminPage` builds its QueryClient internally and does not hand it back. Two
 * properties here need it: simulating the panel's 60-second poll landing a NEW value
 * under an open form (the two-operator case that never reaches the network), and reading
 * the mutation cache to prove a credential is not still sitting in it. Everything else
 * goes through the same real path — real provider, real `apiRequest`, `fetch` as the only
 * seam.
 */

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
    // The concurrency token. `"7"` rather than `"1"` so a test that hard-codes a guess
    // rather than reading the fixture is visible.
    etag: '"7"',
    updated_by: null,
    updated_at: null,
    note: null,
    ...over,
  };
}

function configList(fields: ConfigField[], over: Partial<ConfigList> = {}): ConfigList {
  return {
    // Required since D-101: the keys that can only change with an SSH session and a
    // restart. Their ABSENCE used to read identically to "this build has no such
    // setting", which is why the server states them rather than the console inferring.
    bootstrap: [],
    fields,
    config_version: 42,
    stale: false,
    never_loaded: false,
    config_changed_at: "2026-08-12T09:00:00Z",
    ...over,
  };
}

const SECRETS: SecretsList = {
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
  ],
};

const KEK: KekState = {
  active_kek_id: 1633907231,
  has_retired_kek: false,
  versions: 2,
  current: 2,
  pending: 0,
};

// The model-prices panel shares the `/admin/ops/config` screen with the config and
// credential panels, so every `renderOps` case needs its route stubbed or the panel's
// query errors and paints a `ProblemNotice` (retry button, alert) onto a screen these
// tests assert the exact controls of. One attested row is enough for the panel to render
// its populated state without a lever of its own that these cases exercise.
const MODEL_PRICES: ModelPrices = {
  prices: [
    {
      model: "gpt-4o-mini",
      provider: "azure_openai",
      credential_installed: true,
      price_attested: true,
      offerable: true,
      input_usd_per_mtok: "0.150000",
      output_usd_per_mtok: "0.600000",
      effective_from: "2026-08-01T00:00:00Z",
      attested_at: "2026-08-12T09:00:00Z",
      attested_by: "Ops",
      source_note: "Azure invoice 2026-08",
      reference_input_usd_per_mtok: "0.15",
      reference_output_usd_per_mtok: "0.60",
      reference_verified: true,
    },
  ],
  as_of: "2026-08-23T00:00:00Z",
};

/**
 * Merge route tables WITHOUT spreading.
 *
 * `{ ...base, ...extra }` evaluates getters, and several cases here define a route as a
 * getter precisely so one path can answer differently on a second read — the harness's
 * own header records this trap costing a suite its ability to test a recovery path.
 * Property descriptors are copied instead, so a getter stays a getter.
 */
function merged(...tables: Routes[]): Routes {
  const out: Routes = {};
  for (const table of tables) {
    for (const key of Object.keys(table)) {
      const descriptor = Object.getOwnPropertyDescriptor(table, key);
      if (descriptor) Object.defineProperty(out, key, descriptor);
    }
  }
  return out;
}

function opsRoutes(extra: Routes = {}, identity: unknown = SUPERADMIN): Routes {
  return merged(
    {
      // NO `/v1/ops/platform`: these panels live on `/admin/ops/config` since the
      // founder's correction to D-457, and that screen reads no platform-row state. The
      // harness throws on an unrouted request, so a case that fetched it would say so.
      [ADMIN_ME_PATH]: identity,
      [OPS_CONFIG_PATH]: configList([configField()]),
      [OPS_MODEL_PRICES_PATH]: MODEL_PRICES,
      [OPS_SECRETS_PATH]: SECRETS,
      [`${OPS_SECRETS_PATH}/kek`]: KEK,
    },
    extra,
  );
}

/** The ops CONFIG screen with its QueryClient exposed — see the file header for why. */
function renderOps(routes: Routes) {
  const calls = stubApi(routes);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <OpsConfigPage />
    </QueryClientProvider>,
  );
  return Object.assign(result, { calls, client });
}

/** Fill the config form for one key. Assumes the row's Change button is already clicked. */
function fillConfigForm(over: { value: string; reason: string; confirm: string }): void {
  const box = screen.getByLabelText(/New value/) as HTMLInputElement;
  fireEvent.change(box, { target: { value: over.value } });
  fireEvent.change(screen.getByPlaceholderText(/Q3 price change/), {
    target: { value: over.reason },
  });
  fireEvent.change(screen.getByPlaceholderText(over.confirm), {
    target: { value: over.confirm },
  });
}

function saveButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /^Save$/ }) as HTMLButtonElement;
}

function writeCount(calls: { method: string }[], method: string): number {
  return calls.filter((c) => c.method === method).length;
}

/**
 * The 412 `_refuse_stale` raises, copied from `apps/api/ops/config_service.py`.
 *
 * 412 and not 409, verbatim from the server: RFC 9110 §15.5.13 is "a condition given in
 * the request header fields evaluated to false", which is what a stale `If-Match` is.
 * The console reads the STATUS, so this fixture is the contract it is pinned to.
 */
function stalePrecondition() {
  return problem(412, {
    kind: "conflict",
    type: "urn:calevate:conflict/config_value_changed",
    title: "Somebody else changed this setting first",
    detail:
      "'self_serve_inr_per_min' moved between the value you read and this request, so " +
      "nothing was written — it is now \"7.25\", set by Priya.",
    remediation:
      "Re-read GET /v1/ops/config, decide whether your change still applies to the new " +
      "value, and send it again with the If-Match from that read. Your value was NOT " +
      "stored and the other operator's was NOT overwritten.",
    retryable: false,
  });
}

/* ════════════════════════════════════════════════════════════════════════════════════ */

describe("two operators, one key", () => {
  it("answers a refused write with the value that is there NOW, and never retries it", async () => {
    let reads = 0;
    const routes = opsRoutes({
      get [OPS_CONFIG_PATH]() {
        reads += 1;
        // The first read is what the operator decided against; every read after the
        // refusal is the world as it actually is.
        return reads === 1
          ? configList([configField()])
          : configList([
              configField({
                value: "7.25",
                source: "db",
                updated_by: "Priya",
                updated_at: "2026-08-15T04:30:00Z",
                note: "board approved the Q3 rate",
                etag: '"11"',
              }),
            ]);
      },
      [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: stalePrecondition(),
    });
    const { calls, container } = renderOps(routes);

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "8.00",
      reason: "raising the self-serve rate",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());

    await screen.findByText("The server refused this change — the value had already moved");

    // WHAT IT IS NOW, WHO, WHEN — all three, from the server's own re-read rather than
    // from anything the console remembered.
    // The row's value, the conflict box's, and the server's own sentence inside it.
    expectTextCount(container, "7.25", 3);
    // The row's provenance, the conflict box's, and the server's sentence.
    expectTextCount(container, "Priya", 3);
    expectTextCount(container, "board approved the Q3 rate", 2); // the row's note, and theirs
    // The literal, in IST at the edge — not `formatIST(...)`, which would compare the
    // function under test against itself and pass on any format at all.
    expect(container.textContent).toContain("15 Aug, 10:00 am");

    // EXACTLY ONE write was attempted. A silent retry is the defect this whole case
    // exists to prevent, so the count is the assertion — not the presence of a sentence.
    expect(writeCount(calls, "PUT")).toBe(1);
    // …and the operator cannot fire a second one by pressing the same button again.
    expect(saveButton().disabled).toBe(true);
  });

  it("offers three choices and NO retry, each of them a real button", async () => {
    const routes = opsRoutes({
      [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: stalePrecondition(),
    });
    renderOps(routes);

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "8.00",
      reason: "raising the self-serve rate",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());

    await screen.findByText("The server refused this change — the value had already moved");
    // Roles and names, so a `<div onClick>` that no keyboard can reach would fail here.
    expect(screen.getByRole("button", { name: "Start from their value" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Keep mine and replace theirs" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Discard my change" })).toBeTruthy();
    // The word this screen must not contain, in any control: a retry is the merge's
    // cheaper cousin and just as wrong.
    expect(screen.queryByRole("button", { name: /retry|try again/i })).toBeNull();
    // ONE account of one refusal. `ProblemNotice` is a `role="alert"`, and leaving it up
    // beside this box would give an operator two things to answer — the red one with no
    // choices, and this one with three.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/The API said:/)).toBeTruthy();
  });

  it("re-bases the override onto the value it just showed, and re-arms the confirmation", async () => {
    let reads = 0;
    let puts = 0;
    const routes = opsRoutes({
      get [OPS_CONFIG_PATH]() {
        reads += 1;
        return reads === 1
          ? configList([configField()])
          : configList([
              configField({ value: "7.25", source: "db", updated_by: "Priya", etag: '"11"' }),
            ]);
      },
      get [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]() {
        puts += 1;
        return puts === 1
          ? stalePrecondition()
          : ({
              key: "self_serve_inr_per_min",
              previous: "7.25",
              field: configField({ value: "8.00", source: "db", updated_by: "Ops" }),
              config_version: 44,
              recorded: true,
              etag: '"9"',
            } satisfies ConfigWrite);
      },
    });
    const { calls } = renderOps(routes);

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "8.00",
      reason: "raising the self-serve rate",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());
    await screen.findByText("The server refused this change — the value had already moved");

    fireEvent.click(screen.getByRole("button", { name: "Keep mine and replace theirs" }));

    // THE CONFIRMATION IS GONE. Overriding a peer is a fresh decision, so the typed word
    // that authorised the first attempt does not carry over to the second.
    const confirmBox = screen.getByPlaceholderText(
      "SELF_SERVE_INR_PER_MIN",
    ) as HTMLInputElement;
    expect(confirmBox.value).toBe("");
    expect(saveButton().disabled).toBe(true);
    expect(writeCount(calls, "PUT")).toBe(1);

    fireEvent.change(confirmBox, { target: { value: "SELF_SERVE_INR_PER_MIN" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(writeCount(calls, "PUT")).toBe(2));

    // THE PRECONDITION MOVED WITH THE OPERATOR'S EYES, on the wire. The first attempt was
    // conditional on the token they opened the form against; the second is conditional on
    // the token from the read that told them what it had become — not on the first one,
    // which is what a blind retry would send, and not on nothing at all, which the server
    // answers 428 to.
    const preconditions = calls
      .filter((c) => c.method === "PUT")
      .map((c) => c.headers["If-Match"]);
    expect(preconditions).toEqual(['"7"', '"11"']);
  });

  it("stops a save whose value moved under an OPEN form, before anything is sent", async () => {
    const { calls, client, container } = renderOps(opsRoutes());

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "8.00",
      reason: "raising the self-serve rate",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    expect(saveButton().disabled).toBe(false);

    // The panel's own 60-second poll, landing a peer's change. No network is needed to
    // make this real: the refetch putting a new list in the cache IS the event.
    act(() => {
      client.setQueryData(
        OPS_CONFIG_QUERY_KEY,
        configList([
          configField({ value: "7.25", source: "db", updated_by: "Priya", etag: '"11"' }),
        ]),
      );
    });

    await screen.findByText("This value changed while you had this form open");
    expect(saveButton().disabled).toBe(true);
    // Nothing was attempted, so nothing has to be undone.
    expect(writeCount(calls, "PUT")).toBe(0);
    expect(container.textContent).toContain("Nothing you typed has been sent");

    // AND CONTINUING IS A FRESH DECISION. This half is asserted HERE rather than only on
    // the server-refused path, and that is not duplication: on this path nothing failed,
    // so `rebase` is the only thing that can re-arm the confirmation. A sabotage removing
    // it left the refused-path test green, because the mutation's own error handler was
    // clearing the box as well — two mechanisms, one assertion, nothing pinned.
    fireEvent.click(screen.getByRole("button", { name: "Keep mine and replace theirs" }));
    const confirmBox = screen.getByPlaceholderText(
      "SELF_SERVE_INR_PER_MIN",
    ) as HTMLInputElement;
    expect(confirmBox.value).toBe("");
    expect(saveButton().disabled).toBe(true);
    expect(writeCount(calls, "PUT")).toBe(0);
  });

  it("does not dress an env-pinned refusal up as a concurrent edit", async () => {
    const routes = opsRoutes({
      // ALSO `kind: conflict`, and not a lost update: `_refuse_env_shadowed` raises it
      // for a key the environment pins, at 409 rather than 412. Offering "keep mine and
      // replace theirs" here would be a control with no possible outcome.
      [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: problem(409, {
        kind: "conflict",
        type: "urn:calevate:conflict/config_key_set_in_environment",
        title: "This setting is fixed by the environment",
        detail: "'self_serve_inr_per_min' is set as SELF_SERVE_INR_PER_MIN on this deployment.",
        remediation: "Change SELF_SERVE_INR_PER_MIN in the environment and restart.",
      }),
    });
    renderOps(routes);

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "8.00",
      reason: "raising the self-serve rate",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());

    // The server's own refusal, with its remediation — and NOT the three-way choice,
    // whose "keep mine and replace theirs" would be a control with no possible outcome.
    await screen.findByText(/Change SELF_SERVE_INR_PER_MIN in the environment/);
    expect(screen.queryByRole("button", { name: "Keep mine and replace theirs" })).toBeNull();
    expect(
      screen.queryByText("The server refused this change — the value had already moved"),
    ).toBeNull();
  });

  it("refuses to guess which refusals are a lost update", () => {
    const conflict = (status: number, code: string) =>
      new ApiProblem(status, { kind: "conflict", type: `urn:calevate:conflict/${code}` });

    // The one the server actually raises for a stale token.
    expect(isLostUpdate(conflict(412, "config_value_changed"))).toBe(true);
    // 428 is THIS CLIENT failing to send a precondition at all — a bug here, not a peer.
    // Rendering it as a concurrent edit would send an operator to compare two values
    // while the console is the thing that is broken.
    expect(isLostUpdate(conflict(428, "config_if_match_required"))).toBe(false);
    // The env-pinned refusal shares the `conflict` kind and is not this.
    expect(isLostUpdate(conflict(409, "config_key_set_in_environment"))).toBe(false);
    // A validation refusal changed nothing and has nothing to reconcile.
    expect(isLostUpdate(new ApiProblem(422, { kind: "validation" }))).toBe(false);
    // A dropped connection never reached the API, so nobody moved anything.
    expect(isLostUpdate(new Error("network down"))).toBe(false);
    expect(isLostUpdate(null)).toBe(false);
  });

  it("sends the token it was shown, verbatim, on both kinds of write", async () => {
    const { calls } = renderOps(
      opsRoutes({
        [OPS_CONFIG_PATH]: configList([
          configField({ value: "7.25", source: "db", updated_by: "Ops", etag: '"11"' }),
        ]),
        [`DELETE ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: {
          key: "self_serve_inr_per_min",
          previous: "7.25",
          field: configField({ etag: '"0"' }),
          config_version: 44,
          recorded: true,
          etag: '"0"',
        } satisfies ConfigWrite,
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fireEvent.change(screen.getByPlaceholderText("SELF_SERVE_INR_PER_MIN"), {
      target: { value: "SELF_SERVE_INR_PER_MIN" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Revert to default/ }));

    await waitFor(() => expect(writeCount(calls, "DELETE")).toBe(1));
    // REVERTING IS CONDITIONAL TOO, and this is the half most easily forgotten: DELETE
    // carries no body, so a precondition on it has to be a header or it does not exist —
    // and a revert lands a value nobody has looked at in months on top of whatever a peer
    // just wrote, which is the most expensive lost update this surface has.
    expect(calls.find((c) => c.method === "DELETE")?.headers["If-Match"]).toBe('"11"');
    // Opaque, quoted, verbatim: RFC 9110 §8.8.3, and `parse_etag` refuses `*`, `W/` and
    // lists — every one of which would let an unconditional write through.
    expect(calls.find((c) => c.method === "DELETE")?.headers["If-Match"]).not.toBe("*");
  });

  it("will not offer a form for a key whose API sent no precondition token", async () => {
    // An API older than the conditional write answers every PUT with 428. A console that
    // offered the form anyway would hand an operator a refusal they cannot act on, for a
    // change they were told they could make.
    renderOps(
      opsRoutes({
        [OPS_CONFIG_PATH]: configList([{ ...configField(), etag: undefined as unknown as string }]),
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    expect(screen.queryByRole("button", { name: /Change/ })).toBeNull();
    expect(screen.queryByLabelText(/New value/)).toBeNull();
    expect(
      screen.getByText(/did not send a concurrency token/, { exact: false }),
    ).toBeTruthy();
  });
});

describe("what saving will actually do, said before the save", () => {
  it("puts the restart consequence inside the form that has the Save button", async () => {
    renderOps(
      opsRoutes({
        [OPS_CONFIG_PATH]: configList([
          configField({
            key: "db_pool_size",
            env_var: "DB_POOL_SIZE",
            value: 16,
            default: 16,
            kind: "integer",
            applies: "on_restart",
            caveat: "the SQLAlchemy engine is built once per process",
          }),
        ]),
      }),
    );

    await screen.findByText("db_pool_size");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);

    // Reached from the BUTTON, not from the container: the property is that the sentence
    // is in the same form as the control, not that it appears somewhere on a screen the
    // operator has scrolled past.
    const form = saveButton().closest("form");
    expect(form).not.toBeNull();
    expect(form?.textContent).toContain("Needs a restart to take effect");
    expect(form?.textContent).toContain("the old value keeps running");
    expect(form?.textContent).toContain("the SQLAlchemy engine is built once per process");
  });

  it("does not let a live-but-not-retroactive change read as a finished one", async () => {
    renderOps(
      opsRoutes({
        [OPS_CONFIG_PATH]: configList([
          configField({
            key: "webhook_base_url",
            env_var: "WEBHOOK_BASE_URL",
            value: "https://hooks.calevate.tech",
            default: null,
            has_default: false,
            kind: "string",
            // The API's own word for it (`core/platform_config.NEEDS_REPUBLISH`), which
            // is neither `live` nor `on_restart`: a restart does not fix it and waiting
            // does not either.
            applies: "needs_republish",
            caveat:
              "every agent already published carries the OLD URL and must be re-published",
          }),
        ]),
      }),
    );

    await screen.findByText("webhook_base_url");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    const form = saveButton().closest("form");

    expect(form?.textContent).toContain("Live within seconds, but NOT retroactive");
    expect(form?.textContent).toContain("must be re-published");
    // The sentence a plain live field gets, which this one must NOT get: it is the
    // difference between a change that worked and one that half did.
    expect(form?.textContent).not.toContain("nothing to re-publish");
  });

  it("refuses to claim a change is live when it cannot read the label", async () => {
    renderOps(
      opsRoutes({
        [OPS_CONFIG_PATH]: configList([
          // A future API adding a third answer. `applies` is `str` on the wire, so this
          // arrives without a schema change and the old screen rendered it as silence.
          configField({ applies: "on_republish", caveat: null }),
        ]),
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    const form = saveButton().closest("form");

    expect(form?.textContent).toContain("This build cannot say when this takes effect");
    expect(form?.textContent).toContain("on_republish");
    expect(form?.textContent).not.toContain("Live within seconds");
  });

  it("has words for every answer the API has, and one more", () => {
    // `core/platform_config.APPLIES_VALUES`, verbatim. A value this build cannot name is
    // the sixth case, and it is the only one that may not read as an assurance.
    const id = (applies: string, caveat: string | null = null) =>
      appliesVerdict(configField({ applies, caveat })).id;

    expect(id("live")).toBe("live");
    expect(id("on_restart")).toBe("on_restart");
    expect(id("needs_republish")).toBe("needs_republish");
    expect(id("env_only")).toBe("env_only");
    expect(id("unclassified")).toBe("unclassified");
    expect(id("someday")).toBe("unknown");
    // A LIVE field carrying a caveat is a classification that has drifted; the sentence
    // somebody wrote about the key is rendered rather than dropped on the floor.
    expect(id("live", "re-publish the agents")).toBe("needs_republish");

    // EVERY answer but the plain one warns. `live` is the only quiet branch, and it is
    // the only one where there is nothing left for an operator to do.
    const quiet = ["live", "on_restart", "needs_republish", "env_only", "unclassified", "x"]
      .map((a) => appliesVerdict(configField({ applies: a })).tone)
      .filter((tone) => tone !== "warn");
    expect(quiet).toEqual(["neutral"]);
  });

  it("gives a key nobody classified its own reason, not the environment's", async () => {
    // `describe()` sets `editable: false` for three different reasons. Printing the
    // environment's for all of them sent an operator to change a variable that nobody has
    // set and that would not have helped.
    const { container } = renderOps(
      opsRoutes({
        [OPS_CONFIG_PATH]: configList([
          configField({ source: "default", editable: false, applies: "unclassified" }),
        ]),
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    expect(container.textContent).toContain(
      "This build has not said when a change would take effect",
    );
    expect(container.textContent).not.toContain("The environment always wins over the console");
    expect(screen.queryByRole("button", { name: /Change/ })).toBeNull();
  });

  it("says a key the store can never deliver is not merely awaiting a restart", async () => {
    const { container } = renderOps(
      opsRoutes({
        [OPS_CONFIG_PATH]: configList([
          configField({
            key: "db_pool_size",
            env_var: "DB_POOL_SIZE",
            value: 16,
            default: 16,
            kind: "integer",
            source: "default",
            editable: false,
            applies: "env_only",
            caveat: "the pool is built from the environment before the store is reachable",
          }),
        ]),
      }),
    );

    await screen.findByText("db_pool_size");
    // ONCE. The row's own applies line and the read-only reason are the same sentence,
    // and a screen that prints a warning twice teaches an operator to read neither.
    expectTextCount(container, "The store can never deliver this value", 1);
    expect(container.textContent).toContain("DB_POOL_SIZE");
    // The distinction the API's own comment insists on: `on_restart` PROMISES a restart
    // is enough, and this one does not. Rendering them the same would send an operator to
    // bounce a process and wonder why nothing changed.
    expect(container.textContent).not.toContain("Needs a restart to take effect");
  });
});

describe("the receipt is the server's answer", () => {
  it("shows what the SERVER stored, not what was typed", async () => {
    const { container } = renderOps(
      opsRoutes({
        [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: {
          key: "self_serve_inr_per_min",
          previous: "6.00",
          // The model coerced the trailing zero away. This is exactly the case where the
          // typed value and the stored value differ, and the screen must show the second.
          field: configField({ value: "7.25", source: "db", updated_by: "Ops" }),
          config_version: 43,
          recorded: true,
          etag: '"8"',
        } satisfies ConfigWrite,
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "7.250",
      reason: "Q3 self-serve price change",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());

    const receipt = await screen.findByRole("status");
    expect(receipt.textContent).toContain("7.25");
    expect(receipt.textContent).toContain("was 6.00");
    expect(receipt.textContent).toContain("configuration version 43");
    // The typed string appears NOWHERE — not in the receipt and not left in a form.
    expectTextCount(container, "7.250", 0);
  });

  it("says when the process serving this screen has not picked the change up", async () => {
    // The list keeps answering 6.00 — a `stale` snapshot, or a process that cannot reach
    // the store. Without this the operator sees the old value under a green tick and
    // writes it again.
    const { container } = renderOps(
      opsRoutes({
        [OPS_CONFIG_PATH]: configList([configField()], { stale: true }),
        [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: {
          key: "self_serve_inr_per_min",
          previous: "6.00",
          field: configField({ value: "7.25", source: "db", updated_by: "Ops" }),
          config_version: 43,
          recorded: true,
          etag: '"8"',
        } satisfies ConfigWrite,
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "7.25",
      reason: "Q3 self-serve price change",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());

    await screen.findByText("The process serving this screen has not picked it up yet");
    expect(container.textContent).toContain("It still reports 6.00");
  });

  it("never renders a receipt for a write that failed", async () => {
    const { calls } = renderOps(
      opsRoutes({
        [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: problem(422, {
          kind: "validation",
          type: "urn:calevate:validation/config_value_invalid",
          title: "That value would not be accepted at boot",
          detail: "'self_serve_inr_per_min' cannot be set to that value.",
        }),
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "not a number",
      reason: "fat fingers",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());

    // Waited on the REQUEST rather than on a sentence, so the receipt assertion below is
    // the first one to speak. A test that waits on the error text asserts the receipt only
    // if the error text is still there, which a sabotage that fakes success removes.
    await waitFor(() => expect(writeCount(calls, "PUT")).toBe(1));
    expect(screen.queryByRole("status")).toBeNull();
    // The form stayed open with the value in it, so the operator can correct it — and the
    // API's own words are on screen.
    expect(saveButton()).toBeTruthy();
    expect(
      screen.getByText("'self_serve_inr_per_min' cannot be set to that value."),
    ).toBeTruthy();
  });
});

describe("a write the server did not perform", () => {
  it("says nothing was written when the value was already the value", async () => {
    // `recorded: false` — `set_value` found the submitted value identical to the stored
    // one, touched no row, bumped no sentinel and wrote no audit entry. A double-clicked
    // Save, or two operators reaching the same conclusion, produces exactly this.
    renderOps(
      opsRoutes({
        [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: {
          key: "self_serve_inr_per_min",
          previous: "6.00",
          field: configField(),
          config_version: 42,
          recorded: false,
          etag: '"7"',
        } satisfies ConfigWrite,
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "6.00",
      reason: "confirming the Q3 rate",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());

    const receipt = await screen.findByRole("status");
    expect(receipt.textContent).toContain("Already the value");
    expect(receipt.textContent).toContain("no audit entry was made");
    // The word that would be a lie: nothing was stored by this request.
    expect(receipt.textContent).not.toContain("Stored.");
  });
});

describe("a key the environment pins", () => {
  it("offers no form, states the reason, and survives the value moving underneath", async () => {
    const pinned = (value: string) =>
      configList([
        configField({
          key: "object_store_bucket",
          env_var: "OBJECT_STORE_BUCKET",
          value,
          source: "env",
          editable: false,
          kind: "string",
          default: null,
          has_default: false,
        }),
      ]);

    const { client, container } = renderOps(opsRoutes({ [OPS_CONFIG_PATH]: pinned("calevate-prod") }));

    await screen.findByText("object_store_bucket");
    // No control at all — not a disabled one, because there is nothing this session
    // could ever be granted that would make the write land.
    expect(screen.queryByRole("button", { name: /Change/ })).toBeNull();
    expect(screen.queryByLabelText(/New value/)).toBeNull();
    expect(container.textContent).toContain("OBJECT_STORE_BUCKET");
    expect(container.textContent).toContain("The environment always wins over the console");

    // The deployment's environment changed and the process reloaded. Still no form.
    act(() => client.setQueryData(OPS_CONFIG_QUERY_KEY, pinned("calevate-prod-2")));
    await screen.findByText("calevate-prod-2");
    expect(screen.queryByRole("button", { name: /Change/ })).toBeNull();
    expect(screen.queryByLabelText(/New value/)).toBeNull();
  });

  it("takes the form away when a key becomes env-pinned while the form is open", async () => {
    const { client, container } = renderOps(opsRoutes());

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    expect(screen.getByLabelText(/New value/)).toBeTruthy();

    // Someone set the variable and restarted the process serving this screen. Every write
    // this form could send is now refused by the API, so the form is not one.
    act(() =>
      client.setQueryData(
        OPS_CONFIG_QUERY_KEY,
        configList([configField({ source: "env", editable: false })]),
      ),
    );

    await waitFor(() => expect(screen.queryByLabelText(/New value/)).toBeNull());
    expect(container.textContent).toContain("The environment always wins over the console");
  });
});

/* ════════════════════════════════════════════════════════════════════════════════════ */

function secretInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>('input[type="password"]');
  if (!input) throw new Error("the credential form is not open");
  return input;
}

/** The tone classes of the `NoticeBox` a title sits in. */
function noticeToneOf(title: HTMLElement): string {
  const box = title.closest("div.rounded-card");
  if (!box) throw new Error("that title is not inside a NoticeBox");
  return box.className;
}

function testVerdict(over: Partial<SecretTest> = {}): SecretTest {
  return {
    key: "bolna_api_key",
    outcome: "accepted",
    status: 200,
    detail: "The vendor accepted this credential for one authenticated read.",
    verified: false,
    candidate_last_four: "cdef",
    ...over,
  };
}

const CANDIDATE = "bn-live-secret-abcdef";

/**
 * The verdict headline for the state every probe in this build is in.
 *
 * The exact string, not a regex: `/The vendor accepted this credential/` also matches the
 * DETAIL sentence underneath it ("…for one authenticated read"), so a test written that
 * way would pass while the title said anything at all — the substring-that-matches-
 * elsewhere failure this suite has already been bitten by five times.
 */
const ACCEPTED_UNCONFIRMED = "The vendor accepted this credential — indicative, not confirmed";

async function openSecretFormAndTest(verdict: SecretTest, candidate = CANDIDATE) {
  const rendered = renderOps(
    opsRoutes({ [`POST ${OPS_SECRETS_PATH}/bolna_api_key/test`]: verdict }),
  );
  await screen.findByText("bolna_api_key");
  fireEvent.click(screen.getAllByRole("button", { name: /Rotate|Install/ })[0]);
  fireEvent.change(secretInput(), { target: { value: candidate } });
  fireEvent.click(screen.getByRole("button", { name: /Test with the vendor/ }));
  return rendered;
}

describe("a credential verdict belongs to one candidate", () => {
  it("is gone the moment the value in the box changes", async () => {
    const { container } = await openSecretFormAndTest(testVerdict());
    await screen.findByText(ACCEPTED_UNCONFIRMED);

    // One keystroke later the verdict is about a string nobody checked.
    fireEvent.change(secretInput(), { target: { value: "bn-live-a-different-key-9999" } });

    expect(screen.queryByText(ACCEPTED_UNCONFIRMED)).toBeNull();
    expectTextCount(container, "…cdef", 0);
    // …and the operator is told the candidate in the box is unchecked.
    expect(container.textContent).toContain("has not been checked with the vendor");
  });

  it("does not survive closing and reopening the form", async () => {
    const { container } = await openSecretFormAndTest(testVerdict());
    await screen.findByText(ACCEPTED_UNCONFIRMED);

    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Rotate|Install/ })[0]);

    // An empty box under a green box is the worst version of this: it reads as "the
    // credential on file has been checked", which is not something this screen can know.
    expect(screen.queryByText(ACCEPTED_UNCONFIRMED)).toBeNull();
    expect(secretInput().value).toBe("");
    expectTextCount(container, "…cdef", 0);
  });

  it("does not leave the plaintext in the mutation cache after the form closes", async () => {
    const { client } = await openSecretFormAndTest(testVerdict());
    await screen.findByText(ACCEPTED_UNCONFIRMED);

    const held = () =>
      client
        .getMutationCache()
        .getAll()
        .filter((m) => JSON.stringify(m.state.variables ?? "").includes(CANDIDATE));
    // While the form is open the candidate is legitimately in flight.
    expect(held()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/ }));

    // TanStack keeps a finished mutation's `variables` for five minutes by default, and
    // `variables.value` here is a live vendor key. `gcTime: 0` is what makes this pass.
    await waitFor(() => expect(held()).toHaveLength(0));
  });
});

describe("the four outcomes of a test, kept apart", () => {
  it("does not spend a tick on a check nobody has confirmed", async () => {
    const { container } = await openSecretFormAndTest(testVerdict({ verified: false }));

    const title = await screen.findByText(ACCEPTED_UNCONFIRMED);
    expect(container.textContent).toContain("treat it as indicative rather than authoritative");
    // The green box is what a hurried operator reads instead of the words, so the tone is
    // asserted on THIS box — the key-management panel has a legitimate green one on the
    // same screen, and a container-wide class count would be answering about that.
    expect(noticeToneOf(title)).not.toContain("emerald");
  });

  it("keeps the tick available for a verdict that IS confirmed", () => {
    expect(verdictTone(testVerdict({ verified: true }))).toBe("ok");
    expect(verdictTitle(testVerdict({ verified: true }))).toBe(
      "The vendor accepted this credential",
    );
    expect(verdictTone(testVerdict({ verified: false }))).toBe("neutral");
  });

  it("never reports 'we could not check' as the vendor saying no", async () => {
    const { container } = await openSecretFormAndTest(
      testVerdict({
        outcome: "unreachable",
        status: null,
        detail: "The vendor could not be reached, so this credential has NOT been checked.",
      }),
    );

    const title = await screen.findByText(
      "We could not reach the vendor — indicative, not confirmed",
    );
    expect(container.textContent).not.toContain("REFUSED");
    // A refusal is red. "We could not ask" is not, because it must not send an operator
    // to find a different key.
    expect(noticeToneOf(title)).not.toContain("rose");
  });

  it("says a missing probe is a missing probe, without a caveat arguing with itself", async () => {
    const { container } = await openSecretFormAndTest(
      testVerdict({
        outcome: "no_probe",
        status: null,
        verified: false,
        detail: "This build has no way to test this credential with the vendor.",
      }),
    );

    // `no_probe` already says the check did not happen; appending "not confirmed" to it
    // would be the caveat repeating itself.
    await screen.findByText("This build cannot test this credential");
    expect(container.textContent).not.toContain(
      "This build cannot test this credential — indicative",
    );
    expect(container.textContent).not.toContain("treat it as indicative rather than");
  });

  it("says a build with no probe has no probe, in text a keyboard can reach", async () => {
    renderOps(
      opsRoutes({
        [OPS_SECRETS_PATH]: {
          secrets: [{ ...SECRETS.secrets[0], testable: false }],
        } satisfies SecretsList,
      }),
    );

    await screen.findByText("bolna_api_key");
    fireEvent.click(screen.getAllByRole("button", { name: /Rotate|Install/ })[0]);

    // Was a `title` attribute on the button — invisible to a screen reader and to anyone
    // who never hovers.
    const form = screen.getByRole("button", { name: /Test with the vendor/ }).closest("form");
    expect(form?.textContent).toContain("This build has no probe for this vendor");
    // And it does NOT block the install: "we cannot check" is not "do not store".
    expect(
      (screen.getByRole("button", { name: /Test with the vendor/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true); // no candidate typed yet — the reason is the empty box, not the probe
  });
});

describe("installing a credential", () => {
  it("reports the last four the SERVER holds, and its version", async () => {
    renderOps(
      opsRoutes({
        [`PUT ${OPS_SECRETS_PATH}/bolna_api_key`]: {
          ...SECRETS.secrets[0],
          version: 3,
          versions: 3,
          last_four: "0001",
        } satisfies PlatformSecret,
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

    const receipt = await screen.findByRole("status");
    expect(receipt.textContent).toContain("…0001");
    expect(receipt.textContent).toContain("version 3");
  });

  it("says an install is INERT when the environment shadows the key", async () => {
    renderOps(
      opsRoutes({
        [OPS_SECRETS_PATH]: {
          secrets: [{ ...SECRETS.secrets[0], shadowed_by_env: true }],
        } satisfies SecretsList,
        [`PUT ${OPS_SECRETS_PATH}/bolna_api_key`]: {
          ...SECRETS.secrets[0],
          shadowed_by_env: true,
          version: 3,
          versions: 3,
          last_four: "0001",
        } satisfies PlatformSecret,
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

    // The write SUCCEEDED and the credential is still not in force. A receipt that only
    // said "stored" would be true and useless.
    const receipt = await screen.findByRole("status");
    expect(receipt.textContent).toContain("It is not in force");
    expect(receipt.textContent).toContain("BOLNA_API_KEY");
  });
});

describe("the rewrap", () => {
  it("cannot be fired twice by two quick submits", async () => {
    const { calls } = renderOps(
      opsRoutes({
        [`POST ${OPS_SECRETS_PATH}/kek/rewrap`]: {
          examined: 4,
          rewrapped: 4,
          unreadable: [],
          active_kek_id: 1633907231,
        },
      }),
    );

    // Waiting on the card TITLE would be waiting on static text: the identity read gates
    // the control, and the KEK read gates the panel. Both are behind this sentence.
    await screen.findByText("Every stored key is wrapped under the current KEK");
    const box = screen.getByPlaceholderText("REWRAP");
    fireEvent.change(box, { target: { value: "REWRAP" } });

    const form = box.closest("form");
    if (!form) throw new Error("the rewrap form is not on screen");

    // BOTH SUBMITS IN ONE TASK, dispatched raw rather than through `fireEvent`.
    // This is the difference between an experiment and a demonstration: `fireEvent` wraps
    // every call in `act`, which flushes React in between — so two `fireEvent.submit`
    // calls see a component that has already re-rendered with the confirmation cleared
    // and `isPending` true, and the test passes with NO guard at all. It did, and the
    // sabotage run proved it. Two events inside one `act` are what a double-click or a
    // held Return actually produces: the second handler runs against the render that
    // armed the first, where `confirm` is still "REWRAP" and `isPending` is still false,
    // and only a ref has changed in time.
    const submit = () =>
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    act(() => {
      submit();
      submit();
    });

    await waitFor(() => expect(screen.getByText(/versions re-wrapped/)).toBeTruthy());
    expect(calls.filter((c) => c.path === `${OPS_SECRETS_PATH}/kek/rewrap`)).toHaveLength(1);
  });

  it("can be run again after it finishes, so the latch is not a one-way door", async () => {
    // The pair to the test above, and it is not padding: a guard that latches and never
    // releases turns "cannot double-fire" into "cannot fire twice ever", which on the
    // recovery action for a half-finished rotation is the worse failure of the two.
    const { calls } = renderOps(
      opsRoutes({
        [`POST ${OPS_SECRETS_PATH}/kek/rewrap`]: {
          examined: 4,
          rewrapped: 4,
          unreadable: [],
          active_kek_id: 1633907231,
        },
      }),
    );

    await screen.findByText("Every stored key is wrapped under the current KEK");
    const fire = async () => {
      fireEvent.change(screen.getByPlaceholderText("REWRAP"), { target: { value: "REWRAP" } });
      fireEvent.click(screen.getByRole("button", { name: /Re-wrap every key/ }));
    };
    await fire();
    await waitFor(() =>
      expect(calls.filter((c) => c.path === `${OPS_SECRETS_PATH}/kek/rewrap`)).toHaveLength(1),
    );
    await fire();
    await waitFor(() =>
      expect(calls.filter((c) => c.path === `${OPS_SECRETS_PATH}/kek/rewrap`)).toHaveLength(2),
    );
  });

  it("refuses to say a rotation is complete from a read that failed", async () => {
    const { container } = renderOps(
      opsRoutes({
        [`${OPS_SECRETS_PATH}/kek`]: problem(503, {
          title: "Service unavailable",
          detail: "The database is not reachable.",
        }),
      }),
    );

    await screen.findByText("We could not read the key-management state");
    // The sentence that would license destroying data.
    expect(screen.queryByText("Every stored key is wrapped under the current KEK")).toBeNull();
    expect(container.textContent).toContain("do not remove");
    // The rewrap stays offered: it is the recovery action and it reports its own counts.
    expect(screen.getByRole("button", { name: /Re-wrap every key/ })).toBeTruthy();
  });

  it("names the active key as a fingerprint rather than a generation number", async () => {
    const { container } = renderOps(opsRoutes());
    await screen.findByText("Every stored key is wrapped under the current KEK");
    // D-96: the label is a hash of the key material. "#1633907231" invites an operator to
    // read a rotation count and conclude something has gone very wrong.
    expect(container.textContent).toContain("Active key fingerprint");
    expectTextCount(container, "#1633907231", 0);
  });
});

/**
 * A confirmation an operator cannot reach by keyboard is not a confirmation.
 *
 * The sweep in `a11y.test.tsx` scans this screen at FIRST PAINT, which is the state where
 * every form on it is closed — so none of the markup this slice adds is inside it. The
 * three states below only exist after an interaction, and two of them are the ones an
 * operator meets while something has gone wrong.
 */
describe("the states that only exist after a click are still operable", () => {
  it("has no violations with a config form open and its value in conflict", async () => {
    const { container } = renderOps(
      opsRoutes({
        [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: stalePrecondition(),
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "8.00",
      reason: "raising the self-serve rate",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());
    await screen.findByText("The server refused this change — the value had already moved");

    await expectNoA11yViolations(container, "admin/ops — config conflict");
  });

  it("has no violations with a credential form open and a verdict on screen", async () => {
    const { container } = await openSecretFormAndTest(testVerdict());
    await screen.findByText(ACCEPTED_UNCONFIRMED);

    await expectNoA11yViolations(container, "admin/ops — credential verdict");
  });

  it("has no violations showing a write receipt", async () => {
    const { container } = renderOps(
      opsRoutes({
        [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: {
          key: "self_serve_inr_per_min",
          previous: "6.00",
          field: configField({ value: "7.25", source: "db", updated_by: "Ops" }),
          config_version: 43,
          recorded: true,
          etag: '"8"',
        } satisfies ConfigWrite,
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fillConfigForm({
      value: "7.25",
      reason: "Q3 self-serve price change",
      confirm: "SELF_SERVE_INR_PER_MIN",
    });
    fireEvent.click(saveButton());
    await screen.findByRole("status");

    await expectNoA11yViolations(container, "admin/ops — write receipt");
  });
});
