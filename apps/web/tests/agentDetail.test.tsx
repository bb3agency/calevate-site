import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentDetailPage from "@/app/c/[slug]/agents/[agentId]/page";
import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import { ToastProvider } from "@/components/arc/toast";
import { TOUR_STEPS } from "@/app/c/[slug]/agents/[agentId]/tour/tourModel";
import type { Agent } from "@/lib/api/agents";
import { ENGINE_CATALOGUE_PATH } from "@/lib/api/engineCatalogue";
import type { PendingState } from "@/lib/api/publishing";
import { EMPTY_SCRIPT } from "@/lib/api/script";
import { useCopilotSurfaceHolder, type SurfaceHolder } from "@/lib/copilot/registry";

import { problem, renderClientPage, stillLoading } from "./harness";
import { businessProfileFixture } from "./businessProfileFixture";
import {
  AGENT_SPEND_PATH,
  LANES,
  agentCallHandling,
  organizationCallHandling,
  teamAlertReads,
  agentJobs,
  agentReadiness,
  clientVoiceTuning,
  LEGAL_READY,
  clientLlmTiers,
  prepaidWallet,
  spendThisMonth,
  noVoiceNotes,
} from "./fixtures/sharedReads";
import { operatorEngineCatalogue } from "./fixtures/engineCatalogue";

/*
 * THE AGENT PAGE IS SEVEN TABS (D-825): one tab is mounted at a time, chosen by
 * `?section=`. Each describe below opens the tab that owns its subject; the default is
 * Overview, which is also what a real visit opens first. Old section ids still open the tab
 * that holds their content now (`LEGACY_SECTIONS`).
 */
const nav = vi.hoisted(() => ({ params: new URLSearchParams(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  usePathname: () => "/c/acme/agents/agent-1",
  useRouter: () => ({
    push: nav.push,
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));
function openSection(id: string) {
  nav.params = new URLSearchParams(`section=${id}`);
}
beforeEach(() => {
  nav.params = new URLSearchParams();
  nav.push.mockClear();
});

/**
 * ONE agent's screen — where a client checks what their phone line is saying, changes what
 * it announces, teaches it, and takes it on or off the frontline.
 *
 * Six things can be wrong here, in falling order of what a wrong render costs:
 *
 * 1. **The staged script shown as the live one.** `agents/publishing.py` opens by
 *    recording that the BACKEND shipped this inversion once already, in both directions at
 *    once. Here the same mistake tells an owner that callers are hearing a script nobody
 *    approved — or that an approved fix has landed when it has not. The pointers are
 *    rendered as labelled data, and the tests read the two labels' own values.
 * 2. **A compliance sentence the server does not enforce.** The truthful-answer guarantee
 *    is the server's words, rendered verbatim and ABOVE the switches; the two notice lines
 *    are quoted and not editable. A screen that paraphrased any of it could promise the
 *    opposite of what the platform enforces.
 * 3. **A lifecycle button the server would refuse.** `movesFor` mirrors
 *    `lifecycle.AGENT_TRANSITIONS`, so an archived agent is offered a restore and nothing
 *    else, and a live one is never offered "switch on".
 * 4. **A number this build invented.** The call cap and the worst-case cost are the
 *    server's or are not shown — and `null` cost means "we cannot say", never ₹0.
 * 5. **A control that could only 403.** Apply, Undo and the cap editor are admin-realm and
 *    must not exist here.
 * 6. **An edit that sends more than it moved.** Both the disclosure PATCH and the details
 *    PATCH treat an omitted field as "leave it alone"; sending all of them makes one click
 *    a read-modify-write race against another.
 */

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  // The full client-owner set (core/rbac.py). `agents:write` is NOT in it and cannot be:
  // it is admin-realm only. `org:manage` is what D-440's lifecycle routes require.
  permissions: [
    "agents:read",
    "calls:read",
    "leads:read",
    "billing:read",
    "org:read",
    "org:manage",
    "kb:write",
  ],
  impersonating: false,
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: "agent-1",
    name: "Reception",
    direction: "inbound",
    status: "live",
    archived_at: null,
    language_primary: "te-IN",
    reply_languages: ["te-IN"],
    disclosure_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    // D-163: the two notices this agent volunteers, and the switch on each. Both ON by
    // default — that is what a new agent is born with. `opening_line` is the SERVER's
    // composition and is passed as data rather than derived here: the screen renders it
    // verbatim, so a fixture that joined the two sentences itself would be asserting its
    // own arithmetic instead of the contract.
    ai_disclosure_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_enabled: true,
    recording_notice_line: "This call is being recorded.",
    caller_memory_notice_line: "I keep a short note of what you ask about.",
    caller_memory_enabled: false,
    caller_memory_paused: false,
    caller_has_screen: false,
    purpose: "sales",
    recording_notice_enabled: true,
    opening_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
    script_opening_line: "",
    first_words: "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
    truthful_answer_rule:
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    engine: "thinnest",
    published: true,
    inbound_number_count: 1,
    extraction_fields: [],
    // D-454: inheriting all the way up — what this fixture always meant
    // implicitly, back when an agent had no opinion about its model.
    llm_tier: null,
    llm_tier_effective: "standard",
    llm_tier_label: "Standard",
    llm_tier_source: "platform",
    llm_surcharged: false,
    ...over,
  };
}

/** One named voice as `GET /v1/agents/{id}/pending` returns it, catalogue entry and all. */
function storedVoice(label: string): NonNullable<PendingState["voice"]["live"]> {
  const id = `sonic-3.5:${label.toLowerCase()}`;
  return {
    voice_id: id,
    provider: "cartesia",
    voice_tier: "studio",
    catalog: {
      id,
      label,
      provider: "cartesia",
      tts_model: "sonic-3.5",
      speaker: label.toLowerCase(),
      gender: null,
      languages: ["te-IN"],
      note: "",
      verified: false,
    },
  };
}

/** A stored voice the catalogue no longer describes, rendered by its raw id. */
function legacyVoice(
  voiceId: string,
): NonNullable<PendingState["voice"]["live"]> {
  return { voice_id: voiceId, provider: "cartesia", voice_tier: "studio", catalog: null };
}

/** No staged edit, and the engine holds the voice the row names: the state an agent spends
 *  most of its life in. */
function settled(over: Partial<PendingState> = {}): PendingState {
  return {
    agent_id: "agent-1",
    agent_status: "live",
    published: true,
    has_pending: false,
    pending: [],
    effective_call_cap_s: 600,
    call_cap_is_platform_default: true,
    worst_case_call_cost_inr: "65.00",
    precedence_rule:
      "Script decides content, rules decide conduct, voice only changes delivery.",
    // REQUIRED on `PendingOut`. Empty is the honest default here: this account has no open
    // credit lot to quote a next-minute rate from, so the voice fact prints no price.
    voice_tier_rates: [],
    voice: {
      configured: storedVoice("Ananya"),
      live: storedVoice("Ananya"),
      republish_required: false,
      unnamed_note: null,
      headline: "Callers hear Ananya.",
    },
    engine_verification: {
      state: "applied",
      confirmed: true,
      publishable: true,
      verified_at: "2026-08-15T09:20:00Z",
      headline:
        "The voice platform was read back and is running this script and voice.",
    },
    ...over,
  };
}

/**
 * A staged script, with the two version numbers DELIBERATELY far apart.
 *
 * v9 waiting over v4 live: adjacent numbers would let a swap pass unnoticed, and the
 * numbers are the entire subject of the first test below.
 */
const STAGED: PendingState = settled({
  has_pending: true,
  pending: [
    {
      field: "script",
      lane: "staged",
      staged_version: 9,
      live_version: 4,
      staged_at: "2026-08-12T09:30:00Z",
      headline: "Script changes are waiting to go live.",
      why: "The script decides what the agent says, and a bad version is discovered by a customer on the phone. It waits for Apply.",
    },
  ],
});

const page = (
  <AgentDetailPage
    params={Promise.resolve({ slug: "acme", agentId: "agent-1" })}
  />
);

/**
 * The model catalogue this screen's `AgentModel` panel reads (D-454).
 *
 * ROUTED EVEN THOUGH THIS FILE IS NOT ABOUT THE MODEL PANEL, and the omission was not
 * harmless. The panel fires `GET /v1/organization/llm-defaults` on every render of this
 * screen — `agentLlmView` is non-null the moment the agent fixture carries the three llm
 * fields, which it has since D-454 — and an unrouted request THROWS in this harness by
 * design ("an unstubbed endpoint is a hole in the test's premise"). So every test in this
 * file was rendering a second, spurious `role="alert"`, and the one assertion that reads a
 * SINGLE alert ("does not report an agent as settled when the pending read failed") failed
 * with "Found multiple elements" whenever that alert won the race.
 *
 * Deliberately minimal — one addressable model, no surcharge. What the panel SAYS is
 * `clientLlmModel.test.tsx`'s subject and it carries the fixtures for it; this exists so
 * the panel behaves the way it does in production while the rest of the screen is tested.
 */
const LLM_DEFAULTS = clientLlmTiers();

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/agents/agent-1": agent(),
    "/v1/business-profile": businessProfileFixture(),
    "/v1/agents/agent-1/pending": settled(),
    "POST /v1/agents/agent-1/script/check": { warnings: [] },
    // The header reads the trial to lock an answer-only agent's switch on a trial (D-853).
    "/v1/trial": { on_trial: false },
    "/v1/kb/notes": { notes: [] },
    "/v1/organization/llm-defaults": LLM_DEFAULTS,
    // The Actions tab's reads, so the panel renders rather than raising its own alert —
    // these tests are about the pending/voice surface, not actions.
    "/v1/agents/agent-1/actions": {
      api_actions_enabled: false,
      calendar_available: false,
      tools: [],
    },
    "/v1/integrations/credentials": [],
    // The Questions to answer read (the Training badge and list), for the SAME reason — and
    // it is not optional. Left unstubbed, the harness throws, the list renders the generic
    // "We could not reach Calevate" notice, and the screen then holds TWO elements with
    // role="alert", so every `findByRole("alert")` here becomes a race. Empty because the
    // list is `teachQuestions.test.tsx`'s subject.
    "/v1/teach/questions?agent_id=agent-1": { items: [], open_count: 0 },
    // Mistakes on real calls, beside it on Training (D-949); `callMistakes.test.tsx` is its subject.
    "/v1/agents/agent-1/call-mistakes": { items: [], window_days: 30 },
    // The handover panel's read (D-533), for the SAME reason as the two entries above and
    // not because this file asserts anything about it — `agentHandover.test.tsx` is that
    // subject. Unstubbed, the panel raises its own `role="alert"` and every
    // `findByRole("alert")` here becomes a race it loses whenever that one paints first.
    // Overview's last calls for this agent (REDESIGN-2).
    "/v1/calls?agent_id=agent-1&limit=5": [],
    "/v1/agents/agent-1/readiness": agentReadiness(),
    "/v1/agents/agent-1/jobs": agentJobs(),
    "/v1/agents/agent-1/handoff": {
      agent_id: "agent-1",
      enabled: false,
      trigger: null,
      effective_trigger:
        "Hand the call to a person when the caller asks for one.",
      spoken_line:
        "Okay, I am putting you through to someone from our team now.",
      members: [],
      recent: [],
      on_duty_member_id: null,
      unavailable_reason: "disabled",
      remediation: "Transfer to a person is off for this agent. Turn it on to use it.",
      published: true,
    },
    // The voices the Voice section offers, and the lane rules: both read on this screen, and
    // an unanswered read is a stray `role="alert"`. A client is sent no models (D-679).
    [ENGINE_CATALOGUE_PATH]: operatorEngineCatalogue({ models: [] }),
    "/v1/agents/lanes": LANES,
    // The Calls section reads the call-handling settings (D-751).
    "/v1/agents/agent-1/call-handling": agentCallHandling("agent-1"),
    "/v1/organization/call-handling": organizationCallHandling(),
    ...teamAlertReads(),
    // The Voice section reads how a Studio voice sounds (D-843).
    "/v1/agents/agent-1/voice-tuning": clientVoiceTuning(),
    // And the notes the owner taught it on how to sound (`agents/voice_notes`).
    ...noVoiceNotes(),
    // The header's "spent this month" line (owners hold billing:read).
    [AGENT_SPEND_PATH]: spendThisMonth(),
    // Overview's setup checklist reads the agreements and the script's version.
    "/v1/legal/readiness": LEGAL_READY,
    "/v1/billing/wallet": prepaidWallet(),
    "/v1/agents/agent-1/script": {
      script: {
        opening_line: "Namaskaram.",
        steps: [],
        faqs: [],
        faq_fallback: "",
        end_call_extra_rules: [],
        variables: [],
        raw_override: null,
      },
      version: 4,
      is_freeform: false,
      has_pending: false,
      standard_variables: [],
    },
    ...over,
  };
}

