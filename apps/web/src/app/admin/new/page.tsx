"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  CheckCircle2,
  KeyRound,
  ListChecks,
  Mail,
  Plus,
  TriangleAlert,
} from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  TermGloss,
  formatIST,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { ActionButton } from "@/components/actionButton";
import { ApiProblem } from "@/lib/api/client";
// The SAME derivation the self-serve form previews with, imported rather than re-typed:
// this wizard carried its own inline copy of the regex, and two previews of one server
// rule is how the two screens end up disagreeing about what will be submitted.
import { previewSlug, slugIsDerivable } from "@/lib/api/signup";
import {
  useCreateTenant,
  useInvite,
  useResendTenantInvitation,
  useRevokeTenantInvitation,
  useTenantInvitations,
  type CreateOrgIn,
  type CreateOrgOut,
} from "@/lib/api/admin";
import {
  blockerCopy,
  draftFromState,
  useIntake,
  useUnfinishedOnboardings,
  type IntakeDraft,
  type UnfinishedOnboarding,
} from "@/lib/api/intake";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { IntakeStep } from "./IntakeStep";
import { WIZARD_LANGUAGES } from "./languages";
import { examplesFor } from "@/lib/verticalExamples";

/**
 * New-client wizard, steps 1, 3 and 8 (FLOWS §1).
 *
 * Two of the middle steps are still deliberately absent rather than stubbed: number
 * provisioning (6) and the test-call gate (7) both depend on the Bolna pilot, and a
 * greyed-out button that does nothing is worse than a documented gap — so the checklist
 * in step 8 says what is still manual instead.
 *
 * **Step 3 is no longer one of them.** Intake had been deferred on the grounds that it
 * "needs client #1 in the room", which is a real argument against inventing a field list
 * and no argument at all against building one FLOWS §1 already names. The API landed in
 * BUILD-LOG §45 with those eight fields and nothing in either realm called it; `IntakeStep`
 * is the caller. What genuinely needs client #1 is the CONTENT of a clinic's answers, not
 * the question list.
 *
 * ## What this pass changed
 *
 * Restyled to the console's design language (globals.css tokens, `Card`, `NoticeBox`,
 * lucide icons as affordances) with the field, button and radio-card shapes COPIED
 * VERBATIM from `/c/[slug]/campaigns` — see the constants below. Three things that were
 * wrong underneath the old styling are fixed rather than carried across:
 *
 * - **The success panel described the account from what was TYPED, not from what came
 *   back.** It read "{name} created as /c/{created.slug}", mixing a local input with a
 *   server field in one sentence. The account is now named by the server's own `slug` and
 *   `status`; the typed name is offered separately as what was submitted. The gate on the
 *   panel was already right (`onSuccess`) and stays: nothing here claims a creation that
 *   has not answered.
 * - **A stale invite token could sit under a failed second attempt.** The token is a
 *   single-use credential shown once. Minting one for `owner@a`, then failing to mint one
 *   for `owner@b`, left `owner@a`'s token on screen beside a red error — an operator
 *   copying "the token" would send the wrong person's. It is cleared at submit.
 *   **The token is no longer rendered at all (D-198):** it is mailed to the invitee and
 *   `InviteOut` carries `delivery` instead, so the panel confirms an address rather than
 *   displaying a credential. The clear-at-submit rule survives, pointed at that address.
 * - **`language as "te-IN"` was a cast that lied**: the state was a bare `string`, and the
 *   cast made any string typecheck as the API's three-member enum. The state now IS the
 *   generated union, so a language this API does not accept fails the build instead of the
 *   request.
 *
 * There is no permission PREVIEW on the two writes THIS file makes, which is a choice
 * rather than a limitation: `useAdminAccess` (`@/app/admin/access`) can be asked from
 * anywhere since `GET /v1/admin/me` landed, and the shell already gates the "New client"
 * nav entry on the same `admin:tenants` both of them require (admin/routes.py) — so a
 * role that may not create clients meets the refusal one step earlier, in the sidebar,
 * where it is not standing over a filled-in form. What stays here is the complementary
 * mechanism, and it is not a substitute for the preview: a refusal that HAS arrived, for
 * any reason, disables the control that caused it with the server's own words rather than
 * inviting a second identical refusal.
 *
 * The intake step DOES preview, and the difference is not inconsistency: its route
 * carries a DIFFERENT permission (`agents:write`, not `admin:tenants`), so reaching this
 * screen at all says nothing about whether that submit will be allowed — and the form
 * behind it is forty controls long, which is the worst possible place to learn.
 *
 * NO `<h1>`: the admin shell derives the page title from the same nav list it renders,
 * so a heading here would print "New client" twice.
 */

/**
 * The screen's field and control styling, written once.
 *
 * COPIED VERBATIM from `/c/[slug]/campaigns` — same strings, same order, including the
 * radio-as-card trio and its reasoning. Its author flagged them as belonging in `ui.tsx`
 * once a second screen needed them; this is that second screen, and copying identically
 * is what makes the promotion a lift rather than a reconciliation. They stay local until
 * someone moves all of them at once.
 */

