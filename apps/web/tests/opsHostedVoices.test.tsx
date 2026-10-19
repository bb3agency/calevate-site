import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import VoicesPage from "@/app/admin/ops/voices/page";
import {
  NO_FILTERS,
  applyFilters,
  findByVoiceId,
  metaLine,
} from "@/app/admin/ops/voices/hosted/voiceFilters";
import { ownModelSteps } from "@/app/admin/ops/voices/hosted/OwnModelCard";
import { studioSteps } from "@/app/admin/ops/voices/hosted/StudioVoicesCard";
import {
  OPS_CLONES_PATH,
  OPS_CLONE_CONSENT_PATH,
  OPS_DISPLAY_NAME_PATH,
  OPS_HOSTED_AGENTS_PATH,
  OPS_HOSTED_PATH,
  OPS_OWN_MODEL_DEVELOPER_PATH,
  OPS_OWN_MODEL_ENABLE_PATH,
  OPS_OWN_MODEL_PATH,
  OPS_PERSON_CLONE_PATH,
  OPS_PREVIEW_FETCH_PATH,
  OPS_STUDIO_ENABLE_PATH,
  OPS_STUDIO_VOICES_PATH,
  type HostedVoice,
  type HostedVoices,
  type OwnModel,
  type StudioVoices,
} from "@/lib/api/opsHostedVoices";
import { OPS_VOICES_REFRESH_PATH } from "@/lib/api/opsVoices";
import { OPS_PREVIEW_PATH, previewUrl } from "@/lib/api/voicePreview";

import { expectNoA11yViolations } from "./a11y";
import { HOSTED_VOICES_PROBE_PATH, NOT_HOSTED } from "./fixtures/sharedReads";
import { problem, renderAdminPage, type Routes } from "./harness";

/**
 * THE VOICES PAGE ON AN ENGINE THAT HOSTS ITS VOICES (D-687, D-721).
 *
 * What this screen must get right, by what each failure costs:
 *
 * 1. **The server picks the screen.** `available: true` shows the hosted screen;
 *    `available: false` shows the server's sentence and never reads the Studio voices state.
 * 2. **One compact row per voice**, filterable, paged; the full platform list is read only
 *    when "Add voices" opens, and only voices in a band we sell can be ticked there.
 * 3. **The switch names the state the API holds**: an archived voice is never captioned
 *    "Offered to clients".
 * 4. **A cloned voice of a real person** cannot be switched on without its consent record,
 *    and the record carries its step-up confirmation.
 * 5. **A clone carries both consents and the step-up confirmation**; deleting one with live
 *    agents on it is a second, informed decision.
 * 6. **Studio is a checklist** with the next step as the primary action; our developer
 *    workspace's switch is expected ON (D-727), so nothing offers to switch it off.
 */

const SUPERADMIN: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000f1",
  realm: "admin",
  role: "superadmin",
  permissions: ["ops:manage", "admin:tenants"],
};

function voice(over: Partial<HostedVoice> = {}): HostedVoice {
  return {
    voice_id: "engine:anjali",
    vendor_id: "anjali",
    label: "Anjali",
    vendor_label: "Anjali",
    display_label: null,
    source: "engine",
    rung: "clear",
    band: "premium",
    sold: true,
    not_sold_reason: null,
    is_custom: false,
    accent: "te",
    accent_label: "Telugu",
    gender: null,
    languages: ["te-IN", "hi-IN", "en-IN"],
    description: "Warm and calm",
    language_note: "Speaks the agent's language, with an accent: Telugu.",
    state: "enabled",
    added: true,
    offered: true,
    synced_at: "2026-10-08T04:30:00Z",
    curated_at: "2026-10-08T05:00:00Z",
    withdrawn_at: null,
    preview_available: true,
    preview_source: "upload",
    deletable_clone: false,
    live_agents: 0,
    person_clone: false,
    clone_consent: null,
    clone_blocker: null,
    ...over,
  };
}

const CLONE = voice({
  voice_id: "engine:clone-ravi",
  vendor_id: "clone-ravi",
  label: "Ravi",
  vendor_label: "Ravi",
  is_custom: true,
  state: "disabled",
  offered: false,
  preview_available: false,
  preview_source: null,
  deletable_clone: true,
  live_agents: 2,
});

const STOCK_NO_PREVIEW = voice({
  voice_id: "engine:kavya",
  vendor_id: "kavya",
  label: "Kavya",
  vendor_label: "Kavya",
  preview_available: false,
  preview_source: null,
});

const STUDIO = voice({
  voice_id: "byok:meera",
  vendor_id: "meera",
  label: "Meera",
  vendor_label: "Meera",
  source: "byok",
  rung: "studio",
  band: null,
  gender: "feminine",
  accent: "te",
  languages: ["te-IN"],
  preview_available: false,
  preview_source: null,
});

const ARCHIVED = voice({ voice_id: "engine:old", vendor_id: "old", label: "Old voice", state: "archived", offered: false });

/** The founder's own Instant clone, marked and renamed, with no consent on file yet. */
const PERSON_CLONE = voice({
  voice_id: "byok:sri-clone",
  vendor_id: "a0e99841-438c-4a64-b679-ae501e7d6003",
  label: "Aditya",
  vendor_label: "Sri (instant clone)",
  display_label: "Aditya",
  source: "byok",
  rung: "studio",
  band: null,
  state: "disabled",
  offered: false,
  person_clone: true,
  clone_blocker: "Record the speaker's consent before offering this voice",
});

function hosted(over: Partial<HostedVoices> = {}): HostedVoices {
  return {
    available: true,
    scope: "added",
    voices: [voice(), CLONE, STOCK_NO_PREVIEW, STUDIO],
    cached: 37,
    offered: 2,
    studio_ready: true,
    clear_band: "premium",
    note: "2 voices are offered to clients.",
    bands: { standard: 3, premium: 1, studio: 2 },
    plan_note: null,
    ...over,
  };
}