/** A guide whose call behaviour was kept out of the knowledge (`kb/structured_text.py`). */
const GUIDE_UPLOAD = {
  id: "u-guide",
  source_id: "s-guide",
  name: "Calling guide.md",
  source_kind: "txt",
  ingest_status: "processed",
  review_state: "approved",
  is_live: true,
  version: 2,
  facts_count: 3,
  call_instructions: [
    { section: "If he says he is busy", text: "Ask when to call back." },
    { section: "How the agent should speak", text: "Say who you are and ask whether now is a good time." },
  ],
};

/** What the Training tab reads besides the screen's own: the knowledge, tests and wallet. */
/** What it notes' reads for an agent with no job and only the shared outcomes. */
const NOTES_READS = {
  "/v1/call-outcomes": { max_outcomes: 8, agents: [] },
};

const TRAINING_READS = {
  "/v1/kb/uploads": [GUIDE_UPLOAD],
  "/v1/kb/knows": {
    facts: [
      { id: "f1", text: "We deliver in Kukatpally.", pinned: false, origin: "taught", created_at: "2026-10-10T09:00:00Z" },
      { id: "f2", text: "Red chilli powder is ₹120 for 250 g.", pinned: true, origin: "taught", created_at: "2026-10-10T09:00:00Z" },
    ],
    facts_state: "live",
    items: [{ id: "i1", kind: "document", name: "Price list", state: "live" }],
    pinned_not_yet_on: [],
  },
  "/v1/kb/teach/open": { teaching: null },
  "/v1/agents/agent-1/known-facts": {
    enabled: true,
    applies: true,
    by_heart: [{ text: "Red chilli powder is ₹120 for 250 g.", asks: 4 }],
    looked_up: ["We deliver in Kukatpally."],
    looked_up_total: 1,
    used_chars: 90,
    budget_chars: 6000,
    calls_read: 12,
    computed_at: "2026-10-27T01:00:00Z",
  },
  "/v1/agents/agent-1/test-cases": { cases: [], limit: 20 },
  "/v1/agents/agent-1/script/tests": {
    available: true,
    unavailable_reason: null,
    cost_note: null,
    latest: null,
    history: [],
  },
};

/** The value rendered under a `dt`, read off the `dd` beside it. */
/** The value beside a label: a `<dd>` after its `<dt>`, or a `SettingRow`'s value cell. */
function factValue(label: string): string {
  const term = screen.getByText(label);
  if (term.tagName === "DT") return term.nextElementSibling?.textContent ?? "";
  const value = term.parentElement?.parentElement?.nextElementSibling?.firstElementChild;
  expect(value, `no value beside "${label}"`).toBeTruthy();
  return value?.textContent ?? "";
}

/** The Voice section of the Settings tab. */
/** The Voice tab's panel: the tab's label is its only heading. */
function voiceSection(): HTMLElement {
  const tab = screen.getByRole("tab", { name: "Voice" });
  expect(tab.getAttribute("aria-selected"), "the Voice tab is not open").toBe("true");
  return screen.getByRole("tabpanel");
}

describe("which script callers are actually hearing", () => {
  it("says a change is waiting and that callers keep what is live, with no version numbers", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1/pending": STAGED }),
    );

    await screen.findByText("Changes waiting to go live");
    // Founder decision (10 Oct 2026): owners see "live" and "waiting", never version numbers.
    expect(container.textContent).toContain("Callers hear the old version until then.");
    // The next step is a button to the Script tab, not a sentence pointing at the header.
    expect(screen.getByRole("link", { name: "Review and put live" })).toBeTruthy();
    expect(screen.queryByText("Live version")).toBeNull();
    expect(screen.queryByText("Waiting to be applied")).toBeNull();

    // …and the sentence under the list must not re-attach "what callers hear" to the
    // version listed above it, which is the staged one. This exact phrasing shipped.
    expect(container.textContent).not.toContain(
      "Callers still hear the version above",
    );
  });

  it("says nothing is live yet rather than inventing a version for a first draft", async () => {
    // `live_version` is null until the first Apply, and the server's headline simply drops
    // the clause. Printing "v0" or falling back to the staged number would claim callers
    // are hearing a script that has never been applied.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          has_pending: true,
          pending: [
            {
              field: "script",
              lane: "staged",
              staged_version: 1,
              live_version: null,
              staged_at: "2026-08-12T09:30:00Z",
              headline: "The script is waiting to go live.",
              why: "It waits for Apply.",
            },
          ],
        }),
      }),
    );

    await screen.findByText("Changes waiting to go live");
    expect(container.textContent).not.toContain("Version 1");
    expect(container.textContent).not.toContain("v0");
  });

  it("does not claim callers hear this page when the agent is not on the calling system", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({ published: false, status: "draft" }),
        "/v1/agents/agent-1/pending": settled({
          published: false,
          agent_status: "draft",
        }),
      }),
    );

    // The header says it, and no banner claims anything is waiting.
    await screen.findByText(/Not taking calls yet/);
    expect(container.textContent).not.toContain("what callers hear right now");
    expect(container.textContent).not.toContain("Changes waiting to go live");
  });

  it("does not report an agent as settled when the pending read failed", async () => {
    // The reassuring line ("nothing is waiting to go live") is the one an owner acts on —
    // they stop chasing us about an edit. It may only be printed on the server's word.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": problem(503, {
          title: "Service unavailable",
        }),
      }),
    );

    await screen.findByRole("alert");
    expect(container.textContent).not.toContain(
      "Nothing is waiting to go live",
    );
    expect(container.textContent).not.toContain("Longest one call may run");
  });
});

describe("which voice callers are actually hearing", () => {
  beforeEach(() => openSection("voice"));
  /**
   * A voice is TWO facts once it can be changed without being published, and this screen is
   * where a client finds out which one their callers get — and, since D-547 gave the
   * catalogue two qualities at two per-minute rates, what that voice costs them. Which
   * persona their agent speaks in is theirs to know; changing it stays ours (D-21), so
   * there is no control here.
   */
  it("names the QUALITY and what a minute of it costs this account", async () => {
    // D-547 gave the catalogue two qualities at two rates, so the voice is a price fact
    // again and an owner is entitled to both halves. Two rules are pinned here:
    //
    //  - the QUALITY is named, the VENDOR never is (founder, 7 Sep 2026). "Studio" is the
    //    API's word (`billing/rates.py::VOICE_TIER_LABELS`); which company synthesises it
    //    must be able to change without a client-visible rename.
    //  - the rate belongs to a CREDIT LOT, not to the product: it is the figure frozen on
    //    this account's oldest unspent purchase, and the hint says there is credit behind
    //    it at other rates rather than implying the price is permanent.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": {
          ...settled(),
          // `PendingOut.voice_tier_rates`, generated and required — read as a field now
          // that the schema carries it, not through a hand validator.
          voice_tier_rates: [
            {
              voice_tier: "studio",
              label: "Studio",
              inr_per_min: "8.0000",
              further_open_lots: 1,
            },
          ],
        },
      }),
    );

    // The first test to open the Voice tab pays for its lazy chunk's first import, which on
    // a loaded machine runs past the default one second.
    await screen.findByText("Voice quality and rate", undefined, { timeout: 5000 });
    // The server's own digits, prefixed and never parsed (hard rule 7).
    expect(factValue("Voice quality and rate")).toBe("Studio — ₹8 / min");
    // The rate is on screen; how it is struck is one tap away, behind the ⓘ.
    fireEvent.click(screen.getByRole("button", { name: "About Voice quality and rate" }));
    expect(
      await screen.findByText("You have 1 later purchase behind it, each at its own rate.", { exact: false }),
    ).toBeTruthy();
    expect(container.textContent).not.toMatch(/sarvam|cartesia/i);
  });

  it("shows no rate at all when the API carries none", async () => {
    // The state this build is in until the lots API ships the field, and the state of an
    // account with no open credit. A screen that filled the gap from the public rate card
    // would be quoting a price this client is not on; the whole Fact is absent instead.
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Voice callers hear");
    expect(container.textContent).not.toContain("Voice quality");
    // The model's own surcharges share the Settings tab; the claim is about the voice.
    expect(voiceSection().textContent).not.toContain("/ min");
  });

  it("prices the voice CALLERS HEAR, not the one waiting to go live", async () => {
    // The same inversion the two Facts above exist to prevent, applied to money: an agent
    // with a chosen-but-unpublished Clear voice is still charged at the rate of the voice
    // the calling system is actually speaking in. Pricing the configured one would quote a
    // rate no call on this agent is billed at.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": {
          ...settled({
            voice: {
              // A voice the calling platform supplies itself: no provider, no catalogue entry.
              configured: {
                voice_id: "engine:anjali",
                provider: null,
                voice_tier: "clear",
                catalog: null,
              },
              live: storedVoice("Ananya"),
              republish_required: true,
              unnamed_note: null,
              headline: "Callers still hear Ananya.",
            },
          }),
          voice_tier_rates: [
            {
              voice_tier: "clear",
              label: "Clear",
              inr_per_min: "5.0000",
              further_open_lots: 0,
            },
            {
              voice_tier: "studio",
              label: "Studio",
              inr_per_min: "8.0000",
              further_open_lots: 0,
            },
          ],
        },
      }),
    );

    await screen.findByText("Voice quality and rate");
    expect(factValue("Voice quality and rate")).toBe("Studio — ₹8 / min");
    expect(container.textContent).not.toContain("5.0000");
  });

  it("shows one voice when the calling system is holding the configured one", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe("Ananya");
    expect(container.textContent).not.toContain("New voice waiting");
  });

  it("explains a raw engine ref instead of leaving an owner to guess (D-617)", async () => {
    // THE CLIENT HALF OF THE FOUNDER'S SCREEN. `clientVoiceName` falls back to the stored
    // id so an owner can quote it to their account manager — right, and until now silent:
    // a live client read `sonic-3.5:b6dafaa0-…` as "the voice callers hear" with no
    // explanation and no such voice in the picker below. The sentence is the server's, is
    // printed verbatim, and names no vendor.
    const ref = "sonic-3.5:b6dafaa0-3a87-40b2-823c-1e4cf3c07314";
    const unnamed = { voice_id: ref, provider: "cartesia", voice_tier: "studio", catalog: null };
    const note =
      "The code shown is the voice platform's own reference for this voice.";
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          voice: {
            configured: unnamed,
            live: unnamed,
            republish_required: false,
            unnamed_note: note,
            headline: `Callers hear ${ref}.`,
          },
        }),
      }),
    );

    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe(ref);
    expect(container.textContent).toContain(note);
  });

  it("names BOTH voices when one is chosen and not yet published", async () => {
    // The inversion this screen must never ship: a chosen voice rendered as the one callers
    // hear. `set_agent_voice` writes our row and does not touch the engine, so until a
    // publish the two are different — and both are labelled, because a sentence can be read
    // the wrong way round and two `dt`/`dd` pairs cannot.
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          voice: {
            configured: storedVoice("Ananya"),
            live: legacyVoice("sonic-3.5:legacy"),
            republish_required: true,
            unnamed_note: null,
            headline: "Callers still hear sonic-3.5:legacy.",
          },
        }),
      }),
    );

    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe("sonic-3.5:legacy");
    expect(factValue("New voice waiting")).toBe("Ananya");
  });

  it("says a published agent's voice is unknown rather than claiming it is the configured one", async () => {
    // `live: null` on a PUBLISHED agent means we have no record of what the calling system
    // is holding. Rendering the configured voice here would be the whole defect: an
    // unverifiable claim about what a caller hears, made to the person paying for it.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          voice: {
            configured: storedVoice("Ananya"),
            live: null,
            republish_required: true,
            unnamed_note: null,
            headline: "Callers hear whatever voice was last published.",
          },
        }),
      }),
    );

    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe("We cannot say from here");
    expect(container.textContent).not.toContain("Voice callers hearAnanya");
    expect(factValue("New voice waiting")).toBe("Ananya");
  });

  it("says an unpublished agent has no voice in force at all", async () => {
    // A DIFFERENT null: nothing is on the calling system, so no caller hears anything and
    // nothing is waiting on us. "We cannot say" would be wrong here — we can.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({ published: false, status: "draft" }),
        "/v1/agents/agent-1/pending": settled({
          published: false,
          agent_status: "draft",
          voice: {
            configured: storedVoice("Ananya"),
            live: null,
            republish_required: false,
            unnamed_note: null,
            headline: "This agent is not on the voice platform yet.",
          },
        }),
      }),
    );

    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe("Nothing yet");
    expect(container.textContent).not.toContain("New voice waiting");
  });
});

