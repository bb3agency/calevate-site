"use client";

import Link from "next/link";
import { useState } from "react";
import { Hash, ScrollText } from "lucide-react";

import {
  Card,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { useAdminAccess } from "@/app/admin/access";
import {
  useProvisionNumber,
  useRegisterTemplate,
  useSetNumberDltStatus,
  useSetTemplateStatus,
  useTenantNumbers,
  useTenantTemplates,
} from "@/lib/api/admin";
import { Term } from "@/lib/glossary";

import { DltRegistrationPanel } from "./DltRegistrationPanel";
import { FIELD, PrimaryButton, SecondaryButton } from "./controls";

/**
 * The prerequisites every client campaign stalls on (SEC-COMP §3).
 *
 * Neither of them is a thing we obtain. **We do not buy the number** — the client takes
 * the connection in their own name on their own Exotel / Plivo / Vobiz account and stays
 * the subscriber of record (Model B: `docs/legal/LEGAL-OPS-PLAYBOOK.md` §9, published
 * Terms clause 3); the form below RECORDS the number they bought, so the launch gate can
 * read its series. **And we cannot file a template under their PE** — they hold that DLT
 * login, not us; what we do is draft the template content for them to file, and record
 * the registrar's verdict.
 *
 * They live in the ADMIN console anyway, because both are compliance facts the launch
 * gate reads: a client who could mark their own template "approved" would be launching
 * under a registration that does not exist. The client realm reads these and never
 * writes them.
 */
export function CampaignSetup({ tenantId, slug }: { tenantId: string; slug: string }) {
  const numbers = useTenantNumbers(slug);
  const templates = useTenantTemplates(slug);
  const provision = useProvisionNumber(tenantId);
  const setDlt = useSetNumberDltStatus(tenantId);
  const register = useRegisterTemplate(tenantId);
  const setStatus = useSetTemplateStatus(tenantId);
  // Every write in this panel is `admin:tenants` on `/v1/admin/tenants/{id}/...`.
  const write = useAdminAccess("admin:tenants", "change this client's telecom setup");

  const [e164, setE164] = useState("");
  const numberValid = useFormValidation();
  const [series, setSeries] = useState<"140" | "160" | "standard">("160");
  const [classification, setClassification] = useState<
    "promotional" | "transactional" | "service"
  >("service");
  const [body, setBody] = useState("");
  const templateValid = useFormValidation();
  const [dltRef, setDltRef] = useState("");

  return (
    <Card title="Campaign setup">
      <p className="-mt-2 text-xs text-ink-muted">
        Until a number, an approved template and an active entity registration exist,
        every campaign this client creates is blocked at launch.
      </p>
      <div className="mt-4">
        <RestrictionNote reason={write.reason} />
      </div>
      {/* `min-w-0` on the columns: a grid item defaults to `min-width: auto`, so it
          refuses to shrink below its own min-content and pushes the grid past the
          viewport instead of wrapping. Measured at 320px this column's min-content was
          288px inside a 238px box — the compliance forms below (a `flex-1` input, a
          `<select>` sized by its longest option) are what set it. */}
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div className="min-w-0 space-y-3">
          {/* The heading is a flex ROW of two items — the icon and the label — and the
              link is a sibling of the whole heading rather than a third child of it: a
              flex container holding loose text beside an inline element lays that element
              out as its own item with the gap on both sides (tests/inlineFlow.test.ts). */}
          <div className="flex items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-muted">
              <Hash className="h-3.5 w-3.5" />
              <span>Numbers</span>
            </h3>
            {/* THE OTHER DOOR, and it is a different act (D-537). This form RECORDS a
                connection the client already holds; the numbers screen BUYS one, links a
                vendor handle to one that has none, and releases one — each of which
                spends or stops money and each of which needs its own confirmation. They
                are deliberately not one form. */}
            <Link
              href={`/admin/tenants/${tenantId}/numbers`}
              className="ml-auto text-xs font-medium text-ink-muted underline underline-offset-2 hover:text-ink"
            >
              Buy, link or release a number
            </Link>
          </div>
          {provision.error && <ProblemNotice error={provision.error} />}
          {setDlt.error && <ProblemNotice error={setDlt.error} />}
          {/* A failed read printed "No numbers on file" — the sentence an operator acts
              on by asking a client who already has a number to go and get another. */}
          {numbers.error ? (
            <ProblemNotice error={numbers.error} onRetry={() => numbers.refetch()} />
          ) : numbers.isLoading || !numbers.data ? (
            <Skeleton rows={2} />
          ) : numbers.data.length === 0 ? (
            <p className="text-xs text-ink-muted">No numbers on file.</p>
          ) : (
            <ul className="space-y-1.5">
              {numbers.data.map((number) => (
                <li
                  key={number.id}
                  className="flex flex-wrap items-center gap-2 rounded-card border border-line p-2 text-xs"
                >
                  {/* The client's OWN published business number, which is the whole
                      point of the panel — not a called party's, which is the number
                      hard rule 6 is about. */}
                  <span className="font-mono text-ink">{number.e164}</span>
                  <span className="rounded bg-brand-soft px-1.5 py-0.5 font-medium text-brand-strong">
                    {number.series}
                  </span>
                  <span className="text-ink-muted">{number.dlt_status.replace(/_/g, " ")}</span>
                  {number.dlt_status !== "registered" && (
                    <span className="ml-auto">
                      <SecondaryButton
                        disabled={setDlt.isPending || !write.allowed}
                        onClick={() => setDlt.mutate({ numberId: number.id, dltStatus: "registered" })}
                      >
                        Mark registered
                      </SecondaryButton>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <form
            className="flex flex-wrap gap-2"
            noValidate
            onSubmit={numberValid.onSubmit(() => {
              provision.mutate({ e164, series }, { onSuccess: () => setE164("") });
            })}
          >
            <input
              {...numberValid.field("e164", "Enter the number to record.")}
              required
              minLength={8}
              aria-label="Number to record"
              value={e164}
              disabled={!write.allowed}
              onChange={(ev) => setE164(ev.target.value)}
              placeholder="+918041234567"
              className={`flex-1 font-mono ${FIELD}`}
            />
            {/* The series is what the launch gate matches against the campaign's
                classification — wrong here is a DLT violation later, not a typo. */}
            <select
              aria-label="Number series"
              value={series}
              disabled={!write.allowed}
              onChange={(ev) => setSeries(ev.target.value as typeof series)}
              className={FIELD}
            >
              <option value="140">140 — promotional</option>
              <option value="160">160 — service</option>
              <option value="standard">standard</option>
            </select>
            {numberValid.error("e164")}
            <PrimaryButton
              type="submit"
              /* The length rule is answered at the field now, so the button stays live
                 and a press produces a sentence rather than nothing. */
              disabled={provision.isPending || !write.allowed}
            >
              Add
            </PrimaryButton>
          </form>
        </div>

        <div className="min-w-0 space-y-3">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-muted">
            <ScrollText className="h-3.5 w-3.5" />
            <span>
              <Term id="dlt" /> voice
              templates
            </span>
          </h3>
          {register.error && <ProblemNotice error={register.error} />}
          {setStatus.error && <ProblemNotice error={setStatus.error} />}
          {templates.error ? (
            <ProblemNotice error={templates.error} onRetry={() => templates.refetch()} />
          ) : templates.isLoading || !templates.data ? (
            <Skeleton rows={2} />
          ) : templates.data.length === 0 ? (
            <p className="text-xs text-ink-muted">No templates registered.</p>
          ) : (
            <ul className="space-y-1.5">
              {templates.data.map((template) => (
                <li key={template.id} className="rounded-card border border-line p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-brand-soft px-1.5 py-0.5 font-medium text-brand-strong">
                      {template.classification}
                    </span>
                    <span className="text-ink-muted">{template.status.replace(/_/g, " ")}</span>
                    {template.status !== "approved" && (
                      <span className="ml-auto">
                        <PrimaryButton
                          disabled={setStatus.isPending || !write.allowed}
                          onClick={() =>
                            setStatus.mutate({ templateId: template.id, status: "approved" })
                          }
                        >
                          Registrar approved
                        </PrimaryButton>
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-ink-muted">{template.body}</p>
                </li>
              ))}
            </ul>
          )}
          <form
            className="space-y-2"
            noValidate
            onSubmit={templateValid.onSubmit(() => {
              register.mutate(
                { classification, body, dlt_ref: dltRef || null },
                {
                  onSuccess: () => {
                    setBody("");
                    setDltRef("");
                  },
                },
              );
            })}
          >
            <div className="flex gap-2">
              <select
                aria-label="Template classification"
                value={classification}
                disabled={!write.allowed}
                onChange={(ev) => setClassification(ev.target.value as typeof classification)}
                className={FIELD}
              >
                <option value="promotional">promotional</option>
                <option value="service">service</option>
                <option value="transactional">transactional</option>
              </select>
              <input
                aria-label="Registrar template id"
                value={dltRef}
                disabled={!write.allowed}
                onChange={(ev) => setDltRef(ev.target.value)}
                placeholder="registrar template id (optional)"
                className={`flex-1 ${FIELD}`}
              />
            </div>
            <textarea
              {...templateValid.field("body", "Type the wording registered with the registrar.")}
              required
              aria-label="Template wording"
              minLength={10}
              rows={3}
              value={body}
              disabled={!write.allowed}
              onChange={(ev) => setBody(ev.target.value)}
              placeholder="The exact wording registered with the DLT registrar."
              className={`w-full ${FIELD}`}
            />
            {templateValid.error("body")}
            <PrimaryButton
              type="submit"
              /* The ten-character rule is the field's now. */
              disabled={register.isPending || !write.allowed}
            >
              Register template
            </PrimaryButton>
          </form>
        </div>

        {/* Beside the numbers and the templates, because they are the same family of
            registrar paperwork and an operator working one is usually working all
            three — not on a separate screen a launch blocker has to send them to. */}
        <DltRegistrationPanel tenantId={tenantId} write={write} />
      </div>
    </Card>
  );
}
