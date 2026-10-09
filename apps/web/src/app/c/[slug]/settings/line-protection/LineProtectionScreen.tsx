"use client";

import { useState } from "react";
import Link from "next/link";
import { LifeBuoy, PhoneCall } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
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
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft ?? phone.data?.phone_e164 ?? "";
  const normalised = normaliseIndianMobile(value);
  const invalid = value.trim() !== "" && !INDIA_MOBILE.test(normalised);

  return (
    <Card title="Backup phone">
      {phone.error != null && <ProblemNotice error={phone.error} onRetry={() => phone.refetch()} />}
      {phone.isLoading ? (
        <Skeleton rows={2} label="Loading your backup phone" />
      ) : (
        <form
          noValidate
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (invalid || normalised === "") return;
            save.mutate(normalised, { onSuccess: () => setDraft(null) });
          }}
        >
          <p className="text-sm text-ink-muted">
            {phone.data?.forwarding_supported
              ? "If your agent stops taking calls properly, we pass your callers to this phone while we fix it."
              : "If your agent stops taking calls properly, callers hear a short message asking them to try again later."}{" "}
            Use a mobile someone in your team will answer.
          </p>
          <div>
            <label htmlFor="backup-phone" className={FIELD_LABEL}>
              Indian mobile number
            </label>
            <input
              id="backup-phone"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              className={FIELD}
              value={value}
              disabled={!allowed || save.isPending}
              placeholder="+91 98765 43210"
              aria-invalid={invalid}
              aria-describedby="backup-phone-hint"
              onChange={(event) => setDraft(event.target.value)}
            />
            <span id="backup-phone-hint" className={FIELD_HINT}>
              {invalid ? "Enter an Indian mobile number, like +91 98765 43210." : "Starts with +91."}
            </span>
          </div>
          {save.error != null && <ProblemNotice error={save.error} />}
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              className={PRIMARY_BUTTON}
              disabled={!allowed || invalid || normalised === "" || save.isPending}
            >
              {save.isPending ? "Saving…" : "Save backup phone"}
            </button>
            {phone.data?.phone_e164 && (
              <button
                type="button"
                className={SECONDARY_BUTTON}
                disabled={!allowed || save.isPending}
                onClick={() => save.mutate(null, { onSuccess: () => setDraft(null) })}
              >
                Remove
              </button>
            )}
          </div>
        </form>
      )}
    </Card>
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
  const [confirming, setConfirming] = useState<LineIncident | null>(null);

  return (
    <Card title="Problems with your lines">
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
                <h3 className="text-[15px] font-semibold text-ink">{item.headline}</h3>
                <StatePill open={item.state === "open"} />
              </div>
              <p className="text-xs text-ink-faint">
                {item.state === "open" ? "Since" : "From"} {formatIST(item.opened_at)}
                {item.resolved_at && <> to {formatIST(item.resolved_at)}</>}
              </p>
              <dl className="space-y-1 text-sm">
                <Sentence term="What happened" text={item.what_happened} />
                <Sentence term="What we did" text={item.what_we_did} />
                <Sentence term="What you need to do" text={item.your_part} />
              </dl>
              {item.call_backs.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-ink">Callers to ring back</p>
                  <ul className="mt-1 space-y-1">
                    {item.call_backs.map((call) => (
                      <li key={call.call_id}>
                        <Link
                          href={href(`/c/${slug}/calls/${call.call_id}`)}
                          className="inline-flex items-center gap-1.5 text-sm text-brand-strong underline underline-offset-2"
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
          pending={restore.isPending}
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
    </Card>
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
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[13px] font-medium ${
        open ? "border-warn-line bg-warn-soft text-warn" : "border-line bg-ink/[0.04] text-ink-muted"
      }`}
    >
      {open ? "Ongoing" : "Fixed"}
    </span>
  );
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
    <Card title="Suggested fixes">
      <NoticeBox tone="neutral" icon={<LifeBuoy aria-hidden className="h-5 w-5" />}>
        <p>Nothing changes until you approve it.</p>
      </NoticeBox>
      <ul className="mt-4 divide-y divide-line">
        {pending.map((p) => (
          <li key={p.id} className="space-y-2 py-4 first:pt-0 last:pb-0">
            <h3 className="text-[15px] font-semibold text-ink">
              {p.title}
              {p.agent_name && <span className="font-normal text-ink-muted"> · {p.agent_name}</span>}
            </h3>
            <p className="text-sm text-ink-muted">{p.body}</p>
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
              <button
                type="button"
                className={SECONDARY_BUTTON}
                disabled={!allowed || decide.isPending}
                onClick={() => decide.mutate({ id: p.id, decision: "dismiss" })}
              >
                Dismiss
              </button>
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
          pending={decide.isPending}
          error={decide.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() =>
            decide.mutate(
              { id: confirming.id, decision: "apply" },
              { onSuccess: () => setConfirming(null) },
            )
          }
        >
          {confirming.body}
        </ConfirmDialog>
      )}
    </Card>
  );
}
