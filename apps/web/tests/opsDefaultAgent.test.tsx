import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfigForm } from "@/app/admin/ops/config/ConfigForm";
import { OPS_CONFIG_PATH, type ConfigField } from "@/lib/api/opsConfig";
import type { HostedVoice } from "@/lib/api/opsHostedVoices";

import { SELF_SERVE_PRICE_META, control, placed } from "./fixtures/opsConfig";
import { problem, renderAdminPage, type ApiCall } from "./harness";

/**
 * The agent a new account starts with, set in the console (founder, 16 Nov 2026): its voice
 * is picked from the voices enabled for clients, each with its preview, and a refusal from
 * the server is shown in its own words.
 */

const VOICES_PATH = "/v1/ops/voices/hosted?scope=added";

function voice(over: Partial<HostedVoice> = {}): HostedVoice {
  return {
    voice_id: "byok:meera",
    vendor_id: "meera",
    label: "Meera",
    vendor_label: "Meera",
    display_label: null,
    source: "byok",
    rung: "studio",
    band: null,
    sold: true,
    not_sold_reason: null,
    is_custom: false,
    accent: "te",
    accent_label: "Telugu",
    gender: "Female",
    languages: ["te-IN", "hi-IN", "en-IN"],
    description: null,
    language_note: "",
    state: "enabled",
    added: true,
    offered: true,
    synced_at: "2026-10-08T04:30:00Z",
    curated_at: "2026-10-08T05:00:00Z",
    withdrawn_at: null,
    preview_available: true,
    preview_source: "vendor",
    deletable_clone: false,
    used_by: { live: 0, ready: 0, not_published: 0, total: 0 },
    person_clone: false,
    clone_consent: null,
    clone_blocker: null,
    ...over,
  };
}

const MEERA = voice();
const RAVI = voice({
  voice_id: "engine:ravi",
  vendor_id: "ravi",
  label: "Ravi",
  vendor_label: "Ravi",
  source: "engine",
  rung: "clear",
  gender: "male",
  preview_available: false,
});
const HIDDEN = voice({ voice_id: "engine:off", label: "Off voice", state: "disabled", offered: false });

function voices(list: HostedVoice[]) {
  return {
    available: true,
    scope: "added",
    voices: list,
    cached: list.length,
    offered: list.filter((v) => v.offered).length,
    studio_ready: true,
    clear_band: "studio",
    note: "",
    bands: {},
    plan_note: null,
  };
}

const voiceField: ConfigField = {
  key: "default_agent_voice_id",
  env_var: "DEFAULT_AGENT_VOICE_ID",
  value: null,
  source: "default",
  default: null,
  has_default: true,
  kind: "string",
  options: [],
  editable: true,
  applies: "live",
  caveat: null,
  etag: '"0"',
  updated_by: null,
  updated_at: null,
  note: null,
  ...SELF_SERVE_PRICE_META,
  nullable: true,
  control: control("entity_picker", { source: "client_voices", max_length: 255 }),
  ...placed("speech", "default-agent", "Voice of the first agent"),
};

function renderForm(routes: Record<string, unknown>) {
  const onWritten = vi.fn();
  const rendered = renderAdminPage(
    <ConfigForm field={voiceField} basis={voiceField.etag} onDone={() => {}} onWritten={onWritten} />,
    routes,
  );
  return { ...rendered, onWritten };
}

function putBody(calls: ApiCall[]): unknown {
  return JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}");
}

describe("the first agent's voice is picked from the voices enabled for clients", () => {
  it("lists only offered voices, with a preview where one exists, and saves the one chosen", async () => {
    const { calls, onWritten } = renderForm({
      [VOICES_PATH]: voices([MEERA, RAVI, HIDDEN]),
      [`PUT ${OPS_CONFIG_PATH}/default_agent_voice_id`]: {
        key: "default_agent_voice_id",
        previous: null,
        field: { ...voiceField, value: "byok:meera", source: "db" },
        config_version: 2,
        recorded: true,
        etag: '"1"',
      },
    });

    const meera = await screen.findByRole("radio", { name: /Meera/ });
    expect(screen.getByText("Studio · woman · Telugu")).toBeTruthy();
    expect(screen.getByText("Clear · man · Telugu")).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /Off voice/ })).toBeNull();
    // Unset stays a choice: the best voice for each account.
    expect((screen.getByRole("radio", { name: /Best voice for each account/ }) as HTMLInputElement).checked).toBe(true);
    // The preview sits beside the card, and only for a voice that has one.
    expect(screen.getByRole("button", { name: /Meera/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Ravi/ })).toBeNull();
    expect(screen.queryByRole("textbox", { name: /New value/ })).toBeNull();

    fireEvent.click(meera);
    fireEvent.click(screen.getByRole("button", { name: "Planned change" }));
    fireEvent.click(screen.getByRole("button", { name: "Save change" }));

    await waitFor(() => expect(onWritten).toHaveBeenCalled());
    expect(putBody(calls)).toEqual({ value: "byok:meera", reason: "Planned change" });
  });

  it("says plainly when no voice is enabled for clients", async () => {
    renderForm({ [VOICES_PATH]: voices([HIDDEN]) });
    expect(await screen.findByText("No voice is enabled for clients")).toBeTruthy();
    expect(screen.getByText(/Enable one on the Voices page/)).toBeTruthy();
  });

  it("shows the server's refusal of a voice in its own words", async () => {
    renderForm({
      [VOICES_PATH]: voices([MEERA]),
      [`PUT ${OPS_CONFIG_PATH}/default_agent_voice_id`]: problem(422, {
        kind: "business_rule",
        code: "default_agent_voice_not_offered",
        title: "We cannot do that",
        detail: "That voice is not enabled for clients, so a new agent cannot be given it.",
        remediation: "Enable it on the Voices page first, or choose one of the voices listed.",
      }),
    });

    fireEvent.click(await screen.findByRole("radio", { name: /Meera/ }));
    fireEvent.click(screen.getByRole("button", { name: "Planned change" }));
    fireEvent.click(screen.getByRole("button", { name: "Save change" }));

    expect(
      await screen.findByText(/That voice is not enabled for clients, so a new agent cannot be given it\./),
    ).toBeTruthy();
  });

  it("says when the voice list cannot be read, with a retry", async () => {
    renderForm({
      [VOICES_PATH]: problem(403, {
        kind: "forbidden",
        title: "Not allowed",
        detail: "Your admin account cannot read the voice list.",
      }),
    });
    expect(await screen.findByText("Your admin account cannot read the voice list.")).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull();
  });
});