const EXPLANATION =
  "Studio voices are our Cartesia key, switched on for the voice only. Studio ready switches it on in our developer workspace, where free-trial agents speak Studio.";

const STUDIO_ON: StudioVoices = {
  ready: true,
  cartesia_key_configured: true,
  developer_holds_key: true,
  developer_switch_on: true,
  minute_attested: true,
  synthesis_priced: true,
  voices_listed: true,
  missing: [],
  workspaces: [
    {
      tenant_id: "7f0c2b1e-0000-4000-8000-000000000001",
      tenant_name: "Sri Clinic",
      enabled_at: "2026-10-10T10:00:00Z",
      checked_at: "2026-10-10T11:00:00Z",
      error_code: null,
    },
  ],
  live_studio_agents: 2,
  explanation: EXPLANATION,
  note: "Ready: Studio is on in our developer workspace for trial agents and in 1 client workspace(s).",
  key: {
    enabled: true,
    scope: "voice",
    complete: true,
    using: "own",
    voice_provider: "cartesia",
    speaks_on_own_voice: true,
  },
};

const STUDIO_OFF: StudioVoices = {
  ...STUDIO_ON,
  ready: false,
  developer_holds_key: false,
  developer_switch_on: false,
  voices_listed: false,
  missing: ["Run Studio ready to switch our key on in the developer workspace."],
  workspaces: [],
  live_studio_agents: 0,
  note: "Not ready: Run Studio ready to switch our key on in the developer workspace.",
  key: {
    enabled: false,
    scope: null,
    complete: false,
    using: "none",
    voice_provider: null,
    speaks_on_own_voice: false,
  },
};

const OWN_MODEL_ON: OwnModel = {
  switched_on: true,
  ready: true,
  default_model: "gemini-2.5-flash-lite",
  google_key_configured: true,
  default_offerable: true,
  default_reason: null,
  data_use_attested: true,
  llm_voice_minute_attested: true,
  developer_ready: true,
  developer_checked_at: "2026-10-19T10:00:00Z",
  developer_error_code: null,
  offerable_models: ["gemini-2.5-flash-lite"],
  missing: [],
  workspaces: [],
  explanation: "Agents answer on our Google key.",
  note: "On: 0 client workspace(s) answer on our Google key.",
  floor_prompt_tokens: 6150,
  floor_prompt_source: "published",
  floor_prompt_basis:
    "6,150 prompt tokens: the largest of 2 live agents' published prompts (0 of 20 own-model calls measured)",
  floor_model_inr_per_min: "0.3640",
};

const OWN_MODEL_OFF: OwnModel = {
  ...OWN_MODEL_ON,
  switched_on: false,
  ready: false,
  google_key_configured: false,
  data_use_attested: false,
  developer_ready: false,
  developer_checked_at: null,
  missing: ["Save the Google (Gemini) API key in the ops console Secrets panel."],
  note: "Not ready: Save the Google (Gemini) API key in the ops console Secrets panel.",
};

const ALL_PATH = `${OPS_HOSTED_PATH}?scope=all`;

/** Every voice in these fixtures has nobody on it unless a test says otherwise. */
function noAgents(): Routes {
  const ids = [voice(), CLONE, STOCK_NO_PREVIEW, STUDIO, ARCHIVED, PERSON_CLONE].map((v) => v.voice_id);
  return Object.fromEntries(
    ids.map((id) => [`${OPS_HOSTED_AGENTS_PATH}?voice_id=${encodeURIComponent(id)}`, { voice_id: id, agents: [] }]),
  );
}

function routes(over: Routes = {}): Routes {
  return {
    ...noAgents(),
    [ADMIN_ME_PATH]: SUPERADMIN,
    [HOSTED_VOICES_PROBE_PATH]: hosted(),
    [OPS_STUDIO_VOICES_PATH]: STUDIO_ON,
    [OPS_OWN_MODEL_PATH]: OWN_MODEL_ON,
    ...over,
  };
}

function row(label: string): HTMLElement {
  return screen.getByRole("listitem", { name: label });
}

/** Open one voice's detail drawer from its name in the list. */
async function openVoice(label: string): Promise<HTMLElement> {
  const item = await screen.findByRole("listitem", { name: label });
  fireEvent.click(within(item).getByRole("button", { name: label }));
  return screen.findByRole("dialog", { name: label });
}

async function openAdd(): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole("button", { name: "Add voices" }));
  return screen.findByRole("dialog", { name: "Add voices" });
}

/** The multipart seam: `apiUpload` is an XHR, stubbed as `knowledgeUploads.test.tsx` does. */
interface XhrCall {
  url: string;
  headers: Record<string, string>;
  form: FormData;
}
const xhrCalls: XhrCall[] = [];
let xhrAnswer: { status: number; body: unknown } = { status: 201, body: {} };

class StubXhr {
  status = 0;
  responseText = "";
  withCredentials = false;
  readonly upload = new EventTarget();
  private readonly events = new EventTarget();
  private readonly headers: Record<string, string> = {};
  private url = "";
  open(_method: string, url: string): void {
    this.url = url;
  }
  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }
  getResponseHeader(name: string): string | null {
    if (name.toLowerCase() !== "content-type") return null;
    return xhrAnswer.status >= 400 ? "application/problem+json" : "application/json";
  }
  addEventListener(type: string, listener: EventListener): void {
    this.events.addEventListener(type, listener);
  }
  abort(): void {
    this.events.dispatchEvent(new Event("abort"));
  }
  send(form: FormData): void {
    xhrCalls.push({ url: this.url, headers: { ...this.headers }, form });
    queueMicrotask(() => {
      this.status = xhrAnswer.status;
      this.responseText = JSON.stringify(xhrAnswer.body);
      this.events.dispatchEvent(new Event("load"));
    });
  }
}