/**
 * A radio rendered as a card.
 *
 * Selection is a brand ring plus a tick, NOT a brand fill. `--brand-soft` has no dark
 * value by design (it is the medallion tint, and `ui.tsx` uses it with a fixed dark-green
 * foreground), so a filled card would need its own text colour in each theme to stay
 * readable — a two-colour pair that the next person to add an option will get wrong. A
 * ring changes nothing about the text.
 */
/*
 * The FOCUS ring, on the card rather than on the input.
 *
 * The `<input type="radio">` inside each of these cards is `sr-only`, which deletes the
 * browser's own focus indicator — WCAG 2.4.7 Focus Visible (AA), failure technique F78,
 * exactly. `has-[:focus-visible]` puts it back on the label that hides it, so a keyboard
 * user tabbing into the group can see where they are; `focus-visible` rather than `focus`
 * so a mouse click does not leave a ring behind. `ring-offset-2` separates it from
 * `CHOICE_ON`'s selection ring, so "focused" and "chosen" stay two readable states.
 * `tests/contrast.test.ts` guards this at the source, because axe cannot evaluate a focus
 * indicator and jsdom has no layout to evaluate one in.
 */
const CHOICE_CARD =
  "relative block cursor-pointer rounded-card border p-3 transition-colors " +
  "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app";
const CHOICE_ON = "border-brand ring-1 ring-brand bg-surface";
const CHOICE_OFF = "border-line bg-surface hover:border-ink-faint";

/**
 * The vertical templates, with what choosing one actually DOES.
 *
 * The values are the API's own enum (`CreateOrgIn["vertical_template"]`), so a template
 * the API stops accepting fails this build rather than the operator's first request. The
 * hints are the reason the choice matters: it seeds the extraction schema, which becomes
 * the client's CRM columns — a wrong pick is a schema someone edits later, not a label.
 */
const VERTICALS: { value: CreateOrgIn["vertical_template"]; label: string; hint: string }[] = [
  { value: "clinic", label: "Clinic", hint: "Appointments, department, patient name" },
  { value: "real_estate", label: "Real estate", hint: "Budget, locality, site-visit interest" },
  { value: "insurance", label: "Insurance", hint: "Policy type, renewal date, sum assured" },
  { value: "education", label: "Education", hint: "Course, batch, admission stage" },
  { value: "custom", label: "Custom", hint: "Minimal schema — build the fields by hand" },
];

/**
 * A refusal we have already received, as a reason to stop offering the control.
 *
 * Only 403. Everything else — a validation error, a duplicate slug, a dropped connection
 * — is a reason to try again with different input, and disabling the button on those
 * would strand the operator with no way forward. A permission refusal is not going to
 * change on the second click, so the control says so and the `ProblemNotice` beside it
 * carries the server's full sentence.
 */
function refusalReason(error: unknown): string | null {
  if (error instanceof ApiProblem && error.status === 403) {
    return error.remediation ?? error.message;
  }
  return null;
}

/**
 * The account the wizard's later steps are about, however it got here.
 *
 * Two motions reach step 2 now — creating an account, and RESUMING one whose intake was
 * left half-answered (FLOWS §1: "draft state saved at every step (resume anytime)") —
 * and they carry different evidence. `CreateOrgOut` is what the creation returned;
 * `UnfinishedOnboardingOut` is a row off the resume list. This is their intersection,
 * plus `origin`, because the panels below must not tell an operator resuming a
 * three-week-old onboarding that an account was just created.
 *
 * Modelling it as a union of the two wire types was the alternative, and it pushes a
 * discriminant check into every reader for two shapes that agree on everything the
 * steps use. The narrow record is the same value both motions already hold.
 */
interface WizardAccount {
  id: string;
  slug: string;
  status: string;
  agent_id: string;
  origin: "created" | "resumed";
  /** The business's name as the SERVER holds it. `null` for a fresh creation, where
   *  `CreateOrgOut` carries no name and what was typed is offered separately as what
   *  was submitted — a distinction this screen already draws and keeps. */
  name: string | null;
  /**
   * The trade, taken from the SERVER on both paths.
   *
   * The intake step fills forty placeholders from it (`lib/verticalExamples.ts`), and
   * reading it off the response rather than off the radio button in this component is
   * what makes a RESUMED wizard show the same examples as a fresh one. Before this, the
   * resume path had nothing to read.
   */
  vertical: string;
}

const createdAccount = (created: CreateOrgOut): WizardAccount => ({
  id: created.id,
  slug: created.slug,
  status: created.status,
  agent_id: created.agent_id,
  origin: "created",
  name: null,
  vertical: created.vertical_template,
});

const resumedAccount = (row: UnfinishedOnboarding): WizardAccount => ({
  id: row.tenant_id,
  slug: row.slug,
  // The resume list is exactly "still in onboarding", so this is a fact about the row
  // rather than a default: `unfinished_onboardings` filters on it in SQL.
  status: "onboarding",
  agent_id: row.agent_id,
  origin: "resumed",
  name: row.name,
  vertical: row.vertical_template,
});

