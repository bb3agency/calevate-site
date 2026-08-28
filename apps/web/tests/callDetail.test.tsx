import { QueryClient } from "@tanstack/react-query";
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallDetailPage from "@/app/c/[slug]/calls/[callId]/page";
import type { CallDetail, Me } from "@/lib/api/client";

import { problem, renderClientPage } from "./harness";

/**
 * The call detail screen — the only screen in the product that renders a TRANSCRIPT,
 * and therefore the one where a wrong render is a reportable data incident rather than
 * a bad afternoon.
 *
 * The claims below are mostly NEGATIVE and ranked by what a wrong answer costs:
 *
 * 1. The REDACTED transcript is what renders by default. Hard rule 5 makes
 *    `text_redacted` the default view in every API response; a screen that quietly
 *    fetched the unredacted endpoint instead would satisfy every visual review and
 *    breach the rule on every page load.
 * 2. No raw caller number reaches the DOM, and none reaches an `href`. A URL outlives
 *    the page: it is in history, in the referrer, and in whatever log sits in front of
 *    us (hard rule 6).
 * 3. A failed detail request renders a REFUSAL, never an empty transcript. "This call
 *    had no conversation" sends an owner to check their agent; "we could not read this
 *    call" sends them to us. Only one of those is true, and the failure mode of every
 *    naive `data?.transcript ?? []` is to print the wrong one.
 * 4. The raw-transcript control is refused, before the click, for a session without
 *    `calls:read_raw` — and refusing it means the request is never made, not that the
 *    403 is styled nicely.
 * 5. When the raw view IS opened and the server refuses, the redacted turns stay on
 *    screen. A permission failure that blanks the transcript reads as data loss.
 */

function me(over: Partial<Me> = {}): Me {
  return {
    user_id: "u1",
    realm: "client",
    role: "owner",
    permissions: ["calls:read", "calls:read_raw", "leads:read"],
    impersonating: false,
    organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
    ...over,
  };
}

/** The staff role: `calls:read` but never `calls:read_raw` (core/rbac.py). */
const STAFF = me({ role: "staff", permissions: ["calls:read", "leads:read"] });

/** The digits that must never appear, in any grouping. */
const RAW_NUMBER = "9876543210";

function detail(over: Partial<CallDetail> = {}): CallDetail {
  return {
    id: "c1",
    agent_id: "a1",
    agent_name: "Reception",
    direction: "inbound",
    status: "completed",
    caller_e164: "+919876543210",
    started_at: "2026-08-13T04:30:00Z",
    duration_s: 92,
    outcome_tag: "appointment_booked",
    sentiment: "positive",
    summary: "Caller asked for a Tuesday slot.",
    lead_id: "l1",
    extraction: { patient_name: "Ravi", slot: "Tuesday 5pm" },
    extraction_valid: true,
    has_recording: false,
    disclosure_played: true,
    moments: [],
    transcript: [
      { idx: 0, speaker: "agent", text: "Namaskaram, this is an AI assistant.", redacted: true },
      { idx: 1, speaker: "caller", text: "My number is [redacted].", redacted: true },
    ],
    ...over,
  };
}

const page = <CallDetailPage params={Promise.resolve({ slug: "acme", callId: "c1" })} />;

function routes(call: unknown, over: Record<string, unknown> = {}) {
  return {
    "/v1/me": me(),
    "/v1/calls/c1": call,
    "/v1/calls/c1/callback": { eligible: false, reason: "This call was answered.", rule: null },
    ...over,
  };
}

const RAW_PATH = "/v1/calls/c1/transcript/raw";