beforeEach(() => {
  xhrCalls.length = 0;
  xhrAnswer = { status: 201, body: {} };
  vi.stubGlobal("XMLHttpRequest", StubXhr);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the voices page picks its screen from the server's answer", () => {
  it("shows the hosted screen when the voice platform hosts the voices", async () => {
    renderAdminPage(<VoicesPage />, routes());

    expect(await screen.findByRole("heading", { name: "Offered voices" })).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "Anjali" })).toBeTruthy();
  });

  it("prints the server's sentence and never reads the Studio voices when voices are not hosted", async () => {
    const { calls } = renderAdminPage(<VoicesPage />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      [HOSTED_VOICES_PROBE_PATH]: NOT_HOSTED,
    });

    await screen.findByText("No voices to manage here");
    expect(screen.getByText(NOT_HOSTED.note)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Offered voices" })).toBeNull();
    expect(calls.some((c) => c.path === OPS_STUDIO_VOICES_PATH)).toBe(false);
  });

  it("tells an admin without ops:manage why, and never asks for the voices", async () => {
    const { calls } = renderAdminPage(<VoicesPage />, {
      [ADMIN_ME_PATH]: { ...SUPERADMIN, role: "support", permissions: ["admin:tenants"] },
      [HOSTED_VOICES_PROBE_PATH]: problem(403, { title: "Forbidden", kind: "forbidden" }),
    });

    await screen.findByText(/add and manage the voices this platform offers/);
    expect(screen.queryByText("Forbidden")).toBeNull();
    expect(calls.some((c) => c.path.startsWith("/v1/ops/voices/hosted"))).toBe(false);
  });

  it("renders a failed probe as a refusal, not as either screen", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({ [HOSTED_VOICES_PROBE_PATH]: problem(503, { title: "Upstream unavailable", kind: "unavailable" }) }),
    );
    expect(await screen.findByText(/Upstream unavailable/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Offered voices" })).toBeNull();
  });
});

describe("the offered voices list", () => {
  it("is one row per voice with no raw id, and the platform list is read only for Add voices", async () => {
    const { calls } = renderAdminPage(<VoicesPage />, routes());

    const anjali = within(await screen.findByRole("listitem", { name: "Anjali" }));
    expect(anjali.queryByText(/engine:anjali/)).toBeNull();
    expect(anjali.getByText("Telugu accent")).toBeTruthy();
    // A missing preview is a small badge, not a paragraph.
    expect(within(row("Kavya")).getByText("No preview")).toBeTruthy();
    expect(calls.some((c) => c.path === ALL_PATH)).toBe(false);
  });

  it("filters by tier, name and state, and hides archived voices until asked", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({ [HOSTED_VOICES_PROBE_PATH]: hosted({ voices: [voice(), STOCK_NO_PREVIEW, STUDIO, ARCHIVED] }) }),
    );

    await screen.findByRole("listitem", { name: "Anjali" });
    expect(screen.queryByRole("listitem", { name: "Old voice" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^Studio 1$/ }));
    expect(screen.getByRole("listitem", { name: "Meera" })).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "Anjali" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^All / }));
    fireEvent.change(screen.getByLabelText("Search offered voices by name"), { target: { value: "kav" } });
    expect(screen.getByRole("listitem", { name: "Kavya" })).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "Anjali" })).toBeNull();

    fireEvent.click(screen.getAllByRole("button", { name: "Clear filters" })[0]!);
    fireEvent.change(screen.getByRole("combobox", { name: "State" }), { target: { value: "archived" } });
    expect(screen.getByRole("listitem", { name: "Old voice" })).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "Anjali" })).toBeNull();
  });

  it("pages a long list instead of rendering every row", async () => {
    const many = Array.from({ length: 30 }, (_, i) =>
      voice({ voice_id: `engine:v${i}`, vendor_id: `v${i}`, label: `Voice ${String(i).padStart(2, "0")}` }),
    );
    renderAdminPage(<VoicesPage />, routes({ [HOSTED_VOICES_PROBE_PATH]: hosted({ voices: many }) }));

    await screen.findByRole("listitem", { name: "Voice 00" });
    expect(screen.queryByRole("listitem", { name: "Voice 29" })).toBeNull();
    expect(screen.getByText("Showing 25 of 30")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show 5 more" }));
    expect(screen.getByRole("listitem", { name: "Voice 29" })).toBeTruthy();
  });

  it("switches a voice on for clients with one PATCH naming the voice and the state", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`PATCH ${OPS_HOSTED_PATH}`]: { voice: { ...CLONE, state: "enabled" }, next_step: "Clients can choose Ravi now." },
      }),
    );

    await screen.findByRole("listitem", { name: "Ravi" });
    const toggle = within(row("Ravi")).getByRole("switch", { name: /Not offered: Ravi/ }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    fireEvent.click(toggle);

    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.path === OPS_HOSTED_PATH)).toBe(true));
    const write = calls.find((c) => c.method === "PATCH" && c.path === OPS_HOSTED_PATH)!;
    expect(JSON.parse(write.body!)).toEqual({ voice_id: "engine:clone-ravi", state: "enabled" });
  });

  it("names an archived voice's state as archived, never as offered", async () => {
    renderAdminPage(<VoicesPage />, routes({ [HOSTED_VOICES_PROBE_PATH]: hosted({ voices: [ARCHIVED] }) }));
    await screen.findByText("No voice matches these filters.");
    fireEvent.change(screen.getByRole("combobox", { name: "State" }), { target: { value: "archived" } });

    const drawer = await openVoice("Old voice");
    const toggle = within(drawer).getByRole("switch", { name: /^Archived/ }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(within(drawer).getByText("Archived")).toBeTruthy();
    expect(within(drawer).queryByText("Offered to clients")).toBeNull();
    expect(within(drawer).getByRole("button", { name: "Restore, not offered" })).toBeTruthy();
  });

  it("plays a stored preview through the admin preview route", async () => {
    const play = vi.fn(() => Promise.resolve());
    Object.defineProperty(HTMLMediaElement.prototype, "play", { configurable: true, value: play });
    Object.defineProperty(HTMLMediaElement.prototype, "pause", { configurable: true, value: vi.fn() });
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:clip"), revokeObjectURL: vi.fn() });
    const clip = previewUrl(OPS_PREVIEW_PATH, "engine:anjali");
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [clip]: () => new Response(new Uint8Array([1]), { status: 200, headers: { "content-type": "audio/mpeg" } }),
      }),
    );

    await screen.findByRole("listitem", { name: "Anjali" });
    fireEvent.click(within(row("Anjali")).getByRole("button", { name: "Play the preview of Anjali" }));
    await waitFor(() => expect(play).toHaveBeenCalled());
    expect(calls.some((c) => c.path === clip)).toBe(true);
  });

  it("prints the server's refresh sentence as written", async () => {
    const sentence = "ThinnestAI listed 2 voice(s): 1 Standard, 0 Premium, 1 Studio.";
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`POST ${OPS_VOICES_REFRESH_PATH}`]: {
          seen: 2,
          written: 2,
          pruned: 0,
          complete: true,
          in_force: 1,
          bands: { standard: 1, studio: 1 },
          note: sentence,
        },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Refresh" }));
    expect(await screen.findByText(sentence)).toBeTruthy();
    expect(calls.some((c) => c.method === "POST" && c.path === OPS_VOICES_REFRESH_PATH)).toBe(true);
  });

  it("explains plainly when the platform lists none of the band sold as Clear", async () => {
    const sentence =
      "ThinnestAI listed 4 voice(s) but none in the ThinnestAI Premium band, the band sold as Clear ('ThinnestAI voice band sold as Clear' in the ops console). Check the account on ThinnestAI, then refresh.";
    renderAdminPage(
      <VoicesPage />,
      routes({ [HOSTED_VOICES_PROBE_PATH]: hosted({ voices: [], bands: { standard: 3, studio: 1 }, plan_note: sentence }) }),
    );

    expect(await screen.findByText("No ThinnestAI Premium band voices on the voice platform")).toBeTruthy();
    expect(screen.getByText(sentence)).toBeTruthy();
    expect(screen.queryByText(/is not our Studio tier/)).toBeNull();
    // The empty list offers the way forward.
    expect(screen.getAllByRole("button", { name: "Add voices" }).length).toBe(2);
  });

  it("on ThinnestAI's Studio band, says our Studio tier adds no voice to it", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [HOSTED_VOICES_PROBE_PATH]: hosted({
          voices: [],
          clear_band: "studio",
          bands: { standard: 3, premium: 4 },
          plan_note: "ThinnestAI listed 7 voice(s) but none in the ThinnestAI Studio band.",
        }),
      }),
    );

    expect(await screen.findByText("No ThinnestAI Studio band voices on the voice platform")).toBeTruthy();
    expect(screen.getByText(/is not our Studio tier: that is our Cartesia key/)).toBeTruthy();
  });
});

