import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentPromptPage from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page";
import type { AgentVoiceState } from "@/lib/api/publishing";
import { VOICES_PATH, type OfferedVoice, type VoiceCatalogue } from "@/lib/api/voices";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * Voice selection on the agent screen — `GET /v1/agents/voices` finally has a consumer.
 *
 * The catalogue was readable over the API and selectable nowhere: the persona catalogue
 * (one voice quality, the single-tier voice decision) existed as data, the admin write
 * existed (`PATCH …/agents/{id}/voice`), and no
 * screen joined them. It lives on this screen because voice is agent CONFIGURATION and the
 * write is admin-realm `agents:write` (D-21: which voice speaks Telugu well is an ear
 * test, so it routes through us) — the same gate every other control here is behind.
 *
 * Four things worth pinning:
 *
 * 1. **The catalogue is read through the tenant's impersonation session.** `list_voices` is
 *    `realm="any"`, and `current_any` consults the admin realm only when the impersonation
 *    header is present — so an admin session with no header is rejected on a `/v1/agents/…`
 *    path even for static data. Getting this wrong produces a 401 on a screen that
 *    otherwise looks fine.
 * 2. **A failed catalogue read is a refusal, never an empty `<select>`** (BUILD-LOG §52).
 *    A picker with no options reads as "this agent has no voices available", which is a
 *    claim about the product made from a dead request.
 * 3. **CONFIGURED IS NOT LIVE, and both are on screen.** This is the whole reason the
 *    panel is more than a dropdown. `PATCH .../voice` writes our row and does not touch
 *    the engine, so a published agent keeps its old voice until the next publish. The
 *    select pre-selects `voice.configured` — the thing being edited — while the panel
 *    names `voice.live` beside it as what callers actually hear. The panel used to say it
 *    could not report the voice in force at all; the fix was to make the server answer,
 *    not to start guessing, and the tests below fail if either half goes missing.
 * 4. **The save does not reach the engine, and the screen prints the server's own sentence
 *    about that.** `publish_agent` re-reads the column, so a live agent keeps its old
 *    voice until the next publish — `republish_required` and `next_step` are the server's
 *    answer and are not paraphrased here.
 */

const TENANT = "0192f0aa-8888-7000-8000-0000000000a1";
const AGENT = "0192f0aa-8888-7000-8000-0000000000b2";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const ME_PATH = "/v1/admin/me";
const HISTORY_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/prompt`;
const PENDING_PATH = `/v1/agents/${AGENT}/pending`;
const LANES_PATH = "/v1/agents/lanes";
const EXPERIMENT_PATH = `/v1/agents/${AGENT}/experiment`;
const SET_VOICE_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/voice`;

function voice(over: Partial<OfferedVoice> = {}): OfferedVoice {
  return {
    id: "bulbul:v3:anushka",
    label: "Anushka",
    provider: "sarvam",
    tts_model: "bulbul:v3",
    // The SPEAKER, which the catalogue now names separately from the model (D-358). An id
    // is `<tts_model>:<speaker>`; before the split this fixture's `id` was the model.
    speaker: "anushka",
    gender: "female",
    languages: ["te-IN", "hi-IN", "en-IN"],
    note: "Warm, unhurried; the default for Telugu receptionists.",
    is_default: true,
    verified: false,
    // D-547 made the catalogue two-tier, so a row now carries its own verdict: whether a
    // client may pick it, and — when they may not — the sentence saying why. A Sarvam row
    // is always offerable; the Cartesia rows are the ones that can arrive refused.
    offerable: true,
    unavailable_reason: null,
    // The name a HUMAN reads for this quality, and the only one: `provider` names the
    // VENDOR, keys the money and the metering, and never reaches a screen (founder,
    // 7 Sep 2026). The server owns the label — `billing/rates.py::VOICE_TIER_LABELS` —
    // so this fixture spells the wire, not a second table.
    tier_label: "Clear",
    ...over,
  };
}

