"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { StatusPill } from "@/components/admin/kit";
import { Section } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import {
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { Drawer } from "@/components/console/drawer";
import { PageHeader } from "@/components/console/pageHeader";
import { useAdminAccess } from "@/app/admin/access";
import { adminSession, useTenant } from "@/lib/api/admin";
import {
  termsStateCopy,
  useCommercialTerms,
  useRecordTerms,
  type PlanRow,
} from "@/lib/api/commercials";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { PlatformFeePanel } from "./PlatformFeePanel";
import { TermsForm } from "./TermsForm";
import { money, rate, secondOverageRate } from "./termsFormat";

/**
 * COMMERCIALS — how this client is billed, and on what terms.
 *
 * THE ONE RULE THIS SCREEN KEEPS: **a price change is a NEW DATED ROW.** An invoice is a
 * derived statement — re-rendering July reads `plans` again — so editing the row that priced
 * July would silently rewrite a bill already paid. There is no edit control anywhere: the
 * drawer always records a new agreement and the API refuses a row dated into a closed month.
 *
 * The billing MOTION is read off the client's directory row rather than off `plans`, so it is
 * answerable — and changeable — when the agreement read fails; it sits outside that read.
 *
 * §52 on every branch: loading is a skeleton, failure is a refusal, and neither is a number,
 * a state or an empty state. A failed read must never render as "no terms" — that is also a
 * real, actionable state — and it withholds the write.
 */
export function CommercialsScreen({ tenantId }: { tenantId: string }) {
  const tenant = useTenant(tenantId).data;
  const terms = useCommercialTerms(adminSession(), tenantId);
  // Hoisted: a successful write invalidates the read, and a mutation held in a form that
  // the re-read remounts would lose its own receipt.
  const save = useRecordTerms(adminSession(), tenantId);
  const write = useAdminAccess("admin:tenants", "record commercial terms");
  const [open, setOpen] = useState(false);
  const inEffect = terms.data?.in_effect ?? null;

  if (!tenant) return <Skeleton rows={6} />;

  return (
    <div className="max-w-4xl space-y-10">
      <PageHeader
        title="Commercials"
        description="Every client buys prepaid credits at the list price. Here: the monthly platform fee for this client, and the ceilings and model surcharge it is held to. Every change is a new dated agreement."
        actions={
          terms.data ? (
            <button type="button" className={PRIMARY_BUTTON} onClick={() => setOpen(true)}>
              Agree new terms
            </button>
          ) : undefined
        }
      />

      <PlatformFeePanel tenantId={tenantId} />

      {terms.error && <ProblemNotice error={terms.error} onRetry={() => terms.refetch()} />}

      {terms.isLoading ? (
        <Skeleton rows={5} />
      ) : !terms.data ? (
        /* WITHHELD, not merely unpopulated: recording terms while the current agreement is
           unreadable writes a ceiling and a rate without knowing what they supersede. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot record terms while the current agreement is unreadable"
        >
          <p className="mt-1 text-meta opacity-90">
            We could not read what is in effect for this client. Recording new terms now
            would supersede an agreement nobody can see — including, possibly, a spend
            ceiling. Retry the read above; the form comes back with it.
          </p>
        </NoticeBox>
      ) : (
        <>
          <TermsFacts inEffect={inEffect} />
          <StateBanner state={terms.data.state} />
          <InEffect row={inEffect} />
          <History rows={terms.data.history} inEffectId={inEffect?.id ?? null} />
          <Drawer
            open={open}
            onClose={() => setOpen(false)}
            title="Agree new terms"
            description={tenant.name}
            width="lg"
          >
            <TermsForm
              key={inEffect?.id ?? "none"}
              save={save}
              inEffect={inEffect}
              confirmation={terms.data.loosening_confirmation}
              write={write}
            />
          </Drawer>
        </>
      )}
    </div>
  );
}

/**
 * THE TERMS IN EFFECT, DECLARED TO THE ASSISTANT once the agreement has been read, whether
 * or not the form is open. `?? 0` on the allowance would assert a term nobody agreed: an
 * absent allowance and an allowance of zero are different terms.
 */
function TermsFacts({ inEffect }: { inEffect: PlanRow | null }) {
  useCopilotSurface({
    route: "/admin/tenants/{id}/commercials",
    title: "Commercial terms",
    realm: "admin",
    fields: [],
    facts: [
      {
        key: "in_effect",
        label: "Terms in effect now",
        value:
          inEffect === null
            ? "none recorded"
            : `AI model surcharge ${rate(inEffect.llm_model_surcharge_inr) ?? "none"}/min, ` +
              (inEffect.hard_cap_minutes === null
                ? "no minute ceiling"
                : `minute ceiling ${inEffect.hard_cap_minutes}`),
      },
    ],
    apply: noFill,
  });
  return null;
}

function StateBanner({ state }: { state: string }) {
  const copy = termsStateCopy(state);
  return (
    <NoticeBox tone={copy.tone} icon={<AlertTriangle className="h-5 w-5" />} title={copy.label}>
      <p className="mt-1 text-meta opacity-90">{copy.detail}</p>
    </NoticeBox>
  );
}

function InEffect({ row }: { row: PlanRow | null }) {
  if (!row) return null;
  // Unset terms are ABSENT, never zero: a rate of ₹0 is free minutes, an unset rate is a
  // plan that quotes none.
  const rows: { label: string; value: string | null }[] = [
    // Retainer terms ended with D-707; a row written before then still shows them.
    { label: "Setup fee (retired)", value: money(row.setup_fee_inr) },
    { label: "Monthly retainer (retired)", value: money(row.monthly_fee_inr) },
    { label: "Included minutes", value: row.included_minutes === null ? null : String(row.included_minutes) },
    // Named for the COLUMN, not a tier: `overage_rate_second` is a founder pricing lever,
    // "independent of the single voice quality" (`billing/service.py::OverageRung`).
    { label: "Base overage rate / min", value: rate(row.overage_rate_inr) },
    { label: "Second overage rate / min", value: rate(secondOverageRate(row)) },
    // D-455: added for the minutes this client's OWN model choice upgraded.
    { label: "AI model surcharge / min", value: rate(row.llm_model_surcharge_inr) },
    { label: "Spend ceiling (ours)", value: money(row.hard_cap_spend_inr) },
    { label: "Minute ceiling (ours)", value: row.hard_cap_minutes === null ? null : String(row.hard_cap_minutes) },
    { label: "Client's own spend cap", value: money(row.client_cap_spend_inr) },
    { label: "Concurrent calls", value: String(row.concurrency_ceiling) },
    { label: "In effect from", value: row.effective_from ? formatIST(row.effective_from) : "always" },
    { label: "Until", value: row.effective_to ? formatIST(row.effective_to) : "further notice" },
  ].filter((entry) => entry.value !== null);

  return (
    <Section
      title="In effect now"
      info="Unset fields are absent rather than zero: a rate of ₹0 is free minutes, an unset rate is a plan that quotes none."
    >
      <SettingRows className="border-y border-line">
        {rows.map((entry) => (
          <SettingRow
            key={entry.label}
            label={entry.label}
            value={<span className="tabular-nums">{entry.value}</span>}
          />
        ))}
      </SettingRows>
    </Section>
  );
}

/**
 * The effective-dated history an invoice is re-derived from. BOTH overage columns, because a
 * plan can quote either alone, and the model surcharge (D-455), because it is part of the
 * price: a column missing here is a rate change invisible on the one screen that exists to
 * show rates changing. `—` for NULL — "₹0.0000" would read as a decided price of zero.
 */
function History({ rows, inEffectId }: { rows: PlanRow[]; inEffectId: string | null }) {
  if (rows.length === 0) return null;
  const columns: DataColumn<PlanRow>[] = [
    {
      id: "from",
      header: "From",
      cell: (row) => (
        <span className="whitespace-nowrap">
          {row.effective_from ? formatIST(row.effective_from) : "always"}
          {row.id === inEffectId && (
            <StatusPill tone="ok" className="ml-2">
              In effect
            </StatusPill>
          )}
        </span>
      ),
    },
    { id: "until", header: "Until", cell: (row) => (row.effective_to ? formatIST(row.effective_to) : "—") },
    { id: "retainer", header: "Retainer (retired)", align: "right", cell: (row) => money(row.monthly_fee_inr) ?? "—" },
    {
      id: "included",
      header: "Included",
      align: "right",
      cell: (row) => (row.included_minutes === null ? "—" : row.included_minutes),
    },
    { id: "base", header: "Base overage / min", align: "right", cell: (row) => rate(row.overage_rate_inr) ?? "—" },
    { id: "second", header: "Second overage / min", align: "right", cell: (row) => rate(secondOverageRate(row)) ?? "—" },
    { id: "surcharge", header: "Model surcharge / min", align: "right", cell: (row) => rate(row.llm_model_surcharge_inr) ?? "—" },
    { id: "recorded", header: "Recorded", cell: (row) => <span className="whitespace-nowrap">{formatIST(row.created_at)}</span> },
  ];
  return (
    <Section
      title="Every agreement, newest first"
      info="Nothing here is editable, and that is the point: an invoice is re-derived from these rows every time anyone opens it, so a change to one would rewrite a statement the client has already paid."
    >
      <DataTable
        rows={rows}
        columns={columns}
        getRowId={(row) => row.id}
        label="Dated agreements, newest first"
      />
    </Section>
  );
}