describe("adding voices", () => {
  const fresh = voice({ voice_id: "engine:new", vendor_id: "new", label: "Newly synced", added: false, state: "disabled", offered: false });
  const studioFresh = voice({
    ...STUDIO,
    voice_id: "byok:tara",
    vendor_id: "tara-0001",
    label: "Tara",
    vendor_label: "Tara",
    added: false,
    state: "disabled",
    offered: false,
  });
  const unsold = voice({
    voice_id: "engine:priya",
    vendor_id: "priya",
    label: "Priya",
    rung: null,
    band: "standard",
    sold: false,
    not_sold_reason: "Only ThinnestAI Premium band voices are sold as Clear on this platform, and Priya is in the ThinnestAI Standard band.",
    added: false,
    state: "disabled",
    offered: false,
  });

  it("ticks several voices from the platform's list and adds each with its own POST", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [ALL_PATH]: hosted({ scope: "all", voices: [voice(), fresh, studioFresh, unsold] }),
        [`POST ${OPS_HOSTED_PATH}`]: { voice: { ...fresh, added: true }, next_step: "Give it a preview, then enable it." },
      }),
    );

    const drawer = await openAdd();
    await within(drawer).findByRole("checkbox", { name: /Newly synced/ });
    // Only voices we could sell, and not added yet, can be ticked.
    expect(within(drawer).queryByRole("checkbox", { name: /Anjali/ })).toBeNull();
    expect(within(drawer).queryByRole("checkbox", { name: /Priya/ })).toBeNull();
    expect(within(drawer).getByText(/1 more are in bands we do not sell/)).toBeTruthy();

    fireEvent.click(within(drawer).getByRole("checkbox", { name: /Newly synced/ }));
    fireEvent.click(within(drawer).getByRole("checkbox", { name: /Tara/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add 2 voices" }));

    expect(await within(drawer).findByText(/Added Newly synced, Tara/)).toBeTruthy();
    const writes = calls.filter((c) => c.method === "POST" && c.path === OPS_HOSTED_PATH);
    expect(writes.map((c) => JSON.parse(c.body!))).toEqual([{ voice_id: "engine:new" }, { voice_id: "byok:tara" }]);
  });

  it("finds a voice by its pasted id, and says so honestly when the platform did not list it", async () => {
    renderAdminPage(<VoicesPage />, routes({ [ALL_PATH]: hosted({ scope: "all", voices: [fresh, studioFresh] }) }));

    const drawer = await openAdd();
    await within(drawer).findByRole("checkbox", { name: /Newly synced/ });
    fireEvent.click(within(drawer).getByText("Find a voice by its id"));
    const field = within(drawer).getByLabelText("Voice id");

    fireEvent.change(field, { target: { value: "tara-0001" } });
    expect(within(within(drawer).getByRole("list", { name: "Found voice" })).getByRole("checkbox", { name: /Tara/ })).toBeTruthy();

    fireEvent.change(field, { target: { value: "a0e99841-not-listed" } });
    expect(within(drawer).getByText(/isn.t in the list the voice platform returned for our key/)).toBeTruthy();
  });
});

