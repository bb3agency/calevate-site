import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallDetailPage from "@/app/c/[slug]/calls/[callId]/page";
import { OUTCOME_KIND_WORDS, type OutcomeKind, callOutcome, outcomeWords } from "@/lib/callReview";
import type { CallDetail, Me } from "@/lib/api/client";

import { NeverAnswers, renderClientPage } from "./harness";

/**
 * THE CALL REVIEW (first-call review F-3, founder decisions 4–6): how the call ended in
 * the founder's words with its reason, the English summary with the call's own language
 * one press away, the booked call back with the server's own sentence, ONE primary
 * action, and the transcript read as a script with "Show English" under each line.
 *
 * `tests/callDetail.test.tsx` owns the safety claims on this screen (redaction, numbers
 * never in a link, the raw view's audit); this file owns how the call is READ.
 */

function me(): Me {
  return {
    user_id: "u1",
    realm: "client",
    role: "owner",
    permissions: ["calls:read", "calls:read_raw", "leads:read", "leads:dispatch"],
    impersonating: false,
    withheld_acts: [],
    organization: { id: "o1", name: "Raghava Organics", slug: "acme", status: "active" },
  };
}

function detail(over: Partial<CallDetail> = {}): CallDetail {
  return {
    id: "c1",
    agent_id: "a1",
    agent_name: "Reception",
    direction: "outbound",
    status: "completed",
    caller_e164: "+919876543210",
    started_at: "2026-10-10T12:22:00Z",
    duration_s: 64,
    outcome_tag: "call_back_booked",
    summary_state: "ready",
    test_call: false,
    caller_id_hidden: false,
    forwarding_test: false,
    forwarded_to_phone: false,
    not_placed_reason: null,
    translation_state: "not_needed",
    language: "te-IN",
    sentiment: "neutral",
    summary: "The caller asked whether green chilli is in stock and wants a call back.",
    lead_id: "l1",
    extraction: {},
    captured: [
      { key: "need", label: "What they want", type: "text", core: true, current: true, value: "Green chilli" },
      { key: "preferred_time", label: "Preferred time", type: "text", core: true, current: true, value: null },
      { key: "quantity", label: "Quantity", type: "text", core: false, current: true, value: "2 kg" },
    ],
    extraction_valid: true,
    has_recording: false,
    disclosure_played: true,
    moments: [],
    quality: null,
    signals: [],
    timeline: null,
    transcript: [
      { idx: 0, speaker: "agent", text: "Namaskaram.", redacted: true, start_ms: 0, start_approximate: false, likely_cut_off: false },
      { idx: 1, speaker: "caller", text: "Chilli undha?", redacted: true, start_ms: 4000, start_approximate: false, likely_cut_off: false },
    ],
    ...over,
  };
}

const TELUGU = [
  { idx: 0, speaker: "agent" as const, text: "నమస్కారం అండి.", text_en: "Hello.", lang: "te", redacted: true, start_ms: 0, start_approximate: false, likely_cut_off: false },
  { idx: 1, speaker: "agent" as const, text: "ఎలా సహాయం చేయగలను?", text_en: "How can I help?", lang: "te", redacted: true, start_ms: 2000, start_approximate: false, likely_cut_off: false },
  { idx: 2, speaker: "caller" as const, text: "చిల్లీ ఉందా?", text_en: "Do you have chilli?", lang: "te", redacted: true, start_ms: 5000, start_approximate: false, likely_cut_off: false },
];
/** The same lines before any English was written. */
const TELUGU_ONLY = TELUGU.map((turn) => ({ ...turn, text_en: null }));

const page = (
  <CallDetailPage params={Promise.resolve({ slug: "acme", callId: "c1" })} searchParams={Promise.resolve({})} />
);

function routes(call: unknown, over: Record<string, unknown> = {}) {
  return {
    "/v1/me": me(),
    "/v1/agents": [],
    "/v1/calls/c1": call,
    "/v1/calls/c1/callback": { eligible: false, reason: "A call back is already booked.", rule: null },
    ...over,
  };
}