// Two PERSONAS on the one Sarvam voice quality: same Bulbul v3 model, different speakers.
// The Cartesia tier is a SECOND quality alongside these (D-547) and this fixture does not
// carry one — the picker's two-tier behaviour is covered where the picker is built.
const VOICES: OfferedVoice[] = [
  voice(),
  voice({
    id: "bulbul:v3:vidya",
    label: "Vidya",
    speaker: "vidya",
    gender: "female",
    is_default: false,
    verified: true,
    note: "A brisker, more formal read; still Bulbul v3.",
  }),
];

/** One STUDIO-tier voice, i.e. the second provider's — the tier that can arrive refused. */
function studio(over: Partial<OfferedVoice> = {}): OfferedVoice {
  return voice({
    id: "sonic-3.5:ananya",
    label: "Ananya",
    provider: "cartesia",
    tts_model: "sonic-3.5",
    speaker: "ananya",
    tier_label: "Studio",
    is_default: false,
    verified: true,
    note: "A studio read; Telugu-English mixing is not documented for this one.",
    ...over,
  });
}

/** THE REFUSAL AS `offerable_voices()` COMPOSES IT — `voice_offer.py::
 *  NO_ATTESTED_TTS_PRICE_REASON`, read 7 Sep 2026. Copied here as a fixture is copied: the
 *  screen prints whatever sentence arrives, and this test proves it prints it whole. */
const NO_PRICE_REASON =
  "nobody has recorded what the Cartesia voice tier costs on this account, and an " +
  "unpriced minute is unmetered spend rather than a free one — attest the Cartesia TTS " +
  "price in the ops console";

/** The two tiers, the second one refused: the state this deployment is actually in. */
const TWO_TIER_CATALOGUE: VoiceCatalogue = {
  control: "ours",
  selectable: true,
  voices: [...VOICES, studio({ offerable: false, unavailable_reason: NO_PRICE_REASON })],
  note: "Pick the voice this agent speaks in.",
};

/**
 * The catalogue AS THE SERVER ANSWERS IT (D-93): the rows AND the verdict about them.
 *
 * It stopped being a bare `Voice[]` because a bare list cannot say "no selection here,
 * and that is normal" — its only way to express it is `[]`, which this very panel renders
 * as "this agent has no voices available", a claim about the product rather than about the
 * engine. `selectable` and `control` carry the verdict; `note` is the sentence to print.
 */
const CATALOGUE: VoiceCatalogue = {
  control: "ours",
  selectable: true,
  voices: VOICES,
  note: "Pick the voice this agent speaks in.",
};

/** The same endpoint on an engine that supplies its own voices — no rows, and a reason. */
const DICTATED_CATALOGUE: VoiceCatalogue = {
  control: "engine",
  selectable: false,
  voices: [],
  note: "The voice platform in use supplies its own voices, so a voice cannot be chosen here. Nothing is wrong with this agent.",
};

/** One stored voice as `GET /v1/agents/{id}/pending` answers it. */
function stored(id: string): NonNullable<AgentVoiceState["configured"]> {
  return {
    voice_id: id,
    provider: "sarvam",
    catalog: VOICES.find((entry) => entry.id === id) ?? null,
  };
}

/**
 * The default agent for these tests: published, and the engine is holding the voice the
 * row says it is. The interesting cases override it.
 */
const VOICE_IN_SYNC: AgentVoiceState = {
  configured: stored("bulbul:v3:anushka"),
  live: stored("bulbul:v3:anushka"),
  republish_required: false,
  headline: "Callers hear Anushka — the voice platform is holding the configured voice.",
};

function pendingRoute(voiceState: AgentVoiceState, tierRates?: unknown) {
  return {
    // ⚠ THE FIELD THAT IS NOT ON THE WIRE YET (the handoff). Spread rather than declared,
    // because `PendingOut` does not carry it in this build's schema and inventing a
    // declaration would be the guess `readVoiceTierRates` exists to refuse.
    ...(tierRates === undefined ? {} : { voice_tier_rates: tierRates }),
    agent_id: AGENT,
    agent_status: "live",
    published: true,
    has_pending: false,
    pending: [],
    effective_call_cap_s: 600,
    call_cap_is_platform_default: true,
    worst_case_call_cost_inr: null,
    precedence_rule: "Script decides content.",
    voice: voiceState,
    engine_verification: {
      state: "applied",
      confirmed: true,
      verified_at: "2026-08-15T09:20:00Z",
      headline: "The voice platform was read back and is running this script and voice.",
    },
  };
}