describe("one voice's detail", () => {
  it("shows the copyable vendor id and the agents speaking it, read only when opened", async () => {
    const agents = `${OPS_HOSTED_AGENTS_PATH}?voice_id=${encodeURIComponent("engine:anjali")}`;
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [agents]: {
          voice_id: "engine:anjali",
          agents: [
            { tenant_id: "t1", tenant_name: "Skyline Properties", agent_id: "a1", agent_name: "Reception", status: "live" },
          ],
        },
      }),
    );

    await screen.findByRole("listitem", { name: "Anjali" });
    expect(calls.some((c) => c.path === agents)).toBe(false);
    const drawer = await openVoice("Anjali");
    expect(within(drawer).getByText("anjali")).toBeTruthy();
    expect(within(drawer).getByRole("button", { name: "Copy the voice id" })).toBeTruthy();
    expect(await within(drawer).findByRole("link", { name: "Reception" })).toBeTruthy();
    expect(within(drawer).getByText(/Skyline Properties/)).toBeTruthy();
  });

  it("generates a preview for a clone and uploads one for a stock voice", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`POST ${OPS_PREVIEW_FETCH_PATH}`]: { voice: { ...CLONE, preview_available: true }, next_step: "Stored." },
      }),
    );

    let drawer = await openVoice("Ravi");
    expect(within(drawer).getByLabelText("Upload a preview")).toBeTruthy();
    fireEvent.click(within(drawer).getByRole("button", { name: "Generate preview" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === OPS_PREVIEW_FETCH_PATH)).toBe(true));
    expect(JSON.parse(calls.find((c) => c.path === OPS_PREVIEW_FETCH_PATH)!.body!)).toEqual({ voice_id: "engine:clone-ravi" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));

    xhrAnswer = { status: 200, body: { voice: { ...STOCK_NO_PREVIEW, preview_available: true }, next_step: "Stored." } };
    drawer = await openVoice("Kavya");
    const clip = new File([new Uint8Array([1, 2])], "kavya.mp3", { type: "audio/mpeg" });
    await act(async () => {
      fireEvent.change(within(drawer).getByLabelText("Upload a preview"), { target: { files: [clip] } });
    });
    await waitFor(() => expect(xhrCalls).toHaveLength(1));
    expect(xhrCalls[0]!.url).toContain("/v1/ops/voices/hosted/preview");
    expect(xhrCalls[0]!.form.get("voice_id")).toBe("engine:kavya");
  });

  it("refuses a preview clip over 2 MB before sending it", async () => {
    renderAdminPage(<VoicesPage />, routes());
    const drawer = await openVoice("Kavya");
    const big = new File([new Uint8Array(2 * 1024 * 1024 + 1)], "big.wav", { type: "audio/wav" });
    fireEvent.change(within(drawer).getByLabelText("Upload a preview"), { target: { files: [big] } });
    expect(await within(drawer).findByText(/over the .* limit/)).toBeTruthy();
    expect(xhrCalls).toHaveLength(0);
  });

  it("sets the name clients see with one PATCH", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`PATCH ${OPS_DISPLAY_NAME_PATH}`]: {
          voice: { ...STUDIO, label: "Meenakshi", display_label: "Meenakshi" },
          next_step: "Clients see this voice as Meenakshi.",
        },
      }),
    );

    const drawer = await openVoice("Meera");
    fireEvent.click(within(drawer).getByRole("button", { name: "Change" }));
    fireEvent.change(within(drawer).getByLabelText("Name clients see"), { target: { value: "Meenakshi" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.path === OPS_DISPLAY_NAME_PATH)).toBe(true));
    expect(JSON.parse(calls.find((c) => c.path === OPS_DISPLAY_NAME_PATH)!.body!)).toEqual({
      voice_id: "byok:meera",
      display_label: "Meenakshi",
    });
  });
});

