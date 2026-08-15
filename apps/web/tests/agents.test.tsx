import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentsPage from "@/app/c/[slug]/agents/page";
import type { Agent } from "@/lib/api/agents";
import type { Lanes, PendingState } from "@/lib/api/publishing";

import { expectTextCount, problem, renderClientPage } from "./harness";

/**
 * The agents screen — where a client checks what their phone line is currently saying.
 *
 * Five things can be wrong here, in falling order of what a wrong render costs:
 *
 * 1. **The staged script shown as the live one.** `agents/publishing.py` opens by
 *    recording that the BACKEND shipped this inversion once already, in both directions
 *    at once. On this screen the same mistake tells an owner that callers are hearing a
 *    script nobody has approved — or that an approved fix has landed when it has not.
 *    The pointers are therefore rendered as labelled data (`live_version` under "Callers
 *    hear now", `staged_version` under "Waiting to be applied"), and the tests below
 *    read the two labels' own values rather than the server's prose, so swapping them
 *    fails here rather than in a support call.
 * 2. **A confident agent roster over a request that never landed.** "No agent set up
 *    yet" is a statement about the client's account; a 503 is a statement about us.
 * 3. **A control that can only be refused.** Every write on this feature is admin-realm
 *    and needs `agents:write`, which NEITHER client role holds (core/rbac.py) and which
 *    D-22 refuses to an impersonating operator. So the correct gate is absence: no Apply,
 *    no Undo, no cap editor, and nothing on this screen that issues a non-GET.
 * 4. **A number this build invented.** The call cap, its bounds and the worst-case cost
 *    are the server's or are not shown — and `null` cost means "we cannot say", never ₹0.
 * 5. **An unknown lane described as immediate.** `lane` is a bare `string` on the wire;
 *    guessing "applies straight away" is a promise about a live phone line.
 */

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  // The full client-owner set (core/rbac.py). `agents:write` is NOT in it, and cannot
  // be: it is admin-realm only. If a future control appears on this screen gated on a
  // permission this fixture holds, that is the review question this fixture asks.
  permissions: [
    "agents:read",
    "calls:read",
    "calls:read_raw",
    "leads:read",
    "leads:write",
    "leads:dispatch",
    "billing:read",
    "org:read",
    "org:manage",
    "kb:write",
  ],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "managed" },
};

function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: "agent-1",
    name: "Reception",
    direction: "inbound",
    status: "live",
    language_primary: "te-IN",
    disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    engine: "bolna",
    published: true,
    extraction_fields: [],
    ...over,
  } as Agent;
}

/** One voice as `GET /v1/agents/{id}/pending` returns it, catalogue entry and all. */
function storedVoice(id: string, label: string): NonNullable<PendingState["voice"]["live"]> {
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
  } as NonNullable<PendingState["voice"]["live"]>;
}

/** No staged edit, and the engine holds the voice the row names: the state an agent
 *  spends most of its life in. */
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
      verified_at: "2026-08-15T09:20:00Z",
      headline: "The voice platform was read back and is running this script and voice.",
    },
    ...over,
  } as PendingState;
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

const LANES: Lanes = {
  precedence_rule: "Script decides content, rules decide conduct, voice only changes delivery.",
  lanes: [
    {
      field: "script",
      lane: "staged",
      precedence: 1,
      why: "The script decides what the agent says. It waits for Apply.",
    },
    {
      field: "voice",
      lane: "live",
      precedence: 3,
      why: "A voice only changes delivery.",
    },
  ],
  call_cap_default_s: 600,
  call_cap_min_s: 60,
  call_cap_max_s: 3600,
} as Lanes;

