"use client";

/**
 * WHATSAPP FROM YOUR OWN NUMBER — connecting the business's WhatsApp through Meta, its
 * state, its templates, and the paste-a-key path for a provider (D-784).
 *
 * PRIMARY JOB: get the owner's own WhatsApp connected so their agent can send a booking
 * confirmation or a payment link while the caller is on the line. One primary action:
 * "Connect WhatsApp", which opens Meta's own window. Before it, the screen says in plain
 * words what to have ready, what Meta's window will ask, and who pays Meta (the owner, on
 * their own card; Calevate adds nothing). Until Calevate's Meta set-up is finished, or this
 * week's Meta onboarding limit is used, the same space shows the provider-key guides instead
 * of a button that cannot work.
 *
 * The choices ask which of three people this is, because each needs a different flow:
 * new to WhatsApp Business; on the WhatsApp Business app (offered only when coexistence is
 * switched on for India); already on a provider such as AiSensy or Interakt (Meta's
 * grant-access first, a pasted key as the fallback).
 */

import { MessageCircle, Smartphone, Store } from "lucide-react";
import { useEffect, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { ChecklistRows, type ChecklistRow } from "@/components/console/checklist";
import { Chooser, ChooserItem } from "@/components/console/chooser";
import { IconTile } from "@/components/console/iconTile";
import { Section, TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { TaskSteps } from "@/components/interior/task-steps";
import { NoticeBox, ProblemNotice, Skeleton } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import {
  TEMPLATE_REVIEW_HOURS,
  accountState,
  useBeginSignup,
  useConnectWhatsApp,
  useDisconnectWhatsApp,
  useFinishWhatsApp,
  useWhatsApp,
  type SignupChoice,
  type WhatsAppAccount,
  type WhatsAppConnected,
  type WhatsAppSignup,
} from "@/lib/api/whatsapp";
import { prepareEmbeddedSignup, runEmbeddedSignup } from "@/lib/facebookSignup";

import { KeyGuides } from "./KeyGuides";
import { Templates } from "./Templates";

type GuideKind = "aisensy" | "interakt" | "meta_cloud";

/** What a refused or abandoned window means, in the owner's words. */
function cancelledWords(step: string | null): string {
  return step
    ? "You closed Meta's window. Nothing was connected."
    : "Meta's window closed early. Nothing was connected.";
}

const SETUP_STEPS = [
  { id: "meta", label: "Connected to Meta" },
  { id: "webhooks", label: "Calevate hears from Meta about this number" },
  { id: "number", label: "Number ready to send" },
  { id: "templates", label: "Standard messages sent to Meta for review" },
];

function setupProgress(account: WhatsAppAccount): { current: number; failed: boolean } {
  const done = [true, account.webhooks_subscribed, account.registered && account.status === "connected", account.templates_submitted];
  const current = done.findIndex((d) => !d);
  return { current: current < 0 ? done.length : current, failed: account.status === "needs_attention" };
}

export function WhatsAppSection({
  session,
  canWrite,
  onPasteKey,
}: {
  session: Session;
  canWrite: boolean;
  onPasteKey: (kind: GuideKind) => void;
}) {
  const overview = useWhatsApp(session);
  const [choice, setChoice] = useState<SignupChoice | null>(null);
  const [showKeys, setShowKeys] = useState(false);
  const [connected, setConnected] = useState<WhatsAppConnected | null>(null);

  if (overview.isPending) {
    return (
      <Section title="WhatsApp from your own number" headingLevel={2}>
        <Skeleton rows={3} />
      </Section>
    );
  }
  if (overview.isError) {
    return (
      <Section title="WhatsApp from your own number" headingLevel={2}>
        <ProblemNotice error={overview.error} onRetry={() => void overview.refetch()} />
      </Section>
    );
  }

  const { setup, accounts } = overview.data;
  const live = accounts.filter((a) => a.status !== "disconnected");

  return (
    <Section
      title="WhatsApp from your own number"
      headingLevel={2}
      description="Send confirmations and payment links during calls."
    >
      <div className="space-y-8">
        {connected?.pin && (
          <NoticeBox tone="ok" title="Save your WhatsApp PIN now" role="status">
            <span className="block">
              Your number&rsquo;s two-step PIN is{" "}
              <strong className="font-mono text-ink tabular-nums tracking-[0.2em]">{connected.pin}</strong>. Keep it
              safe. We can&rsquo;t show it again.
            </span>
          </NoticeBox>
        )}

        {live.map((account) => (
          <ConnectedAccount key={account.id} session={session} account={account} canWrite={canWrite} paymentUrl={setup.payment_method_url} />
        ))}

        {live.length === 0 && (
          <div className="space-y-6">
            {!setup.available ? (
              <NoticeBox
                tone="neutral"
                title={
                  setup.reason === "weekly_limit"
                    ? "This week's Meta connections are used up."
                    : "Connecting through Meta is not switched on yet."
                }
              >
                Use a key from your provider below.
              </NoticeBox>
            ) : choice === null ? (
              <Chooser label="How do you use WhatsApp for your business today?">
                <ChooserItem
                  icon={<MessageCircle className="h-5 w-5" />}
                  title="I'm new to WhatsApp Business"
                  description="Use a mobile number that is not on WhatsApp yet."
                  disabled={!canWrite}
                  onSelect={() => setChoice("new")}
                />
                {setup.coexistence && (
                  <ChooserItem
                    icon={<Smartphone className="h-5 w-5" />}
                    title="I use the WhatsApp Business app and want to keep it"
                    description="Keep chatting on your phone. Your agent only sends."
                    disabled={!canWrite}
                    onSelect={() => setChoice("business_app")}
                  />
                )}
                <ChooserItem
                  icon={<Store className="h-5 w-5" />}
                  title="I already send WhatsApp through another company"
                  description="Like AiSensy or Interakt."
                  disabled={!canWrite}
                  onSelect={() => setChoice("grant_access")}
                />
              </Chooser>
            ) : (
              <ConnectFlow
                session={session}
                choice={choice}
                pricingUrl={setup.pricing_url}
                onBack={() => setChoice(null)}
                onConnected={setConnected}
                onShowKeys={() => setShowKeys(true)}
              />
            )}

            {(!setup.available || choice === "grant_access" || showKeys) && (
              <Section
                headingLevel={3}
                title="Connect with a key from your provider"
                description="Paste it once. We never show it again."
              >
                <KeyGuides canWrite={canWrite} onPasteKey={onPasteKey} />
              </Section>
            )}
            {setup.available && choice === null && !showKeys && (
              <button type="button" className={TEXT_ACTION} onClick={() => setShowKeys(true)}>
                Use a key from your provider instead
              </button>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

function ConnectFlow({
  session,
  choice,
  pricingUrl,
  onBack,
  onConnected,
  onShowKeys,
}: {
  session: Session;
  choice: SignupChoice;
  pricingUrl: string;
  onBack: () => void;
  onConnected: (result: WhatsAppConnected) => void;
  onShowKeys: () => void;
}) {
  const begin = useBeginSignup(session);
  const connect = useConnectWhatsApp(session);
  // Both failures render as ProblemNotice above the button.
  const beginFeedback = useActionFeedback(begin, { errorDisplay: "inline" });
  const connectFeedback = useActionFeedback(connect, { errorDisplay: "inline" });
  const [phase, setPhase] = useState<"ready" | "meta" | "saving">("ready");
  const [notice, setNotice] = useState<string | null>(null);

  // Ask for the state and load Meta's SDK as soon as the owner picks how they connect, so the
  // click on Connect opens Meta's window at once: a browser blocks a pop-up opened after a
  // network round trip. A state is spent by a connect attempt, so one is fetched again after.
  const { mutateAsync: beginSignup } = begin;
  const [prepared, setPrepared] = useState<WhatsAppSignup | null>(null);
  const [round, setRound] = useState(0);
  useEffect(() => {
    let live = true;
    beginSignup(choice)
      .then((signup) => {
        if (!live) return;
        setPrepared(signup);
        void prepareEmbeddedSignup(signup.app_id, signup.graph_version).catch(() => undefined);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [beginSignup, choice, round]);

  const start = async () => {
    if (!prepared) return;
    setNotice(null);
    setPhase("meta");
    const outcome = await runEmbeddedSignup({
      appId: prepared.app_id,
      configId: prepared.config_id,
      graphVersion: prepared.graph_version,
      extras: prepared.extras,
    });
    if (outcome.kind === "cancelled") {
      setPhase("ready");
      setNotice(cancelledWords(outcome.step));
      return;
    }
    if (outcome.kind === "failed") {
      setPhase("ready");
      setNotice(`Meta stopped the connection: ${outcome.message} Nothing was connected.`);
      return;
    }
    setPhase("saving");
    connect.mutate(
      { state: prepared.state, ...outcome.result },
      {
        onSuccess: (result) => onConnected(result),
        onSettled: () => {
          setPhase("ready");
          setPrepared(null);
          setRound((r) => r + 1);
        },
      },
    );
  };

  const isExisting = choice === "grant_access";
  return (
    <div className="max-w-2xl space-y-5">
      <button type="button" className={TEXT_ACTION} onClick={onBack}>
        ← Other ways to connect
      </button>

      <div>
        <h3 className="text-body font-semibold text-ink">Have these ready</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-body text-ink">
          <li>Your Facebook login.</li>
          {choice === "new" && (
            <li>A SIM number in your hand, not on WhatsApp yet.</li>
          )}
          {choice === "business_app" && <li>The WhatsApp Business app, updated.</li>}
          {isExisting && <li>Admin access to your provider&rsquo;s WhatsApp account.</li>}
          <li>A card for Meta. Meta charges you for each message; Calevate adds nothing.</li>
        </ul>
      </div>

      <div>
        <h3 className="text-body font-semibold text-ink">What happens</h3>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-body text-ink">
          <li>In Meta&rsquo;s window, sign in and pick your business.</li>
          {choice === "new" && <li>Enter your number, the code, and your business name.</li>}
          {isExisting && <li>Pick your WhatsApp account, if Meta offers it.</li>}
          <li>Back here, we set up your number and messages.</li>
          <li>
            In WhatsApp Manager, add your card so Meta can bill you. Meta reviews messages in up to{" "}
            {TEMPLATE_REVIEW_HOURS} hours.
          </li>
        </ol>
      </div>

      <p className="text-meta text-ink-muted">
        Meta bills you directly, per message, at its own prices.{" "}
        <a href={pricingUrl} target="_blank" rel="noreferrer" className="underline underline-offset-2">
          See Meta&rsquo;s prices
        </a>
        .
      </p>

      {notice && (
        <NoticeBox tone="warn" title={notice} role="status">
          {isExisting ? (
            <button type="button" className={TEXT_ACTION} onClick={onShowKeys}>
              Paste a key instead
            </button>
          ) : null}
        </NoticeBox>
      )}
      {/* Retrying asks for a fresh state; without it the Connect button stayed disabled for
          good after one failed preparation. */}
      {begin.isError && <ProblemNotice error={begin.error} onRetry={() => setRound((r) => r + 1)} />}
      {connect.isError && <ProblemNotice error={connect.error} />}
      {phase === "meta" && (
        <p className="flex flex-wrap items-center gap-x-4 text-body text-ink-muted" role="status">
          Waiting for Meta&rsquo;s window…
          {/* A blocked pop-up never answers: the owner can always start over. */}
          <button type="button" className={TEXT_ACTION} onClick={() => setPhase("ready")}>
            Meta&rsquo;s window did not open
          </button>
        </p>
      )}
      {phase === "saving" && <p className="text-body text-ink-muted" role="status">Getting your number ready…</p>}

      <div className="flex justify-end">
        <ActionButton
          // Getting ready, Meta's window and the save after it are one action to the owner.
          status={
            phase !== "ready" || (!prepared && beginFeedback.status === "pending")
              ? "pending"
              : connectFeedback.status
          }
          disabled={!prepared && beginFeedback.status !== "pending"}
          pendingLabel={phase === "saving" ? "Getting your number ready…" : beginFeedback.status === "pending" ? "Getting ready…" : undefined}
          successLabel="Connected"
          onClick={() => void start()}
        >
          {isExisting ? "Give Calevate access through Meta" : "Connect WhatsApp"}
        </ActionButton>
      </div>
    </div>
  );
}

function ConnectedAccount({
  session,
  account,
  canWrite,
  paymentUrl,
}: {
  session: Session;
  account: WhatsAppAccount;
  canWrite: boolean;
  paymentUrl: string;
}) {
  const finish = useFinishWhatsApp(session);
  const disconnect = useDisconnectWhatsApp(session);
  const finishFeedback = useActionFeedback(finish, { errorDisplay: "inline" });
  const disconnectFeedback = useActionFeedback(disconnect, { errorDisplay: "inline" });
  const [confirming, setConfirming] = useState(false);
  const state = accountState(account);
  const progress = setupProgress(account);
  const nameApproved = account.name_status === "APPROVED" || account.name_status === "AVAILABLE_WITHOUT_REVIEW";

  const rows: ChecklistRow[] = [
    {
      id: "card",
      label: "Add a card in Meta",
      status: "waiting",
      statusText: "Do this in Meta",
      info: "Meta bills each message to this card. We can't see if it's added.",
      action: (
        <a href={paymentUrl} target="_blank" rel="noreferrer" className={TEXT_ACTION}>
          Open WhatsApp Manager
        </a>
      ),
    },
    {
      id: "name",
      label: "Business name approved",
      status: nameApproved ? "done" : account.name_status === "DECLINED" ? "blocked" : "waiting",
      statusText: nameApproved ? "Approved" : account.name_status === "DECLINED" ? "Declined by Meta" : "In review",
      info: "Customers see this name on your messages. Meta reviews it.",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-4">
          <IconTile service="whatsapp" />
          <div className="min-w-0">
            <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">
              {account.verified_name ?? "Your WhatsApp"}
            </p>
            <p className="text-meta text-ink-muted">
              {account.display_phone_number ?? "Number being set up"}
              {account.quality_rating ? ` · Quality ${account.quality_rating.toLowerCase()}` : ""}
            </p>
          </div>
        </div>
        <span className="flex flex-wrap items-center gap-4">
          <StatusPill tone={state.tone}>{state.text}</StatusPill>
          <button type="button" className={TEXT_ACTION_DANGER} disabled={!canWrite} onClick={() => setConfirming(true)}>
            Disconnect
          </button>
        </span>
      </div>

      {account.status !== "connected" || !account.templates_submitted ? (
        <div className="max-w-sm space-y-3">
          <TaskSteps steps={SETUP_STEPS} current={progress.current} failed={progress.failed} label="WhatsApp set-up" />
          {account.status === "needs_attention" && (
            <div className="space-y-2">
              <p className="text-body text-ink">
                {account.account_alert
                  ? "Meta found a problem. Check Meta Business Suite."
                  : "One step did not finish. Nothing was charged."}
              </p>
              <ActionButton
                variant="secondary-sm"
                status={finishFeedback.status}
                disabled={!canWrite}
                onClick={() => finishFeedback.run(account.id)}
                pendingLabel="Trying again…"
                successLabel="Finished"
              >
                Finish set-up
              </ActionButton>
              {finish.isError && <ProblemNotice error={finish.error} />}
            </div>
          )}
        </div>
      ) : null}

      <ChecklistRows heading="Finish in Meta" rows={rows} />

      {account.status === "connected" && <Templates session={session} account={account} canWrite={canWrite} />}

      {confirming && (
        <ConfirmDialog
          title="Disconnect this WhatsApp number?"
          confirmLabel="Disconnect"
          pendingLabel="Disconnecting…"
          successLabel="Disconnected"
          status={disconnectFeedback.status}
          error={disconnect.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() => disconnect.mutate(account.id, { onSuccess: () => setConfirming(false) })}
        >
          <p>Your agents stop sending from this number now.</p>
          <p>Your number and templates stay yours in Meta.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
