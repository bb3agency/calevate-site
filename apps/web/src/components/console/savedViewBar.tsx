"use client";

import { useId, useState } from "react";
import type { UseMutationResult } from "@tanstack/react-query";
import { Bookmark, Trash2 } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD_INLINE, FIELD_LABEL, ProblemNotice } from "@/components/ui";

/** The part of a saved view this bar reads. */
export interface NamedView {
  id: string;
  name: string;
}

/** Save or update: `viewId` set means update that view. */
export interface SaveViewVars<B> {
  viewId?: string;
  body: B;
}

/**
 * NAMED LENSES OVER A LIST — the Leads table's and the Calls log's (SURFACES §2, D-893 L2).
 *
 * **Private to the person who saved them**, which is the industry default (Tableau custom
 * views, SeaTable private views both create private and require an explicit act to share)
 * and the only version with no leak surface.
 *
 * **A view holds every filter on the screen** except the search box, so applying one puts
 * all of them back and clears the rest; the caller's `bodyFor` and `onApply` are exact
 * inverses. A date range that ends today can be kept as "the last N days" (`rollingNote`),
 * on by default, because a view called "This week" that froze on the day it was saved would
 * quietly stop meaning this week.
 *
 * The `<select>` carries a visible `<label>` rather than a placeholder option: axe cannot
 * see placeholder-as-label and neither can a person who is not looking at the arrow.
 */
export function SavedViewBar<V extends NamedView, B extends { name: string }>({
  views,
  error,
  activeViewId,
  canWrite,
  writeReason,
  onApply,
  bodyFor,
  save,
  remove,
  allLabel,
  describe,
  notice,
  rollingNote,
}: {
  views: V[] | undefined;
  error: unknown;
  activeViewId: string | undefined;
  canWrite: boolean;
  writeReason: string | null;
  onApply: (view: V | undefined) => void;
  /** The current filters as a view body; `rolling` keeps ranges ending today moving. */
  bodyFor: (name: string, rolling: boolean) => B;
  save: UseMutationResult<V, unknown, SaveViewVars<B>>;
  remove: UseMutationResult<unknown, unknown, string>;
  /** The picker's "no view" entry, e.g. "All leads (no view)". */
  allLabel: string;
  /** One line on what the chosen view shows, or null. */
  describe?: (view: V) => string | null;
  /** A sentence about the chosen view the person must see (what it lost), or null. */
  notice?: (view: V) => string | null;
  /** Set while a date range on screen ends today: what keeping it moving means. */
  rollingNote: string | null;
}) {
  const ids = useId();
  // A new view closes its form and becomes the chosen one, so its success is a toast; an
  // update keeps its button, whose face says it. A refused name is said beside the form.
  const saving = useActionFeedback(save, {
    errorDisplay: "inline",
    successToast: (view, vars) => (vars.viewId ? null : `Saved the view “${view.name}”`),
  });
  const deleting = useActionFeedback(remove, {
    errorTitle: "Could not delete the view",
    successToast: "View deleted",
  });
  const updatingThis = Boolean(save.variables?.viewId);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [rolling, setRolling] = useState(true);

  const active = views?.find((v) => v.id === activeViewId);
  const description = active && describe ? describe(active) : null;
  const warning = active && notice ? notice(active) : null;

  // A request that never landed must not render as "you have no saved views" — that is a
  // statement about this person's account made from our own ignorance (BUILD-LOG §52).
  if (error) return <ProblemNotice error={error} />;

  const rollingBox = rollingNote ? (
    <label className="flex items-start gap-2 text-meta text-ink touch:min-h-11">
      <input
        type="checkbox"
        checked={rolling}
        onChange={(e) => setRolling(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 accent-(--brand-strong)"
      />
      <span>
        Keep the dates moving <span className="text-ink-muted">— {rollingNote}</span>
      </span>
    </label>
  ) : null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="min-w-0">
          <label htmlFor={`${ids}-pick`} className={FIELD_LABEL}>
            Saved view
          </label>
          <select
            id={`${ids}-pick`}
            value={activeViewId ?? ""}
            // Disabled with a sentence rather than empty, while the list is still coming:
            // an empty picker reads as "you have none", which we do not yet know.
            disabled={views === undefined}
            onChange={(e) => onApply(views?.find((v) => v.id === e.target.value))}
            className={`${FIELD_INLINE} mt-1 block max-w-full`}
          >
            <option value="">{views === undefined ? "Reading your views…" : allLabel}</option>
            {(views ?? []).map((view) => (
              <option key={view.id} value={view.id}>
                {view.name}
              </option>
            ))}
          </select>
        </div>

        {naming ? (
          <form
            className="flex min-w-0 flex-wrap items-end gap-2"
            /* No rule on this form can refuse a submit, and `noValidate` is still here:
               it is the client realm's invariant that the BROWSER never writes a refusal
               on our screens (tests/formValidation.test.tsx pins it). */
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim()) return;
              save.mutate(
                { body: bodyFor(name.trim(), rolling) },
                {
                  onSuccess: (view) => {
                    setNaming(false);
                    setName("");
                    onApply(view);
                  },
                },
              );
            }}
          >
            <div className="min-w-0">
              <label htmlFor={`${ids}-name`} className={FIELD_LABEL}>
                Name this view
              </label>
              <input
                id={`${ids}-name`}
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={60}
                autoComplete="off"
                className={`${FIELD_INLINE} mt-1 block w-48 max-w-full`}
              />
            </div>
            <ActionButton
              type="submit"
              variant="secondary-sm"
              status={updatingThis ? "idle" : saving.status}
              successLabel="Saved"
              disabled={!name.trim()}
            >
              Save
            </ActionButton>
            <button
              type="button"
              onClick={() => {
                setNaming(false);
                setName("");
              }}
              className={TEXT_ACTION}
            >
              Cancel
            </button>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setNaming(true)}
            disabled={!canWrite}
            title={writeReason ?? undefined}
            className={TEXT_ACTION}
          >
            <Bookmark aria-hidden className="h-3.5 w-3.5" />
            Save this view
          </button>
        )}

        {active && (
          <>
            <ActionButton
              variant="secondary-sm"
              status={updatingThis ? saving.status : "idle"}
              successLabel="Updated"
              disabled={!canWrite}
              title={writeReason ?? undefined}
              onClick={() => saving.run({ viewId: active.id, body: bodyFor(active.name, rolling) })}
            >
              <span className="max-w-48 truncate">Update “{active.name}”</span>
            </ActionButton>
            <ActionButton
              variant="secondary-sm"
              status={deleting.status}
              pendingLabel="Deleting…"
              successLabel="Deleted"
              disabled={!canWrite}
              title={writeReason ?? undefined}
              onClick={() => remove.mutate(active.id, { onSuccess: () => onApply(undefined) })}
            >
              <Trash2 aria-hidden className="h-3.5 w-3.5" />
              Delete view
            </ActionButton>
          </>
        )}
      </div>

      {(naming || active) && rollingBox}

      {description && <p className="text-meta text-ink-muted">Shows {description}.</p>}

      {/* Errors from the mutations, in the server's own words. A refused name clash has a
          remediation the client can act on. */}
      {save.error != null && <ProblemNotice error={save.error} />}

      {warning && <p className="text-meta text-warn">{warning}</p>}
    </div>
  );
}
