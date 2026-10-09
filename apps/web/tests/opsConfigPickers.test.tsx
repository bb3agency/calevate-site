import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfigForm } from "@/app/admin/ops/config/ConfigForm";
import {
  OPS_CONFIG_PATH,
  THINNEST_WORKSPACE_SOURCE_PATH,
  type ConfigField,
} from "@/lib/api/opsConfig";

import { SELF_SERVE_PRICE_META, control, placed } from "./fixtures/opsConfig";
import { problem, renderAdminPage, type ApiCall } from "./harness";

/**
 * The change form for settings that are CHOSEN, not typed (D-704): a value naming something
 * that exists is picked from a live read of it, a read that fails says so with a Retry and
 * never becomes a text box, and what is typed is checked against the served control before
 * the server is asked.
 */

const TRIAL_PATH = "/v1/ops/trial-number";

function field(over: Partial<ConfigField> = {}): ConfigField {
  return {
    key: "self_serve_inr_per_min",
    env_var: "SELF_SERVE_INR_PER_MIN",
    value: "4.00",
    source: "default",
    default: "4.00",
    has_default: true,
    kind: "decimal",
    options: [],
    editable: true,
    applies: "live",
    caveat: null,
    etag: '"3"',
    updated_by: null,
    updated_at: null,
    note: null,
    ...SELF_SERVE_PRICE_META,
    ...over,
  };
}

const trialField = field({
  key: "trial_caller_number",
  env_var: "TRIAL_CALLER_NUMBER",
  kind: "string",
  nullable: true,
  value: null,
  default: null,
  control: control("entity_picker", { source: "trial_numbers", max_length: 13 }),
  ...placed("calling-limits", "trial", "Shared trial number"),
});

const workspaceField = field({
  key: "thinnest_developer_workspace_id",
  env_var: "THINNEST_DEVELOPER_WORKSPACE_ID",
  kind: "string",
  nullable: true,
  value: null,
  default: null,
  control: control("entity_picker", {
    source: "thinnest_workspace",
    risk: "high",
    risk_reason: "Decides which workspace is ours.",
  }),
  ...placed("voice-engine", "thinnest", "ThinnestAI developer workspace"),
});

const secondsField = field({
  key: "trial_call_max_seconds",
  env_var: "TRIAL_CALL_MAX_SECONDS",
  kind: "integer",
  value: 180,
  default: 180,
  control: control("duration", { unit: "seconds", minimum: "60", maximum: "1200", step: "1" }),
  ...placed("calling-limits", "trial", "Longest trial test call"),
});

function renderForm(subject: ConfigField, routes: Record<string, unknown>) {
  const onWritten = vi.fn();
  const rendered = renderAdminPage(
    <ConfigForm field={subject} basis={subject.etag} onDone={() => {}} onWritten={onWritten} />,
    routes,
  );
  return { ...rendered, onWritten };
}

function giveReason(): void {
  fireEvent.click(screen.getByRole("button", { name: "Planned change" }));
}

function putBody(calls: ApiCall[]): unknown {
  return JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}");
}

