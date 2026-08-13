"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowLeft,
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
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
} from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import {
  useCreateTenant,
  useInvite,
  type CreateOrgIn,
  type CreateOrgOut,
} from "@/lib/api/admin";

/**
 * New-client wizard, steps 1 and 8 (FLOWS §1).
 *
 * The middle steps are deliberately absent rather than stubbed: intake (3) is a guided
 * form we design with client #1 in the room, number provisioning (6) and the test-call
 * gate (7) both depend on the Bolna pilot. A greyed-out button that does nothing is
 * worse than a documented gap, so the checklist below says what is still manual.
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
 * - **`language as "te-IN"` was a cast that lied**: the state was a bare `string`, and the
 *   cast made any string typecheck as the API's three-member enum. The state now IS the
 *   generated union, so a language this API does not accept fails the build instead of the
 *   request.
 *
 * There is no permission PREVIEW on this screen, which is now a choice rather than a
 * limitation: `useAdminAccess` (`@/app/admin/access`) can be asked from anywhere since
 * `GET /v1/admin/me` landed, and the shell already gates the "New client" nav entry on
 * the same `admin:tenants` both writes require (admin/routes.py) — so a role that may
 * not create clients meets the refusal one step earlier, in the sidebar, where it is not
 * standing over a filled-in form. What stays here is the complementary mechanism, and it
 * is not a substitute for the preview: a refusal that HAS arrived, for any reason,
 * disables the control that caused it with the server's own words rather than inviting a
 * second identical refusal.
 *
 * The `<h1>` stays: the admin shell prints "Calevate admin" and the nav, not the page
 * title. It goes the moment the shell prints one.
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
const CHOICE_CARD = "relative block cursor-pointer rounded-card border p-3 transition-colors";
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

const LANGUAGES: { value: CreateOrgIn["language"]; label: string; hint: string }[] = [
  { value: "te-IN", label: "Telugu", hint: "The default, and what the voice stack is tuned for" },
  { value: "hi-IN", label: "Hindi", hint: "" },
  { value: "en-IN", label: "English (India)", hint: "" },
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

export default function NewClientPage() {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [vertical, setVertical] = useState<CreateOrgIn["vertical_template"]>("clinic");
  const [language, setLanguage] = useState<CreateOrgIn["language"]>("te-IN");
  const [email, setEmail] = useState("");
  // The ONLY evidence that an account exists. Set from the mutation's `onSuccess` and
  // from nowhere else — every sentence in step 2 reads off this object, so the screen
  // structurally cannot report a creation the server did not confirm.
  const [created, setCreated] = useState<CreateOrgOut | null>(null);

  const createTenant = useCreateTenant();
  const refusal = refusalReason(createTenant.error);

  const derivedSlug =
    slug || name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink">New client</h1>
        <p className="mt-0.5 text-sm text-ink-muted">
          Creates the account, its retention policies, a draft receptionist and an
          extraction schema from the vertical template.
        </p>
        <p className="mt-2 text-xs font-medium uppercase tracking-wide text-ink-faint">
          {created ? "Step 2 of 2 — invite the owner" : "Step 1 of 2 — account details"}
        </p>
      </div>

      {!created ? (
        <Card title="Account details">
          <form
            className="space-y-5"
            onSubmit={(e) => {
              e.preventDefault();
              createTenant.mutate(
                {
                  name,
                  slug: derivedSlug,
                  vertical_template: vertical,
                  language,
                  billing_email: email.trim() || null,
                },
                { onSuccess: setCreated },
              );
            }}
          >
            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>Business name</span>
              <input
                required
                minLength={2}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Sunrise Clinic"
                className={FIELD}
              />
            </label>

            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>Slug</span>
              <input
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder={derivedSlug || "sunrise-clinic"}
                className={`${FIELD} font-mono`}
              />
              <span className={FIELD_HINT}>
                Appears in every client URL and is IMMUTABLE once created (a DB trigger
                enforces it). Left blank, we send{" "}
                <span className="font-mono">{derivedSlug || "—"}</span>.
              </span>
            </label>

            <fieldset>
              <legend className={FIELD_LABEL}>Vertical template</legend>
              <p className="mt-1 text-xs text-ink-faint">
                Seeds the extraction schema, which becomes this client&apos;s CRM columns.
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
                {LANGUAGES.map((option) => (
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
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="owner@business.com"
                className={FIELD}
              />
              <span className={FIELD_HINT}>
                Where hot-lead alerts and invoices go. Offered again as the invite address
                in step 2.
              </span>
            </label>

            {createTenant.error && <ProblemNotice error={createTenant.error} />}

            <button
              type="submit"
              title={refusal ?? undefined}
              disabled={createTenant.isPending || name.trim().length < 2 || Boolean(refusal)}
              className={PRIMARY_BUTTON}
            >
              <Building2 aria-hidden className="h-4 w-4" />
              {createTenant.isPending ? "Creating…" : "Create client"}
            </button>
            {refusal && <p className="text-xs text-ink-muted">{refusal}</p>}
          </form>
        </Card>
      ) : (
        <CreatedPanel created={created} submittedName={name} defaultEmail={email} />
      )}
    </div>
  );
}

/**
 * Step 2 — everything here reads off the SERVER's response.
 *
 * `submittedName` is passed separately and labelled as what was submitted, rather than
 * being interpolated into the creation sentence: `CreateOrgOut` carries no name, so a
 * sentence built from the local input would be this screen asserting what the row holds.
 * The slug and status it does carry are the identity an operator can act on.
 */
