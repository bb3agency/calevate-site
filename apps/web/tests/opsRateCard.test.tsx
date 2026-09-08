import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import OpsConfigPage from "@/app/admin/ops/config/page";
import {
  OPS_RATE_CARD_PATH,
  cardInstant,
  cellVerdict,
  earliestPickableDate,
  rateDelta,
  type PendingCard,
  type RateCard,
  type RateCardCell,
} from "@/lib/api/opsRateCard";
import { OPS_TTS_PRICES_PATH, type TtsPrice } from "@/lib/api/opsTtsPricing";
import { ttsVerdict } from "@/app/admin/ops/ModelPricingPanel";
import { OPS_CONFIG_PATH, type ConfigField, type ConfigList } from "@/lib/api/opsConfig";
import { OPS_MODEL_PRICES_PATH } from "@/lib/api/opsModelPricing";
import { OPS_DASHBOARD_DATA_USE_PATH } from "@/lib/api/opsDashboardDataUse";
import { OPS_FX_RATE_PATH } from "@/lib/api/opsFxRate";
import { OPS_SECRETS_PATH } from "@/lib/api/opsSecrets";

import { problem, stubApi, type Routes } from "./harness";

/**
 * THE RATE CARD AND THE VOICE PRICE, on the ops console (D-547).
 *
 * What these pin, worst consequence first:
 *
 * 1. **A THIN MARGIN IS A WARNING AND MUST NEVER BECOME A REFUSAL.** The whole Sarvam
 *    column sits under the 20% target and above cost, by the founder's decision, and the
 *    server's own guard refuses BELOW COST and only REPORTS below target
 *    (`billing/rates.card_margins` / `card_refusals`). A console that rendered "thin" as a
 *    refusal, or disabled the save on one, would take the card that is actually on sale off
 *    sale — the single most expensive mistake this screen can make, and the reason the
 *    first test here asserts the ABSENCE of a refusal as hard as it asserts the warning.
 * 2. **The card's two real refusals arrive as the server's sentences.** `_record_card`
 *    raises one code for two causes — below cost, and a column that stops falling — and
 *    names the pack, the voice and both numbers in each. A generic "the write failed" sends
 *    an operator to the logs for a message the response already carried.
 * 3. **A card that could not be read renders NO cells.** A price table of TypeScript
 *    defaults is a screenful of invented money an operator would commit against.
 * 4. **An unattested voice price BLOCKS a tier rather than looking empty.** Under BYOK the
 *    engine reports the synthesizer leg as ₹0, so an unpriced Cartesia minute would meter as
 *    free and show a margin that does not exist (hard rule 7).
 * 5. **The vendor is NAMED on this screen.** Clients read "Clear" and "Studio"; an operator
 *    pasting a Cartesia key or attesting a Cartesia invoice needs to know whose key and
 *    whose invoice, so both names are on the row.
 */

const SUPERADMIN: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000c1",
  role: "superadmin",
  permissions: ["org:read", "admin:tenants", "ops:manage", "platform:config", "platform:secrets"],
};

function configField(over: Partial<ConfigField> = {}): ConfigField {
  return {
    key: "self_serve_inr_per_min",
    env_var: "SELF_SERVE_INR_PER_MIN",
    value: "5.00",
    source: "default",
    default: "5.00",
    has_default: true,
    kind: "decimal",
    options: [],
    editable: true,
    applies: "live",
    caveat: null,
    etag: '"7"',
    updated_by: null,
    updated_at: null,
    note: null,
    ...over,
  };
}

function configList(): ConfigList {
  return {
    bootstrap: [],
    fields: [configField()],
    config_version: 42,
    stale: false,
    never_loaded: false,
    config_changed_at: "2026-08-12T09:00:00Z",
  };
}

/** One cell of the card, as `GET /v1/ops/rate-card` publishes it. */
function cell(over: Partial<RateCardCell> = {}): RateCardCell {
  return {
    pack_id: "starter",
    amount_inr: "2000.00",
    voice_tier: "sarvam",
    tier_label: "Clear",
    inr_per_min: "5.0000",
    cost_floor_inr_per_min: "4.1211",
    gross_margin_pct: "17.60",
    // THE FOUNDER'S OWN CARD: under target, above cost. Every case below is arranged
    // around this row being sellable.
    below_target: true,
    below_floor: false,
    ...over,
  };
}

