import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import AddOperatorsPage from "@/app/admin/operators/page";
import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import TeamPage from "@/app/c/[slug]/settings/team/page";
import { fieldProblem } from "@/components/formValidation";
import type { Me } from "@/lib/api/client";

import { renderAdminPage, renderClientPage } from "./harness";
import { codeOnly } from "./sourceScan";

/**
 * The forms answer in OUR words now, and the browser answers in none.
 *
 * Every client form carried `required` / `minLength` / `type="email"` with no
 * `noValidate`, so an empty submit was refused by Chrome — in Chrome's UI language,
 * which for a Telugu-first product is the whole defect, and in Chrome's placement, which
 * ignored the error surface the rest of the screen uses.
 *
 * These tests drive the REAL forms rather than the hook: what matters is that a
 * conversion did not quietly delete the rule it replaced, and that is only visible from
 * the outside. Each one submits something invalid, asserts our sentence, asserts that
 * nothing was sent, then corrects it and asserts that the request goes.
 *
 * The accessibility half is asserted for the same reason: the bubble this replaces DID
 * announce itself and DID move focus, so a plain red paragraph would be a regression
 * dressed as an improvement.
 */

const ME: Me = {
  impersonating: false,
  permissions: ["org:read", "org:manage", "leads:read"],
  realm: "client",
  role: "owner",
  user_id: "0192f0aa-1111-7000-8000-000000000001",
  organization: null,
};

async function renderTeam() {
  return await renderClientPage(<TeamPage />, {
    "/v1/me": ME,
    "/v1/members": [{ id: ME.user_id as string, name: "Anita", role: "owner" }],
    "/v1/invitations": [],
    "POST /v1/invitations": {
      id: "0192f0aa-3333-7000-8000-000000000003",
      email: "priya@clinic.example",
      role: "staff",
      invited_at: "2026-08-01T09:00:00Z",
      expires_at: "2026-08-04T09:00:00Z",
      url: "https://app.calevate.tech/invite/abc",
    },
  });
}

describe("an address that is not one", () => {
  it("says so in our words, sends nothing, and takes the invitation once it is fixed", async () => {
    const page = await renderTeam();
    await screen.findByText("Anita");

    const field = screen.getByLabelText("Email address to invite") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "priya" } });
    fireEvent.click(screen.getByRole("button", { name: /Create invite link/ }));

    const message = await screen.findByText("Enter an email address, like name@example.com.");
    expect(page.calls.some((c) => c.method === "POST")).toBe(false);

    // The message is the field's DESCRIPTION, the field says it is invalid, and focus is
    // on the field rather than left where the button was.
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(field.getAttribute("aria-describedby")).toBe(message.id);
    expect(message.getAttribute("role")).toBe("alert");
    expect(document.activeElement).toBe(field);

    // Correcting it clears the message without a second submit — the person is told they
    // are out of the hole at the moment they climb out of it.
    fireEvent.change(field, { target: { value: "priya@clinic.example" } });
    fireEvent.input(field, { target: { value: "priya@clinic.example" } });
    await waitFor(() =>
      expect(screen.queryByText("Enter an email address, like name@example.com.")).toBeNull(),
    );

    fireEvent.click(screen.getByRole("button", { name: /Create invite link/ }));
    await waitFor(() =>
      expect(page.calls.some((c) => c.method === "POST" && c.path === "/v1/invitations")).toBe(
        true,
      ),
    );
  });

  it("never lets the browser refuse a form itself", async () => {
    await renderTeam();
    await screen.findByText("Anita");
    for (const form of Array.from(document.querySelectorAll("form"))) {
      expect(form.hasAttribute("novalidate")).toBe(true);
    }
  });
});

/**
 * THE ADMIN REALM, driven the same way — because it was the realm this rule missed.
 *
 * "Add an admin" is the right screen to prove it on: it carries the two rule shapes the
 * admin console uses everywhere (an address and a minimum-length reason), and its button
 * used to go dead on BOTH of them at once, so an operator who left the reason blank got a
 * dead button beside a filled-in form and no sentence anywhere on the screen. That is the
 * failure this conversion is for, and it is not the browser-bubble one — it is the same
 * defect wearing no words at all.
 */
