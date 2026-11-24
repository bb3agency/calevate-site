"use client";

/**
 * "Put back the flow from before Pip" and the Versions list (D-1039), for a campaign's call
 * flow and an inbound line's script alike.
 *
 * Put-back restores the owner's own last version (`put_back.version`), never the script as it
 * stood before an automatic pass: those passes each change a line or two, so restoring the
 * copy taken before one changed nothing anyone could see. When there is nothing of the
 * owner's to restore the button is held and a short line says why, so it never reports a
 * change it did not make. Versions lists every save with who and when, each one restorable.
 */

import { History } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { ModalDialog } from "@/components/modalDialog";
import type { ActionFeedback } from "@/components/arc/feedback";
import { SECONDARY_BUTTON_SM, formatIST } from "@/components/ui";
import {
  AUTHOR_LABELS,
  type ScriptRestore,
  type ScriptVersion,
  type ScriptVersions as Versions,
} from "@/lib/api/scriptVersions";

type Held = NonNullable<Versions["put_back"]["unavailable"]>;

/** Why put-back is held, in the owner's words. */
export const PUT_BACK_HELD: Record<Held, string> = {
  no_owner_version: "Nothing of yours to put back yet.",
  already_current: "This is already your version.",
};

const UNSAVED = "Save or discard your changes first.";

/** Which version comes back: "your version from 23 Nov, 04:10 pm". */
export const versionLabel = (version: ScriptVersion) =>
  `${version.owner_made ? "your" : "the"} version from ${formatIST(version.created_at)}`;

/** The success toast for a restore (`useActionFeedback`'s `successToast`). */
export const restoredToast = (_out: unknown, input: ScriptRestore) => `Put back ${input.label}`;

export function ScriptVersions({
  versions,
  noun,
  readOnly,
  dirty,
  restore,
  onRestore,
}: {
  versions: Versions | undefined;
  /** What the owner calls it here: the campaign's "flow" or the line's "script". */
  noun: "flow" | "script";
  readOnly: boolean;
  /** Unsaved changes on the page: a restore would throw them away, so it waits. */
  dirty: boolean;
  restore: ActionFeedback<ScriptRestore>;
  onRestore: (input: ScriptRestore) => Promise<unknown>;
}) {
  const [confirming, setConfirming] = useState<ScriptRestore | null>(null);
  const [listOpen, setListOpen] = useState(false);
  if (!versions) return null;
  const own = versions.put_back.version;
  const held = versions.put_back.unavailable;
  const blocked = readOnly || dirty;
  const ask = (input: ScriptRestore) => {
    restore.reset();
    setListOpen(false);
    setConfirming(input);
  };

  return (
    <>
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={blocked || own === null}
        title={dirty ? UNSAVED : undefined}
        onClick={() =>
          own && ask({ expectedVersionId: versions.current_version_id, label: versionLabel(own) })
        }
      >
        <History aria-hidden className="h-3.5 w-3.5" />
        Put back the {noun} from before Pip
      </button>
      {held && <span className="text-meta text-ink-muted">{PUT_BACK_HELD[held]}</span>}
      {versions.versions.length > 1 && (
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setListOpen(true)}>
          Versions
        </button>
      )}

      {listOpen && (
        <ModalDialog
          title="Versions"
          description={`Every saved ${noun}, newest first. What you have now stays here when you put one back.`}
          onClose={() => setListOpen(false)}
          actions={
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setListOpen(false)}>
              Close
            </button>
          }
        >
          <ul className="mt-3 divide-y divide-line">
            {versions.versions.map((version, index) => (
              <li key={version.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <p className="text-body text-ink">
                    {AUTHOR_LABELS[version.author]}
                    <span className="text-meta text-ink-muted"> · {formatIST(version.created_at)}</span>
                  </p>
                  <p className="text-meta text-ink-muted">{version.reason}</p>
                </div>
                {index === 0 ? (
                  <span className="text-meta text-ink-muted">Now</span>
                ) : (
                  <button
                    type="button"
                    className={SECONDARY_BUTTON_SM}
                    disabled={blocked}
                    title={dirty ? UNSAVED : undefined}
                    onClick={() =>
                      ask({
                        versionId: version.id,
                        expectedVersionId: versions.current_version_id,
                        label: versionLabel(version),
                      })
                    }
                  >
                    Put back
                  </button>
                )}
              </li>
            ))}
          </ul>
        </ModalDialog>
      )}

      {confirming && (
        <ConfirmDialog
          title={confirming.versionId ? `Put back this ${noun}?` : `Put back the ${noun} from before Pip?`}
          confirmLabel="Put it back"
          pendingLabel="Putting it back"
          cancelLabel="Keep this one"
          status={restore.status}
          error={restore.error ?? null}
          onCancel={() => {
            restore.reset();
            setConfirming(null);
          }}
          onConfirm={() =>
            void onRestore(confirming).then(
              () => setConfirming(null),
              () => undefined,
            )
          }
        >
          <span className="block">
            The {noun} goes back to {confirming.label}. What you have now stays in Versions, so
            you can switch back.
          </span>
        </ConfirmDialog>
      )}
    </>
  );
}
