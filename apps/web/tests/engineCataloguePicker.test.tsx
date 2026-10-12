import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useQuery } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ClientEngineVoices, EngineModelList } from "@/components/engineCatalogueList";
import { apiRequest } from "@/lib/api/client";
import { ENGINE_CATALOGUE_PATH, type EngineCatalogue } from "@/lib/api/engineCatalogue";
import { useClientSession } from "@/lib/api/session";
import { CLIENT_PREVIEW_PATH, previewUrl } from "@/lib/api/voicePreview";

import { agentRow } from "./fixtures/sharedReads";
import { problem, renderClientPage } from "./harness";

/*
 * The client's own picker for the voices an operator added and enabled (D-678, D-687): the
 * voices are grouped by rung, the saved choice is pre-selected and marked in use, an entry
 * the server marks unavailable cannot be picked, a Studio voice and a model that cannot run
 * beside it block each other with a reason, each voice can be previewed before choosing,
 * only the field that moved is sent, and a refusal arrives in the server's own words.
 */

const AGENT = "0192f0aa-8888-7000-8000-0000000000c3";
const AGENT_PATH = `/v1/agents/${AGENT}`;

const CATALOGUE: EngineCatalogue = {
  available: true,
  complete: true,
  choosable: true,
  studio_available: true,
  note: "3 of 4 voices can be chosen today.",
  voices: [
    {
      voice_id: "engine:3b7e",
      label: "Anjali",
      rung: "clear",
      language_note: "Speaks Telugu, Hindi and English.",
      preview_available: true,
      is_custom: false,
      offerable: true,
      reason: null,
    },
    {
      voice_id: "engine:kiran",
      label: "Kiran",
      rung: "clear",
      language_note: "Speaks Telugu.",
      preview_available: false,
      is_custom: true,
      offerable: true,
      reason: null,
    },
    {
      voice_id: "engine:priya",
      label: "Priya",
      rung: "clear",
      language_note: "Speaks Hindi.",
      preview_available: false,
      is_custom: false,
      offerable: false,
      reason: "Not available yet: this voice has not been priced.",
    },
    {
      voice_id: "byok:meera",
      label: "Meera",
      rung: "studio",
      language_note: "Speaks English.",
      preview_available: false,
      is_custom: false,
      offerable: true,
      reason: null,
    },
  ],
  models: [
    {
      model_id: "m_fast",
      label: "Standard",
      call_capable: true,
      plan_allows: true,
      offerable: true,
      reason: null,
      usable_with_studio_voice: true,
      band_disagrees: false,
    },
    {
      model_id: "m_rich",
      label: "Rich",
      call_capable: true,
      plan_allows: true,
      offerable: true,
      reason: null,
      usable_with_studio_voice: false,
      band_disagrees: false,
    },
  ],
};

function Picker() {
  return <ClientEngineVoices session={useClientSession()} agentId={AGENT} />;
}

describe("the platform voice picker", () => {
  it("starts on the saved voice and sends only the voice that moved", async () => {
    const { calls } = await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: CATALOGUE,
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT, engine_voice_id: "engine:3b7e" }),
      [`PATCH ${AGENT_PATH}`]: agentRow({ id: AGENT, engine_voice_id: "engine:kiran" }),
    });

    const anjali = (await screen.findByRole("radio", { name: /Anjali/ })) as HTMLInputElement;
    await waitFor(() => expect(anjali.checked).toBe(true));
    expect(screen.getByRole("radio", { name: /Anjali/ }).closest("div")?.textContent).toContain("In use");
    expect((screen.getByRole("radio", { name: /Priya/ }) as HTMLInputElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("radio", { name: /Kiran/ }));
    fireEvent.click(screen.getByRole("button", { name: "Use this voice" }));

    await waitFor(() =>
      expect(calls.some((c) => c.path === AGENT_PATH && c.method === "PATCH")).toBe(true),
    );
    const write = calls.find((c) => c.path === AGENT_PATH && c.method === "PATCH")!;
    expect(JSON.parse(write.body!)).toEqual({ engine_voice_id: "engine:kiran" });
  });

  it("groups the voices by rung, Clear before Studio", async () => {
    await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: CATALOGUE,
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT }),
    });

    const clear = await screen.findByRole("group", { name: "Clear voices" });
    const studio = screen.getByRole("group", { name: "Studio voices" });
    expect(within(clear).getByRole("radio", { name: /Anjali/ })).toBeTruthy();
    expect(within(clear).queryByRole("radio", { name: /Meera/ })).toBeNull();
    expect(within(studio).getByRole("radio", { name: /Meera/ })).toBeTruthy();
    // Clear is read first.
    expect(clear.compareDocumentPosition(studio) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("explains Studio rather than listing it when the account cannot have it", async () => {
    await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: {
        ...CATALOGUE,
        studio_available: false,
        voices: CATALOGUE.voices.filter((voice) => voice.rung === "clear"),
      },
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT }),
    });

    await screen.findByRole("radio", { name: /Anjali/ });
    expect(screen.queryByRole("group", { name: "Studio voices" })).toBeNull();
  });

  it("disables Studio voices while the chosen model cannot run with one, and says why", async () => {
    await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: CATALOGUE,
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT, engine_model_id: "m_rich" }),
    });

    const meera = (await screen.findByRole("radio", { name: /Meera/ })) as HTMLInputElement;
    await waitFor(() => expect(meera.disabled).toBe(true));
    expect(meera.closest("div")?.textContent).toContain("Not available with the model this agent runs on");
    expect(meera.closest("div")?.textContent).not.toContain("Rich");
    // A client is never shown the models themselves (D-679).
    expect(screen.queryByRole("radio", { name: /^Rich/ })).toBeNull();
    expect(screen.queryByRole("radio", { name: /^Standard/ })).toBeNull();
  });

  it("puts the server's refusal on screen", async () => {
    await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: CATALOGUE,
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT, engine_voice_id: "engine:3b7e" }),
      [`PATCH ${AGENT_PATH}`]: problem(422, {
        type: "urn:calevate:business_rule/engine_voice_not_on_offer",
        title: "That voice is not on offer",
        detail: "This voice is not on offer to your account any more. Choose another voice.",
        kind: "business_rule",
      }),
    });

    await waitFor(() =>
      expect((screen.getByRole("radio", { name: /Anjali/ }) as HTMLInputElement).checked).toBe(true),
    );
    fireEvent.click(screen.getByRole("radio", { name: /Kiran/ }));
    fireEvent.click(screen.getByRole("button", { name: "Use this voice" }));

    await screen.findByText(/not on offer to your account any more/);
  });
});

