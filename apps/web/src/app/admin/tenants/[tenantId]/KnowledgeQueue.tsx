"use client";

import { useState } from "react";

import { HAIRLINE_LIST } from "@/components/admin/kit";
import { Section, TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import {
  DANGER_BUTTON,
  FIELD,
  FIELD_LABEL,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { useAdminAccess } from "@/app/admin/access";
import {
  useKbDecision,
  useKbPreview,
  useTenantKbQueue,
  type KbSource,
} from "@/lib/api/admin";


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

        <Section
          title="Knowledge awaiting approval"
          info="This is the client's knowledge, shared by all its agents. Only knowledge an operator added, or a page an operator linked, waits here: what the client's own people add goes live on its own. Approving does not make a source live; Publish does."
        >
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
            <ul className={HAIRLINE_LIST}>
              {queue.data.map((source) => (
                <li key={source.id} className="py-3 sm:px-2">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-body font-medium text-ink">
                        {source.name} <span className="text-meta font-normal text-ink-muted">v{source.version}</span>
                      </p>
                      <p className="text-meta text-ink-muted">
                        {source.chunks} chunks · {source.kind}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                      {/* Preview is a READ and stays available to anyone who reached this
                          screen — refusing to show what is queued would make an operator
                          without the decision permission unable to even brief the one who
                          has it. */}
                      <button
                        type="button"
                        className={TEXT_ACTION}
                        onClick={() => setSelected(selected === source.id ? null : source.id)}
                      >
                        {selected === source.id ? "Hide" : "Preview"}
                      </button>
      {/* Reject is a two-stage act (the ops/dnc pattern): this quiet text
                          action only OPENS the confirmation below — nothing is sent until
                          the operator has written why and pressed the rose submit there. */}
                      <button
                        type="button"
                        className={TEXT_ACTION_DANGER}
                        disabled={decide.isPending || !kbWrite.allowed}
                        onClick={() => {
                          setRejecting(rejecting === source.id ? null : source.id);
                          setRejectReason("");
                        }}
                      >
                        {rejecting === source.id ? "Cancel reject" : "Reject…"}
                      </button>
                      <button
                        type="button"
                        className={SECONDARY_BUTTON_SM}
                        disabled={decide.isPending || !kbWrite.allowed}
                        onClick={() => decide.mutate({ sourceId: source.id, decision: "approve" })}
                      >
                        Approve
                      </button>
                    </div>
                  </div>
                  {rejecting === source.id && (
                    <form
                      className="mt-3 max-w-xl space-y-3 border-l-2 border-danger pl-4"
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
                      <p className="text-body text-danger">
                        Rejecting <span className="font-semibold">{source.name}</span> v
                        {source.version}. It stays out of the agents&apos; answers, and the
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
                          className={FIELD}
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
                          <span className="text-meta text-danger">
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
                          <div key={chunk.idx} className="border-l border-line pl-3 text-meta text-ink-muted">
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
            <EmptyState message="Nothing awaiting approval" />
          )}
        </Section>

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
          <Section title="Approved, awaiting publish">
            <Skeleton rows={2} />
          </Section>
        ) : publishQueue.error || !publishQueue.data ? (
          /* `|| !publishQueue.data` closes the same hole one state further out. The comment
             above names "in flight" and "failed"; a query TanStack has PAUSED because the
             browser is offline is neither — `isLoading === false`, `error === null` — so
             `awaitingPublish` was `[]` and the panel rendered `null`, which on this screen
             reads as "nothing is waiting to be published". */
          <Section title="Approved, awaiting publish">
            <ProblemNotice
              error={publishQueue.error ?? new Error("The publish queue did not load.")}
              onRetry={() => publishQueue.refetch()}
            />
          </Section>
        ) : awaitingPublish.length > 0 ? (
          <Section title="Approved, awaiting publish">
            <p className="text-meta text-ink-muted">
              None of the client&apos;s agents know these until they are published.
            </p>
            <RestrictionNote reason={kbWrite.reason} />
            <ul className={`mt-3 ${HAIRLINE_LIST}`}>
              {awaitingPublish.map((source) => (
                <li key={source.id} className="flex flex-wrap items-center gap-2 py-2.5 text-body sm:px-2">
                  <span className="font-medium text-ink">{source.name}</span>
                  <span className="text-meta text-ink-muted">
                    v{source.version} · {source.chunks} chunks
                  </span>
                  <span className="ml-auto">
                    <button
                      type="button"
                      className={SECONDARY_BUTTON_SM}
                      disabled={decide.isPending || !kbWrite.allowed}
                      onClick={() => decide.mutate({ sourceId: source.id, decision: "publish" })}
                    >
                      Publish
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        ) : null}
    </>
  );
}
