import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import PreferenceScrubPage from "@/app/admin/tenants/[tenantId]/dnd-scrub/page";
import type { TenantSummary } from "@/lib/api/admin";
import type { CampaignSummary } from "@/lib/api/campaigns";
import {
  preferenceScrubConfirmation,
  preferenceScrubPath,
  type PreferenceScrubOut,
} from "@/lib/api/preferenceScrub";

import { expectNoA11yViolations } from "./a11y";
import { problem, type Routes } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * THE NATIONAL DND SCRUB — the screen that unblocks promotional dialling.
 *
 * This is not a missing feature, it is the product blocker the route enumeration found.
 * `national_dnd_blocker` refuses every `promotional` campaign with
 * `national_dnd_scrub_missing` / `_expired`, at launch and on every dispatch tick; the
 * only writer of `preference_scrub_runs` is `record_scrub_run`, whose only caller is
 * `POST /v1/admin/tenants/{id}/campaigns/{cid}/preference-scrub` — and nothing in either
 * console called it. No promotional campaign could be launched by anybody.
 *
 * What these tests pin, worst failure first:
 *
 * 1. **The write reaches the route with the campaign-bound confirmation header.** It is
 *    `record_preference_scrub:<id>` — NOT `preference_scrub:<id>`, which is what a
 *    reading from memory produced and which the API would refuse.
 * 2. **The BLOCKED list is what travels**, split from a paste, unnormalized — the server
 *    decides what is a number and counts what it cannot read.
 * 3. **`scrubbed_at` is IST**, not the browser's clock and not UTC: the validity window
 *    is a day in India and getting the zone wrong is a whole day of dialling.
 * 4. **A future timestamp is refused before the round trip**, with the zone named as the
 *    likely cause.
 * 5. **Expiry is the SERVER's verdict.** `is_current: false` must not render as success
 *    however recent `scrubbed_at` looks, and it says what to do instead.
 * 6. **A replay is neither a failure nor a second run** (`recorded: false`).
 * 7. **The confirmation is the provider's reference, re-keyed**, and changing the
 *    reference invalidates it.
 * 8. **Only promotional, still-dialling campaigns are offered**, and a campaign list that
 *    FAILED to read is withheld rather than rendered as "nothing needs a scrub".
 * 9. **A session without `admin:tenants` gets a disabled control with its reason.**
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000d1";
const SLUG = "sri-traders";
const CAMPAIGN = "0192f0aa-7777-7000-8000-0000000000d2";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const SCRUB_PATH = preferenceScrubPath(TENANT, CAMPAIGN);
const CHECK_PATH = `/v1/campaigns/${CAMPAIGN}/launch-check`;
const SUBMIT = { name: /Record this scrub/ };

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: SLUG,
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 4,
    leads: 2,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000d3",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants", "campaigns:read"],
};

const READER: AdminMe = { ...ME, role: "support", permissions: ["org:read"] };

function campaign(over: Partial<CampaignSummary> = {}): CampaignSummary {
  return {
    id: CAMPAIGN,
    name: "Diwali offer",
    classification: "promotional",
    status: "draft",
    contacts: 1200,
    connected: 0,
    consent_provenance_blocker: null,
    created_at: "2026-09-18T05:00:00Z",
    launched_at: null,
    ...over,
  };
}

/** The gate as the launch check reports it while no scrub exists. */
const HELD = {
  ready: false,
  blockers: [
    {
      rule: "national_dnd_scrub_missing",
      reason:
        "This promotional campaign's list has not been scrubbed against the national customer preference register.",
    },
  ],
};

function result(over: Partial<PreferenceScrubOut> = {}): PreferenceScrubOut {
  return {
    recorded: true,
    submitted: 1200,
    suppressed: 3,
    unmatched: 0,
    malformed: 0,
    provider: "Vodafone Idea",
    scrub_ref: "SCRUB-2026-09-19-77",
    scrubbed_at: "2026-09-19T05:30:00Z",
    expires_at: "2026-09-19T18:29:59Z",
    is_current: true,
    ...over,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<PreferenceScrubPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    "/v1/campaigns": [campaign()],
    [CHECK_PATH]: HELD,
    ...routes,
  });
}

