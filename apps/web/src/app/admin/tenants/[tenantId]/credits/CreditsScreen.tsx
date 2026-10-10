"use client";

import { useState } from "react";
import {
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import { Chooser, ChooserItem } from "@/components/console/chooser";
import { Drawer } from "@/components/console/drawer";
import { PageHeader } from "@/components/console/pageHeader";
import { useAdminAccess } from "@/app/admin/access";
import { adminSession, useTenant } from "@/lib/api/admin";
import {
  useCredits,
  useRecordAdjustment,
  useRecordRestatement,
  useRecordTopUp,
  type Credits,
} from "@/lib/api/credits";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { ACT_TITLE, type Act } from "./acts";
import { CorrectionForm } from "./CorrectionForm";
import { GrantPanel } from "./GrantPanel";
import { OverrideForm } from "./OverrideForm";
import { RecordForm } from "./RecordForm";
import { RefundPanel } from "./RefundPanel";
import { RestatementForm } from "./RestatementForm";
import { TrialPanel } from "./TrialPanel";
import { WalletHistory } from "./WalletHistory";
import { CorrectionCard, LedgerUnreadable, WalletSummary } from "./WalletSummary";

/**
 * CREDITS — keep this client's wallet right: see what is on it, record money that arrived,
 * and repair a wrong entry by appending one.
 *
 * The wallet and its history are the screen; every write opens in a drawer over it, one at
 * a time, so the ledger an operator is about to append to stays in view behind the form.
 * Each form keeps its double keying, its typed confirmation and its blast radius above its
 * button exactly as before — moving a control into a drawer changes where it is, never what
 * it asks of the person pressing it.
 *
 * THE WRITES ARE WITHHELD WHEN THE LEDGER CANNOT BE READ. A failed read must not render as
 * "nothing on this wallet" (also a REAL state, and the one an operator acts on by
 * crediting), and a write form over a ledger nobody can see removes the check that catches
 * a payment a colleague recorded ten minutes ago. So `unreadable` renders no write control.
 *
 * The three money mutations live HERE rather than inside their forms: a successful write
 * invalidates the read, and a mutation held in a form the re-read remounts would lose its
 * own receipt at the moment the write landed.
 */
export function CreditsScreen({ tenantId }: { tenantId: string }) {
  // The tenant layout has already resolved this read; a cache hit.
  const tenant = useTenant(tenantId).data;
  const ledger = useCredits(adminSession(), tenantId);
  const save = useRecordTopUp(adminSession(), tenantId);
  const correct = useRecordAdjustment(adminSession(), tenantId);
  const restate = useRecordRestatement(adminSession(), tenantId);
  // All `admin:tenants`, each with its own sentence: a restriction note has to name the
  // control it sits under, or an operator cannot tell which button it is about.
  const write = useAdminAccess("admin:tenants", "record a payment on this client's wallet");
  const amend = useAdminAccess("admin:tenants", "correct an entry on this client's wallet");
  const uprate = useAdminAccess("admin:tenants", "restate a payment on this client's wallet");
  const reprice = useAdminAccess(
    "admin:tenants",
    "sell one of this client's lots at another pack's rates",
  );
  const [act, setAct] = useState<Act | null>(null);

  const state = ledgerState(ledger);

  /*
   * THE SCREEN, DECLARED TO THE ASSISTANT: who and what is on the wallet. The top-up form
   * pushes its own surface (with its money fields read-only) while its drawer is open; this
   * one is what is left when no write is open.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/credits",
    title: "Credits",
    realm: "admin",
    fields: [],
    facts:
      state.status === "read"
        ? [
            { key: "client", label: "Client", value: tenant?.name ?? "not read yet" },
            { key: "balance_inr", label: "Calling credit on the ledger now (₹)", value: state.wallet.balance_inr },
            { key: "paid_inr", label: "Paid for, lifetime (₹)", value: state.wallet.paid_inr },
            { key: "granted_inr", label: "Given, lifetime (₹)", value: state.wallet.granted_inr },
            { key: "is_low", label: "Below the low-balance line", value: state.wallet.is_low ? "yes" : "no" },
          ]
        : [
            { key: "client", label: "Client", value: tenant?.name ?? "not read yet" },
            {
              key: "wallet",
              label: "The wallet",
              value: state.status === "unreadable" ? "could not be read" : "still loading",
            },
          ],
    apply: noFill,
  });

  // Tests render this page without the tenant layout; the layout owns the real guards.
  if (!tenant) return <Skeleton rows={6} />;
  const clientName = tenant.name;

  return (
    <div className="max-w-4xl space-y-10">
      <PageHeader
        title="Credits"
        description="Every line is permanent: a mistake is fixed by adding an entry, never by changing one."
      />

      {ledger.error && <ProblemNotice error={ledger.error} onRetry={() => ledger.refetch()} />}

      {state.status === "loading" ? (
        <Skeleton rows={6} />
      ) : state.status === "unreadable" ? (
        <LedgerUnreadable />
      ) : (
        <>
          <WalletSummary
            wallet={state.wallet}
            tenant={tenant}
            actions={
              <>
                <button
                  type="button"
                  className={SECONDARY_BUTTON}
                  onClick={() => setAct({ kind: "choose" })}
                >
                  Fix or adjust
                </button>
                <button
                  type="button"
                  className={PRIMARY_BUTTON}
                  onClick={() => setAct({ kind: "record" })}
                >
                  Record a payment
                </button>
              </>
            }
          />
          <TrialPanel tenantId={tenantId} clientName={clientName} />
          <WalletHistory wallet={state.wallet} onAct={setAct} />

          <Drawer
            open={act !== null}
            onClose={() => setAct(null)}
            title={act ? ACT_TITLE[act.kind] : ""}
            description={clientName}
            width="lg"
          >
            {act && (
              <ActBody
                act={act}
                wallet={state.wallet}
                tenantId={tenantId}
                clientName={clientName}
                onAct={setAct}
                mutations={{ save, correct, restate }}
                access={{ write, amend, uprate, reprice }}
              />
            )}
          </Drawer>
        </>
      )}

      {/* On every branch: it depends on no read, and the operator most likely to need it is
          the one who has just credited the wrong account and come back to a screen that
          will not load. */}
      <CorrectionCard />
    </div>
  );
}

