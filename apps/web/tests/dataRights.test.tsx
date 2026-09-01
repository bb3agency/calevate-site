import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DataRightsPage from "@/app/c/[slug]/data-rights/page";
import type { Me } from "@/lib/api/client";
import type { DeletionRequest } from "@/lib/api/dataRights";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage } from "./harness";

/**
 * DPDP data-principal rights — the screen that finally calls three endpoints which
 * shipped audited, worker-backed and with nobody calling them.
 *
 * What is actually at stake, and therefore what is asserted:
 *
 * - **Hard rule 6, on the number.** Both requests are POSTs with the number in the BODY,
 *   because a GET writes it into access logs, proxies, referrers and browser history.
 *   That is a property of the REQUEST rather than of the DOM, and the harness records
 *   every request the screen made, so it is asserted instead of trusted. The number must
 *   also not reach the DOM anywhere outside the input the user typed it into.
 * - **§52, on the erasure status.** "Nothing was erased" and "we could not ask" are one
 *   character apart in code and worlds apart in front of a regulator. A failed status
 *   read renders a refusal and NOTHING that looks like an answer.
 * - **The permission split.** The export is `calls:read_raw` (owner only) and filing is
 *   `org:manage`; a `staff` session gets an explanation beside a disabled control rather
 *   than a dead button or a 403 that reads like an outage.
 *
 * The number planted below appears in no fixture payload, so every "must not appear"
 * assertion here is load-bearing: if it shows up, the screen put it there.
 */

const PHONE = "+919876543210";
const REQUEST_ID = "0192f0aa-4444-7000-8000-0000000000ab";