describe("a cloned voice of a real person (D-721)", () => {
  it("cannot be switched on until its consent is recorded, and says why", async () => {
    renderAdminPage(<VoicesPage />, routes({ [HOSTED_VOICES_PROBE_PATH]: hosted({ voices: [PERSON_CLONE] }) }));

    await screen.findByRole("listitem", { name: "Aditya" });
    const toggle = within(row("Aditya")).getByRole("switch") as HTMLInputElement;
    expect(toggle.disabled).toBe(true);
    expect(within(row("Aditya")).getByText("Record the speaker's consent before offering this voice")).toBeTruthy();
    // The client-facing name is the operator's, and the speaker's name is not in the row.
    expect(within(row("Aditya")).queryByText(/Sri/)).toBeNull();
  });

  it("records the consent as a multipart write with the step-up confirmation for that voice", async () => {
    xhrAnswer = {
      status: 200,
      body: {
        voice: {
          ...PERSON_CLONE,
          clone_blocker: null,
          clone_consent: {
            speaker_name: "Test Speaker",
            statement: "I agree.",
            consented_on: "2026-10-10",
            scope: "Calls made by Calevate clients' agents.",
            recorded_by: SUPERADMIN.user_id,
            recorded_by_name: "Ops",
            recorded_at: "2026-10-10T10:00:00Z",
            has_document: true,
          },
        },
        next_step: "The speaker's consent is recorded. The voice can now be offered.",
      },
    };
    renderAdminPage(<VoicesPage />, routes({ [HOSTED_VOICES_PROBE_PATH]: hosted({ voices: [PERSON_CLONE] }) }));

    const drawer = await openVoice("Aditya");
    const submit = within(drawer).getByRole("button", { name: "Record consent" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(drawer).getByLabelText(/Speaker.s full name/), { target: { value: "Test Speaker" } });
    fireEvent.change(within(drawer).getByLabelText("Date they consented"), { target: { value: "2026-10-10" } });
    const signed = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])], "consent.pdf", { type: "application/pdf" });
    await act(async () => {
      fireEvent.change(within(drawer).getByLabelText("Signed consent (optional)"), { target: { files: [signed] } });
    });
    expect(submit.disabled).toBe(false);
    await act(async () => {
      fireEvent.click(submit);
    });

    await waitFor(() => expect(xhrCalls).toHaveLength(1));
    const sent = xhrCalls[0]!;
    expect(sent.url).toContain(OPS_CLONE_CONSENT_PATH);
    expect(sent.headers["X-Confirm-Action"]).toBe("record_voice_consent:byok:sri-clone");
    expect(sent.form.get("speaker_name")).toBe("Test Speaker");
    expect(sent.form.get("consented_on")).toBe("2026-10-10");
    expect(String(sent.form.get("statement"))).toMatch(/cloned copy of my voice/);
    expect(sent.form.get("document")).toBeInstanceOf(File);
  });

  it("switching an offered voice to cloned opens the consent form instead of a refusal", async () => {
    const offered = voice({ ...PERSON_CLONE, person_clone: false, clone_blocker: null });
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({ [HOSTED_VOICES_PROBE_PATH]: hosted({ voices: [offered] }) }),
    );

    const drawer = await openVoice("Aditya");
    fireEvent.click(within(drawer).getByRole("switch", { name: /A cloned voice of a real person/ }));
    expect(await within(drawer).findByRole("button", { name: "Record consent" })).toBeTruthy();
    expect(within(drawer).queryByText("Record the speaker's consent before offering this voice")).toBeNull();
    expect(calls.some((c) => c.method === "PATCH" && c.path === OPS_PERSON_CLONE_PATH)).toBe(false);
  });

  it("unmarking asks first, keeps the record, and carries its own step-up confirmation", async () => {
    const consented = voice({
      ...PERSON_CLONE,
      clone_blocker: null,
      clone_consent: {
        speaker_name: "Test Speaker",
        statement: "I agree.",
        consented_on: "2026-10-10",
        scope: "Calls made by Calevate clients' agents.",
        recorded_by: SUPERADMIN.user_id,
        recorded_by_name: "Ops",
        recorded_at: "2026-10-10T10:00:00Z",
        has_document: false,
      },
    });
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [HOSTED_VOICES_PROBE_PATH]: hosted({ voices: [consented] }),
        [`PATCH ${OPS_PERSON_CLONE_PATH}`]: {
          voice: { ...consented, person_clone: false },
          next_step: "No longer marked as a cloned voice of a real person.",
        },
      }),
    );

    const drawer = await openVoice("Aditya");
    expect(within(drawer).getByText("Test Speaker")).toBeTruthy();
    fireEvent.click(within(drawer).getByRole("switch", { name: /A cloned voice of a real person/ }));
    const dialog = await screen.findByRole("dialog", { name: "Aditya is not a cloned voice?" });
    expect(within(dialog).getByText(/consent record and its signed document are kept/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove the mark" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.path === OPS_PERSON_CLONE_PATH)).toBe(true));
    const write = calls.find((c) => c.path === OPS_PERSON_CLONE_PATH)!;
    expect(JSON.parse(write.body!)).toEqual({ voice_id: "byok:sri-clone", person_clone: false });
    expect(write.headers["X-Confirm-Action"]).toBe("set_voice_person_clone:byok:sri-clone");
  });
});

describe("deleting a clone", () => {
  it("asks again with the server's words when live agents are on it, then confirms", async () => {
    let attempt = 0;
    const inUse = "Ravi is spoken by 2 live agents: Front desk and Reminders. Deleting moves them to a standard voice.";
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`DELETE ${OPS_CLONES_PATH}?voice_id=engine%3Aclone-ravi&confirm=false`]: () => {
          attempt += 1;
          return problem(409, {
            type: "urn:calevate:conflict/voice_clone_in_use",
            title: "Live agents are on this voice",
            detail: inUse,
            kind: "conflict",
          });
        },
        [`DELETE ${OPS_CLONES_PATH}?voice_id=engine%3Aclone-ravi&confirm=true`]: {
          voice_id: "engine:clone-ravi",
          moved_agents: 2,
          next_step:
            "The clone was deleted. The voice platform moved 2 agent(s) to its standard voice; move them to another voice and republish them.",
        },
      }),
    );

    const drawer = await openVoice("Ravi");
    fireEvent.click(within(drawer).getByRole("button", { name: "Delete the clone Ravi" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete the clone Ravi?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete clone" }));

    expect(await within(dialog).findByText(inUse)).toBeTruthy();
    expect(attempt).toBe(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete and move those agents" }));

    // The server's sentence already names the deletion and the move; it is shown once.
    expect(
      await screen.findByText(
        "Ravi: The clone was deleted. The voice platform moved 2 agent(s) to its standard voice; move them to another voice and republish them.",
      ),
    ).toBeTruthy();
    const deletes = calls.filter((c) => c.method === "DELETE");
    expect(deletes.map((c) => c.path.endsWith("confirm=true"))).toEqual([false, true]);
    expect(deletes[1]!.headers["X-Confirm-Action"]).toBe("delete_voice_clone:engine:clone-ravi");
  });
});

