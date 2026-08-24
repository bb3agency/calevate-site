import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentDetailPage from "@/app/c/[slug]/agents/[agentId]/page";
import type { Agent } from "@/lib/api/agents";
import type { PendingState } from "@/lib/api/publishing";

import { problem, renderClientPage } from "./harness";

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
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: "agent-1",
    name: "Reception",
    direction: "inbound",
    status: "live",
    archived_at: null,
    language_primary: "te-IN",
    disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    // D-163: the two notices this agent volunteers, and the switch on each. Both ON by
    // default — that is what a new agent is born with. `opening_line` is the SERVER's
    // composition and is passed as data rather than derived here: the screen renders it
    // verbatim, so a fixture that joined the two sentences itself would be asserting its
    // own arithmetic instead of the contract.
    ai_disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_enabled: true,
    recording_notice_line: "This call is being recorded.",
    recording_notice_enabled: true,
    opening_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
    truthful_answer_rule:
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    engine: "bolna",
    published: true,
    inbound_number_count: 1,
    extraction_fields: [],
    // D-454: inheriting all the way up — what this fixture always meant
    // implicitly, back when an agent had no opinion about its model.
    llm_model: null,
    llm_model_effective: "gpt-4o-mini",
    llm_model_source: "platform",
    ...over,
  };
}

/** One voice as `GET /v1/agents/{id}/pending` returns it, catalogue entry and all. */
type TtsModel = NonNullable<NonNullable<PendingState["voice"]["live"]>["catalog"]>["tts_model"];

/**
 * `id` is the TTS MODEL, and the wire type is a closed two-value union — not a string, so
 * a fixture naming a model this build does not ship does not compile.
 */
function storedVoice(id: TtsModel, label: string): NonNullable<PendingState["voice"]["live"]> {
  return {
    voice_id: id,
    provider: "sarvam",
    catalog: {
      id,
      label,
      provider: "sarvam",
      tts_model: id,
      tier: "premium",
      gender: null,
      languages: ["te-IN"],
      note: "",
      is_default: false,
      verified: false,
    },
  };
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
    precedence_rule: "Script decides content, rules decide conduct, voice only changes delivery.",
    voice: {
      configured: storedVoice("bulbul:v3", "Bulbul v3 — premium"),
      live: storedVoice("bulbul:v3", "Bulbul v3 — premium"),
      republish_required: false,
      headline: "Callers hear Bulbul v3 — premium.",
    },
    engine_verification: {
      state: "applied",
      confirmed: true,
      publishable: true,
      verified_at: "2026-08-15T09:20:00Z",
      headline: "The voice platform was read back and is running this script and voice.",
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
      headline: "Script v9 is waiting to go live (callers currently hear v4).",
      why: "The script decides what the agent says, and a bad version is discovered by a customer on the phone. It waits for Apply.",
    },
  ],
});

const page = (
  <AgentDetailPage params={Promise.resolve({ slug: "acme", agentId: "agent-1" })} />
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
const LLM_DEFAULTS = {
  default_llm_model: null,
  effective_default: "gpt-4o-mini",
  available: [
    {
      model: "gpt-4o-mini",
      provider: "Azure OpenAI",
      platform_cost_inr_per_minute: "0.2400",
      client_surcharge_inr_per_minute: "0",
      is_platform_default: true,
      is_available: true,
      unavailable_reason: null,
    },
  ],
};

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/agents/agent-1": agent(),
    "/v1/agents/agent-1/pending": settled(),
    "/v1/kb/sources": [],
    "/v1/organization/llm-defaults": LLM_DEFAULTS,
    ...over,
  };
}

/** The value rendered under a `dt`, read off the `dd` beside it. */
function factValue(label: string): string {
  const term = screen.getByText(label);
  const value = term.nextElementSibling;
  expect(value, `no <dd> after "${label}"`).not.toBeNull();
  return value?.textContent ?? "";
}

