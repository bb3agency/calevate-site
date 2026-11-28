"use client";

import { useState } from "react";

import { Drawer } from "@/components/console/drawer";
import { EMPTY_REHEARSAL, RehearsePanel, type Rehearsal } from "@/components/rehearse/RehearsePanel";
import { ToldView } from "@/components/rehearse/ToldView";
import { SECONDARY_BUTTON_SM } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import type { ScriptHolder } from "@/lib/api/scriptChecks";

/**
 * The Script tab's dock (W3.2, W3.15), for a campaign's and an inbound line's script alike:
 * Rehearse opens a chat with the saved script, What it is told opens the owner's part of the
 * agent's instructions. Both closed by default: a panel from the right on a wide screen, a
 * sheet on a phone (`Drawer`).
 *
 * "Fix this in the script" hands the request to the holder's own Pip ask (`onFix`) and
 * closes the panel, so the owner watches Pip's change arrive in the Script section.
 */
export function RehearseDock({
  session,
  holder,
  script,
  canWrite,
  refusal,
  onFix,
}: {
  session: Session;
  holder: ScriptHolder;
  /** The saved script; nothing to rehearse while there is none. */
  script: unknown;
  canWrite: boolean;
  refusal?: string;
  onFix?: (instruction: string) => void;
}) {
  const [open, setOpen] = useState<"rehearse" | "told" | null>(null);
  const [rehearsal, setRehearsal] = useState<Rehearsal>(EMPTY_REHEARSAL);
  if (script == null) return null;
  return (
    <>
      <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen("rehearse")}>
        Rehearse
      </button>
      <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen("told")}>
        What it is told
      </button>
      <Drawer
        open={open === "rehearse"}
        onClose={() => setOpen(null)}
        title="Rehearse"
        description="Talk to the saved script as a caller would."
      >
        <RehearsePanel
          session={session}
          holder={holder}
          rehearsal={rehearsal}
          onChange={setRehearsal}
          canWrite={canWrite}
          refusal={refusal}
          onFix={
            onFix
              ? (instruction) => {
                  setOpen(null);
                  onFix(instruction);
                }
              : undefined
          }
        />
      </Drawer>
      <Drawer
        open={open === "told"}
        onClose={() => setOpen(null)}
        title="What it is told"
        initialFocus="container"
        width="lg"
      >
        <ToldView session={session} holder={holder} script={script} />
      </Drawer>
    </>
  );
}