describe("Studio setup", () => {
  it("derives the checklist from the server's booleans, in the order an operator works", () => {
    const steps = studioSteps(STUDIO_OFF);
    expect(steps.map((s) => [s.id, s.done])).toEqual([
      ["key", true],
      ["held", false],
      ["minute", true],
      ["voice-price", true],
      ["listed", false],
    ]);
  });

  it("makes the next step the primary action and runs Studio ready behind a step-up confirmation", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`GET ${OPS_STUDIO_VOICES_PATH}`]: STUDIO_OFF,
        [`POST ${OPS_STUDIO_ENABLE_PATH}`]: STUDIO_ON,
      }),
    );

    expect(await screen.findByText("Not ready")).toBeTruthy();
    expect(screen.getByText("3 of 5 done")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Studio ready" }));
    const dialog = await screen.findByRole("dialog", { name: "Make Studio ready?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Studio ready" }));

    expect(await screen.findByText("Ready")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sri Clinic" })).toBeTruthy();
    const write = calls.find((c) => c.method === "POST" && c.path === OPS_STUDIO_ENABLE_PATH)!;
    expect(write.headers["X-Confirm-Action"]).toBe("enable_studio_voices");
    expect(JSON.parse(write.body!)).toEqual({});
  });

  it("names a paying client to switch on now when one is typed", async () => {
    const tenant = "7f0c2b1e-0000-4000-8000-000000000002";
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`GET ${OPS_STUDIO_VOICES_PATH}`]: { ...STUDIO_OFF, developer_holds_key: true, developer_switch_on: true },
        [`POST ${OPS_STUDIO_ENABLE_PATH}`]: STUDIO_ON,
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "List the voices" }));
    const dialog = await screen.findByRole("dialog", { name: "Make Studio ready?" });
    fireEvent.change(within(dialog).getByLabelText(/Paying client/), { target: { value: tenant } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Studio ready" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === OPS_STUDIO_ENABLE_PATH)).toBe(true));
    const write = calls.find((c) => c.method === "POST" && c.path === OPS_STUDIO_ENABLE_PATH)!;
    expect(JSON.parse(write.body!)).toEqual({ tenant_id: tenant });
  });

  it("renders the server's refusal inside the dialog", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [`GET ${OPS_STUDIO_VOICES_PATH}`]: STUDIO_OFF,
        [`POST ${OPS_STUDIO_ENABLE_PATH}`]: problem(409, {
          type: "urn:calevate:conflict/studio_agents_not_kept_off",
          title: "Studio voices were not switched on",
          detail: "1 published agent(s) in this client's workspace could not be confirmed as staying on the voice platform's own voices.",
          kind: "conflict",
        }),
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Studio ready" }));
    const dialog = await screen.findByRole("dialog", { name: "Make Studio ready?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Studio ready" }));
    expect(await within(dialog).findByText(/could not be confirmed as staying/)).toBeTruthy();
  });

  it("never offers to switch our developer workspace off", async () => {
    renderAdminPage(<VoicesPage />, routes({ [`GET ${OPS_STUDIO_VOICES_PATH}`]: STUDIO_ON }));
    await screen.findByText("Ready");
    expect(screen.queryByText(/developer workspace.s own keys are on/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Switch developer workspace off" })).toBeNull();
  });
});