describe("the numbers come from the server", () => {
  beforeEach(() => openSection("calls"));
  it("formats the worst-case cost as grouped rupees from the string the API sent", async () => {
    // `worst_case_call_cost_inr` is an exact NUMERIC crossing the wire as a STRING (hard
    // rule 7). `Number("1500.00")` is how ₹1,500.00 turns into a float on a screen a client
    // checks against their own books; `formatINR` groups the digits Indian-style and never
    // parses them. The raw wire form is asserted ABSENT.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          worst_case_call_cost_inr: "1500.5",
        }),
      }),
    );

    await screen.findByText("Most one call can cost you");
    expect(container.textContent).toContain("₹1,500.5");
    expect(container.textContent).not.toContain("₹1500.5");
    expect(container.textContent).not.toContain("$");
  });

  it("says it cannot price a call rather than quoting ₹0 when the plan has no rate", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          worst_case_call_cost_inr: null,
        }),
      }),
    );

    await screen.findByText("Most one call can cost you");
    // Null is "we cannot tell you", never "it is free" (publishing.py::_overage_rate) — and
    // never `formatINR`'s "—" either, which is the dash this app prints for a value that is
    // simply absent. This one is absent for a REASON the client can act on.
    expect(factValue("Most one call can cost you")).toBe("We cannot say yet");
    expect(container.textContent).not.toContain("₹0");
  });

  it("never tells a prepaid client the figure is their PLAN's rate", async () => {
    // A PREPAID ACCOUNT HAS NO PLAN ROW AT ALL (`apps/workers/pipeline.py`), and the server
    // now strikes this ceiling from whichever rate can actually price a minute — the plan's
    // overage rate, or the account's own credit (`agents/publishing.py::worst_case_rate`).
    // So the sentence beside the figure may not name a plan: it would be false for exactly
    // the accounts the fallback exists for, and this screen has no way to tell which kind
    // of account it is looking at.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          worst_case_call_cost_inr: "70.00",
        }),
      }),
    );

    await screen.findByText("Most one call can cost you");
    expect(container.textContent).toContain("₹70");
    fireEvent.click(screen.getByRole("button", { name: "About Most one call can cost you" }));
    expect(
      await screen.findByText(/at the dearest per-minute rate your account can be charged/),
    ).toBeTruthy();
    expect(container.textContent).not.toContain("your plan's per-minute rate");
    expect(container.textContent).not.toContain("Your plan does not quote");
  });

  it("sends the owner of an empty wallet to the thing that FIXES it, not to us", async () => {
    openSection("voice");
    // `inr_per_min` is null for exactly one reason (`billing/lots.py::TierRate`): no open
    // lot, i.e. an empty or overdrawn wallet. There is no rate because there is no credit,
    // and the rate is the one frozen on the pack they buy — so "your account manager can"
    // sent an owner to someone who cannot do anything about it.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          voice_tier_rates: [
            {
              voice_tier: "clear",
              label: "Clear",
              inr_per_min: null,
              further_open_lots: 0,
            },
            {
              voice_tier: "studio",
              label: "Studio",
              inr_per_min: null,
              further_open_lots: 0,
            },
          ],
        }),
      }),
    );

    await screen.findByText("Voice quality");
    // The fix is a button on the row, to Billing.
    expect(screen.getByRole("link", { name: "Add credit" }).getAttribute("href")).toBe("/c/acme/billing");
    fireEvent.click(screen.getByRole("button", { name: "About Voice quality" }));
    expect(await screen.findByText(/The credit pack you buy sets it/)).toBeTruthy();
    expect(container.textContent).not.toContain(
      "We cannot put a per-minute price on this voice for your account right now.",
    );
    // And no invented figure beside it: absent renders absent (hard rule 7).
    expect(voiceSection().textContent).not.toContain("/ min");
  });

  it("reads the call cap off the API instead of hardcoding ten minutes", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          effective_call_cap_s: 330,
          call_cap_is_platform_default: false,
        }),
      }),
    );

    await screen.findByText("Longest one call may run");
    expect(factValue("Longest one call may run")).toBe("5 min 30 s");
  });
});

describe("the two opening notices, as the account sets them (D-163, D-1021)", () => {
  //: The fixture agent's `first_words`, shown as the server sent it.
  const OPENING =
    "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.";

  it("leaves the opening line to the Script tab: the Overview does not show it", async () => {
    await renderClientPage(page, routes());

    const panel = await waitFor(() => card("What it says at the start of every call"));
    expect(panel.textContent).not.toContain(OPENING);
    expect(within(panel).queryByRole("link", { name: /opening line/ })).toBeNull();
  });

  it("quotes no fixed notice sentence: the agent words the notices itself", async () => {
    // With a switch on the agent mentions the notice in its own words, so a sentence shown
    // here would be one it may never say. The columns are still on the API.
    const GREETING = "Namaskaram! Sri Clinic, how can I help you today?";
    const panelOf = async () => waitFor(() => card("What it says at the start of every call"));
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          script_opening_line: GREETING,
          first_words: GREETING,
          ai_disclosure_line: "FIXED AI SENTENCE",
          recording_notice_line: "FIXED RECORDING SENTENCE",
        }),
      }),
    );

    const panel = await panelOf();
    expect(panel.textContent).not.toContain("FIXED AI SENTENCE");
    expect(panel.textContent).not.toContain("FIXED RECORDING SENTENCE");
    expect(panel.querySelector("blockquote")).toBeNull();
    expect(panel.textContent).not.toContain("“");
  });

  it("has no memory row on an agent that remembers callers: that sentence is not spoken", async () => {
    const MEMORY = "I keep a short note of what you ask about.";
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          caller_memory_enabled: true,
          caller_memory_paused: false,
          caller_memory_notice_line: MEMORY,
        }),
      }),
    );

    const panel = await waitFor(() => card("What it says at the start of every call"));
    expect(panel.textContent).not.toContain(MEMORY);
    expect(panel.textContent).not.toContain("remembers callers");
  });

  it("asks an account on the old caller-memory statement to accept the new one (D-900)", async () => {
    openSection("settings");
    const STATEMENT = "I confirm the updated statement about what these calls collect.";
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          caller_memory_enabled: true,
          caller_memory_paused: true,
          caller_memory_statement: STATEMENT,
        }),
      }),
    );

    await screen.findByText("Caller memory is paused");
    expect(container.textContent).toContain(STATEMENT);
    expect(screen.getByRole("button", { name: "Accept and resume" })).toBeTruthy();
  });

  it("accepting the updated statement sends memory on with the acceptance (D-900)", async () => {
    openSection("settings");
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          caller_memory_enabled: true,
          caller_memory_paused: true,
          caller_memory_statement: "I confirm the updated statement.",
        }),
        "PATCH /v1/agents/agent-1/caller-memory": {
          agent_id: "agent-1",
          caller_memory_enabled: true,
          attestation: "I confirm the updated statement.",
        },
      }),
    );

    await screen.findByText("Caller memory is paused");
    await act(async () => {
      fireEvent.click(await pressable(document.body, /Accept and resume/));
    });

    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.path).toBe("/v1/agents/agent-1/caller-memory");
    expect(JSON.parse(patch?.body ?? "{}")).toEqual({ enabled: true, accept: true });
  });

  it("offers the screen-guide switch off by default, with how it works (D-906)", async () => {
    openSection("settings");
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Caller follows along on a screen");
    const toggle = screen.getByRole("switch", { name: "Guide callers through their screen" });
    expect((toggle as HTMLInputElement).checked).toBe(false);
    expect(container.textContent).toContain("spells a web address one letter at a time");
  });

  it("shows the screen guide on for an agent that has it (D-906)", async () => {
    openSection("settings");
    await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1": agent({ caller_has_screen: true }) }),
    );

    await screen.findByText("Caller follows along on a screen");
    const toggle = screen.getByRole("switch", { name: "Guide callers through their screen" });
    expect((toggle as HTMLInputElement).checked).toBe(true);
  });

  describe("asks about guiding callers when this agent's own judgement suggests it", () => {
    const REASON = "She walks farmers through installing the app step by step.";
    const asked = { suggested: true, reason: REASON, on: false, dismissed: false, ask: true };
    const HELP = "GET /v1/agents/agent-1/caller-help";
    const BOTH = { state: "done", screen_guide: asked, give_time: asked, checked_at: null };
    const TITLE = "Do Reception's callers follow along on their phone?";

    it("asks on the Overview with the agent's reason, and one press turns both on", async () => {
      const { calls } = await renderClientPage(
        page,
        routes({
          [HELP]: BOTH,
          "PATCH /v1/agents/agent-1/caller-screen": {
            agent_id: "agent-1",
            enabled: true,
            engine_synced: true,
            give_callers_time_settings: [],
          },
          "POST /v1/agents/agent-1/call-handling/give-callers-time": {},
        }),
      );

      await screen.findByText(TITLE);
      expect(screen.getByText(REASON)).toBeTruthy();
      await act(async () => {
        fireEvent.click(await pressable(document.body, /Turn both on/));
      });
      await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
      const writes = calls.filter((call) => call.method !== "GET").map((call) => call.path);
      // The screen guide first: it decides which question "Give callers time" asks.
      expect(writes).toEqual([
        "/v1/agents/agent-1/caller-screen",
        "/v1/agents/agent-1/call-handling/give-callers-time",
      ]);
    });

    it("offers only what is suggested and not yet on", async () => {
      const { calls } = await renderClientPage(
        page,
        routes({
          [HELP]: { ...BOTH, screen_guide: { ...asked, suggested: false, reason: "", ask: false } },
          "POST /v1/agents/agent-1/call-handling/give-callers-time": {},
        }),
      );
      await screen.findByText("Do Reception's callers need time to do what it asks?");
      await act(async () => {
        fireEvent.click(await pressable(document.body, /Give them time/));
      });
      await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
      expect(calls.some((call) => call.path.endsWith("/caller-screen"))).toBe(false);
    });

    it("does not ask about an agent judged to need neither", async () => {
      const { container } = await renderClientPage(page, routes());
      await screen.findByRole("heading", { name: "How ready it is" });
      expect(container.textContent).not.toContain("follow along on their phone?");
    });

    it("remembers not now on the server", async () => {
      const dismissed = { ...asked, dismissed: true, ask: false };
      const { calls } = await renderClientPage(
        page,
        routes({
          [HELP]: BOTH,
          "POST /v1/agents/agent-1/caller-help/dismiss": {
            ...BOTH,
            screen_guide: dismissed,
            give_time: dismissed,
          },
        }),
      );
      await screen.findByText(TITLE);
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "Not now" }));
      });
      await waitFor(() => expect(screen.queryByText(TITLE)).toBeNull());
      expect(calls.some((call) => call.path === "/v1/agents/agent-1/caller-help/dismiss")).toBe(true);
    });

    it("says it is suggested for this agent, and why, beside the switch in Settings", async () => {
      openSection("settings");
      await renderClientPage(page, routes({ [HELP]: BOTH }));
      await screen.findByText("Caller follows along on a screen");
      expect((await screen.findAllByText(`Suggested for Reception: ${REASON}`)).length).toBe(2);
      expect(screen.getByRole("switch", { name: "Guide callers through their screen" })).toBeTruthy();
    });
  });

  it("shows no re-accept prompt on an account on the current statement", async () => {
    openSection("settings");
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1": agent({ caller_memory_enabled: true }) }),
    );

    await screen.findByText("Remembering callers");
    expect(container.textContent).not.toContain("Caller memory is paused");
  });

  it("shows the account's two notices and one button to change them for all calls", async () => {
    // D-1021: the switches are the account's, so this agent's page has none of its own.
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({ ai_disclosure_enabled: true, recording_notice_enabled: false }),
      }),
    );

    const panel = await waitFor(() => card("What it says at the start of every call"));
    expect(panel.textContent).toContain("Says it is an AI: on.");
    expect(panel.textContent).toContain("Says the call is recorded: off.");
    // The guarantee is the server's own words, above the two states (hard rule 5).
    const promise = within(panel).getByText(
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    );
    expect(
      promise.compareDocumentPosition(within(panel).getByText(/Says it is an AI/)) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(within(panel).queryAllByRole("switch")).toHaveLength(0);
    const change = within(panel).getByRole("link", { name: "Change for all calls" });
    expect(change.getAttribute("href")).toContain("/settings/call-notices");
  });
});