const page = <AgentsPage params={Promise.resolve({ slug: "acme" })} />;

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/agents": [agent()],
    "/v1/agents/lanes": LANES,
    "/v1/agents/agent-1/pending": settled(),
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

    // The whole feature in two assertions. v9 is staged and v4 is live; a screen that
    // reads the pointers the wrong way round passes every other test in this file.
    expect(factValue("Callers hear now")).toBe("v4");
    expect(factValue("Waiting to be applied")).toBe("v9");

    // …and the sentence under the list must not re-attach "what callers hear" to the
    // version listed above it, which is the staged one. This exact phrasing shipped.
    expect(container.textContent).not.toContain("Callers still hear the version above");
  });

  it("says nothing is live yet rather than inventing a version for a first draft", async () => {
    // `live_version` is null until the first Apply, and the server's headline simply
    // drops the clause. Printing "v0" or falling back to the staged number would claim
    // callers are hearing a script that has never been applied.
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
        "/v1/agents": [agent({ published: false, status: "draft" })],
        "/v1/agents/agent-1/pending": settled({ published: false, agent_status: "draft" }),
      }),
    );

    // Awaited on the PANEL's own sentence: the roster paints first, and asserting after
    // `findByText("Being set up")` would read a card whose publishing panel is still a
    // skeleton — a `not.toContain` that passes because nothing has rendered yet.
    await screen.findByText(/no caller hears it at all/);
    expect(container.textContent).not.toContain("what callers hear right now");
  });
});

describe("what the screen says when it could not read the agents", () => {
  it("renders the refusal and no agent rows", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents": problem(503, {
          title: "Service unavailable",
          detail: "We could not read your agents.",
        }),
      }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // "You have no agents" is a claim about the client's account. We could not even read
    // the list, so it must not appear beside the notice saying so.
    expect(container.textContent).not.toContain("No agent set up yet");
    // Nor may any per-agent panel render from a roster that never arrived: the cap, the
    // cost ceiling and the lane table all hang off an agent existing.
    expect(container.textContent).not.toContain("Longest one call may run");
    expect(container.textContent).not.toContain("How changes take effect");
  });

  it("does not report an agent as settled when the pending read failed", async () => {
    // The reassuring line ("nothing is waiting to go live") is the one an owner acts on
    // — they stop chasing us about an edit. It may only be printed on the server's word.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": problem(503, { title: "Service unavailable" }),
      }),
    );

    await screen.findByRole("alert");
    expect(container.textContent).not.toContain("Nothing is waiting to go live");
    expect(container.textContent).not.toContain("Longest one call may run");
  });

  it("does say the account has no agents when the server said exactly that", async () => {
    // The positive control for the assertion above. Without it, "No agent set up yet is
    // absent on a 503" could pass because the sentence does not exist at all — a negative
    // assertion is only worth what its positive twin proves is reachable.
    const { container } = await renderClientPage(page, routes({ "/v1/agents": [] }));

    await screen.findByText("No agent set up yet");
    // …and the lane table hangs off the roster: explaining how changes reach agents that
    // do not exist yet is noise, and it is one more request for nothing.
    expect(container.textContent).not.toContain("How changes take effect");
  });
});

describe("the controls this session may not use are absent, not waiting to 403", () => {
  it("offers a client owner no Apply, Undo or cap editor", async () => {
    // Apply/Undo/call-cap are `POST|PATCH /v1/admin/tenants/{tid}/agents/{aid}/…` and
    // require `agents:write` — held by `operator`/`superadmin`, by neither client role,
    // and refused outright to an impersonating operator (D-22). Every session that can
    // reach this screen would be refused the click, so the button must not exist: the
    // repo's rule is that a control which can only 403 is worse than no control.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1/pending": STAGED }),
    );

    await screen.findByText("Changes waiting to go live");

    expect(screen.queryByRole("button", { name: /apply/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /undo/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /discard/i })).toBeNull();
    // No editors either — a disabled input for a field only we may change is the same
    // trap wearing a different hat.
    expect(container.querySelectorAll("input, select, textarea")).toHaveLength(0);
    // Nothing on the happy path is clickable at all. `ProblemNotice`'s retry is a button,
    // which is why this asserts on a render where nothing failed.
    expect(container.querySelectorAll("button")).toHaveLength(0);
    // Whoever DOES apply it is named, so the absence reads as an answer rather than a
    // missing feature.
    expect(container.textContent).toContain("account manager");
  });

  it("issues no request that could change the account", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ "/v1/agents/agent-1/pending": STAGED }),
    );

    await screen.findByText("Changes waiting to go live");
    for (const call of calls) {
      expect(call.method, `${call.method} ${call.path} mutates from a read-only screen`).toBe(
        "GET",
      );
      // The admin realm is not reachable from a client screen, whatever session this tab
      // holds — `useApplyChanges` builds an `adminSession()`, and calling it from here
      // would show up as a `/v1/admin/...` path in this list.
      expect(call.path).not.toContain("/v1/admin/");
    }
  });
});