describe("the verdict", () => {
  it("puts the outcome, its reason, the summary and the one action first", async () => {
    await renderClientPage(
      page,
      routes(detail({ lead_name: "Lakshmi" }), {
        "/v1/calls/c1/callback": { eligible: true, reason: null, rule: null, follow_up_number: 1 },
      }),
    );

    const verdict = await screen.findByRole("heading", { name: "Call back booked" });
    expect(screen.getByText("The caller asked to be called back, and the agent booked it.")).toBeTruthy();
    expect(screen.getByText(/green chilli is in stock/)).toBeTruthy();
    // The lead's name is the title; the number moves to the line under it.
    // First in the page header; the caller's lines in the conversation carry it too.
    expect(screen.getAllByText("Lakshmi")[0].closest("section")).toBeNull();
    expect(screen.getByText("+91 98765 43210")).toBeTruthy();
    // ONE filled action, its label the consequence, and the lead one quiet link away.
    const action = screen.getByRole("button", { name: "Call back now" });
    expect(action.className).toContain("bg-brand-strong");
    expect(screen.getByRole("link", { name: "Open Lakshmi's lead" })).toBeTruthy();
    // The verdict comes before the conversation.
    const conversation = screen.getByRole("heading", { name: "Conversation" });
    expect(verdict.compareDocumentPosition(conversation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("names a call back the caller asked for and nobody booked, in the warning tone", async () => {
    await renderClientPage(
      page,
      routes(detail({ outcome_tag: "needs_you", callback_requested: true, callback: null })),
    );
    const heading = await screen.findByRole("heading", { name: "Needs you" });
    expect(heading.className).toContain("text-warn");
    expect(screen.getByText("They asked for a call back. None is booked.")).toBeTruthy();
  });

  it("states the server's refusal as a sentence, not a dead button", async () => {
    await renderClientPage(page, routes(detail()));
    expect(await screen.findByText("A call back is already booked.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /call back now/i })).toBeNull();
  });

  it("shows the summary in English while the conversation opens as spoken", async () => {
    await renderClientPage(
      page,
      routes(
        detail({
          summary_local: "కాలర్ పచ్చి మిర్చి అడిగారు.",
          summary_language: "te-IN",
          translation_state: "ready",
          transcript: TELUGU,
        }),
      ),
    );
    // The lines open as spoken (D-887); the summary is English whichever way they are read.
    expect((await screen.findByText(/green chilli is in stock/)).getAttribute("lang")).toBe("en");
    expect(screen.queryByText("కాలర్ పచ్చి మిర్చి అడిగారు.")).toBeNull();
    expect(screen.getByText("చిల్లీ ఉందా?").getAttribute("lang")).toBe("te");
    expect(screen.queryByRole("button", { name: /Read it in/ })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "English" }));
    expect(screen.getByText(/green chilli is in stock/).getAttribute("lang")).toBe("en");
  });

  it("gives the next step as the reason a call needs a person, not a task left unfinished", async () => {
    await renderClientPage(
      page,
      routes(
        detail({
          outcome_tag: "needs_you",
          callback_requested: false,
          callback: null,
          next_step: "Confirm the site visit for tomorrow morning.",
          business_outcome: "ready_to_visit",
          business_outcome_label: "Ready to visit",
        }),
      ),
    );
    expect(await screen.findByRole("heading", { name: "Needs you" })).toBeTruthy();
    expect(screen.getByText("Something is left to do. See the next step below.")).toBeTruthy();
    expect(screen.queryByText(/could not finish/)).toBeNull();
    expect(screen.getByText("Confirm the site visit for tomorrow morning.")).toBeTruthy();
  });

  it("says the summary is being written while it is, and says so differently when it failed", async () => {
    const pending = await renderClientPage(
      page,
      routes(detail({ summary: null, summary_state: "pending", outcome_tag: null })),
    );
    expect(await screen.findByText("Writing the summary…")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Reading this call" })).toBeTruthy();
    pending.unmount();

    await renderClientPage(page, routes(detail({ summary: null, summary_state: "failed" })));
    expect(
      await screen.findByText("Couldn't write a summary. The full chat is below."),
    ).toBeTruthy();
  });

  it("prints the booked call back with the server's own sentence for why it was not placed", async () => {
    const reason = "Call backs are not placed during your free trial.";
    await renderClientPage(
      page,
      routes(
        detail({
          callback: {
            id: "cb1",
            due_at: "2026-10-10T12:33:00Z",
            status: "refused",
            blocked_reason: reason,
            blocked_rule: "trial_call_back_unavailable",
          },
          next_step: "Call them back about chilli prices.",
        }),
      ),
    );
    expect(await screen.findByText(reason)).toBeTruthy();
    expect(screen.getByText("Not placed")).toBeTruthy();
    expect(screen.getByText("Call them back about chilli prices.")).toBeTruthy();
    // The rule's machine name is for screens that branch, never for a reader.
    expect(document.body.textContent).not.toContain("trial_call_back_unavailable");
  });

  it("marks a free-trial test call", async () => {
    await renderClientPage(page, routes(detail({ test_call: true })));
    expect(await screen.findByText("Test call")).toBeTruthy();
  });
});

describe("the conversation", () => {
  it("reads as a chat: the agent by name on the left, the caller on the right, each line in its language", async () => {
    await renderClientPage(page, routes(detail({ translation_state: "ready", transcript: TELUGU })));
    fireEvent.click(await screen.findByRole("radio", { name: "Telugu" }));
    expect(screen.getByText("నమస్కారం అండి.").getAttribute("lang")).toBe("te");
    const list = screen.getByRole("list", { name: "The conversation, line by line" });
    const runs = Array.from(list.children);
    expect(runs).toHaveLength(2);
    // The speaker is named once per run: the agent's own name, then the caller.
    expect(runs[0].textContent).toContain("Reception");
    expect(runs[0].className).not.toContain("justify-end");
    expect(runs[1].textContent).toContain("Caller");
    expect(runs[1].className).toContain("justify-end");
    expect(list.textContent).toContain("0:05");
  });

  it("marks a time the platform only approximates with a tilde", async () => {
    await renderClientPage(
      page,
      routes(detail({ transcript: [{ ...TELUGU[2], start_approximate: true, likely_cut_off: false }], translation_state: "ready" })),
    );
    expect(await screen.findByText("~0:05")).toBeTruthy();
  });

  it("says under an agent line when the caller probably spoke over it (D-739)", async () => {
    await renderClientPage(
      page,
      routes(
        detail({
          transcript: [
            { ...TELUGU[1], likely_cut_off: true },
            { ...TELUGU[2], likely_cut_off: false },
          ],
          translation_state: "ready",
        }),
      ),
    );
    const note = await screen.findByText(
      "Caller spoke over this part.",
    );
    expect(screen.getAllByText(/caller spoke over this/i)).toHaveLength(1);
    // Under the agent's line, not inside it.
    expect(note.closest("li")?.textContent).toContain("ఎలా సహాయం చేయగలను?");
    expect(note.closest("button")).toBeNull();
  });

  it("switches every line to English with the one switch, and back", async () => {
    await renderClientPage(page, routes(detail({ translation_state: "ready", transcript: TELUGU })));
    // Opens as spoken even with English ready (D-887).
    expect(await screen.findByText("చిల్లీ ఉందా?")).toBeTruthy();
    expect(screen.queryByText("Do you have chilli?")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "English" }));
    expect(screen.getByText("Do you have chilli?").getAttribute("lang")).toBe("en");
    expect(screen.queryByText("చిల్లీ ఉందా?")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Telugu" }));
    expect(screen.getByText("చిల్లీ ఉందా?")).toBeTruthy();
  });

  it("always offers the switch, and says English is being prepared while it is", async () => {
    await renderClientPage(page, routes(detail({ translation_state: "pending", transcript: TELUGU_ONLY })));
    expect(await screen.findByRole("radio", { name: "Telugu" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "English" }));
    expect(screen.getByText(/English is being prepared/)).toBeTruthy();
    expect(screen.queryByText("చిల్లీ ఉందా?")).toBeNull();
  });

  it("offers Try again when the English failed, and asks the server once", async () => {
    // The server's answer to the poll follows the press, as the real one does.
    let asked = false;
    const { calls } = await renderClientPage(
      page,
      routes(() => detail({ translation_state: asked ? "pending" : "failed", transcript: TELUGU_ONLY }), {
        "POST /v1/calls/c1/translation": () => {
          asked = true;
          return { translation_state: "pending" };
        },
        "/v1/me": { ...me(), permissions: [...me().permissions, "org:manage"] },
      }),
    );
    fireEvent.click(await screen.findByRole("radio", { name: "English" }));
    expect(screen.getByText("Couldn't prepare the English.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/English is being prepared/)).toBeTruthy();
    expect(calls.filter((c) => c.method === "POST" && c.path === "/v1/calls/c1/translation")).toHaveLength(1);
  });

  it("names a call from before English existed, and keeps the action from a role that cannot pay for it", async () => {
    await renderClientPage(page, routes(detail({ translation_state: "unavailable", transcript: TELUGU_ONLY })));
    fireEvent.click(await screen.findByRole("radio", { name: "English" }));
    expect(screen.getByText("This call is older than English reviews.")).toBeTruthy();
    const button = screen.getByRole("button", { name: "Prepare the English" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("needs no switch for a call that was in English, and says so", async () => {
    await renderClientPage(page, routes(detail({ language: "en-IN" })));
    expect(await screen.findByText("This call was in English.")).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "English" })).toBeNull();
  });

  it("says when there is no recording, where the player would be", async () => {
    await renderClientPage(page, routes(detail({ has_recording: false })));
    expect(await screen.findByText("There is no recording of this call.")).toBeTruthy();
  });

  it("says nobody spoke on a call that never connected, with no captured details", async () => {
    await renderClientPage(
      page,
      routes(
        detail({
          status: "no_answer",
          outcome_tag: "missed",
          transcript: [],
          summary: null,
          summary_state: "empty",
          captured: [{ key: "need", label: "What they want", type: "text", core: true, current: true, value: null }],
        }),
      ),
    );
    expect(await screen.findByText("Nobody spoke on this call")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Captured details" })).toBeNull();
  });
});

describe("the rest of the screen", () => {
  it("lists only the details the caller gave, and folds the rest into one quiet line", async () => {
    await renderClientPage(page, routes(detail()));
    expect((await screen.findByText("Quantity")).closest("div")?.textContent).toContain("2 kg");
    expect(screen.queryByText("Not said")).toBeNull();
    expect(screen.getByText("Not mentioned: Preferred time")).toBeTruthy();
  });

  it("gives the caller's own words for a choice none of the choices fitted (D-889)", async () => {
    await renderClientPage(
      page,
      routes(
        detail({
          captured: [
            { key: "need", label: "What they want", type: "text", core: true, current: true, value: "A flat" },
            {
              key: "bhk_size",
              label: "BHK",
              type: "enum",
              core: false,
              current: true,
              value: null,
              unlisted: "6 BHK",
            },
          ],
        }),
      ),
    );
    const row = (await screen.findByText("BHK")).closest("div");
    expect(row?.textContent).toContain("“6 BHK”");
    expect(row?.textContent).toContain("Not one of the choices");
    expect(screen.queryByText(/Not mentioned: .*BHK/)).toBeNull();
  });

  it("says so in one sentence when the caller gave no details", async () => {
    await renderClientPage(
      page,
      routes(
        detail({
          captured: [{ key: "need", label: "What they want", type: "text", core: true, current: true, value: null }],
        }),
      ),
    );
    expect(await screen.findByText("The caller did not give any details on this call.")).toBeTruthy();
    expect(screen.queryByText(/Not mentioned/)).toBeNull();
  });

  it("is a skeleton shaped like the page while the call loads", async () => {
    await renderClientPage(page, routes(new NeverAnswers()));
    expect(await screen.findByText("Loading this call")).toBeTruthy();
  });

  it("keeps the second reading behind a closed disclosure, with no sparkle", async () => {
    const { container } = await renderClientPage(page, routes(detail()));
    const summary = await screen.findByText("A second reading of this call");
    expect(summary.closest("details")?.hasAttribute("open")).toBe(false);
    expect(container.querySelector(".lucide-sparkles")).toBeNull();
  });
});

describe("the business's own outcome (D-836)", () => {
  it("files a plain call under the agent's outcome, and a fact above it", () => {
    expect(outcomeWords({ outcome_tag: "answered", business_outcome_label: "Wants to buy" })).toBe("Wants to buy");
    expect(outcomeWords({ outcome_tag: null, business_outcome_label: "Wants to buy" })).toBe("Wants to buy");
    expect(outcomeWords({ outcome_tag: "needs_you", business_outcome_label: "Wants to buy" })).toBe("Needs you");
    expect(outcomeWords({ outcome_tag: "answered", business_outcome_label: null })).toBe("Answered");
    expect(outcomeWords({ outcome_tag: null })).toBeNull();
  });

  it("no longer says No outcome for a call the model sorted but could not put a fact on", () => {
    expect(
      callOutcome({ status: "completed", outcome_tag: null, summary_state: "ready", business_outcome_label: "Wants to buy" })
        .words,
    ).toBe("Wants to buy");
    expect(callOutcome({ status: "completed", outcome_tag: null, summary_state: "ready" }).words).toBe("Answered");
  });
});

/**
 * THE KIND OF ENDING (founder, 25 Oct 2026): one mapping from structured values to the
 * coloured mark, used by every call list. A likely lead is the agent's own outcome moving
 * the lead to interested or hot — never the label's words.
 */
describe("the kind of ending a call had", () => {
  const done = { status: "completed", summary_state: "ready" } as const;
  const cases: [string, Parameters<typeof callOutcome>[0], string, OutcomeKind][] = [
    [
      "an outcome that moves the lead to interested",
      { ...done, outcome_tag: "answered", business_outcome: "site_visit", business_outcome_label: "Site visit agreed", business_outcome_lead_status: "interested" },
      "Site visit agreed",
      "interested",
    ],
    [
      "an outcome that moves the lead to hot",
      { ...done, outcome_tag: null, business_outcome: "ready", business_outcome_label: "Ready to pay", business_outcome_lead_status: "hot" },
      "Ready to pay",
      "hot",
    ],
    [
      "a lead the call needs a person for keeps its outcome",
      { ...done, outcome_tag: "needs_you", business_outcome: "wants_to_buy", business_outcome_label: "Wants to buy or book", business_outcome_lead_status: "interested" },
      "Wants to buy or book",
      "interested",
    ],
    ["a booked call back", { ...done, outcome_tag: "call_back_booked", business_outcome_label: "Interested", business_outcome_lead_status: "interested" }, "Call back booked", "call_back"],
    ["a hand-over to a person", { ...done, outcome_tag: "transferred" }, "Transferred", "transferred"],
    [
      "an outcome that only marks contact",
      { ...done, outcome_tag: "answered", business_outcome: "asked_for_information", business_outcome_label: "Asked for information", business_outcome_lead_status: "contacted" },
      "Asked for information",
      "neutral",
    ],
    ["a plain answered call", { ...done, outcome_tag: "answered" }, "Answered", "neutral"],
    ["needs you with nothing else known", { ...done, outcome_tag: "needs_you" }, "Answered", "neutral"],
    ["an outcome on no list", { ...done, outcome_tag: "answered", business_outcome: "gone", business_outcome_label: "Gone", business_outcome_lead_status: null }, "Gone", "neutral"],
    ["a call still being read", { status: "completed", summary_state: "pending", outcome_tag: null }, "Being read", "neutral"],
    ["a live call", { status: "in_progress", outcome_tag: null }, "On the line", "neutral"],
    ["an early hang-up", { ...done, outcome_tag: "hung_up_early", business_outcome_label: "Interested", business_outcome_lead_status: "interested" }, "Hung up early", "hung_up_early"],
    [
      "the starting set's not interested",
      { ...done, outcome_tag: "answered", business_outcome: "not_interested", business_outcome_label: "Not interested", business_outcome_lead_status: "contacted" },
      "Not interested",
      "said_no",
    ],
    ["a missed call", { status: "no_answer", outcome_tag: "missed" }, "Missed", "not_connected"],
    ["a busy line", { status: "busy", outcome_tag: null }, "Busy", "not_connected"],
    ["a call that did not connect", { status: "failed", outcome_tag: null }, "Did not connect", "not_connected"],
    ["a status this build has never heard of", { status: "teleported", outcome_tag: null }, "Teleported", "neutral"],
  ];
  it.each(cases)("%s", (_name, call, words, kind) => {
    expect(callOutcome(call)).toEqual({ words, kind });
  });

  it("names every kind in the legend's words", () => {
    expect(Object.keys(OUTCOME_KIND_WORDS).sort()).toEqual(["call_back", "hot", "hung_up_early", "interested", "neutral", "not_connected", "said_no", "transferred"]);
  });
});

describe("the business's own outcome on the verdict (D-836)", () => {

  it("heads the verdict with the fact and names the business outcome under it", async () => {
    await renderClientPage(
      page,
      routes(detail({ outcome_tag: "call_back_booked", business_outcome: "wants_to_buy", business_outcome_label: "Wants to buy" })),
    );
    await screen.findByRole("heading", { name: "Call back booked" });
    expect(screen.getByText("Wants to buy")).toBeTruthy();
    expect(screen.getByText(/For your business:/)).toBeTruthy();
  });

  it("heads the verdict with the business outcome on a call that only answered", async () => {
    await renderClientPage(
      page,
      routes(detail({ outcome_tag: "answered", business_outcome: "wants_to_buy", business_outcome_label: "Wants to buy" })),
    );
    await screen.findByRole("heading", { name: "Wants to buy" });
    expect(screen.queryByText(/For your business:/)).toBeNull();
  });

  it("carries the call log's mark beside the same words, and none beside Needs you", async () => {
    await renderClientPage(
      page,
      routes(
        detail({
          outcome_tag: "answered",
          business_outcome: "wants_to_buy",
          business_outcome_label: "Wants to buy",
          business_outcome_lead_status: "interested",
        }),
      ),
    );
    const heading = await screen.findByRole("heading", { name: "Wants to buy" });
    expect(heading.querySelector('[data-kind="interested"][aria-hidden]')).not.toBeNull();
  });

  it("puts the mark on the business outcome when Needs you heads the verdict", async () => {
    await renderClientPage(
      page,
      routes(
        detail({
          outcome_tag: "needs_you",
          business_outcome: "wants_to_buy",
          business_outcome_label: "Wants to buy",
          business_outcome_lead_status: "interested",
        }),
      ),
    );
    const heading = await screen.findByRole("heading", { name: "Needs you" });
    expect(heading.querySelector("[data-kind]")).toBeNull();
    expect(screen.getByText("Wants to buy").querySelector('[data-kind="interested"]')).not.toBeNull();
  });
});