describe("the order of What it says (redesign 28 Nov 2026)", () => {
  it("puts the notices first, then its jobs, the checklist and the readiness score", async () => {
    await renderClientPage(page, routes());

    // The truthful-answer guarantee and the notices open the first tab (hard rule 5).
    const notices = await screen.findByRole("heading", {
      name: "What it says at the start of every call",
    });
    const jobs = await screen.findByRole("heading", { name: "Its jobs" });
    const checklist = await screen.findByText(/Before its first call|Still to set up|Ready for calls/);
    const readiness = await screen.findByRole("heading", { name: "How ready it is" });
    const order = [notices, jobs, checklist, readiness];
    for (let i = 1; i < order.length; i += 1) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    await screen.findByText("Give it a job: an Inbound line or a campaign.");
    expect(screen.getByText("How the score is made").closest("details")?.open).toBe(false);
  });
});

describe("putting a waiting script live from the header", () => {
  it("offers the owner Put it live on the client-realm door, CAS on the waiting version", async () => {
    // CHANGED 10 Oct 2026 (founder: one "Put it live", no Save → Apply): the header's
    // primary is "Put it live", shown while the script differs from what callers hear. A
    // change saved the older way and still waiting goes through `POST .../script/apply`,
    // CAS on the version the owner was shown.
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": STAGED,
        "/v1/agents/agent-1/script": {
          script: { ...EMPTY_SCRIPT, opening_line: "Namaskaram." },
          version: 9,
          is_freeform: false,
          has_pending: true,
          standard_variables: [],
        },
        "POST /v1/agents/agent-1/script/apply": {
          applied: true,
          live_version: 9,
          engine_synced: true,
        },
      }),
    );

    await screen.findByText("Changes waiting to go live");
    const open = await screen.findByRole("button", { name: "Put it live" });
    await waitFor(() => expect(open.hasAttribute("disabled")).toBe(false));
    await act(async () => {
      fireEvent.click(open);
    });
    const dialog = await screen.findByRole("dialog", { name: "Put the waiting changes live?" });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Put it live" }));
    });
    const posted = calls.find((call) => call.path === "/v1/agents/agent-1/script/apply");
    expect(posted?.method).toBe("POST");
    expect(JSON.parse(posted?.body ?? "{}")).toEqual({ expected_version: 9 });
  });

  it("offers no Put it live when nothing is waiting", async () => {
    await renderClientPage(page, routes());
    await screen.findByText("Reception");
    expect(screen.queryByRole("button", { name: /put it live/i })).toBeNull();
  });

  it("issues no admin-realm request from a client screen", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1/pending": STAGED }),
    );

    await screen.findByText("Changes waiting to go live");
    for (const call of calls) {
      // The admin realm is not reachable from a client screen, whatever session this tab
      // holds — `useApplyChanges` builds an `adminSession()`, and calling it from here
      // would show up as a `/v1/admin/...` path in this list.
      expect(call.path).not.toContain("/v1/admin/");
    }
  });
});

/**
 * A control this session may actually press.
 *
 * Every write on this screen is gated on `useWriteAccess`, which fails CLOSED while
 * `/v1/me` is in flight — a control that flashes an explanation and then retracts it
 * teaches the reader to ignore the next one. So a button is disabled for the first moment
 * of every render, and a test that clicks on the first paint clicks nothing and then fails
 * on whatever it expected the click to produce.
 *
 * Waiting for it here rather than sprinkling `waitFor` through the tests keeps that
 * property in ONE place with the reason attached — and asserts it: a control that never
 * becomes pressable for an owner would time out here rather than pass quietly.
 */
async function pressable(
  panel: HTMLElement,
  name: RegExp,
): Promise<HTMLElement> {
  const button = within(panel).getByRole("button", { name });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  return button;
}

/**
 * The panel with this heading, so a claim is read off the panel it is about.
 *
 * `section, details` and not `section` alone: a panel may be a plain `<section>` (the
 * agent page's sections) or a `<Disclosure>`, a native `<details>` whose `<summary>`
 * carries the heading. The panel is still found by its
 * heading; only the element around it differs, which is exactly the seam a helper should
 * absorb rather than every test.
 *
 * A closed `<details>` still has its children in the DOM under jsdom, so these tests read
 * a disclosed panel without opening it. That is a property of the TEST environment, not a
 * claim that the content is visible to a user — what a person must be able to see without
 * a click is asserted separately, by the hierarchy tests at the top of this file.
 */
function card(title: string): HTMLElement {
  const heading = screen.getByRole("heading", { name: title });
  const panel = heading.closest("section, details");
  expect(panel, `no <section>/<details> around "${title}"`).not.toBeNull();
  return panel as HTMLElement;
}

/** A paused agent, which since D-527 is the only state a delete is offered from. */
const SWITCHED_OFF = {
  "/v1/agents/agent-1": agent({ status: "paused", published: true }),
};