const HEALTHY = cell({
  pack_id: "max",
  amount_inr: "50000.00",
  voice_tier: "cartesia",
  tier_label: "Studio",
  inr_per_min: "6.0000",
  cost_floor_inr_per_min: "4.3639",
  gross_margin_pct: "27.27",
  below_target: false,
});

function card(cells: RateCardCell[] = [cell(), HEALTHY], over: Partial<RateCard> = {}): RateCard {
  return {
    effective_from: "2026-09-07T04:30:00Z",
    target_gross_margin_pct: "20",
    cells,
    // THE WRITE HALF OF THE READ (D-550). `earliest_effective_from` is an INSTANT and the
    // picker's floor is a DAY: 09:44 UTC is 15:14 IST, so midnight on the 8th is already
    // past and the earliest day this fixture can offer is the 9th. Every assertion about
    // the floor below is arranged around that being derived rather than echoed.
    pending: [],
    notice_days: 30,
    notice_recipients: 3,
    earliest_effective_from: "2026-10-08T09:44:00Z",
    ...over,
  };
}

/**
 * A card with EVERY rung on BOTH voices — what the write form needs, because it posts the
 * cells it is showing and each box is required. `card()` above is deliberately ragged (one
 * voice per rung) and stays that way: it is what the read tests are arranged around, and it
 * exercises the "no rate in force to compare against" arm of the delta.
 */
function fullCard(over: Partial<RateCard> = {}): RateCard {
  return card(
    [
      cell(),
      cell({ voice_tier: "cartesia", tier_label: "Studio", inr_per_min: "6.0000", below_target: false }),
      cell({ pack_id: "max", amount_inr: "50000.00", inr_per_min: "4.5000" }),
      cell({
        pack_id: "max",
        amount_inr: "50000.00",
        voice_tier: "cartesia",
        tier_label: "Studio",
        inr_per_min: "5.5000",
        below_target: false,
      }),
    ],
    over,
  );
}

/** The card the write tests read, with one rung already scheduled to move. */
const SCHEDULED: PendingCard = {
  effective_from: "2026-10-20T00:00:00+00:00",
  cells: [
    cell({ inr_per_min: "5.5000" }),
    cell({ voice_tier: "cartesia", tier_label: "Studio", inr_per_min: "6.0000", below_target: false }),
  ],
};

const MODEL_PRICES_BASE = {
  prices: [
    {
      model: "gpt-4o-mini",
      provider: "azure_openai",
      credential_installed: true,
      price_attested: true,
      offerable: true,
      input_usd_per_mtok: "0.150000",
      output_usd_per_mtok: "0.600000",
      effective_from: "2026-08-01T00:00:00Z",
      attested_at: "2026-08-12T09:00:00Z",
      attested_by: "Ops",
      source_note: "Azure invoice 2026-08",
      reference_input_usd_per_mtok: "0.15",
      reference_output_usd_per_mtok: "0.60",
      reference_verified: true,
      withheld_reason: null,
    },
  ],
  as_of: "2026-09-07T00:00:00Z",
  // REQUIRED on `ModelPricesOut`. Empty here on purpose: this base is what the "no voice
  // prices" case is rendered from, and `routes()` puts the two real rows on top of it.
  tts_prices: [],
};

/** One voice row, as `GET /v1/ops/model-prices` publishes it. */
function ttsRow(over: Partial<TtsPrice> = {}): TtsPrice {
  return {
    provider: "cartesia",
    tier_label: "Studio",
    tts_model: "sonic-3.5",
    // The CATALOGUE figure — a pre-fill to confirm an invoice against, never the value a
    // minute is metered at. Required on `TtsPriceOut`.
    reference_inr_per_1k_chars: "3.4496",
    credential_installed: true,
    price_attested: false,
    price_billable: false,
    offerable: false,
    billable_without_attestation_reason: null,
    inr_per_1k_chars: null,
    effective_from: null,
    attested_at: null,
    attested_by: null,
    source_note: null,
    ...over,
  };
}

