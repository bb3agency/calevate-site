"use client";

import { Section } from "@/components/console/section";

import { useState } from "react";
import Link from "next/link";
import { PhoneCall } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Field } from "@/components/arc/field";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import {
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import {
  INDIA_MOBILE,
  normaliseIndianMobile,
  useDecideProposal,
  useFallbackPhone,
  useHealerProposals,
  useLineIncidents,
  useRestoreLine,
  useSetFallbackPhone,
  type HealerProposal,
  type LineIncident,
} from "@/lib/api/healer";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { StatusPill } from "@/components/console/statusPill";

/**
 * What callers get when an agent cannot take calls properly, and what went wrong lately.
 *
 * Three parts, in the order an owner needs them: the backup phone (set it before it is
 * needed), problems with their lines (each in the server's own three sentences: what
 * happened, what we did, what they need to do), and suggested fixes for a struggling
 * agent, which change nothing until approved.
 */
export function LineProtectionScreen() {
  const { session, href } = useClientRealm();
  const slug = session.orgSlug;
  const write = useWriteAccess(session, "org:manage", "change line protection");
  return (
    <div className="max-w-2xl space-y-6 pb-12">
      <PageHeader description="What your callers get if your agent cannot take calls properly." />
      <RestrictionNote reason={write.reason} />
      <BackupPhone session={session} allowed={write.allowed} />
      <Problems session={session} slug={slug} href={href} allowed={write.allowed} />
      <Suggestions session={session} slug={slug} href={href} allowed={write.allowed} />
    </div>
  );
}

type Realm = ReturnType<typeof useClientRealm>;

function BackupPhone({ session, allowed }: { session: Realm["session"]; allowed: boolean }) {
  const phone = useFallbackPhone(session);
  const save = useSetFallbackPhone(session);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  // One write sets or clears the phone; its face shows on the button that was pressed.
  const [pressed, setPressed] = useState<"save" | "remove">("save");
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft ?? phone.data?.phone_e164 ?? "";
  const normalised = normaliseIndianMobile(value);
  const invalid = value.trim() !== "" && !INDIA_MOBILE.test(normalised);

  return (
    <Section title="Backup phone">
      {phone.error != null && <ProblemNotice error={phone.error} onRetry={() => phone.refetch()} />}
      {phone.isLoading ? (
        <Skeleton rows={2} label="Loading your backup phone" />
      ) : phone.data === undefined ? (
        // A failed first read: the notice above says so. An empty form here would claim
        // no backup phone is set and invite overwriting one that is.
        null
      ) : (
        <form
          noValidate
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (invalid || normalised === "") return;
            setPressed("save");
            save.mutate(normalised, { onSuccess: () => setDraft(null) });
          }}
        >
          <p className="text-body text-ink-muted">
            {phone.data?.forwarding_supported
              ? "If your agent stops working, we pass callers to this phone while we fix it."
              : "If your agent stops working, callers hear a short “try again later” message."}
          </p>
          <Field
            id="backup-phone"
            label="Indian mobile number"
            hint="Starts with +91. Use a mobile your team answers."
            error={invalid ? "Enter an Indian mobile number, like +91 98765 43210." : null}
          >
            {(control) => (
              <input
                {...control}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                className={FIELD}
                value={value}
                disabled={!allowed || save.isPending}
                placeholder="+91 98765 43210"
                onChange={(event) => setDraft(event.target.value)}
              />
            )}
          </Field>
          {save.error != null && <ProblemNotice error={save.error} />}
          <div className="flex flex-wrap gap-2">
            <ActionButton
              type="submit"
              status={pressed === "save" ? saveFeedback.status : "idle"}
              successLabel="Saved"
              disabled={
                !allowed || invalid || normalised === "" || (pressed === "remove" && save.isPending)
              }
            >
              Save backup phone
            </ActionButton>
            {phone.data?.phone_e164 && (
              <ActionButton
                variant="secondary"
                status={pressed === "remove" ? saveFeedback.status : "idle"}
                successLabel="Removed"
                disabled={!allowed || (pressed === "save" && save.isPending)}
                onClick={() => {
                  setPressed("remove");
                  save.mutate(null, { onSuccess: () => setDraft(null) });
                }}
              >
                Remove
              </ActionButton>
            )}
          </div>
        </form>
      )}
    </Section>
  );
}