describe("switching an agent on, off and deleting it (D-440, D-527)", () => {
  // CHANGED 10 Oct 2026: on and off are one "Taking calls" switch in the header (it was a
  // primary button and a ⋯ menu item); Delete, with its consequences, is in Settings. The
  // server's transition table is what each test still pins.
  it("offers a live agent only the moves the server's transition table allows", async () => {
    const { calls } = await renderClientPage(page, routes({
      "POST /v1/agents/agent-1/deactivate": { agent_id: "agent-1", status: "paused", changed: true },
    }));

    await screen.findByText("Reception");
    // `live -> {paused}` ONLY (lifecycle.AGENT_TRANSITIONS): the switch is on, and turning
    // it off is the one move.
    const toggle = screen.getByRole("switch", { name: "Taking calls" }) as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    expect(screen.queryByRole("button", { name: "Bring it back" })).toBeNull();
    await waitFor(() => expect(toggle.disabled).toBe(false));
    await act(async () => {
      fireEvent.click(toggle);
    });
    expect(calls.find((call) => call.method === "POST")?.path).toBe("/v1/agents/agent-1/deactivate");
  });

  it("will not offer to delete a working agent, and says the one thing to do first", async () => {
    openSection("advanced");
    await renderClientPage(page, routes());

    await screen.findByText("Reception");
    const panel = card("Delete this agent");
    expect(within(panel).queryByRole("button", { name: /Delete/ })).toBeNull();
    expect(panel.textContent).toContain("It is taking calls. Switch it off first.");
    // A quiet notice, not a tinted card, with the one move beside it.
    expect(panel.querySelector("[data-notice]")).not.toBeNull();
    expect(within(panel).getByRole("button", { name: "Switch off" })).toBeTruthy();
  });

  it("switches a working agent off from the delete notice", async () => {
    openSection("advanced");
    const { calls } = await renderClientPage(
      page,
      routes({
        "POST /v1/agents/agent-1/deactivate": { agent_id: "agent-1", status: "paused", changed: true },
      }),
    );

    await screen.findByText("Reception");
    const panel = card("Delete this agent");
    await act(async () => {
      fireEvent.click(await pressable(panel, /^Switch off$/));
    });
    await waitFor(() =>
      expect(calls.find((call) => call.method === "POST")?.path).toBe("/v1/agents/agent-1/deactivate"),
    );
  });

  it("says the switch-off worked though the notice has given way to the delete by then", async () => {
    openSection("advanced");
    let off = false;
    await renderClientPage(
      <ToastProvider>{page}</ToastProvider>,
      routes({
        // The move's refresh is awaited, so the agent reloads switched off — and the notice
        // holding the button gives way to the delete panel — before the move succeeds.
        "/v1/agents/agent-1": () => (off ? agent({ status: "paused", published: true }) : agent()),
        "POST /v1/agents/agent-1/deactivate": () => {
          off = true;
          return { agent_id: "agent-1", status: "paused", changed: true };
        },
      }),
    );

    await screen.findByText("Reception");
    const panel = card("Delete this agent");
    await act(async () => {
      fireEvent.click(await pressable(panel, /^Switch off$/));
    });
    expect(await screen.findByText("Switched off. You can delete it now.")).toBeTruthy();
    expect(within(card("Delete this agent")).getByRole("button", { name: /^Delete…$/ })).toBeTruthy();
  });

  it("offers a switched-off agent the delete the live one could not have", async () => {
    openSection("advanced");
    await renderClientPage(page, routes(SWITCHED_OFF));

    await screen.findByText("Reception");
    expect((screen.getByRole("switch", { name: "Taking calls" }) as HTMLInputElement).checked).toBe(false);
    const panel = card("Delete this agent");
    expect(within(panel).getByRole("button", { name: /^Delete…$/ })).toBeTruthy();
  });

  it("on a trial, the switch gets an agent ready for test calls rather than refusing (founder, 23 Oct 2026)", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({ status: "draft", published: false }),
        "/v1/trial": {
          on_trial: true,
          calls_today: 0,
          daily_cap: 10,
          max_call_seconds: 180,
          minutes_used: 0,
          pledge_accepted: true,
          can_call: true,
        },
        "POST /v1/agents/agent-1/prepare": { agent_id: "agent-1", status: "paused", changed: true },
      }),
    );

    await screen.findByText("Reception");
    const toggle = screen.getByRole("switch", { name: "Taking calls" }) as HTMLInputElement;
    await waitFor(() => expect(toggle.disabled).toBe(false));
    expect(toggle.checked).toBe(false);
    await act(async () => {
      fireEvent.click(toggle);
    });
    const posts = calls.filter((call) => call.method === "POST").map((call) => call.path);
    expect(posts).toContain("/v1/agents/agent-1/prepare");
    expect(posts.some((path) => path.endsWith("/activate"))).toBe(false);
  });

  it("on a trial, a ready agent shows as on for test calls, with the way to make one", async () => {
    await renderClientPage(page, routes({ ...SWITCHED_OFF, "/v1/trial": {
          on_trial: true,
          calls_today: 0,
          daily_cap: 10,
          max_call_seconds: 180,
          minutes_used: 0,
          pledge_accepted: true,
          can_call: true,
        } }));

    await screen.findByText("Reception");
    const toggle = screen.getByRole("switch", { name: "Taking calls" }) as HTMLInputElement;
    await waitFor(() => expect(toggle.checked).toBe(true));
    // Said once, in the header line; the checklist and the row under the header do not
    // repeat it (D-873).
    expect(screen.getAllByText(/Test calls only, until your account is live/)).toHaveLength(1);
    const links = screen.getAllByRole("link", { name: "Make a test call" });
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("/c/acme");
  });

  it("leaves the switch alone for an answer-only agent on an account that has paid", async () => {
    await renderClientPage(page, routes({ ...SWITCHED_OFF, "/v1/trial": { on_trial: false } }));

    await screen.findByText("Reception");
    const toggle = screen.getByRole("switch", { name: "Taking calls" }) as HTMLInputElement;
    await waitFor(() => expect(toggle.disabled).toBe(false));
  });

  it("offers an archived agent a restore and nothing else, and says it comes back switched off", async () => {
    // `archived -> {paused}` only: a restore never puts an agent straight back on the phone.
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          status: "archived",
          archived_at: "2026-07-02T09:30:00Z",
          published: false,
        }),
      }),
    );

    await screen.findByText("Reception");
    expect(screen.getByRole("button", { name: "Bring it back" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Delete/ })).toBeNull();
    expect(screen.queryByRole("switch", { name: "Taking calls" })).toBeNull();
    expect(document.body.textContent).toContain("comes back switched off");
  });

  it("restates what deleting does before it does it, and only then posts", async () => {
    openSection("advanced");
    const { calls } = await renderClientPage(
      page,
      routes({
        ...SWITCHED_OFF,
        "POST /v1/agents/agent-1/archive": {
          agent_id: "agent-1",
          status: "archived",
          changed: true,
          numbers_released: 2,
        },
      }),
    );

    await screen.findByText("Reception");
    const panel = card("Delete this agent");

    // FIRST PRESS: the consequences, no request. The one a client most needs is that the
    // history survives — an owner who believes Delete erases their call log will leave a
    // dead agent switched off forever instead, which is the reason the word "delete" is
    // affordable at all (D-527).
    await act(async () => {
      fireEvent.click(await pressable(panel, /^Delete…$/));
    });
    expect(panel.textContent).toContain("Its calls, recordings and leads are kept.");
    expect(panel.textContent).toContain("It leaves your list and your campaigns.");
    expect(calls.some((call) => call.method === "POST")).toBe(false);

    // SECOND PRESS: the move — still `POST /archive`, because the server's word for it
    // has not changed and the client's label is a label.
    await act(async () => {
      fireEvent.click(await pressable(panel, /Delete this agent/));
    });
    const posted = calls.find((call) => call.method === "POST");
    expect(posted?.path).toBe("/v1/agents/agent-1/archive");
  });

  it("keeps the confirmed delete on screen, pending and unpressable, while it is in flight", async () => {
    openSection("advanced");
    const { calls } = await renderClientPage(
      page,
      routes({ ...SWITCHED_OFF, "POST /v1/agents/agent-1/archive": stillLoading() }),
    );
    await screen.findByText("Reception");
    const panel = card("Delete this agent");
    await act(async () => {
      fireEvent.click(await pressable(panel, /^Delete…$/));
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Delete this agent/));
    });

    const confirm = within(panel).getByRole("button", { name: /Delete this agent/ });
    await waitFor(() => expect(confirm.getAttribute("aria-busy")).toBe("true"));
    expect(within(panel).queryByRole("button", { name: /^Delete…$/ })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Keep it/ })).toBeNull();
    await act(async () => {
      fireEvent.click(confirm);
    });
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);
  });

  it("announces the delete consequences and leaves the keyboard on the control", async () => {
    /**
     * The half `tests/a11y.ts` says out loud that the axe sweep cannot see: axe checks the
     * markup that exists, never an announcement that never happens or a Tab that goes
     * somewhere it should not. Both are real risks on THIS control, because it is the one
     * destructive action a client can take on an agent and the panel that explains it
     * appears only after a press.
     *
     * 1. **It is announced.** A consequence that exists only as newly-painted pixels is a
     *    consequence a screen-reader user is asked to confirm without having been told.
     * 2. **Focus survives the press.** The trigger and the confirm button are one
     *    `<button>` in one slot of one parent, so React reuses the DOM node and the
     *    keyboard stays on it — the button's NAME changes under the user rather than the
     *    button vanishing from under them. That is a property of the reconciliation, and a
     *    refactor into two sibling buttons would take it away with nothing else failing:
     *    focus would fall to `<body>` and a keyboard-only owner would have to Tab back
     *    through the page to finish an action they had started.
     */
    openSection("advanced");
    await renderClientPage(page, routes(SWITCHED_OFF));
    await screen.findByText("Reception");
    const panel = card("Delete this agent");

    const trigger = await pressable(panel, /^Delete…$/);
    // Focused the way a keyboard user arrives at it, then activated. `fireEvent.click`
    // alone would prove nothing about focus: it does not move it.
    await act(async () => {
      (trigger as HTMLButtonElement).focus();
      fireEvent.click(trigger);
    });

    // The confirm is a kit `ActionButton`, whose own (empty) outcome line is a status too.
    const announced = within(panel)
      .getAllByRole("status")
      .find((el) => el.textContent?.includes("Its calls, recordings and leads are kept."));
    expect(announced, "the delete consequences were not announced").toBeDefined();

    const armed = within(panel).getByRole("button", {
      name: /Delete this agent/,
    });
    expect(
      document.activeElement,
      "the keyboard was dropped by the confirm step",
    ).toBe(armed);

    // And the way out is reachable too — a confirmation a keyboard user can enter and not
    // leave is worse than no confirmation.
    await act(async () => {
      fireEvent.click(within(panel).getByRole("button", { name: /Keep it/ }));
    });
    expect(within(panel).queryByText(/Its calls, recordings and leads are kept/)).toBeNull();
    expect(
      within(panel).getByRole("button", { name: /^Delete…$/ }),
    ).toBeTruthy();
  });

  it("renders the server's refusal when switching on is not possible yet", async () => {
    // The commonest one by far: `publish_agent` refuses an agent with no prompt version by
    // name. It is a refusal a client can act on — ask for the script to be written — so it
    // must arrive as the API's own sentence, not as a spinner that stops.
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({ status: "draft", published: false }),
        "POST /v1/agents/agent-1/activate": problem(409, {
          type: "urn:calevate:agents/agent_has_no_script",
          title: "This agent has no script yet",
          detail: "Nothing has been written for it to say.",
          remediation: "Ask us to write its script.",
        }),
      }),
    );

    await screen.findByText("Reception");
    const switchOn = screen.getByRole("switch", { name: "Taking calls" });
    await waitFor(() => expect(switchOn.hasAttribute("disabled")).toBe(false));
    await act(async () => {
      fireEvent.click(switchOn);
    });

    const alert = await screen.findByRole("alert");
    // `ApiProblem` leads with `detail` (falling back to `title`), and `ProblemNotice`
    // prints the remediation under it — so BOTH halves are asserted: what happened, and
    // what the client can do about it. A refusal with no second line is a dead end.
    expect(alert.textContent).toContain(
      "Nothing has been written for it to say.",
    );
    expect(alert.textContent).toContain(
      "Ask us to write its script.",
    );
  });

  it("links each missing setup step when switching on is refused for the business profile", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({ status: "draft", published: false }),
        "POST /v1/agents/agent-1/activate": problem(409, {
          type: "urn:calevate:tenancy/business_profile_incomplete",
          title: "Finish your business profile first",
          detail: "Your agent needs a few facts about your business before it can take calls.",
          fields: [{ field: "setup.hours", rule: "business_hours_missing", message: "Add your opening hours." }],
        }),
      }),
    );

    await screen.findByText("Reception");
    const switchOn = screen.getByRole("switch", { name: "Taking calls" });
    await waitFor(() => expect(switchOn.hasAttribute("disabled")).toBe(false));
    await act(async () => {
      fireEvent.click(switchOn);
    });
    expect(await screen.findByText("Do these first, then it can take calls.")).toBeTruthy();
    const link = screen.getAllByRole("link").find((a) => a.getAttribute("href")?.includes("/settings/business?mode=steps&step=hours"));
    expect(link).toBeTruthy();
  });

  it("gets a draft ready without switching it on (D-838)", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({ status: "draft", published: false }),
        "POST /v1/agents/agent-1/prepare": { agent_id: "agent-1", status: "paused", changed: true, numbers_released: 0 },
      }),
    );
    await screen.findByText("Reception");
    const ready = screen.getByRole("button", { name: "Get it ready" });
    await waitFor(() => expect(ready.hasAttribute("disabled")).toBe(false));
    await act(async () => {
      fireEvent.click(ready);
    });
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/prepare"))).toBe(true));
    expect(calls.some((c) => c.path.endsWith("/activate"))).toBe(false);
  });
});

describe("a deleted agent offers nothing to tweak (the founder's screenshot)", () => {
  /*
   * THE DEFECT, IN ONE SENTENCE: the header badge said "Deleted" and the page then offered
   * a green "Open the script builder →" under the words "Write the script first — an agent
   * with none cannot be switched on". A deleted agent has a script, cannot be switched on
   * by writing one, and every save from that builder is refused by the server.
   *
   * The assertions are on the ABSENCE of controls rather than on their disabled state,
   * because that is what was asked for and because a dead control is this repo's own
   * defined worse option ("a button that would 403 is worse than no button at all").
   */
  const DELETED = {
    "/v1/agents/agent-1": agent({
      status: "archived",
      archived_at: "2026-07-02T09:30:00Z",
      published: false,
    }),
  };

  it("offers no way into the script builder, and no draft-agent advice", async () => {
    await renderClientPage(page, routes(DELETED));

    await screen.findByText("Reception");
    expect(screen.queryByRole("link", { name: /script builder/i })).toBeNull();
    expect(document.body.textContent).not.toContain("Write the script first");
    // And it says what IS true, in place of the sentence that was not.
    expect(document.body.textContent).toContain("Read-only while deleted");
  });

  it("renders no write control anywhere on the screen except the restore", async () => {
    await renderClientPage(page, routes(DELETED));

    await screen.findByText("Reception");
    // The switches, the save buttons and the teach-it form are all gone, not disabled.
    for (const name of [
      /Save changes/,
      /Add to your knowledge/,
      /Let AI draft/i,
      /Switch off/,
      /Switch on/,
      /Delete/,
    ]) {
      expect(screen.queryByRole("button", { name }), String(name)).toBeNull();
    }
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    // The one available action, named in the copy and present as the only button.
    expect(screen.getByRole("button", { name: "Bring it back" })).toBeTruthy();
  });

  it("still READS: the badge and what it was are on the page", async () => {
    // Deleting keeps the history — that is the whole reason the server archives rather
    // than erases — so a guard that hid the record would be a worse defect than the one
    // this screen had.
    await renderClientPage(page, routes(DELETED));

    await screen.findByText("Reception");
    expect(screen.getAllByText("Deleted").length).toBeGreaterThan(0);
    expect(card("What it is").textContent).toContain("Bring it back to change");
  });
});

