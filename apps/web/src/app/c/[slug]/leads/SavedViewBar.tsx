"use client";

import { useState } from "react";
import { Bookmark, Trash2 } from "lucide-react";

import { FIELD_INLINE, FIELD_LABEL, ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { SavedTick } from "@/components/console/savedTick";
import { useClientRealm } from "@/lib/api/session";
import { useDeleteView, useSaveView, type SavedView, type SavedViewBody } from "@/lib/api/leads";

/**
 * Named lenses over the Leads table — "Hot this week" (SURFACES §2).
 *
 * **Private to the person who saved them**, which is the industry default (Tableau custom
 * views, SeaTable private views both create private and require an explicit act to
 * share) and the only version with no leak surface. Shared views are a later slice with
 * their own question: who may edit a view three colleagues have open.
 *
 * **A view that lost a field says so.** `stale_filter_keys` and `stale_column_keys` come
 * back from the server whenever an admin has edited the capture list out from under a
 * saved view (D-21 makes that admin-only, so the client never sees it coming). The dead
 * references are already removed from what the view applies — a filter silently applied
 * as nothing would WIDEN the set, and the export follows the same lens — and this is
 * where the removal is said out loud.
 *
 * The `<select>` carries a visible `<label>` rather than a placeholder option: axe cannot
 * see placeholder-as-label and neither can a person who is not looking at the arrow.
 */
export function SavedViewBar({
  views,
  error,
  activeViewId,
  canWrite,
  writeReason,
  onApply,
  currentBody,
}: {
  views: SavedView[] | undefined;
  error: unknown;
  activeViewId: string | undefined;
  canWrite: boolean;
  writeReason: string | null;
  onApply: (view: SavedView | undefined) => void;
  /** The lens as it stands right now, minus the name — what "Save" would store. */
  currentBody: Omit<SavedViewBody, "name">;
}) {
  const { session } = useClientRealm();
  // Save, update and delete otherwise leave no trace on screen (the picker just
  // re-selects), so each is acknowledged beside these controls with a tick that fades
  // (REDESIGN-2: no success toasts).
  const [done, setDone] = useState<{ at: number; label: string }>({ at: 0, label: "Saved" });
  const saveView = useSaveView(session);
  const deleteView = useDeleteView(session);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  const active = views?.find((v) => v.id === activeViewId);

  // A request that never landed must not render as "you have no saved views" — that is a
  // statement about this person's account made from our own ignorance (BUILD-LOG §52).
  if (error) return <ProblemNotice error={error} />;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div>
          <label htmlFor="saved-view" className={FIELD_LABEL}>
            Saved view
          </label>
          <select
            id="saved-view"
            value={activeViewId ?? ""}
            // Disabled with a sentence rather than empty, while the list is still coming:
            // an empty picker reads as "you have none", which we do not yet know.
            disabled={views === undefined}
            onChange={(e) => onApply(views?.find((v) => v.id === e.target.value))}
            className={`${FIELD_INLINE} mt-1 block`}
          >
            <option value="">All leads (no view)</option>
            {(views ?? []).map((view) => (
              <option key={view.id} value={view.id}>
                {view.name}
              </option>
            ))}
          </select>
        </div>

        {naming ? (
          <form
            className="flex items-end gap-2"
            /* No rule on this form can refuse a submit, and `noValidate` is still here:
               it is the client realm's invariant that the BROWSER never writes a refusal
               on our screens (tests/formValidation.test.tsx pins it), and a form that
               opts out only when it happens to carry a rule is one attribute away from
               speaking Chrome's words in Chrome's language. */
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              saveView.mutate(
                { body: { ...currentBody, name: name.trim() } },
                {
                  onSuccess: (view) => {
                    setNaming(false);
                    setName("");
                    onApply(view);
                    setDone({ at: Date.now(), label: `Saved “${view.name}”` });
                  },
                },
              );
            }}
          >
            <div>
              <label htmlFor="saved-view-name" className={FIELD_LABEL}>
                Name this view
              </label>
              <input
                id="saved-view-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={60}
                className={`${FIELD_INLINE} mt-1 block w-48`}
              />
            </div>
            <button
              type="submit"
              disabled={!name.trim() || saveView.isPending}
              className={SECONDARY_BUTTON_SM}
            >
              {saveView.isPending ? "Saving…" : "Save"}
            </button>
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
            <button
              type="button"
              disabled={!canWrite || saveView.isPending}
              title={writeReason ?? undefined}
              onClick={() =>
                saveView.mutate(
                  { viewId: active.id, body: { ...currentBody, name: active.name } },
                  {
                    onSuccess: () => setDone({ at: Date.now(), label: `Updated “${active.name}”` }),
                  },
                )
              }
              className={TEXT_ACTION}
            >
              Update “{active.name}”
            </button>
            <button
              type="button"
              disabled={!canWrite || deleteView.isPending}
              title={writeReason ?? undefined}
              onClick={() =>
                deleteView.mutate(active.id, {
                  onSuccess: () => {
                    onApply(undefined);
                    setDone({ at: Date.now(), label: `Deleted “${active.name}”` });
                  },
                })
              }
              className={TEXT_ACTION_DANGER}
            >
              <Trash2 aria-hidden className="h-3.5 w-3.5" />
              Delete
            </button>
          </>
        )}
        <SavedTick at={done.at} label={done.label} />
      </div>

      {/* Errors from the mutations, in the server's own words. A refused name clash has a
          remediation the client can act on, and swallowing it would leave a button that
          looks like it did nothing. */}
      {saveView.error != null && <ProblemNotice error={saveView.error} />}
      {deleteView.error != null && <ProblemNotice error={deleteView.error} />}

      {/* THE DEGRADATION, said out loud. Both lists are already excluded from what the
          view applies, so this is a report and not a warning about something pending. */}
      {active && (active.stale_filter_keys.length > 0 || active.stale_column_keys.length > 0) && (
        <p className="text-meta text-warn">
          “{active.name}” also referred to{" "}
          {[...active.stale_filter_keys, ...active.stale_column_keys].join(", ")}, which your
          agent&apos;s capture list no longer has. Those parts are not being applied. Update the
          view to save it without them.
        </p>
      )}
    </div>
  );
}