describe("the call detail screen", () => {
  it("renders the redacted transcript, and never asks for the raw one on its own", async () => {
    const { calls } = await renderClientPage(page, routes(detail()));

    expect(await screen.findByText("My number is [redacted].")).toBeTruthy();
    // The unredacted endpoint writes an audit_log row on every read. A screen that
    // reaches for it unprompted records a person as having looked at personal data
    // they never asked to see, and hands it to them besides.
    expect(calls.some((c) => c.path === RAW_PATH)).toBe(false);
    // And the reader is TOLD which view they are on — hard rule 5 is invisible
    // otherwise, and an odd-looking line reads as the agent mishearing.
    expect(screen.getByText(/Personal details .* are hidden in this view/)).toBeTruthy();
  });

  it("flags a captured field for review without leaking the value (P4)", async () => {
    await renderClientPage(
      page,
      routes(
        detail({
          extraction: { callback_number: "1234567890" },
          extraction_needs_review: {
            callback_number:
              "Callback number was captured but is not a standard Indian mobile number — check it before dialling.",
          },
        }),
      ),
    );

    // The value still shows (it is usable), with the amber advisory beneath it — and the
    // reason names the field, never a digit of the number (hard rule 6).
    expect(await screen.findByText("1234567890")).toBeTruthy();
    const note = screen.getByText(/is not a standard Indian mobile number/);
    expect(note.textContent).not.toMatch(/1234567890/);
  });

  it("shows no review note for a clean extraction", async () => {
    await renderClientPage(page, routes(detail()));
    expect(await screen.findByText("Ravi")).toBeTruthy();
    expect(screen.queryByText(/check it before dialling/)).toBeNull();
  });

  it("prints the caller's number and never puts it in a link", async () => {
    const { container } = await renderClientPage(
      page,
      routes(detail({ caller_e164: "+919876543210" })),
    );

    // WAS `not.toContain(RAW_NUMBER)`. D-436: this is the screen a callback starts
    // from. `RAW_NUMBER` keeps its meaning further down, where it is a number the
    // caller SPOKE inside the transcript — that one is still gated on `calls:read_raw`.
    expect(await screen.findByText("+919876543210")).toBeTruthy();
    for (const link of Array.from(container.querySelectorAll("a"))) {
      expect(link.getAttribute("href") ?? "").not.toMatch(/\d{10}/);
    }
  });

  it("refuses out loud when the call cannot be read, instead of showing an empty transcript", async () => {
    const { container } = await renderClientPage(
      page,
      routes(problem(503, { title: "Service unavailable", retryable: true })),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // The sentence this screen must never print over a failure.
    expect(container.textContent).not.toContain("No transcript yet");
    expect(container.textContent).not.toContain("Transcripts arrive");
  });

  it("refuses the raw-transcript control to a session without calls:read_raw, before the click", async () => {
    const { calls } = await renderClientPage(page, routes(detail(), { "/v1/me": STAFF }));

    const button = await screen.findByRole("button", { name: /full transcript/i });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByTitle("Only an account owner can open the full transcript.").length)
      .toBeGreaterThan(0);

    // Disabled is not enough on its own — clicking a disabled button is a no-op in a
    // browser, but the assertion that matters is that no code path fires the request.
    fireEvent.click(button);
    expect(calls.some((c) => c.path === RAW_PATH)).toBe(false);
  });

  it("keeps the redacted turns on screen when the raw transcript is refused", async () => {
    const { container } = await renderClientPage(
      page,
      routes(detail(), { [RAW_PATH]: problem(403, { title: "Forbidden" }) }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /show full transcript/i }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    // The transcript did NOT blank out, and it did not silently upgrade either.
    expect(container.textContent).toContain("My number is [redacted].");
    expect(container.textContent).toContain("are hidden in this view");
  });

  it("says that opening the full transcript is recorded, once it is open", async () => {
    // `redacted: false` — this IS the raw view, and the field is REQUIRED on
    // `TranscriptTurnOut`. It was missing here, and the `as unknown as Partial<CallDetail>`
    // that used to sit on this literal is what kept the compiler from saying so; the turn
    // eleven lines above spells the same shape correctly (tests/wireFixtureGuard.test.ts).
    const raw = detail({
      transcript: [
        { idx: 0, speaker: "agent", text: "Namaskaram, this is an AI assistant.", redacted: false },
        { idx: 1, speaker: "caller", text: `My number is ${RAW_NUMBER}.`, redacted: false },
      ],
    });
    const { container } = await renderClientPage(page, routes(detail(), { [RAW_PATH]: raw }));

    fireEvent.click(await screen.findByRole("button", { name: /show full transcript/i }));

    expect(await screen.findByText(`My number is ${RAW_NUMBER}.`)).toBeTruthy();
    // Honesty about the audit row is the price of the view. Someone deciding whether to
    // look must know before they look, not learn it from a compliance review.
    expect(container.textContent).toContain("recorded in your account's audit log");
    expect(container.textContent).not.toContain("are hidden in this view");
  });

  /**
   * ONE OPENING, ONE REQUEST, ONE AUDIT ROW — the compliance invariant behind this
   * screen, not a caching preference.
   *
   * `/v1/calls/{id}/transcript/raw` writes an `audit_log` row in the same transaction as
   * the read, and hard rule 5 / SURFACES §3.1 exist so that "who opened this transcript"
   * is answerable. The read used to be a `useQuery` with `staleTime: Infinity`, which
   * made the SECOND opening free: the unredacted text came back out of the cache with no
   * network call, so the trail recorded the first read and under-reported every one
   * after it. That is the exact question a DPDP enquiry asks.
   *
   * These two tests count REQUESTS at the network seam — the only place the audit row is
   * observable from the browser — rather than asserting the hook's shape. They fail
   * against the `useQuery` version and pass against the mutation, which is what makes
   * them a guard rather than a restatement.
   */
  it("mints a second request, and so a second audit row, on a second opening", async () => {
    const raw = detail({
      transcript: [
        { idx: 0, speaker: "caller", text: `My number is ${RAW_NUMBER}.`, redacted: false },
      ],
    });
    const { calls } = await renderClientPage(page, routes(detail(), { [RAW_PATH]: raw }));

    const button = await screen.findByRole("button", { name: /show full transcript/i });
    fireEvent.click(button);
    expect(await screen.findByText(`My number is ${RAW_NUMBER}.`)).toBeTruthy();
    expect(calls.filter((c) => c.path === RAW_PATH).length).toBe(1);

    // Hide. The unredacted turns must LEAVE, not be parked where the next press can
    // read them back without asking the server.
    fireEvent.click(await screen.findByRole("button", { name: /hide full transcript/i }));
    expect(screen.queryByText(`My number is ${RAW_NUMBER}.`)).toBeNull();

    // Show again — a deliberate re-open, which is a read of personal data and must be
    // recorded as one.
    fireEvent.click(await screen.findByRole("button", { name: /show full transcript/i }));
    expect(await screen.findByText(`My number is ${RAW_NUMBER}.`)).toBeTruthy();
    expect(calls.filter((c) => c.path === RAW_PATH).length).toBe(2);
  });

  it("asks again after leaving the call and coming back", async () => {
    // The same defect through the other door: a query entry survives an unmount for
    // `gcTime` (5 minutes by default), so returning to a call inside that window replayed
    // the unredacted transcript with no request and no row.
    //
    // ONE `QueryClient` ACROSS BOTH MOUNTS is what makes this test able to fail. The app
    // has exactly one per shell mount and navigating between calls keeps it; a second
    // `renderClientPage` with its own client has no cache to restore from, so the same
    // assertions would pass against the broken version and prove nothing.
    const raw = detail({
      transcript: [
        { idx: 0, speaker: "caller", text: `My number is ${RAW_NUMBER}.`, redacted: false },
      ],
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    const first = await renderClientPage(page, routes(detail(), { [RAW_PATH]: raw }), "acme", client);
    fireEvent.click(await screen.findByRole("button", { name: /show full transcript/i }));
    expect(await screen.findByText(`My number is ${RAW_NUMBER}.`)).toBeTruthy();
    expect(first.calls.filter((c) => c.path === RAW_PATH).length).toBe(1);

    first.unmount();

    const second = await renderClientPage(page, routes(detail(), { [RAW_PATH]: raw }), "acme", client);
    // Nothing unredacted is on screen, and nothing was asked for, before the reader asks.
    await screen.findByText("My number is [redacted].");
    expect(screen.queryByText(`My number is ${RAW_NUMBER}.`)).toBeNull();
    expect(second.calls.filter((c) => c.path === RAW_PATH).length).toBe(0);

    fireEvent.click(await screen.findByRole("button", { name: /show full transcript/i }));
    expect(await screen.findByText(`My number is ${RAW_NUMBER}.`)).toBeTruthy();
    expect(second.calls.filter((c) => c.path === RAW_PATH).length).toBe(1);
  });

  it("does not offer a recording this call does not have, and never links the engine's copy", async () => {
    const { container, calls } = await renderClientPage(
      page,
      routes(detail({ has_recording: false })),
    );

    await screen.findByText("My number is [redacted].");
    expect(screen.queryByRole("button", { name: /listen/i })).toBeNull();
    expect(calls.some((c) => c.path.endsWith("/recording"))).toBe(false);
    // Nothing on this screen may point at the vendor (hard rule 2 + §4 residency): our
    // presigned copy is the only audio a client is ever handed.
    expect(container.innerHTML).not.toContain("bolna");
  });

  it("fetches the presigned recording link on the click, not with the page", async () => {
    const { container, calls } = await renderClientPage(
      page,
      routes(detail({ has_recording: true }), {
        "/v1/calls/c1/recording": {
          url: "https://cdn.example.test/rec.mp3?sig=abc",
          expires_in_s: 600,
          duration_s: 300,
        },
      }),
    );

    const listen = await screen.findByRole("button", { name: /listen to this call/i });
    // Minting a signed URL burns its clock and writes an audit row for a listen that
    // never happened, so it must not be a page-load side effect.
    expect(calls.some((c) => c.path === "/v1/calls/c1/recording")).toBe(false);

    fireEvent.click(listen);
    // The player, not the browser's default element. The old assertion here read
    // "stops working in about 10 minutes" — a sentence that told the listener their
    // link would die and left them to do something about it. The link is now sized to
    // the audio and refreshed on expiry, so the sentence it replaces says that.
    expect(await screen.findByText(/refreshed automatically while you listen/)).toBeTruthy();
    // In an <audio>, not an <a href>: a signed URL in a link is a credential handed to
    // history and to the next page's referrer.
    expect(container.querySelector("audio")?.getAttribute("src")).toContain("rec.mp3");
    for (const link of Array.from(container.querySelectorAll("a"))) {
      expect(link.getAttribute("href") ?? "").not.toContain("sig=");
    }
  });

  it("keeps a missing disclosure answer apart from a disclosure that was not played", async () => {
    const unknown = await renderClientPage(page, routes(detail({ disclosure_played: null })));
    await screen.findByText("My number is [redacted].");
    // `null` is "the pipeline never recorded an answer", NOT "no". Telling an owner
    // their call was non-compliant on a null sends them to fix what was never broken.
    expect(unknown.container.textContent).not.toContain("No disclosure was played");
    unknown.unmount();

    await renderClientPage(page, routes(detail({ disclosure_played: false })));
    expect(await screen.findByText("No disclosure was played on this call")).toBeTruthy();
  });

  it("prints a speaker it has never heard of rather than dropping the turn", async () => {
    const { container } = await renderClientPage(
      page,
      // DELIBERATELY OFF-CONTRACT: `TranscriptTurnOut.speaker` is the closed union
      // `"agent" | "caller"`, and a speaker outside it is the whole premise of this test.
      // So the payload is handed to the route map as the `unknown` it is, rather than
      // asserted into a union that does not contain it — an assertion here would keep
      // compiling on the day somebody removed a speaker from the union for real, which is
      // exactly the change this test exists to survive (tests/wireFixtureGuard.test.ts).
      routes({
        ...detail(),
        transcript: [
          { idx: 0, speaker: "constructor", text: "A line nobody may lose.", redacted: true },
        ],
      }),
    );

    // `lookup`, not `SPEAKERS[turn.speaker]`: a wire value naming an Object.prototype
    // member resolves to the `Object` function, which `??` does not treat as missing
    // (src/lib/lookup.ts). Fails VISIBLE — the line and its unfamiliar speaker.
    expect(await screen.findByText("A line nobody may lose.")).toBeTruthy();
    expect(container.textContent).toContain("constructor");
  });
});

/**
 * The follow-up card, and the silence it used to fall into.
 *
 * `{eligibility.data && <Card title="Follow up">…}` — and `eligibility.data` is undefined
 * while `/v1/calls/{id}/callback` is in flight AND after it fails. So a 503 on that read
 * deleted the entire card: no button, no reason, nothing to retry. The card's own comment
 * says it is rendered "whenever the API has an opinion — disabled WITH the reason rather
 * than hidden, so 'why can't I follow this up?' is answered on screen", which is exactly
 * what the missing branch stopped it doing.
 */
describe("the follow-up card when the eligibility read did not answer", () => {
  it("refuses in place, rather than deleting itself, on a failed read", async () => {
    const { container } = await renderClientPage(
      page,
      routes(detail(), {
        "/v1/calls/c1/callback": problem(503, { title: "Service unavailable", retryable: true }),
      }),
    );

    // PRESENT, not merely "the button is gone" — an empty screen satisfies that too.
    expect(await screen.findByText("Follow up")).toBeTruthy();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Service unavailable");
    expect(container.textContent).toContain(
      "We could not check whether this call can be followed up",
    );
    // And the action is not offered on a check that never landed.
    expect(screen.queryByRole("button", { name: /Call back with AI/ })).toBeNull();
  });

  it("still renders the card, with its reason, when the server answered", async () => {
    // The premise: without this, the test above passes on a screen with no card at all.
    const { container } = await renderClientPage(page, routes(detail()));

    expect(await screen.findByText("Follow up")).toBeTruthy();
    expect(container.textContent).toContain("This call was answered.");
    expect(container.textContent).not.toContain("We could not check whether this call");
  });
});