describe("an admin form with two answers missing", () => {
  const SUPERADMIN: AdminMe = {
    user_id: "admin-1",
    realm: "admin",
    role: "superadmin",
    permissions: ["ops:manage", "admin:operators"],
  };

  function renderOperators() {
    return renderAdminPage(<AddOperatorsPage />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      "/v1/admin/operators": [],
    });
  }

  it("names both in our words, sends nothing, and focuses the first", async () => {
    const page = renderOperators();
    const email = (await screen.findByLabelText(
      "Email address of the admin to add",
    )) as HTMLInputElement;
    const reason = screen.getByLabelText("Why you are adding this admin") as HTMLInputElement;

    // SUBMITTED, not clicked. The typed-phrase gate still deadens the button — it is a
    // gate on the act rather than an answer on a control, so it stays there — and Enter
    // in a text input submits the form past a disabled button anyway. That keyboard path
    // is exactly what this validation has to catch, so it is what is driven.
    const form = email.closest("form") as HTMLFormElement;
    fireEvent.submit(form);

    const emailMessage = await screen.findByText("Enter the address this admin signs in with.");
    await screen.findByText("Say why this admin is being added.");
    expect(page.calls.some((c) => c.method === "POST")).toBe(false);

    expect(email.getAttribute("aria-invalid")).toBe("true");
    expect(email.getAttribute("aria-describedby")).toBe(emailMessage.id);
    expect(emailMessage.getAttribute("role")).toBe("alert");
    // DOM order, not registration order: the address is above the reason on the screen.
    expect(document.activeElement).toBe(email);

    // And the address rule is the SHAPE rule, not merely emptiness.
    fireEvent.change(email, { target: { value: "asha" } });
    fireEvent.input(email, { target: { value: "asha" } });
    await screen.findByText("Enter an email address, like name@example.com.");

    fireEvent.change(email, { target: { value: "asha@calevate.tech" } });
    fireEvent.input(email, { target: { value: "asha@calevate.tech" } });
    fireEvent.change(reason, { target: { value: "joining ops" } });
    fireEvent.input(reason, { target: { value: "joining ops" } });
    fireEvent.submit(form);
    await waitFor(() =>
      expect(
        page.calls.some((c) => c.method === "POST" && c.path === "/v1/admin/operators"),
      ).toBe(true),
    );
  });
});

/**
 * THE INVARIANT, asserted over the SOURCE rather than over one screen.
 *
 * A behavioural test can only prove the forms it renders. The rule is about every form in
 * EITHER realm, including the one added next week: the browser never writes a refusal on a
 * Calevate screen. It is a tripwire on the obvious spelling — a `<form>` opening tag
 * without `noValidate` — which is the spelling a well-meaning change actually takes.
 */
describe("no form in either realm leaves its refusals to the browser", () => {
  const SRC = join(process.cwd(), "src");

  function tsxUnder(dir: string): string[] {
    const out: string[] = [];
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) out.push(...tsxUnder(path));
      else if (entry.name.endsWith(".tsx")) out.push(path);
    }
    return out;
  }

  /** Every `<form` opening tag in a file, as text, with the line it starts on. */
  function formTags(source: string): { line: number; tag: string }[] {
    const tags: { line: number; tag: string }[] = [];
    const opener = /<form\b/g;
    let match: RegExpExecArray | null;
    while ((match = opener.exec(source)) !== null) {
      // The tag ends at the first `>` OUTSIDE a JSX expression: `onSubmit={(e) => …}`
      // holds arrows and braces, and the first `>` in the file is usually inside one.
      let depth = 0;
      let end = source.length;
      for (let i = match.index; i < source.length; i += 1) {
        const ch = source[i];
        if (ch === "{") depth += 1;
        else if (ch === "}") depth -= 1;
        else if (ch === ">" && depth === 0) {
          end = i;
          break;
        }
      }
      tags.push({
        line: source.slice(0, match.index).split("\n").length,
        tag: source.slice(match.index, end + 1),
      });
    }
    return tags;
  }

  it("carries noValidate on every form either realm can reach", () => {
    // `app/admin` is here for the same reason `app/c` is, and it was added second: the
    // ADMIN realm kept all thirty-three of its forms on browser validation for a round
    // after the client realm was converted, so this sweep was green while a third of the
    // product's forms still answered in Chrome's words. A sweep scoped to one realm reads
    // exactly like a clean tree.
    const files = [
      ...tsxUnder(join(SRC, "app", "c")),
      ...tsxUnder(join(SRC, "app", "admin")),
      ...tsxUnder(join(SRC, "app", "signup")),
      ...tsxUnder(join(SRC, "components")),
    ];
    // The premise: a scan that stops matching is indistinguishable from a clean tree.
    expect(files.length).toBeGreaterThan(40);

    const offenders: string[] = [];
    let seen = 0;
    for (const file of files) {
      // `codeOnly`, NOT the raw source: a comment that NAMES a form is not a form, and
      // this guard flagged `TopUp.tsx` for the line "Not a `<form>`: there is nothing to
      // submit" — the comment written to explain that the element deliberately is not
      // one. Blanked in place, so the reported line still points at the real line. See
      // `tests/sourceScan.ts` for why that helper is shared rather than copied.
      for (const { line, tag } of formTags(codeOnly(readFileSync(file, "utf8")))) {
        seen += 1;
        if (!/noValidate/.test(tag)) offenders.push(`${relPosix(process.cwd(), file)}:${line}`);
      }
    }
    expect(seen).toBeGreaterThan(50);
    expect(offenders).toEqual([]);
  });
});

