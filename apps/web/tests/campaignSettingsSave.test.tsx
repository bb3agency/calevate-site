import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import type { Session } from "@/lib/api/client";
import { useCampaignSettings, useSaveCampaignSettings } from "@/lib/api/campaignWorkspace";

import { problem, stubApi, type ApiCall } from "./harness";

/**
 * The campaign's script language is stored before it is put on a running campaign's calls,
 * so a refused put-live ("Saved, but not on its calls yet") still changed what the server
 * holds. The language picker reads the settings, so they are read again after a refusal
 * too, or the picker keeps showing the language from before the save.
 */

const SESSION: Session = { orgSlug: "acme" };
const CAMPAIGN_ID = "0192f0aa-2222-7000-8000-000000000009";
const AGENT_ID = "0192f0aa-2222-7000-8000-00000000000a";
const PATH = `/v1/campaigns/${CAMPAIGN_ID}/settings`;

const SETTINGS = {
  agent_id: AGENT_ID,
  agent_name: "Asha",
  defaults: { language_primary: "te-IN", languages_extra: [] },
  overrides: {},
  applied_now: true,
  offered_languages: ["te-IN", "hi-IN", "en-IN"],
};

function reads(calls: ApiCall[]): number {
  return calls.filter((call) => call.method === "GET" && call.path === PATH).length;
}

function mount(answer: unknown): { calls: ApiCall[]; save: () => Promise<void> } {
  const calls = stubApi({ [PATH]: SETTINGS, [`PUT ${PATH}`]: answer });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  let mutate!: (input: { language_primary: string }) => void;
  function Probe() {
    useCampaignSettings(SESSION, CAMPAIGN_ID, AGENT_ID);
    mutate = useSaveCampaignSettings(SESSION, CAMPAIGN_ID).mutate;
    return null;
  }
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  render(
    <Wrapper>
      <Probe />
    </Wrapper>,
  );
  return {
    calls,
    save: async () => {
      await waitFor(() => expect(reads(calls)).toBe(1));
      await act(async () => {
        mutate({ language_primary: "hi-IN" });
      });
    },
  };
}

describe("saving a campaign's script language", () => {
  it("reads the settings again after a save", async () => {
    const { calls, save } = mount({ ...SETTINGS, overrides: { language_primary: "hi-IN" } });
    await save();
    await waitFor(() => expect(reads(calls)).toBe(2));
  });

  it("reads them again after a refused put-live too, which kept the change", async () => {
    const { calls, save } = mount(
      problem(409, {
        type: "https://calevate.tech/problems/engine_agent_allowance_used",
        title: "Saved, but not on its calls yet",
        status: 409,
      }),
    );
    await save();
    await waitFor(() => expect(reads(calls)).toBe(2));
  });
});