describe("which script callers are actually hearing", () => {
  it("shows the staged version as waiting and the live version as live, not the reverse", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1/pending": STAGED }),
    );

    await screen.findByText("Changes waiting to go live");

    // The whole feature in two assertions. v9 is staged and v4 is live; a screen that reads
    // the pointers the wrong way round passes every other test in this file.
    expect(factValue("Callers hear now")).toBe("v4");
    expect(factValue("Waiting to be applied")).toBe("v9");

    // …and the sentence under the list must not re-attach "what callers hear" to the
    // version listed above it, which is the staged one. This exact phrasing shipped.
    expect(container.textContent).not.toContain("Callers still hear the version above");
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
              headline: "Script v1 is waiting to go live.",
              why: "It waits for Apply.",
            },
          ],
        }),
      }),
    );

    await screen.findByText("Changes waiting to go live");
    expect(factValue("Callers hear now")).toBe("Nothing live yet");
    expect(factValue("Waiting to be applied")).toBe("v1");
    expect(container.textContent).not.toContain("v0");
  });

  it("does not claim callers hear this page when the agent is not on the calling system", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({ published: false, status: "draft" }),
        "/v1/agents/agent-1/pending": settled({ published: false, agent_status: "draft" }),
      }),
    );

    await screen.findByText(/no caller hears it at all/);
    expect(container.textContent).not.toContain("what callers hear right now");
  });

  it("does not report an agent as settled when the pending read failed", async () => {
    // The reassuring line ("nothing is waiting to go live") is the one an owner acts on —
    // they stop chasing us about an edit. It may only be printed on the server's word.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1/pending": problem(503, { title: "Service unavailable" }) }),
    );

    await screen.findByRole("alert");
    expect(container.textContent).not.toContain("Nothing is waiting to go live");
    expect(container.textContent).not.toContain("Longest one call may run");
  });
});

describe("which voice callers are actually hearing", () => {
  /**
   * A voice is TWO facts once it can be changed without being published, and this screen is
   * where a client finds out which one their callers get. They are entitled to it: D-36's
   * ladder is a PRICE ladder — the premium and value rungs bill at different per-minute
   * rates and `usage_events.meta.tts_tier` records which one each call ran on. Changing it
   * stays ours (D-21), so there is no control here.
   */
  it("shows one voice when the calling system is holding the configured one", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe("Bulbul v3 — premium");
    expect(container.textContent).not.toContain("New voice waiting");
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
            configured: storedVoice("bulbul:v2", "Bulbul v2 — value"),
            live: storedVoice("bulbul:v3", "Bulbul v3 — premium"),
            republish_required: true,
            headline: "Callers still hear Bulbul v3 — premium.",
          },
        }),
      }),
    );

    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe("Bulbul v3 — premium");
    expect(factValue("New voice waiting")).toBe("Bulbul v2 — value");
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
            configured: storedVoice("bulbul:v2", "Bulbul v2 — value"),
            live: null,
            republish_required: true,
            headline: "Callers hear whatever voice was last published.",
          },
        }),
      }),
    );

    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe("We cannot say from here");
    expect(container.textContent).not.toContain("Voice callers hearBulbul v2");
    expect(factValue("New voice waiting")).toBe("Bulbul v2 — value");
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
            configured: storedVoice("bulbul:v2", "Bulbul v2 — value"),
            live: null,
            republish_required: false,
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
  it("formats the worst-case cost as grouped rupees from the string the API sent", async () => {
    // `worst_case_call_cost_inr` is an exact NUMERIC crossing the wire as a STRING (hard
    // rule 7). `Number("1500.00")` is how ₹1,500.00 turns into a float on a screen a client
    // checks against their own books; `formatINR` groups the digits Indian-style and never
    // parses them. The raw wire form is asserted ABSENT.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({ worst_case_call_cost_inr: "1500.5" }),
      }),
    );

    await screen.findByText("Most one call can cost you");
    expect(container.textContent).toContain("₹1,500.50");
    expect(container.textContent).not.toContain("₹1500.5");
    expect(container.textContent).not.toContain("$");
  });

  it("says it cannot price a call rather than quoting ₹0 when the plan has no rate", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1/pending": settled({ worst_case_call_cost_inr: null }) }),
    );

    await screen.findByText("Most one call can cost you");
    // Null is "we cannot tell you", never "it is free" (publishing.py::_overage_rate) — and
    // never `formatINR`'s "—" either, which is the dash this app prints for a value that is
    // simply absent. This one is absent for a REASON the client can act on.
    expect(factValue("Most one call can cost you")).toBe("We cannot say yet");
    expect(container.textContent).not.toContain("₹0");
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

