import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StepUpPrompt } from "@/components/authn/stepUpPrompt";
import {
  useAmendMaintenance,
  useCancelMaintenance,
  useEndMaintenance,
  useScheduleMaintenance,
} from "@/lib/api/maintenance";
import { useReviewKyc, useSetDigiLockerRequirement } from "@/lib/api/kycReview";
import { useSetNumberEngineRef } from "@/lib/api/numbers";
import { usePostStatus, useResolveIncident } from "@/lib/api/opsHealer";

import { problem, renderAdminPage } from "./harness";

/**
 * Every operator write whose route sits behind the step-up gate must turn a stale second
 * factor into the code prompt and send once more. A hook that sent a plain request left
 * the operator reading the API's remediation ("POST /v1/auth/admin/step-up …") with no
 * way to act on it.
 */

const WINDOW = "019f2000-0000-7000-8000-000000000001";
const INCIDENT = "019f2000-0000-7000-8000-000000000002";
const TENANT = "019f2000-0000-7000-8000-000000000003";
const NUMBER = "019f2000-0000-7000-8000-000000000004";

function reauthRequired() {
  return problem(403, {
    type: "https://calevate.tech/problems/reauthentication_required",
    title: "Confirm it is still you",
    detail: "This action needs a second factor proved in the last 30 minutes.",
    kind: "permission",
  });
}

interface Case {
  name: string;
  method: string;
  path: string;
  confirm: string;
  useRun: () => () => Promise<unknown>;
}

const CASES: Case[] = [
  {
    name: "schedule a maintenance window",
    method: "POST",
    path: "/v1/ops/maintenance",
    confirm: "schedule_maintenance",
    useRun: () => {
      const m = useScheduleMaintenance();
      return () =>
        m.mutateAsync({
          startsAt: "2026-11-01T00:00:00Z",
          endsAt: "2026-11-01T01:00:00Z",
          reason: "Database upgrade",
        });
    },
  },
  {
    name: "amend a maintenance window",
    method: "PATCH",
    path: `/v1/ops/maintenance/${WINDOW}`,
    confirm: `amend_maintenance:${WINDOW}`,
    useRun: () => {
      const m = useAmendMaintenance();
      return () => m.mutateAsync({ windowId: WINDOW, reason: "Longer upgrade" });
    },
  },
  {
    name: "cancel a maintenance window",
    method: "POST",
    path: `/v1/ops/maintenance/${WINDOW}/cancel`,
    confirm: `cancel_maintenance:${WINDOW}`,
    useRun: () => {
      const m = useCancelMaintenance();
      return () => m.mutateAsync(WINDOW);
    },
  },
  {
    name: "end a maintenance window",
    method: "POST",
    path: `/v1/ops/maintenance/${WINDOW}/end`,
    confirm: `end_maintenance:${WINDOW}`,
    useRun: () => {
      const m = useEndMaintenance();
      return () => m.mutateAsync(WINDOW);
    },
  },
  {
    name: "resolve a healer problem",
    method: "POST",
    path: `/v1/ops/healer/incidents/${INCIDENT}/resolve`,
    confirm: `resolve_heal_incident:${INCIDENT}`,
    useRun: () => {
      const m = useResolveIncident();
      return () => m.mutateAsync(INCIDENT);
    },
  },
  {
    name: "post a status notice",
    method: "POST",
    path: "/v1/ops/healer/status-posts",
    confirm: "post_status",
    useRun: () => {
      const m = usePostStatus();
      return () => m.mutateAsync({ incidentId: null, title: "Calls delayed", component: "calls" });
    },
  },
  {
    name: "decide a KYC review",
    method: "POST",
    path: `/v1/admin/tenants/${TENANT}/kyc/review`,
    confirm: `kyc_review:${TENANT}:reject`,
    useRun: () => {
      const m = useReviewKyc(TENANT);
      return () => m.mutateAsync({ decision: "reject", reason: "Unreadable", pan_checked: false });
    },
  },
  {
    name: "lift a DigiLocker requirement",
    method: "POST",
    path: `/v1/admin/tenants/${TENANT}/kyc/digilocker-requirement`,
    confirm: `clear_digilocker_requirement:${TENANT}`,
    useRun: () => {
      const m = useSetDigiLockerRequirement(TENANT);
      return () => m.mutateAsync({ required: false, reason: null });
    },
  },
  {
    name: "record a number's voice platform handle",
    method: "POST",
    path: `/v1/admin/numbers/tenants/${TENANT}/${NUMBER}/engine-ref`,
    confirm: `set_engine_ref:${TENANT}:${NUMBER}`,
    useRun: () => {
      const m = useSetNumberEngineRef(TENANT);
      return () => m.mutateAsync({ numberId: NUMBER, ref: "pn_1" });
    },
  },
];

function Trigger({ useRun }: { useRun: Case["useRun"] }) {
  const run = useRun();
  return (
    <button type="button" onClick={() => void run().catch(() => undefined)}>
      Run it
    </button>
  );
}

describe("step-up gated operator writes ask for a code and retry", () => {
  it.each(CASES)("$name", async ({ method, path, confirm, useRun }) => {
    let refuse = true;
    const { calls } = renderAdminPage(
      <>
        <StepUpPrompt />
        <Trigger useRun={useRun} />
      </>,
      {
        [`${method} ${path}`]: () => (refuse ? reauthRequired() : {}),
        "POST /v1/auth/admin/step-up": {},
        "POST /v1/auth/admin/step-up/verify": {
          realm: "admin",
          subject_id: "op-1",
          mfa_complete: true,
          email_verified: true,
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Run it" }));
    expect(await screen.findByRole("alertdialog")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /email me a code/i }));
    await waitFor(() => {
      expect(calls.some((call) => call.path === "/v1/auth/admin/step-up")).toBe(true);
    });
    refuse = false;
    fireEvent.change(screen.getByLabelText(/six-digit code/i), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));
    await waitFor(() => {
      expect(calls.filter((call) => call.path === path)).toHaveLength(2);
    });
    const sent = calls.filter((call) => call.path === path);
    expect(sent[1]?.method).toBe(method);
    expect(sent[1]?.headers["X-Confirm-Action"]).toBe(confirm);
  });
});
