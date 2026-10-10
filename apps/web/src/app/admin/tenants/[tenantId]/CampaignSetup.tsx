"use client";

import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/console/emptyState";
import { Section, TEXT_ACTION } from "@/components/console/section";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatPhone,
} from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { useFormValidation } from "@/components/formValidation";
import { useAdminAccess } from "@/app/admin/access";
import {
  useRegisterTemplate,
  useSetNumberDltStatus,
  useSetTemplateStatus,
  useTenantNumbers,
  useTenantTemplates,
} from "@/lib/api/admin";
import { Term } from "@/lib/glossary";

import { DltRegistrationPanel } from "./DltRegistrationPanel";
import { HAIRLINE_LIST, StatusPill, sentenceCase } from "@/components/admin/kit";

const LINK =
  "rounded-sm font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2";

/** A registration state as words: "pending_registration" → "Pending registration". */
const state = (value: string) => sentenceCase(value);

/**
 * The prerequisites every client campaign stalls on (SEC-COMP §3), as the Campaign setup
 * page's body.
 *
 * None of them is a thing we obtain. **We do not buy the number**: the client takes the
 * connection in their own name and stays the subscriber of record (Model B,
 * `docs/legal/LEGAL-OPS-PLAYBOOK.md` §9), and recording it is the Numbers page's job. **We
 * cannot file a template under their PE**: they hold that DLT login, so we draft the
 * content and record the registrar's verdict. They live in the ADMIN console because the
 * launch gate reads them — a client who could mark their own template approved would be
 * launching under a registration that does not exist.
 */