export default function NewClientPage() {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [vertical, setVertical] = useState<CreateOrgIn["vertical_template"]>("clinic");
  const [language, setLanguage] = useState<CreateOrgIn["language"]>("te-IN");
  const [email, setEmail] = useState("");
  // The ONLY evidence that an account exists. Set from the creation mutation's
  // `onSuccess` or from a row the resume list returned, and from nowhere else — every
  // sentence in step 2 reads off this object, so the screen structurally cannot report
  // an account the server did not describe.
  const [created, setCreated] = useState<WizardAccount | null>(null);
  /**
   * Which of the two POST-CREATION steps is on screen.
   *
   * It lives here rather than in `AfterCreate` for one reason: the step counter above is
   * derived from it, and a counter that read a copy of this state would eventually
   * disagree with the panel underneath it. Same rule the admin shell applies to its nav
   * (one list drives both the sidebar and the header title).
   *
   * The intake ANSWERS deliberately do not live here — see `AfterCreate`.
   */
  const [step, setStep] = useState<"intake" | "invite">("intake");

  /*
   * STEP 1, DECLARED TO THE SCREEN ASSISTANT.
   *
   * Per-field setters, not a draft object and not the DOM: this component holds five
   * loose `useState` scalars, so `apply` is five typed calls and nothing about it can be
   * defeated by how a control listens for events. The two radio groups are `select`s
   * with the SAME option lists the cards are rendered from, so the assistant cannot
   * offer a vertical or a language this build does not ship — and the guard on the way
   * in is a lookup in that list rather than a cast, because a cast here would put a
   * value the API rejects into a control that then submits it.
   *
   * `null` once an account exists (steps 2 and 3): the fields below are no longer on
   * screen, and step 2 declares itself from inside `IntakeStep`.
   */
  useCopilotSurface(
    created !== null
      ? null
      : {
          route: "/admin/new",
          title: "New client — account details",
          realm: "admin",
          fields: [
            {
              id: "new-client-name",
              label: "Business name",
              type: "text",
              value: name,
              help: "At least 2 characters. The client's own trading name.",
            },
            {
              id: "new-client-slug",
              label: "Slug",
              type: "text",
              value: slug,
              help: "3-40 characters of a-z, 0-9 and -. Appears in every client URL and cannot be changed later. Left blank it is derived from the business name.",
            },
            {
              id: "new-client-vertical",
              label: "Business type",
              type: "select",
              value: vertical,
              options: VERTICALS.map((option) => ({ value: option.value, label: option.label })),
              help: "Sets up the lead fields the agent collects, which become this client's CRM columns.",
            },
            {
              id: "new-client-language",
              label: "Primary language",
              type: "select",
              value: language,
              options: WIZARD_LANGUAGES.map((option) => ({
                value: option.value,
                label: option.label,
              })),
            },
            {
              id: "new-client-email",
              label: "Billing email",
              type: "text",
              value: email,
              // Personal data: an operator is typing a named human's address. It leaves
              // as «EMAIL_1» and comes back as itself (`lib/copilot/redaction.ts`).
              personal: "email",
              help: "Where hot-lead alerts and invoices go.",
            },
          ],
          apply: (items) => {
            for (const item of items) {
              if (item.field_id === "new-client-name") setName(asText(item.value));
              else if (item.field_id === "new-client-slug") setSlug(asText(item.value));
              else if (item.field_id === "new-client-email") setEmail(asText(item.value));
              else if (item.field_id === "new-client-vertical") {
                const option = VERTICALS.find((row) => row.value === item.value);
                if (option) setVertical(option.value);
              } else if (item.field_id === "new-client-language") {
                const option = WIZARD_LANGUAGES.find((row) => row.value === item.value);
                if (option) setLanguage(option.value);
              }
            }
          },
        },
  );

  const createTenant = useCreateTenant();
  const refusal = refusalReason(createTenant.error);
  const valid = useFormValidation();

  const derivedSlug = slug || previewSlug(name);
  // The server REFUSES to invent a URL for a name it cannot fold to ASCII
  // (`slug_not_derivable`). Every character of `మా క్లినిక్` is outside `[a-z0-9]`, so on
  // a Telugu-first product this is the ordinary case: the operator is asked for the slug
  // here, before the POST, rather than being handed the refusal afterwards. The old
  // behaviour was worse than a refusal — the server substituted the constant `client`,
  // so the FIRST such account silently took `/c/client` and the second was told its slug
  // was taken.
  const mustChooseSlug = name.trim().length > 0 && !slugIsDerivable(derivedSlug);

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <p className="mt-0.5 text-sm text-ink-muted">
          Creates the account, its data-retention rules, a draft receptionist, and the
          lead fields for its CRM, based on the business type you choose.
        </p>
        <p className="mt-2 text-xs font-medium uppercase tracking-wide text-ink-faint">
          {!created
            ? "Step 1 of 3 — account details"
            : step === "intake"
              ? "Step 2 of 3 — business intake"
              : "Step 3 of 3 — invite the owner"}
        </p>
      </div>

      {!created && <ResumePanel onResume={(row) => setCreated(resumedAccount(row))} />}

      {!created ? (
        <Card title="Account details">
          <form
            className="space-y-5"
            noValidate
            onSubmit={valid.onSubmit(() => {
              createTenant.mutate(
                {
                  name,
                  // Sent only when there is one. An empty string here was falsy on the
                  // server too, so it fell through to the same derivation — but sending
                  // a value we do not have is how a caller ends up trusting it.
                  slug: derivedSlug || null,
                  vertical_template: vertical,
                  language,
                  billing_email: email.trim() || null,
                },
                { onSuccess: (account) => setCreated(createdAccount(account)) },
              );
            })}
          >
            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>Business name</span>
              <input
                {...valid.field("name", "Give this client its business name.")}
                /* AFTER the spread, deliberately: `field()` supplies an id of its own and
                   the last one wins, and this one is the COPILOT field id (see
                   `useCopilotSurface` above) — what the "filled" outline is drawn on.
                   Overriding it costs nothing: the wrapping label associates the control,
                   and `field()`'s message is tied to it by `aria-describedby`, which names
                   the message's own id rather than the control's. */
                id="new-client-name"
                required
                minLength={2}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={examplesFor(vertical).orgName}
                className={FIELD}
              />
              {valid.error("name")}
            </label>

            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>Slug</span>
              <input
                {...valid.field("slug", "Choose the web address for this client.")}
                id="new-client-slug"
                required={mustChooseSlug}
                minLength={mustChooseSlug ? 3 : undefined}
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder={previewSlug(name) || examplesFor(vertical).orgSlug}
                className={`${FIELD} font-mono`}
              />
              {valid.error("slug")}
              <span className={FIELD_HINT}>
                Appears in every client URL and cannot be changed once the client is
                created.{" "}
                {mustChooseSlug ? (
                  <span className="text-ink">
                    We cannot build a web address out of that business name, so please
                    choose one — 3-40 characters of a-z, 0-9 and -.
                  </span>
                ) : (
                  <>
                    Left blank, we send <MonoValue>{derivedSlug || "—"}</MonoValue>.
                  </>
                )}
              </span>
            </label>

            <fieldset>
              <legend className={FIELD_LABEL}>Business type</legend>
              <p className="mt-1 text-xs text-ink-faint">
                Sets up the lead fields the agent collects, which become this
                client&apos;s CRM columns.
              </p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {VERTICALS.map((option) => (
                  <label
                    key={option.value}
                    className={`${CHOICE_CARD} ${
                      vertical === option.value ? CHOICE_ON : CHOICE_OFF
                    }`}
                  >
                    <input
                      type="radio"
                      name="vertical"
                      className="sr-only"
                      checked={vertical === option.value}
                      onChange={() => setVertical(option.value)}
                    />
                    {vertical === option.value && (
                      <CheckCircle2
                        aria-hidden
                        className="absolute right-2 top-2 h-4 w-4 text-brand"
                      />
                    )}
                    <span className="block pr-6 text-sm font-semibold text-ink">
                      {option.label}
                    </span>
                    <span className="mt-0.5 block text-xs text-ink-faint">{option.hint}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset>
              <legend className={FIELD_LABEL}>Primary language</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                {WIZARD_LANGUAGES.map((option) => (
                  <label
                    key={option.value}
                    className={`${CHOICE_CARD} ${
                      language === option.value ? CHOICE_ON : CHOICE_OFF
                    }`}
                  >
                    <input
                      type="radio"
                      name="language"
                      className="sr-only"
                      checked={language === option.value}
                      onChange={() => setLanguage(option.value)}
                    />
                    {language === option.value && (
                      <CheckCircle2
                        aria-hidden
                        className="absolute right-2 top-2 h-4 w-4 text-brand"
                      />
                    )}
                    <span className="block pr-6 text-sm font-semibold text-ink">
                      {option.label}
                    </span>
                    {option.hint && (
                      <span className="mt-0.5 block text-xs text-ink-faint">{option.hint}</span>
                    )}
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>Billing email</span>
              <input
                {...valid.field("email", "Enter a billing address, or leave it blank.")}
                id="new-client-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="owner@business.com"
                className={FIELD}
              />
              {valid.error("email")}
              <span className={FIELD_HINT}>
                Where hot-lead alerts and invoices go. Offered again as the invite address
                in step 3.
              </span>
            </label>

            {createTenant.error && <ProblemNotice error={createTenant.error} />}

            {/* The shared primary CTA: the label ("Create client") stays mounted so the
                button's accessible name never flickers to "Creating…" mid-request, and the
                spinner is carried by `loading`. `disabled` keeps its two non-pending
                reasons; ActionButton adds `loading` to them, so the effective disabled
                logic is unchanged. */}
            <ActionButton
              type="submit"
              title={refusal ?? undefined}
              loading={createTenant.isPending}
              /* The name's minimum length is answered at the field now, so the button
                 stays live and a press produces a sentence rather than nothing. What is
                 left is `refusal`, which is not about an answer on this form. */
              disabled={Boolean(refusal)}
            >
              <Building2 aria-hidden className="h-4 w-4" />
              Create client
            </ActionButton>
            {refusal && <p className="text-xs text-ink-muted">{refusal}</p>}
          </form>
        </Card>
      ) : (
        <AfterCreate
          created={created}
          submittedName={name}
          defaultEmail={email}
          step={step}
          onStep={setStep}
        />
      )}
    </div>
  );
}

/**
 * Where an unfinished onboarding is picked back up — FLOWS §1's "resume anytime", which
 * had no surface at all while nothing could be saved partially.
 *
 * ## Why the list is HERE
 *
 * Starting an onboarding and continuing one are the same task, so they are the same
 * screen: the operator who wants to finish yesterday's client opens "New client",
 * exactly as they did to begin it, and the wizard picks up from the row's tenant and
 * agent ids. The considered alternative was the tenant DIRECTORY, which is the roster
 * of every account and deliberately "stays dumb: counts, not judgements"
 * (`admin.service.tenant_overview`) — putting four onboarding columns there would make
 * every finished client render them empty, and would send an operator to a second
 * screen to do a thing this one exists for. A standalone `/admin/onboarding` page was
 * the third option and is a fourth place to look for the same work.
 *
 * ## BUILD-LOG §52, and why it bites hard on THIS list
 *
 * loading is a skeleton; a failed read is a REFUSAL. "No unfinished onboardings" over a
 * 503 is the worst sentence on this page: it tells an operator their half-finished
 * client is not waiting for them, which is the one thing they came here to check — and
 * the next thing they do is create the account again, under a slug the first attempt
 * already took. The empty state is rendered ONLY for an answered, genuinely empty list.
 */
function ResumePanel({ onResume }: { onResume: (row: UnfinishedOnboarding) => void }) {
  const unfinished = useUnfinishedOnboardings();

  if (unfinished.isError) {
    return (
      <Card title="Unfinished onboardings">
        <ProblemNotice error={unfinished.error} onRetry={() => void unfinished.refetch()} />
        <p className="mt-3 text-xs text-ink-muted">
          We could not read which onboardings are unfinished, so this list is not saying
          there are none. Retry before creating an account — a client you already started
          holds their slug, and it is immutable.
        </p>
      </Card>
    );
  }

  if (unfinished.isPending) {
    return (
      <Card title="Unfinished onboardings">
        <Skeleton rows={2} />
      </Card>
    );
  }

  if (unfinished.data.length === 0) return null;

  return (
    <Card title="Unfinished onboardings">
      <p className="-mt-2 text-xs text-ink-muted">
        Accounts you started but never finished, most recently worked on first. Picking
        one reopens its intake with whatever was saved.
      </p>
      <ul className="mt-4 space-y-2">
        {unfinished.data.map((row) => (
          <li
            key={row.tenant_id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-line bg-app p-3"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-ink">{row.name}</p>
              <p className="mt-0.5 text-xs text-ink-faint">
                <MonoValue>/c/{row.slug}</MonoValue>
                {" · "}
                {/* Two different states, said differently. A never-opened intake is not
                    a zero and not "saved never"; it is an account whose step 3 nobody
                    has started, which is what the server's `null` means. */}
                {row.draft_saved_at
                  ? `draft saved ${formatIST(row.draft_saved_at)}`
                  : `created ${formatIST(row.created_at)} — intake never opened`}
              </p>
              {row.blockers.length > 0 && (
                <p className="mt-1 text-xs text-ink-muted">
                  Still needed: {row.blockers.map(blockerCopy).join(" ")}
                </p>
              )}
            </div>
            <button type="button" onClick={() => onResume(row)} className={SECONDARY_BUTTON}>
              Resume
              <ArrowRight aria-hidden className="h-4 w-4" />
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/**
 * Everything after the account exists: the confirmation, then step 3, then step 8.
 *
 * ## Why the intake ANSWERS live here and not in `IntakeStep`
 *
 * The wizard's two remaining steps swap one panel for the other, so `IntakeStep` unmounts
 * the moment an operator walks forward to the invite — and a form that lost forty answers
 * on the way to a button and back would be a worse defect than the missing step it
 * replaced. The draft is therefore held one level ABOVE the swap, and `IntakeStep` is a
 * controlled component. The mutation stays inside it on purpose: a submit's outcome
 * belongs to the visit that made it, and the durable "this has been submitted" comes back
 * from the server on `submitted_at` rather than from a notice we kept alive.
 *
 * ## Seeding the draft from the prefill, during render
 *
 * `draft === null` means "the GET has not answered yet", and it is the ONE thing that
 * keeps a blank form off the screen while the answers are still in flight. It is filled
 * during render rather than in an effect — React's own documented answer to "adjust state
 * when something changes" (react.dev/learn/you-might-not-need-an-effect); an effect would
 * paint an empty form for one frame first, which on a failed-then-retried read is exactly
 * the empty form BUILD-LOG §52 is about.
 *
 * It seeds ONCE. After a submit the query is invalidated and comes back changed, and
 * re-seeding then would throw away whatever the operator has typed since — the server's
 * copy is not more current than the form that produced it.
 */
function AfterCreate({
  created,
  submittedName,
  defaultEmail,
  step,
  onStep,
}: {
  created: WizardAccount;
  submittedName: string;
  defaultEmail: string;
  step: "intake" | "invite";
  onStep: (step: "intake" | "invite") => void;
}) {
  // `created.agent_id` is the draft receptionist the creation made — the agent whose
  // prompt and knowledge base the intake writes. It comes from the SERVER's response, so
  // this cannot address a step at an agent that was never created.
  const intake = useIntake(created.id, created.agent_id);
  const [draft, setDraft] = useState<IntakeDraft | null>(null);
  // The primary language comes from the response now, not from step 1's local state:
  // a RESUMED account never went through step 1 in this browser, so the only honest
  // source for "which language does this agent answer in" is the agent's own row.
  if (draft === null && intake.data) setDraft(draftFromState(intake.data));

  return (
    <div className="space-y-4">
      {/* Above BOTH steps, because it is a standing fact about the account rather than
          part of either one — and it reads off the server's own `slug` and `status`.
          A RESUMED account was not created just now and must not say it was: the two
          headings are the same fact ("this is the account the steps below are about")
          told truthfully about two different moments. */}
      <NoticeBox
        tone="ok"
        icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
        title={created.origin === "created" ? "Account created" : `Resuming ${created.name}`}
      >
        <p className="mt-1">
          Live at <MonoValue className="font-semibold">/c/{created.slug}</MonoValue>, status{" "}
          <span className="font-semibold">{created.status}</span>.{" "}
          {created.origin === "created" ? (
            <>
              Retention policies, a draft inbound receptionist and an extraction schema are
              in place. The agent is <strong>draft</strong> — nothing is client-visible
              until it is published.
            </>
          ) : (
            <>
              The intake below is prefilled from what was saved for this client. The agent
              is still <strong>draft</strong> — nothing is client-visible until it is
              published.
            </>
          )}
        </p>
        {created.origin === "created" && submittedName && (
          <p className="mt-1 text-xs">Submitted as &ldquo;{submittedName}&rdquo;.</p>
        )}
      </NoticeBox>

      {step === "intake" ? (
        <IntakeStep
          tenantId={created.id}
          agentId={created.agent_id}
          vertical={created.vertical}
          state={intake}
          draft={draft}
          onDraftChange={setDraft}
          onContinue={() => onStep("invite")}
        />
      ) : (
        <CreatedPanel
          created={created}
          defaultEmail={defaultEmail}
          onBack={() => onStep("intake")}
        />
      )}
    </div>
  );
}

/**
 * Step 8 — everything here reads off the SERVER's response.
 *
 * The creation confirmation itself moved up to `AfterCreate`, which renders it above both
 * remaining steps: it is a standing fact about the account rather than a part of the
 * invite. What did NOT move is the rule it was built on — the account is named by the
 * server's own `slug` and `status`, and the typed name is offered separately as what was
 * submitted, because `CreateOrgOut` carries no name and a sentence built from the local
 * input would be this screen asserting what the row holds.
 */
function CreatedPanel({
  created,
  defaultEmail,
  onBack,
}: {
  created: WizardAccount;
  defaultEmail: string;
  onBack: () => void;
}) {
  const invite = useInvite();
  const revoke = useRevokeTenantInvitation();
  // THE FOUNDER'S OWN ASK, and until now the only route in D-538 with no caller: *"the
  // invite link can be re-sent via the admin panel ... until that mail sets up their
  // business"*. The endpoint, the rotation, the rate limit and the audit row all shipped;
  // the operator staring at `invitation_already_pending` could only CANCEL, which throws
  // away a live key to fix a mail that simply never arrived. Resending is the answer to
  // that refusal far more often than cancelling is, so it stands beside it.
  const resend = useResendTenantInvitation();
  const [email, setEmail] = useState(defaultEmail);
  // WAS the raw token, rendered on screen. D-198 removed it from the response and put the
  // link in the invitee's mailbox instead, so what is remembered here is the ADDRESS it was
  // sent to — the one thing an operator still needs to see, and not a credential. Cleared
  // at every submit so a send to one address can never sit under a refusal for another.
  const [sentTo, setSentTo] = useState<string | null>(null);
  const refusal = refusalReason(invite.error);
  const inviteValid = useFormValidation();
  // THE EXIT FROM THE SERVER'S OWN REFUSAL, and the reason it needs its own state.
  //
  // A second live token for one address is refused (`invitation_already_pending`), which
  // is right — two keys to a client's account in one inbox, only one of them revocable —
  // but on its own it leaves an operator whose first token was lost with nothing to do
  // for 72 hours: the revoke that already existed is client-realm, and this invite is
  // minted before anybody can sign in.
  //
  // `invite.data` cannot carry the id: a mutation clears `data` when the next attempt
  // fails, and the attempt that fails is exactly the one where the cancel is needed. So
  // the mint is remembered here — WITH ITS ADDRESS, which is the part that must not be
  // dropped. Minting for A and then being refused for B is a refusal about B's pending
  // invitation, and offering a button that silently cancels A's would revoke a live
  // credential the operator never asked about. The control appears only when the address
  // in the box is the one we hold.
  const [minted, setMinted] = useState<{ id: string; email: string } | null>(null);
  const blockedByPending =
    invite.error instanceof ApiProblem && invite.error.code === "invitation_already_pending";
  const cancellable =
    blockedByPending && minted && minted.email === email.trim().toLowerCase() ? minted.id : null;
  // The case the remembered mint cannot cover: the first link was issued by a colleague,
  // or from another tab, so this component never saw its id. Fetched only once the server
  // has actually refused — a list of live credentials is not something to put on screen
  // for every operator who opens the wizard.
  const pending = useTenantInvitations(blockedByPending && !cancellable ? created.id : "");

  return (
    <div className="space-y-4">
      <Card title="What happens next">
        {/* The account this wizard just created is immediately HELD on three gates that
            each have a working screen — KYC, commercial terms, first-campaign release —
            and this card used to name neither, so the account dropped silently into
            /admin/holds to be discovered later from a queue instead of continued now
            from the flow that created it (ux-audit F-7). The three links, in the order
            the holds bite; then the two genuinely-manual items. */}
        <ol className="space-y-1.5 text-sm text-ink-muted">
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              <Link
                href={`/admin/tenants/${created.id}/kyc`}
                className="font-medium text-brand-strong hover:underline"
              >
                Record their identity verification
              </Link>{" "}
              — number provisioning and outbound stay held until it is on file
            </span>
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              <Link
                href={`/admin/tenants/${created.id}/commercials`}
                className="font-medium text-brand-strong hover:underline"
              >
                Set their commercial terms
              </Link>{" "}
              — nothing can be billed until the agreement is recorded
            </span>
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              <Link
                href={`/admin/tenants/${created.id}/first-campaign-review`}
                className="font-medium text-brand-strong hover:underline"
              >
                Release their first campaign
              </Link>{" "}
              — every new account&apos;s first launch waits on this review
            </span>
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              Getting a phone number and registering with{" "}
              <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss>/
              <TermGloss term="PE">Principal Entity — the client, as registered on DLT</TermGloss>{" "}
              — still done by hand
            </span>
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            A test call signed off before the agent goes live — still done by hand
          </li>
        </ol>
      </Card>

      <Card title="Invite the owner">
        <div className="space-y-3">
          <p className="text-sm text-ink-muted">
            We send the owner a single-use link that is valid for 72 hours. We only keep
            a fingerprint of it, so it is never shown here and cannot be recovered.
          </p>

          <form
            className="flex flex-wrap items-start gap-2"
            noValidate
            onSubmit={inviteValid.onSubmit(() => {
              // A previous confirmation must not survive this attempt: "sent to …" left
              // over from an earlier address is a claim about mail nobody sent.
              setSentTo(null);
              // No placeholder fallback: an invite is a single-use credential for a real
              // inbox, and minting one for `owner@example.com` because the billing-email
              // field was left blank is a token nobody can use and a membership row
              // nobody asked for.
              invite.mutate(
                { tenantId: created.id, email: email.trim(), role: "owner" },
                {
                  onSuccess: (data) => {
                    setSentTo(email.trim());
                    setMinted({ id: data.id, email: email.trim().toLowerCase() });
                  },
                },
              );
            })}
          >
            <label className="block flex-1 sm:min-w-[16rem]">
              <span className={FIELD_LABEL}>Owner&apos;s email</span>
              <input
                {...inviteValid.field("email", "Enter the owner's email address.")}
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="owner@business.com"
                className={FIELD}
              />
              {inviteValid.error("email")}
            </label>
            <ActionButton
              type="submit"
              title={refusal ?? undefined}
              loading={invite.isPending}
              /* Emptiness is answered at the field now. `refusal` is a permission or a
                 lifecycle gate and stays. */
              disabled={Boolean(refusal)}
              className="mt-5"
            >
              <Mail aria-hidden className="h-4 w-4" />
              Create invite
            </ActionButton>
          </form>

          {invite.error && <ProblemNotice error={invite.error} />}
          {refusal && <p className="text-xs text-ink-muted">{refusal}</p>}
          {revoke.error && <ProblemNotice error={revoke.error} />}
          {resend.error && <ProblemNotice error={resend.error} />}
          {resend.data && (
            <p className="text-xs text-ink-muted">
              A new link is on its way to {resend.data.email}. The previous one has stopped
              working, and this one expires {formatIST(resend.data.expires_at)}.
            </p>
          )}

          {blockedByPending && !cancellable && (
            <div className="space-y-2">
              {/* §52 on a panel that appears only inside a refusal: while the list is in
                  flight it is a skeleton, and a failed read is the read's own refusal —
                  never "there are no pending invites", which would contradict the 409
                  that put this panel on screen. */}
              {pending.isLoading ? (
                <Skeleton rows={2} />
              ) : pending.error || !pending.data ? (
                /* `|| !pending.data` because a paused query — what TanStack does with
                   every read while the browser is offline — has `isLoading === false` and
                   `error === null`, so both arms above were skipped and `?? []` rendered
                   "no pending invites" against the 409 that put this panel on screen. */
                <ProblemNotice
                  error={pending.error ?? new Error("The pending invitations did not load.")}
                  onRetry={() => void pending.refetch()}
                />
              ) : (
                pending.data.map((row) => (
                  <div key={row.id} className="flex flex-wrap items-center gap-2 text-xs">
                    <MonoValue className="text-ink">{row.email}</MonoValue>
                    <span className="text-ink-muted">
                      {row.role} · expires {formatIST(row.expires_at)}
                    </span>
                    <button
                      type="button"
                      disabled={resend.isPending}
                      className={SECONDARY_BUTTON}
                      onClick={() =>
                        resend.mutate({ tenantId: created.id, invitationId: row.id })
                      }
                    >
                      Send this invite again
                    </button>
                    <button
                      type="button"
                      disabled={revoke.isPending}
                      className={SECONDARY_BUTTON}
                      onClick={() =>
                        revoke.mutate({ tenantId: created.id, invitationId: row.id })
                      }
                    >
                      Cancel this invite
                    </button>
                  </div>
                ))
              )}
            </div>
          )}

          {cancellable && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={resend.isPending}
                className={SECONDARY_BUTTON}
                onClick={() => {
                  // The old confirmation goes: "sent to …" described a link this rotation
                  // has just killed, and leaving it beside the new one is two claims about
                  // one mailbox.
                  setSentTo(null);
                  resend.mutate({ tenantId: created.id, invitationId: cancellable });
                }}
              >
                Send it again
              </button>
              <button
                type="button"
                disabled={revoke.isPending}
                className={SECONDARY_BUTTON}
                onClick={() => {
                  // The confirmation goes with the invitation it described — leaving "sent
                  // to …" beside a cancelled link is a claim about a link that no longer
                  // opens anything.
                  setSentTo(null);
                  revoke.mutate(
                    { tenantId: created.id, invitationId: cancellable },
                    {
                      onSuccess: () => {
                        // The row is gone, so the handle must go with it: a second click
                        // would 404 and read as the cancel having failed.
                        setMinted(null);
                        invite.reset();
                      },
                    },
                  );
                }}
              >
                {revoke.isPending ? "Cancelling…" : "Cancel the unused invite"}
              </button>
              <span className="text-xs text-ink-muted">
                Cancels the link this wizard already issued, so a fresh one can be sent to
                the same address. It does nothing to an invite somebody has already used.
              </span>
            </div>
          )}

          {sentTo && (
            <NoticeBox
              tone="ok"
              icon={<KeyRound aria-hidden className="h-5 w-5" />}
              title="Invitation sent"
            >
              <p className="mt-1">
                The link is on its way to <MonoValue>{sentTo}</MonoValue>. It is not shown
                here and cannot be read again — only a fingerprint of it is stored.
              </p>
              <p className="mt-2 flex items-start gap-2 text-xs">
                <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                Whoever opens it becomes an owner of{" "}
                <MonoValue>/c/{created.slug}</MonoValue>. If it went to the wrong address,
                cancel the invitation rather than sending a second one.
              </p>
            </NoticeBox>
          )}
        </div>
      </Card>

      <div className="flex flex-wrap gap-2">
        {/* Back to step 3 with its answers intact — `AfterCreate` holds the draft above
            this swap precisely so this button is not a way to lose them. The sentence
            that used to follow ("the endpoint has no draft save, so an unsubmitted intake
            exists nowhere but in this tab") stopped being true when `POST …/intake/draft`
            landed and `IntakeStep` grew its Save-draft control: an unsubmitted intake IS
            on file, and `Unfinished onboardings` on `/admin/new` is where it resumes. */}
        <button type="button" onClick={onBack} className={SECONDARY_BUTTON}>
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          Back to the intake
        </button>
        <Link href={`/admin/tenants/${created.id}`} className={SECONDARY_BUTTON}>
          <Plus aria-hidden className="h-3.5 w-3.5" />
          Open client
        </Link>
        <Link href="/admin" className={SECONDARY_BUTTON}>
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          Back to clients
        </Link>
      </div>
    </div>
  );
}
