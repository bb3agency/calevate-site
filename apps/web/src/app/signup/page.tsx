"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ArrowRight, CircleAlert, Mail, ShieldCheck } from "lucide-react";

import { Providers } from "@/app/providers";
import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import { AuthPageFrame } from "@/components/authPage";
import { AuthShowcase } from "@/components/authn/authShowcase";
import { CreateAccountForm } from "@/components/authn/createAccountForm";
import { useSignInOptions } from "@/components/authn/googleSignIn";
import { useFormValidation } from "@/components/formValidation";
import { ApiProblem } from "@/lib/api/client";
import { CLIENT_ACCOUNT_PATH, CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";
import { ClientSessionProvider, useClientSessionRow } from "@/lib/authn/clientSession";
import { lookup } from "@/lib/lookup";
import {
  SIGNUP_CONTACT_EMAIL,
  SIGNUP_LANGUAGES,
  SIGNUP_VERTICALS,
  isSignupClosed,
  isSignupDeferred,
  isSignupUnverified,
  previewSlug,
  slugIsDerivable,
  useSignup,
  type SignupLanguage,
} from "@/lib/api/signup";

/**
 * Self-serve signup — `app.calevate.tech/signup` (D-34 motion 2, FLOWS §2; D-703).
 *
 * Two steps, because the identity and the workspace are two things (D-37): a Calevate
 * account first (`CreateAccountForm`: Google, or an email code and a password), then the
 * business (`SignupForm` → `POST /v1/auth/signup`, which starts the free trial).
 *
 * Whether signing up is open is the SERVER's live answer (`GET /v1/auth/client/sign-in-
 * options`, the `self_serve_signup_enabled` console switch), so a closed deployment says
 * so before any form, and an operator can open or close it without a deploy. The refusal
 * paths stay wired under the form, because the server stays the authority.
 *
 * What a new account can and cannot do is the server's sentence: `next_steps` comes back
 * on the response and the success panel renders only what arrived.
 *
 * No app shell wraps this route, so it carries its own frame and scroll container.
 */

/**
 * The console's field/control shapes, copied deliberately and marked for extraction.
 *
 * `/c/<slug>/campaigns` defines this identical set and says they belong in `ui.tsx` "the
 * moment a second screen needs them". This is that second screen — but `ui.tsx` is out of
 * this change's slice, so the constants are duplicated here with the pointer attached
 * rather than the two screens quietly drifting apart. THE FOLLOW-UP IS: move `FIELD`,
 * `FIELD_LABEL`, `FIELD_HINT`, `PRIMARY_BUTTON` and `SECONDARY_BUTTON` into `ui.tsx` and
 * delete both copies.
 */

/**
 * The wire name of every field this form owns, and the DOM id its input carries.
 *
 * Exists so a server-side field error can be put NEXT TO the input it is about and
 * announced as that input's description, rather than only in a list at the top of the
 * page. A validation message a screen-reader user meets while tabbing is the difference
 * between fixing an answer and re-reading the whole form.
 *
 * Read with `lookup` and never `TABLE[name]`: `field` is a string the SERVER chose, and
 * a wire value of `constructor` resolves to the `Object` function on a plain index —
 * which is truthy, so the "we do not own this field" branch would never fire and the
 * message would be dropped from the summary instead (src/lib/lookup.ts).
 */
const FIELD_IDS = {
  business_name: "signup-business-name",
  slug: "signup-slug",
  vertical_template: "signup-vertical",
  language: "signup-language",
  billing_email: "signup-billing-email",
} satisfies Record<string, string>;

type ProblemField = NonNullable<ApiProblem["fields"]>[number];

/** The server's message for one field, or nothing. A `find` rather than a table read —
 * the key here is OUR literal, so there is no dynamic index to make safe. */
function fieldMessage(fields: ProblemField[], name: string): string | undefined {
  return fields.find((f) => f.field === name)?.message;
}

export default function SignupPage() {
  return (
    // The CLIENT realm's session provider, mounted here because this route is outside
    // the `/c/<slug>` shell that mounts it for the console. The PROVIDER and not the
    // GATE: a stranger with no session belongs on this page, reading the panel that says
    // what they need — `ClientSessionGate` would replace the whole screen with a
    // sign-in prompt, which is the demand-with-no-context this page exists to avoid.
    <ClientSessionProvider>
      <Providers>
        <AuthPageFrame realmLabel="Nothing here places a call" aside={<AuthShowcase />} width="wide">
            {/* The kill switch is checked FIRST, above both the form and the account
                gate: on a deployment that opens no workspaces, sending a stranger off to
                create an account would be walking them one screen further into a door
                that is shut. The gate sits above the form component for the same
                shape of reason — a closed deployment does not mount the form at all, so
                no state and no mutation hook exist to reach an endpoint certain to
                refuse them. */}
            <SignupGate />
        </AuthPageFrame>
      </Providers>
    </ClientSessionProvider>
  );
}

/** Open or closed, as the server says right now; a skeleton until it has said. */
function SignupGate() {
  const options = useSignInOptions();
  if (options.isPending) return <Skeleton rows={4} label="Loading…" />;
  if (!options.data?.self_serve_signup) return <SignupClosed deferred={false} />;
  return <SignupOrAccount />;
}

/**
 * The business form for somebody signed in, account creation for somebody who is not.
 * Read off the RESTORED session row (the server's answer to `GET /v1/auth/client/
 * session`), so a stale cookie renders account creation rather than a form that 401s.
 */
function SignupOrAccount() {
  return useClientSessionRow() !== null ? (
    <SignupForm />
  ) : (
    <Card>
      <CreateAccountForm onCreated={() => window.location.reload()} />
      <p className="mt-6 text-center text-sm text-ink-muted">
        Already have an account?{" "}
        <Link
          href={CLIENT_SIGN_IN_PATH}
          className="font-medium text-brand-strong underline underline-offset-2 dark:text-brand-bright"
        >
          Sign in
        </Link>
      </p>
    </Card>
  );
}

/**
 * The closed door, said once — reached two ways and identical from both.
 *
 * `deferred` splits the two closures because they have different lifetimes and so
 * different instructions: the kill switch will not clear by waiting (talk to us),
 * load-shedding will (try again shortly). Collapsing them would either tell a business
 * to wait for something that is never going to happen on its own, or send someone to
 * support over a five-minute reduced-mode window.
 *
 * There is deliberately NO form here and no disabled submit button: a control whose only
 * possible outcome is a refusal is not an affordance, it is a trap. What replaces it is
 * the route that does work — a human at Calevate opening the account by hand, which is
 * how every account is opened today anyway.
 *
 * HONESTY FIX carried in with the design pass: this panel used to end "usually the same
 * day". Nothing measures that — there is no ops SLA for account setup anywhere in the
 * docs — so it was a turnaround promise made by a screen with no way to keep it. Removed
 * rather than restyled.
 */
function SignupClosed({
  deferred,
  remediation,
  onRetry,
}: {
  deferred: boolean;
  remediation?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">
        {deferred ? "Not right now" : "Signing up online is closed"}
      </h1>
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <p>
            {deferred
              ? "We are not creating new accounts at this moment — the platform is running in a reduced mode. Nothing you entered was wrong; try again shortly."
              : "Calevate does not open accounts online yet. Every workspace is set up by hand with you, so there is nothing to fill in here — and nothing you have done is wrong."}
          </p>
          {/* The server's sentence wins when there is one; it knows why THIS request was
              refused. The fallback is only for the build-time closure, where no request
              was made and so no server has spoken. */}
          <p>
            {remediation ??
              (deferred
                ? "Give it a few minutes and try again."
                : "Talk to us and we will set your workspace up with you.")}
          </p>
          {!deferred && SIGNUP_CONTACT_EMAIL && (
            <p className="flex items-start gap-1.5">
              <Mail aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
              <span>
                Write to{" "}
                <a
                  className="font-medium text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                  href={`mailto:${SIGNUP_CONTACT_EMAIL}`}
                >
                  {SIGNUP_CONTACT_EMAIL}
                </a>
                , or reply to whoever showed you the demo.
              </span>
            </p>
          )}
          {!deferred && (
            <p className="text-xs text-ink-faint">
              Already have a workspace? It lives at{" "}
              <code className="rounded bg-black/5 px-1 font-mono text-ink dark:bg-white/10">
                /c/your-slug
              </code>{" "}
              — the URL your account manager gave you.
            </p>
          )}
          {onRetry && (
            <button type="button" onClick={onRetry} className={SECONDARY_BUTTON}>
              Try again
            </button>
          )}
        </div>
      </Card>
    </div>
  );
}

/**
 * "Confirm your email address first" — a step, rendered as a step.
 *
 * The account exists and the session is valid; what is missing is proof of the mailbox,
 * which `/auth/account` takes a code to establish (D-174). The two things this panel is
 * careful about are the two that would make it a dead end:
 *
 * **It links to the door.** `SignupClosed`'s sibling panel deliberately does not link
 * anywhere, because the thing it describes cannot be cleared by the person reading it.
 * This one can be, in under a minute, so not linking would be the failure the stranger's
 * panel above exists to avoid — sent one screen further with nothing to press.
 *
 * **It keeps the retry.** Coming back is the second half of the loop, and a person who
 * has just verified in another tab should not have to retype five fields —
 * `signup.reset()` clears the error and re-renders the form with its state intact,
 * because the form's state lives in `SignupForm` and this panel is rendered by it.
 */
function ConfirmYourAddress({
  remediation,
  onRetry,
}: {
  remediation?: string;
  onRetry: () => void;
}) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">
        Confirm your email address first
      </h1>
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <p>
            Before we create a workspace we need to know the address on your account
            reaches you. It takes one code and about a minute.
          </p>
          {/* The server's sentence when it gave one — it knows why THIS request was
              refused. The fallback covers only the shape where none arrived. */}
          <p>{remediation ?? "Open your account settings and confirm your address."}</p>
          <div className="flex flex-wrap gap-2">
            <Link href={CLIENT_ACCOUNT_PATH} className={PRIMARY_BUTTON}>
              Confirm my address
              <ArrowRight aria-hidden className="h-4 w-4" />
            </Link>
            <button type="button" onClick={onRetry} className={SECONDARY_BUTTON}>
              I have done that
            </button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function SignupForm() {
  const signup = useSignup();
  const [businessName, setBusinessName] = useState("");
  const valid = useFormValidation();
  const [slug, setSlug] = useState("");
  // No default (founder, REDESIGN-2): the trade shapes every agent, script and lead column
  // this business gets, so it is a choice the person makes, never one we make for them.
  const [vertical, setVertical] = useState<string>("");
  const [language, setLanguage] = useState<SignupLanguage>("te-IN");
  const [email, setEmail] = useState("");

  const derived = slug || previewSlug(businessName);
  // The server REFUSES to invent a URL for a name it cannot fold to ASCII
  // (`slug_not_derivable`), which on a Telugu-first product is the ordinary case rather
  // than an edge one. Asking here, before the POST, rather than letting the refusal come
  // back: a form that cannot succeed is a worse answer than a form that says what it
  // needs.
  const mustChooseSlug = businessName.trim().length > 0 && !slugIsDerivable(derived);
  const created = signup.data;

  // THE ONLY SOURCE OF A SUCCESS SCREEN. `signup.data` is set by TanStack Query only
  // after a 2xx that parsed, so there is no state this component can enter where it
  // reports an account without having been handed one.
  if (created) {
    return (
      <div className="space-y-5">
        <div>
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
            <ShieldCheck aria-hidden className="h-5 w-5" />
          </span>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-ink">
            {created.name} is set up
          </h1>
          <p className="mt-2 text-sm text-ink-muted">
            Your workspace is at{" "}
            <code className="rounded bg-black/5 px-1 font-mono text-ink dark:bg-white/10">
              /c/{created.slug}
            </code>{" "}
            and you are its {created.role}. The URL is permanent — it cannot be changed
            later.
          </p>
        </div>

        <Card title="What happens next">
          {/* The server's list, not ours: a second copy of these rules in the frontend
              would be a second copy to keep in step. */}
          <ul className="space-y-2">
            {created.next_steps.map((step) => (
              <li key={step} className="flex gap-2.5 text-sm text-ink-muted">
                <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
                <span>{step}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-ink-faint">
            Nothing is charged during your free trial.
          </p>
        </Card>

        <Link href={`/c/${created.slug}/setup`} className={PRIMARY_BUTTON}>
          Set up {created.name}
          <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
      </div>
    );
  }

  // Not a form problem either, and not a refusal: a STEP the person has not done yet.
  // `assert_email_verified` requires a proved mailbox before a workspace is created, and
  // an account redeemed from an invitation is unverified by design (D-185) — so this is
  // the ordinary path for a brand-new account, not an edge case. It replaces the form
  // for the same reason the two below do: nothing they type here can clear it.
  if (isSignupUnverified(signup.error)) {
    return <ConfirmYourAddress remediation={signup.error.remediation} onRetry={() => signup.reset()} />;
  }

  // The kill switch and the load-shed refusal are not errors the caller can fix by
  // correcting the form, so they replace it rather than sitting above it.
  if (isSignupClosed(signup.error) || isSignupDeferred(signup.error)) {
    const deferred = isSignupDeferred(signup.error);
    return (
      <SignupClosed
        deferred={deferred}
        // The server's own sentence when it gave one — it knows why it refused this
        // request and we do not.
        remediation={signup.error.remediation}
        onRetry={deferred ? () => signup.reset() : undefined}
      />
    );
  }

  const problem = signup.error instanceof ApiProblem ? signup.error : null;
  const fields = problem?.fields ?? [];
  /**
   * Field messages are shown AT their field, so the summary must not repeat them — but a
   * message about a field this form does not render would then vanish entirely, and a
   * dropped refusal is the one outcome worse than a duplicated one. Anything unowned goes
   * into the summary instead.
   */
  const unowned = fields.filter((f) => lookup(FIELD_IDS, f.field) === undefined);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">
          Create your Calevate workspace
        </h1>
        <p className="mt-2 text-sm text-ink-muted">
          This creates the workspace for the Calevate account you are already signed in
          with, and makes you its owner. If you already belong to a workspace, open it at
          its own URL instead.
        </p>
      </div>

      {/*
       * Two error surfaces, split by WHERE the answer is, not by taste.
       *
       * A problem with no field list is about the request as a whole — `ProblemNotice` is
       * the repo's one way to render that, and it carries `remediation`, `retryable` and
       * the trace ref support will ask for. A problem WITH a field list is about specific
       * answers, and the accessible place for those is beside the inputs (`aria-invalid`
       * + `aria-describedby` below), so the summary here only points at them.
       */}
      {problem && fields.length === 0 && <ProblemNotice error={signup.error} />}
      {problem && fields.length > 0 && (
        <NoticeBox
          tone="stop"
          icon={<CircleAlert aria-hidden className="h-4 w-4" />}
          title={problem.message}
        >
          <div role="alert" className="mt-1 space-y-1">
            <p>Check the answers marked below.</p>
            {problem.remediation && <p>{problem.remediation}</p>}
            {unowned.length > 0 && (
              <ul className="list-inside list-disc">
                {unowned.map((f) => (
                  <li key={f.field}>{f.message}</li>
                ))}
              </ul>
            )}
            {/* NO TRACE REFERENCE ON THIS BRANCH. This arm is reached only when the
                server named specific answers to change, which is a refusal the person
                can clear themselves — and a 32-character id printed beside "check the
                answers marked below" competes with the only line that helps, and makes a
                fixable form look like an outage. `ProblemNotice` (the branch above, for a
                refusal that names nothing to fix) applies the same rule and still carries
                the reference where it is genuinely ours to look up. */}
          </div>
        </NoticeBox>
      )}

      <Card>
        <form
          className="space-y-5"
          noValidate
          onSubmit={valid.onSubmit(() => {
            // Everything a prospect typed travels in the POST body. Nothing is ever put
            // in the path or a query string — hard rule 6: a URL lands in access logs,
            // proxy logs and the Referer header of the next request.
            signup.mutate({
              business_name: businessName,
              // Sent only when typed. Absent means the SERVER derives it — the same
              // `slugify` this form previews with, but with the reserved-word and
              // collision checks that only it can do.
              ...(slug.trim() ? { slug: slug.trim() } : {}),
              vertical_template: vertical,
              language,
              plan_tier: "self_serve",
              ...(email.trim() ? { billing_email: email.trim() } : {}),
            });
          })}
        >
          <Field
            id={FIELD_IDS.business_name}
            label="Business name"
            hint="What your callers know you as."
            /* OURS FIRST, then the server's. They are two answers to one question and
               only one can be shown; the client's is about what is on screen right now,
               while the server's arrived before the last keystroke. */
            error={valid.message("business_name") ?? fieldMessage(fields, "business_name")}
          >
            {(props) => (
              <input
                {...props}
                {...valid.track("business_name", "Enter your business name.")}
                required
                minLength={2}
                maxLength={120}
                value={businessName}
                onChange={(e) => setBusinessName(e.target.value)}
                placeholder="Your business name"
                className={FIELD}
              />
            )}
          </Field>

          <Field
            id={FIELD_IDS.slug}
            label="Workspace URL"
            hint="Permanent once created — it cannot be changed later."
            error={valid.message("slug") ?? fieldMessage(fields, "slug")}
          >
            {(props) => (
              <div className="mt-1 flex items-center gap-1">
                <span className="font-mono text-sm text-ink-faint">/c/</span>
                <input
                  {...props}
                  {...valid.track("slug", "Choose a web address for your workspace.")}
                  required={mustChooseSlug}
                  minLength={mustChooseSlug ? 3 : undefined}
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder={previewSlug(businessName) || "your-business"}
                  maxLength={40}
                  className={`${FIELD} mt-0 font-mono`}
                />
              </div>
            )}
          </Field>
          {mustChooseSlug ? (
            <p className="-mt-3 text-xs text-ink-muted">
              We cannot build a web address out of that business name, so please choose
              one — 3-40 characters of a-z, 0-9 and -.
            </p>
          ) : (
            derived && (
              /* A preview, never a promise: the server checks reserved names and
                 collisions, and may hand back a different one. */
              <p className="-mt-3 text-xs text-ink-faint">
                Your workspace will be at{" "}
                <code className="font-mono">/c/{derived}</code>, unless that name is taken.
              </p>
            )
          )}

          <Field
            id={FIELD_IDS.vertical_template}
            label="Kind of business"
            hint="Sets the questions your agent asks and the columns your leads land in."
            error={valid.message("vertical_template") ?? fieldMessage(fields, "vertical_template")}
          >
            {(props) => (
              <select
                {...props}
                {...valid.track("vertical_template", "Choose the kind of business you run.")}
                required
                value={vertical}
                onChange={(e) => setVertical(e.target.value)}
                className={FIELD}
              >
                <option value="" disabled>
                  Choose one
                </option>
                {SIGNUP_VERTICALS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            )}
          </Field>

          <Field
            id={FIELD_IDS.language}
            label="Language your agent speaks"
            error={fieldMessage(fields, "language")}
          >
            {(props) => (
              <select
                {...props}
                value={language}
                onChange={(e) => setLanguage(e.target.value as SignupLanguage)}
                className={FIELD}
              >
                {SIGNUP_LANGUAGES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            )}
          </Field>

          <Field
            id={FIELD_IDS.billing_email}
            label="Billing email"
            hint="Optional — where invoices go."
            error={valid.message("billing_email") ?? fieldMessage(fields, "billing_email")}
          >
            {(props) => (
              <input
                {...props}
                {...valid.track("billing_email", "Enter the email address for invoices.")}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="owner@example.com"
                className={FIELD}
              />
            )}
          </Field>

          <div className="space-y-2">
            <button
              type="submit"
              /* The name rule is not repeated here: the field answers it in a sentence,
                 and a button dead at one character said nothing at all. */
              disabled={signup.isPending}
              className={PRIMARY_BUTTON}
            >
              {signup.isPending ? "Creating…" : "Create workspace"}
            </button>
            <p className="text-xs text-ink-faint">
              Your free trial starts straight away: you can build your agents and place
              test calls to your own phone. Calling your customers opens once you add
              credit and verify your business.
            </p>
          </div>
        </form>
      </Card>
    </div>
  );
}

/**
 * One labelled control, with its hint and its refusal wired to it.
 *
 * The children are a RENDER FUNCTION rather than a node because the input needs the
 * generated ids: `id` to be the label's target, and `aria-describedby` to name the hint
 * and the error. Passing them down is what makes the association real rather than
 * visual — a screen reader announces "Workspace URL, invalid, that name is taken" while
 * tabbing, instead of leaving the user to hunt for a red block at the top of the page.
 *
 * `htmlFor` + an explicit `id` rather than a wrapping `<label>`: the URL field wraps its
 * input in a row with a `/c/` prefix, and a label wrapping two things labels both.
 */
function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: (props: {
    id: string;
    "aria-describedby"?: string;
    "aria-invalid"?: true;
  }) => ReactNode;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      {children({
        id,
        "aria-describedby": describedBy,
        ...(error ? { "aria-invalid": true as const } : {}),
      })}
      {hint && (
        <span id={hintId} className={FIELD_HINT}>
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId} className="mt-1 block text-xs font-medium text-danger">
          {error}
        </span>
      )}
    </div>
  );
}
