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
  modelOption,
  platformDefaultOption,
  type LlmModelOption,
  type OrganizationLlmDefaults,
  type SetOrganizationLlmDefaultIn,
} from "@/lib/api/llmModels";
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
 * `platform_cost_inr_per_minute` is what the CLIENT pays for a minute of a five-minute call on
 * that model. Moving a client between models therefore moves their unit economics, and an
 * operator doing it on a support call must see the two rates and the direction of the
 * change without arithmetic. So every option carries its price, and the summary above the
 * button states what a minute costs afterwards and how that compares with now.
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
          Which model this client&apos;s voice agents think with, and what a minute of it
          costs them. Every model here runs on the same speech stack — this changes the
          language leg only.
        </p>
      </div>

      <NoticeBox
        tone="warn"
        icon={<AlertTriangle className="h-5 w-5" />}
        title="This changes what the model costs US, not what the client is billed"
      >
        <ul className="mt-1 space-y-1 text-xs opacity-90">
          <li>
            The figure beside each model is{" "}
            <span className="font-medium">our own cost</span> to run a minute of a
            five-minute call — not a price this client pays. Their invoice is priced per
            MINUTE by their plan and does not move when the model does, so a dearer model
            is margin we give up, not revenue we gain. Nothing already billed is touched.
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
            colleague&apos;s and move this client&apos;s per-minute price without anyone
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
                <PerMinute rate={platform.platform_cost_inr_per_minute} />
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
                {chosenOption === undefined ? null : (
                  <PerMinute rate={chosenOption.platform_cost_inr_per_minute} />
                )}
              </>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-ink-faint">In effect</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {defaults.effective_default}
            {effectiveOption === undefined ? null : (
              <PerMinute rate={effectiveOption.platform_cost_inr_per_minute} />
            )}
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

/** A per-minute price, at the precision the server sent it. */
function PerMinute({ rate }: { rate: string }) {
  return (
    <span className="ml-1 font-normal text-ink-muted">
      · {formatRupeeRate(rate)}/min
    </span>
  );
}

/**
 * What this change does to the client's per-minute price, in words.
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
  const currentRate = modelOption(defaults.available, defaults.effective_default)
    ?.platform_cost_inr_per_minute;
  const projected = projectedModel(draft, defaults);
  const projectedRate = modelOption(defaults.available, projected)?.platform_cost_inr_per_minute;
  const priceChange = priceChangeSentence(currentRate, projectedRate);

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
        The figure is OUR cost to run a minute of a five-minute call, not a price this
        client pays — their plan prices minutes, not models. Comparisons
        are against what they are on today.
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
          <div className="mt-2 space-y-2">
            {defaults.available.map((option) => (
              <ModelOption
                key={option.model}
                option={option}
                checked={choice === option.model}
                disabled={!write.allowed}
                currentRate={currentRate}
                onPick={() => pick(option.model)}
              />
            ))}
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
                    : `Clears this client's own choice and puts them on ${platform.model} at ${formatRupeeRate(platform.platform_cost_inr_per_minute)}/min — and a future change to that default reaches them.`}
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
              <span className="text-ink-faint">A minute costs them</span> —{" "}
              {projectedRate === undefined
                ? "a price this screen cannot state; that model is not in the priced list."
                : `${formatRupeeRate(projectedRate)}${priceChange === null ? "" : `, ${priceChange}`}.`}
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
  currentRate,
  onPick,
}: {
  option: LlmModelOption;
  checked: boolean;
  disabled: boolean;
  currentRate: string | undefined;
  onPick: () => void;
}) {
  const change = priceChangeSentence(currentRate, option.platform_cost_inr_per_minute);
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
        <span className="mt-0.5 block text-ink-muted">
          {option.provider} · {formatRupeeRate(option.platform_cost_inr_per_minute)} per minute
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
