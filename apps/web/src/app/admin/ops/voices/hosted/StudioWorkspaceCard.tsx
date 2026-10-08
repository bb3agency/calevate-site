"use client";

import { useRef, useState } from "react";
import { CircleCheck, KeyRound, TriangleAlert } from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { Card, FIELD, FIELD_HINT, FIELD_LABEL, MonoValue, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { useSetupStudioWorkspace, useStudioWorkspace } from "@/lib/api/opsHostedVoices";
import { useFocusTrap } from "@/lib/focusTrap";

/**
 * Where Studio agents run (D-687): ONE shared ThinnestAI customer workspace whose own-keys
 * switch is on for the voice only, holding our Cartesia key. Clear agents stay in our
 * developer workspace, where the clones are. The card says whether that workspace is ready
 * and offers the one action that makes it so; every sentence about the state is the
 * server's.
 */
export function StudioWorkspaceCard() {
  const workspace = useStudioWorkspace(true);
  const setup = useSetupStudioWorkspace();
  const [confirming, setConfirming] = useState(false);

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 className="text-[15px] font-semibold text-ink">Studio workspace</h2>
          {workspace.error != null ? (
            <ProblemNotice error={workspace.error} onRetry={() => void workspace.refetch()} />
          ) : !workspace.data ? (
            <Skeleton rows={2} label="Reading the Studio workspace" />
          ) : (
            <>
              <p className="flex items-center gap-1.5 text-sm font-medium">
                {workspace.data.ready ? (
                  <>
                    <CircleCheck aria-hidden className="h-4 w-4 text-brand-strong" />
                    <span className="text-ink">Ready — Studio voices can be offered</span>
                  </>
                ) : (
                  <>
                    <TriangleAlert aria-hidden className="h-4 w-4 text-warn" />
                    <span className="text-warn">Not ready — Studio voices cannot be offered</span>
                  </>
                )}
              </p>
              <p className="text-sm text-ink-muted">{workspace.data.note}</p>
              <dl className="mt-1 grid gap-x-4 gap-y-0.5 text-xs text-ink-muted sm:grid-cols-[auto_1fr]">
                <dt className="font-medium">Workspace</dt>
                <dd className="break-all">
                  {workspace.data.workspace_id ? (
                    <MonoValue>{workspace.data.workspace_id}</MonoValue>
                  ) : (
                    "Not set"
                  )}
                </dd>
                <dt className="font-medium">Voice key</dt>
                <dd>
                  {workspace.data.key === null
                    ? "Not read"
                    : [
                        workspace.data.key.enabled ? "Own keys on" : "Own keys off",
                        workspace.data.key.scope ? `scope ${workspace.data.key.scope}` : null,
                        workspace.data.key.voice_provider
                          ? `voice by ${workspace.data.key.voice_provider}`
                          : null,
                        workspace.data.key.complete ? "complete" : "incomplete",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                </dd>
              </dl>
            </>
          )}
        </div>
        {workspace.data && (
          <button
            type="button"
            className={PRIMARY_BUTTON_SM}
            onClick={() => {
              setup.reset();
              setConfirming(true);
            }}
          >
            <KeyRound aria-hidden className="h-4 w-4" />
            {workspace.data.ready ? "Set up again" : "Set up Studio workspace"}
          </button>
        )}
      </div>
      {!confirming && setup.data && (
        <p role="status" className="mt-2 text-sm text-ink-muted">
          {setup.data.note}
        </p>
      )}
      {confirming && (
        <SetupDialog
          pending={setup.isPending}
          error={setup.error}
          existing={workspace.data?.workspace_id ?? ""}
          onCancel={() => setConfirming(false)}
          onConfirm={(workspaceId) =>
            setup.mutate(
              workspaceId ? { workspace_id: workspaceId } : {},
              { onSuccess: () => setConfirming(false) },
            )
          }
        />
      )}
    </Card>
  );
}

/** The confirmation, with the one optional field the setup takes. */
function SetupDialog({
  pending,
  error,
  existing,
  onCancel,
  onConfirm,
}: {
  pending: boolean;
  error: unknown;
  existing: string;
  onCancel: () => void;
  onConfirm: (workspaceId: string) => void;
}) {
  const [workspaceId, setWorkspaceId] = useState(existing);
  const panel = useRef<HTMLDivElement>(null);
  useFocusTrap(panel, true, onCancel, "container");
  return (
    <div className="scrim-enter fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="studio-setup-title"
        aria-describedby="studio-setup-body"
        tabIndex={-1}
        className="dialog-enter max-h-[90vh] w-full max-w-md overflow-y-auto rounded-card border border-line bg-surface p-6 shadow-overlay outline-none"
      >
        <h2 id="studio-setup-title" className="text-[17px] font-semibold text-ink">
          Set up the Studio workspace?
        </h2>
        <div id="studio-setup-body" className="mt-3 space-y-2 text-sm text-ink-muted">
          <p>
            This creates a ThinnestAI customer workspace (or uses the one named below),
            installs our Cartesia key there as its voice key, and turns on own keys for the
            voice only. Our developer workspace keeps its own keys off.
          </p>
          <p>It installs a credential, so you may be asked to confirm it is still you.</p>
        </div>
        <form
          className="mt-4 space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            onConfirm(workspaceId.trim());
          }}
        >
          <label className="block">
            <span className={FIELD_LABEL}>Existing workspace ID (optional)</span>
            <input
              className={`${FIELD} font-mono`}
              value={workspaceId}
              maxLength={128}
              onChange={(event) => setWorkspaceId(event.target.value)}
            />
            <span className={FIELD_HINT}>Leave empty to create a new customer workspace.</span>
          </label>
          {error != null && <WriteFailure error={error} actionLabel="Set up" />}
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={onCancel}
              disabled={pending}
            >
              Cancel
            </button>
            <button type="submit" className={PRIMARY_BUTTON_SM} disabled={pending}>
              {pending ? "Setting up…" : "Set up"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