function Problems({
  session,
  slug,
  href,
  allowed,
}: {
  session: Realm["session"];
  slug: string;
  href: Realm["href"];
  allowed: boolean;
}) {
  const incidents = useLineIncidents(session);
  const restore = useRestoreLine(session);
  // The dialog shows a refusal inside itself and closes on success, so the success is said
  // in a toast where the person is still looking.
  const restoreFeedback = useActionFeedback(restore, {
    errorDisplay: "inline",
    successToast: "Your line is back on",
  });
  const [confirming, setConfirming] = useState<LineIncident | null>(null);

  return (
    <Section title="Problems with your lines">
      {incidents.error != null && (
        <ProblemNotice error={incidents.error} onRetry={() => incidents.refetch()} />
      )}
      {incidents.isLoading ? (
        <Skeleton rows={3} label="Checking your lines" />
      ) : !incidents.data ? null : incidents.data.items.length === 0 ? (
        <EmptyState message="No problems in the last 30 days." />
      ) : (
        <ul className="divide-y divide-line">
          {incidents.data.items.map((item) => (
            <li key={item.id} className="space-y-2 py-4 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-body font-semibold text-ink">{item.headline}</h3>
                <StatePill open={item.state === "open"} />
              </div>
              <p className="text-meta text-ink-faint">
                {item.state === "open" ? "Since" : "From"} {formatIST(item.opened_at)}
                {item.resolved_at && <> to {formatIST(item.resolved_at)}</>}
              </p>
              <dl className="space-y-1 text-body">
                <Sentence term="What happened" text={item.what_happened} />
                <Sentence term="What we did" text={item.what_we_did} />
                <Sentence term="What you need to do" text={item.your_part} />
              </dl>
              {item.call_backs.length > 0 && (
                <div>
                  <p className="text-body font-medium text-ink">Callers to ring back</p>
                  <ul className="mt-1 space-y-1">
                    {item.call_backs.map((call) => (
                      <li key={call.call_id}>
                        <Link
                          href={href(`/c/${slug}/calls/${call.call_id}`)}
                          className="inline-flex items-center gap-1.5 text-body text-brand-strong underline underline-offset-2 touch:min-h-11"
                        >
                          <PhoneCall aria-hidden className="h-3.5 w-3.5" />
                          Call at {formatIST(call.at)}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {item.can_restore && (
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={!allowed || restore.isPending}
                  onClick={() => setConfirming(item)}
                >
                  Turn the line back on now
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {confirming && (
        <ConfirmDialog
          title={`Turn ${confirming.agent_name ?? "this line"} back on?`}
          confirmLabel="Turn it back on"
          pendingLabel="Turning it on…"
          status={restoreFeedback.status}
          error={restore.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() =>
            restore.mutate(confirming.id, { onSuccess: () => setConfirming(null) })
          }
        >
          Callers will reach your agent again straight away, even though we have not finished
          checking it. If calls go wrong again we will step back in.
        </ConfirmDialog>
      )}
    </Section>
  );
}

function Sentence({ term, text }: { term: string; text: string }) {
  return (
    <div className="sm:flex sm:gap-2">
      <dt className="shrink-0 font-medium text-ink sm:w-40">{term}</dt>
      <dd className="text-ink-muted">{text}</dd>
    </div>
  );
}

function StatePill({ open }: { open: boolean }) {
  return <StatusPill tone={open ? "warn" : "neutral"}>{open ? "Ongoing" : "Fixed"}</StatusPill>;
}

function Suggestions({
  session,
  slug,
  href,
  allowed,
}: {
  session: Realm["session"];
  slug: string;
  href: Realm["href"];
  allowed: boolean;
}) {
  const proposals = useHealerProposals(session);
  const decide = useDecideProposal(session);
  // A decided suggestion leaves the list, so its outcome is said in a toast.
  const decideFeedback = useActionFeedback(decide, {
    errorDisplay: "inline",
    successToast: (_data, vars) =>
      vars.decision === "apply" ? "Fix applied" : "Suggestion dismissed",
  });
  const [deciding, setDeciding] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<HealerProposal | null>(null);
  if (proposals.error || !proposals.data) {
    return proposals.error ? (
      <ProblemNotice error={proposals.error} onRetry={() => proposals.refetch()} />
    ) : null;
  }
  const pending = proposals.data.items.filter((p) => p.status === "pending");
  if (pending.length === 0) return null;

  const screenHref = (p: HealerProposal): string =>
    p.screen === "knowledge"
      ? href(`/c/${slug}/knowledge`)
      : href(`/c/${slug}/agents/${p.agent_id}`);

  return (
    <Section title="Suggested fixes">
      <NoticeBox tone="neutral">
        <p>Nothing changes until you approve it.</p>
      </NoticeBox>
      <ul className="mt-4 divide-y divide-line">
        {pending.map((p) => (
          <li key={p.id} className="space-y-2 py-4 first:pt-0 last:pb-0">
            <h3 className="text-body font-semibold text-ink">
              {p.title}
              {p.agent_name && <span className="font-normal text-ink-muted"> · {p.agent_name}</span>}
            </h3>
            <p className="text-body text-ink-muted">{p.body}</p>
            <div className="flex flex-wrap gap-2">
              {p.can_apply ? (
                <button
                  type="button"
                  className={PRIMARY_BUTTON}
                  disabled={!allowed || decide.isPending}
                  onClick={() => setConfirming(p)}
                >
                  {p.action_label}
                </button>
              ) : (
                <Link href={screenHref(p)} className={PRIMARY_BUTTON}>
                  {p.action_label}
                </Link>
              )}
              <ActionButton
                variant="secondary"
                status={deciding === p.id && !confirming ? decideFeedback.status : "idle"}
                successLabel="Dismissed"
                disabled={!allowed || (decide.isPending && deciding !== p.id)}
                onClick={() => {
                  setDeciding(p.id);
                  decide.mutate({ id: p.id, decision: "dismiss" });
                }}
              >
                Dismiss
              </ActionButton>
            </div>
          </li>
        ))}
      </ul>
      {decide.error != null && !confirming && <ProblemNotice error={decide.error} />}
      {confirming && (
        <ConfirmDialog
          title={confirming.title}
          confirmLabel={confirming.action_label}
          pendingLabel="Applying…"
          status={decideFeedback.status}
          error={decide.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            setDeciding(confirming.id);
            decide.mutate(
              { id: confirming.id, decision: "apply" },
              { onSuccess: () => setConfirming(null) },
            );
          }}
        >
          {confirming.body}
        </ConfirmDialog>
      )}
    </Section>
  );
}
