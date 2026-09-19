import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantKycPage from "@/app/admin/tenants/[tenantId]/kyc/page";
import { TenantNav } from "@/app/admin/tenants/[tenantId]/TenantNav";
import { carrierApplicationPath, type TenantSummary } from "@/lib/api/admin";
import { KYC_PATH, type CarrierApplication, type KycRecord } from "@/lib/api/kyc";

import { problem, type Routes } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The carrier compliance application — the ops half, which had NO caller at all.
 *
 * `GET|POST /v1/admin/tenants/{id}/carrier-application` shipped with the client's own two
 * surfaces and nothing in this console called either, which left live exactly the state
 * the route's module docstring names: "a decision ops cannot record is a client stuck
 * behind a carrier that has already said yes." A business could upload its registration
 * documents, we could forward them, the carrier could approve — and the row would sit at
 * `submitted` for ever, with `assert_carrier_application_accepted` refusing every number
 * purchase, because nobody at Calevate had a form to record the answer in.
 *
 * What these tests pin, worst failure first:
 *
 * 1. **The control exists and reaches the route**, ADMIN realm, our own `status` word,
 *    with the carrier's reference on it — the half that was missing.
 * 2. **A decision illegal from the state on file is refused BEFORE the round trip**, with
 *    a sentence naming what to do, rather than as a 409 out of the CAS.
 * 3. **An acceptance must carry the carrier's reference and a rejection its reason** —
 *    the two API validations, pre-empted where the operator is typing.
 * 4. **No confirmation header and no typed confirmation**: the route accepts none, every
 *    state has a way back, and ceremony on a reversible act teaches operators to type
 *    past ceremony (`set_tenant_plan_tier`'s argument).
 * 5. **`is_accepted` is printed, never re-derived** — the purchase gate's own predicate.
 * 6. **An unreadable application withholds the form** instead of offering a blind write
 *    over a state nobody can see, which is what the KYC form above it does and why.
 * 7. **A status this build cannot name fails VISIBLE**, printed as the server sent it.
 * 8. **A session without `admin:tenants` gets a disabled control with its reason.**
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000c1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const CARRIER_PATH = carrierApplicationPath(TENANT);
const SUBMIT = { name: /Record decision/ };

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 4,
    leads: 2,
    holds: [],
    last_call_at: null,
    capped: false,
  };
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000c2",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

/** A read-only support session: `org:read` and no `admin:tenants`. */
const READER: AdminMe = { ...ME, role: "support", permissions: ["org:read"] };

/** The KYC record the panel above ours reads. Not what this file is about. */
function kyc(): KycRecord {
  return {
    recorded: false,
    status: null,
    entity_type: null,
    document_kind: null,
    document_ref: null,
    signatory_name: null,
    evidence_ref: null,
    rejection_reason: null,
    submitted_at: null,
    verified_at: null,
    is_verified: false,
    number_purchase_available: false,
  };
}

function application(over: Partial<CarrierApplication> = {}): CarrierApplication {
  return {
    recorded: true,
    carrier: "Plivo",
    status: "submitted",
    carrier_application_id: null,
    document_kind: "gst_certificate",
    document_filename: "gst.pdf",
    signed_application_on_file: true,
    rejection_reason: null,
    submitted_at: "2026-09-10T06:30:00Z",
    decided_at: null,
    is_accepted: false,
    ...over,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<TenantKycPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    [KYC_PATH]: kyc(),
    [CARRIER_PATH]: application(),
    ...routes,
  });
}

const DECIDED = {
  [`POST ${CARRIER_PATH}`]: {
    tenant_id: TENANT,
    status: "accepted",
    carrier_application_id: "CA-2026-8891",
    changed: true,
  },
};