function submitButton(): HTMLButtonElement {
  return screen.getByRole("button", SUBMIT) as HTMLButtonElement;
}

/**
 * Choose the campaign, fill the form, re-key the reference — and WAIT for the control to
 * become live.
 *
 * The wait is load-bearing rather than a flake guard: every control on an admin screen is
 * disabled until `GET /v1/admin/me` has answered (`useAdminAccess` fails CLOSED on the
 * unknown), so an assertion made before that settles would pass for a reason that has
 * nothing to do with the rule under test. Every "this is refused" case below therefore
 * reaches a LIVE button first and then breaks one thing.
 */
async function fillForm(ref = "SCRUB-2026-09-19-77") {
  fireEvent.change(await screen.findByLabelText(/Promotional campaign/), {
    target: { value: CAMPAIGN },
  });
  fireEvent.change(await screen.findByLabelText(/Access provider/), {
    target: { value: "Vodafone Idea" },
  });
  fireEvent.change(screen.getByLabelText(/Their reference for this run/), {
    target: { value: ref },
  });
  fireEvent.change(screen.getByLabelText(/Numbers the register SUPPRESSED/), {
    target: { value: "+919000000001, +919000000002\n+919000000003" },
  });
  fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: ref } });
  await waitFor(() => expect(submitButton().disabled).toBe(false));
}

