"use client";

import Link from "next/link";
import { useState } from "react";

import { Providers } from "@/app/providers";
import { Card, ProblemNotice } from "@/components/ui";
import {
  SIGNUP_CONTACT_EMAIL,
  SIGNUP_LANGUAGES,
  SIGNUP_OPEN,
  SIGNUP_VERTICALS,
  isSignupClosed,
  isSignupDeferred,
  previewSlug,
  useSignup,
  type SignupLanguage,
} from "@/lib/api/signup";

/**
 * Self-serve signup — `app.calevate.tech/signup` (D-34 motion 2, FLOWS §2).
 *
 * The symptom: `POST /v1/auth/signup` shipped and nothing called it, so a business that
 * had already created a Clerk account had no way to create its workspace — the product
 * had exactly one door, the one an operator opens by hand.
 *
 * Three things this page is careful about.
 *
 * **It does not pretend to be a sign-up-from-scratch form.** The endpoint is NOT
 * unauthenticated: it needs a Clerk-verified user who has no organization yet, and the
 * membership is what the call creates. So the page says who it is for, rather than
 * silently 401-ing someone who arrived without an account.
 *
 * **A closed deployment says it is closed BEFORE the form, not after it.** The kill
 * switch DEFAULTS OFF, so on most deployments every submission is refused with
 * `signup_disabled` — a normal state of the world, not a fault. This page used to
 * learn that only from the refusal, which meant a closed deployment walked a business
 * through five fields and a submit before answering "no"; the form was decoration over
 * a door that was never going to open. `SIGNUP_OPEN` (build-time, defaulting to
 * CLOSED, documented in lib/api/signup.ts) now decides up front, and the same calm
 * panel — with the other door on it — is what the closed deployment renders instead of
 * the form.
 *
 * The refusal path stays wired up underneath, because the config can only ever be
 * stale and the server is the authority: a build that says open against a server that
 * says closed still lands on the identical panel, and load-shedding — which no
 * build-time flag can predict — still arrives that way with "shortly" attached.
 *
 * **What a new account can and cannot do is the SERVER's sentence.** `next_steps`
 * comes back on the response for exactly that reason — the wallet gate and the KYC
 * requirement are compliance rules, and encoding them a second time here is how the
 * two copies start disagreeing.
 */
