"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Info, Wrench } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatRupeeRate,
} from "@/components/ui";
import { useTenant } from "@/lib/api/admin";
import {
  adminLlmDefaultBlockReason,
  adminLlmDefaultConfirmation,
  isRetiredChoice,
  projectedModel,
  useAdminLlmDefaults,
  useSetAdminLlmDefault,
} from "@/lib/api/llmDefaults";
import {
  MODEL_UNAVAILABLE_FALLBACK,
  inForceSurcharge,
  modelOption,
  platformDefaultOption,
  providerLabel,
  unavailableReason,
  type LlmModelOption,
  type OrganizationLlmDefaults,
  type SetOrganizationLlmDefaultIn,
} from "@/lib/api/llmModels";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { compareRates, rateDifference } from "@/lib/llmRates";

import { useAdminAccess } from "@/app/admin/access";

/**
 * WHICH LANGUAGE MODEL THIS CLIENT'S AGENTS THINK WITH — the operator's half of the
 * control `/c/[slug]` gives the client.
 *
 * ## Why this is a screen and not a panel on the client's detail page
 *
 * The same reason `/feature-flags` and `/commercials` are: the decision needs THREE facts
 * beside it that a single row cannot carry — what the platform runs by default, what this
 * client has chosen for themselves, and what those two resolve to — plus a PRICE against
 * every option. A row showing only the resolved answer reads as a setting nobody set, and
 * a row showing only the price reads as a menu rather than as a change to a client's bill.
 * It is linked from the client's own screen, beside Commercials and Feature flags, because
 * that is where an operator is when they are asked for it.
 *
 * ## THIS IS A MONEY CONTROL, and the screen says so before it says anything else
 *
 * **IT MOVES BOTH SIDES OF THE MARGIN, AND THE TWO FIGURES ARE DIFFERENT NUMBERS.** This
 * screen is the ONE place both belong, because an operator changing a client's model is
 * the person who has to see them together:
 *
 * - `client_surcharge_inr_per_minute` — what this CLIENT is charged extra, per minute, for
 *   running that model. It is `plans.llm_model_surcharge` (D-455), `0` on the model their
 *   rate is struck at, and `0` on every plan until a founder sets one.
 * - `platform_cost_inr_per_minute` — what the language leg costs CALEVATE at list price,
 *   per minute of a five-minute call. OURS. It never appears on a client's own screen,
 *   because publishing a supplier cost to the account it is a margin on is a different
 *   mistake from hiding a price (`apps/api/billing/rates.py` argues both).
 *
 * **THIS SCREEN USED TO STATE THE OPPOSITE, TWICE.** Its own header said the figure "is
 * what the CLIENT pays" and its warning box said the change "costs US, not what the client
 * is billed" — contradicting each other, and after D-455 both are false. A dearer model
 * now moves the client's bill AND our cost, and the screen says so with both figures.
 *
 * The comparison is `lib/llmRates.ts` — digits, never `Number()` (hard rule 7). Nothing on
 * this screen multiplies, adds or rounds a rupee figure: the rates are the server's
 * strings, `formatRupeeRate` only prefixes the symbol, and the one subtraction is
 * `rateDifference`, which refuses rather than rounds.
 *
 * ## Inheriting is a DISTINCT, REACHABLE state — in both directions
 *
 * `default_llm_model: null` means this client has no choice of their own and follows ours,
 * so the next change to the platform default reaches them. A client explicitly pinned to
 * the model the platform default happens to be today is NOT the same thing, and the
 * difference only shows up the day we move the default. Both are rendered, and "follow the
 * platform default" is offered as its own choice so an operator can put a client back —
 * `/feature-flags` makes exactly this argument for a flag.
 *
 * ## §52, and the confirmation
 *
 * Loading is a skeleton. A failed read is a REFUSAL and the controls are withheld with it
 * — not disabled, not empty: this write REPLACES whatever is on file, and deciding while
 * the current state is unreadable can silently reverse a colleague's change and re-price a
 * client at the same time. There is no default position anywhere on this screen.
 *
 * The write is audited by the API. What stops it happening by accident is the console's
 * own idiom for a consequential admin action: a typed confirmation naming the act
 * (`admin/ops/page.tsx`'s `HALT`, the credits screen's payment reference), and here the
 * typed string is the model the client ENDS UP ON — see `adminLlmDefaultConfirmation` for
 * why the outcome rather than the selection, and `lib/api/llmDefaults.ts` for why no
 * `X-Confirm-Action` header is sent when the route asks for none.
 *
 * ## The permission is answered before the click
 *
 * `admin:tenants`, read from the admin realm's own identity (`useAdminAccess`) — never the
 * client realm's `useWriteAccess`, which refuses every permission to an impersonating
 * principal and would disable this control with a reason that is not true. D-177: the two
 * realms share no session logic.
 */
