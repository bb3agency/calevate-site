import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import GlobalDncPage from "@/app/admin/ops/dnc/page";
import {
  OPS_DNC_GLOBAL_PATH,
  RELEASE_GLOBALLY_CONFIRMATION,
  SUPPRESS_GLOBALLY_CONFIRMATION,
  releaseGloballyConfirmation,
  type GlobalDncEntry,
} from "@/lib/api/opsDnc";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderAdminPage, stillLoading, type Routes } from "./harness";

/**
 * The platform-wide do-not-call screen — the console's only cross-tenant COMPLIANCE
 * write, and the one whose destructive direction re-permits calling somebody who asked
 * not to be called.
 *
 * Ranked by what each failure costs, worst first:
 *
 * 1. **A list we could not read must never render as "no number is suppressed".** That
 *    sentence is a compliance claim about every tenant at once, and an operator answering
 *    a regulator is exactly who would act on it. §52's rule, on the payload where being
 *    wrong is a TRAI complaint rather than a wrong number on a dashboard.
 * 2. **Releasing is not one click, and the per-row discipline reaches the wire.** The
 *    typed word is collected per ROW and names that row's number, so a confirmation typed
 *    for one suppression cannot lift the one below it — and the header carries that row's
 *    id (`release_number_platform_wide:<entryId>`), so the API enforces the same binding
 *    the screen collects. A console that collected a word and sent no header, or sent a
 *    header that would have released any row, would be theatre.
 * 3. **`removable: false` must not disable the ops control.** It is the CLIENT surface's
 *    verdict (`is_removable()`), false on every row this endpoint returns; reading it as
 *    "nobody may" would leave this screen unable to do the one thing it exists for.
 * 4. **A session without `ops:manage` is refused with its reason**, before a request has
 *    failed, rather than being handed a 403 that reads like an outage.
 *
 * The ADD answers in three counts and never echoes the pasted list — an operator who
 * pasted the wrong column needs a figure that disagrees with theirs, not their own text
 * handed back. The LIST answers in full numbers (D-436): releasing a platform-wide
 * suppression means reading it back to the regulator or TSP who asked for it, and the
 * per-row confirmation asks the operator to match it.
 */

const SUPERADMIN: AdminMe = {
  user_id: "admin-1",
  realm: "admin",
  role: "superadmin",
  permissions: ["ops:manage", "admin:tenants"],
};

/** An admin who may run the console but not move platform-wide state. */
const OPERATOR: AdminMe = {
  user_id: "admin-2",
  realm: "admin",
  role: "operator",
  permissions: ["admin:tenants", "org:read"],
};

const LIST_PATH = `${OPS_DNC_GLOBAL_PATH}?limit=500`;

/** Typed into the Suppress box. Distinct from every number in the list fixtures. */
const SUBMITTED_NUMBER = "9812349999";

function entry(over: Partial<GlobalDncEntry> = {}): GlobalDncEntry {
  return {
    id: "0192f0aa-7777-7000-8000-000000000001",
    phone_e164: "+919876543210",
    scope: "global",
    source: "regulator",
    added_at: "2026-08-12T09:00:00Z",
    // Always false on this endpoint — see property 3 above.
    removable: false,
    ...over,
  };
}

function routes(over: Routes = {}): Routes {
  return { [ADMIN_ME_PATH]: SUPERADMIN, [LIST_PATH]: [entry()], ...over };
}

