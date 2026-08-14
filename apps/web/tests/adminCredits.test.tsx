import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantCreditsPage from "@/app/admin/tenants/[tenantId]/credits/page";
import type { TenantSummary } from "@/lib/api/admin";
import {
  LEDGER_LIMIT,
  adjustmentsPath,
  creditAdjustmentConfirmation,
  creditsPath,
  type AdjustmentResult,
  type Credits,
  type LedgerEntry,
  type TopUpResult,
} from "@/lib/api/credits";

import { expectNoA11yViolations } from "./a11y";
import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * Credits — the screen that replaced a hand-assembled curl on the money-in path.
 *
 * What these pin, worst first:
 *
 * 1. **A REPEATED reference must read as "already recorded", never as a fresh credit.**
 *    Both outcomes are 200 and differ only by `TopUpOut.recorded`, so a screen that
 *    ignored the flag would tell an operator they had just credited a client who was
 *    already paid — and the entry cannot be taken back, so the belief is what causes the
 *    damage (they go looking for the "extra" money, or refund it). This is the assertion
 *    the slice exists for.
 * 2. **A failed READ withholds the form.** §52 with money on it: "no entries on this
 *    wallet" is also a real state, and it is the one an operator resolves by crediting.
 *    Writing against a ledger nobody can see removes the only check that catches a
 *    payment a colleague recorded an hour ago.
 * 3. **Money leaves as the exact STRING that was typed.** `TopUpIn.amount_inr` accepts a
 *    JSON number and the route refuses one (hard rule 7); a `Number()` anywhere on this
 *    path turns ₹2500.10 into a paise dispute.
 * 4. **The confirmation is the reference, typed twice**, and the button is dead until the
 *    two match — the only guard that catches a transcription error BEFORE the write.
 * 5. **The compensating-entry path is on the screen**, because the ledger is append-only
 *    and the operator who needs that sentence is the one who has already clicked.
 */

const TENANT = "0192f0aa-5555-7000-8000-0000000000a1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const CREDITS_PATH = creditsPath(TENANT);
const CREDITS_READ = `${CREDITS_PATH}?limit=${LEDGER_LIMIT}`;
const ADJUST_PATH = adjustmentsPath(TENANT);
const REF = "UTR-902311";
const ENTRY = "0192f0aa-5555-7000-8000-0000000000b1";

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  } as TenantSummary;
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-5555-7000-8000-0000000000a2",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
} as AdminMe;

function entry(over: Partial<LedgerEntry> = {}): LedgerEntry {
  return {
    id: ENTRY,
    delta_inr: "2500.00",
    reason: "topup",
    ref: REF,
    balance_after_inr: "2500.00",
    occurred_at: "2026-08-12T05:30:00Z",
    // How much of this entry a compensating adjustment can still take back — the
    // server's figure, because the console does no decimal arithmetic on money.
    reversible_inr: "2500.00",
    ...over,
  };
}

function correction(over: Partial<AdjustmentResult> = {}): AdjustmentResult {
  return {
    tenant_id: TENANT,
    entry_id: "0192f0aa-5555-7000-8000-0000000000c1",
    corrects_entry_id: ENTRY,
    ref: `adjust:${ENTRY}:2500.00`,
    delta_inr: "-2500.00",
    balance_inr: "0.00",
    is_low: true,
    recorded: true,
    stops_dialling: false,
    ...over,
  };
}

function credits(over: Partial<Credits> = {}): Credits {
  return {
    tenant_id: TENANT,
    balance_inr: "2500.00",
    is_low: false,
    low_balance_threshold_inr: "200.00",
    entries: [entry()],
    ...over,
  };
}

function result(over: Partial<TopUpResult> = {}): TopUpResult {
  return {
    tenant_id: TENANT,
    entry_id: "0192f0aa-5555-7000-8000-0000000000b2",
    payment_ref: "UTR-900042",
    amount_inr: "2500.10",
    balance_inr: "5000.10",
    is_low: false,
    recorded: true,
    ...over,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<TenantCreditsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    [CREDITS_READ]: credits(),
    ...routes,
  });
}

