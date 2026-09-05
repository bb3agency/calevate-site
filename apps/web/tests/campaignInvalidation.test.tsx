import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { useAttention } from "@/lib/api/attention";
import type { Session } from "@/lib/api/client";
import {
  useAddContacts,
  useCampaigns,
  useDeclareConsentProvenance,
  useLaunchCampaign,
  usePauseCampaign,
} from "@/lib/api/campaigns";

import { stubApi, type ApiCall } from "./harness";

/**
 * WHAT A CAMPAIGN WRITE MUST REFRESH — the sibling reads, not just the one it names.
 *
 * Every defect here is the same shape and it is the one CLAUDE.md's "leave no half-wired
 * feature" is about from the reader's side: the mutation lands, the panel it was fired
 * from updates, and a NUMBER somewhere else on the same screen goes on stating the state
 * before the click. It is worse than a missing refresh, because a stale figure is
 * indistinguishable from a current one — the client has no way to know which they are
 * looking at, and the reasonable reading is that the write did not work.
 *
 * Two sibling reads were being left behind, and neither self-corrects in any useful time:
 *
 * - **`GET /v1/campaigns`** — the list. `CampaignSummaryOut` carries `contacts` (a count)
 *   and `consent_provenance_blocker` (a chip), and `useCampaigns` sets NO
 *   `refetchInterval`, so nothing refetches it until the screen is remounted. Uploading
 *   contacts and answering the provenance question are the two writes that move exactly
 *   those two fields, and they are performed from the same screen the list is on.
 * - **`GET /v1/attention`** — the queue behind the nav bell's count. Its
 *   `stalled_campaigns` source (`apps/api/crm/attention.py`) counts every `paused`
 *   campaign and every `running` one with no `pending` contacts left, so pause, resume,
 *   launch and add-contacts all move that count. It polls at 60s, which means a client
 *   who resumes a campaign watches the badge insist there is still something wrong for
 *   up to a minute after they fixed it.
 *
 * ## Why this drives the hooks rather than the campaigns screen
 *
 * The contract under test is "which cache keys does this mutation invalidate", which is
 * a property of `lib/api/campaigns.ts` and of nothing else — the screen only inherits it.
 * Going through the 2,400-line page would need a full fixture set for facts none of these
 * assertions are about, and would then assert the same thing one indirection further from
 * where it is decided. The seam is still `fetch` (`stubApi`), so what is asserted is the
 * REQUEST the browser makes, exactly as the page-level suites assert it.
 */

const SESSION: Session = { orgSlug: "acme" };
const CAMPAIGN_ID = "0192f0aa-2222-7000-8000-000000000001";

const ATTENTION = { items: [], counts: {}, total: 0 };

/** Every route these hooks can touch, so an unrouted call is a real failure. */
const ROUTES = {
  "/v1/campaigns": [],
  "/v1/attention": ATTENTION,
  [`POST /v1/campaigns/${CAMPAIGN_ID}/contacts`]: { added: 2, rejected: 0, duplicates: 0 },
  [`POST /v1/campaigns/${CAMPAIGN_ID}/consent-provenance`]: {},
  [`POST /v1/campaigns/${CAMPAIGN_ID}/launch`]: { queued: 2 },
  [`POST /v1/campaigns/${CAMPAIGN_ID}/pause`]: {},
  [`POST /v1/campaigns/${CAMPAIGN_ID}/resume`]: {},
  // Read siblings the mutations also refresh. Present so the stub can answer them; the
  // assertions below are only about the two that were being missed.
  [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: { ok: true, blockers: [] },
  [`/v1/campaigns/${CAMPAIGN_ID}/progress`]: { status: "draft", contacts: {} },
};

function countOf(calls: ApiCall[], path: string): number {
  return calls.filter((call) => call.method === "GET" && call.path === path).length;
}

/**
 * Mount the two reads the writes have to refresh, plus one write, and hand the write back.
 *
 * The reads must be MOUNTED for the assertion to mean anything: `invalidateQueries` marks
 * a key stale and refetches only the observers that exist, which is exactly the situation
 * on the real screen — the list and the nav bell are both on it.
 */
function mountWith(
  useWrite: () => { mutate: (input: never) => void },
): { calls: ApiCall[]; fire: (input?: unknown) => Promise<void> } {
  const calls = stubApi(ROUTES);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  let write!: { mutate: (input: never) => void };

  function Probe() {
    useCampaigns(SESSION);
    useAttention(SESSION);
    write = useWrite();
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
    fire: async (input?: unknown) => {
      // Wait for the two reads to land before firing, so the counts below measure the
      // REFETCH and not the first fetch racing the mutation.
      await waitFor(() => expect(countOf(calls, "/v1/campaigns")).toBe(1));
      await waitFor(() => expect(countOf(calls, "/v1/attention")).toBe(1));
      await act(async () => {
        write.mutate(input as never);
      });
    },
  };
}

describe("adding contacts to a campaign", () => {
  it("refreshes the list, whose row carries the contact COUNT it just moved", async () => {
    const { calls, fire } = mountWith(() => useAddContacts(SESSION, CAMPAIGN_ID));
    await fire([{ phone: "+919876543210" }]);
    await waitFor(() => expect(countOf(calls, "/v1/campaigns")).toBe(2));
  });

  it("refreshes the attention queue, which counts a campaign with nothing left to dial", async () => {
    const { calls, fire } = mountWith(() => useAddContacts(SESSION, CAMPAIGN_ID));
    await fire([{ phone: "+919876543210" }]);
    await waitFor(() => expect(countOf(calls, "/v1/attention")).toBe(2));
  });
});

describe("answering the consent provenance question", () => {
  it("refreshes the list, whose row shows the blocker this answer clears", async () => {
    const { calls, fire } = mountWith(() =>
      useDeclareConsentProvenance(SESSION, CAMPAIGN_ID),
    );
    await fire({ source: "website_form", collected_at: "2026-08-09T18:30:00.000Z" });
    await waitFor(() => expect(countOf(calls, "/v1/campaigns")).toBe(2));
  });
});

describe("pausing and resuming", () => {
  it("refreshes the attention queue, where PAUSED is itself an item", async () => {
    const { calls, fire } = mountWith(() => usePauseCampaign(SESSION, CAMPAIGN_ID));
    await fire("pause");
    await waitFor(() => expect(countOf(calls, "/v1/attention")).toBe(2));
  });

  it("refreshes it on the way back out too, so the badge drops when the fix lands", async () => {
    const { calls, fire } = mountWith(() => usePauseCampaign(SESSION, CAMPAIGN_ID));
    await fire("resume");
    await waitFor(() => expect(countOf(calls, "/v1/attention")).toBe(2));
  });
});

describe("launching", () => {
  it("refreshes the attention queue, which only counts running and paused campaigns", async () => {
    const { calls, fire } = mountWith(() => useLaunchCampaign(SESSION, CAMPAIGN_ID));
    await fire();
    await waitFor(() => expect(countOf(calls, "/v1/attention")).toBe(2));
  });
});