function CreatedPanel({
  created,
  submittedName,
  defaultEmail,
}: {
  created: CreateOrgOut;
  submittedName: string;
  defaultEmail: string;
}) {
  const invite = useInvite();
  const [email, setEmail] = useState(defaultEmail);
  // The token is shown ONCE and cannot be recovered, so it is state rather than
  // `invite.data` — and it is cleared at every submit so a token minted for one address
  // can never sit under a refusal for another.
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const refusal = refusalReason(invite.error);

  return (
    <div className="space-y-4">
      <NoticeBox
        tone="ok"
        icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
        title="Account created"
      >
        <p className="mt-1">
          Live at <span className="font-mono font-semibold">/c/{created.slug}</span>, status{" "}
          <span className="font-semibold">{created.status}</span>. Retention policies, a
          draft inbound receptionist and an extraction schema are in place. The agent is{" "}
          <strong>draft</strong> — nothing is client-visible until it is published.
        </p>
        {submittedName && (
          <p className="mt-1 text-xs">Submitted as &ldquo;{submittedName}&rdquo;.</p>
        )}
      </NoticeBox>

      <Card title="Still manual for this client">
        {/* Saying so beats a disabled button that implies the feature exists. */}
        <ul className="space-y-1.5 text-sm text-ink-muted">
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            Intake interview → prompt + T0 context (FLOWS §1 step 3)
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            Number provisioning and DLT/PE registration (step 6, pilot-gated)
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            Test-call sign-off before publish (step 7, pilot-gated)
          </li>
        </ul>
      </Card>

      <Card title="Invite the owner">
        <div className="space-y-3">
          <p className="text-sm text-ink-muted">
            Single-use, valid 72 hours, hashed at rest — the link below is shown once and
            cannot be recovered.
          </p>

          <form
            className="flex flex-wrap items-start gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              // A previous token must not survive this attempt: an operator copying "the
              // token" after a failure would send the wrong person's credential.
              setInviteToken(null);
              // No placeholder fallback: an invite is a single-use credential for a real
              // inbox, and minting one for `owner@example.com` because the billing-email
              // field was left blank is a token nobody can use and a membership row
              // nobody asked for.
              invite.mutate(
                { tenantId: created.id, email: email.trim(), role: "owner" },
                { onSuccess: (data) => setInviteToken(data.token) },
              );
            }}
          >
            <label className="block min-w-[16rem] flex-1">
              <span className={FIELD_LABEL}>Owner&apos;s email</span>
              <input
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="owner@business.com"
                className={FIELD}
              />
            </label>
            <button
              type="submit"
              title={refusal ?? undefined}
              disabled={invite.isPending || !email.trim() || Boolean(refusal)}
              className={`${PRIMARY_BUTTON} mt-5`}
            >
              <Mail aria-hidden className="h-4 w-4" />
              {invite.isPending ? "Creating…" : "Create invite"}
            </button>
          </form>

          {invite.error && <ProblemNotice error={invite.error} />}
          {refusal && <p className="text-xs text-ink-muted">{refusal}</p>}

          {inviteToken && (
            <NoticeBox
              tone="warn"
              icon={<KeyRound aria-hidden className="h-5 w-5" />}
              title="Copy this now — it is not shown again"
            >
              <p className="mt-1 break-all font-mono text-xs">{inviteToken}</p>
              <p className="mt-2 flex items-start gap-2 text-xs">
                <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                Anyone holding this becomes an owner of{" "}
                <span className="font-mono">/c/{created.slug}</span>. Send it to the
                address above and nowhere else.
              </p>
            </NoticeBox>
          )}
        </div>
      </Card>

      <div className="flex flex-wrap gap-2">
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