describe("changing what an agent is", () => {
  beforeEach(() => openSection("advanced"));
  it("sends only the field that moved", async () => {
    // `AgentUpdateIn` treats an omitted field as "leave this alone" and REFUSES a body that
    // names nothing, which is why the button is dead until something differs. Sending all
    // three would make a rename a read-modify-write race against a direction change.
    const { calls } = await renderClientPage(
      page,
      routes({ "PATCH /v1/agents/agent-1": agent({ name: "Front desk" }) }),
    );

    await screen.findByText("Reception");
    const panel = card("What it is");
    // `/^Name/`, not "Name": the label wraps its hint too, so the accessible name is the
    // whole "Name Only you see this…" string and an exact match finds nothing.
    const nameInput = within(panel).getByLabelText(/^Name/);
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: "Front desk" } });
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save changes/));
    });

    const patched = calls.find((call) => call.method === "PATCH");
    expect(patched?.path).toBe("/v1/agents/agent-1");
    expect(JSON.parse(patched?.body ?? "{}")).toEqual({ name: "Front desk" });
  });

  it("says why a save was refused in the save bar, beside the button pressed", async () => {
    await renderClientPage(
      page,
      routes({
        "PATCH /v1/agents/agent-1": problem(409, { title: "That name is taken", detail: "Another agent is already called Front desk." }),
      }),
    );
    await screen.findByText("Reception");
    const panel = card("What it is");
    await act(async () => {
      fireEvent.change(within(panel).getByLabelText(/^Name/), { target: { value: "Front desk" } });
    });
    const save = await pressable(panel, /Save changes/);
    await act(async () => {
      fireEvent.click(save);
    });
    const bar = save.closest(".sticky") as HTMLElement;
    await waitFor(() => expect(bar.textContent).toContain("Another agent is already called Front desk."));
  });

  it("marks the agent as one that helps customers (founder, 21 Nov 2026)", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ "PATCH /v1/agents/agent-1": agent({ purpose: "support" }) }),
    );

    await screen.findByText("Reception");
    const panel = card("What it is");
    const purpose = within(panel).getByRole("group", { name: "What this agent is for" });
    expect(within(purpose).getByRole("radio", { name: /Selling/ })).toHaveProperty("checked", true);
    await act(async () => {
      fireEvent.click(within(purpose).getByRole("radio", { name: /Helping customers/ }));
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save changes/));
    });

    const patched = calls.find((call) => call.method === "PATCH");
    expect(JSON.parse(patched?.body ?? "{}")).toEqual({ purpose: "support" });
  });

  it("sends the languages it replies in, its main language first (D-815)", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "PATCH /v1/agents/agent-1": agent({ reply_languages: ["te-IN", "en-IN"] }),
      }),
    );

    await screen.findByText("Reception");
    const panel = card("What it is");
    const replies = within(panel).getByRole("group", { name: "It also replies in" });
    // The main language is never offered again as an extra one.
    expect(within(replies).queryByRole("checkbox", { name: "Telugu" })).toBeNull();
    await act(async () => {
      fireEvent.click(within(replies).getByRole("checkbox", { name: "English (India)" }));
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save changes/));
    });

    const patched = calls.find((call) => call.method === "PATCH");
    expect(JSON.parse(patched?.body ?? "{}")).toEqual({ reply_languages: ["te-IN", "en-IN"] });
    // Only the extras moved, so no opening line is offered.
    expect(within(panel).queryByRole("button", { name: /ready-made opening line/ })).toBeNull();
  });

  it("does not offer a held-back language by default (D-855)", async () => {
    await renderClientPage(page, routes());
    await screen.findByText("Reception");
    const hidden = within(card("What it is"));
    expect(hidden.queryByRole("checkbox", { name: "Tamil" })).toBeNull();
    expect(hidden.queryByRole("option", { name: "Tamil" })).toBeNull();
  });

  it("offers a held-back language the server has switched on for this account (D-855)", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents/languages": {
          languages: [
            { tag: "te-IN", name: "Telugu" },
            { tag: "hi-IN", name: "Hindi" },
            { tag: "en-IN", name: "English (India)" },
            { tag: "ta-IN", name: "Tamil" },
          ],
        },
      }),
    );
    await screen.findByText("Reception");
    const shown = within(card("What it is"));
    expect(await shown.findByRole("checkbox", { name: "Tamil" })).toBeTruthy();
  });

  it("points to the agent's lines and campaigns for the opening once the language is saved (D-838, D-1005)", async () => {
    await renderClientPage(
      page,
      routes({
        "PATCH /v1/agents/agent-1": agent({ language_primary: "hi-IN", reply_languages: ["hi-IN"] }),
        "/v1/agents/agent-1/jobs": {
          agent_id: "agent-1",
          total: 1,
          jobs: [{ id: "line-1", kind: "inbound_line", name: "Front desk", status: "live" }],
        },
      }),
    );

    await screen.findByText("Reception");
    const panel = card("What it is");
    await act(async () => {
      fireEvent.change(within(panel).getByRole("combobox", { name: /Main language/ }), {
        target: { value: "hi-IN" },
      });
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save changes/));
    });
    expect(await within(panel).findByText("Saved. Its notices are now in Hindi.")).toBeTruthy();
    const line = await within(panel).findByRole("link", { name: "Front desk" });
    expect(line.getAttribute("href")).toContain("/inbound/line-1");
  });

  it("offers no save until something has been changed, and Cancel puts it back", async () => {
    const { calls } = await renderClientPage(page, routes());

    await screen.findByText("Reception");
    const panel = card("What it is");
    expect(within(panel).queryByRole("button", { name: /Save changes/ })).toBeNull();

    const nameInput = within(panel).getByLabelText(/^Name/) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: "Front desk" } });
    });
    expect(within(panel).getByRole("button", { name: /Save changes/ })).toBeTruthy();
    await act(async () => {
      fireEvent.click(within(panel).getByRole("button", { name: "Cancel" }));
    });
    expect(nameInput.value).toBe("Reception");
    expect(within(panel).queryByRole("button", { name: /Save changes/ })).toBeNull();
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
  });

  it("shows a rename made elsewhere, and a later save does not undo it", async () => {
    // Pip's `agent_rename` writes at once and the agent read refreshes. The form held a
    // copy of the old name, showed it as an unsaved change and sent it back on the next save.
    let current = agent();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": () => current,
        "PATCH /v1/agents/agent-1": () => current,
      }),
      "acme",
      client,
    );
    await screen.findByText("Reception");
    const panel = card("What it is");

    current = agent({ name: "Front desk" });
    await act(async () => {
      await client.invalidateQueries();
    });
    const nameInput = within(panel).getByLabelText(/^Name/) as HTMLInputElement;
    await waitFor(() => expect(nameInput.value).toBe("Front desk"));
    expect(within(panel).queryByRole("button", { name: /Save changes/ })).toBeNull();

    const replies = within(panel).getByRole("group", { name: "It also replies in" });
    await act(async () => {
      fireEvent.click(within(replies).getByRole("checkbox", { name: "English (India)" }));
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save changes/));
    });
    const patched = calls.find((call) => call.method === "PATCH");
    expect(JSON.parse(patched?.body ?? "{}")).not.toHaveProperty("name");
  });

  it("keeps the owner's typing when a refresh of the agent fails", async () => {
    let fail = false;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": () =>
          fail ? problem(503, { title: "Upstream unavailable", detail: "Try again." }) : agent(),
      }),
      "acme",
      client,
    );
    await screen.findByText("Reception");
    const panel = card("What it is");
    await act(async () => {
      fireEvent.change(within(panel).getByLabelText(/^Name/), { target: { value: "Front desk" } });
    });

    fail = true;
    await act(async () => {
      await client.invalidateQueries();
    });

    await screen.findByText("Try again.");
    const nameInput = within(card("What it is")).getByLabelText(/^Name/) as HTMLInputElement;
    expect(nameInput.value).toBe("Front desk");
  });

  it("keeps an archived agent's details as they were, and says why", async () => {
    // The server refuses the edit (`agent_archived`) because what a retired agent WAS is a
    // record somebody may be reading. A disabled form whose every input is dead is worse
    // than a sentence saying why there is none.
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          status: "archived",
          archived_at: "2026-07-02T09:30:00Z",
          published: false,
        }),
      }),
    );

    await screen.findByText("Reception");
    const panel = card("What it is");
    expect(
      within(panel).queryByRole("button", { name: /Save changes/ }),
    ).toBeNull();
    expect(panel.textContent).toContain("Bring it back to change");
  });
});

describe("Training shows what the agent knows (D-689: the business's knowledge, shared)", () => {
  beforeEach(() => openSection("training"));

  it("counts what it knows exactly as the Knowledge page does (audit W2)", async () => {
    const first = await renderClientPage(page, routes(TRAINING_READS));
    const heading = await screen.findByRole("heading", { level: 3, name: "Facts and answers" });
    const panel = heading.closest("details") as HTMLElement;
    await waitFor(() => expect(panel.querySelector("summary")?.textContent).toMatch(/\d+ things?/));
    const training = panel.querySelector("summary")?.textContent?.match(/(\d+) things?/)?.[1];
    first.unmount();

    await renderClientPage(<KnowledgePage />, {
      ...routes(TRAINING_READS),
      "/v1/agents": [agent()],
      "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
      "/v1/teach/questions": { items: [], open_count: 0 },
    });
    const total = (await screen.findByText(/things? your agents know/)).textContent?.match(/(\d+)/)?.[1];
    expect(training).toBe(total);
  });

  it("lists the business's facts read-only, pinned first, and links to where they are changed", async () => {
    await renderClientPage(page, routes(TRAINING_READS));

    const heading = await screen.findByRole("heading", { level: 3, name: "Facts and answers" });
    const panel = heading.closest("details") as HTMLElement;
    await within(panel).findAllByText("Red chilli powder is ₹120 for 250 g.");
    // Folded to one line (D-893 §6), counted as the Knowledge page counts it: one pinned,
    // one fact, three things learned from the file, three from business details.
    expect(panel.textContent).toContain("8 things");
    const facts = within(within(panel).getAllByRole("list")[0]!)
      .getAllByRole("listitem")
      .map((row) => row.textContent);
    expect(facts).toEqual(["Red chilli powder is ₹120 for 250 g.", "We deliver in Kukatpally."]);
    const link = within(panel).getByRole("link", { name: /Open What your agents know/ });
    expect(link.getAttribute("href")).toBe("/c/acme/knowledge");
  });

  it("says which facts this agent knows by heart and how many it looks up (D-896)", async () => {
    await renderClientPage(page, routes(TRAINING_READS));

    const heading = await screen.findByRole("heading", { level: 4, name: "Knows by heart" });
    const known = heading.closest("section") as HTMLElement;
    // Inside the folded "Facts and answers" section, so the tab stays one line per part (D-893 §6).
    const whatItKnows = screen.getByRole("heading", { level: 3, name: "Facts and answers" });
    expect(whatItKnows.closest("details")?.contains(known)).toBe(true);
    await within(known).findByText(/Knows 1 fact by heart/);
    expect(within(known).getByLabelText("Known by heart")).toBeTruthy();
    expect(known.textContent).toContain("Looks up 1 fact when asked");
  });

  it("hides the split where every fact is in the agent's instructions anyway", async () => {
    await renderClientPage(
      page,
      routes({
        ...TRAINING_READS,
        "/v1/agents/agent-1/known-facts": {
          ...TRAINING_READS["/v1/agents/agent-1/known-facts"],
          applies: false,
        },
      }),
    );
    await screen.findByRole("heading", { level: 3, name: "Facts and answers" });
    await screen.findAllByText("Red chilli powder is ₹120 for 250 g.");
    expect(screen.queryByRole("heading", { level: 4, name: "Knows by heart" })).toBeNull();
  });

  it("does not say the agent was never tested when the last run could not be read", async () => {
    await renderClientPage(
      page,
      routes({
        ...TRAINING_READS,
        "/v1/agents/agent-1/script/tests": problem(503, { title: "Upstream unavailable" }),
      }),
    );
    await screen.findByText("Could not be read");
    expect(screen.queryByText(/Not run yet/)).toBeNull();
  });

  it("is where an old Knowledge or Test link lands", async () => {
    openSection("knowledge");
    await renderClientPage(page, routes(TRAINING_READS));
    const tab = await screen.findByRole("tab", { name: "What it knows" });
    expect(tab.getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("heading", { level: 3, name: "Teach your agents" })).toBeTruthy();
  });
});

describe("the screen when the agent could not be read", () => {
  it("renders the refusal and none of the panels", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": problem(404, {
          title: "Agent not found",
          detail: "We could not find that agent.",
        }),
      }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // Not one sentence about an agent we could not read — every panel below is a claim
    // about a specific agent's phone line.
    expect(container.textContent).not.toContain("What it says");
    expect(container.textContent).not.toContain("Overview");
    expect(container.textContent).not.toContain("What it knows");
    // The way back is still there, because a 404 on a bookmarked agent is the case where a
    // person most needs it.
    expect(screen.getByRole("link", { name: /All agents/ })).toBeTruthy();
  });
});

/**
 * THE HIERARCHY ITSELF (D-657) — the property a "does it render?" test cannot see.
 *
 * REPLACED with D-657. These tests used to pin the SCRIPT as the screen's hero: first
 * heading after the name, and the only `PRIMARY_BUTTON_LG`. The founder's decision made the
 * workspace a settings layout whose header holds the ONE action that moves the agent
 * forward, so two properties are pinned instead: the header holds the single primary, and
 * Overview — the section that opens first — renders the truthful-answer guarantee ABOVE
 * both opening-notice switches (doctrine §8 rule 7). The script keeps its own section,
 * whose entry point is still pinned below.
 */
describe("the header holds the one primary", () => {
  const HEADER_PRIMARY = "bg-action px-4 py-2";

  it("puts a single primary in the header, and no hero-sized button anywhere", async () => {
    // Switching on is the header's switch, so the one filled button is "Put it live", shown
    // only while a staged version waits (D-1017: an autosaved draft is never put live).
    const { container } = await renderClientPage(
      page,
      routes({
        ...SWITCHED_OFF,
        "/v1/agents/agent-1/pending": STAGED,
        "/v1/agents/agent-1/script": {
          script: { ...EMPTY_SCRIPT, opening_line: "Namaskaram." },
          version: 4,
          is_freeform: false,
          has_pending: true,
          standard_variables: [],
        },
      }),
    );

    await screen.findByText("Reception");
    const header = container.querySelector("header") as HTMLElement;
    await screen.findByRole("button", { name: "Put it live" });
    const primaries = [...header.querySelectorAll("a, button")].filter((node) =>
      node.className.includes(HEADER_PRIMARY),
    );
    expect(primaries).toHaveLength(1);
    expect(primaries[0].textContent).toContain("Put it live");
    expect(
      [...container.querySelectorAll("a, button")].filter((node) =>
        node.className.includes("px-5 py-3 text-base"),
      ),
    ).toHaveLength(0);
  });

  it("offers no primary at all on a live agent with nothing waiting", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Reception");
    const header = container.querySelector("header") as HTMLElement;
    expect(
      [...header.querySelectorAll("a, button")].filter((node) =>
        node.className.includes(HEADER_PRIMARY),
      ),
    ).toHaveLength(0);
  });

  it.each(["script", "overview"])(
    "opens an old ?section=%s address on What it says, with a way to give it a job",
    async (old) => {
      openSection(old);
      await renderClientPage(page, routes());

      expect(await screen.findByRole("heading", { name: "Its jobs" })).toBeTruthy();
      expect(screen.getByRole("tab", { name: "What it says" }).getAttribute("aria-selected")).toBe("true");
      // An answer-only agent is offered an Inbound line, never a campaign.
      expect(await screen.findByRole("button", { name: /Answer calls/ })).toBeTruthy();
      expect(screen.queryByRole("link", { name: /Call people/ })).toBeNull();
    },
  );
});

