"use client";

import { useState } from "react";
import { Building2, CheckCircle2 } from "lucide-react";

import { ActionButton } from "@/components/actionButton";
import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { useFormValidation } from "@/components/formValidation";
import { Card, FIELD, FIELD_HINT, FIELD_LABEL, MonoValue, NoticeBox, ProblemNotice } from "@/components/ui";
import { useCreateTenant, type CreateOrgIn } from "@/lib/api/admin";
import { previewSlug, slugIsDerivable } from "@/lib/api/signup";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { examplesFor } from "@/lib/verticalExamples";

import { NextSteps } from "./NextSteps";
import { VERTICALS, refusalReason, type OwnerDetails } from "./shared";

/**
 * New client: the operator enters the minimum (D-695) — the business's name and web
 * address, its type, and who the owner is — then sends the owner their invite. The owner
 * fills in the business itself (hours, address, services, people) in their own guided
 * setup after they join; an operator can help through view-as.
 *
 * Primary job: create the account and get the owner in.
 */
export function NewClientScreen() {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [vertical, setVertical] = useState<CreateOrgIn["vertical_template"]>("clinic");
  const [owner, setOwner] = useState<OwnerDetails>({ name: "", email: "", phone: "" });
  const [created, setCreated] = useState<{ id: string; slug: string; status: string; email: string } | null>(null);

  const createTenant = useCreateTenant();
  const refusal = refusalReason(createTenant.error);
  const valid = useFormValidation();
  const derivedSlug = slug || previewSlug(name);
  // A name with no ASCII cannot become a web address: ask for one before the POST.
  const mustChooseSlug = name.trim().length > 0 && !slugIsDerivable(derivedSlug);
  const ownerField = (key: keyof OwnerDetails) => (value: string) =>
    setOwner((was) => ({ ...was, [key]: value }));

  useCopilotSurface(
    created !== null
      ? null
      : {
          route: "/admin/new",
          title: "New client",
          realm: "admin",
          fields: [
            { id: "new-client-name", label: "Business name", type: "text", value: name },
            { id: "new-client-slug", label: "Web address", type: "text", value: slug },
            {
              id: "new-client-vertical",
              label: "Business type",
              type: "select",
              value: vertical,
              options: VERTICALS.map((option) => ({ value: option.value, label: option.label })),
            },
            { id: "new-client-owner-name", label: "Owner's name", type: "text", value: owner.name, personal: "name" },
            { id: "new-client-email", label: "Owner's email", type: "text", value: owner.email, personal: "email" },
            { id: "new-client-owner-phone", label: "Owner's mobile", type: "text", value: owner.phone, personal: "phone" },
          ],
          apply: (items) => {
            for (const item of items) {
              const value = asText(item.value);
              if (item.field_id === "new-client-name") setName(value);
              else if (item.field_id === "new-client-slug") setSlug(value);
              else if (item.field_id === "new-client-owner-name") ownerField("name")(value);
              else if (item.field_id === "new-client-email") ownerField("email")(value);
              else if (item.field_id === "new-client-owner-phone") ownerField("phone")(value);
              else if (item.field_id === "new-client-vertical") {
                const option = VERTICALS.find((row) => row.value === item.value);
                if (option) setVertical(option.value);
              }
            }
          },
        },
  );

  return (
    <div className="max-w-3xl space-y-5">
      <PageHeader
        description="Creates the account and invites its owner, together. The owner fills in their business after they join."
      />

      {created ? (
        <div className="space-y-4">
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Account created and owner invited"
          >
            <p className="mt-1">
              Live at <MonoValue className="font-semibold">/c/{created.slug}</MonoValue>, status{" "}
              <span className="font-semibold">{created.status}</span>. The invitation is on its
              way to <MonoValue>{created.email}</MonoValue>; the link is never shown here.
            </p>
          </NoticeBox>
          <NextSteps created={created} />
        </div>
      ) : (
        <Card title="The business">
          <form
            className="space-y-5"
            noValidate
            onSubmit={valid.onSubmit(() => {
              createTenant.mutate(
                {
                  name,
                  slug: derivedSlug || null,
                  vertical_template: vertical,
                  owner: {
                    email: owner.email.trim(),
                    name: owner.name.trim() || null,
                    phone_e164: owner.phone.trim() || null,
                  },
                  // The draft receptionist starts in Telugu; each agent's language is set on
                  // the agent's own screens, not here.
                  language: "te-IN",
                },
                {
                  onSuccess: (account) =>
                    setCreated({
                      id: account.id,
                      slug: account.slug,
                      status: account.status,
                      email: owner.email.trim(),
                    }),
                },
              );
            })}
          >
            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>Business name</span>
              <input
                {...valid.field("name", "Give this client its business name.")}
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
              <span className={FIELD_LABEL}>Web address</span>
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
                In every link the client uses; it cannot be changed later.{" "}
                {mustChooseSlug ? (
                  <span className="text-ink">
                    We cannot build a web address out of that business name, so choose one:
                    3–40 characters of a–z, 0–9 and -.
                  </span>
                ) : (
                  <>
                    Left blank: <MonoValue>{derivedSlug || "—"}</MonoValue>.
                  </>
                )}
              </span>
            </label>

            <fieldset>
              <legend className={`${FIELD_LABEL} flex items-center gap-1`}>
                Business type
                <InfoTip label="business type" align="start">
                  Sets up the lead fields the agent collects, which become this client&apos;s
                  lead columns.
                </InfoTip>
              </legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {VERTICALS.map((option) => (
                  <label
                    key={option.value}
                    className={`${CHOICE_CARD} ${vertical === option.value ? CHOICE_ON : CHOICE_OFF}`}
                  >
                    <input
                      type="radio"
                      name="vertical"
                      className="sr-only"
                      checked={vertical === option.value}
                      onChange={() => setVertical(option.value)}
                    />
                    {vertical === option.value && (
                      <CheckCircle2 aria-hidden className="absolute right-2 top-2 h-4 w-4 text-brand" />
                    )}
                    <span className="block pr-6 text-sm font-semibold text-ink">{option.label}</span>
                    <span className="mt-0.5 block text-xs text-ink-faint">{option.hint}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="grid gap-3 sm:grid-cols-3">
              <legend className={`${FIELD_LABEL} mb-1`}>The owner — their invitation is sent when you create the account</legend>
              <label className="block min-w-0">
                <span className={FIELD_LABEL}>Name</span>
                <input
                  id="new-client-owner-name"
                  value={owner.name}
                  maxLength={200}
                  onChange={(e) => ownerField("name")(e.target.value)}
                  className={FIELD}
                />
              </label>
              <label className="block min-w-0">
                <span className={FIELD_LABEL}>Email</span>
                <input
                  {...valid.field("email", "Enter the owner's email address.")}
                  id="new-client-email"
                  type="email"
                  required
                  value={owner.email}
                  onChange={(e) => ownerField("email")(e.target.value)}
                  placeholder="owner@business.com"
                  className={FIELD}
                />
                {valid.error("email")}
              </label>
              <label className="block min-w-0">
                <span className={FIELD_LABEL}>Mobile</span>
                <input
                  id="new-client-owner-phone"
                  value={owner.phone}
                  inputMode="tel"
                  placeholder="+919876543210"
                  onChange={(e) => ownerField("phone")(e.target.value)}
                  className={`${FIELD} font-mono`}
                />
              </label>
            </fieldset>

            {createTenant.error && <ProblemNotice error={createTenant.error} />}
            <ActionButton
              type="submit"
              title={refusal ?? undefined}
              loading={createTenant.isPending}
              disabled={Boolean(refusal)}
            >
              <Building2 aria-hidden className="h-4 w-4" />
              Create and invite
            </ActionButton>
            {refusal && <p className="text-xs text-ink-muted">{refusal}</p>}
          </form>
        </Card>
      )}
    </div>
  );
}