function render(over: Partial<Routes> = {}) {
  return renderAdminRoute(
    <AgentPromptPage params={routeParams({ tenantId: TENANT, agentId: AGENT })} />,
    {
      [TENANT_PATH]: { id: TENANT, name: "Sunrise Clinic", slug: "sunrise" },
      [ME_PATH]: {
        realm: "admin",
        user_id: "0192f0aa-8888-7000-8000-0000000000f2",
        role: "operator",
        permissions: ["agents:read", "agents:write"],
      },
      [HISTORY_PATH]: [],
      [PENDING_PATH]: pendingRoute(VOICE_IN_SYNC),
      [LANES_PATH]: {
        precedence_rule: "Script decides content.",
        lanes: [],
        call_cap_default_s: 600,
        call_cap_min_s: 60,
        call_cap_max_s: 3600,
      },
      [EXPERIMENT_PATH]: {
        agent_id: AGENT,
        rules: {
          metrics: [{ key: "call_outcome_resolved", label: "calls the agent resolved" }],
          default_metric: "call_outcome_resolved",
          minimum_calls_per_variant: 40,
          split_min_bp: 500,
          split_total_bp: 10000,
          peeking_caveat: "The 95% confidence is per reading.",
        },
        experiment: null,
      },
      [VOICES_PATH]: CATALOGUE,
      ...over,
    },
  );
}

/**
 * This account's per-tier rates as the pending read will carry them (`voice_tier_rates`).
 *
 * ⚠ NOT ON THE WIRE YET — the lots API is another lane's, and this fixture is the exact
 * shape reported as the handoff. `lib/api/voices.readVoiceTierRates` validates it at the
 * seam, so a build whose API omits the field renders no price at all, which is the case
 * the last test in this describe pins.
 */
const TIER_RATES = [
  { provider: "sarvam", label: "Clear", inr_per_min: "5.0000", further_open_lots: 0 },
  { provider: "cartesia", label: "Studio", inr_per_min: "8.0000", further_open_lots: 2 },
];

/** One picker row. Its accessible name is the whole row — persona, languages, note and the
 *  refusal — which is exactly what a screen reader announces, so it is what we match on. */
function voiceRow(name: RegExp): HTMLInputElement {
  return screen.getByRole("radio", { name }) as HTMLInputElement;
}