/**
 * The wallet as this screen may know it — three states, never a fourth. A balance of ₹0 and
 * a balance we could not read are OPPOSITE facts, and `Credits | undefined` collapses them.
 * Error FIRST: a refetch that fails leaves the previous `data` in place, and a stale balance
 * rendered as the current one is the same lie as an invented one.
 */
type LedgerState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; wallet: Credits };

function ledgerState(query: { data: Credits | undefined; isError: boolean }): LedgerState {
  if (query.isError) return { status: "unreadable" };
  if (!query.data) return { status: "loading" };
  return { status: "read", wallet: query.data };
}

type Access = ReturnType<typeof useAdminAccess>;

function ActBody({
  act,
  wallet,
  tenantId,
  clientName,
  onAct,
  mutations,
  access,
}: {
  act: Act;
  wallet: Credits;
  tenantId: string;
  clientName: string;
  onAct: (act: Act) => void;
  mutations: {
    save: ReturnType<typeof useRecordTopUp>;
    correct: ReturnType<typeof useRecordAdjustment>;
    restate: ReturnType<typeof useRecordRestatement>;
  };
  access: { write: Access; amend: Access; uprate: Access; reprice: Access };
}) {
  switch (act.kind) {
    case "choose":
      return <FixChooser wallet={wallet} onAct={onAct} />;
    case "record":
      return (
        <RecordForm
          clientName={clientName}
          wallet={wallet}
          save={mutations.save}
          write={access.write}
        />
      );
    case "correct":
      return (
        <CorrectionForm
          clientName={clientName}
          wallet={wallet}
          correct={mutations.correct}
          write={access.amend}
          initialEntryId={act.entryId}
        />
      );
    case "restate":
      return (
        <RestatementForm
          clientName={clientName}
          wallet={wallet}
          restate={mutations.restate}
          write={access.uprate}
          initialPaymentRef={act.paymentRef}
        />
      );
    case "refund":
      return (
        <RefundPanel
          clientName={clientName}
          wallet={wallet}
          tenantId={tenantId}
          session={adminSession()}
          initialPaymentRef={act.paymentRef}
        />
      );
    case "grant":
      return (
        <GrantPanel
          clientName={clientName}
          wallet={wallet}
          tenantId={tenantId}
          session={adminSession()}
        />
      );
    case "reprice":
      return (
        <OverrideForm
          lots={wallet.lots}
          packs={wallet.override_packs}
          tenantId={tenantId}
          write={access.reprice}
          clientName={clientName}
          initialLotId={act.lotId}
        />
      );
  }
}

/**
 * WHICH WRITE, by the mistake or the decision in front of the operator. Each opens the same
 * form a row's menu opens, without a row chosen. An act with nothing to act on still opens:
 * its form says why in its own words rather than leaving a dead button to guess at.
 */
function FixChooser({ wallet, onAct }: { wallet: Credits; onAct: (act: Act) => void }) {
  const choices: { act: Act; line: string }[] = [
    { act: { kind: "correct" }, line: "Too much was credited — the wrong client, or more than arrived." },
    { act: { kind: "restate" }, line: "Too little was credited against a bank transfer." },
    { act: { kind: "refund" }, line: "Send a captured payment back through the payment provider." },
    { act: { kind: "grant" }, line: "Credit with no payment behind it, audited." },
    ...(wallet.lots.length > 0
      ? [{ act: { kind: "reprice" } as Act, line: "Make the minutes in one lot cheaper." }]
      : []),
  ];
  return (
    <Chooser label="What needs fixing">
      {choices.map(({ act, line }) => (
        <ChooserItem
          key={act.kind}
          title={ACT_TITLE[act.kind]}
          description={line}
          onSelect={() => onAct(act)}
        />
      ))}
    </Chooser>
  );
}
