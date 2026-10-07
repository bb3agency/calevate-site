import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClientEngineCatalogue } from "@/components/engineCatalogueList";
import { ENGINE_CATALOGUE_PATH, type EngineCatalogue } from "@/lib/api/engineCatalogue";
import { useClientSession } from "@/lib/api/session";

import { agentRow } from "./fixtures/sharedReads";
import { problem, renderClientPage } from "./harness";

/*
 * The client's own picker for the voice platform's voices and models (D-678): the saved
 * choice is pre-selected, an entry the server marks unavailable cannot be picked, only the
 * field that moved is sent, and a refusal arrives in the server's own words.
 */

const AGENT = "0192f0aa-8888-7000-8000-0000000000c3";
const AGENT_PATH = `/v1/agents/${AGENT}`;

const CATALOGUE: EngineCatalogue = {
  available: true,
  complete: true,
  choosable: true,
  note: "2 of 3 voices can be chosen today.",
  voices: [
    { voice_id: "3b7e", label: "Anjali", price_band: "standard", is_custom: false, offerable: true, reason: null },
    { voice_id: "kiran", label: "Kiran", price_band: "standard", is_custom: false, offerable: true, reason: null },
    {
      voice_id: "priya",
      label: "Priya",
      price_band: "premium",
      is_custom: false,
      offerable: false,
      reason: "Not available yet: premium voices have not been priced.",
    },
  ],
  models: [
    { model_id: "m_6f1c2a9e0b7d4c35", label: "Standard", call_capable: true, plan_allows: true, offerable: true, reason: null },
  ],
};

function Picker() {
  return <ClientEngineCatalogue session={useClientSession()} agentId={AGENT} />;
}

describe("the platform voice picker", () => {
  it("starts on the saved voice and sends only the voice that moved", async () => {
    const { calls } = await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: CATALOGUE,
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT, engine_voice_id: "3b7e" }),
      [`PATCH ${AGENT_PATH}`]: agentRow({ id: AGENT, engine_voice_id: "kiran" }),
    });

    const anjali = (await screen.findByRole("radio", { name: /Anjali/ })) as HTMLInputElement;
    await waitFor(() => expect(anjali.checked).toBe(true));
    expect((screen.getByRole("radio", { name: /Priya/ }) as HTMLInputElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("radio", { name: /Kiran/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save voice and model" }));

    await waitFor(() =>
      expect(calls.some((c) => c.path === AGENT_PATH && c.method === "PATCH")).toBe(true),
    );
    const write = calls.find((c) => c.path === AGENT_PATH && c.method === "PATCH")!;
    expect(JSON.parse(write.body!)).toEqual({ engine_voice_id: "kiran" });
  });

  it("puts the server's refusal on screen", async () => {
    await renderClientPage(<Picker />, {
      [ENGINE_CATALOGUE_PATH]: CATALOGUE,
      [`GET ${AGENT_PATH}`]: agentRow({ id: AGENT, engine_voice_id: "3b7e" }),
      [`PATCH ${AGENT_PATH}`]: problem(422, {
        type: "urn:calevate:business_rule/engine_choice_reset_unsupported",
        title: "This agent's voice cannot be put back to the default",
        detail:
          "The voice platform keeps the last voice it was given and offers no way to return to its default, so clearing the choice would not change what callers hear.",
        kind: "business_rule",
      }),
    });

    const defaults = await screen.findAllByRole("radio", { name: /Platform default/ });
    await waitFor(() =>
      expect((screen.getByRole("radio", { name: /Anjali/ }) as HTMLInputElement).checked).toBe(true),
    );
    fireEvent.click(defaults[0]!);
    fireEvent.click(screen.getByRole("button", { name: "Save voice and model" }));

    await screen.findByText(/keeps the last voice it was given/);
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
    expect(
      (screen.getByRole("button", { name: "Save voice and model" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