/**
 * THE SETUP CHECKLIST STATES WHAT THE SERVER SAID, AND SAYS SO WHEN IT COULD NOT ASK.
 *
 * The defect these pin: "Add calling credit" read UNCHECKED on an account holding ₹5,000,
 * because the row was inferred from the voice tier rates (null when no credit LOT prices a
 * minute) instead of read from the wallet the dashboard's credit tile reads.
 */
describe("the setup checklist reflects the real state", () => {
  function row(label: string): HTMLElement {
    const li = screen.getByText(label).closest("li");
    expect(li, `no checklist row "${label}"`).not.toBeNull();
    return li as HTMLElement;
  }

  it("counts credit as added when the wallet holds a positive balance, whatever the tier rates say", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/billing/wallet": prepaidWallet({ balance_inr: "5000.00" }),
        // No credit lot prices a minute — the state that used to read as "no credit".
        "/v1/agents/agent-1/pending": settled({
          voice_tier_rates: [
            { voice_tier: "clear", label: "Clear", inr_per_min: null, further_open_lots: 0 },
          ],
        }),
      }),
    );

    await screen.findByText("Add calling credit");
    const credit = row("Add calling credit");
    expect(credit.textContent).toContain("Done");
    expect(credit.textContent).toContain("₹5,000 left");
    expect(within(credit).queryByRole("link", { name: /Top up/ })).toBeNull();
  });

  it("asks for credit when the server says calls have stopped for want of it", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/billing/wallet": prepaidWallet({ balance_inr: "0.00", outbound_stopped: true }),
      }),
    );

    await screen.findByText("Add calling credit");
    const credit = row("Add calling credit");
    expect(credit.textContent).toContain("To do");
    expect(within(credit).getByRole("link", { name: /Top up/ })).toBeTruthy();
  });

  it("says it could not check, rather than 'to do', when the wallet read failed", async () => {
    await renderClientPage(
      page,
      routes({ "/v1/billing/wallet": problem(503, { title: "Service unavailable" }) }),
    );

    await screen.findByText("Add calling credit");
    const credit = row("Add calling credit");
    expect(credit.textContent).toContain("Couldn't check this.");
    expect(credit.textContent).not.toContain("To do");
  });

  it("leaves credit off the list for an account billed by invoice", async () => {
    await renderClientPage(
      page,
      routes({ "/v1/billing/wallet": prepaidWallet({ prepaid: false }) }),
    );

    await screen.findByText("Choose a voice");
    expect(screen.queryByText("Add calling credit")).toBeNull();
  });

  it("names the voice as not chosen when the server says none is set", async () => {
    const none = settled({
      voice: {
        configured: null,
        live: null,
        republish_required: false,
        unnamed_note: null,
        headline: "No voice has been set on this agent.",
      },
    });
    const first = await renderClientPage(page, routes({ "/v1/agents/agent-1/pending": none }));
    await screen.findByText("Choose a voice");
    expect(row("Choose a voice").textContent).toContain("To do");
    first.unmount();

    // …and the Voice section says the same thing, rather than "we cannot say".
    openSection("voice");
    await renderClientPage(page, routes({ "/v1/agents/agent-1/pending": none }));
    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe("None chosen");
    expect(document.body.textContent).toContain("No voice has been set on this agent.");
  });

  it("sends a client without a number to buy one, never to an account manager (D-707)", async () => {
    await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1": agent({ inbound_number_count: 0 }) }),
    );

    await screen.findByText("Give it a phone number to answer");
    const number = row("Give it a phone number to answer");
    expect(number.textContent).not.toContain("account manager");
    expect(number.textContent).toMatch(/Needs a verified business|verify your business first/);
    expect(within(number).getByRole("link", { name: /Get a number|Add credit/ })).toBeTruthy();
  });
});

/**
 * WHAT IS BEHIND A CLICK AND WHAT IS NOT — the disclosure contract (UX-DOCTRINE §3, §8).
 *
 * A rarely-touched panel drifting back into the foreground is how nine equal cards happen
 * again; a COMPLIANCE control drifting behind a disclosure is far worse, and §8 is absolute
 * about it.
 */
describe("progressive disclosure defaults", () => {
  /** Is this panel inside a `<details>` a reader would have to open? */
  function disclosed(title: string): boolean {
    const panel = card(title);
    const details = panel.closest("details");
    return details !== null && !details.hasAttribute("open");
  }

  it("shows Settings as plain sections, like the rest of the agent page", async () => {
    // REDESIGN-2: a headed section with its controls in view, not a closed card.
    openSection("advanced");
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Reception");
    expect(disclosed("What it is")).toBe(false);
    expect(disclosed("Delete this agent")).toBe(false);
    expect(container.querySelector("main details, [role='main'] details")).toBeNull();
  });

  it("shows six plain tabs in one tab list, What it says open first", async () => {
    await renderClientPage(page, routes());
    await screen.findByText("Reception");
    const list = screen.getByRole("tablist", { name: "About this agent" });
    expect(within(list).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "What it says",
      "What it knows",
      "Actions",
      "What it notes",
      "Voice",
      "Settings",
    ]);
    const first = within(list).getByRole("tab", { name: "What it says" });
    expect(first.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(first.id);
  });

  it("moves along the tabs with the arrow keys and opens one with Enter, by its address", async () => {
    await renderClientPage(page, routes());
    await screen.findByText("Reception");
    const first = screen.getByRole("tab", { name: "What it says" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    const knowledge = screen.getByRole("tab", { name: "What it knows" });
    expect(document.activeElement).toBe(knowledge);
    // Manual activation: moving the focus opens nothing until Enter.
    expect(nav.push).not.toHaveBeenCalled();
    fireEvent.keyDown(knowledge, { key: "Enter" });
    expect(nav.push).toHaveBeenCalledWith("/c/acme/agents/agent-1?section=knowledge", { scroll: false });
  });

  it.each([
    ["overview", "What it says"],
    ["script", "What it says"],
    ["training", "What it knows"],
    ["test", "What it knows"],
    ["knowledge", "What it knows"],
    ["captured", "What it notes"],
    ["voice", "Voice"],
    ["calls", "Settings"],
    ["model", "Settings"],
    ["advanced", "Settings"],
  ])("opens the tab that holds an old ?section=%s", async (old, tab) => {
    openSection(old);
    await renderClientPage(page, routes({ ...TRAINING_READS, ...NOTES_READS }));
    expect((await screen.findByRole("tab", { name: tab })).getAttribute("aria-selected")).toBe("true");
  });

  it("shows what each job notes and how its calls end, and sends edits to Lead details", async () => {
    openSection("notes");
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/jobs": agentJobs("agent-1", [
          { kind: "inbound_line", id: "line-1", name: "Main number", status: "draft" },
        ]),
        "/v1/inbound-lines/line-1/notes": {
          agent_id: "agent-1",
          agent_name: "Reception",
          applied_now: false,
          digest: "d1",
          core_fields: [{ key: "name", label: "Name", type: "text", required: false, reason: "" }],
          fields: [{ key: "visit_day", label: "Visit day", type: "date", required: false, reason: "" }],
        },
        "/v1/call-outcomes": {
          max_outcomes: 8,
          agents: [
            {
              id: "agent-1",
              name: "Reception",
              direction: "inbound",
              status: "live",
              draft: null,
              starting: false,
              outcomes: [
                { key: "booked", label: "Booked a visit", meaning: "A day was agreed.", lead_status: "hot" },
              ],
            },
          ],
        },
      }),
    );
    expect(await screen.findByText("Visit day")).toBeTruthy();
    expect(screen.getByText("Name")).toBeTruthy();
    expect(await screen.findByText("Booked a visit")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Change in Lead details" }).getAttribute("href")).toBe(
      "/c/acme/settings/lead-details",
    );
    expect(screen.getByRole("link", { name: "Open line" }).getAttribute("href")).toBe("/c/acme/inbound/line-1");
    // Read-only: one editor per list, and it is on Lead details (D-1029).
    expect(screen.queryByRole("button", { name: /Save/ })).toBeNull();
  });

  it("lists each job with the first thing it says and a link to change it", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/jobs": agentJobs("agent-1", [
          { kind: "inbound_line", id: "line-1", name: "Main number", status: "draft" },
          { kind: "campaign", id: "camp-1", name: "Your first calls", status: "draft" },
        ]),
        "/v1/inbound-lines": {
          lines: [{ id: "line-1", live: true, script: { ...EMPTY_SCRIPT, opening_line: "Namaskaram, Sri Clinic." } }],
        },
        "/v1/campaigns/camp-1/workspace": {
          campaign_id: "camp-1",
          script: { ...EMPTY_SCRIPT, opening_line: "Hello, this is Reception." },
          proposal: null,
        },
      }),
    );
    const list = await screen.findByRole("list", { name: "Its jobs" });
    expect(await within(list).findByText(/Namaskaram, Sri Clinic\./)).toBeTruthy();
    expect(await within(list).findByText(/Hello, this is Reception\./)).toBeTruthy();
    const links = within(list).getAllByRole("link", { name: /Change what it says/ });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/c/acme/inbound/line-1",
      "/c/acme/campaigns/camp-1?tab=script",
    ]);
    expect(within(list).getByText("Answers calls")).toBeTruthy();
    expect(within(list).getByText("Calls people")).toBeTruthy();
  });

  it("puts the calls link in the header with this agent's count", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents/stats": [
          {
            agent_id: "agent-1",
            calls_total: 12,
            calls_connected: 9,
            calls_inbound: 12,
            calls_outbound: 0,
            last_call_at: null,
            outcomes: {},
            status: "live",
          },
        ],
      }),
    );
    const link = await screen.findByRole("link", { name: "Calls (12)" });
    expect(link.getAttribute("href")).toBe("/c/acme/calls?agent_id=agent-1");
  });

  it("opens call handling and the model in Settings from their old addresses", async () => {
    openSection("calls");
    await renderClientPage(page, routes());
    expect((await screen.findByRole("tab", { name: "Settings" })).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("heading", { level: 3, name: "How it handles calls" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: "Model" })).toBeTruthy();
  });

  it("never hides a compliance control behind one", async () => {
    await renderClientPage(page, routes());

    await screen.findByText("Reception");
    expect(disclosed("What it says at the start of every call")).toBe(false);
  });

  it("folds what it knows to a line (D-893)", async () => {
    // Founder, 26 Oct 2026 (PIP-AGENT-PLAN §6): on Training the questions come first and
    // what it knows is one line that opens on click, saying how much it knows when closed.
    openSection("training");
    await renderClientPage(page, routes(TRAINING_READS));
    await screen.findByRole("heading", { level: 3, name: "Facts and answers" });
    expect(disclosed("Facts and answers")).toBe(true);
    expect(await screen.findByText("8 things")).toBeTruthy();
  });

  it("states the tier in force on the Model section before any option", async () => {
    openSection("model");
    await renderClientPage(page, routes());

    await screen.findByText("Reception");
    const row = await screen.findByText("Model it thinks with");
    const summary = row.closest("div.flex") as HTMLElement;
    expect(summary.parentElement?.parentElement?.textContent).toContain("Standard");
  });
});

/**
 * The header's month line: what this agent has been charged this month, from the same
 * `/v1/billing/spend` the Spend screen reads, and only for someone who may read billing.
 */
