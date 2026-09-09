"use client";

import { useState } from "react";

import {
  Card,
  DANGER_BUTTON,
  EmptyState,
  FIELD_LABEL,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import {
  useKbDecision,
  useKbPreview,
  useTenantKbQueue,
  type KbSource,
} from "@/lib/api/admin";

import { DangerButton, PrimaryButton, SecondaryButton } from "./controls";

/**
 * The two knowledge queues an operator works on this client: what is waiting to be
 * approved, and what was approved and is not live yet.
 *
 * One subject, one file. Approving does NOT push to the engine (`kb_service
 * .approve_source` only moves the status), so the second queue is not a variation on the
 * first — it is the other half of a job that otherwise stops silently halfway, and the
 * client's Knowledge screen sits on "Approved, not live yet" for ever.
 */

/**
 * Approved and NOT live — the publish queue, read once so the screen and the assistant
 * cannot disagree about its size.
 *
 * Publishing leaves `status` at 'approved' and flips `is_active`, so the live ones stay
 * in the same list; filtering them out here is what stops a second Publish button
 * appearing beside a source that is already live.
 */
export function unpublishedSources(sources: readonly KbSource[]): KbSource[] {
  return sources.filter((source) => !source.is_active);
}

export function KnowledgeQueue({ tenantId, slug }: { tenantId: string; slug: string }) {
  const queue = useTenantKbQueue(slug);
  const publishQueue = useTenantKbQueue(slug, "approved");
  const awaitingPublish = unpublishedSources(publishQueue.data ?? []);
  const [selected, setSelected] = useState<string | null>(null);
  // Two-stage reject (ux-audit F-4): the quiet Reject reveals a confirmation bound to
  // ONE source, carrying a reason the OPERATOR writes — the old one-click reject sent a
  // hardcoded "Not suitable for the agent" the operator never saw, into the permanent
  // `rejection_reason` on the client's document.
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const preview = useKbPreview(slug, selected);
  const decide = useKbDecision(tenantId);
  const kbWrite = useAdminAccess("admin:tenants", "decide on this client's knowledge");

  return (
    <>
        {decide.error && <ProblemNotice error={decide.error} />}

        <Card title="Knowledge awaiting approval">
          <RestrictionNote reason={kbWrite.reason} />
          {queue.error ? (
            /* Never an empty queue on a failed read: "nothing is waiting" is a claim about
               this client's work, and an expired token is not evidence for it. */
            <ProblemNotice error={queue.error} onRetry={() => queue.refetch()} />
          ) : queue.isLoading ? (
            <Skeleton rows={3} />
          ) : !queue.data ? (
            /* A paused query (offline) is neither loading nor failed and leaves `data`
               undefined, so `queue.data?.length` would fall through to "Nothing awaiting
               approval" — a claim about this client's work made from a read that never
               arrived. Refuse instead, the way the preview branch below already does. */
            <ProblemNotice
              error={new Error("The knowledge queue did not load.")}
              onRetry={() => queue.refetch()}
            />
          ) : queue.data.length ? (
            <ul className="space-y-2">
              {queue.data.map((source) => (
                <li key={source.id} className="rounded-card border border-line p-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-ink">
                        {source.name} <span className="text-xs text-ink-faint">v{source.version}</span>
                      </p>
                      <p className="text-xs text-ink-muted">
                        {source.chunks} chunks · {source.kind}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {/* Preview is a READ and stays available to anyone who reached this
                          screen — refusing to show what is queued would make an operator
                          without the decision permission unable to even brief the one who
                          has it. */}
                      <SecondaryButton
                        onClick={() => setSelected(selected === source.id ? null : source.id)}
                      >
                        {selected === source.id ? "Hide" : "Preview"}
                      </SecondaryButton>
                      <PrimaryButton
                        disabled={decide.isPending || !kbWrite.allowed}
                        onClick={() => decide.mutate({ sourceId: source.id, decision: "approve" })}
                      >
                        Approve
                      </PrimaryButton>
      {/* Reject is a two-stage act (the ops/dnc pattern): this quiet outline
                          button only OPENS the confirmation below — nothing is sent until
                          the operator has written why and pressed the rose submit there. */}
                      <DangerButton
                        disabled={decide.isPending || !kbWrite.allowed}
                        onClick={() => {
                          setRejecting(rejecting === source.id ? null : source.id);
                          setRejectReason("");
                        }}
                      >
                        {rejecting === source.id ? "Cancel reject" : "Reject…"}
                      </DangerButton>
                    </div>
                  </div>
                  {rejecting === source.id && (
                    <form
                      className="mt-3 space-y-2 rounded-card border border-rose-200 bg-rose-50/40 p-3 dark:border-rose-900 dark:bg-rose-950/20"
                      noValidate
                      onSubmit={(event) => {
                        event.preventDefault();
                        decide.mutate(
                          { sourceId: source.id, decision: "reject", reason: rejectReason.trim() },
                          {
                            onSuccess: () => {
                              setRejecting(null);
                              setRejectReason("");
                            },
                          },
                        );
                      }}
                    >
                      <p className="text-xs text-rose-900 dark:text-rose-200">
                        Rejecting <span className="font-semibold">{source.name}</span> v
                        {source.version}. It stays out of the agent&apos;s answers, and the
                        reason below is recorded on the document permanently — a repeat
                        rejection does not rewrite it.
                      </p>
                      <label className="block">
                        <span className={FIELD_LABEL}>Why it can&apos;t be used</span>
                        <textarea
                          rows={2}
                          maxLength={500}
                          value={rejectReason}
                          disabled={!kbWrite.allowed}
                          onChange={(event) => setRejectReason(event.target.value)}
                          className="mt-1 w-full min-w-0 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11"
                          /* The example must name an action the client can actually take. It used to say
                             "upload the current rate card", and there is no upload: knowledge is
                             submitted as TEXT (`POST /v1/kb/sources` refuses `kind="file"` and
                             `kind="url"`, `apps/api/kb/routes.py:44`) and the console has no file
                             input at all. An operator copying the example would send a client
                             looking for a control that does not exist. */
                          placeholder="e.g. These prices are last year's — send us the current ones and we will put them in"
                        />
                      </label>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="submit"
                          disabled={
                            decide.isPending || !kbWrite.allowed || rejectReason.trim().length < 3
                          }
                          className={DANGER_BUTTON}
                        >
                          {decide.isPending ? "Rejecting…" : "Reject this document"}
                        </button>
                        {rejectReason.trim().length < 3 && (
                          <span className="text-xs text-rose-800 dark:text-rose-300">
                            Write the reason in your own words first — it goes on the record.
                          </span>
                        )}
                      </div>
                    </form>
                  )}
                  {selected === source.id && (
                    <div className="mt-3 space-y-2">
                      {preview.error ? (
                        <ProblemNotice error={preview.error} onRetry={() => preview.refetch()} />
                      ) : preview.isLoading ? (
                        <Skeleton rows={2} />
                      ) : !preview.data ? (
                        /* A paused query (offline) is neither loading nor failed, and
                           `?? []` below would have shown an operator an EMPTY source and
                           invited them to approve it on that evidence. */
                        <ProblemNotice
                          error={new Error("The preview did not load.")}
                          onRetry={() => preview.refetch()}
                        />
                      ) : (
                        /* Chunk-by-chunk is how it is reviewed because chunk-by-chunk is
                           how it will be retrieved and read aloud. */
                        preview.data.map((chunk) => (
                          <div key={chunk.idx} className="rounded-md bg-app p-2 text-xs text-ink-muted">
                            <span className="mr-2 text-ink-faint">#{chunk.idx}</span>
                            {chunk.content}
                            <span className="ml-2 text-ink-faint">({chunk.chars} chars)</span>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="Nothing awaiting approval"
              hint="Approved sources still need publishing before the agent knows them."
            />
          )}
        </Card>

        {/* Approve moves a source to `approved`; publishing is the separate step that
            pushes it to the engine and makes it the live version (FLOWS §7). Both are
            ours, so both need a button — an approved source with nowhere to press is
            work that silently stops halfway.
            The whole panel used to vanish on a failed read of the approved list, which is
            the same silence as an empty one: a source stuck at "Approved, not live yet"
            on the client's screen and nothing here to explain why.
            §52's OTHER clause was still open here, and it is the same sentence drawn a
            third way: while the approved list is IN FLIGHT, `awaitingPublish` is `[]` — the
            `?? []` above cannot tell "not answered yet" from "the server says none" — so
            the panel rendered `null` and an operator's first paint of this screen said
            "nothing is waiting to be published" about a request that had not come back.
            The §52 guard (apps/web/tests/surfaceStatesGuard.test.ts) deliberately does not
            scan a `?? []` outside a JSX child, because whether it reaches a pixel is a
            question about branch dominance; this was the branch that let it through.
            Loading is a skeleton. An empty list, once the server has said so, is still
            nothing — the approval card above already carries the sentence that explains
            what publishing is for. */}
        {publishQueue.isLoading ? (
          <Card title="Approved, awaiting publish">
            <Skeleton rows={2} />
          </Card>
        ) : publishQueue.error || !publishQueue.data ? (
          /* `|| !publishQueue.data` closes the same hole one state further out. The comment
             above names "in flight" and "failed"; a query TanStack has PAUSED because the
             browser is offline is neither — `isLoading === false`, `error === null` — so
             `awaitingPublish` was `[]` and the panel rendered `null`, which on this screen
             reads as "nothing is waiting to be published". */
          <Card title="Approved, awaiting publish">
            <ProblemNotice
              error={publishQueue.error ?? new Error("The publish queue did not load.")}
              onRetry={() => publishQueue.refetch()}
            />
          </Card>
        ) : awaitingPublish.length > 0 ? (
          <Card title="Approved, awaiting publish" bodyClassName="px-4 pb-4 sm:px-6">
            <p className="pt-2 text-xs text-ink-muted">
              The agent does not know these until they are published.
            </p>
            <RestrictionNote reason={kbWrite.reason} />
            <ul className="divide-y divide-line">
              {awaitingPublish.map((source) => (
                <li key={source.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
                  <span className="font-medium text-ink">{source.name}</span>
                  <span className="text-xs text-ink-muted">
                    v{source.version} · {source.chunks} chunks
                  </span>
                  <span className="ml-auto">
                    <PrimaryButton
                      disabled={decide.isPending || !kbWrite.allowed}
                      onClick={() => decide.mutate({ sourceId: source.id, decision: "publish" })}
                    >
                      Publish
                    </PrimaryButton>
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
    </>
  );
}