export function CampaignSetup({ tenantId, slug }: { tenantId: string; slug: string }) {
  const numbers = useTenantNumbers(slug);
  const templates = useTenantTemplates(slug);
  const setDlt = useSetNumberDltStatus(tenantId);
  const register = useRegisterTemplate(tenantId);
  const setStatus = useSetTemplateStatus(tenantId);
  // Every write here is `admin:tenants` on `/v1/admin/tenants/{id}/...`.
  const write = useAdminAccess("admin:tenants", "change this client's telecom setup");

  const [classification, setClassification] = useState<
    "promotional" | "transactional" | "service"
  >("service");
  const [body, setBody] = useState("");
  const templateValid = useFormValidation();
  const [dltRef, setDltRef] = useState("");
  const bodyField = templateValid.field("body", "Type the wording registered with the registrar.");

  return (
    <div className="max-w-3xl space-y-10">
      <PageHeader
        title="Campaign setup"
        description="Until a number, an approved template and an active entity registration exist, every campaign this client creates is blocked at launch."
      />

      {/* THE FOURTH PREREQUISITE, NOT RECORDED HERE: a promotional campaign is also held by
          `national_dnd_blocker`, per CAMPAIGN rather than per client, so it cannot be a
          field on this page — and three green prerequisites here would otherwise read as
          an open launch gate. */}
      <p className="max-w-prose text-body text-ink-muted">
        A <span className="font-medium text-ink">promotional</span> campaign needs one thing
        more, and it is recorded per campaign rather than per client: a national DND scrub,
        on{" "}
        <Link href={`/admin/tenants/${tenantId}/dnd-scrub`} className={LINK}>
          DND scrub
        </Link>
        . Without a current one it stays held whatever is green below.
      </p>

      <RestrictionNote reason={write.reason} />

      <Section
        title="Numbers"
        description="Marking a number registered records what the registrar decided. Recording a new number, and choosing which agent answers it, is on the numbers screen."
        action={
          <Link href={`/admin/tenants/${tenantId}/numbers`} className={TEXT_ACTION}>
            Record a number, or choose which agent answers it
          </Link>
        }
      >
        {setDlt.error && <ProblemNotice error={setDlt.error} />}
        {/* A failed read never prints "No numbers on file": that sentence has an operator
            ask a client who already has a number to go and get another. */}
        {numbers.error ? (
          <ProblemNotice error={numbers.error} onRetry={() => numbers.refetch()} />
        ) : numbers.isLoading || !numbers.data ? (
          <Skeleton rows={2} />
        ) : numbers.data.length === 0 ? (
          <EmptyState message="No numbers on file." />
        ) : (
          <ul className={HAIRLINE_LIST}>
            {numbers.data.map((number) => (
              <li key={number.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 text-body sm:px-2">
                {/* The client's OWN published business number — not a called party's,
                    which is the number hard rule 6 is about. */}
                <span className="font-mono text-ink">{formatPhone(number.e164)}</span>
                <StatusPill tone="neutral">{number.series}</StatusPill>
                <span className="text-meta text-ink-muted">{state(number.dlt_status)}</span>
                {number.dlt_status !== "registered" && (
                  <button
                    type="button"
                    className={`${SECONDARY_BUTTON_SM} ml-auto`}
                    disabled={setDlt.isPending || !write.allowed}
                    onClick={() => setDlt.mutate({ numberId: number.id, dltStatus: "registered" })}
                  >
                    Mark registered
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Voice templates"
        description={
          <>
            Templates registered with the <Term id="dlt" /> registrar, and the registrar&apos;s
            verdict on each.
          </>
        }
      >
        {register.error && <ProblemNotice error={register.error} />}
        {setStatus.error && <ProblemNotice error={setStatus.error} />}
        {templates.error ? (
          <ProblemNotice error={templates.error} onRetry={() => templates.refetch()} />
        ) : templates.isLoading || !templates.data ? (
          <Skeleton rows={2} />
        ) : templates.data.length === 0 ? (
          <EmptyState message="No templates registered." />
        ) : (
          <ul className={HAIRLINE_LIST}>
            {templates.data.map((template) => (
              <li key={template.id} className="py-3 text-body sm:px-2">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <StatusPill tone="neutral">{template.classification}</StatusPill>
                  <span className="text-meta text-ink-muted">{state(template.status)}</span>
                  {template.status !== "approved" && (
                    <button
                      type="button"
                      className={`${SECONDARY_BUTTON_SM} ml-auto`}
                      disabled={setStatus.isPending || !write.allowed}
                      onClick={() => setStatus.mutate({ templateId: template.id, status: "approved" })}
                    >
                      Registrar approved
                    </button>
                  )}
                </div>
                <p className="mt-1.5 max-w-prose text-ink">{template.body}</p>
              </li>
            ))}
          </ul>
        )}

        <form
          className="mt-8 max-w-xl space-y-4"
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
          <h3 className="text-body font-semibold text-ink">Register a template</h3>
          <div className="space-y-4">
            <div>
              <label htmlFor="template-classification" className={FIELD_LABEL}>
                Template classification
              </label>
              <select
                id="template-classification"
                value={classification}
                disabled={!write.allowed}
                onChange={(ev) => setClassification(ev.target.value as typeof classification)}
                className={FIELD}
              >
                <option value="promotional">promotional</option>
                <option value="service">service</option>
                <option value="transactional">transactional</option>
              </select>
            </div>
            <div>
              <label htmlFor="template-dlt-ref" className={FIELD_LABEL}>
                Registrar template id (optional)
              </label>
              <input
                id="template-dlt-ref"
                value={dltRef}
                disabled={!write.allowed}
                onChange={(ev) => setDltRef(ev.target.value)}
                className={`${FIELD} font-mono`}
              />
            </div>
          </div>
          <div>
            <label htmlFor={bodyField.id} className={FIELD_LABEL}>
              Template wording
            </label>
            <textarea
              {...bodyField}

              required
              minLength={10}
              rows={3}
              value={body}
              disabled={!write.allowed}
              onChange={(ev) => setBody(ev.target.value)}
              className={FIELD}
            />
            <span className={FIELD_HINT}>The exact wording registered with the registrar.</span>
            {templateValid.error("body")}
          </div>
          <div className="flex justify-end">
            <button
              type="submit"
              className={PRIMARY_BUTTON}
              disabled={register.isPending || !write.allowed}
            >
              Register template
            </button>
          </div>
        </form>
      </Section>

      <DltRegistrationPanel tenantId={tenantId} write={write} />
    </div>
  );
}