describe("recording a national DND scrub", () => {
  it("posts to the admin route with the campaign-bound confirmation header", async () => {
    const { calls } = await render({ [`POST ${SCRUB_PATH}`]: result() });

    await fillForm();
    fireEvent.click(submitButton());

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === SCRUB_PATH)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === SCRUB_PATH);
    // ⚠ `record_preference_scrub:<id>`. The shorter `preference_scrub:<id>` is what a
    // reading from memory produced, and every scrub would have been refused on a header
    // an operator could not debug.
    expect(post?.headers["X-Confirm-Action"]).toBe(preferenceScrubConfirmation(CAMPAIGN));
    expect(preferenceScrubConfirmation(CAMPAIGN)).toBe(`record_preference_scrub:${CAMPAIGN}`);
    // `admin:tenants` is mutating, so D-22 keeps it off an impersonating session.
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();

    const body = JSON.parse(post?.body ?? "{}");
    expect(body.provider).toBe("Vodafone Idea");
    expect(body.scrub_ref).toBe("SCRUB-2026-09-19-77");
    // The SUPPRESSED list, split from the paste and sent exactly as typed: the server's
    // `normalize_phone` decides what is a number and COUNTS what it cannot read. A
    // console that cleaned the list would be deciding which numbers were blocked.
    expect(body.blocked_numbers).toEqual([
      "+919000000001",
      "+919000000002",
      "+919000000003",
    ]);
    // There is no `submitted` field and there must never be one — the server counts it.
    expect(body.submitted).toBeUndefined();
    expect(body.submitted_count).toBeUndefined();
  });

  it("sends the moment the operator typed as IST, not as the machine's clock", async () => {
    const { calls } = await render({ [`POST ${SCRUB_PATH}`]: result() });

    await fillForm();
    fireEvent.change(screen.getByLabelText(/When the provider ran it/), {
      target: { value: "2026-09-19T11:00" },
    });
    fireEvent.click(submitButton());

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === SCRUB_PATH)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === SCRUB_PATH);
    // 11:00 IST is 05:30Z. The validity window is a DAY IN INDIA, so a browser-local or
    // UTC reading of these digits is a whole day of dialling either side of the truth.
    expect(JSON.parse(post?.body ?? "{}").scrubbed_at).toBe("2026-09-19T05:30:00.000Z");
  });

  it("refuses a future timestamp before the round trip, naming the likely cause", async () => {
    const { calls, container } = await render({ [`POST ${SCRUB_PATH}`]: result() });

    await fillForm();
    fireEvent.change(screen.getByLabelText(/When the provider ran it/), {
      target: { value: "2099-01-01T10:00" },
    });
    expect(submitButton().disabled).toBe(true);
    fireEvent.click(submitButton());
    expect(calls.some((c) => c.method === "POST" && c.path === SCRUB_PATH)).toBe(false);
    expect(container.textContent).toContain("has not happened yet");
    expect(container.textContent).toContain("UTC time into a field that means IST");
  });

  it("does not report a recorded-but-expired run as an open gate", async () => {
    const { container } = await render({
      // The server's own verdict. It is NOT re-derived from `expires_at` here, because a
      // run recorded after its own day has ended is a legitimate historical record that
      // does not satisfy the gate — and only the server is entitled to say which.
      [`POST ${SCRUB_PATH}`]: result({
        is_current: false,
        scrubbed_at: "2026-09-18T05:30:00Z",
        expires_at: "2026-09-18T18:29:59Z",
      }),
    });

    await fillForm();
    fireEvent.click(submitButton());

    await waitFor(() => {
      expect(container.textContent).toContain("does NOT open the gate");
    });
    expect(container.textContent).toContain("ask the provider for a scrub run TODAY");
    expect(container.textContent).not.toContain("this campaign may launch");
  });

  it("says when the scrub stops being good, and that dialling outlives it", async () => {
    const { container } = await render({ [`POST ${SCRUB_PATH}`]: result() });

    await fillForm();
    fireEvent.click(submitButton());

    await waitFor(() => {
      expect(container.textContent).toContain("this campaign may launch");
    });
    expect(container.textContent).toContain("midnight IST");
    // The half nobody guesses: the campaign keeps dialling past the expiry.
    expect(container.textContent).toContain("does not cover tomorrow");
  });

  it("reports a replay as nothing new written, not as a failure and not as a second run", async () => {
    const { container } = await render({
      [`POST ${SCRUB_PATH}`]: result({ recorded: false }),
    });

    await fillForm();
    fireEvent.click(submitButton());

    await waitFor(() => {
      expect(container.textContent).toContain("were already on file");
    });
    // It still opened the gate, so it is not rendered as a refusal.
    expect(container.textContent).toContain("this campaign may launch");
  });

  it("will not submit until the provider's reference is re-keyed", async () => {
    const { calls } = await render({ [`POST ${SCRUB_PATH}`]: result() });

    // A live button first, so what follows is about the confirmation and not about an
    // identity read that has not answered yet.
    await fillForm();
    fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: "" } });

    expect(submitButton().disabled).toBe(true);
    fireEvent.click(submitButton());
    expect(calls.some((c) => c.method === "POST" && c.path === SCRUB_PATH)).toBe(false);
  });

  it("invalidates the confirmation when the reference is corrected", async () => {
    const { calls } = await render({ [`POST ${SCRUB_PATH}`]: result() });

    await fillForm();

    // The operator spots a typo and fixes the reference. The confirmation named the OLD
    // one, so it must stop counting — otherwise a corrected reference is filed under a
    // confirmation typed for a different string.
    fireEvent.change(screen.getByLabelText(/Their reference for this run/), {
      target: { value: "SCRUB-2026-09-19-78" },
    });
    expect(submitButton().disabled).toBe(true);
    fireEvent.click(submitButton());
    expect(calls.some((c) => c.method === "POST" && c.path === SCRUB_PATH)).toBe(false);
  });

  it("shows the gate's own refusal for the chosen campaign, in the server's words", async () => {
    const { container } = await render();

    fireEvent.change(await screen.findByLabelText(/Promotional campaign/), {
      target: { value: CAMPAIGN },
    });

    await waitFor(() => {
      expect(container.textContent).toContain("No scrub on file — this campaign is held");
    });
    expect(container.textContent).toContain("national customer preference register");
  });

  it("says the gate is open, and that it shuts again at midnight", async () => {
    const { container } = await render({ [CHECK_PATH]: { ready: true, blockers: [] } });

    fireEvent.change(await screen.findByLabelText(/Promotional campaign/), {
      target: { value: CAMPAIGN },
    });

    await waitFor(() => {
      expect(container.textContent).toContain("gate is open for this campaign");
    });
    // The expiry is the whole point of saying it here: a campaign that launched on a
    // valid scrub is dialling an unscrubbed list by morning.
    expect(container.textContent).toContain("stops being current at midnight IST");
  });

  it("names an expired scrub differently from a missing one", async () => {
    const { container } = await render({
      [CHECK_PATH]: {
        ready: false,
        blockers: [
          {
            rule: "national_dnd_scrub_expired",
            reason: "The scrub on this campaign's list was run on 18 Sep and is no longer current.",
          },
        ],
      },
    });

    fireEvent.change(await screen.findByLabelText(/Promotional campaign/), {
      target: { value: CAMPAIGN },
    });

    await waitFor(() => {
      expect(container.textContent).toContain("The scrub on file has expired");
    });
  });

  it("offers no scrub for traffic the register does not scope", async () => {
    const { container } = await render({
      "/v1/campaigns": [
        campaign({ classification: "transactional" }),
        campaign({ id: "0192f0aa-7777-7000-8000-0000000000d9", classification: "service" }),
      ],
    });

    await screen.findByText("No campaign here needs a scrub");
    expect(container.textContent).toContain("transactional or service traffic");
    expect(screen.queryByRole("button", SUBMIT)).toBeNull();
  });

  it("offers no scrub for a campaign that will not dial again", async () => {
    // `SCRUBBABLE_CAMPAIGN_STATUSES` — evidence against a completed campaign is evidence
    // of nothing, and the route refuses it.
    await render({ "/v1/campaigns": [campaign({ status: "completed" })] });

    await screen.findByText("No campaign here needs a scrub");
  });

  it("withholds the picker when the campaign list could not be read", async () => {
    const { container } = await render({
      "/v1/campaigns": problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this client's campaigns.",
        retryable: true,
      }),
    });

    await screen.findByText("Cannot list this client's campaigns");
    // "Nothing needs a scrub" is also a REAL state; rendering it over a failed read tells
    // an operator there is nothing to unblock on the screen they came to unblock it on.
    expect(container.textContent).toContain("not the same as there being none");
    expect(screen.queryByText("No campaign here needs a scrub")).toBeNull();
  });

  it("renders the refusal when the write fails, rather than a silent no-op", async () => {
    const { container } = await render({
      [`POST ${SCRUB_PATH}`]: problem(422, {
        title: "Scrub timestamp is in the future",
        detail: "A scrub timestamp records something a provider already did.",
      }),
    });

    await fillForm();
    fireEvent.click(submitButton());

    await waitFor(() => {
      expect(container.textContent).toContain("records something a provider already did");
    });
  });

  it("disables the control, with its reason, for a session that may not use it", async () => {
    const { calls } = await render({
      [ADMIN_ME_PATH]: READER,
      [`POST ${SCRUB_PATH}`]: result(),
    });

    fireEvent.change(await screen.findByLabelText(/Promotional campaign/), {
      target: { value: CAMPAIGN },
    });
    // The REASON is what proves the identity read has answered — and that it answered
    // "refused" rather than "not yet". A disabled button alone would prove neither.
    await screen.findByText(/record a national DND scrub/);
    expect(submitButton().disabled).toBe(true);
    fireEvent.click(submitButton());
    expect(calls.some((c) => c.method === "POST" && c.path === SCRUB_PATH)).toBe(false);
  });
});

/**
 * The half `tests/a11y.test.tsx` cannot reach.
 *
 * That sweep renders each screen in its ENTRY state — its `Screen` entries have no
 * interaction hook — so it scans this one's campaign picker and never the form behind it.
 * Everything an operator actually types into mounts only after a campaign is chosen, so
 * it is scanned here, with the same helper, after choosing one.
 */
describe("the scrub form's accessibility", () => {
  it("has no axe violations with the form open", async () => {
    const { container } = await render();

    await fillForm();
    await expectNoA11yViolations(container, "admin/tenants/[tenantId]/dnd-scrub (form open)");
  });
});