const SARVAM_ROW = ttsRow({
  provider: "sarvam",
  tier_label: "Clear",
  tts_model: "bulbul:v3",
  price_attested: false,
  price_billable: true,
  offerable: true,
  billable_without_attestation_reason:
    "The call platform bills us for this synthesizer leg and reports what it charged, so " +
    "every call already carries a measured cost. There is nothing to confirm.",
});

const FX_RATE = {
  base_currency: "USD",
  quote_currency: "INR",
  effective_rate: "88.427500",
  state: "live",
  using_fallback: false,
  fallback_rate: "88.00",
  published_rate: "88.427500",
  published_as_of: "2026-08-27",
  published_source: "frankfurter:FBIL",
  observed_at: "2026-08-27T04:05:00Z",
  age_label: "3 minutes ago",
  max_age_days: 5,
  history: [],
};

const DASHBOARD_DATA_USE = { providers: [], statement: "" };
const SECRETS = { secrets: [] };
const KEK = {
  active_kek_id: 1633907231,
  has_retired_kek: false,
  versions: 2,
  current: 2,
  pending: 0,
};

function routes(extra: Routes = {}): Routes {
  const table: Routes = {
    [ADMIN_ME_PATH]: SUPERADMIN,
    [OPS_CONFIG_PATH]: configList(),
    [OPS_RATE_CARD_PATH]: card(),
    [OPS_MODEL_PRICES_PATH]: { ...MODEL_PRICES_BASE, tts_prices: [SARVAM_ROW, ttsRow()] },
    [OPS_DASHBOARD_DATA_USE_PATH]: DASHBOARD_DATA_USE,
    [OPS_FX_RATE_PATH]: FX_RATE,
    [OPS_SECRETS_PATH]: SECRETS,
    [`${OPS_SECRETS_PATH}/kek`]: KEK,
  };
  for (const key of Object.keys(extra)) {
    const descriptor = Object.getOwnPropertyDescriptor(extra, key);
    if (descriptor) Object.defineProperty(table, key, descriptor);
  }
  return table;
}

function renderOps(table: Routes) {
  const calls = stubApi(table);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <OpsConfigPage />
    </QueryClientProvider>,
  );
  return Object.assign(result, { calls });
}

/* ════════════════════════════════════════════════════════════════════════════════════ */

