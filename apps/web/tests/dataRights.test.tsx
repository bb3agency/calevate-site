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
const STATUS_PATH = `/v1/compliance/deletion-requests/${REQUEST_ID}`;

/** The document the export endpoint answers with — opaque to us, and deliberately so. */
const EXPORT_DOCUMENT = { phone_e164: PHONE, calls: [], counts: { calls: 0 } };

function render(routes: Record<string, unknown>, me: Me = OWNER) {
  return renderClientPage(<DataRightsPage />, { "/v1/me": me, ...routes });
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

  it("shows the certificate with what survived the erasure, not only what it cleared", async () => {
    await render({ [STATUS_PATH]: completedRequest() });

    type(/Look up a request id/, REQUEST_ID);
    fireEvent.click(screen.getByRole("button", { name: "Track it" }));

    expect(await screen.findByText("Erasure complete")).toBeTruthy();
    expect(screen.getByText("Proof certificate")).toBeTruthy();
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
    const view = await render({ [STATUS_PATH]: completedRequest() });

    type(/Look up a request id/, REQUEST_ID);
    fireEvent.click(screen.getByRole("button", { name: "Track it" }));
    await screen.findByText("Proof certificate");

    await expectNoA11yViolations(view.container, "c/[slug]/data-rights (certificate)");
  });

  it("says an erasure was already running instead of reporting a fault", async () => {
    await render({
      [FILE_PATH]: { ...pendingRequest(), already_open: true },
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
      [STATUS_PATH]: problem(503, {
        title: "We could not read this erasure request",
        detail: "The database was unreachable.",
        retryable: true,
      }),
    });

    type(/Look up a request id/, REQUEST_ID);
    fireEvent.click(screen.getByRole("button", { name: "Track it" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();

    // None of the three things a client could act on may appear over a read that never
    // landed: not the completed verdict, not the pending one, and not the certificate.
    expect(screen.queryByText("Erasure complete")).toBeNull();
    expect(screen.queryByText(/Submitted — waiting to run/)).toBeNull();
    expect(screen.queryByText("Proof certificate")).toBeNull();
    // And not the "nothing tracked" copy either — an empty state under a failed read is
    // the §52 defect wearing a different word.
    expect(screen.queryByText(/Nothing filed from this session yet/)).toBeNull();
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
