import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import VoicesPage from "@/app/admin/ops/voices/page";
import {
  OPS_CLONES_PATH,
  OPS_HOSTED_PATH,
  OPS_PREVIEW_FETCH_PATH,
  OPS_STUDIO_DISABLE_PATH,
  OPS_STUDIO_ENABLE_PATH,
  OPS_STUDIO_VOICES_PATH,
  type HostedVoice,
  type HostedVoices,
  type StudioVoices,
} from "@/lib/api/opsHostedVoices";
import { OPS_VOICES_PATH, OPS_VOICES_REFRESH_PATH } from "@/lib/api/opsVoices";
import { OPS_PREVIEW_PATH, previewUrl } from "@/lib/api/voicePreview";

import { expectNoA11yViolations } from "./a11y";
import { HOSTED_VOICES_PROBE_PATH, NOT_HOSTED } from "./fixtures/sharedReads";
import { problem, renderAdminPage, type Routes } from "./harness";

/**
 * THE VOICES PAGE ON AN ENGINE THAT HOSTS ITS VOICES (D-687).
 *
 * What this screen must get right, by what each failure costs:
 *
 * 1. **The server picks the screen.** `available: true` shows the hosted screen and never
 *    reads the Pipecat catalogue; `available: false` shows the Pipecat catalogue and never
 *    reads the Studio voices state. The engine is not named in the bundle.
 * 2. **A clone carries both consents and the step-up confirmation**, and cannot be sent
 *    without both boxes ticked.
 * 3. **Deleting a clone with live agents on it is a second, informed decision**: the first
 *    request goes without `confirm`, the server's `voice_clone_in_use` sentence is shown, and
 *    only then is `confirm=true` sent.
 * 4. **Every offered voice can be given a preview**: generate for a Studio voice or a clone,
 *    upload for a stock platform voice, and play through the admin route.
 * 5. **Studio voices are switched on and off behind a confirmation** carrying its step-up
 *    header, and switching off with Studio agents live is a second, informed decision.
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
    label: "Anjali",
    source: "engine",
    rung: "clear",
    band: "premium",
    sold: true,
    not_sold_reason: null,
    is_custom: false,
    accent: "Telugu",
    description: "Warm and calm",
    language_note: "Speaks Telugu, Hindi and English.",
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
    ...over,
  };
}

const CLONE = voice({
  voice_id: "engine:clone-ravi",
  label: "Ravi",
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
  label: "Kavya",
  preview_available: false,
  preview_source: null,
});

const STUDIO = voice({
  voice_id: "byok:meera",
  label: "Meera",
  source: "byok",
  rung: "studio",
  band: null,
  preview_available: false,
  preview_source: null,
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
  "Switching it on would move every agent that is not set to stay on the platform's own voices onto Cartesia at the Studio rate, so every published Clear agent is set to stay off it first.";

const STUDIO_ON: StudioVoices = {
  ready: true,
  cartesia_key_configured: true,
  live_studio_agents: 2,
  explanation: EXPLANATION,
  note: "On: Studio agents speak on our Cartesia key; Clear agents stay off it.",
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
  live_studio_agents: 0,
  note: "Off: our Cartesia key is not installed in the workspace yet.",
  key: {
    enabled: false,
    scope: null,
    complete: false,
    using: "none",
    voice_provider: null,
    speaks_on_own_voice: false,
  },
};

function routes(over: Routes = {}): Routes {
  return {
    [ADMIN_ME_PATH]: SUPERADMIN,
    [HOSTED_VOICES_PROBE_PATH]: hosted(),
    [OPS_STUDIO_VOICES_PATH]: STUDIO_ON,
    ...over,
  };
}

function card(label: string): HTMLElement {
  return screen.getByRole("listitem", { name: label });
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
  it("shows the hosted screen and never reads the Pipecat catalogue", async () => {
    const { calls } = renderAdminPage(<VoicesPage />, routes());

    await screen.findByRole("tab", { name: "Clear" });
    expect(screen.getByRole("listitem", { name: "Anjali" })).toBeTruthy();
    expect(calls.some((c) => c.path.startsWith(`${OPS_VOICES_PATH}?`))).toBe(false);
    // The Clear tab lists the Clear rung only.
    expect(screen.queryByRole("listitem", { name: "Meera" })).toBeNull();
  });

  it("shows the Pipecat catalogue and never reads the Studio voices when voices are not hosted", async () => {
    const { calls } = renderAdminPage(<VoicesPage />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      [HOSTED_VOICES_PROBE_PATH]: NOT_HOSTED,
      [`${OPS_VOICES_PATH}?scope=decided`]: {
        voices: [],
        source: "engine",
        offered: 0,
        scope: "decided",
        cached: 0,
        note: "Nothing is offered.",
        form: { providers: [], languages: ["te-IN"] },
      },
    });

    await screen.findByText(/No voice has been added yet/);
    expect(screen.queryByRole("tab", { name: "Clear" })).toBeNull();
    expect(calls.some((c) => c.path === OPS_STUDIO_VOICES_PATH)).toBe(false);
  });

  it("renders a failed probe as a refusal, not as either screen", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({ [HOSTED_VOICES_PROBE_PATH]: problem(503, { title: "Upstream unavailable", kind: "unavailable" }) }),
    );
    expect(await screen.findByText(/Upstream unavailable/)).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "Clear" })).toBeNull();
  });
});

describe("the hosted voices", () => {
  it("lists Studio voices on the Studio tab and reads every voice only when asked", async () => {
    const all = `${OPS_HOSTED_PATH}?scope=all`;
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [all]: hosted({
          scope: "all",
          voices: [voice(), voice({ voice_id: "engine:new", label: "Newly synced", added: false, state: "disabled", offered: false })],
        }),
      }),
    );

    fireEvent.click(await screen.findByRole("tab", { name: "Studio" }));
    expect(await screen.findByRole("listitem", { name: "Meera" })).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "Anjali" })).toBeNull();
    expect(calls.some((c) => c.path === all)).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: "Every voice on the platform" }));
    expect(await screen.findByRole("listitem", { name: "Newly synced" })).toBeTruthy();
    expect(calls.some((c) => c.path === all)).toBe(true);
  });

  it("adds a voice that is not added yet", async () => {
    const all = `${OPS_HOSTED_PATH}?scope=all`;
    const fresh = voice({ voice_id: "engine:new", label: "Newly synced", added: false, state: "disabled", offered: false });
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [all]: hosted({ scope: "all", voices: [fresh] }),
        [`POST ${OPS_HOSTED_PATH}`]: { voice: { ...fresh, added: true }, next_step: "Give it a preview, then enable it." },
      }),
    );

    fireEvent.click(await screen.findByRole("tab", { name: "Every voice on the platform" }));
    await screen.findByRole("listitem", { name: "Newly synced" });
    fireEvent.click(within(card("Newly synced")).getByRole("button", { name: "Add Newly synced" }));

    await screen.findByText("Give it a preview, then enable it.");
    const write = calls.find((c) => c.method === "POST" && c.path === OPS_HOSTED_PATH)!;
    expect(JSON.parse(write.body!)).toEqual({ voice_id: "engine:new" });
  });

  it("shows every band with a badge and will not add a voice outside the Studio band", async () => {
    const all = `${OPS_HOSTED_PATH}?scope=all`;
    const premium = voice({
      voice_id: "engine:priya",
      label: "Priya",
      rung: null,
      band: "standard",
      sold: false,
      not_sold_reason: "Only Premium-tier voices are sold as Clear on this platform, and Priya is in the Standard tier.",
      added: false,
      state: "disabled",
      offered: false,
    });
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({ [all]: hosted({ scope: "all", voices: [voice(), premium] }) }),
    );

    fireEvent.click(await screen.findByRole("tab", { name: "Every voice on the platform" }));
    const row = within(await screen.findByRole("listitem", { name: "Priya" }));
    expect(row.getByText("Standard tier")).toBeTruthy();
    expect(row.queryByText("Clear")).toBeNull();
    const add = row.getByRole("button", { name: "Add Priya" }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    expect(row.getByText(/Priya is in the Standard tier/)).toBeTruthy();
    expect(within(card("Anjali")).getByText("Premium tier")).toBeTruthy();
    expect(
      screen.getByText(/Tiers on the platform: 3 Standard · 1 Premium · 2 Studio/),
    ).toBeTruthy();
    fireEvent.click(add);
    expect(calls.some((c) => c.method === "POST" && c.path === OPS_HOSTED_PATH)).toBe(false);
  });

  it("explains plainly when the platform lists none of the tier sold as Clear", async () => {
    const sentence =
      "ThinnestAI listed 4 voice(s) but none in the Premium tier, the tier sold as Clear ('Voice band sold as Clear' in the ops console). Check the account on ThinnestAI, then refresh.";
    renderAdminPage(
      <VoicesPage />,
      routes({
        [HOSTED_VOICES_PROBE_PATH]: hosted({
          voices: [],
          bands: { standard: 3, studio: 1 },
          plan_note: sentence,
        }),
      }),
    );

    expect(await screen.findByText("No Premium-tier voices on the voice platform")).toBeTruthy();
    expect(screen.getByText(sentence)).toBeTruthy();
    expect(screen.queryByText(/not the Studio voices switch below/)).toBeNull();
  });

  it("on the Studio tier, says the Cartesia switch adds no voice to it", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [HOSTED_VOICES_PROBE_PATH]: hosted({
          voices: [],
          clear_band: "studio",
          bands: { standard: 3, premium: 4 },
          plan_note: "ThinnestAI listed 7 voice(s) but none in the Studio tier.",
        }),
      }),
    );

    expect(await screen.findByText("No Studio-tier voices on the voice platform")).toBeTruthy();
    expect(screen.getByText(/not the Studio voices switch below: that switch is our Cartesia key/)).toBeTruthy();
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

  it("switches a voice on for clients with one PATCH naming the voice and the state", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`PATCH ${OPS_HOSTED_PATH}`]: { voice: { ...CLONE, state: "enabled" }, next_step: "Clients can choose Ravi now." },
      }),
    );

    await screen.findByRole("listitem", { name: "Ravi" });
    const toggle = within(card("Ravi")).getByRole("switch", { name: /Offered to clients/ }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    fireEvent.click(toggle);

    await screen.findByText("Clients can choose Ravi now.");
    const write = calls.find((c) => c.method === "PATCH" && c.path === OPS_HOSTED_PATH)!;
    expect(JSON.parse(write.body!)).toEqual({ voice_id: "engine:clone-ravi", state: "enabled" });
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
    fireEvent.click(within(card("Anjali")).getByRole("button", { name: "Play the preview of Anjali" }));
    await waitFor(() => expect(play).toHaveBeenCalled());
    expect(calls.some((c) => c.path === clip)).toBe(true);
  });

  it("generates a preview for a clone and uploads one for a stock voice", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`POST ${OPS_PREVIEW_FETCH_PATH}`]: { voice: { ...CLONE, preview_available: true }, next_step: "Stored." },
      }),
    );

    await screen.findByRole("listitem", { name: "Ravi" });
    // A clone has the platform's own preview to fetch, and no upload control.
    expect(within(card("Ravi")).queryByRole("button", { name: /Upload preview/ })).toBeNull();
    fireEvent.click(within(card("Ravi")).getByRole("button", { name: "Generate preview" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === OPS_PREVIEW_FETCH_PATH)).toBe(true),
    );
    const fetchWrite = calls.find((c) => c.path === OPS_PREVIEW_FETCH_PATH)!;
    expect(JSON.parse(fetchWrite.body!)).toEqual({ voice_id: "engine:clone-ravi" });

    // A stock voice with no sample is given one by upload.
    xhrAnswer = { status: 200, body: { voice: { ...STOCK_NO_PREVIEW, preview_available: true }, next_step: "Stored." } };
    const input = within(card("Kavya")).getByLabelText(/Upload a preview clip for Kavya/) as HTMLInputElement;
    const clipFile = new File([new Uint8Array([1, 2])], "kavya.mp3", { type: "audio/mpeg" });
    await act(async () => {
      fireEvent.change(input, { target: { files: [clipFile] } });
    });
    await waitFor(() => expect(xhrCalls).toHaveLength(1));
    expect(xhrCalls[0]!.url).toContain("/v1/ops/voices/hosted/preview");
    expect(xhrCalls[0]!.form.get("voice_id")).toBe("engine:kavya");
    expect(xhrCalls[0]!.form.get("sample")).toBeInstanceOf(File);
  });

  it("refuses a preview clip over 2 MB before sending it", async () => {
    renderAdminPage(<VoicesPage />, routes());
    await screen.findByRole("listitem", { name: "Kavya" });
    const input = within(card("Kavya")).getByLabelText(/Upload a preview clip for Kavya/) as HTMLInputElement;
    const big = new File([new Uint8Array(2 * 1024 * 1024 + 1)], "big.wav", { type: "audio/wav" });
    fireEvent.change(input, { target: { files: [big] } });
    expect(await screen.findByText(/larger than 2 MB/)).toBeTruthy();
    expect(xhrCalls).toHaveLength(0);
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
          next_step: "Republish the two agents to pick their new voice.",
        },
      }),
    );

    await screen.findByRole("listitem", { name: "Ravi" });
    fireEvent.click(within(card("Ravi")).getByRole("button", { name: "Delete the clone Ravi" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete the clone Ravi?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete clone" }));

    expect(await within(dialog).findByText(inUse)).toBeTruthy();
    expect(attempt).toBe(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete and move those agents" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const deletes = calls.filter((c) => c.method === "DELETE");
    expect(deletes.map((c) => c.path.endsWith("confirm=true"))).toEqual([false, true]);
    expect(deletes[1]!.headers["X-Confirm-Action"]).toBe("delete_voice_clone:engine:clone-ravi");
  });
});

describe("the Studio voices card", () => {
  it("says Studio voices are off and switches them on behind a step-up confirmation", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`GET ${OPS_STUDIO_VOICES_PATH}`]: STUDIO_OFF,
        [`POST ${OPS_STUDIO_ENABLE_PATH}`]: STUDIO_ON,
      }),
    );

    expect(await screen.findByText(/Off — Studio voices cannot be offered/)).toBeTruthy();
    expect(screen.getByText(STUDIO_OFF.note)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Enable Studio voices" }));
    const dialog = await screen.findByRole("dialog", { name: "Enable Studio voices?" });
    expect(within(dialog).getByText(EXPLANATION)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Enable Studio voices" }));

    await screen.findByText(/On — Studio voices can be offered/);
    const write = calls.find((c) => c.method === "POST" && c.path === OPS_STUDIO_ENABLE_PATH)!;
    expect(write.headers["X-Confirm-Action"]).toBe("enable_studio_voices");
    expect(JSON.parse(write.body!)).toEqual({});
  });

  it("renders the server's refusal inside the dialog", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [`GET ${OPS_STUDIO_VOICES_PATH}`]: STUDIO_OFF,
        [`POST ${OPS_STUDIO_ENABLE_PATH}`]: problem(409, {
          type: "urn:calevate:conflict/studio_agents_not_kept_off",
          title: "Studio voices were not switched on",
          detail: "1 published agent(s) could not be confirmed as staying on the voice platform's own voices.",
          kind: "conflict",
        }),
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Enable Studio voices" }));
    const dialog = await screen.findByRole("dialog", { name: "Enable Studio voices?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Enable Studio voices" }));
    expect(await within(dialog).findByText(/could not be confirmed as staying/)).toBeTruthy();
  });

  it("asks again with the server's words before switching off under live Studio agents", async () => {
    const inUse = problem(409, {
      type: "urn:calevate:conflict/studio_voices_in_use",
      title: "Published agents are speaking Studio voices",
      detail: "2 published agent(s) speak a Studio voice.",
      kind: "conflict",
    });
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [`POST ${OPS_STUDIO_DISABLE_PATH}?confirm=false`]: inUse,
        [`POST ${OPS_STUDIO_DISABLE_PATH}?confirm=true`]: STUDIO_OFF,
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Turn off Studio voices" }));
    const dialog = await screen.findByRole("dialog", { name: "Turn off Studio voices?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Turn off Studio voices" }));
    expect(await within(dialog).findByText(/2 published agent\(s\) speak a Studio voice/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Turn off and move those agents" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual([
        `${OPS_STUDIO_DISABLE_PATH}?confirm=false`,
        `${OPS_STUDIO_DISABLE_PATH}?confirm=true`,
      ]),
    );
    expect(calls.find((c) => c.method === "POST")!.headers["X-Confirm-Action"]).toBe(
      "disable_studio_voices",
    );
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
    expect(sent.form.get("description")).toBe("Warm");
    expect(sent.form.get("language")).toBe("te-IN");
    expect(sent.form.get("remove_noise")).toBe("true");
    expect(sent.form.get("consent_own_voice")).toBe("true");
    expect(sent.form.get("consent_no_impersonation")).toBe("true");
    expect(sent.form.get("sample")).toBeInstanceOf(File);
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

describe("accessibility", () => {
  it("has no axe violations on the hosted screen", async () => {
    const { container } = renderAdminPage(<VoicesPage />, routes());
    await screen.findByRole("listitem", { name: "Anjali" });
    await screen.findByText(/On — Studio voices can be offered/);
    await expectNoA11yViolations(container, "admin/ops/voices/page.tsx (hosted)");
  });
});