describe("which voice callers are actually hearing", () => {
  /**
   * A voice is TWO facts once it can be changed without being published, and this
   * screen is where a client finds out which one their callers get.
   *
   * They are entitled to it: the catalogue is client-realm readable already ("a client
   * is legally the Principal Entity and should be able to see what their own agent
   * sounds like"), and D-36's ladder is a PRICE ladder — the premium and value rungs
   * bill at different per-minute rates and `usage_events.meta.tts_tier` records which
   * one each call ran on. Changing it stays ours (D-21), so there is no control here.
   */
  it("shows one voice when the calling system is holding the configured one", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Voice callers hear");
    expect(factValue("Voice callers hear")).toBe("Bulbul v3 — premium");
    // No second box: there is one fact, and inventing a "waiting" row for an agent with
    // nothing waiting is how a client learns to ignore the one that matters.
    expect(container.textContent).not.toContain("New voice waiting");
  });

  it("names BOTH voices when one is chosen and not yet published", async () => {
    // The inversion this screen must never ship: a chosen voice rendered as the one
    // callers hear. `set_agent_voice` writes our row and does not touch the engine, so
    // until a publish the two are different — and both are labelled, because a sentence
    // can be read the wrong way round and two `dt`/`dd` pairs cannot.
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
    // `live: null` on a PUBLISHED agent means we have no record of what the calling
    // system is holding. Rendering the configured voice here would be the whole defect:
    // an unverifiable claim about what a caller hears, made to the person paying for it.
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
    // A DIFFERENT null: nothing is on the calling system, so no caller hears anything
    // and nothing is waiting on us. "We cannot say" would be wrong here — we can.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents": [agent({ published: false, status: "draft" })],
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

describe("the numbers and the sentences come from the server", () => {
  it("formats the worst-case cost as grouped rupees from the string the API sent", async () => {
    // `worst_case_call_cost_inr` is an exact NUMERIC crossing the wire as a STRING
    // (hard rule 7). `Number("1500.00")` is how ₹1,500.00 turns into a float on a screen
    // a client checks against their own books; `formatINR` groups the digits Indian-style
    // and never parses them. The raw wire form is asserted ABSENT.
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
      routes({
        "/v1/agents/agent-1/pending": settled({ worst_case_call_cost_inr: null }),
      }),
    );

    await screen.findByText("Most one call can cost you");
    // Null is "we cannot tell you", never "it is free" (publishing.py::_overage_rate) —
    // and never `formatINR`'s "—" either, which is the dash this app prints for a value
    // that is simply absent. This one is absent for a REASON the client can act on.
    expect(factValue("Most one call can cost you")).toBe("We cannot say yet");
    expect(container.textContent).not.toContain("₹0");
  });

  it("reads the call cap and its bounds off the API instead of hardcoding ten minutes", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/agent-1/pending": settled({
          effective_call_cap_s: 330,
          call_cap_is_platform_default: false,
        }),
        "/v1/agents/lanes": {
          ...LANES,
          call_cap_default_s: 900,
          call_cap_min_s: 120,
          call_cap_max_s: 1800,
        },
      }),
    );

    await screen.findByText("How changes take effect");
    expect(factValue("Longest one call may run")).toBe("5 min 30 s");
    expect(container.textContent).toContain("capped at 15 minutes per call by default");
    expect(container.textContent).toContain("between 2 minutes and 30 minutes");
    // The platform's real default, printed for an agent the server said is overridden.
    expect(container.textContent).not.toContain("10 minutes");
  });

  it("puts an unrecognised lane where it claims nothing, not under 'applies straight away'", async () => {
    // `lane` is a bare `string` on `LaneOut`. The old split was staged-versus-everything,
    // so a lane this build has never seen was announced as immediate — a promise about a
    // live phone line made from a value we do not understand.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/lanes": {
          ...LANES,
          lanes: [
            ...LANES.lanes,
            {
              field: "webhook",
              lane: "scheduled",
              precedence: 2,
              why: "Applied at the next maintenance window.",
            },
          ],
        },
      }),
    );

    await screen.findByText("How changes take effect");

    const immediate = screen.getByText("Applies straight away").parentElement;
    expect(immediate?.textContent).toContain("Its voice");
    expect(immediate?.textContent).not.toContain("webhook");
    expect(container.textContent).toContain("Ask your account manager");
    // The unnamed field still appears — a lane the client cannot see is worse than an
    // ugly label (FIELD_LABELS falls through to the field's own name).
    expect(container.textContent).toContain("webhook");
  });
});