export default function SignupPage() {
  return (
    <Providers>
      <div className="min-h-full bg-slate-50 dark:bg-slate-950">
        <main className="mx-auto max-w-xl px-4 py-10">
          {/* The gate sits HERE, above the form component, so a closed deployment does
              not mount the form at all: no state, no mutation hook, and therefore no
              submit path that could reach an endpoint certain to refuse it. */}
          {SIGNUP_OPEN ? <SignupForm /> : <SignupClosed deferred={false} />}
        </main>
      </div>
    </Providers>
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
 * There is deliberately NO form here and no disabled submit button: a control whose
 * only possible outcome is a refusal is not an affordance, it is a trap. What replaces
 * it is the route that does work — a human at Calevate opening the account by hand,
 * which is how every account is opened today anyway.
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
      <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">
        {deferred ? "Not right now" : "Signing up online is closed"}
      </h1>
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
        <p>
          {deferred
            ? "We are not creating new accounts at this moment — the platform is running in a reduced mode. Nothing you entered was wrong; try again shortly."
            : "Calevate does not open accounts online yet. Every workspace is set up by hand with you, so there is nothing to fill in here — and nothing you have done is wrong."}
        </p>
        {/* The server's sentence wins when there is one; it knows why THIS request was
            refused. The fallback is only for the build-time closure, where no request
            was made and so no server has spoken. */}
        <p className="mt-2">
          {remediation ??
            (deferred
              ? "Give it a few minutes and try again."
              : "Talk to us and we will set your workspace up — usually the same day.")}
        </p>
        {!deferred && SIGNUP_CONTACT_EMAIL && (
          <p className="mt-2">
            Write to{" "}
            <a className="font-medium underline" href={`mailto:${SIGNUP_CONTACT_EMAIL}`}>
              {SIGNUP_CONTACT_EMAIL}
            </a>
            , or reply to whoever showed you the demo.
          </p>
        )}
        {!deferred && (
          <p className="mt-3 text-xs text-slate-500">
            Already have a workspace? It lives at{" "}
            <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">/c/your-slug</code> —
            the URL your account manager gave you.
          </p>
        )}
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium dark:border-slate-700"
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

function SignupForm() {
  const signup = useSignup();
  const [businessName, setBusinessName] = useState("");
  const [slug, setSlug] = useState("");
  const [vertical, setVertical] = useState<string>("clinic");
  const [language, setLanguage] = useState<SignupLanguage>("te-IN");
  const [email, setEmail] = useState("");

  const derived = slug || previewSlug(businessName);
  const created = signup.data;

  if (created) {
    return (
      <div className="space-y-5">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">
            {created.name} is set up
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Your workspace is at{" "}
            <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">/c/{created.slug}</code>{" "}
            and you are its {created.role}. The URL is permanent — it cannot be changed
            later.
          </p>
        </div>

        <Card title="Before your agent can call anyone">
          {/* The server's list, not ours. These are compliance rules (an empty wallet
              blocks outbound; a number needs KYC), and a second copy of them in the
              frontend is a second copy to keep in step. */}
          <ul className="space-y-2">
            {created.next_steps.map((step) => (
              <li key={step} className="flex gap-2 text-sm text-slate-700 dark:text-slate-300">
                <span aria-hidden className="text-slate-400">
                  ●
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-slate-500">
            Your receptionist starts as a draft, so nothing is live and nothing is being
            charged yet.
          </p>
        </Card>

        <Link
          href={`/c/${created.slug}`}
          className="inline-block rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
        >
          Open {created.name}
        </Link>
      </div>
    );
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

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">
          Create your Calevate workspace
        </h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Sign in first — this creates the workspace for the account you are signed in
          with, and makes you its owner. If you already belong to a workspace, open it at
          its own URL instead.
        </p>
      </div>

      {signup.error && <ProblemNotice error={signup.error} />}

      <form
        className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
        onSubmit={(e) => {
          e.preventDefault();
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
        }}
      >
        <Field label="Business name" hint="What your callers know you as.">
          <input
            required
            minLength={2}
            maxLength={120}
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
            placeholder="Sri Sai Dental Care"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
          />
        </Field>

        <Field
          label="Workspace URL"
          hint="Permanent once created — it cannot be changed later."
        >
          <div className="flex items-center gap-1">
            <span className="text-sm text-slate-500">/c/</span>
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder={previewSlug(businessName) || "sri-sai-dental"}
              maxLength={40}
              className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm dark:border-slate-700 dark:bg-slate-950"
            />
          </div>
          {derived && (
            <p className="mt-1 text-xs text-slate-500">
              {/* A preview, never a promise: the server checks reserved names and
                  collisions, and may hand back a different one. */}
              Your workspace will be at <code>/c/{derived}</code>, unless that name is
              taken.
            </p>
          )}
        </Field>

        <Field
          label="Kind of business"
          hint="Sets the questions your agent asks and the columns your leads land in."
        >
          <select
            value={vertical}
            onChange={(e) => setVertical(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
          >
            {SIGNUP_VERTICALS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Language your agent speaks">
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as SignupLanguage)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
          >
            {SIGNUP_LANGUAGES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Billing email" hint="Optional — where invoices go.">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="owner@example.com"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
          />
        </Field>

        <button
          type="submit"
          disabled={signup.isPending || businessName.trim().length < 2}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {signup.isPending ? "Creating…" : "Create workspace"}
        </button>
        <p className="text-xs text-slate-500">
          Creating a workspace does not start any calling. Your agent begins as a draft,
          the wallet starts empty, and outbound calls stay blocked until there is credit
          and a verified number.
        </p>
      </form>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-800 dark:text-slate-200">{label}</span>
      {hint && <span className="mt-0.5 block text-xs text-slate-500">{hint}</span>}
      <div className="mt-1.5">{children}</div>
    </label>
  );
}
