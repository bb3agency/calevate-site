import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import LlmModelPage from "@/app/admin/tenants/[tenantId]/llm-model/page";
import type { TenantSummary } from "@/lib/api/admin";
import { adminLlmDefaultsPath } from "@/lib/api/llmDefaults";
import type { LlmModelOption, OrganizationLlmDefaults } from "@/lib/api/llmModels";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * Setting ONE client's default language model from the operator console.
 *
 * What these pin, worst first:
 *
 * 1. **§52 — a failed read is a REFUSAL and the controls go with it.** This write replaces
 *    whatever is on file. It does NOT move what the client pays — their plan prices
 *    minutes, not models — but it does move OUR cost, so acting while the
 *    current state is unreadable can undo a colleague's change and re-price an account in
 *    one request. The form is WITHHELD, not disabled and not empty.
 * 2. **Inheriting is its own state, in both directions.** `default_llm_model: null` must
 *    read as "follows the platform default", never as an explicit choice that happens to
 *    match — and an operator must be able to put a client back onto it, which is the wire
 *    value `null` and not a model name.
 * 3. **The money is on screen before the click.** Every option carries its per-minute
 *    price, and the summary above the button says what a minute costs afterwards and which
 *    direction it moved. The comparison is exact: `Number()` on these strings is the hard
 *    rule 7 defect, and one of the fixtures below is chosen so that a float subtraction
 *    would print a figure nobody was ever charged.
 * 4. **It cannot happen by accident.** The console's idiom for a consequential admin write
 *    is a typed confirmation naming the act; here it names the model the client ENDS UP
 *    ON, so it differs per choice and cannot be typed past by muscle memory.
 * 5. **No `X-Confirm-Action`**, because the route publishes none — a header the API ignores
 *    is a confirmation of nothing (`admin/tenants/[tenantId]/credits/page.tsx`).
 * 6. **A refusal is the SERVER'S sentence**, rendered from problem+json, not a generic
 *    "something went wrong".
 * 7. **A control the session may not use is disabled with its reason**, before the click.
 */

const TENANT = "0192f0aa-9999-7000-8000-0000000000b1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const DEFAULTS_PATH = adminLlmDefaultsPath(TENANT);

/**
 * Two rates a float would get wrong, deliberately.
 *
 * `Number("0.4830") - Number("0.2400")` is 0.24300000000000002 in IEEE-754 doubles, so a
 * screen that subtracted these as numbers would offer to move a client for
 * "₹0.24300000000000002 per minute less". The assertion on the rendered difference below
 * is what makes that unwriteable.
 */
const PREMIUM_RATE = "0.4830";
const DEFAULT_RATE = "0.2400";
/** What the client pays extra for the dearer model — a plan term, not our cost (D-455). */
const PREMIUM_SURCHARGE = "1.5000";
const EXACT_DIFFERENCE = "₹0.2430";

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    vertical_template: "clinic",
    live_agents: 2,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

function me(permissions: string[]): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-9999-7000-8000-0000000000b2",
    role: "operator",
    permissions,
  };
}

const OPERATOR = me(["org:read", "admin:tenants"]);
const READ_ONLY = me(["org:read"]);

function option(over: Partial<LlmModelOption> = {}): LlmModelOption {
  return {
    model: "gpt-4o-mini",
    // The server's own machine value for the provider (`apps/api/agents/llm_routes.py`),
    // which the screen turns into a friendly heading through `providerLabel` — so this
    // fixture carries the wire token, not the label, and the test proves the mapping.
    provider: "azure_openai",
    platform_cost_inr_per_minute: DEFAULT_RATE,
    // D-455: what the CLIENT is charged extra for this model. `"0"` on the base-rate
    // model always, and on every model while the plan quotes no surcharge.
    client_surcharge_inr_per_minute: "0",
    is_platform_default: true,
    is_available: true,
    unavailable_reason: null,
    ...over,
  };
}