/**
 * A rule with a number in it, and two refusals at once.
 *
 * The knowledge form asks for a title of at least two characters and an answer of at
 * least ten. Both were `minLength` with no `noValidate`, so a short answer produced
 * Chrome's "Please lengthen this text to 10 characters or more" — in Chrome's language,
 * beside a Submit button that had gone dead at nine characters for reasons the screen
 * never gave.
 */
describe("two answers missing at once", () => {
  const KB_ME: Me = {
    ...ME,
    permissions: ["org:read", "agents:read", "kb:write"],
  };
  const AGENT = {
    id: "0192f0aa-5555-7000-8000-000000000001",
    name: "Reception",
    status: "live",
    direction: "inbound",
    language_primary: "te-IN",
    extraction_fields: [],
  };

  async function renderKnowledge() {
    return await renderClientPage(<KnowledgePage />, {
      "/v1/me": KB_ME,
      "/v1/agents": [AGENT],
      "/v1/kb/sources": [],
      "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
      "POST /v1/kb/sources": { id: "kb-1" },
    });
  }

  it("names both, sends nothing, and puts focus on the first", async () => {
    const page = await renderKnowledge();
    const title = (await screen.findByLabelText(
      "What this knowledge is about",
    )) as HTMLInputElement;
    const body = screen.getByLabelText("What the agent should say") as HTMLTextAreaElement;

    fireEvent.click(screen.getByRole("button", { name: /Submit for review/ }));

    expect(await screen.findByText("Say what this is about.")).toBeTruthy();
    expect(screen.getByText("Write what the agent should say.")).toBeTruthy();
    expect(document.activeElement).toBe(title);
    expect(page.calls.some((c) => c.method === "POST")).toBe(false);

    // A title that is present but too short is the OTHER half of the rule, and it is
    // this module's sentence rather than a per-form one — the count comes off the
    // control, so the two cannot drift.
    fireEvent.change(title, { target: { value: "A" } });
    fireEvent.change(body, { target: { value: "Long enough to pass." } });
    fireEvent.click(screen.getByRole("button", { name: /Submit for review/ }));
    expect(await screen.findByText("Use at least 2 characters.")).toBeTruthy();
    expect(page.calls.some((c) => c.method === "POST")).toBe(false);

    fireEvent.change(title, { target: { value: "Parking" } });
    fireEvent.click(screen.getByRole("button", { name: /Submit for review/ }));
    await waitFor(() =>
      expect(page.calls.some((c) => c.method === "POST" && c.path === "/v1/kb/sources")).toBe(
        true,
      ),
    );
  });
});

/**
 * The unit under the screens: what each rule says, and in whose words.
 *
 * Driven through a real control rather than through a mock, because the rules are read
 * OFF the DOM — `el.minLength` is 2 only if the attribute is really there, and a fake
 * object would happily answer 2 for a control that carries nothing.
 */
describe("the words each rule uses", () => {
  function input(attrs: Record<string, string>): HTMLInputElement {
    const el = document.createElement("input");
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    return el;
  }

  it("says what is asked for when a field is empty, in the form's own words", () => {
    expect(fieldProblem(input({ required: "" }), "Enter your email address.")).toBe(
      "Enter your email address.",
    );
    // Whitespace is emptiness here. The browser counts a space as filled; the server
    // strips before it validates, so the browser's reading sends a space to be refused.
    const spaced = input({ required: "" });
    spaced.value = "   ";
    expect(fieldProblem(spaced, "Enter your email address.")).toBe("Enter your email address.");
  });

  it("never says 'field', 'required', 'invalid' or a type name", () => {
    const cases: [HTMLInputElement, string][] = [];
    const short = input({ minlength: "12" });
    short.value = "abc";
    cases.push([short, "min"]);
    const email = input({ type: "email" });
    email.value = "priya";
    cases.push([email, "email"]);
    const url = input({ type: "url" });
    url.value = "yourshop.example";
    cases.push([url, "url"]);
    const number = input({ type: "number", min: "1", max: "10" });
    number.value = "40";
    cases.push([number, "number"]);
    const day = input({ type: "date", max: "2026-09-02" });
    day.value = "2026-12-25";
    cases.push([day, "date"]);

    for (const [el] of cases) {
      const message = fieldProblem(el, "Answer this.");
      expect(message, `no message for ${el.type}`).toBeTruthy();
      for (const banned of ["field", "required", "invalid", "String", "format"]) {
        expect(message!.toLowerCase()).not.toContain(banned.toLowerCase());
      }
      // One sentence, ending in a full stop, like every other refusal in the console.
      expect(message!.endsWith(".")).toBe(true);
    }
  });

  it("reports emptiness before shape, because an empty box is not a bad address", () => {
    const email = input({ type: "email", required: "" });
    expect(fieldProblem(email, "Enter their email address.")).toBe(
      "Enter their email address.",
    );
  });

  it("passes an answer that satisfies the rule", () => {
    const email = input({ type: "email", required: "", minlength: "5" });
    email.value = "priya@clinic.example";
    expect(fieldProblem(email, "Enter their email address.")).toBeNull();
  });
});