describe("the shared trial number is picked from what ThinnestAI holds", () => {
  const candidates = {
    current: null,
    current_held: null,
    engine_uses_it: true,
    candidates: [
      {
        e164: "+918041234567",
        rented: true,
        answered: true,
        label: "Front desk",
        answering_agent: "Reception",
        calling_agent: null,
      },
      {
        e164: "+918041230000",
        rented: false,
        answered: false,
        label: null,
        answering_agent: null,
        calling_agent: null,
      },
    ],
  };

  it("lists each number with its label and agent, and saves the one chosen", async () => {
    const { calls, onWritten } = renderForm(trialField, {
      [TRIAL_PATH]: candidates,
      [`PUT ${OPS_CONFIG_PATH}/trial_caller_number`]: {
        key: "trial_caller_number",
        previous: null,
        field: { ...trialField, value: "+918041234567", source: "db" },
        config_version: 2,
        recorded: true,
        etag: '"4"',
      },
    });

    const choice = await screen.findByRole("radio", { name: /\+91 80412 34567/ });
    expect(screen.getByText("Front desk · Rented from ThinnestAI · answered by Reception")).toBeTruthy();
    expect(screen.getByText("Brought from a carrier · nobody answers it")).toBeTruthy();
    // Never a text box: a typed number is the value that must not be trusted.
    expect(screen.queryByRole("textbox", { name: /New value/ })).toBeNull();

    fireEvent.click(choice);
    giveReason();
    // Standard risk: the preview is the confirmation, and one press saves.
    expect(screen.queryByText(/^Type /)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save change" }));

    await waitFor(() => expect(onWritten).toHaveBeenCalled());
    expect(putBody(calls)).toEqual({ value: "+918041234567", reason: "Planned change" });
    // The server's step-up confirmation is sent whatever the console asked of the person.
    expect(calls.find((c) => c.method === "PUT")?.headers["X-Confirm-Action"]).toBe(
      "set_config:trial_caller_number",
    );
  });

  it("says when ThinnestAI cannot be read, with a retry and no box to type into", async () => {
    renderForm(trialField, {
      [TRIAL_PATH]: problem(502, {
        kind: "dependency",
        title: "Voice engine unavailable",
        detail: "ThinnestAI did not answer.",
        retryable: true,
      }),
    });

    await screen.findByText("ThinnestAI did not answer.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: /New value/ })).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
  });
});

describe("the developer workspace is read, not typed", () => {
  it("offers the workspace our key belongs to and asks for it to be typed back", async () => {
    const { calls, onWritten } = renderForm(workspaceField, {
      [THINNEST_WORKSPACE_SOURCE_PATH]: {
        workspace_id: "org_calevate",
        name: "Calevate",
        matches_setting: false,
      },
      [`PUT ${OPS_CONFIG_PATH}/thinnest_developer_workspace_id`]: {
        key: "thinnest_developer_workspace_id",
        previous: null,
        field: { ...workspaceField, value: "org_calevate", source: "db" },
        config_version: 2,
        recorded: true,
        etag: '"4"',
      },
    });

    fireEvent.click(await screen.findByRole("radio", { name: /Use this workspace: Calevate/ }));
    giveReason();
    const save = screen.getByRole("button", { name: "Save change" }) as HTMLButtonElement;
    // High risk: held until the new value is typed back.
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByPlaceholderText("org_calevate"), {
      target: { value: "org_calevate" },
    });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);

    await waitFor(() => expect(onWritten).toHaveBeenCalled());
    expect(putBody(calls)).toEqual({ value: "org_calevate", reason: "Planned change" });
  });
});

describe("the drawer checks what is typed", () => {
  it("states the served bounds before anything is sent", async () => {
    const { calls } = renderForm(secondsField, {});

    const box = screen.getByRole("textbox", { name: /New value/ });
    expect(screen.getByText(/Between 60 and 1,200 seconds\./)).toBeTruthy();
    fireEvent.change(box, { target: { value: "30" } });
    expect(screen.getByRole("alert").textContent).toBe("Must be at least 60 seconds.");
    giveReason();
    expect((screen.getByRole("button", { name: "Save change" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(box, { target: { value: "240" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/That is 4 minutes./)).toBeTruthy();
    // The before → after preview, in the words the row uses.
    const preview = screen.getByText("What changes").parentElement?.textContent ?? "";
    expect(preview).toContain("3 minutes");
    expect(preview).toContain("4 minutes");
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("puts the server's refusal of the value beside the input, in words", async () => {
    renderForm(secondsField, {
      [`PUT ${OPS_CONFIG_PATH}/trial_call_max_seconds`]: problem(422, {
        kind: "validation",
        title: "That value would not be accepted at boot",
        detail: "'trial_call_max_seconds' cannot be set to that value.",
        fields: [
          {
            field: "trial_call_max_seconds",
            rule: "less_than_equal",
            message: "Input should be less than or equal to 900",
          },
        ],
      }),
    });

    fireEvent.change(screen.getByRole("textbox", { name: /New value/ }), {
      target: { value: "1000" },
    });
    giveReason();
    fireEvent.click(screen.getByRole("button", { name: "Save change" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Should be less than or equal to 900",
    );
  });

  it("edits a switch as On or Off, never as true or false", async () => {
    const healer = field({
      key: "healer_enabled",
      env_var: "HEALER_ENABLED",
      kind: "boolean",
      value: true,
      default: true,
      control: control("switch", { risk: "high", risk_reason: "Off stops every repair." }),
      ...placed("healer", "switches", "Auto-healer on"),
    });
    renderForm(healer, {});

    fireEvent.click(screen.getByRole("radio", { name: "Off" }));
    expect(screen.getByText("What changes")).toBeTruthy();
    expect(screen.getByLabelText(/Type .*Off.* to confirm/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("false");
  });
});