export default function LlmModelPage({
  params,
}: {
  // Next 15: `params` is a Promise in every page, unwrapped with React's `use()` in a
  // client component — nextjs.org/docs/app/api-reference/file-conventions/dynamic-routes.
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const defaults = useAdminLlmDefaults(tenantId);
  // The mutation lives HERE rather than inside the form, for the reason `/feature-flags`
  // and `/commercials` both record: a successful write invalidates the read, the form is
  // remounted by its key to pick up the new state, and a mutation held inside it would be
  // remounted with it — taking the confirmation down at the moment the write landed.
  const set = useSetAdminLlmDefault(tenantId);
  const write = useAdminAccess("admin:tenants", "change which model a client's agents use");

  if (tenantQuery.isLoading) return <Skeleton rows={6} />;
  // A 403, a 500 or a dropped connection is not "no such client".
  if (tenantQuery.error)
    return <ProblemNotice error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />;
  if (!tenant) return <EmptyState title="Client not found" />;

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {tenant.name}
        </Link>
        {/* `admin/layout.tsx` prints no page title (unlike the client shell), so this
            heading is the only name this screen has. Delete it if a title lands there. */}
        <h1 className="mt-1 text-xl font-semibold text-ink">Language model</h1>
        <p className="text-sm text-ink-muted">
          Which model this client&apos;s voice agents think with, what it adds to their
          bill, and what it costs us to run. Every model here runs on the same speech
          stack — this changes the language leg only.
        </p>
      </div>

      <NoticeBox
        tone="warn"
        icon={<AlertTriangle className="h-5 w-5" />}
        title="This changes what this client is billed, and what it costs us"
      >
        <ul className="mt-1 space-y-1 text-xs opacity-90">
          <li>
            Each model shows{" "}
            <span className="font-medium">what it adds to this client&apos;s bill</span>{" "}
            per minute — their plan&apos;s model surcharge, set on Commercials — and,
            separately, <span className="font-medium">what it costs us</span> to run.
            &ldquo;No extra charge&rdquo; means their plan quotes no surcharge, so a dearer
            model is margin we give up rather than revenue we gain. Nothing already billed
            is touched: a past call is priced from what the ledger recorded, not from this
            setting.
          </li>
          <li>
            It reaches every agent on this account that has not been given a model of its
            own. An agent with its own choice keeps that choice.
          </li>
          <li>
            The client can change this themselves from their own console. An operator
            setting it here is making the same decision on their behalf, and it is recorded
            against your admin account.
          </li>
        </ul>
      </NoticeBox>

      {defaults.error && (
        <ProblemNotice error={defaults.error} onRetry={() => defaults.refetch()} />
      )}

      {defaults.isLoading ? (
        <Skeleton rows={5} />
      ) : !defaults.data ? (
        /* The controls are WITHHELD rather than merely disabled, and the reason belongs on
           screen. This write replaces whatever is on file, so acting while the current
           state is unreadable can undo a colleague's change AND re-price a client in the
           same request — and unlike a compliance decision, nothing downstream refuses it.
           `/commercials` withholds its own form for the same reason. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot change the model while the current one is unreadable"
        >
          <p className="mt-1 text-xs opacity-90">
            We could not read what this client is on, or what the alternatives cost. A
            change replaces whatever is on file, so making one now could undo a
            colleague&apos;s and move this client&apos;s per-minute charge without anyone
            seeing it happen. Retry the read above; the controls come back with it.
          </p>
        </NoticeBox>
      ) : (
        <>
          <Resolution defaults={defaults.data} />
          <ChoiceForm
            // Remounted only when the STORED choice changes — an equal refetch keeps the
            // key, so a poll or a sibling write cannot wipe a confirmation an operator is
            // halfway through typing. Resetting state via `key` rather than an effect is
            // React's own answer (react.dev/learn/you-might-not-need-an-effect).
            //
            // The two states are PREFIXED rather than collapsed onto one sentinel: `null`
            // and a model whose id happened to BE that sentinel would otherwise share a
            // key, and the form would not remount on the one transition that changes every
            // sentence on it.
            key={
              defaults.data.default_llm_model === null
                ? "inherit"
                : `model:${defaults.data.default_llm_model}`
            }
            defaults={defaults.data}
            tenantName={tenant.name}
            set={set}
            write={write}
          />
          {set.error != null && <ProblemNotice error={set.error} />}
          {set.isSuccess && <Recorded sent={set.variables} defaults={defaults.data} />}
          <PerAgentNote />
        </>
      )}
    </div>
  );
}

/**
 * The three facts behind one answer — platform, client, resolved.
 *
 * `effective_default` is the SERVER's resolution and is never re-derived here: a client
 * with no choice of their own inherits ours, and which model that is changes when we
 * change it (`AZURE_OPENAI_DEFAULT_MODEL` is a live config switch). A browser resolving
 * the fallback itself would name last quarter's model on the screen an operator opened
 * precisely to check it.
 */
function Resolution({ defaults }: { defaults: OrganizationLlmDefaults }) {
  const platform = platformDefaultOption(defaults.available);
  const chosen = defaults.default_llm_model;
  const chosenOption = modelOption(defaults.available, chosen);
  const effectiveOption = modelOption(defaults.available, defaults.effective_default);

  return (
    <Card title="Where this client stands">
      <dl className="grid gap-3 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-ink-faint">Platform default</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {platform === undefined ? (
              "— this build names none"
            ) : (
              <>
                {platform.model}
                <PerMinute option={platform} />
              </>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-ink-faint">This client&apos;s own default</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {chosen === null ? (
              "None — follows the platform default"
            ) : (
              <>
                {chosen}
                {chosenOption === undefined ? null : <PerMinute option={chosenOption} />}
              </>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-ink-faint">In effect</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {defaults.effective_default}
            {effectiveOption === undefined ? null : <PerMinute option={effectiveOption} />}
            <span className="ml-1 font-normal text-ink-muted">
              ({chosen === null ? "from the platform default" : "from this client's own choice"})
            </span>
          </dd>
        </div>
      </dl>

      {isRetiredChoice(defaults) && (
        <NoticeBox
          tone="warn"
          icon={<Wrench className="h-5 w-5" />}
          title="This client is pinned to a model the platform no longer offers"
          className="mt-4"
        >
          <p className="mt-1 text-xs opacity-90">
            The choice on file is not in the list below, so nothing here can price it and
            it cannot be re-selected. Move this client onto a model that is offered, or
            clear the choice and put them back on the platform default.
          </p>
        </NoticeBox>
      )}
    </Card>
  );
}

/**
 * BOTH per-minute figures, at the precision the server sent them, labelled.
 *
 * They are different KINDS and an unlabelled pair on one line is how the two got confused
 * in this screen's own prose. `+₹x client` is what this account is charged EXTRA for the
 * model; `₹y ours` is what the language leg costs Calevate. A zero surcharge says so in
 * words for the reason the client picker does — the answer to "what does this cost them"
 * is "nothing", not a rupee amount of nothing.
 */
function PerMinute({ option }: { option: LlmModelOption }) {
  const free = compareRates(option.client_surcharge_inr_per_minute, "0") === "same";
  return (
    <span className="ml-1 font-normal text-ink-muted">
      ·{" "}
      {free
        ? "no extra charge"
        : `+${formatRupeeRate(option.client_surcharge_inr_per_minute)}/min client`}{" "}
      · {formatRupeeRate(option.platform_cost_inr_per_minute)}/min ours
    </span>
  );
}

/**
 * What this change does to a per-minute figure, in words. Used for BOTH of them.
 *
 * Deliberately kind-agnostic: it takes two decimal strings and says how the second differs
 * from the first, so the surcharge line and the cost line read identically and neither
 * needs its own arithmetic. WHICH figure a sentence is about is the caller's label, not
 * this function's business — the same separation `billing/service.py::overage_rungs` keeps
 * between a rung's money and its wording.
 *
 * A DIRECTION and a difference, never a recomputed total. `compareRates` answers from the
 * digits and `rateDifference` refuses rather than rounds, so a pair this console cannot
 * compare exactly renders as nothing at all instead of as "the same price" — which is a
 * claim, and one we would not have.
 */
function priceChangeSentence(from: string | undefined, to: string | undefined): string | null {
  const order = compareRates(to, from);
  if (order === "unknown") return null;
  if (order === "same") return "the same per-minute price as now";
  const difference = rateDifference(to, from);
  if (difference === null) return null;
  return `${formatRupeeRate(difference)} per minute ${order === "dearer" ? "more" : "less"} than now`;
}

/** The inherit row's description, referenced by `aria-describedby`. */
const INHERIT_DETAIL_ID = "llm-option-inherit-detail";

/**
 * The catalogue, gathered by provider in first-appearance order (D-456).
 *
 * The three declared legs — Azure OpenAI, OpenAI, Google Gemini — are presented on equal
 * footing: a group per provider, the server's ordering preserved. Kept beside the form
 * rather than inlined so the grouping reads as one expression and the render stays a map.
 */
function providerGroups(
  options: readonly LlmModelOption[],
): { key: string; label: string; options: LlmModelOption[] }[] {
  const groups: { key: string; label: string; options: LlmModelOption[] }[] = [];
  for (const option of options) {
    const group = groups.find((candidate) => candidate.key === option.provider);
    if (group) group.options.push(option);
    else
      groups.push({
        key: option.provider,
        label: providerLabel(option.provider),
        options: [option],
      });
  }
  return groups;
}

/** The catalogue, the choice, the consequence, and the typed confirmation. */
function ChoiceForm({
  defaults,
  tenantName,
  set,
  write,
}: {
  defaults: OrganizationLlmDefaults;
  tenantName: string;
  set: ReturnType<typeof useSetAdminLlmDefault>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  // `null` here is the CLIENT'S CHOICE being absent, not "unknown" — the two-way choice
  // the API takes. It starts at whatever is on file, so the form opens describing the
  // truth rather than proposing a change nobody asked for.
  const [choice, setChoice] = useState<string | null>(defaults.default_llm_model);
  const [typed, setTyped] = useState("");

  const draft: SetOrganizationLlmDefaultIn = { default_llm_model: choice };
  const blocked = adminLlmDefaultBlockReason(draft, typed, defaults);
  const confirmation = adminLlmDefaultConfirmation(draft, defaults);
  const platform = platformDefaultOption(defaults.available);
  // WHAT THIS CLIENT PAYS TODAY — through the shared rule, because an account FOLLOWING
  // the platform default is never surcharged however dear that default is
  // (`lib/api/llmModels.ts::inForceSurcharge`). Reading the resolved model's own row here
  // would show an operator a charge the meter will not apply.
  const currentSurcharge = inForceSurcharge(defaults);
  const currentCost = modelOption(defaults.available, defaults.effective_default)
    ?.platform_cost_inr_per_minute;
  const projected = projectedModel(draft, defaults);
  const projectedOption = modelOption(defaults.available, projected);
  // The PROJECTED surcharge is the outcome of the write: clearing the choice puts them
  // back on the platform default, which carries none whatever it resolves to.
  const projectedSurcharge =
    draft.default_llm_model === null
      ? "0"
      : (projectedOption?.client_surcharge_inr_per_minute ?? undefined);
  const surchargeChange = priceChangeSentence(currentSurcharge ?? undefined, projectedSurcharge);
  const costChange = priceChangeSentence(currentCost, projectedOption?.platform_cost_inr_per_minute);

  /*
   * THE MODEL CHOICE, DECLARED TO THE SCREEN ASSISTANT.
   *
   * ONE fillable control — the radio group — applied through `setChoice`, the same
   * setter every row already calls. The DOM is not touched: these rows are `sr-only`
   * radios inside choice cards, which is exactly the shape `lib/copilot/dom.ts` warns
   * about, and there is no reason to go near it when the state is right here.
   *
   * `""` IS THE PLATFORM DEFAULT, not an empty answer: the API's two-way choice is a
   * model id or `null`, and `null` means "follow whatever the platform is on". The
   * options list says so in words so the model is not left inferring it from a blank.
   *
   * UNAVAILABLE MODELS ARE STILL OFFERED AS OPTIONS AND STILL CARRY THEIR REASON, because
   * the useful question on this screen is often "why can I not pick Gemini 3?" — hiding
   * the row would leave the assistant unable to answer it. The SUBMIT is what refuses an
   * unavailable model, and that gate is untouched.
   *
   * The confirmation phrase is `writable: false`. It exists to make an operator state the
   * outcome in their own hand before a client's bill changes; a machine typing it would
   * turn the one deliberate step on this screen into a formality.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/llm-model",
    title: "Client's default AI model",
    realm: "admin",
    fields: [
      {
        id: "admin-llm-choice",
        label: "This client's default model",
        type: "select",
        value: choice ?? "",
        options: [
          { value: "", label: "Follow the platform default (no client-specific choice)" },
          ...defaults.available.map((option) => ({
            value: option.model,
            label: `${option.model} — ${option.provider}${
              unavailableReason(option) === null ? "" : ` (unavailable: ${unavailableReason(option)})`
            }`,
          })),
        ],
      },
      {
        id: "admin-llm-confirm",
        label: "Confirmation phrase",
        type: "text",
        value: typed,
        writable: false,
        help: "Typed by a human to confirm the change. Never machine-filled.",
      },
    ],
    facts: [
      { key: "client", label: "Client", value: tenantName },
      { key: "effective_default", label: "Model in force today", value: defaults.effective_default },
      {
        key: "surcharge_today",
        label: "Model surcharge on this plan today (₹ / minute)",
        value: currentSurcharge ?? "none",
      },
    ],
    apply: (items) => {
      const pickItem = items.find((item) => item.field_id === "admin-llm-choice");
      if (pickItem === undefined) return;
      if (pickItem.value === "") {
        pick(null);
        return;
      }
      // Only a model the catalogue carries. A free-text id would put this form into a
      // state whose radio group shows nothing selected while `draft` names a model.
      const picked = asText(pickItem.value);
      if (defaults.available.some((option) => option.model === picked)) {
        pick(picked);
      }
    },
  });

  const pick = (next: string | null) => {
    setChoice(next);
    // The confirmation names the OUTCOME, so a different selection means a different
    // string — carrying the old one over would let a phrase typed for one model confirm
    // a change to another.
    setTyped("");
    set.reset();
  };

  return (
    <Card title="Choose a model">
      <p className="-mt-2 text-sm text-ink-muted">
        Each row shows what the model ADDS to this client&apos;s bill per minute (their
        plan&apos;s model surcharge) and, separately, what a minute of a five-minute call
        costs US to run. Comparisons are against what they are on today.
      </p>

      <form
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (blocked === null) set.mutate(draft);
        }}
      >
        {/* The permission the route requires, answered before the click. */}
        <RestrictionNote reason={write.reason} />

        <fieldset>
          <legend className={FIELD_LABEL}>This client&apos;s default</legend>
          {/* GROUPED BY PROVIDER, ON EQUAL FOOTING (D-456). The client's own pickers do the
              same through `ModelPicker`; this console renders its own rows because it shows
              BOTH per-minute figures, so the grouping is repeated here rather than shared —
              a labelled sub-group per provider, each a `role="group"` so an operator on a
              screen reader hears the vendor once instead of on every row. "Follow the
              platform default" belongs to no provider and stays at the end, ungrouped, but
              inside the one radio group. */}
          <div className="mt-2 space-y-4">
            {providerGroups(defaults.available).map((group, index) => {
              const headingId = `admin-llm-provider-${index}`;
              return (
                <div key={group.key} role="group" aria-labelledby={headingId} className="space-y-2">
                  <p
                    id={headingId}
                    className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint"
                  >
                    {group.label}
                  </p>
                  {group.options.map((option) => (
                    <ModelOption
                      key={option.model}
                      option={option}
                      checked={choice === option.model}
                      disabled={!write.allowed}
                      currentSurcharge={currentSurcharge}
                      onPick={() => pick(option.model)}
                    />
                  ))}
                </div>
              );
            })}
            <label className="flex cursor-pointer gap-2 rounded-card border border-line p-3 text-xs hover:bg-black/5 dark:hover:bg-white/5">
              <input
                type="radio"
                name="llm-default"
                checked={choice === null}
                disabled={!write.allowed}
                onChange={() => pick(null)}
                className="mt-0.5"
                // Split for `ModelOption`'s reason — see the comment there.
                aria-label="Follow the platform default"
                aria-describedby={INHERIT_DETAIL_ID}
              />
              <span id={INHERIT_DETAIL_ID}>
                <span className="font-medium text-ink">Follow the platform default</span>
                <span className="mt-0.5 block text-ink-muted">
                  {platform === undefined
                    ? "Clears this client's own choice. This build names no platform default, so nothing here can say what they would fall back to."
                    : `Clears this client's own choice and puts them on ${platform.model} at no extra charge to them — following the platform default is never surcharged — and a future change to that default reaches them.`}
                </span>
              </span>
            </label>
          </div>
        </fieldset>

        {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON — blast radius first, then the money,
            then that it is recorded. The order `admin/ops/page.tsx` established: an
            operator who reads only the first line has read the part that matters. */}
        <div className="rounded-card border border-line bg-app p-3 text-xs text-ink-muted">
          <p className="font-medium text-ink">This will record, against {tenantName}:</p>
          <ul className="mt-1.5 space-y-1">
            <li>
              <span className="text-ink-faint">Their agents run on</span> —{" "}
              {projected === null
                ? "nothing this screen can name; there is no platform default to fall back to."
                : `${projected}, ${
                    draft.default_llm_model === null
                      ? "from the platform default, because their own choice is being cleared."
                      : "as their own choice, so a future change to the platform default does not reach them."
                  }`}
            </li>
            <li>
              <span className="text-ink-faint">They are charged extra</span> —{" "}
              {projectedSurcharge === undefined
                ? "a charge this screen cannot state; that model is not in the priced list."
                : compareRates(projectedSurcharge, "0") === "same"
                  ? `nothing per minute${surchargeChange === null ? "" : `, ${surchargeChange}`}.`
                  : `${formatRupeeRate(projectedSurcharge)} per minute${surchargeChange === null ? "" : `, ${surchargeChange}`}.`}
            </li>
            <li>
              <span className="text-ink-faint">It costs us</span> —{" "}
              {projectedOption === undefined
                ? "a cost this screen cannot state; that model is not in the priced list."
                : `${formatRupeeRate(projectedOption.platform_cost_inr_per_minute)} per minute of a five-minute call${costChange === null ? "" : `, ${costChange}`}.`}
            </li>
            <li>
              <span className="text-ink-faint">Scope</span> — every agent on this account
              that has not been given a model of its own. An agent with its own choice keeps
              it.
            </li>
            <li>
              <span className="text-ink-faint">Audit</span> — one entry, against the admin
              account sending this request. Taken from your session, not from this form.
              There is no undo; putting it back is another change and another entry.
            </li>
          </ul>
        </div>

        <div>
          {/* A persistent visible label, not a placeholder: the hint below explains the
              field, the label names it, and neither disappears when typing starts. */}
          <label htmlFor="llm-default-confirm" className={FIELD_LABEL}>
            {confirmation === null
              ? "Confirm"
              : `Type ${confirmation} to confirm`}
          </label>
          <input
            id="llm-default-confirm"
            value={typed}
            disabled={!write.allowed || confirmation === null}
            placeholder={confirmation ?? undefined}
            onChange={(event) => {
              setTyped(event.target.value);
              set.reset();
            }}
            className={`${FIELD} font-mono`}
          />
          <span className={FIELD_HINT}>
            The model this client ends up on — not the option you clicked, which is the
            same thing only when you are setting one explicitly. Typing it is what
            separates &ldquo;I meant this client, on this model&rdquo; from a mis-click on
            a row.
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={set.isPending || blocked !== null || !write.allowed}
            className={PRIMARY_BUTTON}
          >
            {set.isPending ? "Saving…" : "Save this model"}
          </button>
          {blocked && <span className="text-xs text-amber-700 dark:text-amber-400">{blocked}</span>}
        </div>
      </form>
    </Card>
  );
}

/**
 * One model in the catalogue, priced, and compared with what the client is on today.
 *
 * A model this platform has no deployment behind is SHOWN AND DISABLED, with the server's
 * own reason beside it — the instruction is `apps/api/agents/llm_routes.py`'s and the
 * argument is the same one `useAdminAccess` rests on: hiding the row leaves an operator
 * hunting for a model that has quietly vanished, and offering it hands them a 422. The
 * `is_available === false` test is explicit because an API build predating the field
 * reports `undefined`, which is "this deployment does not say" and must disable nothing.
 */
function ModelOption({
  option,
  checked,
  disabled,
  currentSurcharge,
  onPick,
}: {
  option: LlmModelOption;
  checked: boolean;
  disabled: boolean;
  /** What this client is charged extra TODAY — the row everything is compared against. */
  currentSurcharge: string | null;
  onPick: () => void;
}) {
  const change = priceChangeSentence(
    currentSurcharge ?? undefined,
    option.client_surcharge_inr_per_minute,
  );
  const undeployed = option.is_available === false;
  const describedBy = `llm-option-${option.model}-detail`;
  return (
    <label
      className={`flex gap-2 rounded-card border border-line p-3 text-xs ${
        undeployed
          ? "cursor-not-allowed opacity-60"
          : "cursor-pointer hover:bg-black/5 dark:hover:bg-white/5"
      }`}
    >
      <input
        type="radio"
        name="llm-default"
        checked={checked}
        disabled={disabled || undeployed}
        onChange={onPick}
        className="mt-0.5"
        // NAME AND DESCRIPTION SPLIT, and this is a deliberate departure from the wrapped
        // label the flag screen uses — measured rather than assumed. Text nodes concatenate
        // with NO separator in the accessible-name computation, so the wrapped form here
        // announces "gpt-4oazure-openai · ₹1.9200 per minuteCannot be selected — …": the
        // model id and the provider run together, and four sentences arrive as the control's
        // NAME. The rows on the flag screen carry two short sentences and survive it; a row
        // whose name is an id followed by a price and a refusal does not.
        //
        // So the name is the model id — what the operator is choosing and what they type
        // into the confirmation — and everything else is the DESCRIPTION, which is what
        // ARIA's radio pattern is for (w3.org/WAI/ARIA/apg/patterns/radio). The visual
        // layout is unchanged; only what a screen reader announces first is.
        aria-label={option.model}
        aria-describedby={describedBy}
      />
      <span id={describedBy}>
        <span className="font-medium text-ink">{option.model}</span>
        {/* The provider is the group heading above this row now (D-456), so the money line
            leads with what the operator came for — both per-minute figures. */}
        <span className="mt-0.5 block text-ink-muted">
          {compareRates(option.client_surcharge_inr_per_minute, "0") === "same"
            ? "no extra charge to them"
            : `+${formatRupeeRate(option.client_surcharge_inr_per_minute)} per minute to them`}{" "}
          · {formatRupeeRate(option.platform_cost_inr_per_minute)} per minute to us
          {option.is_platform_default ? " · what the platform runs by default" : ""}
        </span>
        {/* Only when there IS a comparison to make. `priceChangeSentence` returns null
            rather than "the same price" for a pair it cannot compare exactly, so a rate
            this console does not understand renders as nothing instead of as a claim.
            "Choosing this pins the client" is deliberately NOT repeated per row — it is
            the same sentence on every option, and the summary below says it once, about
            the option actually selected. */}
        {change === null ? null : (
          <span className="mt-0.5 block text-ink-faint">{change}</span>
        )}
        {undeployed && (
          <span className="mt-0.5 block font-medium text-amber-700 dark:text-amber-400">
            {/* One sentence for a row the platform cannot run, shared with the client
                picker's rendering of the same fact: this was written out here and again
                in `MODEL_UNAVAILABLE_FALLBACK`, and two spellings of one refusal is how
                an operator and the client they are on the phone to end up reading
                different explanations of the same greyed-out row. */}
            Cannot be selected — {option.unavailable_reason ?? MODEL_UNAVAILABLE_FALLBACK}
          </span>
        )}
      </span>
    </label>
  );
}

/**
 * What was just written, said from what was SENT.
 *
 * Deliberately not read out of the mutation's response body: the contract this lane was
 * given names the request and stops, so a screen that rendered `set.data.effective_default`
 * would be asserting a shape nobody agreed to. The panel above is the SERVER's answer — it
 * is re-read the moment this returns — and this sentence is only a receipt for the request
 * the operator made.
 */
function Recorded({
  sent,
  defaults,
}: {
  sent: SetOrganizationLlmDefaultIn | undefined;
  defaults: OrganizationLlmDefaults;
}) {
  if (sent === undefined) return null;
  const landed = projectedModel(sent, defaults);
  return (
    <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
      <p className="text-xs">
        {sent.default_llm_model === null ? (
          <>
            Cleared. This client follows the platform default again
            {landed === null ? "" : ` — ${landed}`}, and a future change to it reaches them.
          </>
        ) : (
          <>
            Saved. This client&apos;s agents default to{" "}
            <span className="font-medium">{sent.default_llm_model}</span>, whatever the
            platform default becomes.
          </>
        )}{" "}
        The panel above has been re-read from the server; it is the record, not this line.
      </p>
    </NoticeBox>
  );
}

/**
 * The one thing this screen deliberately does NOT offer: a per-agent override.
 *
 * `llm_model` on an agent is the client's own control (`lib/api/llmModels.ts`), and D-21's
 * boundary is about what an agent SAYS and CAPTURES rather than what it costs. An operator
 * reaching for a per-agent model from here is usually about to solve an account-level
 * problem one agent at a time; the note points them at the right control instead.
 */
function PerAgentNote() {
  return (
    <NoticeBox tone="neutral" icon={<Info className="h-5 w-5" />} title="Per agent">
      <p className="mt-1 text-xs opacity-90">
        One agent can be put on a different model from the rest. That choice lives on the
        agent and belongs to the client, and it is not made from here — this page sets the
        account-wide default that every agent without a choice of its own follows.
      </p>
    </NoticeBox>
  );
}