describe("the voice panel", () => {
  it("reads the catalogue through the tenant's impersonation session", async () => {
    const { calls } = await render();

    await screen.findByRole("radio", { name: /Anushka/ });
    const read = calls.filter((call) => call.path === VOICES_PATH);
    expect(read).toHaveLength(1);
    // The header IS the mechanism: without it `current_any` falls through to the client
    // verifier and rejects the admin token, on an endpoint that touches no tenant data.
    expect(read[0]!.headers["X-Impersonate-Org"]).toBe("sunrise");
  });

  it("offers every catalogue entry and marks the unverified ones", async () => {
    const { container } = await render();

    await screen.findByRole("radio", { name: /Anushka/ });
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(voiceRow(/Anushka/).value).toBe("bulbul:v3:anushka");
    expect(voiceRow(/Vidya/).value).toBe("bulbul:v3:vidya");
    // The catalogue carries `verified: false` until the pilot confirms the engine accepts
    // the string (OPERATIONS §2 gate 3). Rendered, not hidden — and on the row itself, so
    // it is part of the accessible name a screen reader announces for that option.
    expect(container.textContent).toContain("Not yet heard on a live call");
    expect(voiceRow(/Anushka/).labels?.[0]?.textContent).toContain("Not yet heard");
    expect(voiceRow(/Vidya/).labels?.[0]?.textContent).not.toContain("Not yet heard");
  });

  it("pre-selects the voice the agent is configured with", async () => {
    // The gap this slice closed. `voice.configured` is the thing the operator is
    // editing, so it is what the select opens on — not `voice.live` (the past), not the
    // catalogue's `is_default` (D-36's written default, not this agent's state), and not
    // a blank, which invites an operator to re-pick a value that is already set.
    const { container } = await render();

    await screen.findByRole("radio", { name: /Anushka/ });
    expect(voiceRow(/Anushka/).checked).toBe(true);
    expect(voiceRow(/Vidya/).checked).toBe(false);
    // The detail block follows the selection without anyone touching the control.
    expect(container.textContent).toContain(
      "Warm, unhurried; the default for Telugu receptionists.",
    );
  });

  it("shows an agent with no voice set as exactly that, with nothing pre-selected", async () => {
    // A blank select is still correct for an agent nobody has configured — but it is now
    // a state the SERVER reported, not a state the screen could not read.
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: null,
        live: null,
        republish_required: false,
        headline: "No voice has been set on this agent.",
      }),
    });

    await screen.findByRole("radio", { name: /Anushka/ });
    expect(screen.getAllByRole("radio").every((radio) => !(radio as HTMLInputElement).checked)).toBe(
      true,
    );
    expect(container.textContent).toContain("No voice has been set on this agent.");
    expect(container.textContent).toContain("None set");
  });

  it("names the LIVE voice and the CONFIGURED one separately when they differ", async () => {
    // The distinction this panel exists for. A voice change lands in our row and stops:
    // `publish_agent` re-reads the column, so the caller keeps hearing the old voice.
    // Showing one value and calling it "the voice" is the defect — so both are rendered
    // as labelled data, and the server's own sentence sits above them.
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: stored("bulbul:v3:vidya"),
        live: stored("bulbul:v3:anushka"),
        republish_required: true,
        headline: "Callers still hear Anushka; Vidya reaches them at the next publish.",
      }),
    });

    await screen.findByRole("radio", { name: /Vidya/ });
    // Pre-selection follows CONFIGURED — the operator edits the configuration.
    expect(voiceRow(/Vidya/).checked).toBe(true);
    expect(voiceRow(/Anushka/).checked).toBe(false);

    expect(container.textContent).toContain("Callers hear now");
    expect(container.textContent).toContain("Anushka (bulbul:v3)");
    expect(container.textContent).toContain("Configured");
    expect(container.textContent).toContain("Vidya (bulbul:v3)");
    // The server's sentence, printed rather than paraphrased.
    expect(container.textContent).toContain(
      "Callers still hear Anushka; Vidya reaches them at the next publish.",
    );
    // And WHO closes the gap. Only a publish does; nothing on this screen is it.
    expect(container.textContent).toContain(
      "Publishing this agent is what moves the voice callers hear.",
    );
  });

  it("says a published agent's live voice is unrecorded rather than calling it in sync", async () => {
    // An agent published before the server recorded what it sent. "We cannot prove it"
    // is not "nothing is live" and is certainly not "in sync" — the server still asks
    // for a republish, and the screen must not soften that into a green state.
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: stored("bulbul:v3:vidya"),
        live: null,
        republish_required: true,
        headline:
          "Callers hear whatever voice was last published; we have no record of which. Vidya reaches them at the next publish.",
      }),
    });

    await screen.findByRole("radio", { name: /Vidya/ });
    expect(container.textContent).toContain("Not recorded — publish to be sure");
    expect(container.textContent).toContain("we have no record of which");
  });

  it("says an unpublished agent has no live voice at all", async () => {
    // A different null from the one above, and a different sentence: nothing is on the
    // engine, so no caller hears anything and no republish is owed.
    const { container } = await render({
      [PENDING_PATH]: {
        ...pendingRoute({
          configured: stored("bulbul:v3:vidya"),
          live: null,
          republish_required: false,
          headline:
            "This agent is not on the voice platform yet; publishing it will use Vidya.",
        }),
        published: false,
        agent_status: "draft",
      },
    });

    await screen.findByRole("radio", { name: /Vidya/ });
    expect(container.textContent).toContain("Nothing — not on the voice platform yet");
    expect(container.textContent).not.toContain(
      "Publishing this agent is what moves the voice callers hear.",
    );
  });

  it("shows the chosen voice's detail before it is saved", async () => {
    const { container } = await render();

    await screen.findByRole("radio", { name: /Vidya/ });
    fireEvent.click(voiceRow(/Vidya/));

    await waitFor(() =>
      expect(container.textContent).toContain("A brisker, more formal read; still Bulbul v3."),
    );
    expect(container.textContent).toContain("te-IN, hi-IN, en-IN");
    // The commit block names the QUALITY, in the server's word for it — never the vendor.
    expect(container.textContent).toContain("Clear voice");
  });

  it("names the tenant in the PATH and reports that a republish is still needed", async () => {
    // The tenant is in the URL, not the body: an admin principal has no tenant of its
    // own, and the one way it could get one — impersonation — is refused for every
    // mutation by D-22. It used to ride in the body on `PATCH /v1/agents/{id}/voice`,
    // which made this the only admin-realm route in the client path space; the write now
    // sits beside publish, apply, undo and the call cap under
    // `/v1/admin/tenants/{tenant_id}/agents/{agent_id}/…`.
    const { container, calls } = await render({
      [SET_VOICE_PATH]: {
        agent_id: AGENT,
        voice: voice({ id: "bulbul:v3:vidya", label: "Vidya", speaker: "vidya" }),
        agent_status: "live",
        published: true,
        engine_synced: false,
        live_voice_id: "bulbul:v3:anushka",
        republish_required: true,
        next_step:
          "Publish the agent to send this voice to the engine — until then callers hear the previous voice.",
      },
    });

    await screen.findByRole("radio", { name: /Vidya/ });
    fireEvent.click(voiceRow(/Vidya/));
    fireEvent.click(screen.getByRole("button", { name: "Set voice" }));

    await waitFor(() => expect(calls.some((c) => c.path === SET_VOICE_PATH)).toBe(true));
    const write = calls.find((c) => c.path === SET_VOICE_PATH)!;
    expect(write.method).toBe("PATCH");
    // ONE field. The tenant is in the path the call was made to (`SET_VOICE_PATH`), and
    // sending it twice would be two places to disagree.
    expect(JSON.parse(write.body!)).toEqual({ voice_id: "bulbul:v3:vidya" });
    // The admin write is NOT impersonating — the impersonation header on a mutation is a
    // guaranteed 403 under D-22.
    expect(write.headers["X-Impersonate-Org"]).toBeUndefined();

    // The server's own sentence, printed rather than paraphrased: a live agent keeps its
    // old voice until someone publishes, and implying otherwise is the expensive lie.
    await waitFor(() =>
      expect(container.textContent).toContain(
        "Publish the agent to send this voice to the engine",
      ),
    );
    expect(container.textContent).toContain("Saved — Vidya (bulbul:v3)");

    // And the read that feeds the "in force" block is refetched, because the write moved
    // `voice.configured` and deliberately left `voice.live` alone. Without this the panel
    // would keep showing the previous configuration next to the sentence saying it just
    // changed.
    await waitFor(() =>
      expect(calls.filter((c) => c.path === PENDING_PATH).length).toBeGreaterThan(1),
    );
  });

  it("states the reason, not an error, when the engine supplies its own voices", async () => {
    // D-93. THREE things must all be true at once, and each of them is a way the screen
    // used to be able to lie:
    //
    //  - no picker. A dropdown listing Bulbul entries against an engine that only speaks
    //    its own voices is a screen offering a choice the caller will never hear. Not
    //    rendered-and-disabled either: a disabled list still says "these are your options".
    //  - no ProblemNotice. Nothing is broken. An error card here sends an operator to a
    //    runbook for a deployment working exactly as designed.
    //  - the voice in force is STILL shown. "What do callers hear right now" remains a
    //    fair question; it is only the answer that is not ours to change.
    const { container } = await render({ [VOICES_PATH]: DICTATED_CATALOGUE });

    await screen.findByText(/supplies its own voices/);
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Set voice" })).toBeNull();
    // The server's sentence, verbatim — the panel does not compose its own from the flags
    // and get the tone wrong.
    expect(container.textContent).toContain("Nothing is wrong with this agent.");
    // Still answering the question it can answer.
    expect(container.textContent).toContain("Callers hear now");
  });

  it("renders a refusal, not an empty picker, when the catalogue cannot be read", async () => {
    // §52. A `<select>` with only "Choose a voice" in it says "there are no voices",
    // which is a claim about the product built from a dead request.
    const { container } = await render({
      [VOICES_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "The voice catalogue is unavailable.",
        retryable: true,
      }),
    });

    await screen.findByText("The voice catalogue is unavailable.");
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Set voice" })).toBeNull();
    expect(container.querySelectorAll("input[type=radio]")).toHaveLength(0);
  });

  it("surfaces the server's refusal of an unknown voice rather than pre-empting it", async () => {
    // Membership in the catalogue is the SERVER's check, and its refusal carries the whole
    // list in its remediation. A second copy of that rule here is a rule that drifts.
    const { container } = await render({
      [SET_VOICE_PATH]: problem(422, {
        type: "urn:calevate:business_rule/unknown_voice",
        title: "Unknown voice",
        detail: "That voice is not in the catalog, so it cannot be set on an agent.",
        remediation: "Pick one of the available voices: bulbul:v3:anushka, bulbul:v3:vidya.",
        kind: "business_rule",
      }),
    });

    await screen.findByRole("radio", { name: /Anushka/ });
    fireEvent.click(voiceRow(/Anushka/));
    fireEvent.click(screen.getByRole("button", { name: "Set voice" }));

    await screen.findByText("That voice is not in the catalog, so it cannot be set on an agent.");
    expect(container.textContent).toContain("Pick one of the available voices: bulbul:v3:anushka, bulbul:v3:vidya");
    // Still usable: the operator can pick another entry without reloading.
    expect(screen.getByRole("button", { name: "Set voice" })).toBeTruthy();
  });

  it("groups the two qualities under the names the SERVER gave them, never the vendor's", async () => {
    // The founder's rule (7 Sep 2026): no human-facing surface names a vendor as a tier.
    // "Clear" and "Studio" are the API's words (`billing/rates.py::VOICE_TIER_LABELS`);
    // `sarvam`/`cartesia` name the vendor, key the money, and must never reach a screen —
    // so this asserts both halves, and the second half is the one that regresses silently.
    const { container } = await render({ [VOICES_PATH]: TWO_TIER_CATALOGUE });

    await screen.findByRole("radio", { name: /Ananya/ });
    // Named groups, and the name is the SERVER's label — `getByRole("group", { name })`
    // fails outright if the heading ever says anything else, which is the assertion that
    // matters here.
    const clear = screen.getByRole("group", { name: "Clear voice" });
    const studio = screen.getByRole("group", { name: "Studio voice" });
    // Each quality holds its own voices: the personas are inside their tier's group, which
    // is what makes this two qualities rather than one flat list of three names.
    expect(clear.textContent).toContain("Anushka");
    expect(clear.textContent).toContain("Vidya");
    expect(clear.textContent).not.toContain("Ananya");
    expect(studio.textContent).toContain("Ananya");
    expect(studio.textContent).not.toContain("Anushka");
    // NO VENDOR NAME ANYWHERE — with one deliberate exception, the server's refusal, which
    // is addressed to the operator who installs the key and has to know whose key it is.
    // Everything else on this screen names the QUALITY.
    expect(clear.textContent).not.toMatch(/sarvam|cartesia/i);
    expect(container.textContent!.replace(NO_PRICE_REASON, "")).not.toMatch(/sarvam|cartesia/i);
  });

  it("shows a refused voice disabled with the server's reason, and never a shorter list", async () => {
    // The whole point of `offerable_voices()` returning EVERY voice. A missing Studio row
    // is indistinguishable from a product that does not sell a Studio voice, so the
    // operator who pasted the key an hour ago cannot see that the PRICE is what is still
    // missing. The row is shown, dead, with the one sentence naming the one fix.
    const { container } = await render({ [VOICES_PATH]: TWO_TIER_CATALOGUE });

    await screen.findByRole("radio", { name: /Ananya/ });
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(voiceRow(/Ananya/).disabled).toBe(true);
    expect(voiceRow(/Anushka/).disabled).toBe(false);
    // VERBATIM. The panel does not compose its own sentence from the flags and get the
    // audience or the remedy wrong.
    expect(container.textContent).toContain(NO_PRICE_REASON);

    // And it cannot be chosen by clicking it either — a disabled radio that still moved
    // the selection would offer a save the server is bound to refuse.
    fireEvent.click(voiceRow(/Ananya/));
    expect(voiceRow(/Ananya/).checked).toBe(false);
  });

  it("prices each quality from the account's oldest open credit lot", async () => {
    // THE RATE IS PER LOT, NOT PER PACK AND NOT PER PRODUCT (D-547): a minute costs what
    // the lot it draws from was sold at, oldest lot first. So the figure is the server's,
    // it is this account's, and the note says there is credit behind it at other rates —
    // otherwise a client reads a rate that quietly changes under them.
    const { container } = await render({
      [VOICES_PATH]: TWO_TIER_CATALOGUE,
      [PENDING_PATH]: pendingRoute(VOICE_IN_SYNC, TIER_RATES),
    });

    await screen.findByRole("radio", { name: /Ananya/ });
    expect(container.textContent).toContain("₹5.0000 / min");
    expect(container.textContent).toContain("₹8.0000 / min");
    // The server's digits, unrounded and unparsed (hard rule 7).
    expect(container.textContent).not.toContain("₹5.00 /");
    expect(container.textContent).toContain("the rate on this account's credit");
    expect(container.textContent).toContain(
      "the rate on this account's oldest credit — 2 later purchases behind it at their own rates",
    );
  });

  it("prints no rate at all when the API does not carry one", async () => {
    // The state this build is actually in until the lots API ships the field. A picker that
    // filled the gap from the rate card, a constant or the last known figure would be
    // quoting a price nobody is charged; nothing is the honest answer.
    const { container } = await render({ [VOICES_PATH]: TWO_TIER_CATALOGUE });

    await screen.findByRole("radio", { name: /Ananya/ });
    expect(container.textContent).toContain("Studio voice");
    expect(container.textContent).not.toContain("/ min");
    expect(container.textContent).not.toContain("₹");
  });

  it("drops the whole rate set rather than half-price the picker", async () => {
    // A rate that is not an exact decimal string is a body we do not understand, and
    // rendering the tier we DID understand beside a blank one reads as "that one is free".
    // `readVoiceTierRates` refuses the set; the picker then prices nothing.
    const { container } = await render({
      [VOICES_PATH]: TWO_TIER_CATALOGUE,
      [PENDING_PATH]: pendingRoute(VOICE_IN_SYNC, [
        TIER_RATES[0],
        { ...TIER_RATES[1], inr_per_min: 8 },
      ]),
    });

    await screen.findByRole("radio", { name: /Ananya/ });
    expect(container.textContent).not.toContain("₹");
  });

  it("renders a voice with no server-sent quality name ungrouped, not under its vendor", async () => {
    // An API build that does not send `tier_label` yet. The rows still appear — a voice is
    // not hidden for want of a heading — but nothing invents the heading, because the only
    // other name available is the vendor's and that is the one name it may not be.
    const { container } = await render({
      [VOICES_PATH]: {
        ...CATALOGUE,
        voices: [voice({ tier_label: null }), studio({ tier_label: undefined })],
      },
    });

    await screen.findByRole("radio", { name: /Ananya/ });
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    // The `<fieldset>` is itself a group; what must not exist is a tier group inside it.
    expect(screen.queryByRole("group", { name: /voice$/ })).toBeNull();
    expect(container.textContent).not.toMatch(/sarvam|cartesia/i);
  });

  it("explains the disabled control to an operator without agents:write", async () => {
    const { container } = await render({
      [ME_PATH]: {
        realm: "admin",
        user_id: "0192f0aa-8888-7000-8000-0000000000f3",
        role: "support",
        permissions: ["agents:read"],
      },
    });

    await screen.findByRole("radio", { name: /Anushka/ });
    expect(voiceRow(/Anushka/).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Set voice" })).toHaveProperty("disabled", true);
    expect(container.textContent).toContain(
      "does not have permission to change this agent's script",
    );
  });
});