describe("our own model card (D-764)", () => {
  it("lists the five steps from the server's booleans", () => {
    expect(ownModelSteps(OWN_MODEL_OFF).map((s) => [s.id, s.done])).toEqual([
      ["key", false],
      ["model", true],
      ["data-use", false],
      ["minute", true],
      ["developer", false],
    ]);
  });

  it("sets up our developer workspace behind a step-up confirmation (D-834)", async () => {
    const ready = { ...OWN_MODEL_OFF, google_key_configured: true, data_use_attested: true };
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`GET ${OPS_OWN_MODEL_PATH}`]: ready,
        [`POST ${OPS_OWN_MODEL_DEVELOPER_PATH}`]: OWN_MODEL_ON,
      }),
    );
    const card = (await screen.findByRole("heading", { name: "Our own model" })).closest("section")!;
    expect(within(card).getByText(/developer workspace not set up/)).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Set up developer workspace" }));
    const dialog = await screen.findByRole("dialog", { name: "Set up our developer workspace?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Set up" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === OPS_OWN_MODEL_DEVELOPER_PATH)).toBe(true),
    );
    const write = calls.find((c) => c.method === "POST" && c.path === OPS_OWN_MODEL_DEVELOPER_PATH)!;
    expect(write.headers["X-Confirm-Action"]).toBe("enable_own_model_developer");
  });

  it("says what is missing and links the next step", async () => {
    renderAdminPage(<VoicesPage />, routes({ [`GET ${OPS_OWN_MODEL_PATH}`]: OWN_MODEL_OFF }));
    const card = (await screen.findByRole("heading", { name: "Our own model" })).closest("section")!;
    expect(within(card).getByText("Not ready")).toBeTruthy();
    expect(within(card).getByText("2 of 5 done")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Open keys" }).getAttribute("href")).toBe(
      "/admin/ops/config?section=credentials",
    );
  });

  it("shows the prompt size the cost floor adds our model at, and where it came from", async () => {
    renderAdminPage(<VoicesPage />, routes({ [`GET ${OPS_OWN_MODEL_PATH}`]: OWN_MODEL_ON }));
    const card = (await screen.findByRole("heading", { name: "Our own model" })).closest("section")!;
    expect(
      within(card).getByText(
        /Cost floor: gemini-2\.5-flash-lite adds ₹0\.3640\/min at 6,150 prompt tokens: the largest of 2 live agents/,
      ),
    ).toBeTruthy();
  });

  it("installs our key for one client behind a step-up confirmation", async () => {
    const tenant = "7f0c2b1e-0000-4000-8000-000000000002";
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({ [`POST ${OPS_OWN_MODEL_ENABLE_PATH}`]: OWN_MODEL_ON }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Install our key for a client now" }));
    const dialog = await screen.findByRole("dialog", { name: "Install our Google key for a client?" });
    fireEvent.change(within(dialog).getByLabelText(/Paying client/), { target: { value: tenant } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Install" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === OPS_OWN_MODEL_ENABLE_PATH)).toBe(true),
    );
    const write = calls.find((c) => c.method === "POST" && c.path === OPS_OWN_MODEL_ENABLE_PATH)!;
    expect(write.headers["X-Confirm-Action"]).toBe("enable_own_model_workspace");
    expect(JSON.parse(write.body!)).toEqual({ tenant_id: tenant });
  });
});
describe("cloning a voice", () => {
  async function openClone(): Promise<HTMLElement> {
    fireEvent.click(await screen.findByRole("button", { name: "Clone a voice" }));
    return screen.findByRole("dialog", { name: "Clone a voice" });
  }

  function fill(dialog: HTMLElement) {
    const sample = new File([new Uint8Array([1, 2, 3])], "me.wav", { type: "audio/wav" });
    fireEvent.change(within(dialog).getByLabelText(/^Recording/), { target: { files: [sample] } });
    fireEvent.change(within(dialog).getByLabelText(/^Name/), { target: { value: "Ravi" } });
  }

  it("cannot be sent until both promises are ticked", async () => {
    renderAdminPage(<VoicesPage />, routes());
    const dialog = await openClone();
    fill(dialog);
    const submit = screen.getByRole("button", { name: "Clone this voice" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /The voice in this recording is mine/ }));
    expect(submit.disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /will not be used to pretend/ }));
    expect(submit.disabled).toBe(false);
  });

  it("sends the recording, the facts, both consents and the step-up confirmation", async () => {
    xhrAnswer = {
      status: 201,
      body: { voice: CLONE, usable_on_agents: true, next_step: "Listen to Ravi, then enable it." },
    };
    renderAdminPage(<VoicesPage />, routes());
    const dialog = await openClone();
    fill(dialog);
    fireEvent.change(within(dialog).getByLabelText(/^Description/), { target: { value: "Warm" } });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /The voice in this recording is mine/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /will not be used to pretend/ }));
    fireEvent.click(screen.getByRole("button", { name: "Clone this voice" }));

    expect(await screen.findByText("Listen to Ravi, then enable it.")).toBeTruthy();
    const sent = xhrCalls[0]!;
    expect(sent.url).toContain(OPS_CLONES_PATH);
    expect(sent.headers["X-Confirm-Action"]).toBe("clone_voice");
    expect(sent.form.get("name")).toBe("Ravi");
    expect(sent.form.get("consent_own_voice")).toBe("true");
    expect(sent.form.get("consent_no_impersonation")).toBe("true");
  });

  it("offers the second-factor prompt when the server asks for it", async () => {
    xhrAnswer = {
      status: 403,
      body: {
        type: "urn:calevate:auth/reauthentication_required",
        title: "Confirm it is still you",
        detail: "This action needs a recent second factor.",
        kind: "auth",
      },
    };
    renderAdminPage(<VoicesPage />, routes());
    const dialog = await openClone();
    fill(dialog);
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /The voice in this recording is mine/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /will not be used to pretend/ }));
    fireEvent.click(screen.getByRole("button", { name: "Clone this voice" }));

    expect(await within(dialog).findByRole("button", { name: "Send me a code" })).toBeTruthy();
  });
});

describe("the filters, as functions", () => {
  it("narrows by tier and hides archived voices by default", () => {
    const list = [voice(), STUDIO, ARCHIVED];
    expect(applyFilters(list, NO_FILTERS).map((v) => v.label)).toEqual(["Anjali", "Meera"]);
    expect(applyFilters(list, { ...NO_FILTERS, tier: "studio" }).map((v) => v.label)).toEqual(["Meera"]);
    expect(applyFilters(list, { ...NO_FILTERS, state: "any" })).toHaveLength(3);
  });

  it("finds a voice by the provider's id or ours, and nothing for an id the platform did not list", () => {
    const list = [voice(), STUDIO];
    expect(findByVoiceId(list, " meera ")?.label).toBe("Meera");
    expect(findByVoiceId(list, "engine:anjali")?.label).toBe("Anjali");
    expect(findByVoiceId(list, "not-there")).toBeNull();
  });

  it("says an engine voice's tag is an accent and an own-key voice's is its language", () => {
    expect(metaLine(voice())).toBe("Telugu accent");
    expect(metaLine(STUDIO)).toBe("Telugu · Feminine");
  });
});

describe("accessibility", () => {
  it("has no axe violations on the hosted screen", async () => {
    const { container } = renderAdminPage(<VoicesPage />, routes());
    await screen.findByRole("listitem", { name: "Anjali" });
    await screen.findByText("Ready");
    await expectNoA11yViolations(container, "admin/ops/voices/page.tsx (hosted)");
  });

  it("has no axe violations in a voice's detail", async () => {
    renderAdminPage(<VoicesPage />, routes({ [HOSTED_VOICES_PROBE_PATH]: hosted({ voices: [PERSON_CLONE] }) }));
    const drawer = await openVoice("Aditya");
    await expectNoA11yViolations(drawer, "admin/ops/voices/hosted/VoiceDrawer.tsx");
  });
});