describe("the two opening notices, and the answer neither of them reaches (D-163)", () => {
  it("renders the server's opening line verbatim and offers no way to reword it", async () => {
    const OPENING =
      "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.";
    const { container } = await renderClientPage(page, routes());

    await screen.findByText(`“${OPENING}”`);
    // The WORDING is still ours to write (hard rule 5): a client may switch a notice off,
    // and may not retype it into something that no longer discloses. The screen SAYS so
    // rather than leaving a quoted sentence with no control beside it to read as an
    // oversight.
    expect(container.textContent).toContain("cannot be edited here");
    expect(container.textContent).toContain("every agent must have both on file");
  });

  it("puts the truthful-answer guarantee above the switches, in the server's words", async () => {
    // The one sentence that must not be paraphrased on the way to a client: the switches
    // change what the agent VOLUNTEERS, never what it ANSWERS. It comes from the API
    // (`compliance/disclosure.TRUTHFUL_ANSWER_PROMISE`) and is rendered as sent.
    const RULE = "The agent never claims to be human. Ask it and it says so.";
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1": agent({ truthful_answer_rule: RULE }) }),
    );

    // VERBATIM: asserted against a sentence this test invents, so it can only pass if the
    // screen renders what the server sent rather than wording of its own.
    const promise = await screen.findByText(RULE);
    expect(container.textContent).toContain(RULE);
    const switches = screen.getAllByRole("switch");
    expect(switches).toHaveLength(2);
    // Above, not below: two switches read "off" before the guarantee is read is exactly how
    // a client concludes the opposite of what the platform enforces.
    expect(
      promise.compareDocumentPosition(switches[0]) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("says plainly what switching each notice off does NOT do", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          ai_disclosure_enabled: false,
          recording_notice_enabled: false,
          opening_line: "",
        }),
      }),
    );

    await screen.findByText(/opens straight into its script/);
    // Never an empty quotation: a pair of empty quotes reads as "the agent says nothing",
    // which is true of the OPENING and false of the call.
    expect(container.textContent).not.toContain("“”");
    // The two sentences a screen like this most easily omits.
    expect(container.textContent).toContain("Calls are still recorded");
    expect(container.textContent).toContain("still your responsibility under the DPDP Act");
    // And, in both off-states, the agent still answers honestly when asked.
    expect(container.textContent).toContain("the agent still says it is an AI");
    expect(container.textContent).toContain("the agent still says yes");
  });

  it("sends only the switch that moved", async () => {
    // `null` on the other field means "leave it alone" server-side, so a screen that sent
    // both would make one click a read-modify-write race against the other.
    const { calls } = await renderClientPage(
      page,
      routes({
        "PATCH /v1/agents/agent-1/disclosure": {
          agent_id: "agent-1",
          ai_disclosure_enabled: false,
          recording_notice_enabled: true,
          opening_line: "This call is being recorded.",
          engine_synced: true,
          truthful_answer_rule:
            "Whatever these settings say, the agent always answers honestly when a caller asks.",
        },
      }),
    );

    const [aiSwitch] = await screen.findAllByRole("switch");
    await act(async () => {
      fireEvent.click(aiSwitch);
    });

    const patched = calls.find((call) => call.path.endsWith("/disclosure"));
    expect(patched?.method).toBe("PATCH");
    expect(JSON.parse(patched?.body ?? "{}")).toEqual({ ai_disclosure_enabled: false });
  });
});