describe("the disclosure line, which the law does not let us lose", () => {
  it("renders it verbatim and offers no way to change or empty it", async () => {
    const LINE = "Namaskaram, this is an AI assistant calling for Sri Clinic.";
    const { container } = await renderClientPage(page, routes());

    await screen.findByText(`“${LINE}”`);
    // Hard rule 5 is kept here by having no editor at all: a screen that cannot write it
    // cannot blank it. If an edit control ever lands, this fails first.
    expect(container.querySelectorAll("input, textarea")).toHaveLength(0);
    expect(container.textContent).toContain("it cannot be removed");
  });

  it("calls out a blank opening line instead of rendering an empty quotation", async () => {
    // The column is NOT NULL with `length(disclosure_line) > 0` (agents/models.py,
    // `disclosure_nonempty`) — which whitespace satisfies. A pair of empty quotes reads
    // as "the agent says nothing", the one failure on this card that must not be quiet.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents": [agent({ disclosure_line: "   " })] }),
    );

    await screen.findByText(/no opening line on file/);
    expect(container.textContent).not.toContain("“   ”");
  });
});

describe("what the extraction list promises about a call", () => {
  it("does not tell a client every required field is asked aloud", async () => {
    // `required` means the post-call extraction must produce the field
    // (packages/shared/.../extraction.py) — a call that ends without it still becomes a
    // lead. The old badge said "Always asked", which promised an interrogation the
    // product deliberately does not do, two lines above the sentence saying it never
    // reads a form aloud.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents": [
          agent({
            extraction_fields: [
              {
                key: "visit_reason",
                label: "Reason for visit",
                type: "text",
                required: true,
                description: "",
                enum_values: null,
              },
            ],
          }),
        ],
      }),
    );

    await screen.findByText("Reason for visit");
    expect(container.textContent).not.toContain("Always asked");
    expect(container.textContent).toContain("with that column left empty");
    expectTextCount(container, "Required", 2); // the badge, and the sentence explaining it
  });

  it("says nothing about required fields on an agent that has none", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents": [
          agent({
            extraction_fields: [
              {
                key: "budget",
                label: "Budget",
                type: "number",
                required: false,
                description: "",
                enum_values: null,
              },
            ],
          }),
        ],
      }),
    );

    await screen.findByText("Budget");
    expectTextCount(container, "Required", 0);
  });
});

describe("the page's own chrome", () => {
  it("renders no heading, because the shell already prints one", async () => {
    // The shell prints "Voice agents" from the nav list (layout.tsx). A second heading
    // here is a visible duplicate, and the copy that drifts when the nav is renamed.
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Reception");
    expect(container.querySelectorAll("h1")).toHaveLength(0);
  });
});