const PLATFORM = option();
const PREMIUM = option({
  model: "gpt-4.1-mini",
  platform_cost_inr_per_minute: PREMIUM_RATE,
  // A plan that quotes a surcharge — the state this console has to render honestly.
  client_surcharge_inr_per_minute: PREMIUM_SURCHARGE,
  is_platform_default: false,
});
/**
 * A model this platform quotes but has no deployment behind.
 *
 * `PUT` refuses it with `llm_model_not_deployed` (`apps/api/agents/llm_models.py`), and the
 * route's own comment says a screen must show the row DISABLED with the reason rather than
 * hide it — an operator has to be able to see what is left to configure.
 */
const UNDEPLOYED = option({
  model: "gpt-4o",
  platform_cost_inr_per_minute: "1.9200",
  is_platform_default: false,
  is_available: false,
  unavailable_reason: "No Azure deployment for gpt-4o on this platform yet.",
});

/** The client on OUR default: no choice of their own. */
function inheriting(over: Partial<OrganizationLlmDefaults> = {}): OrganizationLlmDefaults {
  return {
    default_llm_model: null,
    effective_default: PLATFORM.model,
    available: [PLATFORM, PREMIUM],
    ...over,
  };
}

/** The same client, explicitly pinned to the dearer model. */
function pinned(): OrganizationLlmDefaults {
  return {
    default_llm_model: PREMIUM.model,
    effective_default: PREMIUM.model,
    available: [PLATFORM, PREMIUM],
  };
}

/** The save control, typed — this suite has no jest-dom, so `disabled` is read directly. */
function saveButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "Save this model" }) as HTMLButtonElement;
}

function confirmField(name: string): HTMLInputElement {
  return screen.getByLabelText(`Type ${name} to confirm`) as HTMLInputElement;
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<LlmModelPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: OPERATOR,
    [DEFAULTS_PATH]: inheriting(),
    ...routes,
  });
}