describe("the rate card an operator is about to date", () => {
  it("prints every cell with the vendor, the tier the client reads, and the server's own margin", async () => {
    const { container } = renderOps(routes());

    await screen.findByText(/Rate card — six packs, two voices/);
    // The CELLS, once the read lands — the panel header renders before the query does, and
    // asserting on the header alone would pass on an empty table.
    await screen.findByText("17.60%");
    // The VENDOR and the client-facing label, together — the deliberate exception this
    // screen is. A cell naming only one of the two leaves an operator unable to connect a
    // rate to the key they installed, or to the word the client is quoting at them.
    expect(container.textContent).toContain("Sarvam · Clear");
    expect(container.textContent).toContain("Cartesia · Studio");
    // The server's percentage, printed — never a division done in the browser from two
    // rounded figures.
    expect(container.textContent).toContain("17.60%");
    expect(container.textContent).toContain("27.27%");
    // The rate and the cost it was struck against, both as exact strings.
    expect(container.textContent).toContain("₹5.0000");
    expect(container.textContent).toContain("₹4.1211");
  });

  /**
   * THE REGRESSION THAT WOULD TAKE THE FOUNDER'S CARD OFF SALE.
   *
   * A thin rung must read as a warning an operator acts on, and must NOT read as a refusal,
   * must not disable the save, and must not claim nothing was written. If this test ever
   * fails, the console is refusing the card that is actually on sale.
   */
  it("shows a thin margin as a warning, never as a refusal, and leaves the write armed", async () => {
    const { container } = renderOps(routes());

    await screen.findByText(/1 of 2 rungs earn less than 20%/);
    expect(container.textContent).toContain("above what the minute costs us");
    expect(container.textContent).toContain("a decision, not a fault");

    // NOT A REFUSAL. None of the refusal sentences may appear anywhere on the screen for a
    // card whose only fault is thinness.
    // The below-cost refusal, VERBATIM as the panel would render it — a paraphrase here is
    // an assertion that passes while the screen refuses the card.
    expect(screen.queryByText("Some rungs sell a minute for less than it costs")).toBeNull();
    expect(container.textContent).not.toContain(
      "The server refuses to record a card in this state",
    );
    expect(container.textContent).not.toContain("nothing was saved");
    expect(screen.queryByText(/The rate card was refused/)).toBeNull();

    // AND THE WRITE IS STILL AVAILABLE: the row that dates the card offers its form, and
    // filling it arms the save. A thin margin blocks nothing.
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fireEvent.change(screen.getByLabelText(/New value/), { target: { value: "5.00" } });
    fireEvent.change(screen.getByPlaceholderText(/Q3 price change/), {
      target: { value: "re-dating the card" },
    });
    fireEvent.change(screen.getByPlaceholderText("SELF_SERVE_INR_PER_MIN"), {
      target: { value: "SELF_SERVE_INR_PER_MIN" },
    });
    expect((screen.getByRole("button", { name: /^Save$/ }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("renders the two refusals as the server's own sentences when the write is refused", async () => {
    const { container } = renderOps(
      routes({
        [`PUT ${OPS_CONFIG_PATH}/self_serve_inr_per_min`]: problem(409, {
          kind: "conflict",
          type: "urn:calevate:conflict/rate_card_below_floor",
          title: "The rate card cannot be published",
          detail:
            "Calevate refused to record this rate card because it would sell minutes below " +
            "what they cost: starter on sarvam is 4.0000/min against a floor of 4.1211; " +
            "scale on cartesia is 6.7500/min but plus is dearer at 6.5000",
          retryable: false,
        }),
      }),
    );

    await screen.findByText("self_serve_inr_per_min");
    fireEvent.click(screen.getAllByRole("button", { name: /Change/ })[0]);
    fireEvent.change(screen.getByLabelText(/New value/), { target: { value: "4.00" } });
    fireEvent.change(screen.getByPlaceholderText(/Q3 price change/), {
      target: { value: "cutting the rate" },
    });
    fireEvent.change(screen.getByPlaceholderText("SELF_SERVE_INR_PER_MIN"), {
      target: { value: "SELF_SERVE_INR_PER_MIN" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    await screen.findByText(/The rate card was refused — nothing was saved/);
    // BOTH causes, split back into the sentences the server wrote — each names the pack,
    // the voice and the numbers, which is what an operator acts on.
    expect(container.textContent).toContain(
      "starter on sarvam is 4.0000/min against a floor of 4.1211",
    );
    expect(container.textContent).toContain(
      "scale on cartesia is 6.7500/min but plus is dearer at 6.5000",
    );
  });

  it("shows no cells at all when the card could not be read", async () => {
    const { container } = renderOps(routes({ [OPS_RATE_CARD_PATH]: problem(404, {}) }));

    await screen.findByText("We could not read the rate card");
    // NOT a table of defaults: no rate, no floor, no margin and no verdict anywhere.
    expect(container.textContent).not.toContain("₹5.0000");
    expect(container.textContent).not.toContain("₹4.1211");
    expect(container.textContent).not.toContain("Thin margin");
    expect(container.textContent).not.toContain("rungs earn less than");
  });
});

describe("the voice price that decides whether a tier can be sold", () => {
  it("says an unconfirmed price BLOCKS the voice, and names the vendor beside the tier", async () => {
    const { container } = renderOps(routes());

    await screen.findByText(/Voice prices/);
    expect(container.textContent).toContain("Cartesia · Studio");
    expect(container.textContent).toContain("sonic-3.5");
    expect(container.textContent).toContain("This voice cannot be sold until its price is confirmed");
    // The CONSEQUENCE, in the words that make it actionable: a blank price is not "no data",
    // it is a leg that would meter every minute as free.
    expect(container.textContent).toContain("metered as free");
    expect(container.textContent).toContain("Blocked — needs a confirmed price");
  });

  it("does not demand an attestation for the leg the engine already bills us for", async () => {
    const { container } = renderOps(routes());

    await screen.findByText(/Voice prices/);
    expect(container.textContent).toContain("Sarvam · Clear");
    expect(container.textContent).toContain("There is nothing to confirm.");
    expect(container.textContent).toContain("On sale to customers");
  });

  it("sends the typed rupees as an exact string, with the step-up bound to the vendor", async () => {
    const { calls } = renderOps(
      routes({ [`POST ${OPS_TTS_PRICES_PATH}/cartesia`]: { ok: true } }),
    );

    await screen.findByText(/Voice prices/);
    fireEvent.click(screen.getAllByRole("button", { name: /Confirm price/ }).slice(-1)[0]);
    fireEvent.change(screen.getByLabelText(/Price \(₹ per 1,000 characters\)/), {
      target: { value: "3.4496" },
    });
    fireEvent.change(screen.getByPlaceholderText(/Cartesia Startup plan/), {
      target: { value: "Cartesia Startup plan, Sep 2026 invoice" },
    });
    fireEvent.change(screen.getByLabelText(/Type CONFIRM/), { target: { value: "CONFIRM" } });
    // The SUBMIT inside the open form, not the button that opens another row's form: three
    // controls on this screen carry the words "Confirm price".
    const form = screen.getByLabelText(/Price \(₹ per 1,000 characters\)/).closest("form");
    fireEvent.submit(form as HTMLFormElement);

    const write = await waitForCall(calls, `POST ${OPS_TTS_PRICES_PATH}/cartesia`);
    // The exact string, four decimals of a division somebody did against an invoice —
    // never a JSON number (hard rule 7).
    expect(write.body).toContain('"inr_per_1k_chars":"3.4496"');
    expect(write.headers["X-Confirm-Action"]).toBe("attest_tts_price:cartesia");
  });

  it("shows nothing rather than a table when the API published no voice prices", async () => {
    // An EMPTY list, not an absent field: `ModelPricesOut.tts_prices` is required now, so
    // the case the panel still has to survive is a server that sent no rows.
    const { container } = renderOps(
      routes({ [OPS_MODEL_PRICES_PATH]: MODEL_PRICES_BASE }),
    );

    await screen.findByText("This deployment did not send any voice prices");
    expect(container.textContent).toContain("treat this as unknown, not as free");
    // The rate card above names the same two words for a different fact, so the tell that
    // no voice ROW rendered is the synthesizer model and the row's own verdict.
    expect(container.textContent).not.toContain("sonic-3.5");
    expect(container.textContent).not.toContain("On sale to customers");
  });
});

/* ── the pure functions, where the seam is cheapest to pin ───────────────────────────── */

/*
 * DELETED with the validators they tested: "drops the whole card when one cell is
 * malformed" and "returns null when the payload carries none".
 *
 * Both fed `asRateCard` / `ttsPricesOf` a payload with a field missing or of the wrong
 * type, and asserted the reader dropped the whole set rather than rendering a short card
 * or defaulting a sellability flag to true. `RateCardOut` and `ModelPricesOut.tts_prices`
 * are generated now, with every field on both required, so those readers are gone and the
 * payloads they refused cannot be built without an `as` onto a wire type — the assertion
 * `tests/wireFixtureGuard.test.ts` exists to stop. The property they protected is the
 * compiler's: a cell with a null cost floor does not type-check anywhere in this app. The
 * rendered case that IS still reachable — a read that failed, so no cells at all — is
 * pinned above by "shows no cells at all when the card could not be read".
 */

describe("what a margin verdict may say", () => {
  it("never returns a refusal tone for a thin cell — there is no such tone to return", () => {
    const thin = cellVerdict(card().cells[0], "20");
    expect(thin.tone).toBe("thin");
    expect(thin.sentence).toContain("deliberately");
    const healthy = cellVerdict(card().cells[1], "20");
    expect(healthy.tone).toBe("ok");
  });
});

describe("reading a voice price off the wire", () => {
  it("names both gaps when both are missing, so the operator does one trip", () => {
    expect(ttsVerdict(ttsRow({ credential_installed: false })).label).toBe(
      "Blocked — needs a vendor key and a confirmed price",
    );
    expect(ttsVerdict(ttsRow({ offerable: true })).label).toBe("On sale to customers");
  });
});


/* ════════════════════════════════════════════════════════════════════════════════════ */

/**
 * RECORDING A CARD — the half the founder asked for: "make it editable, and every time the
 * price is updated all the affected clients should be notified about it for sure."
 *
 * What these pin, worst consequence first:
 *
 * 1. **THE NUMBER OF CLIENTS WHO GET AN EMAIL IS IN FRONT OF THE OPERATOR BEFORE THEY
 *    SAVE.** The notice is the founder's condition on the whole feature, and its size is
 *    something you learn before sending it, not from the replies. A screen that hid it
 *    would make "tell everyone" a surprise.
 * 2. **THE INSTANT ON THE WIRE IS THE ONE THE STEP-UP HEADER NAMES.** The API builds
 *    `record_rate_card:<isoformat>` from the instant it PARSED, so a console that sent
 *    `toISOString()` would name `…T18:30:00.000Z` while the server computed
 *    `…T18:30:00+00:00` and every save would be refused with a message telling the
 *    operator to reload — which would never help. This is the single most expensive
 *    regression available on this screen, and it is invisible in a diff.
 * 3. **MONEY IS THE TYPED STRING.** A JSON number is a binary float; the API refuses one
 *    outright, and a console that sent `4.85` as a number would be refused on every save.
 * 4. **A REFUSAL SAYS WHAT TO DO.** `rate_card_too_soon` must print the earliest date this
 *    deployment accepts — the operator's next act is picking it.
 * 5. **A SCHEDULED CARD CAN BE TAKEN BACK,** with the server's own instant echoed, because
 *    a card recorded by mistake is otherwise priced into every purchase from its date.
 * 6. **AN OLDER API MUST NOT BLANK THE SCREEN.** `pending` is required on the current
 *    build and absent on the previous one; reading it blindly would throw inside render and
 *    take the whole configuration screen — settings, secrets, prices — down with it.
 */
describe("recording the next rate card", () => {
  it("says how many clients will be emailed before anything is sent", async () => {
    const { container } = renderOps(routes({ [OPS_RATE_CARD_PATH]: fullCard() }));

    await screen.findByRole("button", { name: /Record a new card/ });
    fireEvent.click(screen.getByRole("button", { name: /Record a new card/ }));

    // The SERVER's count, in front of the button, before a keystroke is typed.
    await screen.findByText("3 clients will be emailed as soon as you record this");
    expect(container.textContent).toContain("Clients on an invoiced plan are not emailed");
    // And the promise that stops the support call, on the same panel.
    expect(container.textContent).toContain("Credit already bought is not repriced");
  });

  it("does not invent a count when the API did not publish one", async () => {
    // The previous build's payload: no `notice_recipients` key at all. A console that
    // showed `0` here would tell an operator that recording a card emails nobody.
    const older = fullCard();
    delete (older as { notice_recipients?: number }).notice_recipients;
    const { container } = renderOps(routes({ [OPS_RATE_CARD_PATH]: older }));

    fireEvent.click(await screen.findByRole("button", { name: /Record a new card/ }));

    await screen.findByText("We do not know how many clients would be emailed");
    expect(container.textContent).not.toContain("0 clients will be emailed");
    expect(container.textContent).toContain("no number is shown rather than a guessed one");
  });

  it("sends the typed rates as exact strings, with the step-up bound to the instant it sent", async () => {
    const { calls } = renderOps(
      routes({
        [OPS_RATE_CARD_PATH]: fullCard(),
        [`POST ${OPS_RATE_CARD_PATH}`]: {
          effective_from: "2026-10-20T00:00:00+05:30",
          cells: [],
          clients_notified: true,
        },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /Record a new card/ }));
    fireEvent.change(screen.getByLabelText("Rupees per minute, starter pack on Sarvam Clear"), {
      target: { value: "5.5000" },
    });
    fireEvent.change(screen.getByLabelText(/The day the new rates start/), {
      target: { value: "2026-10-20" },
    });
    fireEvent.change(screen.getByPlaceholderText(/Cartesia raised/), {
      target: { value: "Cartesia raised its per-character price" },
    });
    fireEvent.change(screen.getByLabelText(/Type RECORD/), { target: { value: "RECORD" } });
    fireEvent.click(screen.getByRole("button", { name: /^Record card$/ }));

    const write = await waitForCall(calls, `POST ${OPS_RATE_CARD_PATH}`);
    // THE EXACT STRING THE OPERATOR TYPED — never a JSON number (hard rule 7). The quotes
    // are the assertion: `"inr_per_min":5.5` would be a float on the wire.
    expect(write.body).toContain('"inr_per_min":"5.5000"');
    expect(write.body).toContain('"pack_id":"starter"');
    // MIDNIGHT IST WITH THE OFFSET WRITTEN IN, not `toISOString()`. Both halves are
    // asserted because only their EQUALITY makes the save possible.
    expect(write.body).toContain('"effective_from":"2026-10-20T00:00:00+05:30"');
    expect(write.headers["X-Confirm-Action"]).toBe("record_rate_card:2026-10-20T00:00:00+05:30");
  });

  it("shows what each rate moved by, against the card in force", async () => {
    renderOps(routes({ [OPS_RATE_CARD_PATH]: fullCard() }));

    fireEvent.click(await screen.findByRole("button", { name: /Record a new card/ }));
    fireEvent.change(screen.getByLabelText("Rupees per minute, starter pack on Sarvam Clear"), {
      target: { value: "5.5000" },
    });

    // Exact rupees and the percentage of the old rate, both derived without parsing either
    // figure into a JavaScript number.
    await screen.findByText(/up ₹0\.5000 \(10\.00%\)/);
  });

  it("names the earliest permitted date when the server says the card starts too soon", async () => {
    const { container } = renderOps(
      routes({
        [OPS_RATE_CARD_PATH]: fullCard(),
        [`POST ${OPS_RATE_CARD_PATH}`]: problem(422, {
          kind: "validation",
          type: "urn:calevate:validation/rate_card_too_soon",
          title: "This card starts too soon",
          detail: "a rate card starts at least 30 days out; that instant is 4 days away",
          retryable: false,
        }),
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /Record a new card/ }));
    fireEvent.change(screen.getByLabelText(/The day the new rates start/), {
      target: { value: "2026-10-20" },
    });
    fireEvent.change(screen.getByPlaceholderText(/Cartesia raised/), {
      target: { value: "moving the entry rung" },
    });
    fireEvent.change(screen.getByLabelText(/Type RECORD/), { target: { value: "RECORD" } });
    fireEvent.click(screen.getByRole("button", { name: /^Record card$/ }));

    await screen.findByText("This card starts too soon — nothing was saved");
    // THE DATE, not "pick a later one". `earliest_effective_from` is 15:14 IST on the 8th,
    // so midnight on the 8th is already past and the first day this deployment will accept
    // is the 9th — derived here, exactly as the picker's floor is.
    expect(container.textContent).toContain(
      "The earliest date this deployment will accept is 2026-10-09",
    );
    // And the server's own sentence, verbatim, beside it.
    expect(container.textContent).toContain("that instant is 4 days away");
  });

  it("offers the earliest permitted day as the picker's own floor", async () => {
    renderOps(routes({ [OPS_RATE_CARD_PATH]: fullCard() }));

    fireEvent.click(await screen.findByRole("button", { name: /Record a new card/ }));
    const picker = screen.getByLabelText(/The day the new rates start/) as HTMLInputElement;
    // The client-side floor and the sentence under it are one answer, and the server is
    // still the real gate — see `earliestPickableDate`.
    expect(picker.min).toBe("2026-10-09");
    expect(screen.getByText(/earliest day this deployment accepts is 2026-10-09/)).toBeTruthy();
  });
});

describe("a card that is scheduled but has not started", () => {
  it("lists it with what it moves, and can withdraw it with the server's own instant", async () => {
    const { calls, container } = renderOps(
      routes({
        [OPS_RATE_CARD_PATH]: fullCard({ pending: [SCHEDULED] }),
        [`POST ${OPS_RATE_CARD_PATH}/cancellations`]: {
          effective_from: SCHEDULED.effective_from,
          cancelled: true,
        },
      }),
    );

    await screen.findByText(/Scheduled changes/);
    // What it MOVES, not just what it is: the operator is deciding whether to let it stand.
    expect(container.textContent).toContain("up ₹0.5000 (10.00%)");

    fireEvent.click(screen.getByRole("button", { name: /Withdraw/ }));
    fireEvent.change(screen.getByPlaceholderText(/superseded by/), {
      target: { value: "recorded against the wrong quarter" },
    });
    fireEvent.change(screen.getByLabelText(/Type WITHDRAW/), { target: { value: "WITHDRAW" } });
    fireEvent.click(screen.getByRole("button", { name: /^Withdraw$/ }));

    const write = await waitForCall(calls, `POST ${OPS_RATE_CARD_PATH}/cancellations`);
    // THE SERVER'S OWN STRING, ECHOED — re-deriving it here is how the step-up header and
    // the row the API looks up stop naming the same instant.
    expect(write.body).toContain(`"effective_from":"${SCHEDULED.effective_from}"`);
    expect(write.headers["X-Confirm-Action"]).toBe(
      `cancel_rate_card:${SCHEDULED.effective_from}`,
    );
  });

  it("says nothing is scheduled rather than leaving a blank, and survives an API that omits the field", async () => {
    // The PREVIOUS BUILD's payload: no `pending` key at all. Reading it blindly would throw
    // inside render and take the whole configuration screen down — settings, model prices,
    // secrets — for a field that is merely absent.
    const older = fullCard();
    delete (older as { pending?: unknown }).pending;
    const { container } = renderOps(routes({ [OPS_RATE_CARD_PATH]: older }));

    await screen.findByText(/Nothing is scheduled/);
    // The rest of the panel is still there, which is the property being pinned.
    expect(container.textContent).toContain("Rate card — six packs, two voices");
    expect(screen.getByRole("button", { name: /Record a new card/ })).toBeTruthy();
  });
});

/* ── the seams where the arithmetic and the two date rules are cheapest to pin ───────── */

describe("what a rate moved by, computed without parsing money", () => {
  it("is exact in rupees and rounded only in the percentage", () => {
    expect(rateDelta("5.0000", "5.5000")).toEqual({
      direction: "up",
      amount: "0.5000",
      percent: "10.00",
    });
    expect(rateDelta("6.0000", "5.5000")).toEqual({
      direction: "down",
      amount: "0.5000",
      percent: "8.33",
    });
    // The case a float gets wrong: 0.1 + 0.2 arithmetic on these two produces
    // 0.30000000000000004 through `Number`, and this is exact.
    expect(rateDelta("4.10", "4.40")?.amount).toBe("0.30");
    expect(rateDelta("5.0000", "5.0000")?.direction).toBe("same");
  });

  it("says nothing at all about a box that is empty or half-typed", () => {
    // NOT "unchanged": that would be a claim about a value nobody has finished typing.
    expect(rateDelta("5.0000", "")).toBeNull();
    expect(rateDelta("5.0000", "5.")).toBeNull();
    expect(rateDelta("", "5.0000")).toBeNull();
  });
});

describe("the two date rules the step-up header rests on", () => {
  it("spells a picked day as midnight IST with the offset written in", () => {
    // NOT `toISOString()`. The server rebuilds the confirmation string from what it
    // parsed, and only this spelling round-trips through Python unchanged.
    expect(cardInstant("2026-10-20")).toBe("2026-10-20T00:00:00+05:30");
    expect(cardInstant("")).toBeNull();
    expect(cardInstant("20/10/2026")).toBeNull();
  });

  it("moves the floor to the next day unless the instant is itself midnight IST", () => {
    // 09:44 UTC is 15:14 IST — midnight on the 8th has already passed, so offering it
    // would offer a day the server refuses.
    expect(earliestPickableDate("2026-10-08T09:44:00Z")).toBe("2026-10-09");
    // Exactly midnight IST: that day is itself acceptable.
    expect(earliestPickableDate("2026-10-07T18:30:00Z")).toBe("2026-10-08");
    // No instant, no invented floor — the server is the gate either way.
    expect(earliestPickableDate(null)).toBeNull();
    expect(earliestPickableDate("not a date")).toBeNull();
  });
});

/** The first call matching a method-scoped key, once it has happened. */
async function waitForCall(
  calls: { method: string; path: string; body: string | null; headers: Record<string, string> }[],
  scoped: string,
) {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const found = calls.find((call) => `${call.method} ${call.path}` === scoped);
    if (found) return found;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`no request matched ${scoped}`);
}