describe("the platform-wide do-not-call list", () => {
  it("says what the suppression will do BEFORE it is clicked, and sends the step-up header", async () => {
    const { calls, container } = renderAdminPage(<GlobalDncPage />, routes());

    // Found by the stem, because the label counts what is in the box and there is
    // nothing in it yet — the count itself is asserted after the paste, below.
    const button = await screen.findByRole("button", { name: /Suppress/ });
    expect(container.textContent).toContain(
      "Every client stops dialling these numbers, from the next dispatch decision",
    );
    // The half that is NOT affected, said in the same breath, and the distinction the
    // route's own docstring says operators get wrong.
    expect(container.textContent).toContain("Inbound calls are unaffected");
    expect(container.textContent).toContain("NOT the national customer preference register");

    fireEvent.change(screen.getByPlaceholderText(/9876543210/), {
      target: { value: "9876543210" },
    });
    fireEvent.change(screen.getByPlaceholderText(/TRAI escalation/), {
      target: { value: "  TRAI escalation TR-4471  " },
    });
    fireEvent.change(screen.getByPlaceholderText("SUPPRESS"), {
      target: { value: "SUPPRESS" },
    });
    // One pasted number, one number named on the button: an operator confirming a bulk
    // suppression should never have to guess how many rows the box parsed to.
    expect(button.textContent).toContain("Suppress 1 number platform-wide");
    // The control unlocks only once `GET /v1/admin/me` has said this session may use it —
    // fail-closed while the answer is missing, which is also why every test below waits
    // for the ENABLED state before drawing a conclusion from a disabled one.
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === OPS_DNC_GLOBAL_PATH)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === OPS_DNC_GLOBAL_PATH);
    expect(post?.headers["X-Confirm-Action"]).toBe(SUPPRESS_GLOBALLY_CONFIRMATION);
    // Trimmed, because the server strips the reason and refuses anything under three
    // characters — a console that sent the padding would fail on the operator's behalf.
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      numbers: ["9876543210"],
      source: "regulator",
      reason: "TRAI escalation TR-4471",
    });
  });

  it("will not submit a whitespace reason the server would strip and reject", async () => {
    renderAdminPage(<GlobalDncPage />, routes());

    const button = await screen.findByRole("button", { name: /Suppress/ });
    // Deliberately NOT the number in the list fixture: since D-436 the list renders its
    // rows in full, so an assertion using the same digits could not tell "the form was
    // cleared and the server echoed nothing" from "the list is on screen".
    fireEvent.change(screen.getByPlaceholderText(/9876543210/), {
      target: { value: SUBMITTED_NUMBER },
    });
    fireEvent.change(screen.getByPlaceholderText(/TRAI escalation/), {
      target: { value: "registrar instruction" },
    });
    fireEvent.change(screen.getByPlaceholderText("SUPPRESS"), {
      target: { value: "SUPPRESS" },
    });
    // The baseline first: a dead button proves nothing about the reason rule if it was
    // dead for want of a permission answer, which is what it is until `/v1/admin/me`
    // lands. This assertion is what stops the next one passing vacuously.
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));

    fireEvent.change(screen.getByPlaceholderText(/TRAI escalation/), {
      target: { value: "   " },
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("answers a completed suppression with counts and never echoes what was typed", async () => {
    const { container } = renderAdminPage(
      <GlobalDncPage />,
      routes({
        [`POST ${OPS_DNC_GLOBAL_PATH}`]: { added: 2, already_suppressed: 1, malformed: 0 },
      }),
    );

    const button = await screen.findByRole("button", { name: /Suppress/ });
    fireEvent.change(screen.getByPlaceholderText(/9876543210/), {
      target: { value: "9876543210" },
    });
    fireEvent.change(screen.getByPlaceholderText(/TRAI escalation/), {
      target: { value: "registrar instruction" },
    });
    fireEvent.change(screen.getByPlaceholderText("SUPPRESS"), {
      target: { value: "SUPPRESS" },
    });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => {
      expect(container.textContent).toContain("Already suppressed");
    });
    expect(container.textContent).toContain(
      "Totals, not which number went where",
    );
    // The number typed in is gone from the form, and none came back from the server to
    // render — `GlobalSuppressOut` is three integers.
    expect(container.textContent).not.toContain(SUBMITTED_NUMBER);
  });

  it("offers Release on a row the CLIENT surface calls unremovable", async () => {
    renderAdminPage(<GlobalDncPage />, routes());
    // `removable: false` is `is_removable()`'s answer about clients. If this control ever
    // hangs off it, ops loses the only route by which a global suppression can be lifted.
    expect(
      await screen.findByRole("button", {
        name: "Release the platform-wide suppression on +919876543210",
      }),
    ).toBeTruthy();
  });

  it("takes a typed confirmation naming the row, and sends the RELEASE header", async () => {
    const { calls, container } = renderAdminPage(
      <GlobalDncPage />,
      routes({ [`DELETE ${OPS_DNC_GLOBAL_PATH}/${entry().id}`]: null }),
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Release the platform-wide suppression on +919876543210",
      }),
    );

    // The blast radius, in the direction that matters: this re-permits calling somebody.
    expect(container.textContent).toContain(
      "Releasing +919876543210 lets every client dial it again",
    );
    // …and WHY it was suppressed, quoted back, so the operator lifting it knows whose
    // instruction they are overriding.
    expect(container.textContent).toContain("a regulator, TSP or registrar named it");

    const confirm = await screen.findByRole("button", { name: /Release \+9198/ });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Type RELEASE to confirm lifting/), {
      target: { value: "RELEASE" },
    });
    fireEvent.click(confirm);

    await waitFor(() => {
      expect(calls.some((c) => c.method === "DELETE")).toBe(true);
    });
    const sent = calls.find((c) => c.method === "DELETE");
    expect(sent?.path).toBe(`${OPS_DNC_GLOBAL_PATH}/${entry().id}`);
    // The API binds the two directions to DIFFERENT strings, and binds the release to the
    // ROW: a header captured for a suppression cannot release one, and a header captured
    // for one entry cannot release another. A console that sent the bare stem would be
    // refused, and one that sent none would make the step-up decorative.
    expect(sent?.headers["X-Confirm-Action"]).toBe(releaseGloballyConfirmation(entry().id));
    expect(sent?.headers["X-Confirm-Action"]).not.toBe(RELEASE_GLOBALLY_CONFIRMATION);
    expect(sent?.headers["X-Confirm-Action"]).toContain(entry().id);
    expect(RELEASE_GLOBALLY_CONFIRMATION).not.toBe(SUPPRESS_GLOBALLY_CONFIRMATION);
  });

  it("does not carry a confirmation from one row to the next", async () => {
    const { calls } = renderAdminPage(
      <GlobalDncPage />,
      routes({
        [LIST_PATH]: [
          entry(),
          entry({ id: "0192f0aa-7777-7000-8000-000000000002", phone_e164: "+919812347788" }),
        ],
      }),
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Release the platform-wide suppression on +919876543210",
      }),
    );
    fireEvent.change(screen.getByLabelText(/Type RELEASE to confirm lifting/), {
      target: { value: "RELEASE" },
    });
    // The SECOND row's confirmation opens empty and its button is dead: the typed word
    // belongs to the number it was typed against, which is the whole reason it is
    // collected per row rather than once for the list.
    fireEvent.click(
      screen.getByRole("button", {
        name: "Release the platform-wide suppression on +919812347788",
      }),
    );
    expect(
      (screen.getByRole("button", { name: /Release \+919812347788/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });

  it("renders a skeleton while the list is in flight, and no empty state", async () => {
    const { container } = renderAdminPage(
      <GlobalDncPage />,
      routes({ [LIST_PATH]: stillLoading() }),
    );

    // The PRESENCE of the skeleton, not the absence of rows: an empty card passes an
    // absence assertion just as happily, which is the trap this suite exists to avoid.
    await waitFor(() => {
      expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    });
    expect(container.textContent).not.toContain("No number is suppressed platform-wide");
  });

  it("refuses rather than reporting an empty platform-wide list when the read fails", async () => {
    const { container } = renderAdminPage(
      <GlobalDncPage />,
      routes({ [LIST_PATH]: problem(503, { title: "Service unavailable" }) }),
    );

    await waitFor(() => {
      expect(container.textContent).toContain(
        "This screen will not tell you what is suppressed",
      );
    });
    // The sentence that must never appear over a failed read — it is a statement about
    // what this platform refuses to dial, made on no evidence.
    expect(container.textContent).not.toContain("No number is suppressed platform-wide");
    // …and no count, because there is nothing to count.
    expect(container.textContent).not.toContain("entries");
  });

  it("says the list is empty only when the server said so", async () => {
    const { container } = renderAdminPage(<GlobalDncPage />, routes({ [LIST_PATH]: [] }));

    await waitFor(() => {
      expect(container.textContent).toContain("No number is suppressed platform-wide");
    });
    // The empty state must not read as "nothing is on any client's list either".
    expect(container.textContent).toContain("Clients' own do-not-call lists are separate");
  });

  it("disables both directions for an admin without ops:manage, with the reason", async () => {
    const { calls, container } = renderAdminPage(
      <GlobalDncPage />,
      routes({ [ADMIN_ME_PATH]: OPERATOR }),
    );

    await waitFor(() => {
      expect(container.textContent).toContain("does not have the ops:manage permission");
    });
    expect(
      (
        (await screen.findByRole("button", { name: /Suppress/ })) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    // The destructive control is not merely disabled, it is not offered: a Release button
    // that 403s teaches an operator that our compliance rules are a bug.
    expect(screen.queryByRole("button", { name: /Release the platform-wide/ })).toBeNull();
    expect(calls.some((c) => c.method !== "GET")).toBe(false);
  });

  it("explains a refused confirmation as a version skew, not a retry", async () => {
    const { container } = renderAdminPage(
      <GlobalDncPage />,
      routes({
        [`POST ${OPS_DNC_GLOBAL_PATH}`]: problem(403, {
          kind: "permission",
          // The machine code is the last segment of `type` (`ApiProblem`), which is the
          // shape `core/stepup.py` actually sends.
          type: "urn:calevate:error/step_up_required",
          title: "Confirmation required",
          detail: "This action needs an explicit confirmation.",
          remediation:
            "Repeat the request with the header X-Confirm-Action: " +
            SUPPRESS_GLOBALLY_CONFIRMATION,
        }),
      }),
    );

    const button = await screen.findByRole("button", { name: /Suppress/ });
    fireEvent.change(screen.getByPlaceholderText(/9876543210/), {
      target: { value: "9876543210" },
    });
    fireEvent.change(screen.getByPlaceholderText(/TRAI escalation/), {
      target: { value: "registrar instruction" },
    });
    fireEvent.change(screen.getByPlaceholderText("SUPPRESS"), {
      target: { value: "SUPPRESS" },
    });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => {
      expect(container.textContent).toContain(
        "Refused: this console's confirmation is not the one the API expects",
      );
    });
    // The console DID send the header, so "you forgot to confirm" is impossible here and
    // clicking again cannot help. Both facts are on screen.
    expect(container.textContent).toContain("Nothing was changed");
    expect(container.textContent).toContain("Reload this page first");
  });

  it("has no accessibility violation with a release confirmation open", async () => {
    // The confirmation block only exists after a click, so the populated-screen sweep in
    // a11y.test.tsx cannot reach it — the same gap the data-rights certificate has, closed
    // the same way rather than left to the sweep it is invisible to.
    const { container } = renderAdminPage(<GlobalDncPage />, routes());
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Release the platform-wide suppression on +919876543210",
      }),
    );
    await expectNoA11yViolations(container, "admin/ops/dnc (release confirmation)");
  });
});