describe("the per-client language-model screen", () => {
  it("withholds every control when the current model could not be read", async () => {
    const { container } = await render({
      [DEFAULTS_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this client's model settings.",
        retryable: true,
      }),
    });

    await screen.findByText("Cannot change the model while the current one is unreadable");

    // Not a disabled radio and not an empty form: no choice control exists at all,
    // because a blind write here replaces a colleague's change AND re-prices the client.
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /Save this model/ })).toBeNull();
    // And nothing on screen states a model, or a price, that we do not know.
    expect(container.textContent).not.toContain("In effect");
    // No figure either: the top notice explains that this control moves OUR cost,
    // but not one rupee figure is stated over a read that did not land.
    expect(container.textContent).not.toContain("₹");
  });

  it("renders a client with NO choice as following the platform default", async () => {
    const { container } = await render();

    await screen.findByText("None — follows the platform default");
    // Three separate facts, never collapsed into one verdict.
    expect(container.textContent).toContain("Platform default");
    expect(container.textContent).toContain("from the platform default");
  });

  it("shows a client's OWN choice as an explicit pin, not as the same thing", async () => {
    const { container } = await render({ [DEFAULTS_PATH]: pinned() });

    await screen.findByText(/from this client's own choice/);
    expect(container.textContent).not.toContain("None — follows the platform default");
  });

  it("prices every option on BOTH sides of the margin, and says which way each moves", async () => {
    const { container } = await render();

    // BOTH figures, labelled, and this is the screen that has to carry them together
    // (D-455): what the CLIENT is charged extra, and what it costs US. Every rate is
    // printed at the precision the server sent it — NOT `formatINR`'s two decimals, which
    // would round ₹0.4830 to ₹0.48 on a field an invoice multiplies by.
    await screen.findByText(new RegExp(`₹${PREMIUM_RATE} per minute to us`));
    expect(container.textContent).toContain(`₹${DEFAULT_RATE} per minute to us`);
    expect(container.textContent).toContain(`+₹${PREMIUM_SURCHARGE} per minute to them`);
    // A plan quoting no surcharge for the base model says so in words, on the operator's
    // screen as on the client's: "₹0.0000" is a rupee amount of nothing.
    expect(container.textContent).toContain("no extra charge to them");
    // The dearer option, against what this client is on today. A ROW compares the figure
    // an operator is moving on their behalf — what they will be CHARGED — and both
    // deltas appear in the summary above the button, where the decision is confirmed.
    // The difference is the exact decimal, which a float subtraction cannot produce.
    expect(container.textContent).toContain(`₹${PREMIUM_SURCHARGE} per minute more than now`);
    expect(container.textContent).not.toContain("0.24300000000000002");
  });

  it("states BOTH consequences in the summary above the button", async () => {
    const { container } = await render();

    fireEvent.click(await screen.findByRole("radio", { name: "gpt-4.1-mini" }));
    expect(container.textContent).toContain("This will record, against Sri Traders");
    // What the client pays, and what it costs us, as two lines. One line could only ever
    // be one of the two, and the screen's own prose contradicted itself about which for
    // as long as there was only one figure.
    expect(container.textContent).toContain(
      `They are charged extra — ₹${PREMIUM_SURCHARGE} per minute, ₹${PREMIUM_SURCHARGE} per minute more than now.`,
    );
    expect(container.textContent).toContain(
      `It costs us — ₹${PREMIUM_RATE} per minute of a five-minute call, ${EXACT_DIFFERENCE} per minute more than now.`,
    );
  });

  it("refuses to send until the outcome model is typed, and says which one", async () => {
    await render();

    fireEvent.click(await screen.findByRole("radio", { name: "gpt-4.1-mini" }));
    expect(saveButton().disabled).toBe(true);
    await screen.findByText(/type gpt-4\.1-mini in the field above/);

    // A near miss is still a miss: the field is the double-key on which model was meant.
    fireEvent.change(confirmField(PREMIUM.model), { target: { value: "gpt-4.1" } });
    expect(saveButton().disabled).toBe(true);

    fireEvent.change(confirmField(PREMIUM.model), { target: { value: PREMIUM.model } });
    expect(saveButton().disabled).toBe(false);
  });

  it("clears a typed confirmation when the choice moves under it", async () => {
    await render({ [DEFAULTS_PATH]: pinned() });

    fireEvent.click(await screen.findByRole("radio", { name: "gpt-4o-mini" }));
    fireEvent.change(confirmField(PLATFORM.model), { target: { value: PLATFORM.model } });
    expect(saveButton().disabled).toBe(false);

    // Same outcome model, a different ROUTE to it — the confirmation must not carry over,
    // or a phrase typed for one row would confirm a change made on another.
    fireEvent.click(screen.getByRole("radio", { name: "Follow the platform default" }));
    expect(confirmField(PLATFORM.model).value).toBe("");
    expect(saveButton().disabled).toBe(true);
  });

  it("sends the chosen model, and no confirmation header", async () => {
    const { calls } = await render({ [`PUT ${DEFAULTS_PATH}`]: {} });

    fireEvent.click(await screen.findByRole("radio", { name: "gpt-4.1-mini" }));
    fireEvent.change(confirmField(PREMIUM.model), { target: { value: PREMIUM.model } });
    fireEvent.click(saveButton());

    await screen.findByText(/agents default to/);
    const write = calls.find((call) => call.method === "PUT");
    expect(write, "the screen must send the change").toBeTruthy();
    expect(write!.path).toBe(DEFAULTS_PATH);
    expect(JSON.parse(write!.body ?? "{}")).toEqual({ default_llm_model: PREMIUM.model });
    // The route publishes no confirmation string, and a header the API ignores is a
    // confirmation of nothing — the typed field above is what confirms this write.
    expect(write!.headers["X-Confirm-Action"]).toBeUndefined();
  });

  it("offers 'follow the platform default' as its own choice, and sends null for it", async () => {
    const { calls } = await render({
      [DEFAULTS_PATH]: pinned(),
      [`PUT ${DEFAULTS_PATH}`]: {},
    });

    fireEvent.click(await screen.findByRole("radio", { name: "Follow the platform default" }));
    // The confirmation is the model they FALL BACK ONTO, not the word "inherit".
    fireEvent.change(confirmField(PLATFORM.model), { target: { value: PLATFORM.model } });
    fireEvent.click(saveButton());

    await screen.findByText(/follows the platform default again/);
    const write = calls.find((call) => call.method === "PUT");
    expect(write, "the screen must send the clear").toBeTruthy();
    expect(JSON.parse(write!.body ?? "{}")).toEqual({ default_llm_model: null });
  });

  it("refuses to clear a choice this client does not have", async () => {
    await render();
    // The form opens on the stored position, so the button is dead until something moves.
    await screen.findByText(/no choice of their own to clear/);
    expect(saveButton().disabled).toBe(true);
  });

  it("refuses to re-send the model already on file", async () => {
    await render({ [DEFAULTS_PATH]: pinned() });
    await screen.findByText(/already this client's own default/);
    expect(saveButton().disabled).toBe(true);
  });

  it("calls out a client pinned to a model the platform no longer offers", async () => {
    const { container } = await render({
      [DEFAULTS_PATH]: {
        default_llm_model: "sarvam-105b",
        effective_default: "sarvam-105b",
        available: [PLATFORM, PREMIUM],
      },
    });

    await screen.findByText("This client is pinned to a model the platform no longer offers");
    // The retired id is shown rather than hidden — a hidden pin is how a client stays on
    // something nobody can see — and no price is invented for it.
    expect(container.textContent).toContain("sarvam-105b");
  });

  it("will not state a fallback the catalogue does not name", async () => {
    await render({
      [DEFAULTS_PATH]: {
        default_llm_model: PREMIUM.model,
        effective_default: PREMIUM.model,
        available: [PREMIUM],
      },
    });

    fireEvent.click(await screen.findByRole("radio", { name: "Follow the platform default" }));
    await screen.findByText(/names no default model/);
    expect(saveButton().disabled).toBe(true);
  });


  it("names each option by its model id, and puts the money in the description", async () => {
    /**
     * The documented departure from the flag screen's wrapped label, pinned so it cannot
     * quietly come undone. Text nodes concatenate with NO separator in the accessible-name
     * computation, so the wrapped form announced "gpt-4o-mini₹0.2400 per minute · what the
     * platform runs by default…" as the control's NAME — the id and the price run together,
     * and the whole row arrives before the reader knows what the control is. `aria-label` +
     * `aria-describedby` is ARIA's own answer for a radio with a rich description, and it
     * also makes the name the exact string this screen asks the operator to type into the
     * confirmation.
     *
     * The PROVIDER is no longer in the description at all (D-456): it heads the group above
     * the row, rendered through `providerLabel`, so the row's description is money only and
     * the wire token never reaches the screen.
     */
    await render({ [DEFAULTS_PATH]: inheriting({ available: [PLATFORM, PREMIUM] }) });

    const row = (await screen.findByRole("radio", { name: "gpt-4o-mini" })) as HTMLInputElement;
    const describedBy = row.getAttribute("aria-describedby");
    expect(describedBy, "the row's detail must be a DESCRIPTION, not part of the name").toBeTruthy();
    const detail = document.getElementById(describedBy!);
    expect(detail, "aria-describedby must point at an element that exists").toBeTruthy();
    // The money is the row's description; the provider is not — it labels the group.
    expect(detail!.textContent).toContain(`₹${DEFAULT_RATE} per minute`);
    expect(detail!.textContent).not.toContain("azure_openai");
    // The provider LABEL heads a group, and it is the friendly form, never the wire token.
    const group = screen.getByRole("group", { name: "Azure OpenAI" });
    expect(group.textContent).not.toContain("azure_openai");
  });

  it("presents all three providers as their own labelled groups, on equal footing", async () => {
    // The founder's decision: Gemini and OpenAI shown on par with Azure. The console
    // renders one labelled sub-group per provider, in the order the server sent them, and
    // each model sits under its own provider — never crammed into another's group.
    const openaiModel = option({
      model: "gpt-5-mini",
      provider: "openai",
      is_platform_default: false,
    });
    const geminiModel = option({
      model: "gemini-2.5-flash",
      provider: "google",
      is_platform_default: false,
    });
    await render({
      [DEFAULTS_PATH]: inheriting({ available: [PLATFORM, PREMIUM, openaiModel, geminiModel] }),
    });

    await screen.findByRole("radio", { name: "gpt-4o-mini" });
    // An EXACT string name, so "OpenAI" does not also match "Azure OpenAI".
    for (const label of ["Azure OpenAI", "OpenAI", "Google Gemini"]) {
      expect(
        screen.getByRole("group", { name: label }),
        `provider ${label} must head its own group`,
      ).toBeTruthy();
    }
    expect(screen.getByRole("group", { name: "OpenAI" }).textContent).toContain("gpt-5-mini");
    expect(screen.getByRole("group", { name: "Google Gemini" }).textContent).toContain(
      "gemini-2.5-flash",
    );
  });

  it("shows a model with no deployment behind it, disabled, with the server's reason", async () => {
    const { container } = await render({
      [DEFAULTS_PATH]: inheriting({ available: [PLATFORM, PREMIUM, UNDEPLOYED] }),
    });

    const row = (await screen.findByRole("radio", { name: "gpt-4o" })) as HTMLInputElement;
    // SHOWN, not hidden: an operator must be able to see what is left to configure.
    expect(row.disabled).toBe(true);
    expect(container.textContent).toContain("No Azure deployment for gpt-4o on this platform yet.");
  });

  it("never disables a row on an API build that does not report availability", async () => {
    // `undefined` is "this deployment does not say", not "unavailable" — an older API
    // reports neither field, and refusing on absence would dead-end the whole screen.
    // Spelled out rather than derived, because what an older build sends is exactly these
    // four keys and no more. The generated wire type makes `is_available` and
    // `unavailable_reason` REQUIRED — right for every build we serve — so a fixture missing
    // them cannot be that type, and pretending otherwise would assert the thing under test.
    const full = option({ model: "gpt-4o", is_platform_default: false });
    const silent = {
      model: full.model,
      provider: full.provider,
      platform_cost_inr_per_minute: full.platform_cost_inr_per_minute,
      is_platform_default: full.is_platform_default,
    };

    // Built by spread rather than through `inheriting()`, whose return type is
    // today's strict wire shape. This payload is deliberately NOT that shape — it is
    // what an older server sends — so annotating it with the current type would be
    // asserting the very thing under test. Inferred, and handed to the route stub as
    // the JSON it is.
    const older = { ...inheriting(), available: [PLATFORM, silent] };

    await render({ [DEFAULTS_PATH]: older });

    const row = (await screen.findByRole("radio", { name: "gpt-4o" })) as HTMLInputElement;
    expect(row.disabled).toBe(false);
  });

  it("surfaces the server's own refusal rather than pretending the write landed", async () => {
    await render({
      [`PUT ${DEFAULTS_PATH}`]: problem(409, {
        title: "Changed concurrently",
        detail: "This client's default model was changed by someone else a moment ago.",
        remediation: "Re-read the model and send the change again.",
      }),
    });

    fireEvent.click(await screen.findByRole("radio", { name: "gpt-4.1-mini" }));
    fireEvent.change(confirmField(PREMIUM.model), { target: { value: PREMIUM.model } });
    fireEvent.click(saveButton());

    await screen.findByText(/changed by someone else a moment ago/);
    await screen.findByText(/Re-read the model and send the change again/);
    expect(screen.queryByText(/agents default to/)).toBeNull();
  });

  it("disables the controls, with the reason, for a session that may not write", async () => {
    await render({ [ADMIN_ME_PATH]: READ_ONLY, [DEFAULTS_PATH]: pinned() });

    await screen.findByText(/does not have the admin:tenants permission/);
    for (const radio of screen.getAllByRole("radio"))
      expect((radio as HTMLInputElement).disabled).toBe(true);
    // The form opens on the STORED choice, so that is the model the confirmation names.
    expect(confirmField(PREMIUM.model).disabled).toBe(true);
    expect(saveButton().disabled).toBe(true);
  });

  it("reads this client's row with the ADMIN session, never through impersonation", async () => {
    const { calls } = await render();
    await screen.findByText("None — follows the platform default");

    const read = calls.find((call) => call.path === DEFAULTS_PATH);
    expect(read, "the screen must read the defaults").toBeTruthy();
    // D-22: `admin:tenants` is a mutating permission and `core/auth.py` refuses it for an
    // impersonating principal, so a screen that read through `viewAsSession` would have a
    // read that works and a write that cannot.
    expect(read!.headers["X-Impersonate-Org"]).toBeUndefined();
    expect(read!.headers["X-Org-Slug"]).toBeUndefined();
  });
});
