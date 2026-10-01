"use client";

import { useState } from "react";

import { Drawer } from "@/components/console/drawer";
import { PageHeader } from "@/components/console/pageHeader";
import { PRIMARY_BUTTON, RestrictionNote, SECONDARY_BUTTON } from "@/components/ui";
import { useDeletionRequests } from "@/lib/api/dataRights";
import { useActAccess } from "@/lib/api/hooks";
import { Term } from "@/lib/glossary";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { useSubjectExportAccess } from "./access";
import { Erasure } from "./Erasure";
import { Register } from "./Register";
import { SubjectExport } from "./SubjectExport";

/**
 * Data rights (DPDP §11, SEC-COMP §4): the two requests a data principal can make of a
 * client, and the certificate that answers the second. The register is the page; exporting
 * and erasing are tasks that open in a drawer, each with its consequences stated above
 * its control (`SubjectExport.tsx`, `Erasure.tsx`, `Register.tsx`).
 */
export default function DataRightsPage() {
  const session = useClientSession();
  // The same read `Register` makes, served from cache; read here so the one copilot
  // declaration (below) covers every state, including loading and failed.
  const requests = useDeletionRequests(session);
  const [task, setTask] = useState<"export" | "erase" | null>(null);
  const exportAccess = useSubjectExportAccess(session);
  // The same act check the erasure form makes (D-587): `org:manage` alone would arm the
  // button for a view-as operator and let the typed ERASE end in a 403.
  const eraseAccess = useActAccess(session, "org:manage", "compliance.erasure_request", "file an erasure request");

  // Neither phone box is declared: both act on a named person, with a statutory clock and
  // no undo. The register is declared as counts only, and "could not read the register"
  // is carried into the fact rather than flattened into "nobody asked" (§52).
  useCopilotSurface({
    route: "/c/{slug}/data-rights",
    title: "Data rights",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: requests.data
          ? "the erasure register below has loaded"
          : requests.error
            ? "the register failed to load — this is NOT evidence that nobody has asked to be erased"
            : "still loading",
      },
      ...(requests.data
        ? [
            { key: "requests_total", label: "Erasure requests on the register", value: String(requests.data.length) },
            {
              key: "requests_pending",
              label: "Of those, still running",
              value: String(requests.data.filter((request) => request.status === "pending").length),
            },
            {
              key: "requests_completed",
              label: "Of those, completed",
              value: String(requests.data.filter((request) => request.status === "completed").length),
            },
            {
              key: "requests_with_certificate",
              label: "Requests with an erasure certificate on file",
              value: String(requests.data.filter((request) => request.has_certificate).length),
            },
          ]
        : []),
    ],
    apply: noFill,
  });

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        description={
          <>
            Answer a person who asks what you hold about them, or asks you to erase it. You
            are the <Term id="dataFiduciary" />; every request is recorded against your
            account.
          </>
        }
        actions={
          <>
            <button
              type="button"
              onClick={() => setTask("export")}
              disabled={!exportAccess.allowed}
              title={exportAccess.reason ?? undefined}
              className={PRIMARY_BUTTON}
            >
              {"Export someone's data"}
            </button>
            {/* Never styled like the primary beside it: this one cannot be undone. */}
            <button
              type="button"
              onClick={() => setTask("erase")}
              disabled={!eraseAccess.allowed}
              title={eraseAccess.reason ?? undefined}
              className={`${SECONDARY_BUTTON} enabled:text-danger`}
            >
              {"Erase someone's data"}
            </button>
          </>
        }
      />

      <RestrictionNote reason={exportAccess.reason} />
      {eraseAccess.reason !== exportAccess.reason && <RestrictionNote reason={eraseAccess.reason} />}

      <Register session={session} />

      <Drawer open={task === "export"} onClose={() => setTask(null)} title="Export someone's data" width="md">
        <SubjectExport session={session} />
      </Drawer>
      <Drawer open={task === "erase"} onClose={() => setTask(null)} title="Erase someone's data" width="md">
        <Erasure session={session} onFiled={() => setTask(null)} />
      </Drawer>
    </div>
  );
}