describe("the carrier compliance application panel", () => {
  it("records an acceptance with the carrier's reference, on an admin session", async () => {
    const { calls } = await render(DECIDED);

    fireEvent.change(await screen.findByLabelText(/application reference/), {
      target: { value: "CA-2026-8891" },
    });
    fireEvent.click(screen.getByRole("button", SUBMIT));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === CARRIER_PATH)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === CARRIER_PATH);
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      // OUR word, never the carrier's: `_resolved_status` refuses both-or-neither, and
      // the console deliberately offers no transcription box.
      status: "accepted",
      carrier_status: null,
      carrier_application_id: "CA-2026-8891",
      rejection_reason: null,
    });
    // `admin:tenants` is a MUTATING permission — D-22 keeps it off an impersonating
    // session, and this route names its tenant in the path for exactly that reason.
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();
    // The route accepts no confirmation header, and a header the API ignores is a
    // confirmation of nothing.
    expect(post?.headers["X-Confirm-Action"]).toBeUndefined();
  });

  it("refuses a decision the application's state does not allow, naming what to do", async () => {
    // Already accepted: only `expired` is legal from here, so the default `accepted`
    // must be refused BEFORE the CAS answers 409.
    const { calls, container } = await render({
      [CARRIER_PATH]: application({
        status: "accepted",
        carrier_application_id: "CA-2026-0001",
        decided_at: "2026-09-12T06:30:00Z",
        is_accepted: true,
      }),
      ...DECIDED,
    });

    const button = await screen.findByRole("button", SUBMIT);
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((c) => c.method === "POST" && c.path === CARRIER_PATH)).toBe(false);
    // A remedy, not a rule name: which state it is in, which states the decision needs,
    // and the two things that are actually going on when an operator sees this.
    expect(container.textContent).toContain('can only be recorded while it is "With the carrier"');
    expect(container.textContent).toContain("a colleague may have recorded this already");
  });

  it("will not accept an application without the carrier's own reference", async () => {
    const { calls, container } = await render(DECIDED);

    const button = await screen.findByRole("button", SUBMIT);
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((c) => c.method === "POST" && c.path === CARRIER_PATH)).toBe(false);
    expect(container.textContent).toContain("A number purchase quotes it");
  });

  it("will not record a rejection with no reason for the client to act on", async () => {
    const { calls, container } = await render(DECIDED);

    fireEvent.change(await screen.findByLabelText(/What the carrier decided/), {
      target: { value: "rejected" },
    });
    const button = screen.getByRole("button", SUBMIT);
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((c) => c.method === "POST" && c.path === CARRIER_PATH)).toBe(false);
    expect(container.textContent).toContain("the only person who can fix it");
  });

  it("prints the server's own number-gate verdict rather than deriving one", async () => {
    const { container } = await render({
      [CARRIER_PATH]: application({
        status: "accepted",
        carrier_application_id: "CA-2026-0001",
        is_accepted: true,
        decided_at: "2026-09-12T06:30:00Z",
      }),
    });

    await screen.findByText("Application on file");
    expect(container.textContent).toContain("numbers open");
  });

  it("says numbers are closed while the carrier has not accepted", async () => {
    const { container } = await render({
      [CARRIER_PATH]: application({ is_accepted: false }),
    });

    await screen.findByText("Application on file");
    expect(container.textContent).toContain("numbers closed");
  });

  it("reports an already-in-this-state answer as nothing moved", async () => {
    const { container } = await render({
      [`POST ${CARRIER_PATH}`]: {
        tenant_id: TENANT,
        status: "accepted",
        carrier_application_id: "CA-2026-8891",
        changed: false,
      },
    });

    fireEvent.change(await screen.findByLabelText(/application reference/), {
      target: { value: "CA-2026-8891" },
    });
    fireEvent.click(screen.getByRole("button", SUBMIT));

    await waitFor(() => {
      expect(container.textContent).toContain("so nothing moved");
    });
  });

  it("says nothing is with the carrier yet, and whose move that is", async () => {
    const { container } = await render({
      [CARRIER_PATH]: application({
        recorded: false,
        carrier: null,
        status: null,
        document_kind: null,
        document_filename: null,
        signed_application_on_file: false,
        submitted_at: null,
      }),
    });

    await screen.findByText("Nothing sent to the carrier yet");
    // Absence is a STATE, not a failure — and the next move is the client's, which is the
    // fact an operator hunting for a form they cannot find needs.
    expect(container.textContent).toContain("only they hold them");
  });

  it("withholds the form when the application cannot be read", async () => {
    const { container } = await render({
      [CARRIER_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "The database is unreachable.",
        retryable: true,
      }),
    });

    await screen.findByText("Cannot record a decision while the application is unreadable");
    // A decision is a CAS against the state on file: recording one blind means guessing
    // which decision is even legal.
    expect(screen.queryByRole("button", SUBMIT)).toBeNull();
    expect(container.textContent).toContain("The database is unreachable.");
  });

  it("prints a status this build cannot name, rather than blanking or guessing it", async () => {
    const { container } = await render({
      // A state from a newer server. It must NOT resolve to one of the six we know.
      [CARRIER_PATH]: application({ status: "under_appeal" as CarrierApplication["status"] }),
    });

    await screen.findByText("Application on file");
    expect(container.textContent).toContain("under_appeal");
    expect(container.textContent).toContain("This build has no description for that state");
  });

  it("renders the refusal when the write fails, rather than a silent no-op", async () => {
    const { container } = await render({
      [`POST ${CARRIER_PATH}`]: problem(409, {
        title: "Already decided",
        detail: "This application is no longer with the carrier.",
      }),
    });

    fireEvent.change(await screen.findByLabelText(/application reference/), {
      target: { value: "CA-2026-8891" },
    });
    fireEvent.click(screen.getByRole("button", SUBMIT));

    await waitFor(() => {
      expect(container.textContent).toContain("This application is no longer with the carrier.");
    });
  });

  it("disables the control, with its reason, for a session that may not use it", async () => {
    const { calls } = await render({ [ADMIN_ME_PATH]: READER, ...DECIDED });

    const button = await screen.findByRole("button", SUBMIT);
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/record a carrier decision/)).toBeDefined();
    fireEvent.click(button);
    expect(calls.some((c) => c.method === "POST" && c.path === CARRIER_PATH)).toBe(false);
  });

  it("does not poll — every read of this route writes an audit row", async () => {
    const { calls } = await render();

    await screen.findByText("Application on file");
    expect(calls.filter((c) => c.method === "GET" && c.path === CARRIER_PATH)).toHaveLength(1);
  });
});

/**
 * The way in. Both checks in front of a phone connection are behind ONE nav entry, and it
 * is named for the question an operator is asking rather than for either record — the
 * screen they open when a client cannot have a number. It read "Identity (KYC)" while the
 * carrier half had no caller, which named the only record the screen then held.
 */
describe("finding the carrier decision at all", () => {
  it("names the tenant nav entry for both checks, not only ours", async () => {
    const { container } = await renderAdminRoute(
      <TenantNav tenantId={TENANT} slug="sri-traders" />,
      { [ADMIN_ME_PATH]: ME },
    );

    expect(container.textContent).toContain("Identity & carrier");
    const link = container.querySelector(`a[href="/admin/tenants/${TENANT}/kyc"]`);
    expect(link).not.toBeNull();
  });
});
