"use client";

import { ArrowDown, ArrowUp, X } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { InlineEdit } from "@/components/arc/inline-edit";
import { Section } from "@/components/console/section";
import { ProblemNotice, QUIET_ICON_BUTTON, Skeleton } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import {
  usePinCard,
  usePins,
  useRemovePin,
  useRenamePin,
  useReorderPins,
  useRestorePin,
  type Pin,
} from "@/lib/api/pins";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import type { ChartRealm } from "@/lib/copilot/charts";

import { ChartView } from "./ChartView";

/**
 * The charts people pinned from Pip (D-934), on the client home or the admin home. Each
 * card re-runs its chart for whoever is looking, so a card the viewer may not see says so
 * instead of showing a figure. Rename in place, move up or down, remove with Undo — each at
 * once. Nothing renders until something is pinned: an empty section is homework.
 */
export function PinnedCards({
  session,
  realm,
  canEdit,
}: {
  session: Session;
  realm: ChartRealm;
  canEdit: boolean;
}) {
  const pins = usePins(session, realm);
  const reorder = useReorderPins(session, realm);
  const list = pins.data?.pins ?? [];
  if (pins.isError) {
    return (
      <Section title="Pinned charts">
        <ProblemNotice error={pins.error} onRetry={() => void pins.refetch()} />
      </Section>
    );
  }
  if (list.length === 0) return null;

  const move = (index: number, by: -1 | 1) => {
    const ids = list.map((pin) => pin.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + by, 0, moved as string);
    reorder.mutate(ids);
  };

  return (
    <Section title="Pinned charts" description={`Kept here from ${ASSISTANT_NAME}. Always up to date.`}>
      <ul className="grid grid-cols-1 gap-4 page-lg:grid-cols-2">
        {list.map((pin, index) => (
          <li key={pin.id}>
            <PinnedCard
              session={session}
              realm={realm}
              pin={pin}
              canEdit={canEdit}
              onUp={index > 0 ? () => move(index, -1) : undefined}
              onDown={index < list.length - 1 ? () => move(index, 1) : undefined}
            />
          </li>
        ))}
      </ul>
    </Section>
  );
}

function PinnedCard({
  session,
  realm,
  pin,
  canEdit,
  onUp,
  onDown,
}: {
  session: Session;
  realm: ChartRealm;
  pin: Pin;
  canEdit: boolean;
  onUp?: () => void;
  onDown?: () => void;
}) {
  const card = usePinCard(session, realm, pin.id);
  const rename = useRenamePin(session, realm);
  const renameFeedback = useActionFeedback(rename, { errorDisplay: "inline" });
  const restore = useRestorePin(session, realm);
  const remove = useRemovePin(session, realm);
  const removeFeedback = useActionFeedback(remove, {
    errorTitle: "Could not remove this card",
    successToast: "Card removed",
    undo: (_removed, id) => restore.mutate(id),
  });
  const spec = card.data?.spec;

  return (
    <div className="rounded-card border border-line bg-surface p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        {canEdit ? (
          <InlineEdit
            value={pin.title}
            label="Card name"
            maxLength={80}
            textClassName="text-body font-semibold"
            status={renameFeedback.status}
            onSave={(title) => renameFeedback.run({ id: pin.id, title })}
          />
        ) : (
          <h3 className="text-body font-semibold text-ink">{pin.title}</h3>
        )}
        {canEdit ? (
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              className={QUIET_ICON_BUTTON}
              onClick={onUp}
              disabled={onUp === undefined}
              aria-label={`Move “${pin.title}” up`}
            >
              <ArrowUp aria-hidden className="h-4 w-4" />
            </button>
            <button
              type="button"
              className={QUIET_ICON_BUTTON}
              onClick={onDown}
              disabled={onDown === undefined}
              aria-label={`Move “${pin.title}” down`}
            >
              <ArrowDown aria-hidden className="h-4 w-4" />
            </button>
            <button
              type="button"
              className={QUIET_ICON_BUTTON}
              onClick={() => removeFeedback.run(pin.id)}
              aria-label={`Remove “${pin.title}”`}
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          </div>
        ) : null}
      </div>
      {card.isPending ? (
        <Skeleton rows={4} label="Loading the chart…" />
      ) : card.isError ? (
        <ProblemNotice error={card.error} onRetry={() => void card.refetch()} />
      ) : spec ? (
        <ChartView spec={spec} hideTitle />
      ) : (
        <p className="text-body text-ink-muted">{card.data?.refused ?? "This chart is not available."}</p>
      )}
    </div>
  );
}