describe("the voice preview", () => {
  const play = vi.fn(() => Promise.resolve());
  const pause = vi.fn();

  beforeEach(() => {
    Object.defineProperty(HTMLMediaElement.prototype, "play", { configurable: true, value: play });
    Object.defineProperty(HTMLMediaElement.prototype, "pause", { configurable: true, value: pause });
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:preview"),
      revokeObjectURL: vi.fn(),
    });
    play.mockClear();
    pause.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reads the clip through the client's own session only when asked, then plays it", async () => {
    const clipPath = previewUrl(CLIENT_PREVIEW_PATH, "engine:3b7e");
    const { calls } = await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: CATALOGUE,
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT }),
      [clipPath]: () =>
        new Response(new Uint8Array([1, 2, 3]), { status: 200, headers: { "content-type": "audio/mpeg" } }),
    });

    const button = await screen.findByRole("button", { name: "Play the preview of Anjali" });
    // Nothing is downloaded until somebody presses play.
    expect(calls.some((c) => c.path === clipPath)).toBe(false);
    // Only voices with a stored clip get a button.
    expect(screen.queryByRole("button", { name: /preview of Kiran/ })).toBeNull();

    fireEvent.click(button);
    await waitFor(() => expect(play).toHaveBeenCalled());
    const read = calls.find((c) => c.path === clipPath)!;
    expect(read.headers["X-Org-Slug"]).toBe("acme");
    expect(URL.createObjectURL).toHaveBeenCalled();
    // Pressing play never moves the selection.
    expect((screen.getByRole("radio", { name: /Anjali/ }) as HTMLInputElement).checked).toBe(false);
  });

  it("says plainly when a voice has no stored clip", async () => {
    const clipPath = previewUrl(CLIENT_PREVIEW_PATH, "engine:3b7e");
    await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: CATALOGUE,
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT }),
      [clipPath]: problem(404, { title: "Not found", detail: "Voice preview was not found.", kind: "not_found" }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Play the preview of Anjali" }));
    await screen.findByText("No preview is stored for this voice yet.");
    expect(play).not.toHaveBeenCalled();
  });
});

describe("the platform voice picker on an account running its own keys", () => {
  it("is locked with the server's reason", async () => {
    const note =
      "This account's voice platform runs on the account's own speech, model and voice keys, so the voice and the language model are set once for the whole account and cannot be chosen per agent.";
    await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: { ...CATALOGUE, choosable: false, choice_note: note },
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT }),
    });

    await screen.findByText(note);
    for (const radio of screen.getAllByRole("radio")) {
      expect((radio as HTMLInputElement).disabled).toBe(true);
    }
    // Nothing can be picked, so no save is ever offered.
    expect(screen.queryByRole("button", { name: "Use this voice" })).toBeNull();
  });
});

describe("the platform model list, for an operator", () => {
  function Models({ voiceId }: { voiceId: string | null }) {
    const session = useClientSession();
    const catalogue = useQuery({
      queryKey: ["engine-catalogue", "test"],
      queryFn: () => apiRequest<EngineCatalogue>(session, ENGINE_CATALOGUE_PATH),
    });
    return <EngineModelList catalogue={catalogue} voiceId={voiceId} modelId={null} />;
  }

  it("lists every model on a Clear voice, each with its maker's mark or a monogram", async () => {
    const { container } = await renderClientPage(<Models voiceId="engine:3b7e" />, {
      [ENGINE_CATALOGUE_PATH]: {
        ...CATALOGUE,
        models: [
          ...CATALOGUE.models,
          { ...CATALOGUE.models[0], model_id: "m_gpt", label: "GPT-5 Nano", price_band: "none", latency_ms: 915 },
        ],
      },
    });

    await screen.findByText("GPT-5 Nano");
    expect(screen.getByText("Rich")).toBeTruthy();
    expect(screen.queryByText(/More models are available/)).toBeNull();
    const makers = [...container.querySelectorAll("[data-model-maker]")].map((n) =>
      n.getAttribute("data-model-maker"),
    );
    expect(makers).toContain("OpenAI");
    expect(makers).toContain("unknown");
    expect(container.textContent).toContain("No extra charge · replies in about 915 ms");
    expect(container.textContent).toContain("Not checked yet");
  });

  it("lists only the models a Studio voice can run with, and says more exist, quietly", async () => {
    const { container } = await renderClientPage(<Models voiceId="byok:meera" />, {
      [ENGINE_CATALOGUE_PATH]: CATALOGUE,
    });

    await screen.findByText("Standard");
    expect(screen.queryByText("Rich")).toBeNull();
    expect(screen.getByText(/More models are available with a Clear voice/)).toBeTruthy();
    expect(container.textContent).not.toMatch(/cannot be used/i);
    expect(container.querySelector(".text-warn")).toBeNull();
  });
});
