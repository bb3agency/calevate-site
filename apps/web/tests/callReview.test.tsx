import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallDetailPage from "@/app/c/[slug]/calls/[callId]/page";
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
    translation_state: "not_needed",
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
    transcript: [
      { idx: 0, speaker: "agent", text: "Namaskaram.", redacted: true, start_ms: 0 },
      { idx: 1, speaker: "caller", text: "Chilli undha?", redacted: true, start_ms: 4000 },
    ],
    ...over,
  };
}

const page = <CallDetailPage params={Promise.resolve({ slug: "acme", callId: "c1" })} />;

function routes(call: unknown, over: Record<string, unknown> = {}) {
  return {
    "/v1/me": me(),
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
    expect(screen.getByText("Lakshmi")).toBeTruthy();
    expect(screen.getByText("+91 98765 43210")).toBeTruthy();
    // ONE filled action, its label the consequence, and the lead one quiet link away.
    const action = screen.getByRole("button", { name: "Have the agent call back now" });
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
    expect(screen.getByText("The caller asked to be called back, and no call back was booked.")).toBeTruthy();
  });

  it("states the server's refusal as a sentence, not a dead button", async () => {
    await renderClientPage(page, routes(detail()));
    expect(await screen.findByText("A call back is already booked.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /call back now/i })).toBeNull();
  });

  it("shows the summary in the call's language on request, tagged with that language", async () => {
    await renderClientPage(
      page,
      routes(detail({ summary_local: "కాలర్ పచ్చి మిర్చి అడిగారు.", summary_language: "te-IN" })),
    );
    expect((await screen.findByText(/green chilli is in stock/)).getAttribute("lang")).toBe("en");
    fireEvent.click(screen.getByRole("button", { name: "Read it in Telugu" }));
    expect(screen.getByText("కాలర్ పచ్చి మిర్చి అడిగారు.").getAttribute("lang")).toBe("te-IN");
    expect(screen.getByRole("button", { name: "Read it in English" }).getAttribute("aria-pressed")).toBe("true");
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
      await screen.findByText("The summary could not be written for this call. The conversation below is complete."),
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
  const TELUGU = [
    { idx: 0, speaker: "agent" as const, text: "నమస్కారం అండి.", text_en: "Hello.", lang: "te", redacted: true, start_ms: 0 },
    { idx: 1, speaker: "agent" as const, text: "ఎలా సహాయం చేయగలను?", text_en: "How can I help?", lang: "te", redacted: true, start_ms: 2000 },
    { idx: 2, speaker: "caller" as const, text: "చిల్లీ ఉందా?", text_en: "Do you have chilli?", lang: "te", redacted: true, start_ms: 5000 },
  ];

  it("prints the speaker once per run, and each line carries its language", async () => {
    await renderClientPage(page, routes(detail({ translation_state: "ready", transcript: TELUGU })));
    expect((await screen.findByText("నమస్కారం అండి.")).getAttribute("lang")).toBe("te");
    const conversation = screen.getByRole("heading", { name: "Conversation" }).closest("section")!;
    const text = conversation.textContent ?? "";
    expect(text.split("Agent").length - 1).toBe(1);
    expect(text.split("Caller").length - 1).toBe(1);
    // Times sit in the gutter, the line beside them.
    expect(text).toContain("0:05");
  });

  it("shows English under each line on request, and keeps the original as the record", async () => {
    await renderClientPage(page, routes(detail({ translation_state: "ready", transcript: TELUGU })));
    await screen.findByText("చిల్లీ ఉందా?");
    expect(screen.queryByText("Do you have chilli?")).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Show English" }));
    expect(screen.getByText("Do you have chilli?").getAttribute("lang")).toBe("en");
    expect(screen.getByText("చిల్లీ ఉందా?")).toBeTruthy();
  });

  it("says the English is still being written rather than offering a switch that does nothing", async () => {
    await renderClientPage(page, routes(detail({ translation_state: "pending" })));
    expect(await screen.findByText("The English of each line is still being written.")).toBeTruthy();
    expect(screen.queryByRole("switch", { name: "Show English" })).toBeNull();
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
  it("lists captured details under the business's labels, with 'Not said' for an empty one", async () => {
    await renderClientPage(page, routes(detail()));
    expect((await screen.findByText("Preferred time")).closest("div")?.textContent).toContain("Not said");
    expect(screen.getByText("Quantity").closest("div")?.textContent).toContain("2 kg");
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