/** Fill the form the way an operator does: reference, reference again, amount. */
async function fillTopUp(reference: string, amount: string) {
  const ref = (await screen.findByLabelText("Bank reference (UTR / RRN)")) as HTMLInputElement;
  fireEvent.change(ref, { target: { value: reference } });
  fireEvent.change(screen.getByLabelText("Type the reference again"), {
    target: { value: reference },
  });
  fireEvent.change(screen.getByLabelText("Amount received (₹)"), { target: { value: amount } });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: /^Credit / }));
}

/** Fill the correction the way an operator does: entry, amount, amount again, why. */
async function fillCorrection(entryId: string, amount: string, why = "wrong client") {
  const select = (await screen.findByLabelText("Entry to correct")) as HTMLSelectElement;
  fireEvent.change(select, { target: { value: entryId } });
  fireEvent.change(screen.getByLabelText("Amount to take back (₹)"), {
    target: { value: amount },
  });
  fireEvent.change(screen.getByLabelText("Type the amount again"), {
    target: { value: amount },
  });
  fireEvent.change(screen.getByLabelText("Why (required)"), { target: { value: why } });
}

function correctButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /^(Take .* back off|Put .* back on|Correct this entry|Correcting)/,
  }) as HTMLButtonElement;
}

describe("the credits screen", () => {
  it("records a payment and sends the amount as the exact string, never a number", async () => {
    const { calls, container } = await render({
      [`POST ${CREDITS_PATH}`]: result(),
    });

    await fillTopUp("UTR-900042", "2500.10");
    submit();

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === CREDITS_PATH)).toBe(
        true,
      );
    });
    const post = calls.find((call) => call.method === "POST" && call.path === CREDITS_PATH);
    const body = JSON.parse(post?.body ?? "{}");
    // The whole of hard rule 7 at the last inch: a JSON number here is REFUSED by the
    // route rather than rounded, and 2500.10 through a binary float is the reason.
    expect(typeof body.amount_inr).toBe("string");
    expect(body.amount_inr).toBe("2500.10");
    expect(body.payment_ref).toBe("UTR-900042");
    // An unwritten note is `null`, not `""`: the entry's `meta` should not carry an
    // empty string somebody later reads as "a note was left".
    expect(body.note).toBeNull();
    // The admin session with the tenant in the PATH, never an impersonating one:
    // `admin:tenants` is in MUTATING_PERMISSIONS and D-22 refuses those to an acting-as
    // session.
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();
    // The route accepts no step-up header, so the console sends none — one that the API
    // ignores is a confirmation of nothing.
    expect(post?.headers["X-Confirm-Action"]).toBeUndefined();

    await screen.findByText("Recorded — ₹2,500.10 credited");
    expect(container.textContent).toContain("₹5,000.10");
  });

  it("reads a repeated reference as ALREADY RECORDED, not as a second credit", async () => {
    // The same 200 the route answers on a replay: the existing entry, `recorded: false`,
    // and a balance that did not move. The only thing separating this from a fresh
    // credit is the flag.
    const { container } = await render({
      [`POST ${CREDITS_PATH}`]: result({
        recorded: false,
        payment_ref: REF,
        amount_inr: "2500.00",
        balance_inr: "2500.00",
        entry_id: entry().id,
      }),
    });

    await fillTopUp(REF, "2500.00");
    submit();

    await screen.findByText("Already recorded — nothing was credited");
    expect(container.textContent).toContain("no second entry was written");
    expect(container.textContent).toContain("has not been credited twice");
    // NOT a failure: no refusal panel anywhere on the screen.
    expect(screen.queryByRole("alert")).toBeNull();
    // And NOT a fresh credit. This is the belief that causes the damage — the money is
    // already unrecoverable by the time anyone acts on it.
    expect(container.textContent).not.toContain("Recorded — ₹");
  });

  it("warns before the click when the reference is already on the ledger", async () => {
    // A preview from the entries already on screen, one-directional by design: a match
    // is a fact worth saying; an absence proves nothing, because this list is the newest
    // 50 and the server checks the whole ledger.
    const { container } = await render();

    await fillTopUp(REF, "2500.00");

    await waitFor(() => {
      expect(container.textContent).toContain("That reference is already on this ledger");
    });
    expect(container.textContent).toContain("Sending it again credits nothing");
    // Not blocked: submitting a repeat is harmless and is how the operator finds out.
    expect((screen.getByRole("button", { name: /^Credit / }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("cautions about an internal space without normalizing it away", async () => {
    // The one double-credit path double keying cannot catch: an operator who reads a
    // space off the statement types it both times. The server keys on the exact string,
    // so silently stripping it here would make the console's key differ from the
    // ledger's — the caution is raised and the value is sent verbatim.
    const { calls, container } = await render({ [`POST ${CREDITS_PATH}`]: result() });

    await fillTopUp("UTR 900042", "2500.00");
    await waitFor(() => {
      expect(container.textContent).toContain("This reference has a space inside it");
    });

    submit();
    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST")).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST");
    expect(JSON.parse(post?.body ?? "{}").payment_ref).toBe("UTR 900042");
  });

  it("keeps the button dead until the reference has been typed twice and matches", async () => {
    await render();

    const ref = (await screen.findByLabelText("Bank reference (UTR / RRN)")) as HTMLInputElement;
    fireEvent.change(ref, { target: { value: "UTR-900042" } });
    fireEvent.change(screen.getByLabelText("Amount received (₹)"), {
      target: { value: "2500.00" },
    });

    const button = () => screen.getByRole("button", { name: /^Credit / }) as HTMLButtonElement;
    expect(button().disabled).toBe(true);
    expect(screen.getByText(/Type the reference a second time/)).toBeDefined();

    // A near miss — the transposition this control exists to catch.
    fireEvent.change(screen.getByLabelText("Type the reference again"), {
      target: { value: "UTR-900024" },
    });
    expect(button().disabled).toBe(true);
    expect(screen.getByText(/These two do not match/)).toBeDefined();

    fireEvent.change(screen.getByLabelText("Type the reference again"), {
      target: { value: "UTR-900042" },
    });
    expect(button().disabled).toBe(false);
  });

  it("refuses a malformed amount before the click, without parsing it", async () => {
    await render();

    await fillTopUp("UTR-900042", "₹2,500.10");

    expect(screen.getByText(/no commas, no ₹ sign/)).toBeDefined();
    expect((screen.getByRole("button", { name: /^Credit /}) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("withholds the form entirely when the ledger could not be read", async () => {
    const { container } = await render({
      [CREDITS_READ]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this client's wallet.",
        retryable: true,
      }),
    });

    await screen.findByText("We could not read this wallet, so nothing can be credited to it here");
    expect(screen.queryByRole("button", { name: /^Credit / })).toBeNull();
    expect(screen.queryByLabelText("Bank reference (UTR / RRN)")).toBeNull();
    // The three sentences a failed read must never produce: a balance, an empty ledger,
    // or a wallet that reads healthy. Each is a REAL state with a different remedy.
    expect(container.textContent).not.toContain("₹0");
    expect(container.textContent).not.toContain("On the wallet now");
    expect(container.textContent).not.toContain("Nothing has ever been written to this ledger");
  });

  it("states an empty ledger as an empty ledger, but only after a successful read", async () => {
    const { container } = await render({
      [CREDITS_READ]: credits({ balance_inr: "0.00", is_low: true, entries: [] }),
    });

    await screen.findByText("Nothing has ever been written to this ledger");
    expect(container.textContent).toContain("₹0.00");
    // The server's own verdict, displayed and not recomputed from the balance.
    expect(container.textContent).toContain("Below the low-balance line of ₹200.00");
  });

  it("disables the write, with its reason, for a session that may not make it", async () => {
    await render({
      [ADMIN_ME_PATH]: { ...ME, permissions: ["org:read", "billing:read"] },
    });

    const button = (await screen.findByRole("button", {
      name: /^Credit /,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(
      (screen.getByLabelText("Bank reference (UTR / RRN)") as HTMLInputElement).disabled,
    ).toBe(true);
    // A RestrictionNote beside the dead control, not a 403 after the click — and one
    // sentence PER control, so it is never ambiguous which button is being explained.
    expect(screen.getByText(/record a payment on this client's wallet/)).toBeDefined();
    expect(screen.getByText(/correct an entry on this client's wallet/)).toBeDefined();
  });

  it("routes each mistake to the remedy that repairs it", async () => {
    const { container } = await render();

    await screen.findByText("If a credit was wrong");
    expect(container.textContent).toContain("There is no undo");
    // The duplicate case still belongs to the script: a duplicate is DETECTED, and its
    // correction is keyed on a fingerprint of the rows it cancels — not something an
    // operator can type into a form.
    expect(container.textContent).toContain("reconcile_credit_ledger");
    // …and the sentence this slice deleted. The console HAS a control for the wrong
    // client and the wrong amount now, so the card must not still send people away.
    expect(container.textContent).not.toContain("There is no control for this");
    expect(container.textContent).toContain("Correct a wrong entry");
  });

  it("scans clean once the form is filled and its notices are on screen", async () => {
    // The a11y sweep (tests/a11y.test.tsx) scans this screen at FIRST PAINT, where the
    // field errors, the duplicate-reference notice and the outcome panel do not exist.
    // They are markup with labels and colours of their own, so they are scanned here —
    // the device tests/dataRights.test.tsx uses for its certificate.
    const { container } = await render({
      [`POST ${CREDITS_PATH}`]: result({ recorded: false }),
      [`POST ${ADJUST_PATH}`]: correction({ balance_inr: "-500.00", stops_dialling: true }),
    });

    await fillTopUp(REF, "2500.00");
    submit();
    await screen.findByText("Already recorded — nothing was credited");
    // The correction panel's own notices too — the selected-entry box and the outcome,
    // including the one that only appears when a client has just been stopped dialling.
    await fillCorrection(ENTRY, "2500.00");
    fireEvent.click(correctButton());
    await screen.findByText(
      "Sri Traders cannot place outbound calls until this wallet is topped up",
    );

    await expectNoA11yViolations(container, "admin/tenants/[tenantId]/credits (filled)");
  });
});

/**
 * Correcting a wrong entry — the control that did not exist.
 *
 * `POST .../credits` refused a negative amount with "record a compensating adjustment
 * instead" and this screen said, truthfully, that there was no such thing. These pin the
 * five properties that make the replacement safe, worst first:
 *
 * 1. **A repeated correction must read as "already corrected", never as a second debit.**
 *    Both outcomes are 200 and differ only by `recorded`, and this direction is the
 *    expensive one: an operator who believes they have just taken ₹50,000 off a client
 *    twice goes looking for money that never moved.
 * 2. **The step-up header is sent for the dangerous DIRECTION and only that one**, which
 *    is the route's own rule. Sending it always would make the confirmation meaningless;
 *    sending it never would make every wrong-client correction a 403.
 * 3. **`stops_dialling` is rendered as itself.** A correction that silently stops a
 *    client's calling is the consequence an operator must not learn from the client.
 * 4. **The amount is double-keyed and the reason is required** — the two guards
 *    proportional to money leaving an account on our say-so.
 * 5. **A refusal is a refusal.** The server's problem+json is rendered and the draft
 *    survives it, so the operator can correct the amount rather than retype everything.
 */
describe("correcting a wrong entry", () => {
  it("appends a compensating entry, with the confirmation the direction demands", async () => {
    const { calls, container } = await render({ [`POST ${ADJUST_PATH}`]: correction() });

    await fillCorrection(ENTRY, "2500.00", "paid by Sri Traders, credited here by mistake");
    fireEvent.click(correctButton());

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === ADJUST_PATH)).toBe(
        true,
      );
    });
    const post = calls.find((call) => call.method === "POST" && call.path === ADJUST_PATH);
    const body = JSON.parse(post?.body ?? "{}");
    // A POSITIVE magnitude as a STRING. The sign is the route's to derive from the entry
    // — the one thing a form must never be trusted with (hard rule 7 for the string).
    expect(typeof body.amount_inr).toBe("string");
    expect(body.amount_inr).toBe("2500.00");
    expect(body.corrects_entry_id).toBe(ENTRY);
    expect(body.reason).toBe("paid by Sri Traders, credited here by mistake");
    // Taking credit AWAY is the dangerous direction, so the header goes on the wire —
    // bound to the ENTRY, so a confirmation captured here cannot be replayed elsewhere.
    expect(post?.headers["X-Confirm-Action"]).toBe(creditAdjustmentConfirmation(ENTRY));
    // The admin session with the tenant in the path, never an impersonating one (D-22).
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();

    await screen.findByText("Corrected — -₹2,500.00 taken back");
    expect(container.textContent).toContain("The entry it cancels is still there too");
  });

  it("sends NO confirmation when the correction puts credit back", async () => {
    // Reversing a call charge credits the client. That is not the dangerous direction,
    // and a header the route does not ask for is a confirmation of nothing.
    const charge = entry({
      id: "0192f0aa-5555-7000-8000-0000000000b9",
      delta_inr: "-80.00",
      reason: "usage",
      ref: "0192f0aa-0000-7000-8000-00000000000c",
      balance_after_inr: "2420.00",
      reversible_inr: "80.00",
    });
    const { calls, container } = await render({
      [CREDITS_READ]: credits({ balance_inr: "2420.00", entries: [charge, entry()] }),
      [`POST ${ADJUST_PATH}`]: correction({
        corrects_entry_id: charge.id,
        delta_inr: "80.00",
        balance_inr: "2500.00",
        is_low: false,
      }),
    });

    await fillCorrection(charge.id, "80.00", "the call never connected");
    expect(container.textContent).toContain("puts credit back on this wallet");
    fireEvent.click(screen.getByRole("button", { name: /^Put ₹80.00 back on/ }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === ADJUST_PATH)).toBe(
        true,
      );
    });
    const post = calls.find((call) => call.method === "POST" && call.path === ADJUST_PATH);
    expect(post?.headers["X-Confirm-Action"]).toBeUndefined();
    await screen.findByText("Corrected — ₹80.00 credited back");
  });

  it("reads a repeated correction as ALREADY CORRECTED, not as a second debit", async () => {
    const { container } = await render({
      [`POST ${ADJUST_PATH}`]: correction({ recorded: false }),
    });

    await fillCorrection(ENTRY, "2500.00");
    fireEvent.click(correctButton());

    await screen.findByText("Already corrected — nothing moved");
    expect(container.textContent).toContain("no second one was written");
    expect(container.textContent).toContain("has not been debited twice");
    // NOT a failure, and NOT a fresh debit — the belief that causes the damage.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.textContent).not.toContain("Corrected — -₹");
  });

  it("says out loud when the correction has stopped the client dialling", async () => {
    const { container } = await render({
      [`POST ${ADJUST_PATH}`]: correction({ balance_inr: "-12000.00", stops_dialling: true }),
    });

    await fillCorrection(ENTRY, "2500.00");
    fireEvent.click(correctButton());

    await screen.findByText(
      "Sri Traders cannot place outbound calls until this wallet is topped up",
    );
    // The gate's own reason, and the half that is NOT affected — an operator who reads
    // only this needs to know inbound still answers.
    expect(container.textContent).toContain("no_credits");
    expect(container.textContent).toContain("Inbound calls are unaffected");
  });

  it("keeps the button dead until the entry, both amounts and the reason are in", async () => {
    await render();

    // The consequences are stated before anything is chosen — above the control, not
    // revealed by filling it in.
    const upfront = await screen.findByText(/There is no undo, here either/);
    expect(upfront).toBeDefined();

    expect(correctButton().disabled).toBe(true);
    expect(screen.getByText(/Pick the entry that was wrong/)).toBeDefined();

    fireEvent.change(screen.getByLabelText("Entry to correct"), { target: { value: ENTRY } });
    expect(correctButton().disabled).toBe(true);
    expect(screen.getByText(/Enter how much of that entry to take back/)).toBeDefined();

    fireEvent.change(screen.getByLabelText("Amount to take back (₹)"), {
      target: { value: "2500.00" },
    });
    expect(correctButton().disabled).toBe(true);
    expect(screen.getByText(/Type the amount a second time/)).toBeDefined();

    // A near miss — the transposition double keying exists to catch.
    fireEvent.change(screen.getByLabelText("Type the amount again"), {
      target: { value: "2500.10" },
    });
    expect(correctButton().disabled).toBe(true);
    expect(screen.getByText(/These two do not match/)).toBeDefined();

    fireEvent.change(screen.getByLabelText("Type the amount again"), {
      target: { value: "2500.00" },
    });
    expect(correctButton().disabled).toBe(true);
    expect(screen.getByText(/Say why\. It is stored on the entry/)).toBeDefined();

    fireEvent.change(screen.getByLabelText("Why (required)"), {
      target: { value: "wrong client" },
    });
    expect(correctButton().disabled).toBe(false);
  });

  it("refuses a signed or malformed amount before the click, without parsing it", async () => {
    await render();

    await fillCorrection(ENTRY, "-2500.00");
    expect(screen.getByText(/Never a minus sign — the direction comes from the entry/)).toBeDefined();
    expect(correctButton().disabled).toBe(true);
  });

  it("offers only entries that still have something to take back", async () => {
    const spent = entry({
      id: "0192f0aa-5555-7000-8000-0000000000b7",
      ref: "UTR-ALREADY-FIXED",
      reversible_inr: "0.00",
    });
    const { container } = await render({
      [CREDITS_READ]: credits({ entries: [spent, entry()] }),
    });

    const select = (await screen.findByLabelText("Entry to correct")) as HTMLSelectElement;
    const values = Array.from(select.options).map((option) => option.value);
    // A fully corrected entry is a dead option, and offering one is the defect §52
    // named — the route would refuse it, after the click.
    expect(values).not.toContain(spent.id);
    expect(values).toContain(ENTRY);
    // …and the ledger says WHY it is missing, rather than leaving it unexplained.
    expect(container.textContent).toContain("fully corrected");
  });

  it("says so plainly when there is nothing left to correct", async () => {
    const { container } = await render({
      [CREDITS_READ]: credits({
        balance_inr: "0.00",
        is_low: true,
        entries: [entry({ reversible_inr: "0.00" })],
      }),
    });

    await screen.findByText(/Every entry on this wallet has already been taken back in full/);
    expect(screen.queryByLabelText("Entry to correct")).toBeNull();
    expect(container.textContent).not.toContain("Correct this entry");
  });

  it("renders the server's refusal and keeps the draft", async () => {
    // The ceiling is the SERVER's: this console shows `reversible_inr` but never
    // enforces it, so the refusal has to be legible and the values have to survive it.
    const { container } = await render({
      [`POST ${ADJUST_PATH}`]: problem(422, {
        type: "https://calevate.tech/problems/adjustment_exceeds_entry",
        title: "Request rejected by a business rule",
        detail: "That entry has ₹400.00 left to take back, and this asks for ₹600.01.",
        kind: "business_rule",
        remediation: "Correct at most what is left of the entry.",
      }),
    });

    await fillCorrection(ENTRY, "600.01");
    fireEvent.click(correctButton());

    await screen.findByText(/That entry has ₹400.00 left to take back/);
    expect(container.textContent).toContain("Correct at most what is left of the entry");
    // The draft survives, so the operator edits the amount instead of retyping the lot.
    expect((screen.getByLabelText("Why (required)") as HTMLInputElement).value).toBe(
      "wrong client",
    );
    expect((screen.getByLabelText("Amount to take back (₹)") as HTMLInputElement).value).toBe(
      "600.01",
    );
  });

  it("disables the correction, with its reason, for a session that may not make it", async () => {
    await render({ [ADMIN_ME_PATH]: { ...ME, permissions: ["org:read", "billing:read"] } });

    await screen.findByLabelText("Entry to correct");
    expect(correctButton().disabled).toBe(true);
    expect((screen.getByLabelText("Entry to correct") as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByLabelText("Why (required)") as HTMLInputElement).disabled).toBe(true);
  });

  it("withholds the correction with the form when the ledger could not be read", async () => {
    // A correction names a specific ledger row, so a ledger nobody can read is a row
    // nobody can name — the same §52 argument as the top-up form, one step stronger.
    await render({
      [CREDITS_READ]: problem(503, { title: "Upstream unavailable", retryable: true }),
    });

    await screen.findByText("We could not read this wallet, so nothing can be credited to it here");
    expect(screen.queryByLabelText("Entry to correct")).toBeNull();
  });
});