describe("editing what an agent captures (the extraction variables)", () => {
  /** One extraction field on the wire, with `reason` (the renamed per-field hint). */
  function field(over: Partial<Agent["extraction_fields"][number]> = {}): Agent["extraction_fields"][number] {
    return {
      key: "visit_reason",
      label: "Reason for visit",
      type: "text",
      required: false,
      reason: "",
      enum_values: null,
      ...over,
    };
  }

  /** The whole-list PUT's answer — a new version and the stored fields. */
  function schemaOut(fields: Agent["extraction_fields"], version = 2) {
    return { fields, version, changed: true };
  }

  const captures = "What it captures";

  it("renders the agent's current variables in editable inputs, keys read-only", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          extraction_fields: [
            field({ key: "visit_reason", label: "Reason for visit", type: "text", required: true }),
            field({ key: "budget", label: "Budget", type: "number" }),
          ],
        }),
      }),
    );

    await screen.findByText("Reception");
    const panel = card(captures);
    // The labels are the current values, sitting in inputs — not a static list any more.
    expect(within(panel).getByDisplayValue("Reason for visit")).toBeTruthy();
    expect(within(panel).getByDisplayValue("Budget")).toBeTruthy();
    // The old account-manager disclaimer is gone; the self-serve promise replaces it.
    expect(panel.textContent).not.toContain("test run against real calls");
    expect(panel.textContent).toContain("take effect on the next call");
    // An existing variable's key is shown but not editable — changing it orphans history.
    expect(within(panel).queryByDisplayValue("visit_reason")).toBeNull();
    expect(panel.textContent).toContain("visit_reason");
  });

  it("adds a blank variable when Add variable is pressed", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          extraction_fields: [field({ key: "budget", label: "Budget", type: "number" })],
        }),
      }),
    );

    await screen.findByText("Reception");
    const panel = card(captures);
    expect(within(panel).getAllByLabelText("Name")).toHaveLength(1);
    await act(async () => {
      fireEvent.click(await pressable(panel, /Add variable/));
    });
    expect(within(panel).getAllByLabelText("Name")).toHaveLength(2);
  });

  it("saves the WHOLE list on an edited label and reason", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          extraction_fields: [field({ key: "visit_reason", label: "Reason for visit" })],
        }),
        "PUT /v1/agents/agent-1/extraction-schema": schemaOut([
          field({ key: "visit_reason", label: "Why they called", reason: "route urgent cases first" }),
        ]),
      }),
    );

    await screen.findByText("Reception");
    const panel = card(captures);
    // The inputs are disabled until write access resolves off `/v1/me`; gate on that first,
    // or an edit fired at first paint lands on a dead control (see `pressable`).
    await pressable(panel, /Add variable/);
    await act(async () => {
      fireEvent.change(within(panel).getByLabelText("Name"), {
        target: { value: "Why they called" },
      });
      fireEvent.change(within(panel).getByLabelText(/^Reason/), {
        target: { value: "route urgent cases first" },
      });
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save variables/));
    });

    const put = calls.find((call) => call.method === "PUT");
    expect(put?.path).toBe("/v1/agents/agent-1/extraction-schema");
    // The whole ordered list, not a per-field patch — the edited label and reason ride the
    // existing key.
    expect(JSON.parse(put?.body ?? "{}")).toEqual({
      fields: [
        {
          key: "visit_reason",
          label: "Why they called",
          type: "text",
          required: false,
          reason: "route urgent cases first",
          enum_values: null,
        },
      ],
    });
  });

  it("saves a reason left blank as an empty string, not omitted", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          extraction_fields: [field({ key: "budget", label: "Budget", type: "number" })],
        }),
        "PUT /v1/agents/agent-1/extraction-schema": schemaOut([
          field({ key: "budget", label: "Monthly budget", type: "number" }),
        ]),
      }),
    );

    await screen.findByText("Reception");
    const panel = card(captures);
    await pressable(panel, /Add variable/); // wait for write access before editing
    await act(async () => {
      fireEvent.change(within(panel).getByLabelText("Name"), { target: { value: "Monthly budget" } });
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save variables/));
    });

    const put = calls.find((call) => call.method === "PUT");
    const sent = JSON.parse(put?.body ?? "{}").fields[0];
    expect(sent.reason).toBe("");
    expect("reason" in sent).toBe(true);
  });

  it("toggles required and sends it on the whole list", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          extraction_fields: [field({ key: "visit_reason", label: "Reason for visit", required: false })],
        }),
        "PUT /v1/agents/agent-1/extraction-schema": schemaOut([
          field({ key: "visit_reason", label: "Reason for visit", required: true }),
        ]),
      }),
    );

    await screen.findByText("Reception");
    const panel = card(captures);
    await pressable(panel, /Add variable/); // wait for write access before toggling
    await act(async () => {
      fireEvent.click(within(panel).getByRole("switch"));
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save variables/));
    });

    const put = calls.find((call) => call.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}").fields[0].required).toBe(true);
  });

  it("deletes a variable and saves the remaining list", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          extraction_fields: [
            field({ key: "visit_reason", label: "Reason for visit" }),
            field({ key: "budget", label: "Budget", type: "number" }),
          ],
        }),
        "PUT /v1/agents/agent-1/extraction-schema": schemaOut([
          field({ key: "budget", label: "Budget", type: "number" }),
        ]),
      }),
    );

    await screen.findByText("Reception");
    const panel = card(captures);
    // pressable waits for the delete control to be live (write access resolves off `/v1/me`).
    await act(async () => {
      fireEvent.click(await pressable(panel, /Delete Reason for visit/));
    });
    // The row is gone before we save — proves the delete registered, and that removing a
    // row is itself the change that lights the Save button.
    await waitFor(() => expect(within(panel).queryByDisplayValue("Reason for visit")).toBeNull());
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save variables/));
    });

    const put = calls.find((call) => call.method === "PUT");
    const fields = JSON.parse(put?.body ?? "{}").fields;
    expect(fields).toHaveLength(1);
    expect(fields[0].key).toBe("budget");
  });

  it("surfaces a reserved-key / duplicate-key 422 field by field", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          extraction_fields: [field({ key: "visit_reason", label: "Reason for visit" })],
        }),
        "PUT /v1/agents/agent-1/extraction-schema": problem(422, {
          type: "urn:calevate:validation/extraction_field_reserved_key",
          title: "That id is reserved",
          detail: "One of the variable ids collides with a built-in Leads column.",
          remediation: "Pick a different id for the highlighted variable.",
          fields: [{ field: "status", rule: "reserved", message: "“status” is a built-in column." }],
        }),
      }),
    );

    await screen.findByText("Reception");
    const panel = card(captures);
    await pressable(panel, /Add variable/); // wait for write access before editing
    // Make something change so Save lights, then save into the refusal.
    await act(async () => {
      fireEvent.change(within(panel).getByLabelText("Name"), { target: { value: "Status" } });
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save variables/));
    });

    const alert = await within(panel).findByRole("alert");
    expect(alert.textContent).toContain("built-in Leads column");
    expect(alert.textContent).toContain("Pick a different id");
    // The specific offending field is named, not just the headline.
    expect(alert.textContent).toContain("“status” is a built-in column.");
    // The whole-list PUT was still what was attempted.
    expect(calls.some((call) => call.method === "PUT")).toBe(true);
  });

  it("adds a variable, derives a key from its name, and saves the pair", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1": agent({
          extraction_fields: [field({ key: "visit_reason", label: "Reason for visit" })],
        }),
        "PUT /v1/agents/agent-1/extraction-schema": schemaOut([
          field({ key: "visit_reason", label: "Reason for visit" }),
          field({ key: "call_back_time", label: "Call back time", type: "text" }),
        ]),
      }),
    );

    await screen.findByText("Reception");
    const panel = card(captures);
    await act(async () => {
      fireEvent.click(await pressable(panel, /Add variable/));
    });
    const names = within(panel).getAllByLabelText("Name");
    await act(async () => {
      fireEvent.change(names[names.length - 1], { target: { value: "Call back time" } });
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Save variables/));
    });

    const put = calls.find((call) => call.method === "PUT");
    const fields = JSON.parse(put?.body ?? "{}").fields;
    expect(fields).toHaveLength(2);
    // The new row's key was slugified from its name.
    expect(fields[1]).toEqual({
      key: "call_back_time",
      label: "Call back time",
      type: "text",
      required: false,
      reason: "",
      enum_values: null,
    });
  });
});