describe("what this agent spent this month", () => {
  it("names this agent's charge, grouped, from the string the API sent", async () => {
    await renderClientPage(
      page,
      routes({
        [AGENT_SPEND_PATH]: spendThisMonth({
          calls: 3,
          by_agent: [
            { agent_id: "agent-2", agent_name: "Sales", calls: 1, minutes: "2.0000", charged_inr: "90.00" },
            { agent_id: "agent-1", agent_name: "Reception", calls: 2, minutes: "18.5000", charged_inr: "1200.00" },
          ],
        }),
      }),
    );
    await screen.findByText(/₹1,200 this month/);
    expect(screen.queryByText(/₹90/)).toBeNull();
  });

  it("says nothing was spent when the agent has no row this month", async () => {
    await renderClientPage(page, routes());
    await screen.findByText(/Nothing spent this month/);
  });

  it("does not read billing for someone without billing:read", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/me": { ...OWNER, permissions: OWNER.permissions.filter((p) => p !== "billing:read") },
      }),
    );
    await screen.findByText("Reception");
    expect(screen.queryByText(/this month/)).toBeNull();
    expect(calls.some((call) => call.path === AGENT_SPEND_PATH)).toBe(false);
  });
});

/*
 * D-826: the assistant sees a whole tab, the header's way into Training respects unsaved
 * edits, and real calls lead Training while they left questions open.
 */
const seen: { holder: SurfaceHolder | null } = { holder: null };
function SurfaceProbe() {
  seen.holder = useCopilotSurfaceHolder();
  return null;
}

describe("the assistant sees every panel on a tab (D-826)", () => {
  beforeEach(() => {
    seen.holder = null;
  });

  it("reads call handling, the model and what the agent is together on Settings", async () => {
    openSection("settings");
    await renderClientPage(
      <>
        {page}
        <SurfaceProbe />
      </>,
      routes(),
    );
    await screen.findByRole("heading", { level: 3, name: "What it is" });
    await waitFor(() => {
      const surface = seen.holder?.read();
      const facts = surface?.facts?.map((fact) => fact.key) ?? [];
      expect(facts).toEqual(expect.arrayContaining(["agent_id", "call_cap_s", "tier"]));
      expect(surface?.fields.map((field) => field.id)).toEqual(
        expect.arrayContaining(["agent-name", "agent-direction", "agent-language"]),
      );
    });
    expect(seen.holder?.read().title).toBe("Agent: settings (Reception)");
  });

  it("fills a field on its own panel, and keeps the teach box beside the trial number on Training", async () => {
    openSection("training");
    await renderClientPage(
      <>
        {page}
        <SurfaceProbe />
      </>,
      routes(TRAINING_READS),
    );
    await screen.findByRole("heading", { level: 3, name: "Teach your agents" });
    await waitFor(() => expect(seen.holder?.read().fields.map((field) => field.id)).toContain("kb-teach"));
    await act(async () => {
      seen.holder?.read().apply([{ field_id: "kb-teach", value: "We open at 9." }]);
    });
    expect((screen.getByLabelText(/What should your agents know/) as HTMLTextAreaElement).value).toBe(
      "We open at 9.",
    );
  });
});

describe("Training is the checklist first, the rest folded (D-893 §6)", () => {
  beforeEach(() => openSection("training"));

  const OPEN_QUESTION = {
    "/v1/teach/questions?agent_id=agent-1": {
      items: [
        {
          key: "timings",
          question: "When are you open?",
          topic: "Opening hours",
          why: "callers",
          callers: 2,
          times: 2,
          agent_ids: ["agent-1"],
          latest_call_id: "call-1",
          latest_at: "2026-10-18T09:00:00Z",
          example: "Do you open on Sundays?",
          draft: null,
          draft_source_kind: null,
          draft_source_label: null,
          drafting: false,
        },
      ],
      open_count: 1,
    },
  };
  const order = () =>
    screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent?.trim() ?? "");

  it("leads with the questions to answer, then the mistakes on real calls, then Try it, then the folded summaries", async () => {
    await renderClientPage(page, routes({ ...TRAINING_READS, ...OPEN_QUESTION }));
    await screen.findByText("When are you open?");
    const headings = order();
    expect(headings[0]).toBe("Questions to answer");
    expect(headings[1]).toBe("Mistakes on real calls");
    expect(headings.indexOf("Try it")).toBeLessThan(headings.indexOf("Facts and answers"));
    expect(headings.indexOf("Facts and answers")).toBeLessThan(headings.indexOf("Test your agent"));
    // One section runs every test (D-970): no separate saved tests or practice callers.
    expect(headings).not.toContain("Saved tests");
    expect(headings).not.toContain("Practice callers");
    // The tab's badge counts the same list.
    expect((await screen.findByRole("tab", { name: /What it knows/ })).textContent).toContain("1");
  });

  it("runs every test from one section with one run button, the owner's own tests listed inside (D-970)", async () => {
    await renderClientPage(page, routes(TRAINING_READS));
    const toggle = await screen.findByRole("heading", { name: "Test your agent" });
    fireEvent.click(toggle);
    expect(await screen.findByRole("button", { name: "Run the tests" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /^Run/ })).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Your own tests" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Write a test" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Save a test from a call" })).toBeTruthy();
  });

  it("keeps Test your agent open when the run it opened for finishes (audit W2)", async () => {
    const run = (status: "running" | "done") => ({
      available: true,
      unavailable_reason: null,
      cost_note: null,
      history: [],
      latest: {
        id: "run-1",
        status,
        prompt_version: 3,
        is_current: true,
        round: 1,
        retest_of: null,
        auto_improve: false,
        score: { passed: 0, judged: 0, total: 0 },
        results: [],
        improvement: null,
        note: null,
        improving: false,
        created_at: "2026-11-08T10:00:00Z",
        completed_at: status === "done" ? "2026-11-08T10:05:00Z" : null,
      },
    });
    let answer = run("running");
    await renderClientPage(page, routes({ ...TRAINING_READS, "/v1/agents/agent-1/script/tests": () => answer }));
    const panel = (await screen.findByRole("heading", { name: "Test your agent" })).closest("details") as HTMLDetailsElement;
    await waitFor(() => expect(panel.open).toBe(true));
    answer = run("done");
    // The tab polls while a run is going; the finished run is what the owner opened it to read.
    await waitFor(() => expect(screen.queryByText("Running now")).toBeNull(), { timeout: 6000 });
    expect(panel.open).toBe(true);
  }, 10000);

  it("opens on the question a link named", async () => {
    nav.params = new URLSearchParams("section=training&question=timings");
    await renderClientPage(page, routes({ ...TRAINING_READS, ...OPEN_QUESTION }));
    expect(await screen.findByLabelText("Your answer to: When are you open?")).toBeTruthy();
  });
});

describe("the header's Try it asks before leaving unsaved edits (D-826)", () => {
  it("opens the leave-without-saving dialog instead of switching to What it knows", async () => {
    openSection("settings");
    await renderClientPage(page, routes());
    const panel = (await screen.findByRole("heading", { level: 3, name: "What it is" })).closest("section") as HTMLElement;
    await act(async () => {
      fireEvent.change(within(panel).getByLabelText(/^Name/), { target: { value: "Front desk" } });
    });
    const tryIt = screen.getByRole("link", { name: "Try it" });
    expect(tryIt.getAttribute("href")).toBe("/c/acme/agents/agent-1?section=knowledge");
    await act(async () => {
      fireEvent.click(tryIt);
    });
    expect(await screen.findByRole("dialog", { name: "Leave without saving?" })).toBeTruthy();
    expect(nav.push).not.toHaveBeenCalled();
  });
});

describe("Show me around points at what the agent page draws (D-855)", () => {
  it("finds the tabs and Try it the tour steps name", async () => {
    await renderClientPage(page, routes());
    await screen.findByRole("button", { name: "Show me around" });
    const found = Object.fromEntries(TOUR_STEPS.map((step) => [step.id, step.target(document) !== null]));
    // The assistant's launcher is the console header's, which a page render does not mount.
    expect(found).toEqual({ script: true, pip: false, knowledge: true, voice: true, try: true });
  });

  it("is not offered on a deleted agent", async () => {
    await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1": agent({ status: "archived", archived_at: "2026-07-02T09:30:00Z", published: false }) }),
    );
    await screen.findByRole("button", { name: "Bring it back" });
    expect(screen.queryByRole("button", { name: "Show me around" })).toBeNull();
  });
});

describe("Try it on the business or on one of its jobs (founder, 16 Nov 2026)", () => {
  beforeEach(() => openSection("training"));

  const JOBS = agentJobs("agent-1", [
    { kind: "inbound_line", id: "line-1", name: "Main number", status: "published" },
    { kind: "campaign", id: "camp-1", name: "Diwali offers", status: "draft" },
    { kind: "campaign", id: "camp-2", name: "Old customers", status: "running" },
  ]);

  it("tries just the business by default, chatting with no script", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        ...TRAINING_READS,
        "/v1/agents/agent-1/jobs": JOBS,
        "POST /v1/agents/agent-1/try-chat": {
          session: "s-1",
          reply: "We open at nine.",
          looked_up_knowledge: false,
          cut_short: false,
          cost_note: "Replies here are not charged.",
        },
      }),
    );
    const business = (await screen.findByRole("radio", { name: /Just the business/ })) as HTMLInputElement;
    expect(business.checked).toBe(true);
    fireEvent.change(await screen.findByLabelText("What the caller says"), { target: { value: "When do you open?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("We open at nine.")).toBeTruthy();
    const sent = JSON.parse(calls.find((c) => c.path === "/v1/agents/agent-1/try-chat")?.body ?? "{}");
    expect(sent).toEqual({ message: "When do you open?", session: null, business: true });
  });

  it("says the test-call read failed instead of telling a paying account to add credit", async () => {
    await renderClientPage(
      page,
      routes({ ...TRAINING_READS, "/v1/trial": problem(403, { title: "Test calls could not be read" }) }),
    );
    expect(await screen.findByText("Test calls could not be read", {}, { timeout: 8000 })).toBeTruthy();
    expect(screen.queryByText("Test calls open once you add credit. Try the chat.")).toBeNull();
  }, 15000);

  it("links a job to its own test call instead of repeating it", async () => {
    await renderClientPage(page, routes({ ...TRAINING_READS, "/v1/agents/agent-1/jobs": JOBS }));
    fireEvent.click(await screen.findByRole("radio", { name: /Main number/ }));
    expect(screen.getByRole("link", { name: "Open its test call" }).getAttribute("href")).toBe(
      "/c/acme/inbound/line-1#line-test-call",
    );
    // The chat and the call are the business's only; a job is tried where it is written.
    expect(screen.queryByLabelText("What the caller says")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: /Diwali offers/ }));
    expect(screen.getByRole("link", { name: "Open its test call" }).getAttribute("href")).toBe(
      "/c/acme/campaigns/camp-1#campaign-test",
    );

    fireEvent.click(screen.getByRole("radio", { name: /Old customers/ }));
    expect(screen.getByRole("link", { name: "Open the campaign" }).getAttribute("href")).toBe(
      "/c/acme/campaigns/camp-2",
    );
  });

  it("says when no Inbound line or campaign uses it yet", async () => {
    await renderClientPage(page, routes(TRAINING_READS));
    expect(await screen.findByText("No Inbound line or campaign uses it yet.")).toBeTruthy();
  });
});

describe("Overview asks for a job, not a script (founder, 16 Nov 2026)", () => {
  it("offers Inbound and Campaigns while nothing uses the agent", async () => {
    await renderClientPage(page, routes());
    const step = await screen.findByText("Give it a job: an Inbound line or a campaign");
    const row = step.closest("li") as HTMLElement;
    expect(within(row).getByRole("link", { name: "Inbound" }).getAttribute("href")).toBe("/c/acme/inbound");
    expect(within(row).getByRole("link", { name: "Campaigns" }).getAttribute("href")).toBe("/c/acme/campaigns");
  });

  it("marks it done once a line or campaign uses it", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/jobs": agentJobs("agent-1", [
          { kind: "inbound_line", id: "line-1", name: "Main number", status: "draft" },
        ]),
        "/v1/inbound-lines": { lines: [] },
      }),
    );
    const step = await screen.findByText("Give it a job: an Inbound line or a campaign");
    const row = step.closest("li") as HTMLElement;
    expect(within(row).queryByRole("link", { name: "Inbound" })).toBeNull();
  });
});
