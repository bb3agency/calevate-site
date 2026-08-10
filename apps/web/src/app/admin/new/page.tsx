"use client";

import Link from "next/link";
import { useState } from "react";

import { ProblemNotice } from "@/components/ui";
import { useCreateTenant, useInvite, type CreateOrgOut } from "@/lib/api/admin";

const VERTICALS = ["clinic", "real_estate", "insurance", "education", "custom"] as const;
const LANGUAGES = [
  { value: "te-IN", label: "Telugu" },
  { value: "hi-IN", label: "Hindi" },
  { value: "en-IN", label: "English (India)" },
] as const;

/**
 * New-client wizard, steps 1 and 8 (FLOWS §1).
 *
 * The middle steps are deliberately absent rather than stubbed: intake (3) is a guided
 * form we design with client #1 in the room, number provisioning (6) and the test-call
 * gate (7) both depend on the Bolna pilot. A greyed-out button that does nothing is
 * worse than a documented gap, so the checklist below says what is still manual.
 */
export default function NewClientPage() {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [vertical, setVertical] = useState<(typeof VERTICALS)[number]>("clinic");
  const [language, setLanguage] = useState<string>("te-IN");
  const [email, setEmail] = useState("");
  const [created, setCreated] = useState<CreateOrgOut | null>(null);
  const [inviteToken, setInviteToken] = useState<string | null>(null);

  const createTenant = useCreateTenant();
  const invite = useInvite();

  const derivedSlug =
    slug || name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold">New client</h1>
        <p className="mt-0.5 text-sm text-slate-400">
          Creates the account, its retention policies, a draft receptionist and an
          extraction schema from the vertical template.
        </p>
      </div>

      {createTenant.error && <ProblemNotice error={createTenant.error} />}

      {!created ? (
        <form
          className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            createTenant.mutate(
              {
                name,
                slug: derivedSlug,
                vertical_template: vertical,
                language: language as "te-IN",
                billing_email: email || null,
              },
              { onSuccess: setCreated },
            );
          }}
        >
          <Field label="Business name">
            <input
              required
              minLength={2}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm"
              placeholder="Sunrise Clinic"
            />
          </Field>

          <Field
            label="Slug"
            hint="Appears in every client URL and is IMMUTABLE once created (a DB trigger enforces it)."
          >
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder={derivedSlug || "sunrise-clinic"}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-sm"
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Vertical template" hint="Pre-fills the extraction schema.">
              <select
                value={vertical}
                onChange={(e) => setVertical(e.target.value as (typeof VERTICALS)[number])}
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm"
              >
                {VERTICALS.map((v) => (
                  <option key={v} value={v}>
                    {v.replace("_", " ")}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Primary language">
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Billing email" hint="Where hot-lead alerts and invoices go.">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm"
            />
          </Field>

          <button
            type="submit"
            disabled={createTenant.isPending || name.length < 2}
            className="rounded-md bg-slate-100 px-4 py-2 text-sm font-medium text-slate-900 disabled:opacity-50"
          >
            {createTenant.isPending ? "Creating…" : "Create client"}
          </button>
        </form>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl border border-emerald-900 bg-emerald-950/50 p-4 text-sm">
            <p className="font-medium text-emerald-300">
              {name} created as <span className="font-mono">/c/{created.slug}</span>
            </p>
            <p className="mt-1 text-emerald-200/80">
              Retention policies, a draft inbound receptionist and an extraction schema
              are in place. The agent is <strong>draft</strong> — nothing is client-visible
              until it is published.
            </p>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
            <h2 className="text-sm font-semibold">Still manual for this client</h2>
            {/* Saying so beats a disabled button that implies the feature exists. */}
            <ul className="mt-2 space-y-1 text-sm text-slate-400">
              <li>· Intake interview → prompt + T0 context (FLOWS §1 step 3)</li>
              <li>· Number provisioning and DLT/PE registration (step 6, pilot-gated)</li>
              <li>· Test-call sign-off before publish (step 7, pilot-gated)</li>
            </ul>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
            <h2 className="text-sm font-semibold">Invite the owner</h2>
            <p className="mt-1 text-xs text-slate-400">
              Single-use, valid 72 hours, hashed at rest — the link below is shown once
              and cannot be recovered.
            </p>
            <form
              className="mt-3 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                invite.mutate(
                  { tenantId: created.id, email: email || "owner@example.com", role: "owner" },
                  { onSuccess: (data) => setInviteToken(data.token) },
                );
              }}
            >
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="owner@business.com"
                className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm"
              />
              <button
                type="submit"
                disabled={invite.isPending}
                className="rounded-md bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-900 disabled:opacity-50"
              >
                Create invite
              </button>
            </form>
            {invite.error && (
              <div className="mt-3">
                <ProblemNotice error={invite.error} />
              </div>
            )}
            {inviteToken && (
              <p className="mt-3 break-all rounded-md bg-slate-950 p-2 font-mono text-xs text-amber-300">
                {inviteToken}
              </p>
            )}
          </div>

          <div className="flex gap-2">
            <Link
              href={`/admin/tenants/${created.id}`}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-sm"
            >
              Open client
            </Link>
            <Link href="/admin" className="rounded-md border border-slate-700 px-3 py-1.5 text-sm">
              Back to clients
            </Link>
          </div>
        </div>
      )}
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
      <span className="text-sm font-medium text-slate-200">{label}</span>
      {hint && <span className="mt-0.5 block text-xs text-slate-500">{hint}</span>}
      <div className="mt-1">{children}</div>
    </label>
  );
}