describe("the controls this session may not use are absent, not waiting to 403", () => {
  it("offers no Apply, Undo or cap editor", async () => {
    // Apply/Undo/call-cap are `POST|PATCH /v1/admin/tenants/{tid}/agents/{aid}/…` and
    // require `agents:write` — held by `operator`/`superadmin`, by neither client role, and
    // refused outright to an impersonating operator (D-22). Every session that can reach
    // this screen would be refused the click, so the button must not exist: the repo's rule
    // is that a control which can only 403 is worse than no control.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1/pending": STAGED }),
    );

    await screen.findByText("Changes waiting to go live");
    expect(screen.queryByRole("button", { name: /^apply/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /undo/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /discard/i })).toBeNull();
    // Whoever DOES apply it is named, so the absence reads as an answer rather than a
    // missing feature.
    expect(container.textContent).toContain("account manager");
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
async function pressable(panel: HTMLElement, name: RegExp): Promise<HTMLElement> {
  const button = within(panel).getByRole("button", { name });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  return button;
}

/** The card with this heading, so a claim is read off the panel it is about. */
function card(title: string): HTMLElement {
  const heading = screen.getByRole("heading", { name: title });
  const section = heading.closest("section");
  expect(section, `no <section> around "${title}"`).not.toBeNull();
  return section as HTMLElement;
}

describe("switching an agent on, off and into the archive (D-440)", () => {
  it("offers a live agent only the moves the server's transition table allows", async () => {
    await renderClientPage(page, routes());

    await screen.findByText("Reception");
    const panel = card("Switching it on and off");
    // `live -> {paused, archived}` (lifecycle.AGENT_TRANSITIONS). "Switch on" is not one of
    // them, and offering it is a click that could only ever be refused.
    expect(within(panel).getByRole("button", { name: /Switch off/ })).toBeTruthy();
    expect(within(panel).getByRole("button", { name: /Archive/ })).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: /Switch on/ })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Bring it back/ })).toBeNull();
  });

  it("offers an archived agent a restore and nothing else, and says it comes back switched off", async () => {
    // `archived -> {paused}` only: a restore never puts an agent straight back on the
    // phone, because the voice platform may have drifted while it sat retired and only a
    // publish can establish what it is holding.
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
    const panel = card("Switching it on and off");
    expect(within(panel).getByRole("button", { name: /Bring it back/ })).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: /Archive/ })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Switch off/ })).toBeNull();
    expect(panel.textContent).toContain("comes back switched OFF");
  });

  it("restates what archiving does before it does it, and only then posts", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "POST /v1/agents/agent-1/archive": {
          agent_id: "agent-1",
          status: "archived",
          changed: true,
          numbers_released: 2,
        },
      }),
    );

    await screen.findByText("Reception");
    const panel = card("Switching it on and off");

    // FIRST PRESS: the consequences, no request. The one a client most needs is that
    // nothing is deleted — an owner who believes archiving erases their call history will
    // leave a dead agent switched off forever instead.
    await act(async () => {
      fireEvent.click(await pressable(panel, /^Archive…$/));
    });
    expect(panel.textContent).toContain("Nothing is deleted");
    expect(panel.textContent).toContain("no longer be put on a campaign");
    expect(calls.some((call) => call.method === "POST")).toBe(false);

    // SECOND PRESS: the move.
    await act(async () => {
      fireEvent.click(await pressable(panel, /Archive this agent/));
    });
    const posted = calls.find((call) => call.method === "POST");
    expect(posted?.path).toBe("/v1/agents/agent-1/archive");
  });

  it("announces the archive consequences and leaves the keyboard on the control", async () => {
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
    await renderClientPage(page, routes());
    await screen.findByText("Reception");
    const panel = card("Switching it on and off");

    const trigger = await pressable(panel, /^Archive…$/);
    // Focused the way a keyboard user arrives at it, then activated. `fireEvent.click`
    // alone would prove nothing about focus: it does not move it.
    await act(async () => {
      (trigger as HTMLButtonElement).focus();
      fireEvent.click(trigger);
    });

    const announced = within(panel).getByRole("status");
    expect(announced.textContent).toContain("Nothing is deleted");

    const armed = within(panel).getByRole("button", { name: /Archive this agent/ });
    expect(document.activeElement, "the keyboard was dropped by the confirm step").toBe(armed);

    // And the way out is reachable too — a confirmation a keyboard user can enter and not
    // leave is worse than no confirmation.
    await act(async () => {
      fireEvent.click(within(panel).getByRole("button", { name: /Keep it/ }));
    });
    expect(within(panel).queryByRole("status")).toBeNull();
    expect(within(panel).getByRole("button", { name: /^Archive…$/ })).toBeTruthy();
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
          remediation: "Ask your account manager to write its script.",
        }),
      }),
    );

    await screen.findByText("Reception");
    const panel = card("Switching it on and off");
    await act(async () => {
      fireEvent.click(await pressable(panel, /Switch on/));
    });

    const alert = await within(panel).findByRole("alert");
    // `ApiProblem` leads with `detail` (falling back to `title`), and `ProblemNotice`
    // prints the remediation under it — so BOTH halves are asserted: what happened, and
    // what the client can do about it. A refusal with no second line is a dead end.
    expect(alert.textContent).toContain("Nothing has been written for it to say.");
    expect(alert.textContent).toContain("Ask your account manager to write its script.");
  });
});

