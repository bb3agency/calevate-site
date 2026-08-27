import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgreementsPage from "@/app/c/[slug]/agreements/page";
import {
  ACCEPTANCES_PATH,
  READINESS_PATH,
  type LegalDocumentState,
  type LegalReadiness,
} from "@/lib/api/agreements";

import { NeverAnswers, problem, renderClientPage } from "./harness";

/**
 * Agreements & readiness — the screen that clears the one refusal a client can clear.
 *
 * Three failures are worth a test here and none of them is visible to a type checker:
 *
 * 1. **A read that did not land must produce a refusal, not a verdict.** Every branch of
 *    this screen is reassuring to somebody. "Nothing is holding up your outgoing calls"
 *    printed over a 503 tells a blocked client to stop looking, on the one screen they
 *    opened to find out why their calls stopped — the §52 defect, in the place it would
 *    cost the most.
 * 2. **The screen must compute NO verdict of its own.** `may_operate`, the state word on
 *    every document and the count of what is outstanding are the server's, decided by the
 *    same predicates the dial gate uses. A test that only checked the happy path would
 *    pass just as well against a browser that re-derived them and disagreed with the gate.
 * 3. **Nobody signs for the client but the client.** A reader the server says may not
 *    accept must be shown the reason, and no control — a disabled button here is a 403
 *    with a contract ledger behind it.
 */

function doc(over: Partial<LegalDocumentState> = {}): LegalDocumentState {
  return {
    slug: "terms",
    title: "Terms of Service",
    href: "/legal/terms",
    blocking: true,
    version: "1+pre-review",
    provisional: true,
    effective_date: null,
    state: "never_accepted",
    headline: "Not accepted yet.",
    accepted_version: null,
    accepted_at: null,
    accepted_by_name: null,
    ...over,
  };
}

const BLOCKING: LegalDocumentState[] = [
  doc({ slug: "privacy", title: "Privacy Policy", href: "/legal/privacy" }),
  doc(),
  doc({ slug: "acceptable-use", title: "Acceptable Use", href: "/legal/acceptable-use" }),
  doc({ slug: "dpa", title: "Data Processing Addendum", href: "/legal/dpa" }),
];

const READABLE = doc({
  slug: "subprocessors",
  title: "Sub-processors",
  href: "/legal/subprocessors",
  blocking: false,
  state: "not_required",
  headline: "Published for you to read. There is nothing to accept.",
});

const STATEMENT = "I accept the Terms of Service, the Privacy Policy, the Data Processing Addendum and the Acceptable Use Policy on behalf of this business.";

function readiness(over: Partial<LegalReadiness> = {}): LegalReadiness {
  return {
    may_operate: false,
    verdict:
      "Your agreements have not been accepted, so this account cannot make outgoing calls or publish an agent yet.",
    outstanding_documents: 4,
    pending_legal_review: true,
    provisional_notice: "These documents are drafts.",
    acceptance_statement: STATEMENT,
    acceptance_statement_version: "1+pre-review",
    can_accept: true,
    can_accept_reason: null,
    documents: [...BLOCKING, READABLE],
    blockers: [
      {
        rule: "agreements_not_accepted",
        title: "Agreements not accepted",
        reason: "This account has not accepted its agreements yet.",
        actor: "client",
        next_step: "The account owner reads each agreement and accepts it on this screen.",
      },
    ],
    ...over,
  };
}

/** Everything accepted, nothing else in the way. */
const READY = readiness({
  may_operate: true,
  verdict: "Nothing is holding up your outgoing calls.",
  outstanding_documents: 0,
  documents: [
    ...BLOCKING.map((d) => ({
      ...d,
      state: "accepted" as const,
      headline: "Accepted.",
      accepted_version: "1+pre-review",
      accepted_at: "2026-08-20T06:00:00Z",
      accepted_by_name: "Padmavathi Rao",
    })),
    READABLE,
  ],
  blockers: [],
});

describe("the screen renders the server's verdict and never its own", () => {
  it("prints the outstanding verdict, every document's state, and whose move each blocker is", async () => {
    await renderClientPage(<AgreementsPage />, { [READINESS_PATH]: readiness() });

    await screen.findByText("Outgoing calls are blocked.");
    // The reassurance that has to survive every refusal on this screen: the receptionist
    // is still answering. `check_dispatch` is outbound-only, by design (D-38).
    expect(screen.getAllByText(/Calls coming IN are unaffected/i).length).toBeGreaterThan(0);

    // The server's own sentence, not a composed one.
    expect(screen.getByText(readiness().verdict)).toBeTruthy();
    expect(screen.getAllByText("Not accepted")).toHaveLength(4);
    expect(screen.getByText("Reading only")).toBeTruthy();

    // The blocker arrives with its actor already decided; the screen labels, never infers.
    expect(screen.getByText("Agreements not accepted")).toBeTruthy();
    expect(screen.getByText("Your move")).toBeTruthy();
  });

  it("shows who accepted what, and offers nothing to click once nothing is outstanding", async () => {
    await renderClientPage(<AgreementsPage />, { [READINESS_PATH]: READY });

    await screen.findByText("This account is ready to make calls.");
    expect(screen.getAllByText("Accepted")).toHaveLength(4);
    expect(screen.getAllByText(/Padmavathi Rao/)).toHaveLength(4);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText(/Nothing else at the account level/i)).toBeTruthy();
  });

  it("says an undated document is undated rather than hiding the row", async () => {
    // `{{EFFECTIVE_DATE}}` is an unfilled placeholder in the bundle, so every document
    // carries no effective date. A reader who sees no row cannot tell that from a screen
    // that forgot to print one.
    await renderClientPage(<AgreementsPage />, { [READINESS_PATH]: readiness() });
    await screen.findByText("Outgoing calls are blocked.");
    expect(screen.getAllByText("not yet dated").length).toBeGreaterThan(0);
  });
});