const OWNER: Me = {
  impersonating: false,
  permissions: ["calls:read", "calls:read_raw", "leads:read", "org:read", "org:manage"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/** A viewer who may look at the account and neither export nor erase anyone (`staff`). */
const STAFF: Me = {
  ...OWNER,
  permissions: ["calls:read", "leads:read", "org:read"],
  role: "staff",
};

const LIMITATIONS = [
  "Call recordings: the pointer to the audio is cleared immediately, so nothing in this system can reach, play or export it.",
  "consent_ledger entries are retained, and they carry the caller's number.",
];

function pendingRequest(): DeletionRequest {
  return {
    request_id: REQUEST_ID,
    subject_ref: "b1946ac92492d2347c6235b4d2611184",
    status: "pending",
    requested_at: "2026-08-14T06:00:00Z",
    completed_at: null,
    proof: null,
    limitations: LIMITATIONS,
  };
}

function completedRequest(): DeletionRequest {
  return {
    ...pendingRequest(),
    status: "completed",
    completed_at: "2026-08-14T06:04:00Z",
    proof: {
      subject_hash: "b1946ac92492d2347c6235b4d2611184",
      executed_at: "2026-08-14T06:04:00Z",
      scope: {
        calls: ["a1", "a2"],
        leads: ["l1"],
        transcript_turns_erased: 34,
        call_extractions_erased: 2,
        recordings_within_trai_floor: 1,
        // Required on the wire since the caller-chunk erasure landed on the proof. Numeric
        // means the store was searched; `null` (a proof predating it) means it could not be.
        caller_vectors_erased: 27,
        caller_memories_erased: 3,
        // Required on the wire since the recording-hold fields landed on the proof;
        // added by the slice that regenerated the client, so the fixture is a shape the
        // server can actually send.
        recordings_destroyed: 0,
        recording_hold_until: "2026-11-12T06:04:00Z",
        // D-179's ninth limitation: the knowledge base is SEARCHED and not erased, so the
        // proof carries how many documents matched rather than a count destroyed. Zero is
        // the ordinary answer and is not the same as `null` (not searched), which is why
        // the fixture states it rather than omitting the key.
        knowledge_base_documents_matched: 0,
      },
      actions: { calls: "personal fields cleared" },
      engine_deletion: "unconfirmed_pending_vendor_api",
      erased: ["The transcripts of 2 calls."],
      not_erased: [
        {
          what: "The audio recordings of the calls this erasure covered.",
          outcome: "retained_under_legal_floor",
          why: "Indian telecom rules require call recordings to be kept for at least 90 days.",
          authority: "TRAI 90-day recording-retention floor (SECURITY-COMPLIANCE §1).",
          count: 1,
        },
      ],
      limitations: LIMITATIONS,
      limitations_version: "v3",
    },
  };
}

const EXPORT_PATH = "POST /v1/compliance/subject-export";
const FILE_PATH = "POST /v1/compliance/deletion-requests";
const LIST_PATH = "/v1/compliance/deletion-requests?limit=100";
const STATUS_PATH = `/v1/compliance/deletion-requests/${REQUEST_ID}`;

/**
 * The export document as the endpoint now models it. Only `counts` is read by the screen
 * — the rest of the document is never rendered, on purpose — and the counts are planted
 * with distinguishable values so an assertion cannot pass on the wrong field.
 */
const EXPORT_DOCUMENT = {
  phone_e164: PHONE,
  generated_at: "2026-08-14T06:00:00+00:00",
  // `null` = nobody has asked for this number to be erased, which is the ordinary case
  // and a different answer from an erasure with nothing outstanding.
  erasure: null,
  lead: null,
  calls: [],
  transcripts: [],
  consent: [],
  counts: {
    leads: 1,
    calls: 3,
    transcript_turns: 47,
    consent_records: 2,
    recordings_available: 1,
  },
};

/** One row of the account's erasure register. */
function summary(overrides: Record<string, unknown> = {}) {
  return {
    request_id: REQUEST_ID,
    subject_ref: "b1946ac92492d2347c6235b4d2611184",
    status: "pending",
    requested_at: "2026-08-14T06:00:00Z",
    completed_at: null,
    has_certificate: false,
    ...overrides,
  };
}

const COMPLETED_SUMMARY = summary({
  status: "completed",
  completed_at: "2026-08-14T06:04:00Z",
  has_certificate: true,
});

/** The register answers empty unless a test says otherwise: it loads on every paint. */
function render(routes: Record<string, unknown>, me: Me = OWNER) {
  return renderClientPage(<DataRightsPage />, {
    "/v1/me": me,
    [LIST_PATH]: [],
    ...routes,
  });
}

/** Open one register row so its certificate panel mounts. */
async function open(name: RegExp = /Show the certificate|Show details/) {
  fireEvent.click(await screen.findByRole("button", { name }));
}

/** Fill a labelled field the way a person does — by its visible label. */
function type(label: string | RegExp, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("data rights — subject access export", () => {
  it("posts the number in the body and offers the file without rendering it", async () => {
    const view = await render({ [EXPORT_PATH]: EXPORT_DOCUMENT });

    type("Their phone number", PHONE);
    fireEvent.click(screen.getByRole("button", { name: /Build the export/ }));

    expect(await screen.findByText("The export is ready")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Save the file/ })).toBeTruthy();

    // The endpoint has a response model now, so the screen can state what it built. It
    // could not before: the document typed as an opaque JSON object, and saying anything
    // about it would have meant hand-writing a wire shape nothing checks.
    expect(screen.getByText("Transcript turns")).toBeTruthy();
    expect(screen.getByText("47")).toBeTruthy();

    const request = view.calls.find((call) => call.path === "/v1/compliance/subject-export");
    expect(request?.method).toBe("POST");
    expect(request?.body).toBe(JSON.stringify({ phone: PHONE }));

    // Hard rule 6: never in a URL, and never painted onto the page. The only place the
    // number lives is the input the user typed it into, which `textContent` does not see.
    for (const call of view.calls) expect(call.url).not.toContain("9876543210");
    expect(view.container.textContent ?? "").not.toContain("9876543210");
  });

  it("refuses rather than claiming an export exists when the request fails", async () => {
    await render({
      [EXPORT_PATH]: problem(503, { title: "Upstream unavailable", detail: "Try again shortly." }),
    });

    type("Their phone number", PHONE);
    fireEvent.click(screen.getByRole("button", { name: /Build the export/ }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    // The success panel and its download must be absent: a "Save the file" button over a
    // failed build hands someone an empty file and calls it their record.
    expect(screen.queryByText("The export is ready")).toBeNull();
    expect(screen.queryByRole("button", { name: /Save the file/ })).toBeNull();
  });
});

describe("data rights — filing an erasure", () => {
  it("stays disarmed until the confirmation is typed, then files and tracks the request", async () => {
    const view = await render({
      [FILE_PATH]: { ...pendingRequest(), already_open: false },
      [LIST_PATH]: [summary()],
      [STATUS_PATH]: pendingRequest(),
    });

    const submit = screen.getByRole("button", { name: /Erase this person's data/ });
    type(/Number to erase permanently/, PHONE);
    // A number alone must not arm an irreversible action.
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    type(/Type ERASE to confirm/, "ERASE");
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);

    expect(await screen.findByText(/Submitted — waiting to run/)).toBeTruthy();

    const filed = view.calls.find(
      (call) => call.path === "/v1/compliance/deletion-requests" && call.method === "POST",
    );
    expect(filed?.body).toBe(JSON.stringify({ phone: PHONE }));
    // Irreversible and therefore idempotent on the wire: a double-click must not file two.
    expect(filed?.headers["Idempotency-Key"]).toBeTruthy();
    for (const call of view.calls) expect(call.url).not.toContain("9876543210");
  });

  it("offers a target check before erasing — whose record the digits point at (DR-1)", async () => {
    const view = await render({ [EXPORT_PATH]: EXPORT_DOCUMENT, [LIST_PATH]: [] });

    type(/Number to erase permanently/, PHONE);
    // The typed ERASE confirms INTENT; this button confirms TARGET.
    fireEvent.click(screen.getByRole("button", { name: /Check whose record this is first/ }));

    await screen.findByText(/All of it will be erased/);
    const previewCall = view.calls.find(
      (call) => call.path === "/v1/compliance/subject-export" && call.method === "POST",
    );
    expect(previewCall?.body).toBe(JSON.stringify({ phone: PHONE }));

    // Changing the number withdraws the previous person's counts — a count standing
    // beside a different number is the wrong person's record vouching for this one.
    type(/Number to erase permanently/, "+919876543299");
    expect(screen.queryByText(/All of it will be erased/)).toBeNull();
  });

  it("says so in words when the target check finds nothing — the strongest sign of a typo", async () => {
    await render({
      [EXPORT_PATH]: {
        ...EXPORT_DOCUMENT,
        counts: { leads: 0, calls: 0, transcript_turns: 0, consent_records: 0, recordings_available: 0 },
      },
      [LIST_PATH]: [],
    });
    type(/Number to erase permanently/, PHONE);
    fireEvent.click(screen.getByRole("button", { name: /Check whose record this is first/ }));
    await screen.findByText(/check the digits/);
  });

  it("shows the certificate with what survived the erasure, not only what it cleared", async () => {
    await render({ [LIST_PATH]: [COMPLETED_SUMMARY], [STATUS_PATH]: completedRequest() });

    expect(await screen.findByText("Erasure complete")).toBeTruthy();
    await open();

    expect(await screen.findByText("Proof certificate")).toBeTruthy();
    expect(screen.getByText("Not erased")).toBeTruthy();
    expect(
      screen.getByText(/The audio recordings of the calls this erasure covered\./),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /Save the certificate/ })).toBeTruthy();
  });

  it("has no accessibility violations once the certificate is on screen", async () => {
    // The sweep in `tests/a11y.test.tsx` scans this screen at FIRST PAINT, where the
    // certificate does not exist yet — it only appears after a request has been tracked.
    // Scanning it here rather than leaving it uncovered: the exemption tables in
    // `tests/a11y.ts` are deliberately empty, and a state nobody scans is not an
    // exemption, it is a hole with no entry.
    const view = await render({
      [LIST_PATH]: [COMPLETED_SUMMARY],
      [STATUS_PATH]: completedRequest(),
    });

    await open();
    await screen.findByText("Proof certificate");

    await expectNoA11yViolations(view.container, "c/[slug]/data-rights (certificate)");
  });

  it("says an erasure was already running instead of reporting a fault", async () => {
    await render({
      [FILE_PATH]: { ...pendingRequest(), already_open: true },
      [LIST_PATH]: [summary()],
      [STATUS_PATH]: pendingRequest(),
    });

    type(/Number to erase permanently/, PHONE);
    type(/Type ERASE to confirm/, "ERASE");
    fireEvent.click(screen.getByRole("button", { name: /Erase this person's data/ }));

    expect(await screen.findByText(/already running/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("data rights — §52: a failed status read is a refusal, never an answer", () => {
  it("renders a refusal and no erasure verdict when the status read fails", async () => {
    await render({
      [LIST_PATH]: [COMPLETED_SUMMARY],
      [STATUS_PATH]: problem(503, {
        title: "We could not read this erasure request",
        detail: "The database was unreachable.",
        retryable: true,
      }),
    });

    await open();

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();

    // None of the three things a client could act on may appear over a read that never
    // landed: not the completed verdict, not the pending one, and not the certificate.
    expect(screen.queryByText("Proof certificate")).toBeNull();
    expect(screen.queryByText(/what an erasure cannot do/i)).toBeNull();
  });

  it("says it could not check, rather than refusing, when /v1/me fails", async () => {
    await render({ "/v1/me": problem(503, { title: "Identity unavailable" }) }, OWNER);

    expect(
      await screen.findByText(/We could not check what you are allowed to see/),
    ).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /Build the export/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

describe("data rights — the erasure register", () => {
  it("lists what the account has been asked to erase, by hash and never by number", async () => {
    const view = await render({
      [LIST_PATH]: [
        COMPLETED_SUMMARY,
        summary({
          request_id: "0192f0aa-4444-7000-8000-0000000000cd",
          subject_ref: "c0ffee1122334455667788990011aabb",
          status: "completed",
          completed_at: "2026-08-13T09:00:00Z",
          has_certificate: false,
        }),
        summary({ request_id: "0192f0aa-4444-7000-8000-0000000000ef" }),
      ],
    });

    expect(await screen.findByText("Erasure complete")).toBeTruthy();
    // The third state the list can state on its own: complete, with no proof recorded.
    // A client must never report that one to a data principal as finished, which is the
    // whole reason `has_certificate` rides the index instead of the certificate.
    expect(screen.getByText("Complete — no certificate recorded")).toBeTruthy();
    expect(screen.getByText(/Submitted — waiting to run/)).toBeTruthy();

    // The register is the one read that returns many subjects at once, so this is where
    // a number would leak in bulk. Neither the request nor the rendered rows carry one.
    for (const call of view.calls) expect(call.url).not.toContain("9876543210");
    expect(view.container.textContent ?? "").not.toContain("9876543210");

    // Certificates are fetched per request, so opening the screen must not pull every
    // proof on the account across the wire.
    expect(view.calls.filter((call) => call.path.startsWith(STATUS_PATH))).toHaveLength(0);
  });

  it("refuses rather than claiming the account has no erasure requests", async () => {
    // §52 at its sharpest: "you have been asked to erase nobody" and "we could not read
    // what you have been asked to erase" are one branch apart, and only the first is a
    // sentence a client could repeat to a regulator.
    await render({
      [LIST_PATH]: problem(503, {
        title: "We could not read your erasure requests",
        detail: "The database was unreachable.",
        retryable: true,
      }),
    });

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryByText(/No erasure requests have been filed/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Show the certificate/ })).toBeNull();
  });

  it("says the register is empty only when the server said so", async () => {
    await render({ [LIST_PATH]: [] });

    expect(await screen.findByText(/No erasure requests have been filed/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("re-reads the register after a request is filed, instead of remembering it here", async () => {
    const view = await render({
      [FILE_PATH]: { ...pendingRequest(), already_open: false },
      [LIST_PATH]: [summary()],
    });

    type(/Number to erase permanently/, PHONE);
    type(/Type ERASE to confirm/, "ERASE");
    fireEvent.click(screen.getByRole("button", { name: /Erase this person's data/ }));

    // The filed request has to come back from the server's register, not from component
    // state: a closed tab must not lose the handle on a live legal obligation.
    await waitFor(() =>
      expect(view.calls.filter((call) => call.path === LIST_PATH).length).toBeGreaterThan(1),
    );
  });
});

describe("data rights — permissions", () => {
  it("explains the refusal beside each disabled control for a staff session", async () => {
    await render({}, STAFF);

    expect(
      await screen.findByText(/Only an account owner can build a subject access export/),
    ).toBeTruthy();
    expect(screen.getByText(/Only an account owner can file an erasure request/)).toBeTruthy();

    expect(
      (screen.getByRole("button", { name: /Build the export/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: /Erase this person's data/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});