describe("changing what an agent is", () => {
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

  it("will not save when nothing has been changed", async () => {
    const { calls } = await renderClientPage(page, routes());

    await screen.findByText("Reception");
    const panel = card("What it is");
    const save = within(panel).getByRole("button", { name: /Save changes/ });
    expect(save.hasAttribute("disabled")).toBe(true);
    expect(panel.textContent).toContain("Nothing has been changed yet");
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
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
    expect(within(panel).queryByRole("button", { name: /Save changes/ })).toBeNull();
    expect(panel.textContent).toContain("Bring it back first");
  });
});

describe("teaching the agent", () => {
  it("files a submission against THIS agent, with no picker to get wrong", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "POST /v1/kb/sources": { id: "src-1", status: "pending_approval", version: 1 },
      }),
    );

    await screen.findByText("What it knows");
    const panel = card("What it knows");
    await act(async () => {
      fireEvent.change(within(panel).getByLabelText("What this is about"), {
        target: { value: "Clinic hours" },
      });
      fireEvent.change(within(panel).getByLabelText("What the agent should say"), {
        target: { value: "We are open 9am to 7pm, Monday to Saturday." },
      });
    });
    await act(async () => {
      fireEvent.click(await pressable(panel, /Submit for review/));
    });

    // Matched on the METHOD too: `/v1/kb/sources` is also the LIST read this panel makes
    // on mount, and `find` on the path alone returns that GET every time.
    const posted = calls.find(
      (call) => call.path === "/v1/kb/sources" && call.method === "POST",
    );
    expect(posted, "no POST to /v1/kb/sources").toBeTruthy();
    expect(JSON.parse(posted?.body ?? "{}").agent_id).toBe("agent-1");
  });

  it("shows only this agent's knowledge, not the whole account's", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/kb/sources": [
          {
            id: "s1",
            agent_id: "agent-1",
            name: "Clinic hours",
            kind: "text",
            status: "pending_approval",
            version: 1,
            is_active: false,
            published_at: null,
            chunks: 2,
          },
          {
            id: "s2",
            agent_id: "someone-else",
            name: "Другой agent's pricing",
            kind: "text",
            status: "approved",
            version: 1,
            is_active: true,
            published_at: "2026-08-01T00:00:00Z",
            chunks: 3,
          },
        ],
      }),
    );

    await screen.findByText("Clinic hours");
    expect(container.textContent).not.toContain("Другой agent's pricing");
    expect(within(card("What it knows")).getByText("In review")).toBeTruthy();
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
    expect(container.textContent).not.toContain("Switching it on and off");
    expect(container.textContent).not.toContain("What it knows");
    // The way back is still there, because a 404 on a bookmarked agent is the case where a
    // person most needs it.
    expect(screen.getByRole("link", { name: /All agents/ })).toBeTruthy();
  });
});