describe("accepting", () => {
  it("posts one acceptance per outstanding document, echoing the server's own version and wording", async () => {
    // The readiness route answers what the SERVER would answer at that moment: blocked
    // until the acceptances land, ready afterwards. A static answer would be a route that
    // contradicts the POST it just served — and it would hide the `invalidateQueries`
    // re-read `useAcceptAgreement` fires, which is the thing that would overwrite a
    // freshly-seeded cache with a stale view if the two ever disagreed.
    let accepted = 0;
    const { calls } = await renderClientPage(<AgreementsPage />, {
      [READINESS_PATH]: () => (accepted >= 4 ? READY : readiness()),
      [ACCEPTANCES_PATH]: () => {
        accepted += 1;
        return accepted >= 4 ? READY : readiness({ outstanding_documents: 4 - accepted });
      },
    });

    await screen.findByText("Outgoing calls are blocked.");
    const button = screen.getByRole("button", { name: /Accept 4 agreements/i });
    // Nothing may be recorded before the person has ticked the statement they are agreeing
    // to: the wording IS half the evidence the ledger row stores.
    expect(button.hasAttribute("disabled")).toBe(true);

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Accept 4 agreements/i }));

    const posted = () => calls.filter((call) => call.path === ACCEPTANCES_PATH);
    await waitFor(() => expect(posted()).toHaveLength(4));
    expect(posted().map((call) => JSON.parse(call.body ?? "{}").slug)).toEqual([
      "privacy",
      "terms",
      "acceptable-use",
      "dpa",
    ]);
    for (const call of posted()) {
      const body = JSON.parse(call.body ?? "{}");
      // Both fields are the SERVER's strings, echoed back. A console that minted either
      // would be recording an agreement to text nobody was shown.
      expect(body.version).toBe("1+pre-review");
      expect(body.statement_version).toBe("1+pre-review");
    }

    // The POST answers with the WHOLE screen, so the verdict flips without a re-read.
    await screen.findByText("This account is ready to make calls.");
  });

  it("renders the refusal when a version moved under an open tab", async () => {
    await renderClientPage(<AgreementsPage />, {
      [READINESS_PATH]: readiness(),
      [ACCEPTANCES_PATH]: problem(409, {
        type: "https://calevate.tech/problems/legal_version_not_current",
        title: "The version of this document on your screen is out of date.",
        remediation: "Reload the page and read it again.",
      }),
    });

    await screen.findByText("Outgoing calls are blocked.");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Accept 4 agreements/i }));

    await screen.findByText("The version of this document on your screen is out of date.");
    // Still blocked, and the screen says so: a refused write must not read as a success.
    expect(screen.getByText("Outgoing calls are blocked.")).toBeTruthy();
  });
});

describe("who may sign", () => {
  it("gives a reader who cannot accept the server's reason and no control at all", async () => {
    const reason =
      "Only the account owner can accept these agreements. You can read every document here.";
    await renderClientPage(<AgreementsPage />, {
      [READINESS_PATH]: readiness({ can_accept: false, can_accept_reason: reason }),
    });

    await screen.findByText("Outgoing calls are blocked.");
    expect(screen.getByText(reason)).toBeTruthy();
    // Absent, not disabled. A disabled control with no explanation is the shape D-22
    // exists to stop, and this one has a contract ledger behind it.
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Accept/i })).toBeNull();
  });
});

describe("when the read does not land", () => {
  it("refuses, and never prints a verdict", async () => {
    // The worst sentence this screen can print. "Nothing is holding up your outgoing
    // calls" over a request that failed is a compliance claim made on no evidence, and
    // the client acts on it by going back to the campaign they cannot launch.
    await renderClientPage(<AgreementsPage />, {
      [READINESS_PATH]: problem(503, {
        title: "We could not load your agreements.",
      }),
    });

    await screen.findByRole("alert");
    expect(screen.queryByText(/Nothing is holding up/i)).toBeNull();
    expect(screen.queryByText("This account is ready to make calls.")).toBeNull();
    expect(screen.queryByText("Outgoing calls are blocked.")).toBeNull();
  });

  it("shows a skeleton while the read is in flight, not an empty screen", async () => {
    const { container } = await renderClientPage(<AgreementsPage />, {
      [READINESS_PATH]: new NeverAnswers(),
    });

    expect(container.querySelector(".animate-pulse")).toBeTruthy();
    expect(screen.queryByText(/agreements that bind/i)).toBeNull();
  });
});
